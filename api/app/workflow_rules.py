from __future__ import annotations

from datetime import datetime, timezone

ROLE_TRANSITIONS = {
    "operator": {
        "NEW": {"TRIAGED", "ASSIGNED"},
        "TRIAGED": {"ASSIGNED", "IN_PROGRESS"},
        "ASSIGNED": {"IN_PROGRESS"},
        "IN_PROGRESS": {"WAITING_CITIZEN", "RESOLVED"},
    },
    "supervisor": {
        "NEW": {"TRIAGED", "ASSIGNED", "ESCALATED"},
        "TRIAGED": {"ASSIGNED", "IN_PROGRESS", "ESCALATED"},
        "ASSIGNED": {"IN_PROGRESS", "ESCALATED", "RESOLVED"},
        "IN_PROGRESS": {"WAITING_CITIZEN", "RESOLVED", "ESCALATED"},
        "WAITING_CITIZEN": {"IN_PROGRESS", "ESCALATED"},
        "ESCALATED": {"IN_PROGRESS", "RESOLVED", "CLOSED"},
        "RESOLVED": {"CLOSED", "IN_PROGRESS"},
        "CLOSED": {"IN_PROGRESS"},
    },
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def can_transition(role: str, from_state: str, to_state: str) -> bool:
    return to_state in ROLE_TRANSITIONS.get(role, {}).get(from_state, set())


def compute_sla_status(deadline: datetime) -> str:
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    remaining_minutes = int((deadline - utc_now()).total_seconds() // 60)
    if remaining_minutes <= 0:
        return "BREACHED"
    if remaining_minutes <= 60:
        return "AT_RISK"
    return "ON_TRACK"
