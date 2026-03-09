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
    verification_code: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600
    role: str


class CaseSummary(BaseModel):
    case_id: str
    intent: str
    urgency: str
    department: str
    confidence: float
    state: str
    assigned_team: Optional[str] = None
    assigned_user: Optional[str] = None
    sla_deadline_utc: datetime
    updated_at_utc: datetime


class CaseDetail(CaseSummary):
    request_text_ar: str
    request_text_en: str
    policy_rule: str
    created_at_utc: datetime


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
