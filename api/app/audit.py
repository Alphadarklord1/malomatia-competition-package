from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from .models import AuditEvent


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def append_audit_event(
    session: Session,
    *,
    user_id: str,
    role: str,
    action: str,
    result: str,
    timestamp: datetime,
    details: dict[str, Any] | None = None,
    case_id: str | None = None,
) -> AuditEvent:
    last_event = session.exec(select(AuditEvent).order_by(AuditEvent.timestamp_utc.desc())).first()
    prev_hash = last_event.event_hash if last_event else "GENESIS"
    payload = {
        "event_id": str(uuid.uuid4()),
        "timestamp_utc": timestamp.isoformat(),
        "user_id": user_id,
        "role": role,
        "action": action,
        "case_id": case_id,
        "result": result,
        "details": details or {},
        "prev_hash": prev_hash,
    }
    event_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    event = AuditEvent(
        event_id=payload["event_id"],
        case_id=case_id,
        user_id=user_id,
        role=role,
        action=action,
        result=result,
        details_json=json.dumps(details or {}, ensure_ascii=False),
        prev_hash=prev_hash,
        event_hash=event_hash,
        timestamp_utc=timestamp,
    )
    session.add(event)
    return event
