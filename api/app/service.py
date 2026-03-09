from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlmodel import Session, func, select

from .audit import append_audit_event
from .models import AuditEvent, Case, Notification, WorkflowEvent
from .schemas import CaseDetail, CaseExplanation, CaseSummary, NotificationItem, ReviewCase, TimelineEvent
from .security import CurrentUser
from .workflow_rules import can_transition, compute_sla_status, utc_now


def case_to_summary(case: Case) -> CaseSummary:
    return CaseSummary(
        case_id=case.case_id,
        request_text=case.request_text_en,
        intent=case.intent_en,
        urgency=case.urgency_en,
        department=case.department_en,
        confidence=case.confidence,
        state=case.state,
        assigned_team=case.assigned_team,
        assigned_user=case.assigned_user,
        sla_status=compute_sla_status(case.sla_deadline_utc),
        sla_deadline_utc=case.sla_deadline_utc,
        updated_at_utc=case.updated_at_utc,
    )


def case_to_detail(case: Case) -> CaseDetail:
    return CaseDetail(
        case_id=case.case_id,
        request_text_ar=case.request_text_ar,
        request_text_en=case.request_text_en,
        intent_ar=case.intent_ar,
        intent_en=case.intent_en,
        urgency_ar=case.urgency_ar,
        urgency_en=case.urgency_en,
        department_ar=case.department_ar,
        department_en=case.department_en,
        confidence=case.confidence,
        state=case.state,
        assigned_team=case.assigned_team,
        assigned_user=case.assigned_user,
        status_ar=case.status_ar,
        status_en=case.status_en,
        explanation=CaseExplanation(
            reason_ar=case.reason_ar,
            reason_en=case.reason_en,
            detected_keywords_ar=case.detected_keywords_ar,
            detected_keywords_en=case.detected_keywords_en,
            detected_time_ar=case.detected_time_ar,
            detected_time_en=case.detected_time_en,
            policy_rule=case.policy_rule,
        ),
        sla_status=compute_sla_status(case.sla_deadline_utc),
        sla_deadline_utc=case.sla_deadline_utc,
        created_at_utc=case.created_at_utc,
        updated_at_utc=case.updated_at_utc,
    )


def get_case_or_404(session: Session, case_id: str) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return case


def list_cases_filtered(
    session: Session,
    *,
    department: str | None,
    state: str | None,
    urgency: str | None,
    assigned_user: str | None,
    search: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Case], int]:
    filters = []
    if department:
        filters.append(Case.department_en == department)
    if state:
        filters.append(Case.state == state)
    if urgency:
        filters.append(Case.urgency_en == urgency)
    if assigned_user:
        filters.append(Case.assigned_user == assigned_user)
    if search:
        needle = search.strip()
        if needle:
            filters.append(
                (Case.case_id.contains(needle))
                | (Case.request_text_en.contains(needle))
                | (Case.intent_en.contains(needle))
            )

    query = select(Case)
    count_query = select(func.count()).select_from(Case)
    for condition in filters:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = int(session.exec(count_query).one())
    items = session.exec(
        query.order_by(Case.updated_at_utc.desc(), Case.case_id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return items, total


def _add_workflow_event(
    session: Session,
    *,
    case_id: str,
    actor: CurrentUser,
    event_type: str,
    from_state: str | None,
    to_state: str | None,
    reason: str | None,
    meta: dict[str, Any] | None = None,
    timestamp: datetime,
) -> None:
    session.add(
        WorkflowEvent(
            event_id=str(uuid.uuid4()),
            case_id=case_id,
            actor_user_id=actor.user_id,
            actor_role=actor.role,
            event_type=event_type,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            timestamp_utc=timestamp,
            meta_json=json.dumps(meta or {}, ensure_ascii=False),
        )
    )


def approve_case_action(session: Session, case: Case, actor: CurrentUser, reason: str | None) -> Case:
    now = utc_now()
    from_state = case.state
    to_state = from_state
    if case.state == "NEW":
        to_state = "TRIAGED"
        if not can_transition(actor.role, from_state, to_state):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Transition not allowed")
        case.state = to_state
        if case.triaged_at_utc is None:
            case.triaged_at_utc = now
    case.updated_at_utc = now
    session.add(case)
    _add_workflow_event(
        session,
        case_id=case.case_id,
        actor=actor,
        event_type="APPROVE",
        from_state=from_state,
        to_state=to_state,
        reason=reason,
        meta={"updated_fields": ["state", "triaged_at_utc"] if from_state != to_state else ["updated_at_utc"]},
        timestamp=now,
    )
    append_audit_event(
        session,
        user_id=actor.user_id,
        role=actor.role,
        action="approve",
        result="success",
        case_id=case.case_id,
        details={"from_state": from_state, "to_state": to_state, "reason": reason or ""},
        timestamp=now,
    )
    session.commit()
    session.refresh(case)
    return case


def override_case_action(session: Session, case: Case, actor: CurrentUser, reason: str | None) -> Case:
    if actor.role != "supervisor":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Supervisor role required")
    now = utc_now()
    from_state = case.state
    to_state = "ESCALATED"
    if not can_transition(actor.role, from_state, to_state):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Transition not allowed")
    case.state = to_state
    case.assigned_team = "Human Review"
    case.assigned_user = None
    case.updated_at_utc = now
    session.add(case)
    _add_workflow_event(
        session,
        case_id=case.case_id,
        actor=actor,
        event_type="OVERRIDE",
        from_state=from_state,
        to_state=to_state,
        reason=reason,
        meta={"assigned_team": "Human Review"},
        timestamp=now,
    )
    append_audit_event(
        session,
        user_id=actor.user_id,
        role=actor.role,
        action="override",
        result="success",
        case_id=case.case_id,
        details={"from_state": from_state, "to_state": to_state, "reason": reason or ""},
        timestamp=now,
    )
    session.commit()
    session.refresh(case)
    return case


def assign_case_action(
    session: Session,
    case: Case,
    actor: CurrentUser,
    assigned_team: str,
    assigned_user: str | None,
    reason: str | None,
) -> Case:
    if actor.role not in {"operator", "supervisor"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Assignment not allowed")
    now = utc_now()
    from_state = case.state
    to_state = case.state
    if case.state in {"NEW", "TRIAGED"}:
        to_state = "ASSIGNED"
        if not can_transition(actor.role, from_state, to_state):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Transition not allowed")
        case.state = to_state
        if case.assigned_at_utc is None:
            case.assigned_at_utc = now
    case.assigned_team = assigned_team
    case.assigned_user = assigned_user or None
    case.updated_at_utc = now
    session.add(case)
    _add_workflow_event(
        session,
        case_id=case.case_id,
        actor=actor,
        event_type="ASSIGN",
        from_state=from_state,
        to_state=case.state,
        reason=reason,
        meta={"assigned_team": assigned_team, "assigned_user": assigned_user or ""},
        timestamp=now,
    )
    append_audit_event(
        session,
        user_id=actor.user_id,
        role=actor.role,
        action="assign",
        result="success",
        case_id=case.case_id,
        details={
            "from_state": from_state,
            "to_state": case.state,
            "assigned_team": assigned_team,
            "assigned_user": assigned_user or "",
            "reason": reason or "",
        },
        timestamp=now,
    )
    session.commit()
    session.refresh(case)
    return case


def dashboard_summary(session: Session) -> dict[str, Any]:
    cases = session.exec(select(Case)).all()
    open_cases = sum(1 for case in cases if case.state != "CLOSED")
    sla_at_risk = sum(1 for case in cases if compute_sla_status(case.sla_deadline_utc) in {"AT_RISK", "BREACHED"})
    escalated_cases = sum(1 for case in cases if case.state == "ESCALATED")
    override_count = int(
        session.exec(select(func.count()).select_from(WorkflowEvent).where(WorkflowEvent.event_type == "OVERRIDE")).one()
    )
    by_department: dict[str, int] = {}
    for case in cases:
        key = case.assigned_team or case.department_en
        by_department[key] = by_department.get(key, 0) + 1
    return {
        "open_cases": open_cases,
        "sla_at_risk": sla_at_risk,
        "escalated_cases": escalated_cases,
        "override_count": override_count,
        "by_department": [
            {"department": department, "count": count}
            for department, count in sorted(by_department.items())
        ],
    }


def build_timeline(session: Session, case_id: str) -> list[TimelineEvent]:
    workflow_events = session.exec(
        select(WorkflowEvent).where(WorkflowEvent.case_id == case_id).order_by(WorkflowEvent.timestamp_utc.desc())
    ).all()
    audit_events = session.exec(
        select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.timestamp_utc.desc())
    ).all()
    timeline: list[TimelineEvent] = []
    for item in workflow_events:
        timeline.append(
            TimelineEvent(
                source="workflow",
                event_type=item.event_type,
                actor_user_id=item.actor_user_id,
                actor_role=item.actor_role,
                timestamp_utc=item.timestamp_utc,
                from_state=item.from_state,
                to_state=item.to_state,
                reason=item.reason,
                details=json.loads(item.meta_json or "{}"),
            )
        )
    for item in audit_events:
        timeline.append(
            TimelineEvent(
                source="audit",
                event_type=item.action,
                actor_user_id=item.user_id,
                actor_role=item.role,
                timestamp_utc=item.timestamp_utc,
                result=item.result,
                details=json.loads(item.details_json or "{}"),
            )
        )
    timeline.sort(key=lambda event: event.timestamp_utc, reverse=True)
    return timeline


def build_review_summary(session: Session) -> dict[str, list[ReviewCase]]:
    cases = session.exec(select(Case).order_by(Case.updated_at_utc.desc())).all()
    overrides = session.exec(
        select(WorkflowEvent).where(WorkflowEvent.event_type == "OVERRIDE").order_by(WorkflowEvent.timestamp_utc.desc())
    ).all()
    latest_override_by_case: dict[str, datetime] = {}
    for event in overrides:
        if event.case_id not in latest_override_by_case:
            latest_override_by_case[event.case_id] = event.timestamp_utc

    escalated: list[ReviewCase] = []
    low_confidence: list[ReviewCase] = []
    recently_overridden: list[ReviewCase] = []

    for case in cases:
        summary = case_to_summary(case)
        flags: list[str] = []
        latest_override_at = latest_override_by_case.get(case.case_id)
        if case.state == "ESCALATED":
            flags.append("ESCALATED")
            escalated.append(ReviewCase(case=summary, review_flags=flags.copy(), latest_override_at=latest_override_at))
        if case.confidence < 0.75:
            low_confidence.append(
                ReviewCase(case=summary, review_flags=["LOW_CONFIDENCE"], latest_override_at=latest_override_at)
            )
        if latest_override_at is not None:
            recently_overridden.append(
                ReviewCase(case=summary, review_flags=["OVERRIDDEN"], latest_override_at=latest_override_at)
            )

    return {
        "escalated": escalated[:10],
        "low_confidence": low_confidence[:10],
        "recently_overridden": recently_overridden[:10],
    }


def _upsert_notification(
    session: Session,
    *,
    notification_id: str,
    case_id: str,
    category: str,
    severity: str,
    title: str,
    message: str,
    now: datetime,
) -> Notification:
    existing = session.get(Notification, notification_id)
    if existing is None:
        existing = Notification(
            notification_id=notification_id,
            case_id=case_id,
            category=category,
            severity=severity,
            title=title,
            message=message,
            created_at_utc=now,
            updated_at_utc=now,
        )
    else:
        existing.category = category
        existing.severity = severity
        existing.title = title
        existing.message = message
        existing.updated_at_utc = now
    session.add(existing)
    return existing


def sync_notifications(session: Session) -> None:
    now = utc_now()
    cases = session.exec(select(Case)).all()
    for case in cases:
        sla_status = compute_sla_status(case.sla_deadline_utc)
        if sla_status in {"AT_RISK", "BREACHED"}:
            _upsert_notification(
                session,
                notification_id=f"sla:{case.case_id}",
                case_id=case.case_id,
                category="sla",
                severity="high" if sla_status == "BREACHED" else "medium",
                title=f"SLA {sla_status.title()}",
                message=f"Case {case.case_id} is {sla_status.lower().replace('_', ' ')} and needs attention.",
                now=now,
            )
        if case.confidence < 0.75:
            _upsert_notification(
                session,
                notification_id=f"confidence:{case.case_id}",
                case_id=case.case_id,
                category="quality",
                severity="medium",
                title="Low Confidence Routing",
                message=f"Case {case.case_id} is below the 0.75 confidence threshold.",
                now=now,
            )
        if case.state == "ESCALATED":
            _upsert_notification(
                session,
                notification_id=f"escalation:{case.case_id}",
                case_id=case.case_id,
                category="review",
                severity="high",
                title="Escalated for Human Review",
                message=f"Case {case.case_id} is escalated and waiting for supervisor review.",
                now=now,
            )
    session.commit()


def list_notifications(session: Session, *, include_acked: bool) -> list[NotificationItem]:
    sync_notifications(session)
    query = select(Notification).order_by(Notification.updated_at_utc.desc(), Notification.notification_id.asc())
    if not include_acked:
        query = query.where(Notification.ack_at_utc.is_(None))
    items = session.exec(query).all()
    return [
        NotificationItem(
            notification_id=item.notification_id,
            case_id=item.case_id,
            category=item.category,
            severity=item.severity,
            title=item.title,
            message=item.message,
            ack_by_user=item.ack_by_user,
            ack_at_utc=item.ack_at_utc,
            created_at_utc=item.created_at_utc,
            updated_at_utc=item.updated_at_utc,
        )
        for item in items
    ]


def acknowledge_notification(session: Session, notification_id: str, actor: CurrentUser) -> NotificationItem:
    item = session.get(Notification, notification_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    now = utc_now()
    item.ack_by_user = actor.user_id
    item.ack_at_utc = now
    item.updated_at_utc = now
    session.add(item)
    append_audit_event(
        session,
        user_id=actor.user_id,
        role=actor.role,
        action="ack_notification",
        result="success",
        case_id=item.case_id,
        details={"notification_id": notification_id, "category": item.category},
        timestamp=now,
    )
    session.commit()
    session.refresh(item)
    return NotificationItem(
        notification_id=item.notification_id,
        case_id=item.case_id,
        category=item.category,
        severity=item.severity,
        title=item.title,
        message=item.message,
        ack_by_user=item.ack_by_user,
        ack_at_utc=item.ack_at_utc,
        created_at_utc=item.created_at_utc,
        updated_at_utc=item.updated_at_utc,
    )
