from __future__ import annotations

from pathlib import Path

from rag_engine import answer_question, build_index, retrieve

BASE_DIR = Path(__file__).resolve().parents[1]
KB_PATH = BASE_DIR / "domain_knowledge.json"


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
