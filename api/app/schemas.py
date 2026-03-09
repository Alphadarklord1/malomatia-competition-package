from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    name: str
    version: str
    environment: str
    database_mode: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int = 0
    role: Optional[str] = None
    mfa_required: bool = False
    pending_token: Optional[str] = None
    message: Optional[str] = None


class MfaVerifyRequest(BaseModel):
    pending_token: str
    code: str = Field(min_length=6, max_length=6)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    display_name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    enable_mfa: bool = False


class RegisterResponse(BaseModel):
    user_id: str
    status: str
    mfa_secret: Optional[str] = None
    provisioning_uri: Optional[str] = None
    message: str


class UserProfile(BaseModel):
    user_id: str
    display_name: str
    role: str
    auth_provider: str
    status: str
    mfa_enabled: bool


class DashboardSummaryResponse(BaseModel):
    open_cases: int
    sla_at_risk: int
    escalated_cases: int
    override_count: int
    by_department: list[dict[str, Any]]


class CaseSummary(BaseModel):
    case_id: str
    request_text: str
    intent: str
    urgency: str
    department: str
    confidence: float
    state: str
    assigned_team: Optional[str] = None
    assigned_user: Optional[str] = None
    sla_status: str
    sla_deadline_utc: datetime
    updated_at_utc: datetime


class CaseExplanation(BaseModel):
    reason_ar: str
    reason_en: str
    detected_keywords_ar: str
    detected_keywords_en: str
    detected_time_ar: str
    detected_time_en: str
    policy_rule: str


class CaseDetail(BaseModel):
    case_id: str
    request_text_ar: str
    request_text_en: str
    intent_ar: str
    intent_en: str
    urgency_ar: str
    urgency_en: str
    department_ar: str
    department_en: str
    confidence: float
    state: str
    assigned_team: Optional[str] = None
    assigned_user: Optional[str] = None
    status_ar: str
    status_en: str
    explanation: CaseExplanation
    sla_status: str
    sla_deadline_utc: datetime
    created_at_utc: datetime
    updated_at_utc: datetime


class PaginatedCasesResponse(BaseModel):
    items: list[CaseSummary]
    page: int
    page_size: int
    total: int


class CaseActionRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


class CaseAssignmentRequest(BaseModel):
    assigned_team: str = Field(min_length=2, max_length=100)
    assigned_user: Optional[str] = Field(default=None, max_length=100)
    reason: Optional[str] = Field(default=None, max_length=500)


class CaseActionResponse(BaseModel):
    message: str
    case: CaseDetail


class CaseTransitionRequest(BaseModel):
    to_state: str = Field(min_length=2, max_length=50)
    reason: Optional[str] = Field(default=None, max_length=500)


class TimelineEvent(BaseModel):
    source: str
    event_type: str
    actor_user_id: str
    actor_role: str
    timestamp_utc: datetime
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    result: Optional[str] = None
    reason: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)


class TimelineResponse(BaseModel):
    case_id: str
    events: list[TimelineEvent]


class ReviewCase(BaseModel):
    case: CaseSummary
    review_flags: list[str]
    latest_override_at: Optional[datetime] = None


class ReviewSummaryResponse(BaseModel):
    escalated: list[ReviewCase]
    low_confidence: list[ReviewCase]
    recently_overridden: list[ReviewCase]


class NotificationItem(BaseModel):
    notification_id: str
    case_id: Optional[str] = None
    category: str
    severity: str
    title: str
    message: str
    ack_by_user: Optional[str] = None
    ack_at_utc: Optional[datetime] = None
    created_at_utc: datetime
    updated_at_utc: datetime


class NotificationsResponse(BaseModel):
    items: list[NotificationItem]


class UserSummary(BaseModel):
    user_id: str
    display_name: str
    role: str
    status: str
    auth_provider: str
    mfa_enabled: bool
    locked_until_utc: Optional[datetime] = None
    failed_login_attempts: int


class UsersResponse(BaseModel):
    items: list[UserSummary]


class UserCreateRequest(BaseModel):
    user_id: str = Field(min_length=3, max_length=100)
    display_name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="operator")
    status: str = Field(default="active")
    enable_mfa: bool = False


class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    role: Optional[str] = None
    status: Optional[str] = None


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class MfaSetupResponse(BaseModel):
    user_id: str
    mfa_enabled: bool
    mfa_secret: Optional[str] = None
    provisioning_uri: Optional[str] = None


class RagQueryRequest(BaseModel):
    query: str = Field(min_length=3)
    language: str = Field(default="en", pattern="^(ar|en)$")
    top_k: int = Field(default=5, ge=1, le=8)
    department_hint: Optional[str] = None


class RagHit(BaseModel):
    rank: int
    doc_id: str
    chunk_id: str
    title: str
    department: str
    policy_rule: str
    text: str
    base_score: float
    rerank_score: float
    keyword_hits: list[str]
    reasons: list[str]


class RagQueryResponse(BaseModel):
    answer: str
    hits: list[RagHit]
    used_llm: bool
    insufficient_evidence: bool
    policy_blocked: bool
    llm_error: Optional[str] = None


class ApiMessage(BaseModel):
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
