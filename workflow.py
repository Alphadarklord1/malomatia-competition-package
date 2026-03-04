from __future__ import annotations

from typing import Literal


CaseState = Literal[
    "NEW",
    "TRIAGED",
    "ASSIGNED",
    "IN_PROGRESS",
    "WAITING_CITIZEN",
    "ESCALATED",
    "RESOLVED",
    "CLOSED",
]

ALL_STATES: tuple[CaseState, ...] = (
    "NEW",
    "TRIAGED",
    "ASSIGNED",
    "IN_PROGRESS",
    "WAITING_CITIZEN",
    "ESCALATED",
    "RESOLVED",
    "CLOSED",
)

OPERATOR_TRANSITIONS: dict[CaseState, tuple[CaseState, ...]] = {
    "NEW": ("ASSIGNED", "IN_PROGRESS", "TRIAGED"),
    "TRIAGED": ("ASSIGNED", "IN_PROGRESS"),
    "ASSIGNED": ("IN_PROGRESS",),
    "IN_PROGRESS": ("WAITING_CITIZEN", "RESOLVED"),
    "WAITING_CITIZEN": ("IN_PROGRESS",),
    "ESCALATED": (),
    "RESOLVED": (),
    "CLOSED": (),
}

SUPERVISOR_EXTRA_TRANSITIONS: dict[CaseState, tuple[CaseState, ...]] = {
    "NEW": ("ESCALATED",),
    "TRIAGED": ("ESCALATED",),
    "ASSIGNED": ("ESCALATED",),
    "IN_PROGRESS": ("ESCALATED", "RESOLVED"),
    "WAITING_CITIZEN": ("ESCALATED", "IN_PROGRESS"),
    "ESCALATED": ("ASSIGNED", "IN_PROGRESS", "RESOLVED"),
    "RESOLVED": ("CLOSED", "IN_PROGRESS"),
    "CLOSED": ("IN_PROGRESS",),
}


def is_state(value: str) -> bool:
    return value in ALL_STATES


def get_allowed_next_states(role: str, from_state: str) -> list[str]:
    if not is_state(from_state):
        return []

    base = set(OPERATOR_TRANSITIONS.get(from_state, ()))
    if role == "supervisor":
        base.update(SUPERVISOR_EXTRA_TRANSITIONS.get(from_state, ()))
        return sorted(base)
    if role == "operator":
        return sorted(base)
    if role == "auditor":
        return []
    return []


def can_transition(role: str, from_state: str, to_state: str) -> bool:
    if not (is_state(from_state) and is_state(to_state)):
        return False
    if from_state == to_state:
        return True
    return to_state in get_allowed_next_states(role, from_state)
