from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
import uuid

from sqlmodel import Session, select

from .models import AuditEvent, Case, User, WorkflowEvent
from .workflow_rules import utc_now

BASE_DIR = Path(__file__).resolve().parents[2]
EXAMPLE_DATA_PATH = BASE_DIR / "example_data.json"

DEMO_USERS = [
    {
        "user_id": "operator_demo",
        "display_name": "Operator Demo",
        "role": "operator",
        "password_hash": "pbkdf2_sha256$210000$VUcCddM9P1o4Uf0YcEfG2w==$AiQUCfM3YRpWjEUqqw9bRiuat2ESpM8mgJFXeBT7tB4=",
    },
    {
        "user_id": "supervisor_demo",
        "display_name": "Supervisor Demo",
        "role": "supervisor",
        "password_hash": "pbkdf2_sha256$210000$W6aM9+TlmJEAXkzuuSDtZA==$zMxyTmj5Jh9cEwzNJOW2YnqpfBmjjOqJUTnY3M72S7w=",
    },
    {
        "user_id": "auditor_demo",
        "display_name": "Auditor Demo",
        "role": "auditor",
        "password_hash": "pbkdf2_sha256$210000$Ues1cCoN/ob43yR3W+flyw==$C0ZOlDvIM6JnLtUq/7Ne21/DyTfs0s9IV3G4JqOhjIg=",
    },
]


def _deadline_for_urgency(urgency_en: str, created_at):
    if urgency_en.strip().lower() == "urgent":
        return created_at + timedelta(hours=4)
    return created_at + timedelta(hours=24)


def seed_database(session: Session) -> None:
    has_users = session.exec(select(User)).first() is not None
    if not has_users:
        now = utc_now()
        for item in DEMO_USERS:
            session.add(
                User(
                    user_id=item["user_id"],
                    display_name=item["display_name"],
                    auth_provider="local",
                    role=item["role"],
                    status="active",
                    password_hash=item["password_hash"],
                    created_at_utc=now,
                    updated_at_utc=now,
                )
            )

    has_cases = session.exec(select(Case)).first() is not None
    if not has_cases:
        records = json.loads(EXAMPLE_DATA_PATH.read_text(encoding="utf-8"))
        now = utc_now()
        for idx, record in enumerate(records):
            created_at = now - timedelta(minutes=idx * 7)
            deadline = _deadline_for_urgency(str(record["urgency_en"]), created_at)
            session.add(
                Case(
                    case_id=str(record["id"]),
                    request_text_ar=str(record["request_ar"]),
                    request_text_en=str(record["request_en"]),
                    intent_ar=str(record["intent_ar"]),
                    intent_en=str(record["intent_en"]),
                    urgency_ar=str(record["urgency_ar"]),
                    urgency_en=str(record["urgency_en"]),
                    department_ar=str(record["department_ar"]),
                    department_en=str(record["department_en"]),
                    confidence=float(record["confidence"]),
                    reason_ar=str(record["reason_ar"]),
                    reason_en=str(record["reason_en"]),
                    detected_keywords_ar=str(record["detected_keywords_ar"]),
                    detected_keywords_en=str(record["detected_keywords_en"]),
                    detected_time_ar=str(record["detected_time_ar"]),
                    detected_time_en=str(record["detected_time_en"]),
                    policy_rule=str(record["policy_rule"]),
                    status_ar=str(record["status_ar"]),
                    status_en=str(record["status_en"]),
                    state="NEW",
                    assigned_team=None,
                    assigned_user=None,
                    sla_deadline_utc=deadline,
                    created_at_utc=created_at,
                    updated_at_utc=created_at,
                )
            )

    session.commit()


def reset_demo_data(session: Session) -> None:
    for model in (AuditEvent, WorkflowEvent, Case, User):
        for row in session.exec(select(model)).all():
            session.delete(row)
    session.commit()
    seed_database(session)
