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
    mfa_required: bool = Field(default=False)
    mfa_type: str = Field(default="none")
    password_hash: str = Field(default="managed_externally")
    totp_secret_encrypted: Optional[str] = None
    created_at_utc: datetime
    updated_at_utc: datetime


class Case(SQLModel, table=True):
    case_id: str = Field(primary_key=True)
    request_text_ar: str
    request_text_en: str
    intent: str
    urgency: str
    department: str = Field(index=True)
    confidence: float
    policy_rule: str
    state: str = Field(index=True)
    assigned_team: Optional[str] = Field(default=None, index=True)
    assigned_user: Optional[str] = Field(default=None, index=True)
    sla_deadline_utc: datetime = Field(index=True)
    created_at_utc: datetime = Field(index=True)
    updated_at_utc: datetime = Field(index=True)


class AuditEvent(SQLModel, table=True):
    event_id: str = Field(primary_key=True)
    case_id: Optional[str] = Field(default=None, index=True)
    user_id: str = Field(index=True)
    role: str = Field(index=True)
    action: str = Field(index=True)
    result: str = Field(index=True)
    details_json: str
    prev_hash: str
    event_hash: str
    timestamp_utc: datetime = Field(index=True)
