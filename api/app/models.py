from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    user_id: str = Field(primary_key=True)
    display_name: str
    auth_provider: str = Field(default="local", index=True)
    role: str = Field(index=True)
    status: str = Field(default="active", index=True)
    password_hash: str
    created_at_utc: datetime
    updated_at_utc: datetime


class Case(SQLModel, table=True):
    case_id: str = Field(primary_key=True)
    request_text_ar: str
    request_text_en: str
    intent_ar: str
    intent_en: str
    urgency_ar: str
    urgency_en: str
    department_ar: str
    department_en: str = Field(index=True)
    confidence: float
    reason_ar: str
    reason_en: str
    detected_keywords_ar: str
    detected_keywords_en: str
    detected_time_ar: str
    detected_time_en: str
    policy_rule: str
    status_ar: str
    status_en: str
    state: str = Field(index=True)
    assigned_team: Optional[str] = Field(default=None, index=True)
    assigned_user: Optional[str] = Field(default=None, index=True)
    sla_deadline_utc: datetime = Field(index=True)
    created_at_utc: datetime = Field(index=True)
    triaged_at_utc: Optional[datetime] = None
    assigned_at_utc: Optional[datetime] = None
    resolved_at_utc: Optional[datetime] = None
    closed_at_utc: Optional[datetime] = None
    updated_at_utc: datetime = Field(index=True)


class WorkflowEvent(SQLModel, table=True):
    event_id: str = Field(primary_key=True)
    case_id: str = Field(index=True)
    actor_user_id: str = Field(index=True)
    actor_role: str = Field(index=True)
    event_type: str = Field(index=True)
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    reason: Optional[str] = None
    timestamp_utc: datetime = Field(index=True)
    meta_json: str = Field(default="{}")


class AuditEvent(SQLModel, table=True):
    event_id: str = Field(primary_key=True)
    case_id: Optional[str] = Field(default=None, index=True)
    user_id: str = Field(index=True)
    role: str = Field(index=True)
    action: str = Field(index=True)
    result: str = Field(index=True)
    details_json: str = Field(default="{}")
    prev_hash: str
    event_hash: str
    timestamp_utc: datetime = Field(index=True)


class Notification(SQLModel, table=True):
    notification_id: str = Field(primary_key=True)
    case_id: Optional[str] = Field(default=None, index=True)
    category: str = Field(index=True)
    severity: str = Field(index=True)
    title: str
    message: str
    ack_by_user: Optional[str] = Field(default=None, index=True)
    ack_at_utc: Optional[datetime] = None
    created_at_utc: datetime = Field(index=True)
    updated_at_utc: datetime = Field(index=True)
