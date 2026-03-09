from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlmodel import Session

from app.db import get_session
from app.security import CurrentUser, require_roles
from app.service import export_audit_jsonl

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/export", response_class=PlainTextResponse)
def export_audit(
    session: Session = Depends(get_session),
    _: CurrentUser = Depends(require_roles("supervisor", "auditor")),
) -> PlainTextResponse:
    payload = export_audit_jsonl(session)
    return PlainTextResponse(
        payload,
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit-export.jsonl"'},
    )
