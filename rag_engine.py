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
    if not api_key:
        return None, "OPENAI_API_KEY missing"
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


def _openai_answer(
    *,
    api_key: str,
    model: str,
    query: str,
    hits: list[RetrievalHit],
    language: str,
) -> tuple[str | None, str | None]:
    if not api_key:
        return None, "OPENAI_API_KEY missing"
    if not hits:
        return None, "No retrieval hits"

    context = "\n\n".join(
        f"[{h.doc_id}/{h.chunk_id}] {h.title} ({h.policy_rule})\n{h.text}"
        for h in hits[:5]
    )

    if language == "ar":
        system = (
            "أنت مساعد عمليات حكومية. أجب فقط من المقاطع المسترجعة. "
            "إذا كانت المعلومات غير كافية قل ذلك بوضوح. أضف المراجع بصيغة [DOC/CHUNK]."
        )
    else:
        system = (
            "You are a government operations assistant. Answer only from retrieved chunks. "
            "If evidence is insufficient, say so. Add citations as [DOC/CHUNK]."
        )

    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Question:\n{query}\n\nRetrieved Context:\n{context}",
            },
        ],
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
        text = body["choices"][0]["message"]["content"].strip()
        if not text:
            return None, "Empty LLM response"
        return text, None
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        return None, f"LLM_HTTP_{exc.code}: {error_text[:280]}"
    except Exception as exc:  # pragma: no cover - network/runtime dependent
        return None, f"LLM_ERROR: {exc}"


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

    llm_answer: str | None = None
    llm_error: str | None = None
    if openai_api_key:
        llm_answer, llm_error = _openai_answer(
            api_key=openai_api_key,
            model=openai_model,
            query=query,
            hits=hits,
            language=language,
        )

    answer = llm_answer or _fallback_answer(query, hits, language)
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
    }
