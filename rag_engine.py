from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u0600-\u06FF]+")

REQUIRED_DOC_KEYS = {
    "id",
    "title_ar",
    "title_en",
    "department",
    "policy_rule",
    "keywords_ar",
    "keywords_en",
    "text_ar",
    "text_en",
}
MANIFEST_REQUIRED_KEYS = {"last_refresh_utc", "documents"}
DOC_CITATION_RE = re.compile(r"\[[A-Z0-9\-]+/[A-Z0-9\-]+\]")
MIN_EVIDENCE_SCORE = 0.18
DISALLOWED_QUERY_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\b(approve|override|close|delete|reroute|assign|resolve|reveal)\b",
        r"\b(password|secret|token|api key|system prompt|prompt)\b",
        r"\b(execute|run command|change setting|write to database)\b",
        r"\b(كشف البيانات|إظهار البيانات|كلمة المرور|الرمز السري|اعتماد|تجاوز|إغلاق|حذف|تحويل|إسناد)\b",
    ]
]

CAPABILITY_GUIDE = {
    "en": {
        "can": [
            "Answer only from retrieved policy and operations knowledge.",
            "Explain routing, urgency, SLA, privacy, and escalation rules with citations.",
            "Show which chunks and policy rules were used to form the answer.",
        ],
        "cannot": [
            "Approve, override, assign, or change any case state.",
            "Reveal masked PII, secrets, prompts, or hidden system instructions.",
            "Invent policy details or answer out-of-scope questions as if they were grounded facts.",
        ],
    },
    "ar": {
        "can": [
            "الإجابة فقط من سياسات ومعرفة التشغيل المسترجعة.",
            "شرح قواعد التوجيه والأولوية وSLA والخصوصية والتصعيد مع المراجع.",
            "إظهار المقاطع والقواعد التي بُنيت عليها الإجابة.",
        ],
        "cannot": [
            "اعتماد أو تجاوز أو إسناد أو تغيير حالة أي قضية.",
            "كشف البيانات الحساسة أو الأسرار أو التعليمات الداخلية المخفية.",
            "اختلاق سياسات أو تقديم معلومات خارج النطاق باعتبارها حقائق مؤكدة.",
        ],
    },
}


@dataclass(frozen=True)
class RetrievalHit:
    rank: int
    doc_id: str
    chunk_id: str
    title: str
    department: str
    policy_rule: str
    text: str
    base_score: float
    rerank_score: float
    keyword_hits: list[str]
    reasons: list[str]


class RagConfigError(RuntimeError):
    pass


def tokenize(text: str) -> list[str]:
    return [tok.lower() for tok in TOKEN_RE.findall(text or "")]


def baseline_answer(query: str, language: str) -> str:
    lowered = query.strip().lower()
    if not lowered:
        return (
            "اكتب سؤالاً أولاً."
            if language == "ar"
            else "Enter a question first."
        )

    if language == "ar":
        if any(term in lowered for term in ["إقامة", "تنتهي", "تجديد"]):
            return "قد تكون هذه معاملة هجرة أو تجديد إقامة، لكن بدون الرجوع إلى سياسة المؤسسة لا يمكن تأكيد الأولوية أو قاعدة التوجيه."
        if any(term in lowered for term in ["رخصة", "تجارية", "ترخيص"]):
            return "يبدو أنها معاملة ترخيص، لكن النموذج العام لا يحدد القاعدة التشغيلية أو مستوى الأولوية المؤسسي."
        if any(term in lowered for term in ["sla", "مهلة", "عاجل"]):
            return "عادة توجد مهلات مختلفة حسب نوع الحالة، لكن النموذج العام لا يضمن أنه يستخدم اتفاقية مستوى الخدمة الخاصة بالمؤسسة."
        return "هذا يبدو طلب خدمات حكومية، لكن الإجابة العامة قد تكون غير دقيقة لأنها غير مربوطة بسياسات التشغيل الداخلية."

    if any(term in lowered for term in ["residency", "renewal", "expires"]):
        return "This looks like an immigration or renewal issue, but a plain model cannot reliably confirm routing or urgency without the organization policy."
    if any(term in lowered for term in ["license", "licensing", "commercial"]):
        return "This appears to be a licensing matter, but a plain model cannot reliably identify the internal rule or operational priority."
    if any(term in lowered for term in ["sla", "deadline", "urgent"]):
        return "There is likely an SLA target involved, but a plain model cannot guarantee it is using the organization-specific service rule."
    return "This looks like a government service request, but a plain model may answer generically because it is not grounded in the internal policy base."


def capability_guide(language: str) -> dict[str, list[str]]:
    return CAPABILITY_GUIDE["ar" if language == "ar" else "en"]


def validate_api_key_format(api_key: str | None) -> tuple[bool, str | None]:
    value = (api_key or "").strip()
    if not value:
        return False, "OPENAI_API_KEY missing"
    if not value.startswith("sk-") or len(value) < 20:
        return False, "Invalid OpenAI API key format"
    return True, None


def evaluate_query_policy(query: str, language: str) -> tuple[bool, str | None]:
    value = query.strip()
    if not value:
        return False, "اكتب سؤالاً أولاً." if language == "ar" else "Enter a question first."
    for pattern in DISALLOWED_QUERY_PATTERNS:
        if pattern.search(value):
            if language == "ar":
                return False, "هذا المساعد يشرح السياسات فقط ولا ينفذ إجراءات تشغيلية أو يكشف بيانات حساسة."
            return False, "This assistant explains policy only. It cannot execute workflow actions or reveal sensitive data."
    return True, None


def _chunk_tokens(tokens: list[str], chunk_size: int, overlap: int) -> list[list[str]]:
    if chunk_size <= 0:
        chunk_size = 85
    if overlap < 0:
        overlap = 0
    step = max(1, chunk_size - overlap)
    chunks: list[list[str]] = []
    for start in range(0, len(tokens), step):
        part = tokens[start : start + chunk_size]
        if part:
            chunks.append(part)
        if start + chunk_size >= len(tokens):
            break
    return chunks


def _tfidf_vector(counter: Counter[str], idf: dict[str, float], total_tokens: int) -> tuple[dict[str, float], float]:
    if total_tokens <= 0:
        return {}, 0.0
    vector: dict[str, float] = {}
    for token, count in counter.items():
        weight = (count / total_tokens) * idf.get(token, 0.0)
        if weight > 0:
            vector[token] = weight
    norm = math.sqrt(sum(v * v for v in vector.values()))
    return vector, norm


def _dot(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(weight * b.get(token, 0.0) for token, weight in a.items())


def _vec_norm(values: list[float]) -> float:
    return math.sqrt(sum(v * v for v in values))


def _vec_cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    denom = _vec_norm(a) * _vec_norm(b)
    if denom <= 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / denom


def _language_suffix(language: str) -> str:
    return "ar" if language == "ar" else "en"


def _load_docs(data_path: Path) -> list[dict[str, Any]]:
    raw = json.loads(data_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise RagConfigError("domain_knowledge.json must be a non-empty list")
    docs: list[dict[str, Any]] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise RagConfigError(f"Document at index {idx} is not an object")
        missing = REQUIRED_DOC_KEYS - set(item.keys())
        if missing:
            raise RagConfigError(f"Document at index {idx} missing keys: {sorted(missing)}")
        docs.append(item)
    return docs


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RagConfigError("knowledge_manifest.json must be an object")
    missing = MANIFEST_REQUIRED_KEYS - set(raw.keys())
    if missing:
        raise RagConfigError(f"knowledge_manifest.json missing keys: {sorted(missing)}")
    docs = raw.get("documents")
    if not isinstance(docs, list) or not docs:
        raise RagConfigError("knowledge_manifest.json documents must be a non-empty list")
    return raw


@lru_cache(maxsize=8)
def build_index(data_path_str: str, language: str = "ar", chunk_size: int = 85, overlap: int = 18) -> dict[str, Any]:
    data_path = Path(data_path_str)
    docs = _load_docs(data_path)
    suffix = _language_suffix(language)

    chunks: list[dict[str, Any]] = []
    for doc in docs:
        text = str(doc[f"text_{suffix}"])
        tokens = tokenize(text)
        for i, part in enumerate(_chunk_tokens(tokens, chunk_size, overlap), start=1):
            chunks.append(
                {
                    "chunk_id": f"{doc['id']}-C{i}",
                    "doc_id": str(doc["id"]),
                    "title": str(doc[f"title_{suffix}"]),
                    "department": str(doc["department"]),
                    "policy_rule": str(doc["policy_rule"]),
                    "keywords": {str(k).lower() for k in doc[f"keywords_{suffix}"]},
                    "tokens": part,
                    "text": " ".join(part),
                }
            )

    if not chunks:
        raise RagConfigError("No chunks were generated from domain knowledge")

    df: Counter[str] = Counter()
    for chunk in chunks:
        df.update(set(chunk["tokens"]))

    total_chunks = len(chunks)
    idf = {token: math.log((1 + total_chunks) / (1 + freq)) + 1.0 for token, freq in df.items()}

    for chunk in chunks:
        token_counter = Counter(chunk["tokens"])
        vec, norm = _tfidf_vector(token_counter, idf, len(chunk["tokens"]))
        chunk["counter"] = token_counter
        chunk["vector"] = vec
        chunk["norm"] = norm

    return {
        "language": suffix,
        "chunks": chunks,
        "idf": idf,
    }


def _openai_embeddings(
    *,
    api_key: str,
    model: str,
    texts: list[str],
) -> tuple[list[list[float]] | None, str | None]:
    ok, error = validate_api_key_format(api_key)
    if not ok:
        return None, error
    if not texts:
        return None, "No texts for embedding"

    payload = {
        "model": model,
        "input": texts,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/embeddings",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        data = body.get("data")
        if not isinstance(data, list):
            return None, "Invalid embeddings response format"
        vectors: list[list[float]] = []
        for item in data:
            emb = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(emb, list):
                return None, "Invalid embedding vector in response"
            vectors.append([float(v) for v in emb])
        return vectors, None
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        return None, f"EMBED_HTTP_{exc.code}: {error_text[:280]}"
    except Exception as exc:  # pragma: no cover - network/runtime dependent
        return None, f"EMBED_ERROR: {exc}"


def _openai_chat_request(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
) -> tuple[str | None, str | None]:
    ok, error = validate_api_key_format(api_key)
    if not ok:
        return None, error

    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        text = str(body["choices"][0]["message"]["content"]).strip()
        if not text:
            return None, "Empty LLM response"
        return text, None
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        return None, f"LLM_HTTP_{exc.code}: {error_text[:280]}"
    except Exception as exc:  # pragma: no cover - network/runtime dependent
        return None, f"LLM_ERROR: {exc}"


def retrieve(
    *,
    query: str,
    data_path: Path,
    language: str,
    top_k: int = 5,
    fetch_k: int = 12,
    department_hint: str | None = None,
    openai_api_key: str | None = None,
    openai_embedding_model: str = "text-embedding-3-small",
) -> list[RetrievalHit]:
    query = (query or "").strip()
    if not query:
        return []

    index = build_index(str(data_path), language)
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    q_counter = Counter(query_tokens)
    q_vector, q_norm = _tfidf_vector(q_counter, index["idf"], len(query_tokens))
    if q_norm <= 0:
        return []

    ranked: list[dict[str, Any]] = []
    for chunk in index["chunks"]:
        c_norm = float(chunk["norm"])
        if c_norm <= 0:
            continue
        base_score = _dot(q_vector, chunk["vector"]) / (q_norm * c_norm)
        if base_score <= 0:
            continue
        ranked.append({"chunk": chunk, "base_score": base_score})

    ranked.sort(key=lambda item: item["base_score"], reverse=True)
    candidates = ranked[: max(fetch_k, top_k)]

    q_set = set(query_tokens)
    lower_query = query.lower()
    reranked: list[dict[str, Any]] = []
    for item in candidates:
        chunk = item["chunk"]
        base_score = float(item["base_score"])
        reasons: list[str] = [f"base={base_score:.3f}"]

        keyword_hits = sorted(q_set.intersection(chunk["keywords"]))
        keyword_bonus = min(0.20, 0.05 * len(keyword_hits))
        if keyword_bonus > 0:
            reasons.append(f"keyword_bonus={keyword_bonus:.3f}")

        department_bonus = 0.0
        if department_hint and chunk["department"].lower() == department_hint.lower():
            department_bonus = 0.08
            reasons.append("department_match=0.080")

        policy_bonus = 0.0
        policy_rule = str(chunk["policy_rule"])
        if policy_rule and policy_rule.lower() in lower_query:
            policy_bonus = 0.08
            reasons.append("policy_match=0.080")

        rerank_score = base_score + keyword_bonus + department_bonus + policy_bonus
        reranked.append(
            {
                "chunk": chunk,
                "base_score": base_score,
                "rerank_score": rerank_score,
                "keyword_hits": keyword_hits,
                "reasons": reasons,
            }
        )

    # Optional semantic rerank with OpenAI embeddings when API key is present.
    if openai_api_key and reranked:
        embed_texts = [query, *[str(item["chunk"]["text"]) for item in reranked]]
        vectors, embed_err = _openai_embeddings(
            api_key=openai_api_key,
            model=openai_embedding_model,
            texts=embed_texts,
        )
        if vectors and len(vectors) == len(embed_texts):
            q_vec = vectors[0]
            for i, item in enumerate(reranked, start=1):
                sem = max(0.0, _vec_cosine(q_vec, vectors[i]))
                sem_bonus = min(0.35, sem * 0.35)
                item["rerank_score"] += sem_bonus
                item["reasons"].append(f"semantic_bonus={sem_bonus:.3f}")
        elif embed_err:
            for item in reranked:
                item["reasons"].append(embed_err[:120])

    reranked.sort(key=lambda item: item["rerank_score"], reverse=True)

    hits: list[RetrievalHit] = []
    for rank, item in enumerate(reranked[:top_k], start=1):
        chunk = item["chunk"]
        hits.append(
            RetrievalHit(
                rank=rank,
                doc_id=str(chunk["doc_id"]),
                chunk_id=str(chunk["chunk_id"]),
                title=str(chunk["title"]),
                department=str(chunk["department"]),
                policy_rule=str(chunk["policy_rule"]),
                text=str(chunk["text"]),
                base_score=float(item["base_score"]),
                rerank_score=float(item["rerank_score"]),
                keyword_hits=list(item["keyword_hits"]),
                reasons=list(item["reasons"]),
            )
        )
    return hits


def _fallback_answer(query: str, hits: list[RetrievalHit], language: str) -> str:
    if not hits:
        if language == "ar":
            return "لم يتم العثور على مقاطع مناسبة في قاعدة المعرفة. جرّب إعادة صياغة السؤال أو إضافة كلمات أدق."
        return "No relevant knowledge chunks were found. Try rephrasing the question with more specific terms."

    top = hits[:3]
    if language == "ar":
        lines = ["الإجابة المبنية على الاسترجاع:"]
        for h in top:
            lines.append(f"- ({h.policy_rule}) {h.title}: {h.text[:220]}...")
        lines.append("المراجع: " + ", ".join(f"{h.doc_id}/{h.chunk_id}" for h in top))
        return "\n".join(lines)

    lines = ["Grounded answer from retrieved policy chunks:"]
    for h in top:
        lines.append(f"- ({h.policy_rule}) {h.title}: {h.text[:220]}...")
    lines.append("Citations: " + ", ".join(f"{h.doc_id}/{h.chunk_id}" for h in top))
    return "\n".join(lines)


def insufficient_evidence_message(language: str) -> str:
    if language == "ar":
        return "الأدلة المسترجعة غير كافية لتقديم إجابة موثوقة. جرّب سؤالاً أكثر تحديداً أو استخدم كلمات من السياسة المطلوبة."
    return "Retrieved evidence is insufficient for a reliable answer. Try a more specific question or include policy-related terms."


def build_knowledge_manifest(data_path: Path, manifest_path: Path) -> dict[str, Any]:
    docs = _load_docs(data_path)
    manifest = _load_manifest(manifest_path)
    documents = {str(item.get("document_id")): item for item in manifest.get("documents", []) if isinstance(item, dict)}

    ar_index = build_index(str(data_path), "ar")
    en_index = build_index(str(data_path), "en")
    ar_counts = Counter(str(chunk["doc_id"]) for chunk in ar_index["chunks"])
    en_counts = Counter(str(chunk["doc_id"]) for chunk in en_index["chunks"])

    rows: list[dict[str, Any]] = []
    for doc in docs:
        doc_id = str(doc["id"])
        meta = documents.get(doc_id, {})
        rows.append(
            {
                "document_id": doc_id,
                "title_ar": str(meta.get("title_ar") or doc["title_ar"]),
                "title_en": str(meta.get("title_en") or doc["title_en"]),
                "department_scope": str(meta.get("department_scope") or doc["department"]),
                "language": str(meta.get("language") or "ar+en"),
                "version": str(meta.get("version") or "1.0"),
                "updated_timestamp": str(meta.get("updated_timestamp") or manifest.get("last_refresh_utc")),
                "chunk_count": int(ar_counts.get(doc_id, 0) + en_counts.get(doc_id, 0)),
                "policy_rule": str(doc["policy_rule"]),
            }
        )

    return {
        "last_refresh_utc": str(manifest.get("last_refresh_utc")),
        "documents": rows,
    }


def run_rag_evaluation(
    *,
    eval_path: Path,
    data_path: Path,
    language: str = "en",
) -> dict[str, Any]:
    raw = json.loads(eval_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise RagConfigError("rag_eval_set.json must be a non-empty list")

    rows: list[dict[str, Any]] = []
    passed = 0
    for item in raw:
        query = str(item.get("question_ar") if language == "ar" else item.get("question_en"))
        expected_department = str(item.get("expected_department"))
        expected_policy_rule = str(item.get("expected_policy_rule"))
        expected_doc_id = str(item.get("expected_doc_id"))
        result = answer_question(
            query=query,
            data_path=data_path,
            language=language,
            top_k=3,
            department_hint=expected_department or None,
            openai_api_key=None,
        )
        hits = list(result.get("hits", []))
        top_hit = hits[0] if hits else {}
        ok = bool(
            hits
            and str(top_hit.get("department")) == expected_department
            and any(str(h.get("doc_id")) == expected_doc_id for h in hits)
            and any(str(h.get("policy_rule")) == expected_policy_rule for h in hits)
        )
        passed += 1 if ok else 0
        rows.append(
            {
                "query": query,
                "expected_department": expected_department,
                "expected_policy_rule": expected_policy_rule,
                "expected_doc_id": expected_doc_id,
                "top_department": str(top_hit.get("department", "")),
                "top_policy_rule": str(top_hit.get("policy_rule", "")),
                "top_doc_id": str(top_hit.get("doc_id", "")),
                "passed": ok,
            }
        )

    total = len(rows)
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round((passed / total) * 100.0, 1) if total else 0.0,
        "rows": rows,
    }


def _openai_answer(
    *,
    api_key: str,
    model: str,
    query: str,
    hits: list[RetrievalHit],
    language: str,
) -> tuple[str | None, str | None]:
    ok, error = validate_api_key_format(api_key)
    if not ok:
        return None, error
    if not hits:
        return None, "No retrieval hits"

    context = "\n\n".join(
        f"[{h.doc_id}/{h.chunk_id}] {h.title} ({h.policy_rule})\n{h.text}"
        for h in hits[:5]
    )

    if language == "ar":
        system = (
            "أنت مساعد عمليات حكومية مقيّد. "
            "يمكنك فقط شرح السياسات والقرارات التشغيلية اعتماداً على المقاطع المسترجعة. "
            "لا تنفذ إجراءات، لا تكشف بيانات حساسة، لا تخترع سياسات، ولا تستخدم معرفة خارج السياق. "
            "إذا لم تكف الأدلة فاذكر ذلك بوضوح. أضف مراجع بصيغة [DOC/CHUNK] في الجواب."
        )
    else:
        system = (
            "You are a constrained government operations assistant. "
            "You may only explain policy and workflow decisions from retrieved chunks. "
            "Do not execute actions, reveal sensitive data, invent policy, or use outside knowledge as fact. "
            "If evidence is insufficient, say so clearly. Add citations as [DOC/CHUNK] in the answer."
        )
    answer, request_error = _openai_chat_request(
        api_key=api_key,
        model=model,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Question:\n{query}\n\nRetrieved Context:\n{context}",
            },
        ],
        temperature=0.1,
        max_tokens=380,
    )
    if not answer:
        return None, request_error
    if not DOC_CITATION_RE.search(answer):
        return None, "LLM output missing citations; reverted to grounded fallback"
    return answer, None


def test_openai_runtime(
    *,
    api_key: str,
    answer_model: str,
    embedding_model: str,
) -> dict[str, Any]:
    ok, error = validate_api_key_format(api_key)
    if not ok:
        return {
            "ok": False,
            "embedding_ok": False,
            "chat_ok": False,
            "error": error,
        }

    vectors, embed_err = _openai_embeddings(
        api_key=api_key,
        model=embedding_model,
        texts=["policy routing check"],
    )
    embedding_ok = bool(vectors and len(vectors) == 1)
    chat_text, chat_err = _openai_chat_request(
        api_key=api_key,
        model=answer_model,
        messages=[
            {"role": "system", "content": "Reply with OK only."},
            {"role": "user", "content": "OK"},
        ],
        temperature=0.0,
        max_tokens=8,
    )
    chat_ok = bool(chat_text)
    return {
        "ok": embedding_ok and chat_ok,
        "embedding_ok": embedding_ok,
        "chat_ok": chat_ok,
        "embedding_error": embed_err,
        "chat_error": chat_err,
    }


def answer_question(
    *,
    query: str,
    data_path: Path,
    language: str,
    top_k: int,
    department_hint: str | None,
    openai_api_key: str | None,
    openai_model: str = "gpt-4o-mini",
    openai_embedding_model: str = "text-embedding-3-small",
) -> dict[str, Any]:
    allowed, policy_message = evaluate_query_policy(query, language)
    if not allowed:
        return {
            "answer": policy_message,
            "hits": [],
            "used_llm": False,
            "llm_error": None,
            "policy_blocked": True,
        }

    hits = retrieve(
        query=query,
        data_path=data_path,
        language=language,
        top_k=top_k,
        fetch_k=max(12, top_k * 2),
        department_hint=department_hint,
        openai_api_key=openai_api_key,
        openai_embedding_model=openai_embedding_model,
    )

    top_score = float(hits[0].rerank_score) if hits else 0.0
    insufficient_evidence = (not hits) or top_score < MIN_EVIDENCE_SCORE

    llm_answer: str | None = None
    llm_error: str | None = None
    if openai_api_key and not insufficient_evidence:
        llm_answer, llm_error = _openai_answer(
            api_key=openai_api_key,
            model=openai_model,
            query=query,
            hits=hits,
            language=language,
        )

    answer = insufficient_evidence_message(language) if insufficient_evidence else (llm_answer or _fallback_answer(query, hits, language))
    return {
        "answer": answer,
        "hits": [
            {
                "rank": h.rank,
                "doc_id": h.doc_id,
                "chunk_id": h.chunk_id,
                "title": h.title,
                "department": h.department,
                "policy_rule": h.policy_rule,
                "text": h.text,
                "base_score": round(h.base_score, 4),
                "rerank_score": round(h.rerank_score, 4),
                "keyword_hits": h.keyword_hits,
                "reasons": h.reasons,
            }
            for h in hits
        ],
        "used_llm": bool(llm_answer),
        "llm_error": llm_error,
        "policy_blocked": False,
        "insufficient_evidence": insufficient_evidence,
    }
