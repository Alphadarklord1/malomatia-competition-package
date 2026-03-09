from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.schemas import ReviewSummaryResponse
from app.security import CurrentUser, get_current_user
from app.service import build_review_summary

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/summary", response_model=ReviewSummaryResponse)
def get_review_summary(
    session: Session = Depends(get_session),
    _: CurrentUser = Depends(get_current_user),
) -> ReviewSummaryResponse:
    return ReviewSummaryResponse(**build_review_summary(session))
