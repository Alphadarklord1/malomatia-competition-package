from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from app.schemas import CaseDetail, CaseSummary

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=list[CaseSummary])
def list_cases() -> list[CaseSummary]:
    now = datetime.now(timezone.utc)
    return [
        CaseSummary(
            case_id="CASE-001",
            intent="Residency Renewal",
            urgency="Urgent",
            department="Immigration",
            confidence=0.82,
            state="ESCALATED",
            assigned_team="Human Review",
            assigned_user=None,
            sla_deadline_utc=now,
            updated_at_utc=now,
        )
    ]


@router.get("/{case_id}", response_model=CaseDetail)
def get_case(case_id: str) -> CaseDetail:
    now = datetime.now(timezone.utc)
    return CaseDetail(
        case_id=case_id,
        request_text_ar="اقامتي تنتهي غداً وأحتاج تجديداً عاجلاً",
        request_text_en="My residency expires tomorrow and I need urgent renewal",
        intent="Residency Renewal",
        urgency="Urgent",
        department="Immigration",
        confidence=0.82,
        state="ESCALATED",
        assigned_team="Human Review",
        assigned_user=None,
        policy_rule="PR-17",
        sla_deadline_utc=now,
        created_at_utc=now,
        updated_at_utc=now,
    )
