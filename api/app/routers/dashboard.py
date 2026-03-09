from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.schemas import DashboardSummaryResponse
from app.security import get_current_user, CurrentUser
from app.service import dashboard_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    session: Session = Depends(get_session),
    _: CurrentUser = Depends(get_current_user),
) -> DashboardSummaryResponse:
    return DashboardSummaryResponse(**dashboard_summary(session))
