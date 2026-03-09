from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.db import get_session
from app.schemas import CaseActionRequest, CaseActionResponse, CaseDetail, PaginatedCasesResponse, TimelineResponse
from app.security import CurrentUser, get_current_user, require_roles
from app.service import (
    approve_case_action,
    build_timeline,
    case_to_detail,
    case_to_summary,
    get_case_or_404,
    list_cases_filtered,
    override_case_action,
)

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=PaginatedCasesResponse)
def list_cases(
    department: str | None = None,
    state: str | None = None,
    urgency: str | None = None,
    assigned_user: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    session: Session = Depends(get_session),
    _: CurrentUser = Depends(get_current_user),
) -> PaginatedCasesResponse:
    items, total = list_cases_filtered(
        session,
        department=department,
        state=state,
        urgency=urgency,
        assigned_user=assigned_user,
        page=page,
        page_size=page_size,
    )
    return PaginatedCasesResponse(
        items=[case_to_summary(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{case_id}", response_model=CaseDetail)
def get_case_detail(
    case_id: str,
    session: Session = Depends(get_session),
    _: CurrentUser = Depends(get_current_user),
) -> CaseDetail:
    return case_to_detail(get_case_or_404(session, case_id))


@router.post("/{case_id}/approve", response_model=CaseActionResponse)
def approve_case(
    case_id: str,
    payload: CaseActionRequest,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(require_roles("operator", "supervisor")),
) -> CaseActionResponse:
    case = approve_case_action(session, get_case_or_404(session, case_id), current_user, payload.reason)
    return CaseActionResponse(message="Case approved", case=case_to_detail(case))


@router.post("/{case_id}/override", response_model=CaseActionResponse)
def override_case(
    case_id: str,
    payload: CaseActionRequest,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(require_roles("supervisor")),
) -> CaseActionResponse:
    case = override_case_action(session, get_case_or_404(session, case_id), current_user, payload.reason)
    return CaseActionResponse(message="Case overridden to Human Review", case=case_to_detail(case))


@router.get("/{case_id}/timeline", response_model=TimelineResponse)
def get_case_timeline(
    case_id: str,
    session: Session = Depends(get_session),
    _: CurrentUser = Depends(get_current_user),
) -> TimelineResponse:
    _ = get_case_or_404(session, case_id)
    return TimelineResponse(case_id=case_id, events=build_timeline(session, case_id))
