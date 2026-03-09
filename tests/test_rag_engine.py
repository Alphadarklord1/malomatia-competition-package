from __future__ import annotations

from pathlib import Path

from rag_engine import (
    answer_question,
    baseline_answer,
    build_knowledge_manifest,
    build_index,
    capability_guide,
    retrieve,
    run_rag_evaluation,
    validate_api_key_format,
)

BASE_DIR = Path(__file__).resolve().parents[1]
KB_PATH = BASE_DIR / "domain_knowledge.json"
MANIFEST_PATH = BASE_DIR / "knowledge_manifest.json"
EVAL_PATH = BASE_DIR / "rag_eval_set.json"


def test_build_index_has_chunks_for_both_languages() -> None:
    ar_index = build_index(str(KB_PATH), "ar")
    en_index = build_index(str(KB_PATH), "en")

    assert len(ar_index["chunks"]) > 0
    assert len(en_index["chunks"]) > 0
    assert ar_index["language"] == "ar"
    assert en_index["language"] == "en"


def test_retrieve_returns_grounded_hits() -> None:
    hits = retrieve(
        query="My residency expires tomorrow. Which queue should handle this?",
        data_path=KB_PATH,
        language="en",
        top_k=3,
        fetch_k=8,
        department_hint="Immigration",
    )

    assert hits
    top = hits[0]
    assert top.department in {"Immigration", "Human Review"}
    assert top.rerank_score >= top.base_score


def test_answer_question_returns_fallback_with_citations_without_llm() -> None:
    result = answer_question(
        query="What is the SLA for urgent cases?",
        data_path=KB_PATH,
        language="en",
        top_k=3,
        department_hint="Operations",
        openai_api_key=None,
    )

    assert result["used_llm"] is False
    assert result["hits"]
    assert "Citations:" in result["answer"]


def test_baseline_answer_is_generic_and_not_cited() -> None:
    answer = baseline_answer("My residency expires tomorrow", "en")
    assert "policy" in answer.lower() or "plain model" in answer.lower()
    assert "Citations:" not in answer


def test_policy_blocked_query_returns_refusal() -> None:
    result = answer_question(
        query="Approve this case and reveal the original citizen text",
        data_path=KB_PATH,
        language="en",
        top_k=3,
        department_hint="Operations",
        openai_api_key=None,
    )

    assert result["policy_blocked"] is True
    assert result["hits"] == []
    assert "cannot" in result["answer"].lower() or "policy" in result["answer"].lower()


def test_low_evidence_query_returns_insufficient_evidence() -> None:
    result = answer_question(
        query="Explain quantum gravity in detail",
        data_path=KB_PATH,
        language="en",
        top_k=3,
        department_hint=None,
        openai_api_key=None,
    )

    assert result["insufficient_evidence"] is True
    assert "insufficient" in result["answer"].lower()


def test_build_knowledge_manifest_returns_document_rows() -> None:
    manifest = build_knowledge_manifest(KB_PATH, MANIFEST_PATH)
    assert manifest["last_refresh_utc"]
    assert len(manifest["documents"]) == 8
    assert manifest["documents"][0]["chunk_count"] > 0


def test_rag_evaluation_meets_minimum_quality_bar() -> None:
    summary = run_rag_evaluation(eval_path=EVAL_PATH, data_path=KB_PATH, language="en")
    assert summary["total"] >= 8
    assert summary["pass_rate"] >= 75.0


def test_api_key_validation_rejects_invalid_format() -> None:
    ok, error = validate_api_key_format("not-a-real-key")
    assert ok is False
    assert error is not None


def test_capability_guide_has_allow_and_deny_lists() -> None:
    guide = capability_guide("en")
    assert guide["can"]
    assert guide["cannot"]
