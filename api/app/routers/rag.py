from __future__ import annotations

from pathlib import Path
import sys

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from app.audit import append_audit_event
from app.config import get_settings
from app.db import get_session
from app.rate_limit import rate_limiter
from app.schemas import RagHit, RagQueryRequest, RagQueryResponse
from app.security import CurrentUser, get_current_user
from app.workflow_rules import utc_now

router = APIRouter(prefix="/rag", tags=["rag"])
BASE_DIR = Path(__file__).resolve().parents[3]
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from rag_engine import answer_question

DOMAIN_KB_PATH = BASE_DIR / "domain_knowledge.json"


@router.post("/query", response_model=RagQueryResponse)
def query_knowledge(
    payload: RagQueryRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> RagQueryResponse:
    rate_key = f"{current_user.user_id}:{request.client.host if request.client else 'unknown'}"
    if not rate_limiter.allow(rate_key):
        append_audit_event(
            session,
            user_id=current_user.user_id,
            role=current_user.role,
            action="rag_query",
            result="denied",
            details={"reason": "rate_limited"},
            timestamp=utc_now(),
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="RAG query rate limit exceeded")

    settings = get_settings()
    result = answer_question(
        query=payload.query,
        data_path=DOMAIN_KB_PATH,
        language=payload.language,
        top_k=payload.top_k,
        department_hint=payload.department_hint,
        openai_api_key=settings.openai_api_key or None,
        openai_model=settings.openai_model,
        openai_embedding_model=settings.openai_embedding_model,
    )
    append_audit_event(
        session,
        user_id=current_user.user_id,
        role=current_user.role,
        action="rag_query",
        result="success",
        details={
            "used_llm": result["used_llm"],
            "hits": len(result["hits"]),
            "insufficient_evidence": result["insufficient_evidence"],
        },
        timestamp=utc_now(),
    )
    session.commit()
    return RagQueryResponse(
        answer=result["answer"],
        hits=[RagHit(**hit) for hit in result["hits"]],
        used_llm=result["used_llm"],
        insufficient_evidence=result["insufficient_evidence"],
        policy_blocked=result["policy_blocked"],
        llm_error=result.get("llm_error"),
    )
