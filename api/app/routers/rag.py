from __future__ import annotations

from pathlib import Path
import sys

from fastapi import APIRouter

from app.config import get_settings
from app.schemas import RagHit, RagQueryRequest, RagQueryResponse

router = APIRouter(prefix="/rag", tags=["rag"])
BASE_DIR = Path(__file__).resolve().parents[3]
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from rag_engine import answer_question

DOMAIN_KB_PATH = BASE_DIR / "domain_knowledge.json"


@router.post("/query", response_model=RagQueryResponse)
def query_knowledge(payload: RagQueryRequest) -> RagQueryResponse:
    settings = get_settings()
    result = answer_question(
        query=payload.query,
        data_path=DOMAIN_KB_PATH,
        language=payload.language,
        top_k=payload.top_k,
        department_hint=payload.department_hint,
        openai_api_key=None,
        openai_model=settings.openai_model,
        openai_embedding_model=settings.openai_embedding_model,
    )
    return RagQueryResponse(
        answer=result["answer"],
        hits=[RagHit(**hit) for hit in result["hits"]],
        used_llm=result["used_llm"],
        insufficient_evidence=result["insufficient_evidence"],
        policy_blocked=result["policy_blocked"],
        llm_error=result.get("llm_error"),
    )
