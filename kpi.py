from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from storage import compute_sla_state, parse_utc_iso


def _avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _to_minutes(start_iso: str, end_iso: str) -> float:
    start = parse_utc_iso(start_iso)
    end = parse_utc_iso(end_iso)
    return max(0.0, (end - start).total_seconds() / 60.0)


def compute_operational_kpis(
    cases: list[dict[str, Any]], audit_events: list[dict[str, Any]]
) -> dict[str, float]:
    triage_minutes: list[float] = []
    assignment_minutes: list[float] = []

    breached = 0
    total_cases = len(cases)
    human_review_cases = 0

    for case in cases:
        created = case.get("created_at_utc")
        triaged = case.get("triaged_at_utc")
        assigned = case.get("assigned_at_utc")
        if created and triaged:
            triage_minutes.append(_to_minutes(created, triaged))
        if created and assigned:
            assignment_minutes.append(_to_minutes(created, assigned))

        sla = compute_sla_state(case)
        if sla["status"] == "BREACHED":
            breached += 1
        if case.get("assigned_team") == "Human Review" or case.get("state") == "ESCALATED":
            human_review_cases += 1

    approve_count = 0
    override_count = 0
    for event in audit_events:
        action = str(event.get("action", "")).lower()
        result = str(event.get("result", "")).lower()
        if result != "success":
            continue
        if action == "approve":
            approve_count += 1
        elif action == "override":
            override_count += 1

    denom = approve_count + override_count
    override_rate = (override_count / denom * 100.0) if denom else 0.0
    breached_pct = (breached / total_cases * 100.0) if total_cases else 0.0

    return {
        "avg_time_to_triage_minutes": _avg(triage_minutes),
        "avg_time_to_first_assignment_minutes": _avg(assignment_minutes),
        "sla_breached_pct": breached_pct,
        "override_rate_pct": override_rate,
        "human_review_volume": float(human_review_cases),
    }
