from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import struct
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from itertools import chain
from pathlib import Path
from typing import Any, Iterator

import streamlit as st

from kpi import compute_operational_kpis
from rag_engine import (
    RagConfigError,
    answer_question,
    baseline_answer,
    build_knowledge_manifest,
    build_index,
    capability_guide,
    run_rag_evaluation,
    test_openai_runtime,
    validate_api_key_format,
)
from storage import (
    CURRENT_SCHEMA_VERSION,
    ack_notification,
    approve_case,
    assign_case,
    bootstrap_auth_users,
    compute_sla_state,
    connect_db,
    create_local_user,
    set_local_totp_requirement,
    set_user_role,
    set_user_status,
    ensure_schema,
    export_cases_csv_rows,
    get_case,
    get_user,
    list_case_workflow_events,
    list_cases,
    list_low_confidence,
    list_notifications,
    list_pending_escalations,
    list_recent_overrides,
    list_saved_views,
    list_users,
    list_workflow_events,
    override_case,
    parse_utc_iso,
    record_case_select,
    record_login_failure,
    record_login_success,
    reset_local_user_password,
    seed_cases_if_empty,
    to_utc_iso,
    transition_case_state,
    upsert_external_user,
    upsert_notification,
    upsert_saved_view,
    delete_saved_view,
    utc_now,
)
from workflow import ALL_STATES, get_allowed_next_states


BASE_DIR = Path(__file__).parent
DATA_PATH = BASE_DIR / "example_data.json"
THEME_PATH = BASE_DIR / "theme.css"
SCHEMA_PATH = BASE_DIR / "schema.sql"
DB_PATH = BASE_DIR / "triage.db"
DOMAIN_KB_PATH = BASE_DIR / "domain_knowledge.json"
KNOWLEDGE_MANIFEST_PATH = BASE_DIR / "knowledge_manifest.json"
RAG_EVAL_PATH = BASE_DIR / "rag_eval_set.json"
AUDIT_LOG_PATH = BASE_DIR / "audit.log.jsonl"
AUDIT_ARCHIVE_PATH = BASE_DIR / "audit.archive.jsonl"
FEEDBACK_LOG_PATH = BASE_DIR / "feedback.log.jsonl"
AUTH_SCHEMA_VERSION = 7
APP_VERSION = "1.0.0"
RELEASE_STAGE = "final"
LOGIN_LOCKOUT_AFTER = 5
LOGIN_LOCKOUT_MINUTES = 15

ROLE_PERMISSIONS = {
    "operator": {"view", "select", "approve", "assign", "transition"},
    "supervisor": {
        "view",
        "select",
        "approve",
        "assign",
        "transition",
        "override",
        "settings_write",
        "audit_export",
        "review_actions",
        "reveal_pii",
    },
    "auditor": {"view", "select", "audit_export"},
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+|00)?\d[\d\s\-]{7,}\d")
QID_RE = re.compile(r"\b\d{11}\b")


def as_plain_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return {str(k): v for k, v in obj.items()}
    if hasattr(obj, "items"):
        return {str(k): v for k, v in obj.items()}
    return {}


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def ensure_session_defaults() -> None:
    defaults: dict[str, Any] = {
        "ui_language_mode": "ar",
        "ui_nav": "dashboard",
        "ui_sidebar_contrast": True,
        "ui_compact_mode": False,
        "ui_confidence_precision": 2,
        "ui_default_queue": "all",
        "ui_search_query": "",
        "ui_page_size": 10,
        "ui_page_index": 0,
        "ui_sla_filter": "all",
        "ui_urgency_filter": "all",
        "ui_assigned_user_filter": "all",
        "ui_state_filter": "ALL",
        "ui_queue_scope": "ALL",
        "ui_selected_case_ids": set(),
        "rag_query": "",
        "rag_top_k": 5,
        "rag_department_hint": "AUTO",
        "rag_last_result": None,
        "rag_query_timestamps": [],
        "ai_runtime_api_key": "",
        "ai_runtime_model": "gpt-4o-mini",
        "ai_runtime_embedding_model": "text-embedding-3-small",
        "ai_runtime_test_result": None,
        "security_session_idle_minutes": 15,
        "security_session_max_hours": 8,
        "security_audit_retention_days": 90,
        "security_privacy_masking_enabled": True,
        "security_public_signup_enabled": False,
        "security_signup_requires_approval": True,
        "revealed_case_ids": set(),
        "auth_user_id": None,
        "auth_display_name": None,
        "auth_provider": None,
        "auth_role": None,
        "auth_login_at": None,
        "auth_last_activity_at": None,
        "pending_mfa_user_id": None,
        "selected_case_id": None,
        "ui_loaded_default_view_for_user": "",
        "auth_schema_version": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def load_auth_users() -> dict[str, dict[str, str]]:
    raw_users = as_plain_dict(st.secrets.get("auth_users", {}))
    users: dict[str, dict[str, str]] = {}
    for username, raw_payload in raw_users.items():
        payload = as_plain_dict(raw_payload)
        role = str(payload.get("role", "")).strip().lower()
        password_hash = str(payload.get("password_hash", "")).strip()
        display_name = str(payload.get("display_name", "")).strip() or str(username).strip().replace("_", " ").title()
        status = str(payload.get("status", "active")).strip().lower() or "active"
        totp_secret = str(payload.get("totp_secret", "")).strip()
        if role not in ROLE_PERMISSIONS or not password_hash:
            continue
        users[str(username).strip()] = {
            "role": role,
            "password_hash": password_hash,
            "display_name": display_name,
            "status": status,
            "totp_secret": totp_secret,
        }
    return users


def get_audit_signing_salt() -> str:
    return str(st.secrets.get("audit_signing_salt", ""))


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith("pbkdf2_sha256$"):
        parts = stored_hash.split("$", 3)
        if len(parts) != 4:
            return False
        _, iter_str, salt_b64, digest_b64 = parts
        try:
            iterations = int(iter_str)
            salt = base64.b64decode(salt_b64.encode("utf-8"))
            expected = base64.b64decode(digest_b64.encode("utf-8"))
        except Exception:
            return False
        derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(derived, expected)

    return False


def hash_password_pbkdf2(password: str, iterations: int = 210000) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256$%s$%s$%s" % (
        iterations,
        base64.b64encode(salt).decode("utf-8"),
        base64.b64encode(digest).decode("utf-8"),
    )


def generate_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("utf-8")


def _normalize_totp_secret(secret: str) -> str:
    return "".join(secret.strip().split()).upper()


def _generate_totp_code(secret: str, for_time: datetime, digits: int = 6, period_seconds: int = 30) -> str:
    normalized_secret = _normalize_totp_secret(secret)
    key = base64.b32decode(normalized_secret, casefold=True)
    counter = int(for_time.timestamp()) // period_seconds
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10**digits)).zfill(digits)


def verify_totp_code(secret: str, code: str, window: int = 1) -> bool:
    normalized = re.sub(r"\D", "", code or "")
    if len(normalized) != 6:
        return False
    now = utc_now()
    for delta in range(-window, window + 1):
        candidate_time = now + timedelta(seconds=delta * 30)
        if hmac.compare_digest(_generate_totp_code(secret, candidate_time), normalized):
            return True
    return False


def get_oidc_providers() -> list[str]:
    auth_section = as_plain_dict(st.secrets.get("auth", {}))
    excluded = {"redirect_uri", "cookie_secret"}
    providers = [str(key) for key in auth_section.keys() if str(key) not in excluded]
    return sorted(providers)


def normalize_auth_provider(provider_value: str) -> str:
    raw = provider_value.strip().lower()
    if not raw:
        return "oidc"
    if "google" in raw:
        return "google"
    if "microsoft" in raw or "microsoftonline" in raw or "live.com" in raw:
        return "microsoft"
    return raw


def resolve_oidc_role(user_email: str) -> str:
    oidc_roles = as_plain_dict(st.secrets.get("oidc_roles", {}))
    user_email = user_email.strip().lower()
    supervisors = {str(v).strip().lower() for v in oidc_roles.get("supervisors", [])}
    auditors = {str(v).strip().lower() for v in oidc_roles.get("auditors", [])}
    if user_email in supervisors:
        return "supervisor"
    if user_email in auditors:
        return "auditor"
    return "operator"


def auth_status_snapshot(conn_obj: Any) -> dict[str, Any]:
    providers = get_oidc_providers()
    users = list_users(conn_obj)
    local_users = [u for u in users if str(u.get("auth_provider", "local")) == "local"]
    local_mfa_enabled = sum(1 for u in local_users if int(u.get("mfa_required", 0)) == 1)
    return {
        "oidc_enabled": bool(providers),
        "providers": providers,
        "local_user_count": len(local_users),
        "local_mfa_enabled": local_mfa_enabled,
        "current_provider": str(st.session_state.get("auth_provider") or "local"),
    }


def has_permission(permission: str) -> bool:
    role = st.session_state.get("auth_role")
    if not role:
        return False
    return permission in ROLE_PERMISSIONS.get(role, set())


def bi(ar: str, en: str, arabic_default: bool) -> str:
    return ar if arabic_default else en


def mask_pii(text: str) -> str:
    masked = EMAIL_RE.sub("[EMAIL_REDACTED]", text)
    masked = QID_RE.sub("[QID_REDACTED]", masked)
    masked = PHONE_RE.sub("[PHONE_REDACTED]", masked)
    return masked


def maybe_mask(text: str, case_id: str) -> str:
    if not st.session_state.get("security_privacy_masking_enabled", True):
        return text
    revealed = st.session_state.get("revealed_case_ids", set())
    if case_id in revealed:
        return text
    return mask_pii(text)


def field(case: dict[str, Any], stem: str, arabic_default: bool) -> str:
    lang = "ar" if arabic_default else "en"
    value = str(case[f"{stem}_{lang}"])
    if stem in {"request_text", "reason", "detected_keywords", "detected_time"}:
        return maybe_mask(value, str(case["case_id"]))
    return value


def load_theme(direction: str, high_contrast_sidebar: bool, compact_mode: bool) -> str:
    css = THEME_PATH.read_text(encoding="utf-8")
    sidebar_text = "#F4F7FC" if high_contrast_sidebar else "#CFD6DE"
    sidebar_heading = "#FFFFFF" if high_contrast_sidebar else "#E2E7ED"
    css += f"""
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {{
      color: {sidebar_heading} !important;
      opacity: 1 !important;
    }}
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] div {{
      color: {sidebar_text} !important;
      opacity: 1 !important;
    }}
    """

    if direction == "rtl":
        css += """
        html, body, [data-testid="stAppViewContainer"] { direction: rtl; }
        [data-testid="stSidebar"] * { text-align: right; }
        """
    else:
        css += """
        html, body, [data-testid="stAppViewContainer"] { direction: ltr; }
        [data-testid="stSidebar"] * { text-align: left; }
        """

    if compact_mode:
        css += """
        .metric-card { padding: 8px 10px !important; }
        .triage-card { padding: 10px !important; }
        .panel { padding: 10px !important; }
        .trace-row { padding: 7px 0 !important; }
        """
    return css


def icon_svg(name: str) -> str:
    icons = {
        "clock": """<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M12 7v5l3 2"></path></svg>""",
        "building": """<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="3" width="16" height="18" rx="1"></rect><path d="M8 7h1M11.5 7h1M15 7h1M8 11h1M11.5 11h1M15 11h1M8 15h1M11.5 15h1M15 15h1M11 21v-3h2v3"></path></svg>""",
        "brain": """<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 4a3 3 0 0 0-3 3v10a3 3 0 0 0 3 3"></path><path d="M15 4a3 3 0 0 1 3 3v10a3 3 0 0 1-3 3"></path><path d="M9 8a3 3 0 0 1 0-6M15 8a3 3 0 0 0 0-6M9 12a3 3 0 0 0 0 6M15 12a3 3 0 0 1 0 6"></path></svg>""",
    }
    return icons[name]


def badge_html(text: str, kind: str) -> str:
    return f'<span class="badge badge-{kind}">{text}</span>'


def iter_jsonl_lines(path: Path) -> Iterator[str]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as file_obj:
        for raw_line in file_obj:
            line = raw_line.strip()
            if line:
                yield line


def read_audit_lines(limit: int | None = None) -> list[str]:
    if limit is None:
        return list(iter_jsonl_lines(AUDIT_LOG_PATH))
    return list(deque(iter_jsonl_lines(AUDIT_LOG_PATH), maxlen=max(0, limit)))


def read_audit_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in iter_jsonl_lines(AUDIT_LOG_PATH):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def compute_event_hash(payload: dict[str, Any], signing_salt: str) -> str:
    material = canonical_json(payload)
    if signing_salt:
        material = f"{material}|{signing_salt}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def get_last_event_hash() -> str:
    last_hash = "GENESIS"
    for line in iter_jsonl_lines(AUDIT_LOG_PATH):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_hash = str(obj.get("event_hash", "")).strip()
        if event_hash:
            last_hash = event_hash
    return last_hash


def append_audit_event(
    action: str,
    result: str,
    details: dict[str, Any] | None = None,
    case_id: str | None = None,
    actor_user_id: str | None = None,
    actor_role: str | None = None,
) -> None:
    user_id = actor_user_id or st.session_state.get("auth_user_id") or "anonymous"
    role = actor_role or st.session_state.get("auth_role") or "unauthenticated"
    timestamp = to_utc_iso(utc_now())
    prev_hash = get_last_event_hash()

    event_core = {
        "event_id": str(uuid.uuid4()),
        "timestamp_utc": timestamp,
        "user_id": user_id,
        "role": role,
        "action": action,
        "case_id": case_id,
        "result": result,
        "details": details or {},
        "prev_hash": prev_hash,
    }
    event_hash = compute_event_hash(event_core, get_audit_signing_salt())
    event = {**event_core, "event_hash": event_hash}

    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def archive_old_audit_events(retention_days: int) -> None:
    if retention_days <= 0 or not AUDIT_LOG_PATH.exists():
        return

    cutoff = utc_now() - timedelta(days=retention_days)
    old_lines: list[str] = []
    keep_lines: list[str] = []

    for line in iter_jsonl_lines(AUDIT_LOG_PATH):
        try:
            event = json.loads(line)
            ts = parse_utc_iso(str(event.get("timestamp_utc", "")))
        except Exception:
            keep_lines.append(line)
            continue

        if ts < cutoff:
            old_lines.append(line)
        else:
            keep_lines.append(line)

    if old_lines:
        with AUDIT_ARCHIVE_PATH.open("a", encoding="utf-8") as archive_file:
            for line in old_lines:
                archive_file.write(line + "\n")
        AUDIT_LOG_PATH.write_text("\n".join(keep_lines) + ("\n" if keep_lines else ""), encoding="utf-8")


def validate_audit_chain() -> tuple[bool, str, int]:
    line_iter = iter_jsonl_lines(AUDIT_LOG_PATH)
    first_line = next(line_iter, None)
    if first_line is None:
        return True, "Audit log empty", 0

    signing_salt = get_audit_signing_salt()
    prev_event_hash: str | None = None
    count = 0

    for i, line in enumerate(chain((first_line,), line_iter)):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return False, f"Invalid JSON on line {i + 1}", count

        expected_hash = str(event.get("event_hash", ""))
        payload = {
            "event_id": event.get("event_id"),
            "timestamp_utc": event.get("timestamp_utc"),
            "user_id": event.get("user_id"),
            "role": event.get("role"),
            "action": event.get("action"),
            "case_id": event.get("case_id"),
            "result": event.get("result"),
            "details": event.get("details"),
            "prev_hash": event.get("prev_hash"),
        }
        actual_hash = compute_event_hash(payload, signing_salt)
        if not hmac.compare_digest(expected_hash, actual_hash):
            return False, f"Hash mismatch on line {i + 1}", count

        if i > 0 and event.get("prev_hash") != prev_event_hash:
            return False, f"Chain break on line {i + 1}", count

        prev_event_hash = expected_hash
        count += 1

    return True, "Audit chain valid", count


def read_feedback_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in iter_jsonl_lines(FEEDBACK_LOG_PATH):
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def append_feedback_entry(category: str, summary: str, details: str, rating: int) -> None:
    entry = {
        "feedback_id": str(uuid.uuid4()),
        "timestamp_utc": to_utc_iso(utc_now()),
        "user_id": st.session_state.get("auth_user_id") or "anonymous",
        "role": st.session_state.get("auth_role") or "unauthenticated",
        "category": category,
        "summary": summary.strip(),
        "details": details.strip(),
        "rating": int(rating),
    }
    with FEEDBACK_LOG_PATH.open("a", encoding="utf-8") as file_obj:
        file_obj.write(json.dumps(entry, ensure_ascii=False) + "\n")


def beta_readiness_snapshot(conn_obj: Any) -> dict[str, Any]:
    auth_status = auth_status_snapshot(conn_obj)
    chain_ok, chain_message, chain_count = validate_audit_chain()
    feedback_entries = read_feedback_entries()
    schema_row = conn_obj.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
    schema_version = int(schema_row[0]) if schema_row else 0
    doc_count = 0
    chunk_count = 0
    try:
        knowledge_manifest = build_knowledge_manifest(DOMAIN_KB_PATH, KNOWLEDGE_MANIFEST_PATH)
        doc_count = len(knowledge_manifest.get("documents", []))
        chunk_count = int(knowledge_manifest.get("chunk_count", 0))
    except Exception:
        pass
    return {
        "app_version": APP_VERSION,
        "release_stage": RELEASE_STAGE,
        "schema_version": schema_version,
        "schema_expected": CURRENT_SCHEMA_VERSION,
        "audit_chain_ok": chain_ok,
        "audit_chain_message": chain_message,
        "audit_event_count": chain_count,
        "local_user_count": auth_status["local_user_count"],
        "local_mfa_enabled": auth_status["local_mfa_enabled"],
        "oidc_enabled": auth_status["oidc_enabled"],
        "providers": auth_status["providers"],
        "feedback_count": len(feedback_entries),
        "case_count": len(list_cases(conn_obj)),
        "knowledge_documents": doc_count,
        "knowledge_chunks": chunk_count,
    }


def system_status_snapshot(conn_obj: Any) -> dict[str, Any]:
    base = beta_readiness_snapshot(conn_obj)
    openai_secret_configured = bool(str(st.secrets.get("openai_api_key", "")).strip())
    openai_runtime_active = bool(str(st.session_state.get("ai_runtime_api_key", "")).strip())
    return {
        **base,
        "public_signup_enabled": bool(st.session_state.get("security_public_signup_enabled", False)),
        "signup_requires_approval": bool(st.session_state.get("security_signup_requires_approval", True)),
        "openai_secret_configured": openai_secret_configured,
        "openai_runtime_active": openai_runtime_active,
        "openai_available": openai_secret_configured or openai_runtime_active,
    }


def release_status_label(snapshot: dict[str, Any]) -> str:
    if (
        snapshot["schema_version"] == snapshot["schema_expected"]
        and snapshot["audit_chain_ok"]
        and snapshot["case_count"] > 0
        and snapshot["knowledge_documents"] > 0
    ):
        return "READY"
    return "CHECK"


def clear_auth_state() -> None:
    for key in list(st.session_state.keys()):
        if key in {"revealed_case_ids", "selected_case_id", "reveal_reason", "ui_selected_case_ids"}:
            st.session_state.pop(key, None)
            continue
        if key.startswith(("bulk_", "saved_view_", "notify_ack_")):
            st.session_state.pop(key, None)
            continue
        if key.startswith(("team_", "assignee_", "next_state_", "state_reason_")):
            st.session_state.pop(key, None)
            continue
        if key.startswith(("assign_btn_", "transition_btn_", "approve_", "override_", "select_")):
            st.session_state.pop(key, None)
    st.session_state["auth_user_id"] = None
    st.session_state["auth_display_name"] = None
    st.session_state["auth_provider"] = None
    st.session_state["auth_role"] = None
    st.session_state["auth_login_at"] = None
    st.session_state["auth_last_activity_at"] = None
    st.session_state["pending_mfa_user_id"] = None
    st.session_state["revealed_case_ids"] = set()
    st.session_state["selected_case_id"] = None
    st.session_state["ui_loaded_default_view_for_user"] = ""
    st.session_state["ai_runtime_api_key"] = ""
    st.session_state["rag_query_timestamps"] = []


def finalize_local_login(conn_obj: Any, user: dict[str, Any], username: str) -> None:
    login_ok, login_msg, refreshed_user = record_login_success(conn_obj, username.strip())
    if not login_ok or not refreshed_user:
        append_audit_event(
            action="login",
            result="failure",
            details={"reason": login_msg},
            actor_user_id=username,
            actor_role=str(user.get("role", "unauthenticated")),
        )
        st.error("Login failed due to a database error.")
        return

    now_iso = to_utc_iso(utc_now())
    st.session_state["auth_user_id"] = username.strip()
    st.session_state["auth_display_name"] = str(refreshed_user.get("display_name") or username.strip())
    st.session_state["auth_provider"] = str(refreshed_user.get("auth_provider") or "local")
    st.session_state["auth_role"] = str(refreshed_user["role"])
    st.session_state["auth_login_at"] = now_iso
    st.session_state["auth_last_activity_at"] = now_iso
    st.session_state["pending_mfa_user_id"] = None
    st.session_state["revealed_case_ids"] = set()

    append_audit_event(
        action="login",
        result="success",
        details={
            "reason": "credentials_verified",
            "display_name": st.session_state["auth_display_name"],
            "auth_provider": st.session_state["auth_provider"],
        },
        actor_user_id=username.strip(),
        actor_role=str(refreshed_user["role"]),
    )
    st.rerun()


def login_screen(conn_obj: Any) -> None:
    st.markdown("## Sign In Required")
    st.caption("Government AI Triage System")
    st.caption("Authentication is verified against the secured local user directory.")
    st.caption("Passwords are stored as hashes, login failures are rate-limited, sessions are audited, and MFA is supported.")

    oidc_providers = get_oidc_providers()
    if oidc_providers:
        st.markdown("### Single Sign-On")
        provider_cols = st.columns(max(1, len(oidc_providers)))
        for idx, provider in enumerate(oidc_providers):
            label = provider.replace("_", " ").title()
            if provider_cols[idx].button(f"Continue with {label}", key=f"oidc_{provider}"):
                try:
                    st.login(provider)
                except Exception as exc:
                    st.error(f"OIDC login failed to start: {exc}")

        st.caption("Google or Microsoft MFA is enforced by the identity provider when enabled on that account.")
        st.markdown("---")
    else:
        st.markdown("### Single Sign-On")
        st.caption("Google and Microsoft sign-in will appear here when OIDC is configured for this deployment.")
        st.markdown("---")

    if not bool(st.session_state.get("security_public_signup_enabled", False)):
        st.caption("New account creation is currently disabled by the administrator.")
    elif bool(st.session_state.get("security_signup_requires_approval", True)):
        st.caption("New local accounts require supervisor approval before first login.")
    else:
        st.caption("New local accounts are enabled and become active immediately after sign-up.")

    pending_mfa_user_id = str(st.session_state.get("pending_mfa_user_id") or "").strip()

    if pending_mfa_user_id:
        pending_user = get_user(conn_obj, pending_mfa_user_id)
        if not pending_user or str(pending_user.get("status", "active")).lower() != "active":
            st.session_state["pending_mfa_user_id"] = None
            st.warning("Your pending sign-in session expired. Please sign in again.")
            st.rerun()

        st.info("Username and password verified. Enter your verification code to continue.")
        with st.form("mfa_form"):
            st.text_input("Username", value=pending_mfa_user_id, disabled=True)
            mfa_code = st.text_input("Verification Code", max_chars=6)
            verify_submitted = st.form_submit_button("Verify code", type="primary")
        if st.button("Back to sign in", key="mfa_back_btn"):
            st.session_state["pending_mfa_user_id"] = None
            st.rerun()

        if verify_submitted:
            totp_secret = str(pending_user.get("totp_secret") or "").strip()
            if not verify_totp_code(totp_secret, mfa_code):
                fail_ok, fail_msg, fail_state = record_login_failure(
                    conn_obj,
                    pending_mfa_user_id,
                    lockout_after=LOGIN_LOCKOUT_AFTER,
                    lockout_minutes=LOGIN_LOCKOUT_MINUTES,
                )
                append_audit_event(
                    action="login",
                    result="denied",
                    details={
                        "reason": "invalid_mfa_code",
                        "failed_attempts": int((fail_state or {}).get("failed_attempts", 0)) if fail_ok else None,
                        "locked_until_utc": (fail_state or {}).get("locked_until_utc") if fail_ok else None,
                    },
                    actor_user_id=pending_mfa_user_id,
                    actor_role=str(pending_user.get("role", "unauthenticated")),
                )
                st.error("Verification code is invalid.")
                return

            finalize_local_login(conn_obj, pending_user, pending_mfa_user_id)
        return

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")

    if submitted:
        user = get_user(conn_obj, username.strip())
        if not user:
            append_audit_event(
                action="login",
                result="denied",
                details={"reason": "unknown_user"},
                actor_user_id=username or "anonymous",
                actor_role="unauthenticated",
            )
            st.error("Invalid credentials")
            return

        if str(user.get("status", "active")).lower() != "active":
            append_audit_event(
                action="login",
                result="denied",
                details={"reason": "inactive_user"},
                actor_user_id=username,
                actor_role=str(user.get("role", "unauthenticated")),
            )
            st.error("Account is inactive.")
            return

        locked_until_raw = str(user.get("locked_until_utc") or "").strip()
        if locked_until_raw:
            locked_until = parse_utc_iso(locked_until_raw)
            if utc_now() < locked_until:
                append_audit_event(
                    action="login",
                    result="denied",
                    details={"reason": "account_locked", "locked_until_utc": locked_until_raw},
                    actor_user_id=username,
                    actor_role=str(user.get("role", "unauthenticated")),
                )
                st.error(f"Account is temporarily locked until {locked_until_raw}.")
                return

        if not verify_password(password, user["password_hash"]):
            fail_ok, fail_msg, fail_state = record_login_failure(
                conn_obj,
                username.strip(),
                lockout_after=LOGIN_LOCKOUT_AFTER,
                lockout_minutes=LOGIN_LOCKOUT_MINUTES,
            )
            append_audit_event(
                action="login",
                result="denied",
                details={
                    "reason": "invalid_password",
                    "failed_attempts": int((fail_state or {}).get("failed_attempts", 0)) if fail_ok else None,
                    "locked_until_utc": (fail_state or {}).get("locked_until_utc") if fail_ok else None,
                },
                actor_user_id=username,
                actor_role="unauthenticated",
            )
            if fail_ok and fail_state and fail_state.get("locked_until_utc"):
                st.error(f"Invalid credentials. Account locked until {fail_state['locked_until_utc']}.")
            elif fail_msg.startswith("DB_"):
                st.error("Login failed due to a database error.")
            else:
                st.error("Invalid credentials")
            return

        totp_secret = str(user.get("totp_secret") or "").strip()
        mfa_required = int(user.get("mfa_required", 0)) == 1 and str(user.get("mfa_type", "none")) == "totp"
        if mfa_required:
            st.session_state["pending_mfa_user_id"] = username.strip()
            append_audit_event(
                action="login_mfa_challenge",
                result="success",
                details={
                    "reason": "password_verified_mfa_required",
                },
                actor_user_id=username.strip(),
                actor_role=str(user.get("role", "operator")),
            )
            st.info("Username and password verified. Enter your verification code to continue.")
            st.rerun()
            return

        finalize_local_login(conn_obj, user, username.strip())

    if not bool(st.session_state.get("security_public_signup_enabled", False)):
        return

    st.markdown("---")
    with st.expander("Create Account"):
        st.caption("Create a local operator account. Google and Microsoft sign-in depend on external provider setup.")
        if bool(st.session_state.get("security_signup_requires_approval", True)):
            st.caption("New sign-ups are created in inactive status and must be approved by a supervisor in Settings.")
        with st.form("create_account_form"):
            signup_user_id = st.text_input("New username")
            signup_display_name = st.text_input("Display name")
            signup_password = st.text_input("New password", type="password")
            signup_confirm_password = st.text_input("Confirm password", type="password")
            signup_enable_mfa = st.checkbox("Enable two-step verification (TOTP)")
            signup_totp_secret = st.text_input(
                "Authenticator secret (Base32)",
                value=generate_totp_secret() if signup_enable_mfa else "",
                disabled=not signup_enable_mfa,
            )
            signup_submitted = st.form_submit_button("Create account", type="primary")

        if signup_submitted:
            new_user_id = signup_user_id.strip()
            display_name = signup_display_name.strip() or new_user_id.replace("_", " ").title()
            password_value = signup_password.strip()
            confirm_value = signup_confirm_password.strip()
            totp_secret = _normalize_totp_secret(signup_totp_secret) if signup_enable_mfa else ""

            if not new_user_id or not re.fullmatch(r"[A-Za-z0-9_.@-]{3,64}", new_user_id):
                st.error("Username must be 3-64 characters and use letters, numbers, dot, underscore, @, or hyphen.")
            elif len(password_value) < 8:
                st.error("Password must be at least 8 characters.")
            elif password_value != confirm_value:
                st.error("Password confirmation does not match.")
            elif signup_enable_mfa and len(totp_secret) < 16:
                st.error("Enter a valid Base32 authenticator secret.")
            else:
                ok_new, msg_new, created_user = create_local_user(
                    conn_obj,
                    user_id=new_user_id,
                    display_name=display_name,
                    role="operator",
                    password_hash=hash_password_pbkdf2(password_value),
                    status="inactive" if bool(st.session_state.get("security_signup_requires_approval", True)) else "active",
                    mfa_required=signup_enable_mfa,
                    totp_secret=totp_secret or None,
                )
                append_audit_event(
                    action="self_signup",
                    result="success" if ok_new else ("failure" if str(msg_new).startswith("DB_") else "denied"),
                    actor_user_id=new_user_id,
                    actor_role="operator",
                    details={
                        "display_name": display_name,
                        "mfa_required": bool(signup_enable_mfa),
                        "status": "inactive" if bool(st.session_state.get("security_signup_requires_approval", True)) else "active",
                        "reason": msg_new if not ok_new else "local_account_created",
                    },
                )
                if not ok_new:
                    render_mutation_error(msg_new, arabic_default=False)
                else:
                    if created_user and int(created_user.get("mfa_required", 0)) == 1:
                        st.warning(
                            "Store this authenticator secret now. It is shown for initial setup and should be treated as sensitive."
                        )
                        if str(created_user.get("status", "active")) != "active":
                            st.success("Account created and submitted for approval. Keep this authenticator secret; you will need it after a supervisor activates the account.")
                        else:
                            st.success("Account created. Sign in with your username and password, then enter the verification code from your authenticator app.")
                        st.code(str(created_user.get("totp_secret") or ""), language=None)
                    elif created_user and str(created_user.get("status", "active")) != "active":
                        st.success("Account created and submitted for approval. A supervisor must activate it before you can sign in.")
                    else:
                        st.success("Account created. You can sign in now.")


def enforce_session_limits() -> bool:
    user_id = st.session_state.get("auth_user_id")
    role = st.session_state.get("auth_role")
    login_at_raw = st.session_state.get("auth_login_at")
    last_activity_raw = st.session_state.get("auth_last_activity_at")
    if not user_id or not role or not login_at_raw or not last_activity_raw:
        return False

    db_user = get_user(conn, str(user_id))
    if not db_user or str(db_user.get("status", "active")).lower() != "active":
        append_audit_event(
            action="session_invalidated",
            result="success",
            details={"reason": "user_missing_or_inactive"},
            actor_user_id=str(user_id),
            actor_role=str(role),
        )
        clear_auth_state()
        st.warning("Session was invalidated. Please sign in again.")
        return False

    now = utc_now()
    login_at = parse_utc_iso(login_at_raw)
    last_activity = parse_utc_iso(last_activity_raw)

    idle_minutes = int(st.session_state.get("security_session_idle_minutes", 15))
    max_hours = int(st.session_state.get("security_session_max_hours", 8))

    if now - last_activity > timedelta(minutes=idle_minutes):
        append_audit_event(
            action="session_timeout_idle",
            result="success",
            details={"idle_minutes": idle_minutes},
            actor_user_id=user_id,
            actor_role=role,
        )
        clear_auth_state()
        st.warning("Session expired due to inactivity.")
        return False

    if now - login_at > timedelta(hours=max_hours):
        append_audit_event(
            action="session_timeout_max",
            result="success",
            details={"max_hours": max_hours},
            actor_user_id=user_id,
            actor_role=role,
        )
        clear_auth_state()
        st.warning("Session reached maximum duration. Please sign in again.")
        return False

    st.session_state["auth_last_activity_at"] = to_utc_iso(now)
    return True


def require_permission(permission: str, action: str, case_id: str | None = None) -> bool:
    if has_permission(permission):
        return True
    append_audit_event(
        action=action,
        result="denied",
        case_id=case_id,
        details={"reason": f"missing_permission:{permission}"},
    )
    st.error("Permission denied.")
    return False


def render_mutation_error(message: str, arabic_default: bool) -> None:
    if message.startswith("DB_BUSY:"):
        st.error(
            bi(
                "قاعدة البيانات مشغولة حالياً. حاول مرة أخرى خلال لحظات.",
                "Database is busy right now. Please retry in a moment.",
                arabic_default,
            )
        )
        return
    if message.startswith("DB_ERROR:"):
        st.error(
            bi(
                "تعذر تنفيذ العملية بسبب خطأ في قاعدة البيانات.",
                "Action failed due to a database error.",
                arabic_default,
            )
        )
        return
    st.error(message)


def require_active_action(permission: str, action: str, case_id: str | None = None) -> bool:
    if not enforce_session_limits():
        append_audit_event(
            action=action,
            result="denied",
            case_id=case_id,
            details={"reason": "session_expired"},
        )
        st.rerun()
        return False
    if not st.session_state.get("auth_user_id") or not st.session_state.get("auth_role"):
        append_audit_event(
            action=action,
            result="denied",
            case_id=case_id,
            details={"reason": "unauthenticated"},
        )
        st.error("Session expired. Please sign in again.")
        return False
    return require_permission(permission, action, case_id=case_id)


def enforce_rag_rate_limit(window_seconds: int = 60, max_queries: int = 8, min_interval_seconds: int = 2) -> tuple[bool, str]:
    now = utc_now()
    timestamps = [
        parse_utc_iso(value)
        for value in st.session_state.get("rag_query_timestamps", [])
        if isinstance(value, str)
    ]
    recent = [ts for ts in timestamps if (now - ts).total_seconds() <= window_seconds]
    if recent and (now - recent[-1]).total_seconds() < min_interval_seconds:
        return False, f"Please wait at least {min_interval_seconds} seconds between assistant queries."
    if len(recent) >= max_queries:
        return False, f"Assistant query limit reached ({max_queries} per {window_seconds} seconds). Try again shortly."
    recent.append(now)
    st.session_state["rag_query_timestamps"] = [to_utc_iso(ts) for ts in recent]
    return True, ""


def render_auth_config_error() -> None:
    st.error("Authentication is not configured.")
    st.markdown(
        f"Create `{(BASE_DIR / '.streamlit' / 'secrets.toml').relative_to(BASE_DIR)}` "
        f"from `{(BASE_DIR / '.streamlit' / 'secrets.example.toml').relative_to(BASE_DIR)}`. "
        "Users are bootstrapped into the secured local user directory from hashed credentials."
    )


def status_kind(urgency_en: str) -> str:
    return "urgent" if urgency_en == "Urgent" else "warning"


def _normalize_text(value: str) -> str:
    return value.strip().lower()


def _matches_search(case: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    q = _normalize_text(query)
    searchable = [
        str(case.get("case_id", "")),
        str(case.get("request_text_ar", "")),
        str(case.get("request_text_en", "")),
        str(case.get("intent_ar", "")),
        str(case.get("intent_en", "")),
        str(case.get("department_ar", "")),
        str(case.get("department_en", "")),
    ]
    return any(q in _normalize_text(v) for v in searchable)


def filter_cases(
    cases: list[dict[str, Any]],
    *,
    department_filter: str,
    state_filter: str,
    urgency_filter: str,
    sla_filter: str,
    assigned_user_filter: str,
    queue_scope: str,
    search_query: str,
    current_user: str,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for case in cases:
        if not _matches_search(case, search_query):
            continue

        if department_filter != "all":
            if department_filter == "Human Review":
                if case.get("assigned_team") != "Human Review":
                    continue
            elif case["department_en"] != department_filter:
                continue

        if state_filter != "ALL" and case["state"] != state_filter:
            continue

        if urgency_filter != "all":
            if str(case.get("urgency_en", "")).lower() != urgency_filter.lower():
                continue

        sla_status = compute_sla_state(case)["status"]
        if sla_filter != "all" and sla_status != sla_filter:
            continue

        assigned_user = str(case.get("assigned_user") or "")
        if assigned_user_filter != "all":
            if assigned_user_filter == "unassigned" and assigned_user:
                continue
            if assigned_user_filter not in {"all", "unassigned"} and assigned_user != assigned_user_filter:
                continue

        if queue_scope == "MY_QUEUE" and assigned_user != current_user:
            continue
        if queue_scope == "UNASSIGNED" and assigned_user:
            continue

        filtered.append(case)
    return filtered


def paginate_cases(
    cases: list[dict[str, Any]],
    *,
    page_size: int,
    page_index: int,
) -> tuple[list[dict[str, Any]], int]:
    if page_size <= 0:
        page_size = 10
    total_pages = max(1, (len(cases) + page_size - 1) // page_size)
    safe_index = min(max(page_index, 0), total_pages - 1)
    start = safe_index * page_size
    end = start + page_size
    return cases[start:end], safe_index


def render_case_table(cases: list[dict[str, Any]], arabic_default: bool) -> None:
    rows = []
    for case in cases:
        sla = compute_sla_state(case)
        rows.append(
            {
                bi("رقم الحالة", "Case", arabic_default): case["case_id"],
                bi("الطلب", "Request", arabic_default): field(case, "request_text", arabic_default),
                bi("النية", "Intent", arabic_default): field(case, "intent", arabic_default),
                bi("الأولوية", "Urgency", arabic_default): field(case, "urgency", arabic_default),
                bi("الإدارة", "Department", arabic_default): field(case, "department", arabic_default),
                bi("الحالة", "State", arabic_default): case["state"],
                bi("المسند إليه", "Assigned User", arabic_default): case.get("assigned_user") or "-",
                bi("SLA", "SLA", arabic_default): sla["status"],
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)


def cases_to_csv_bytes(cases: list[dict[str, Any]], arabic_default: bool) -> bytes:
    rows = export_cases_csv_rows(cases, arabic_default)
    if not rows:
        return b""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def render_pagination_controls(
    total_count: int,
    *,
    page_size: int,
    page_index: int,
    key_prefix: str,
    arabic_default: bool,
) -> tuple[int, int]:
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    safe_index = min(max(page_index, 0), total_pages - 1)
    col_l, col_m, col_r = st.columns([1.1, 2.4, 1.1])
    prev_disabled = safe_index <= 0
    next_disabled = safe_index >= total_pages - 1

    if col_l.button(bi("السابق", "Previous", arabic_default), key=f"{key_prefix}_prev", disabled=prev_disabled):
        safe_index = max(0, safe_index - 1)
    col_m.caption(
        bi(
            f"صفحة {safe_index + 1} من {total_pages} • إجمالي {total_count}",
            f"Page {safe_index + 1} of {total_pages} • Total {total_count}",
            arabic_default,
        )
    )
    if col_r.button(bi("التالي", "Next", arabic_default), key=f"{key_prefix}_next", disabled=next_disabled):
        safe_index = min(total_pages - 1, safe_index + 1)
    return safe_index, total_pages


def summarize_sla(cases: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"ON_TRACK": 0, "AT_RISK": 0, "BREACHED": 0}
    for case in cases:
        sla = compute_sla_state(case)
        counts[sla["status"]] += 1
    return counts


def render_page_header(title_ar: str, title_en: str, subtitle_ar: str, subtitle_en: str, arabic_default: bool) -> None:
    st.markdown(f"### {bi(title_ar, title_en, arabic_default)}")
    st.caption(bi(subtitle_ar, subtitle_en, arabic_default))


def render_global_worklist_toolbar(selected_nav: str, arabic_default: bool) -> None:
    if selected_nav not in {"incoming", "queues", "review"}:
        return

    toolbar_cols = st.columns([4, 1.4, 1.2])
    st.session_state["ui_search_query"] = toolbar_cols[0].text_input(
        bi("بحث عام بالحالة أو النص", "Global search by case/text", arabic_default),
        value=str(st.session_state.get("ui_search_query", "")),
        key="ui_search_query_input",
    ).strip()
    st.session_state["ui_page_size"] = int(
        toolbar_cols[1].selectbox(
            bi("حجم الصفحة", "Page size", arabic_default),
            options=[10, 25, 50],
            index=[10, 25, 50].index(int(st.session_state.get("ui_page_size", 10)))
            if int(st.session_state.get("ui_page_size", 10)) in [10, 25, 50]
            else 0,
            key="ui_page_size_input",
        )
    )
    if toolbar_cols[2].button(bi("إعادة ضبط المرشحات", "Reset Filters", arabic_default), width="stretch"):
        st.session_state["ui_search_query"] = ""
        st.session_state["ui_page_index"] = 0
        st.session_state["ui_default_queue"] = "all"
        st.session_state["ui_sla_filter"] = "all"
        st.session_state["ui_urgency_filter"] = "all"
        st.session_state["ui_assigned_user_filter"] = "all"
        st.session_state["ui_state_filter"] = "ALL"
        st.session_state["ui_queue_scope"] = "ALL"
        st.rerun()


def build_filter_payload(
    *,
    search_query: str,
    department_filter: str,
    state_filter: str,
    urgency_filter: str,
    sla_filter: str,
    assigned_user_filter: str,
    queue_scope: str,
    page_size: int,
) -> dict[str, Any]:
    return {
        "search_query": search_query,
        "department_filter": department_filter,
        "state_filter": state_filter,
        "urgency_filter": urgency_filter,
        "sla_filter": sla_filter,
        "assigned_user_filter": assigned_user_filter,
        "queue_scope": queue_scope,
        "page_size": page_size,
    }


def apply_saved_view_filters(filters: dict[str, Any]) -> None:
    st.session_state["ui_search_query"] = str(filters.get("search_query", ""))
    st.session_state["ui_default_queue"] = str(filters.get("department_filter", "all"))
    st.session_state["ui_state_filter"] = str(filters.get("state_filter", "ALL"))
    st.session_state["ui_sla_filter"] = str(filters.get("sla_filter", "all"))
    st.session_state["ui_urgency_filter"] = str(filters.get("urgency_filter", "all"))
    st.session_state["ui_assigned_user_filter"] = str(filters.get("assigned_user_filter", "all"))
    st.session_state["ui_queue_scope"] = str(filters.get("queue_scope", "ALL"))
    st.session_state["ui_page_size"] = int(filters.get("page_size", 10))
    st.session_state["ui_page_index"] = 0


def refresh_notifications(conn_obj: Any, cases: list[dict[str, Any]], audit_events: list[dict[str, Any]]) -> None:
    override_counts: dict[str, int] = {}
    for event in audit_events:
        if event.get("action") == "override" and event.get("result") == "success" and event.get("case_id"):
            case_id = str(event["case_id"])
            override_counts[case_id] = override_counts.get(case_id, 0) + 1

    for case in cases:
        case_id = str(case["case_id"])
        sla_state = compute_sla_state(case)["status"]
        if sla_state == "BREACHED":
            upsert_notification(
                conn_obj,
                case_id=case_id,
                severity="high",
                notif_type="SLA_BREACHED",
                message_ar=f"الحالة {case_id} تجاوزت اتفاقية مستوى الخدمة.",
                message_en=f"Case {case_id} has breached SLA.",
            )
        if float(case.get("confidence", 1.0)) < 0.75:
            upsert_notification(
                conn_obj,
                case_id=case_id,
                severity="medium",
                notif_type="LOW_CONFIDENCE",
                message_ar=f"الحالة {case_id} منخفضة الثقة.",
                message_en=f"Case {case_id} has low confidence.",
            )
        if override_counts.get(case_id, 0) >= 2:
            upsert_notification(
                conn_obj,
                case_id=case_id,
                severity="high",
                notif_type="REPEATED_OVERRIDE",
                message_ar=f"الحالة {case_id} شهدت تجاوزات متكررة.",
                message_en=f"Case {case_id} has repeated overrides.",
            )


st.set_page_config(
    page_title="Malomatia Gov-Service Triage AI",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

ensure_session_defaults()
if st.session_state.get("auth_schema_version") != AUTH_SCHEMA_VERSION:
    clear_auth_state()
    st.session_state["auth_schema_version"] = AUTH_SCHEMA_VERSION

conn = connect_db(DB_PATH)
ensure_schema(conn, SCHEMA_PATH)
seed_cases_if_empty(conn, DATA_PATH)

archive_old_audit_events(int(st.session_state["security_audit_retention_days"]))

auth_users = load_auth_users()
if auth_users:
    bootstrap_ok, bootstrap_msg = bootstrap_auth_users(conn, auth_users)
    if not bootstrap_ok:
        st.error(f"Authentication bootstrap failed: {bootstrap_msg}")
        st.stop()

if not list_users(conn):
    render_auth_config_error()
    st.stop()

if getattr(st.user, "is_logged_in", False) and not st.session_state.get("auth_user_id"):
    oidc_email = str(getattr(st.user, "email", "") or "").strip().lower()
    oidc_name = str(getattr(st.user, "name", "") or oidc_email or "OIDC User").strip()
    oidc_provider = normalize_auth_provider(str(getattr(st.user, "iss", "") or "oidc"))
    if oidc_email:
        resolved_role = resolve_oidc_role(oidc_email)
        external_ok, external_msg, external_user = upsert_external_user(
            conn,
            user_id=oidc_email,
            display_name=oidc_name,
            auth_provider=oidc_provider,
            role=resolved_role,
        )
        if not external_ok or not external_user:
            st.error(f"OIDC user sync failed: {external_msg}")
            st.stop()
        login_ok, login_msg, refreshed_user = record_login_success(conn, oidc_email)
        if not login_ok or not refreshed_user:
            st.error(f"OIDC login failed: {login_msg}")
            st.stop()
        now_iso = to_utc_iso(utc_now())
        st.session_state["auth_user_id"] = oidc_email
        st.session_state["auth_display_name"] = str(refreshed_user.get("display_name") or oidc_name)
        st.session_state["auth_provider"] = str(refreshed_user.get("auth_provider") or oidc_provider)
        st.session_state["auth_role"] = str(refreshed_user["role"])
        st.session_state["auth_login_at"] = now_iso
        st.session_state["auth_last_activity_at"] = now_iso
        append_audit_event(
            action="login",
            result="success",
            details={"reason": "oidc_login", "auth_provider": st.session_state["auth_provider"]},
            actor_user_id=oidc_email,
            actor_role=str(refreshed_user["role"]),
        )

if not st.session_state.get("auth_user_id"):
    login_screen(conn)
    st.stop()

if not enforce_session_limits():
    st.stop()

cases = list_cases(conn)
if not cases:
    st.error("No cases available.")
    st.stop()

if st.session_state.get("selected_case_id") is None:
    st.session_state["selected_case_id"] = cases[0]["case_id"]

selected_case = get_case(conn, str(st.session_state["selected_case_id"]))
if not selected_case:
    selected_case = cases[0]
    st.session_state["selected_case_id"] = selected_case["case_id"]

role = str(st.session_state["auth_role"])
current_user = str(st.session_state["auth_user_id"])
display_name = str(st.session_state.get("auth_display_name") or current_user)
auth_provider = str(st.session_state.get("auth_provider") or "local")
audit_events_all = read_audit_events()
refresh_notifications(conn, cases, audit_events_all)

if st.session_state.get("ui_loaded_default_view_for_user") != current_user:
    default_views = [v for v in list_saved_views(conn, current_user) if int(v.get("is_default", 0)) == 1]
    if default_views:
        try:
            apply_saved_view_filters(json.loads(str(default_views[0]["filters_json"])))
        except json.JSONDecodeError:
            pass
    st.session_state["ui_loaded_default_view_for_user"] = current_user

with st.sidebar:
    st.markdown("### Language")
    st.radio(
        "Language",
        options=["ar", "en"],
        format_func=lambda value: "العربية" if value == "ar" else "English",
        key="ui_language_mode",
        label_visibility="collapsed",
    )
    arabic_default = st.session_state.get("ui_language_mode", "ar") == "ar"

    st.caption(
        bi(
            f"المستخدم: {display_name} | المعرف: {current_user} | الدور: {role} | الموفر: {auth_provider}",
            f"User: {display_name} | ID: {current_user} | Role: {role} | Provider: {auth_provider}",
            arabic_default,
        )
    )
    if st.button(bi("تبديل المستخدم", "Switch User", arabic_default), width="stretch"):
        append_audit_event(action="logout", result="success", details={"reason": "switch_user"})
        clear_auth_state()
        if auth_provider != "local" and getattr(st.user, "is_logged_in", False):
            st.logout()
        st.rerun()

    nav_options = [
        ("dashboard", "لوحة التحكم", "Dashboard"),
        ("incoming", "الطلبات الواردة", "Incoming Requests"),
        ("queues", "الطوابير", "Queues"),
        ("review", "المراجعة", "Review"),
        ("assistant", "المساعد المعرفي", "Knowledge Assistant"),
        ("notifications", "التنبيهات", "Notifications"),
        ("settings", "الإعدادات", "Settings"),
        ("help", "المساعدة", "Help"),
    ]
    nav_map = {k: bi(ar, en, arabic_default) for k, ar, en in nav_options}
    selected_nav = st.radio(
        bi("القائمة", "Navigation", arabic_default),
        options=list(nav_map.keys()),
        format_func=lambda value: nav_map[value],
        key="ui_nav",
    )

direction = "rtl" if arabic_default else "ltr"
st.markdown(
    f"<style>{load_theme(direction, st.session_state['ui_sidebar_contrast'], st.session_state['ui_compact_mode'])}</style>",
    unsafe_allow_html=True,
)

if st.session_state.get("security_privacy_masking_enabled", True):
    st.info(
        bi(
            "وضع الخصوصية مفعل: يتم إخفاء البيانات الحساسة افتراضياً.",
            "Privacy mode is enabled: sensitive data is masked by default.",
            arabic_default,
        )
    )

header_cols = st.columns([5.2, 1.1])
with header_cols[0]:
    top_bar_html = f"""
    <div class="top-bar">
      <div class="brand-wrap">
        <div class="gov-logo">MG</div>
        <div>
          <div class="system-title">{bi("نظام الفرز الحكومي بالذكاء الاصطناعي", "Government AI Triage System", arabic_default)}</div>
          <div class="system-sub">{bi("عمليات الخدمات العامة - قطر", "Public-Service Operations - Qatar", arabic_default)}</div>
        </div>
      </div>
      <div class="top-meta">
        <span class="chip">{bi("اللغة", "Language", arabic_default)}: {("العربية" if arabic_default else "English")}</span>
        <span class="chip">{bi("المستخدم", "User", arabic_default)}: {display_name}</span>
        <span class="chip">{bi("الوصول", "Access", arabic_default)}: {role} · {auth_provider}</span>
      </div>
    </div>
    """
    st.markdown(top_bar_html, unsafe_allow_html=True)
with header_cols[1]:
    if st.button(bi("تسجيل الخروج", "Logout", arabic_default), width="stretch"):
        append_audit_event(action="logout", result="success", details={"reason": "user_initiated"})
        clear_auth_state()
        if auth_provider != "local" and getattr(st.user, "is_logged_in", False):
            st.logout()
        st.rerun()

if selected_nav in {"dashboard", "incoming", "queues", "review"}:
    sla_counts = summarize_sla(cases)
    metric_cols = st.columns(4)
    metric_cols[0].markdown(
        f'<div class="metric-card"><div>{bi("إجمالي الحالات", "Total Cases", arabic_default)}</div><div class="metric-value">{len(cases)}</div></div>',
        unsafe_allow_html=True,
    )
    metric_cols[1].markdown(
        f'<div class="metric-card"><div>{bi("ضمن SLA", "SLA On Track", arabic_default)}</div><div class="metric-value">{sla_counts["ON_TRACK"]}</div></div>',
        unsafe_allow_html=True,
    )
    metric_cols[2].markdown(
        f'<div class="metric-card"><div>{bi("معرضة للخطر", "SLA At Risk", arabic_default)}</div><div class="metric-value">{sla_counts["AT_RISK"]}</div></div>',
        unsafe_allow_html=True,
    )
    metric_cols[3].markdown(
        f'<div class="metric-card"><div>{bi("متجاوزة SLA", "SLA Breached", arabic_default)}</div><div class="metric-value">{sla_counts["BREACHED"]}</div></div>',
        unsafe_allow_html=True,
    )

render_global_worklist_toolbar(selected_nav, arabic_default)

main_col, right_col = st.columns([2.2, 1], gap="large")

if selected_nav == "dashboard":
    with main_col:
        render_page_header(
            "لوحة التشغيل",
            "Operations Dashboard",
            "ملخص سريع للحالة التشغيلية والأحمال والتنبيهات.",
            "Fast operational snapshot of workload, health, and alerts.",
            arabic_default,
        )
        quick_action_cols = st.columns(4)
        dashboard_actions = [
            ("incoming", bi("فتح الطلبات الواردة", "Open Incoming", arabic_default)),
            ("queues", bi("فتح الطوابير", "Open Queues", arabic_default)),
            ("review", bi("فتح المراجعة", "Open Review", arabic_default)),
            ("assistant", bi("فتح المساعد", "Open Assistant", arabic_default)),
        ]
        for idx, (target_nav, label) in enumerate(dashboard_actions):
            if quick_action_cols[idx].button(label, key=f"dashboard_nav_{target_nav}", width="stretch"):
                st.session_state["ui_nav"] = target_nav
                st.rerun()
        state_counts: dict[str, int] = {}
        dept_counts: dict[str, int] = {}
        for case in cases:
            state_counts[str(case["state"])] = state_counts.get(str(case["state"]), 0) + 1
            dept_key = str(case.get("assigned_team") or case["department_en"])
            dept_counts[dept_key] = dept_counts.get(dept_key, 0) + 1

        escalated_cases = [c for c in cases if str(c.get("state")) == "ESCALATED"]
        now_ts = utc_now()
        aging = {"0-1h": 0, "1-4h": 0, "4h+": 0}
        for c in escalated_cases:
            updated = parse_utc_iso(str(c.get("updated_at_utc", c.get("created_at_utc"))))
            hours = max(0.0, (now_ts - updated).total_seconds() / 3600.0)
            if hours < 1:
                aging["0-1h"] += 1
            elif hours < 4:
                aging["1-4h"] += 1
            else:
                aging["4h+"] += 1

        trend_rows = []
        for queue_name, total in sorted(dept_counts.items()):
            recent = sum(
                1
                for c in cases
                if str(c.get("assigned_team") or c.get("department_en")) == queue_name
                and (now_ts - parse_utc_iso(str(c.get("updated_at_utc", c.get("created_at_utc"))))).total_seconds()
                <= 24 * 3600
            )
            trend_rows.append(
                {
                    bi("الطابور", "Queue", arabic_default): queue_name,
                    bi("الإجمالي", "Total", arabic_default): total,
                    bi("آخر 24 ساعة", "Last 24h", arabic_default): recent,
                }
            )
        dashboard_overview_tab, dashboard_trends_tab, dashboard_activity_tab = st.tabs(
            [
                bi("نظرة عامة", "Overview", arabic_default),
                bi("الاتجاهات", "Trends", arabic_default),
                bi("النشاط", "Activity", arabic_default),
            ]
        )
        with dashboard_overview_tab:
            s_col, d_col = st.columns(2)
            s_col.markdown(f"#### {bi('توزيع الحالات حسب الحالة', 'Cases by State', arabic_default)}")
            s_col.dataframe(
                [
                    {
                        bi("الحالة", "State", arabic_default): state,
                        bi("العدد", "Count", arabic_default): count,
                    }
                    for state, count in sorted(state_counts.items())
                ],
                width="stretch",
                hide_index=True,
            )
            d_col.markdown(f"#### {bi('توزيع الحالات حسب الطابور', 'Cases by Queue', arabic_default)}")
            d_col.dataframe(
                [
                    {
                        bi("الطابور", "Queue", arabic_default): queue_name,
                        bi("العدد", "Count", arabic_default): count,
                    }
                    for queue_name, count in sorted(dept_counts.items())
                ],
                width="stretch",
                hide_index=True,
            )
        with dashboard_trends_tab:
            e_col, t_col = st.columns(2)
            e_col.markdown(f"#### {bi('تقادم التصعيدات', 'Escalation Aging', arabic_default)}")
            e_col.dataframe(
                [
                    {
                        bi("الفئة", "Bucket", arabic_default): bucket,
                        bi("العدد", "Count", arabic_default): count,
                    }
                    for bucket, count in aging.items()
                ],
                width="stretch",
                hide_index=True,
            )
            t_col.markdown(f"#### {bi('اتجاه الأحمال', 'Backlog Trend', arabic_default)}")
            t_col.dataframe(trend_rows, width="stretch", hide_index=True)
        with dashboard_activity_tab:
            st.markdown(f"#### {bi('أحدث أحداث سير العمل', 'Recent Workflow Events', arabic_default)}")
            st.dataframe(list_workflow_events(conn, limit=20), width="stretch", hide_index=True)

    with right_col:
        audit_events = read_audit_events()
        kpis = compute_operational_kpis(cases, audit_events)
        release_snapshot = beta_readiness_snapshot(conn)
        open_alerts_count = len(list_notifications(conn, include_acked=False))
        dashboard_side_kpi, dashboard_side_release, dashboard_side_case = st.tabs(
            [
                bi("المؤشرات", "KPIs", arabic_default),
                bi("الإصدار", "Release", arabic_default),
                bi("الحالة", "Case", arabic_default),
            ]
        )
        with dashboard_side_kpi:
            st.markdown(f"### {bi('ملخص مؤشرات الأداء', 'KPI Snapshot', arabic_default)}")
            st.markdown(
                "\n".join(
                    [
                        f"- {bi('متوسط زمن الفرز', 'Avg time to triage', arabic_default)}: {kpis['avg_time_to_triage_minutes']:.1f} {bi('دقيقة', 'min', arabic_default)}",
                        f"- {bi('متوسط زمن أول إسناد', 'Avg time to first assignment', arabic_default)}: {kpis['avg_time_to_first_assignment_minutes']:.1f} {bi('دقيقة', 'min', arabic_default)}",
                        f"- {bi('نسبة تجاوز SLA', 'SLA breached %', arabic_default)}: {kpis['sla_breached_pct']:.1f}%",
                        f"- {bi('معدل التجاوز', 'Override rate', arabic_default)}: {kpis['override_rate_pct']:.1f}%",
                        f"- {bi('تنبيهات مفتوحة', 'Open alerts', arabic_default)}: {open_alerts_count}",
                    ]
                )
            )
        with dashboard_side_release:
            st.markdown(f"### {bi('حالة الإصدار', 'Release Status', arabic_default)}")
            st.markdown(
                "\n".join(
                    [
                        f"- {bi('الإصدار', 'Version', arabic_default)}: {release_snapshot['app_version']}",
                        f"- {bi('المرحلة', 'Stage', arabic_default)}: {release_snapshot['release_stage']}",
                        f"- {bi('التقييم', 'Status', arabic_default)}: {release_status_label(release_snapshot)}",
                        f"- {bi('إنشاء الحسابات العامة', 'Public signup', arabic_default)}: {bi('مفعل', 'Enabled', arabic_default) if st.session_state.get('security_public_signup_enabled', True) else bi('معطل', 'Disabled', arabic_default)}",
                    ]
                )
            )
        with dashboard_side_case:
            st.markdown(f"### {bi('الحالة المحددة', 'Selected Case', arabic_default)}")
            st.markdown(
                "\n".join(
                    [
                        f"- {bi('رقم الحالة', 'Case', arabic_default)}: `{selected_case['case_id']}`",
                        f"- {bi('النية', 'Intent', arabic_default)}: {field(selected_case, 'intent', arabic_default)}",
                        f"- {bi('الأولوية', 'Urgency', arabic_default)}: {field(selected_case, 'urgency', arabic_default)}",
                        f"- {bi('الإدارة', 'Department', arabic_default)}: {field(selected_case, 'department', arabic_default)}",
                    ]
                )
            )

elif selected_nav in {"incoming", "queues"}:
    with main_col:
        if selected_nav == "incoming":
            render_page_header(
                "الطلبات الواردة",
                "Incoming Requests",
                "راجع الحالات الجديدة وحدد القرار المناسب بسرعة.",
                "Review new cases and take the next operational action quickly.",
                arabic_default,
            )
        else:
            render_page_header(
                "عرض الطوابير",
                "Queue View",
                "اعرض الجدول التشغيلي الكامل مع المرشحات والإجراءات الجماعية.",
                "Use the full operational table with filters and bulk actions.",
                arabic_default,
            )

        queue_labels = {
            "all": bi("الكل", "All", arabic_default),
            "Immigration": bi("الهجرة", "Immigration", arabic_default),
            "Municipal": bi("البلدية", "Municipal", arabic_default),
            "Licensing": bi("الترخيص", "Licensing", arabic_default),
            "Human Review": bi("مراجعة بشرية", "Human Review", arabic_default),
        }
        scope_labels = {
            "ALL": bi("جميع الحالات", "All Cases", arabic_default),
            "MY_QUEUE": bi("طابوري", "My Queue", arabic_default),
            "UNASSIGNED": bi("غير مسند", "Unassigned", arabic_default),
        }
        urgency_labels = {
            "all": bi("الكل", "All", arabic_default),
            "Urgent": bi("عاجل", "Urgent", arabic_default),
            "Warning": bi("تحذير", "Warning", arabic_default),
        }
        sla_labels = {
            "all": bi("الكل", "All", arabic_default),
            "ON_TRACK": bi("ضمن SLA", "On Track", arabic_default),
            "AT_RISK": bi("معرض للخطر", "At Risk", arabic_default),
            "BREACHED": bi("متجاوز", "Breached", arabic_default),
        }

        saved_views = list_saved_views(conn, current_user)
        saved_view_options = ["__none__", *[v["name"] for v in saved_views]]

        with st.expander(bi("العروض والمرشحات", "Views & Filters", arabic_default), expanded=False):
            saved_cols = st.columns([2.2, 1, 1.2, 1])
            selected_saved_view_name = saved_cols[0].selectbox(
                bi("العروض المحفوظة", "Saved Views", arabic_default),
                options=saved_view_options,
                format_func=lambda n: bi("بدون", "None", arabic_default) if n == "__none__" else n,
                key=f"{selected_nav}_saved_view_select",
            )
            if saved_cols[1].button(bi("تطبيق", "Apply", arabic_default), key=f"{selected_nav}_saved_apply"):
                if selected_saved_view_name != "__none__":
                    chosen = next((v for v in saved_views if v["name"] == selected_saved_view_name), None)
                    if chosen:
                        try:
                            apply_saved_view_filters(json.loads(str(chosen["filters_json"])))
                        except json.JSONDecodeError:
                            st.warning(bi("تنسيق العرض المحفوظ غير صالح.", "Saved view payload is invalid.", arabic_default))
                        st.rerun()
            view_name = saved_cols[2].text_input(
                bi("اسم العرض", "View Name", arabic_default),
                value=selected_saved_view_name if selected_saved_view_name != "__none__" else "",
                key=f"{selected_nav}_saved_view_name",
            ).strip()
            if saved_cols[3].button(bi("حفظ", "Save", arabic_default), key=f"{selected_nav}_saved_save"):
                if view_name:
                    payload_now = build_filter_payload(
                        search_query=str(st.session_state.get("ui_search_query", "")),
                        department_filter=str(st.session_state.get("ui_default_queue", "all")),
                        state_filter=str(st.session_state.get("ui_state_filter", "ALL")),
                        urgency_filter=str(st.session_state.get("ui_urgency_filter", "all")),
                        sla_filter=str(st.session_state.get("ui_sla_filter", "all")),
                        assigned_user_filter=str(st.session_state.get("ui_assigned_user_filter", "all")),
                        queue_scope=str(st.session_state.get("ui_queue_scope", "ALL")),
                        page_size=int(st.session_state.get("ui_page_size", 10)),
                    )
                    make_default = selected_saved_view_name != "__none__" and any(
                        int(v.get("is_default", 0)) == 1 and v["name"] == selected_saved_view_name for v in saved_views
                    )
                    ok_sv, msg_sv = upsert_saved_view(conn, current_user, view_name, payload_now, make_default)
                    if ok_sv:
                        append_audit_event(
                            action="saved_view_save",
                            result="success",
                            details={"name": view_name, "is_default": make_default},
                        )
                        st.rerun()
                    else:
                        append_audit_event(
                            action="saved_view_save",
                            result="failure" if msg_sv.startswith("DB_") else "denied",
                            details={"name": view_name, "reason": msg_sv},
                        )
                        render_mutation_error(msg_sv, arabic_default)
                else:
                    st.warning(bi("اسم العرض مطلوب.", "View name is required.", arabic_default))

            manage_cols = st.columns([1, 1, 4])
            if manage_cols[0].button(bi("افتراضي", "Set Default", arabic_default), key=f"{selected_nav}_saved_default"):
                if selected_saved_view_name != "__none__":
                    chosen = next((v for v in saved_views if v["name"] == selected_saved_view_name), None)
                    if chosen:
                        try:
                            filters_obj = json.loads(str(chosen["filters_json"]))
                        except json.JSONDecodeError:
                            filters_obj = {}
                        ok_df, msg_df = upsert_saved_view(conn, current_user, selected_saved_view_name, filters_obj, True)
                        if ok_df:
                            append_audit_event(
                                action="saved_view_default",
                                result="success",
                                details={"name": selected_saved_view_name},
                            )
                            st.rerun()
                        else:
                            append_audit_event(
                                action="saved_view_default",
                                result="failure" if msg_df.startswith("DB_") else "denied",
                                details={"name": selected_saved_view_name, "reason": msg_df},
                            )
                            render_mutation_error(msg_df, arabic_default)
            if manage_cols[1].button(bi("حذف", "Delete", arabic_default), key=f"{selected_nav}_saved_delete"):
                if selected_saved_view_name != "__none__":
                    chosen = next((v for v in saved_views if v["name"] == selected_saved_view_name), None)
                    if chosen:
                        ok_del, msg_del = delete_saved_view(conn, current_user, str(chosen["view_id"]))
                        if ok_del:
                            append_audit_event(
                                action="saved_view_delete",
                                result="success",
                                details={"name": selected_saved_view_name},
                            )
                            st.rerun()
                        else:
                            append_audit_event(
                                action="saved_view_delete",
                                result="failure" if msg_del.startswith("DB_") else "denied",
                                details={"name": selected_saved_view_name, "reason": msg_del},
                            )
                            render_mutation_error(msg_del, arabic_default)

            filters_cols = st.columns(6)
            queue_keys = list(queue_labels.keys())
            current_queue_key = st.session_state.get("ui_default_queue", "all")
            queue_index = queue_keys.index(current_queue_key) if current_queue_key in queue_keys else 0
            selected_queue = filters_cols[0].selectbox(
                bi("الطابور", "Department Queue", arabic_default),
                options=list(queue_labels.values()),
                index=queue_index,
            )
            selected_queue_key = {v: k for k, v in queue_labels.items()}[selected_queue]
            st.session_state["ui_default_queue"] = selected_queue_key
            selected_state = filters_cols[1].selectbox(
                bi("حالة دورة الحياة", "Lifecycle State", arabic_default),
                options=["ALL", *ALL_STATES],
                index=(["ALL", *ALL_STATES].index(st.session_state.get("ui_state_filter", "ALL"))
                       if st.session_state.get("ui_state_filter", "ALL") in ["ALL", *ALL_STATES] else 0),
            )
            st.session_state["ui_state_filter"] = selected_state
            selected_urgency = filters_cols[2].selectbox(
                bi("مرشح الأولوية", "Urgency Filter", arabic_default),
                options=list(urgency_labels.values()),
                index=list(urgency_labels.keys()).index(st.session_state.get("ui_urgency_filter", "all"))
                if st.session_state.get("ui_urgency_filter", "all") in urgency_labels
                else 0,
            )
            selected_urgency_key = {v: k for k, v in urgency_labels.items()}[selected_urgency]
            st.session_state["ui_urgency_filter"] = selected_urgency_key
            selected_sla = filters_cols[3].selectbox(
                bi("مرشح SLA", "SLA Filter", arabic_default),
                options=list(sla_labels.values()),
                index=list(sla_labels.keys()).index(st.session_state.get("ui_sla_filter", "all"))
                if st.session_state.get("ui_sla_filter", "all") in sla_labels
                else 0,
            )
            selected_sla_key = {v: k for k, v in sla_labels.items()}[selected_sla]
            st.session_state["ui_sla_filter"] = selected_sla_key
            assigned_users = sorted({str(c.get("assigned_user") or "") for c in cases if c.get("assigned_user")})
            assigned_labels = {
                "all": bi("الكل", "All", arabic_default),
                "unassigned": bi("غير مسند", "Unassigned", arabic_default),
                **{u: u for u in assigned_users},
            }
            selected_assigned = filters_cols[4].selectbox(
                bi("المسند إليه", "Assigned User", arabic_default),
                options=list(assigned_labels.values()),
                index=list(assigned_labels.keys()).index(st.session_state.get("ui_assigned_user_filter", "all"))
                if st.session_state.get("ui_assigned_user_filter", "all") in assigned_labels
                else 0,
            )
            selected_assigned_key = {v: k for k, v in assigned_labels.items()}[selected_assigned]
            st.session_state["ui_assigned_user_filter"] = selected_assigned_key
            selected_scope = filters_cols[5].selectbox(
                bi("نطاق العرض", "Queue Scope", arabic_default),
                options=list(scope_labels.values()),
                index=list(scope_labels.keys()).index(st.session_state.get("ui_queue_scope", "ALL"))
                if st.session_state.get("ui_queue_scope", "ALL") in scope_labels
                else 0,
            )
            selected_scope_key = {v: k for k, v in scope_labels.items()}[selected_scope]
            st.session_state["ui_queue_scope"] = selected_scope_key

        filtered_cases = filter_cases(
            cases,
            department_filter=selected_queue_key,
            state_filter=selected_state,
            urgency_filter=selected_urgency_key,
            sla_filter=selected_sla_key,
            assigned_user_filter=selected_assigned_key,
            queue_scope=selected_scope_key,
            search_query=str(st.session_state.get("ui_search_query", "")),
            current_user=current_user,
        )
        page_size = int(st.session_state.get("ui_page_size", 10))
        page_index = int(st.session_state.get("ui_page_index", 0))
        page_index, _ = render_pagination_controls(
            len(filtered_cases),
            page_size=page_size,
            page_index=page_index,
            key_prefix=f"{selected_nav}_cases",
            arabic_default=arabic_default,
        )
        st.session_state["ui_page_index"] = page_index
        paged_cases, safe_page_index = paginate_cases(
            filtered_cases,
            page_size=page_size,
            page_index=page_index,
        )
        st.session_state["ui_page_index"] = safe_page_index

        if not filtered_cases:
            st.warning(bi("لا توجد حالات مطابقة للمرشحات.", "No cases match current filters.", arabic_default))

        can_approve = has_permission("approve")
        can_override = has_permission("override")
        can_assign = has_permission("assign")
        can_transition = has_permission("transition")

        team_options = ["Immigration", "Municipal", "Licensing", "Human Review"]

        if selected_nav == "incoming":
            for idx, case in enumerate(paged_cases):
                urgency_kind = status_kind(str(case["urgency_en"]))
                selected_class = "selected" if case["case_id"] == st.session_state["selected_case_id"] else ""
                sla = compute_sla_state(case)
                sla_kind = "urgent" if sla["status"] == "BREACHED" else ("warning" if sla["status"] == "AT_RISK" else "ai")

                card_html = f"""
                <div class="triage-card {selected_class} {urgency_kind}">
                  <div class="request-text">{field(case, 'request_text', arabic_default)}</div>
                  <div class="meta-grid">
                    <div><span class="label">{bi('النية', 'Intent', arabic_default)}</span><br>{field(case, 'intent', arabic_default)}</div>
                    <div><span class="label">{icon_svg('clock')} {bi('الأولوية', 'Urgency', arabic_default)}</span><br>{badge_html(field(case, 'urgency', arabic_default), urgency_kind)}</div>
                    <div><span class="label">{icon_svg('building')} {bi('الإدارة', 'Department', arabic_default)}</span><br>{field(case, 'department', arabic_default)}</div>
                    <div><span class="label">{icon_svg('brain')} {bi('الثقة', 'Confidence', arabic_default)}</span><br>{badge_html(f"{case['confidence']:.{int(st.session_state['ui_confidence_precision'])}f}", 'ai')}</div>
                  </div>
                  <div class="explain">{bi('الحالة', 'State', arabic_default)}: {case['state']} | {bi('المسند إليه', 'Assigned', arabic_default)}: {case.get('assigned_user') or '-'}</div>
                  <div class="explain">{bi('SLA', 'SLA', arabic_default)}: {badge_html(sla['status'], sla_kind)} | {bi('المتبقي بالدقائق', 'Minutes Remaining', arabic_default)}: {sla['minutes_remaining']}</div>
                  <div class="explain">{bi('السبب', 'Reason', arabic_default)}: {field(case, 'reason', arabic_default)}</div>
                </div>
                """
                st.markdown(card_html, unsafe_allow_html=True)

                action_cols = st.columns([1.2, 1.2, 1.4, 4.2])
                approve_clicked = action_cols[0].button(
                    bi("اعتماد", "Approve", arabic_default),
                    key=f"approve_{case['case_id']}",
                    type="primary",
                    width="stretch",
                    disabled=not can_approve,
                )
                override_clicked = action_cols[1].button(
                    bi("تجاوز", "Override", arabic_default),
                    key=f"override_{case['case_id']}",
                    width="stretch",
                    disabled=not can_override,
                )
                select_clicked = action_cols[2].button(
                    bi("تحديد", "Select", arabic_default),
                    key=f"select_{case['case_id']}",
                    width="stretch",
                )

                if approve_clicked:
                    if require_active_action("approve", "approve", case_id=case["case_id"]):
                        ok, msg, _ = approve_case(
                            conn,
                            case_id=case["case_id"],
                            actor_user_id=current_user,
                            actor_role=role,
                            reason="approve_action",
                        )
                        if ok:
                            append_audit_event(action="approve", result="success", case_id=case["case_id"])
                            st.toast(bi("تم اعتماد الحالة", "Case approved", arabic_default))
                            st.rerun()
                        else:
                            append_audit_event(
                                action="approve",
                                result="failure" if msg.startswith("DB_") else "denied",
                                case_id=case["case_id"],
                                details={"reason": msg},
                            )
                            render_mutation_error(msg, arabic_default)

                if override_clicked:
                    if require_active_action("override", "override", case_id=case["case_id"]):
                        ok, msg, _ = override_case(
                            conn,
                            case_id=case["case_id"],
                            actor_user_id=current_user,
                            actor_role=role,
                            reason="override_action",
                        )
                        if ok:
                            append_audit_event(action="override", result="success", case_id=case["case_id"])
                            st.toast(bi("تم التحويل للمراجعة البشرية", "Sent to human review", arabic_default))
                            st.rerun()
                        else:
                            append_audit_event(
                                action="override",
                                result="failure" if msg.startswith("DB_") else "denied",
                                case_id=case["case_id"],
                                details={"reason": msg},
                            )
                            render_mutation_error(msg, arabic_default)

                if select_clicked:
                    if require_active_action("select", "select", case_id=case["case_id"]):
                        ok, msg = record_case_select(
                            conn,
                            case_id=case["case_id"],
                            actor_user_id=current_user,
                            actor_role=role,
                        )
                        if ok:
                            st.session_state["selected_case_id"] = case["case_id"]
                            append_audit_event(action="select", result="success", case_id=case["case_id"])
                            st.rerun()
                        else:
                            append_audit_event(
                                action="select",
                                result="failure" if msg.startswith("DB_") else "denied",
                                case_id=case["case_id"],
                                details={"reason": msg},
                            )
                            render_mutation_error(msg, arabic_default)

                if case["case_id"] == st.session_state["selected_case_id"]:
                    with action_cols[3]:
                        st.markdown(f"**{bi('إجراءات التشغيل', 'Operational Controls', arabic_default)}**")
                        ac1, ac2 = st.columns(2)
                        team_selected = ac1.selectbox(
                            bi("تعيين فريق", "Assign Team", arabic_default),
                            options=team_options,
                            key=f"team_{case['case_id']}",
                            index=team_options.index(case.get("assigned_team") or case["department_en"]) if (case.get("assigned_team") or case["department_en"]) in team_options else 0,
                            disabled=not can_assign,
                        )
                        assignee_value = ac2.text_input(
                            bi("المستخدم المسند", "Assigned User", arabic_default),
                            value=case.get("assigned_user") or "",
                            key=f"assignee_{case['case_id']}",
                            disabled=not can_assign,
                        )
                        assign_clicked = st.button(
                            bi("تحديث الإسناد", "Update Assignment", arabic_default),
                            key=f"assign_btn_{case['case_id']}",
                            disabled=not can_assign,
                        )
                        if assign_clicked:
                            if require_active_action("assign", "assign_case", case_id=case["case_id"]):
                                ok, msg, _ = assign_case(
                                    conn,
                                    case_id=case["case_id"],
                                    assigned_team=team_selected,
                                    assigned_user=assignee_value.strip() or None,
                                    actor_user_id=current_user,
                                    actor_role=role,
                                    reason="manual_assignment",
                                )
                                if ok:
                                    append_audit_event(
                                        action="assign_case",
                                        result="success",
                                        case_id=case["case_id"],
                                        details={"assigned_team": team_selected, "assigned_user": assignee_value.strip() or None},
                                    )
                                    st.toast(bi("تم تحديث الإسناد", "Assignment updated", arabic_default))
                                    st.rerun()
                                else:
                                    append_audit_event(
                                        action="assign_case",
                                        result="failure" if msg.startswith("DB_") else "denied",
                                        case_id=case["case_id"],
                                        details={"reason": msg},
                                    )
                                    render_mutation_error(msg, arabic_default)

                        allowed_next = get_allowed_next_states(role, str(case["state"]))
                        if allowed_next:
                            ns1, ns2 = st.columns(2)
                            next_state = ns1.selectbox(
                                bi("الحالة التالية", "Next State", arabic_default),
                                options=allowed_next,
                                key=f"next_state_{case['case_id']}",
                                disabled=not can_transition,
                            )
                            state_reason = ns2.text_input(
                                bi("سبب الانتقال", "Transition Reason", arabic_default),
                                key=f"state_reason_{case['case_id']}",
                                value="manual_transition",
                                disabled=not can_transition,
                            )
                            transition_clicked = st.button(
                                bi("تطبيق الانتقال", "Apply Transition", arabic_default),
                                key=f"transition_btn_{case['case_id']}",
                                disabled=not can_transition,
                            )
                            if transition_clicked:
                                if require_active_action("transition", "state_transition", case_id=case["case_id"]):
                                    ok, msg, _ = transition_case_state(
                                        conn,
                                        case_id=case["case_id"],
                                        to_state=next_state,
                                        actor_user_id=current_user,
                                        actor_role=role,
                                        reason=state_reason.strip() or None,
                                    )
                                    if ok:
                                        append_audit_event(
                                            action="state_transition",
                                            result="success",
                                            case_id=case["case_id"],
                                            details={"to_state": next_state, "reason": state_reason.strip() or None},
                                        )
                                        st.toast(bi("تم تحديث الحالة", "State updated", arabic_default))
                                        st.rerun()
                                    else:
                                        append_audit_event(
                                            action="state_transition",
                                            result="failure" if msg.startswith("DB_") else "denied",
                                            case_id=case["case_id"],
                                            details={"reason": msg, "to_state": next_state},
                                        )
                                        render_mutation_error(msg, arabic_default)

                if idx < len(paged_cases) - 1:
                    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)

            st.caption(
                bi(
                    "اعرض الجدول التشغيلي الكامل من صفحة الطوابير.",
                    "Use the Queues page for the full operational table view.",
                    arabic_default,
                )
            )
        else:
            st.caption(
                bi(
                    "شاشة الطوابير تعرض الحالات المفلترة مع SLA وحالة دورة الحياة.",
                    "Queue screen shows filtered cases with SLA and lifecycle status.",
                    arabic_default,
                )
            )
            render_case_table(paged_cases, arabic_default)
            st.download_button(
                label=bi("تصدير CSV (حسب المرشحات)", "Export CSV (Filtered)", arabic_default),
                data=cases_to_csv_bytes(filtered_cases, arabic_default),
                file_name="queue_filtered_export.csv",
                mime="text/csv",
                width="stretch",
            )

            selected_bulk_ids = st.multiselect(
                bi("تحديد حالات لإجراءات جماعية", "Select Cases for Bulk Actions", arabic_default),
                options=[str(c["case_id"]) for c in filtered_cases],
                default=sorted(st.session_state.get("ui_selected_case_ids", set())),
                key="bulk_selected_ids",
            )
            st.session_state["ui_selected_case_ids"] = set(selected_bulk_ids)
            if selected_bulk_ids and (can_assign or can_transition):
                bulk_cols = st.columns(4)
                bulk_team = bulk_cols[0].selectbox(
                    bi("فريق التعيين", "Assign Team", arabic_default),
                    options=team_options,
                    key="bulk_assign_team",
                )
                bulk_user = bulk_cols[1].text_input(
                    bi("المستخدم", "User", arabic_default),
                    key="bulk_assign_user",
                ).strip() or None
                bulk_state = bulk_cols[2].selectbox(
                    bi("الحالة الهدف", "Target State", arabic_default),
                    options=list(ALL_STATES),
                    key="bulk_target_state",
                )
                if bulk_cols[3].button(bi("تنفيذ جماعي", "Run Bulk", arabic_default), key="bulk_run_btn"):
                    ok_count = 0
                    fail_count = 0
                    for cid in selected_bulk_ids:
                        if can_assign:
                            ok_b, msg_b, _ = assign_case(
                                conn,
                                case_id=cid,
                                assigned_team=bulk_team,
                                assigned_user=bulk_user,
                                actor_user_id=current_user,
                                actor_role=role,
                                reason="bulk_assignment",
                            )
                            append_audit_event(
                                action="bulk_assign_case",
                                result="success" if ok_b else ("failure" if msg_b.startswith("DB_") else "denied"),
                                case_id=cid,
                                details={"assigned_team": bulk_team, "assigned_user": bulk_user, "reason": msg_b if not ok_b else None},
                            )
                            ok_count += 1 if ok_b else 0
                            fail_count += 0 if ok_b else 1
                        if can_transition:
                            ok_t, msg_t, _ = transition_case_state(
                                conn,
                                case_id=cid,
                                to_state=bulk_state,
                                actor_user_id=current_user,
                                actor_role=role,
                                reason="bulk_transition",
                            )
                            append_audit_event(
                                action="bulk_state_transition",
                                result="success" if ok_t else ("failure" if msg_t.startswith("DB_") else "denied"),
                                case_id=cid,
                                details={"to_state": bulk_state, "reason": msg_t if not ok_t else None},
                            )
                            ok_count += 1 if ok_t else 0
                            fail_count += 0 if ok_t else 1
                    st.toast(
                        bi(
                            f"نجاح: {ok_count} | فشل: {fail_count}",
                            f"Success: {ok_count} | Failed: {fail_count}",
                            arabic_default,
                        )
                    )
                    st.rerun()

    with right_col:
        st.markdown(f"### {bi('لوحة تفسير الذكاء الاصطناعي', 'AI Explanation Panel', arabic_default)}")
        trace_html = f"""
        <div class="panel">
          <div class="panel-title">{bi('مسار القرار', 'Decision Trace', arabic_default)}</div>
          <div class="trace-row"><span>{bi('الكلمات المكتشفة', 'Detected keywords', arabic_default)}</span><strong>{field(selected_case, 'detected_keywords', arabic_default)}</strong></div>
          <div class="trace-row"><span>{bi('الإشارة الزمنية', 'Detected time signal', arabic_default)}</span><strong>{field(selected_case, 'detected_time', arabic_default)}</strong></div>
          <div class="trace-row"><span>{bi('قاعدة السياسة', 'Policy rule', arabic_default)}</span><strong>{selected_case['policy_rule']}</strong></div>
          <div class="trace-row"><span>{bi('الثقة', 'Confidence', arabic_default)}</span><strong>{badge_html(f"{selected_case['confidence']:.{int(st.session_state['ui_confidence_precision'])}f}", 'ai')}</strong></div>
          <div class="trace-row"><span>{bi('نوع الإجراء', 'Action Type', arabic_default)}</span><strong>{selected_case['state']}</strong></div>
        </div>
        """
        st.markdown(trace_html, unsafe_allow_html=True)

        st.markdown(f"### {bi('الخط الزمني للحالة', 'Case Timeline', arabic_default)}")
        timeline_events = list_case_workflow_events(conn, str(selected_case["case_id"]), limit=10)
        if timeline_events:
            timeline_rows = [
                {
                    bi("الوقت", "Time", arabic_default): e["timestamp_utc"],
                    bi("الإجراء", "Event", arabic_default): e["event_type"],
                    bi("المنفذ", "Actor", arabic_default): f'{e["actor_user_id"]} ({e["actor_role"]})',
                    bi("الانتقال", "Transition", arabic_default): f'{e.get("from_state") or "-"} -> {e.get("to_state") or "-"}',
                }
                for e in timeline_events
            ]
            st.dataframe(timeline_rows, width="stretch", hide_index=True)
        else:
            st.caption(bi("لا توجد أحداث بعد.", "No timeline events yet.", arabic_default))

        if has_permission("reveal_pii") and st.session_state.get("security_privacy_masking_enabled", True):
            st.markdown(f"#### {bi('إظهار الحقول الحساسة', 'Reveal Sensitive Fields', arabic_default)}")
            reveal_reason = st.text_input(
                bi("سبب الإظهار", "Reveal reason", arabic_default),
                key="reveal_reason",
            )
            if st.button(bi("إظهار الحالة المحددة", "Reveal Selected Case", arabic_default), width="stretch"):
                if not reveal_reason.strip():
                    st.warning(bi("السبب مطلوب قبل الإظهار.", "Reason is required before reveal.", arabic_default))
                elif not require_active_action("reveal_pii", "pii_reveal", case_id=str(selected_case["case_id"])):
                    pass
                else:
                    revealed = set(st.session_state.get("revealed_case_ids", set()))
                    revealed.add(str(selected_case["case_id"]))
                    st.session_state["revealed_case_ids"] = revealed
                    append_audit_event(
                        action="pii_reveal",
                        result="success",
                        case_id=str(selected_case["case_id"]),
                        details={"reason": reveal_reason.strip()},
                    )
                    st.rerun()
        elif st.session_state.get("security_privacy_masking_enabled", True):
            st.caption(bi("إظهار البيانات الحساسة متاح للمشرف فقط.", "Sensitive data reveal is supervisor-only.", arabic_default))

        st.markdown(f"### {bi('مبادئ الوصول', 'Accessibility', arabic_default)}")
        st.markdown(
            "\n".join(
                [
                    f"- {bi('تباين ألوان متوافق مع AA', 'AA color contrast compliance', arabic_default)}",
                    f"- {bi('وسوم نصية بجانب الألوان', 'Text labels alongside color signals', arabic_default)}",
                    f"- {bi('دعم اتجاه RTL وLTR', 'RTL/LTR layout parity', arabic_default)}",
                    f"- {bi('وضوح تسميات سير العمل', 'Clear workflow labels for operators', arabic_default)}",
                ]
            )
        )

elif selected_nav == "review":
    with main_col:
        render_page_header(
            "مراجعة التشغيل",
            "Operational Review",
            "ركز على التصعيدات والثقة المنخفضة وحالات التجاوز.",
            "Focus on escalations, low-confidence cases, and overrides.",
            arabic_default,
        )
        escalations = filter_cases(
            list_pending_escalations(conn),
            department_filter=str(st.session_state.get("ui_default_queue", "all")),
            state_filter=str(st.session_state.get("ui_state_filter", "ALL")),
            urgency_filter=str(st.session_state.get("ui_urgency_filter", "all")),
            sla_filter=str(st.session_state.get("ui_sla_filter", "all")),
            assigned_user_filter=str(st.session_state.get("ui_assigned_user_filter", "all")),
            queue_scope=str(st.session_state.get("ui_queue_scope", "ALL")),
            search_query=str(st.session_state.get("ui_search_query", "")),
            current_user=current_user,
        )
        low_confidence = filter_cases(
            list_low_confidence(conn, threshold=0.75),
            department_filter=str(st.session_state.get("ui_default_queue", "all")),
            state_filter=str(st.session_state.get("ui_state_filter", "ALL")),
            urgency_filter=str(st.session_state.get("ui_urgency_filter", "all")),
            sla_filter=str(st.session_state.get("ui_sla_filter", "all")),
            assigned_user_filter=str(st.session_state.get("ui_assigned_user_filter", "all")),
            queue_scope=str(st.session_state.get("ui_queue_scope", "ALL")),
            search_query=str(st.session_state.get("ui_search_query", "")),
            current_user=current_user,
        )
        recent_overrides = list_recent_overrides(conn, limit=25)

        st.markdown(f"#### {bi('التصعيدات المعلقة', 'Pending Escalations', arabic_default)}")
        esc_page = int(st.session_state.get("review_escalations_page", 0))
        esc_page, _ = render_pagination_controls(
            len(escalations),
            page_size=int(st.session_state.get("ui_page_size", 10)),
            page_index=esc_page,
            key_prefix="review_escalations",
            arabic_default=arabic_default,
        )
        st.session_state["review_escalations_page"] = esc_page
        paged_escalations, _ = paginate_cases(
            escalations,
            page_size=int(st.session_state.get("ui_page_size", 10)),
            page_index=esc_page,
        )
        render_case_table(paged_escalations, arabic_default)

        st.markdown(f"#### {bi('حالات منخفضة الثقة', 'Low-Confidence Cases', arabic_default)}")
        low_page = int(st.session_state.get("review_low_page", 0))
        low_page, _ = render_pagination_controls(
            len(low_confidence),
            page_size=int(st.session_state.get("ui_page_size", 10)),
            page_index=low_page,
            key_prefix="review_low",
            arabic_default=arabic_default,
        )
        st.session_state["review_low_page"] = low_page
        paged_low_confidence, _ = paginate_cases(
            low_confidence,
            page_size=int(st.session_state.get("ui_page_size", 10)),
            page_index=low_page,
        )
        render_case_table(paged_low_confidence, arabic_default)

        st.markdown(f"#### {bi('أحدث التجاوزات', 'Recent Overrides', arabic_default)}")
        st.dataframe(recent_overrides, width="stretch", hide_index=True)
        st.download_button(
            label=bi("تصدير CSV للمراجعة", "Export Review CSV", arabic_default),
            data=cases_to_csv_bytes([*escalations, *low_confidence], arabic_default),
            file_name="review_filtered_export.csv",
            mime="text/csv",
            width="stretch",
        )

        if has_permission("review_actions"):
            st.markdown(f"### {bi('إجراءات المشرف', 'Supervisor Actions', arabic_default)}")
            target_options = [c["case_id"] for c in escalations] or [selected_case["case_id"]]
            target_case_id = st.selectbox(
                bi("اختر حالة", "Choose Case", arabic_default),
                options=target_options,
            )
            action = st.selectbox(
                bi("الإجراء", "Action", arabic_default),
                options=[
                    "confirm_route",
                    "reroute",
                    "return_to_operator",
                    "escalate_policy_exception",
                ],
            )
            reroute_team = st.selectbox(
                bi("فريق إعادة التوجيه", "Reroute Team", arabic_default),
                options=["Immigration", "Municipal", "Licensing", "Human Review"],
            )
            action_reason = st.text_input(
                bi("السبب", "Reason", arabic_default),
                value="review_action",
            )

            if st.button(bi("تنفيذ الإجراء", "Run Action", arabic_default), type="primary"):
                action_ok = False
                action_msg = ""
                if require_active_action("review_actions", "review_action", case_id=target_case_id):
                    if action == "confirm_route":
                        action_ok, action_msg, _ = transition_case_state(
                            conn,
                            case_id=target_case_id,
                            to_state="IN_PROGRESS",
                            actor_user_id=current_user,
                            actor_role=role,
                            reason=action_reason,
                        )
                    elif action == "reroute":
                        action_ok, action_msg, _ = assign_case(
                            conn,
                            case_id=target_case_id,
                            assigned_team=reroute_team,
                            assigned_user=None,
                            actor_user_id=current_user,
                            actor_role=role,
                            reason=action_reason,
                        )
                    elif action == "return_to_operator":
                        action_ok, action_msg, _ = transition_case_state(
                            conn,
                            case_id=target_case_id,
                            to_state="ASSIGNED",
                            actor_user_id=current_user,
                            actor_role=role,
                            reason=action_reason,
                        )
                    elif action == "escalate_policy_exception":
                        action_ok, action_msg, _ = transition_case_state(
                            conn,
                            case_id=target_case_id,
                            to_state="ESCALATED",
                            actor_user_id=current_user,
                            actor_role=role,
                            reason=action_reason,
                        )

                if action_ok:
                    append_audit_event(
                        action="review_action",
                        result="success",
                        case_id=target_case_id,
                        details={"action": action, "reason": action_reason},
                    )
                    st.toast(bi("تم تنفيذ الإجراء", "Action executed", arabic_default))
                    st.rerun()
                else:
                    if action_msg:
                        append_audit_event(
                            action="review_action",
                            result="failure" if action_msg.startswith("DB_") else "denied",
                            case_id=target_case_id,
                            details={"action": action, "reason": action_reason, "error": action_msg},
                        )
                        render_mutation_error(action_msg, arabic_default)
        else:
            st.info(bi("إجراءات المراجعة متاحة للمشرف فقط.", "Review actions are supervisor-only.", arabic_default))

    with right_col:
        audit_events = read_audit_events()
        kpis = compute_operational_kpis(cases, audit_events)
        st.markdown(f"### {bi('مؤشرات التشغيل', 'Operations KPIs', arabic_default)}")
        st.markdown(
            "\n".join(
                [
                    f"- {bi('متوسط زمن الفرز', 'Avg time to triage', arabic_default)}: {kpis['avg_time_to_triage_minutes']:.1f} {bi('دقيقة', 'min', arabic_default)}",
                    f"- {bi('متوسط زمن أول إسناد', 'Avg time to first assignment', arabic_default)}: {kpis['avg_time_to_first_assignment_minutes']:.1f} {bi('دقيقة', 'min', arabic_default)}",
                    f"- {bi('نسبة تجاوز SLA', 'SLA breached %', arabic_default)}: {kpis['sla_breached_pct']:.1f}%",
                    f"- {bi('معدل التجاوز', 'Override rate', arabic_default)}: {kpis['override_rate_pct']:.1f}%",
                    f"- {bi('حجم المراجعة البشرية', 'Human review volume', arabic_default)}: {int(kpis['human_review_volume'])}",
                ]
            )
        )

elif selected_nav == "assistant":
    with main_col:
        render_page_header(
            "المساعد المعرفي الموجه للسياسات",
            "Domain RAG Assistant",
            "اطرح سؤالاً تشغيلياً أو سياسياً لتحصل على إجابة موثقة بمراجع مسترجعة.",
            "Ask an operational or policy question and get a grounded answer with retrieved citations.",
            arabic_default,
        )
        try:
            kb_index = build_index(str(DOMAIN_KB_PATH), "ar" if arabic_default else "en")
            knowledge_manifest = build_knowledge_manifest(DOMAIN_KB_PATH, KNOWLEDGE_MANIFEST_PATH)
            rag_eval = run_rag_evaluation(
                eval_path=RAG_EVAL_PATH,
                data_path=DOMAIN_KB_PATH,
                language="ar" if arabic_default else "en",
            )
            st.caption(
                bi(
                    f"قاعدة المعرفة جاهزة: {len(kb_index['chunks'])} مقطع مسترجع.",
                    f"Knowledge base ready: {len(kb_index['chunks'])} indexed chunks.",
                    arabic_default,
                )
            )
        except RagConfigError as exc:
            st.error(
                bi(
                    f"فشل تحميل قاعدة المعرفة: {exc}",
                    f"Knowledge base configuration error: {exc}",
                    arabic_default,
                )
            )
            append_audit_event(
                action="rag_query",
                result="failure",
                details={"reason": "kb_config_error", "error": str(exc)[:180]},
            )
            st.stop()

        sample_queries = [
            (
                "sample_rag_1",
                "اقامتي تنتهي غداً وأحتاج تجديداً عاجلاً",
                "My residency expires tomorrow and I need urgent renewal",
            ),
            (
                "sample_rag_2",
                "ما هي مهلة SLA للحالات العاجلة ومتى تعتبر متجاوزة؟",
                "What is the SLA for urgent cases and when do they become breached?",
            ),
            (
                "sample_rag_3",
                "طلب رخصة تجارية جديدة في المنطقة الصناعية هذا الأسبوع",
                "Request for a new commercial shop license in the industrial area this week",
            ),
        ]
        dept_options = ["AUTO", "all", "Immigration", "Municipal", "Licensing", "Human Review", "Operations"]
        dept_labels = {
            "AUTO": bi("تلقائي من الحالة المحددة", "Auto from selected case", arabic_default),
            "all": bi("بدون تقييد", "No department filter", arabic_default),
            "Immigration": bi("الهجرة", "Immigration", arabic_default),
            "Municipal": bi("البلدية", "Municipal", arabic_default),
            "Licensing": bi("الترخيص", "Licensing", arabic_default),
            "Human Review": bi("مراجعة بشرية", "Human Review", arabic_default),
            "Operations": bi("العمليات", "Operations", arabic_default),
        }

        assistant_ask_tab, assistant_results_tab, assistant_knowledge_tab = st.tabs(
            [
                bi("اسأل", "Ask", arabic_default),
                bi("النتائج", "Results", arabic_default),
                bi("المعرفة", "Knowledge", arabic_default),
            ]
        )
        with assistant_ask_tab:
            st.info(
                bi(
                    "للعرض السريع: جرّب الاستعلامات الثلاثة، وسجّل الدخول كمشرف لمراجعة الحوكمة والإدارة، ثم افتح أثر الاسترجاع.",
                    "For a fast demo: run the three sample queries, sign in as supervisor to review governance/admin, then open the retrieval trace.",
                    arabic_default,
                )
            )
            st.markdown(f"#### {bi('استعلامات سريعة', 'Quick Queries', arabic_default)}")
            for sample_id, query_ar, query_en in sample_queries:
                sample_label = query_ar if arabic_default else query_en
                if st.button(sample_label, key=sample_id, width="stretch"):
                    st.session_state["rag_query"] = sample_label
                    st.session_state["rag_last_result"] = None
                    st.rerun()

            with st.expander(bi("إعدادات AI", "AI Runtime Settings", arabic_default), expanded=False):
                runtime_api_key = st.text_input(
                    bi("OpenAI API Key (جلسة مؤقتة)", "OpenAI API Key (session only)", arabic_default),
                    value=str(st.session_state.get("ai_runtime_api_key", "")),
                    type="password",
                    key="ai_runtime_api_key_input",
                ).strip()
                st.session_state["ai_runtime_api_key"] = runtime_api_key
                model_cols = st.columns(2)
                st.session_state["ai_runtime_model"] = model_cols[0].text_input(
                    bi("نموذج الإجابة", "Answer model", arabic_default),
                    value=str(st.session_state.get("ai_runtime_model", "gpt-4o-mini")),
                    key="ai_runtime_model_input",
                ).strip() or "gpt-4o-mini"
                st.session_state["ai_runtime_embedding_model"] = model_cols[1].text_input(
                    bi("نموذج التمثيل المتجهي", "Embedding model", arabic_default),
                    value=str(st.session_state.get("ai_runtime_embedding_model", "text-embedding-3-small")),
                    key="ai_runtime_embedding_model_input",
                ).strip() or "text-embedding-3-small"

                secret_key_exists = bool(str(st.secrets.get("openai_api_key", "")).strip())
                effective_key = runtime_api_key or str(st.secrets.get("openai_api_key", "")).strip()
                st.caption(
                    bi(
                        "وضع AI: مفعل" if effective_key else "وضع AI: غير مفعل (سيستخدم الاسترجاع المحلي فقط)",
                        "AI mode: ON" if effective_key else "AI mode: OFF (local retrieval fallback only)",
                        arabic_default,
                    )
                )
                if not runtime_api_key and secret_key_exists:
                    st.caption(
                        bi(
                            "يتم استخدام مفتاح OpenAI من أسرار التطبيق.",
                            "Using OpenAI key from app secrets.",
                            arabic_default,
                        )
                    )
                st.caption(
                    bi(
                        "أي مفتاح API يتم إدخاله هنا يبقى ضمن الجلسة الحالية فقط ولا يحفظ كإعداد دائم داخل التطبيق.",
                        "Any API key entered here is used for the current session only and is not stored as a permanent in-app setting.",
                        arabic_default,
                    )
                )
                effective_key = str(effective_key).strip()
                key_ok, key_error = (
                    validate_api_key_format(effective_key) if effective_key else (False, "OPENAI_API_KEY missing")
                )
                if effective_key and not key_ok:
                    st.warning(bi(f"مشكلة في المفتاح: {key_error}", f"API key issue: {key_error}", arabic_default))

                test_cols = st.columns([1.4, 3.6])
                if test_cols[0].button(bi("اختبار AI", "Test AI", arabic_default), key="ai_runtime_test_btn"):
                    if not effective_key:
                        st.session_state["ai_runtime_test_result"] = {
                            "ok": False,
                            "embedding_ok": False,
                            "chat_ok": False,
                            "error": "OPENAI_API_KEY missing",
                        }
                    else:
                        st.session_state["ai_runtime_test_result"] = test_openai_runtime(
                            api_key=effective_key,
                            answer_model=str(st.session_state.get("ai_runtime_model", "gpt-4o-mini")),
                            embedding_model=str(
                                st.session_state.get("ai_runtime_embedding_model", "text-embedding-3-small")
                            ),
                        )
                runtime_test = st.session_state.get("ai_runtime_test_result")
                if runtime_test:
                    if runtime_test.get("ok"):
                        test_cols[1].success(
                            bi(
                                "اتصال OpenAI ناجح: التضمين والإجابة يعملان.",
                                "OpenAI connectivity passed: embeddings and answer model both work.",
                                arabic_default,
                            )
                        )
                    else:
                        failure_bits = [
                            str(runtime_test.get("error") or ""),
                            str(runtime_test.get("embedding_error") or ""),
                            str(runtime_test.get("chat_error") or ""),
                        ]
                        failure_message = " | ".join(bit for bit in failure_bits if bit)
                        test_cols[1].error(
                            bi(
                                f"فشل اختبار AI: {failure_message or 'unknown error'}",
                                f"AI runtime test failed: {failure_message or 'unknown error'}",
                                arabic_default,
                            )
                        )

            q_cols = st.columns([4, 1.2, 1.6, 1.1])
            st.session_state["rag_query"] = q_cols[0].text_input(
                bi("اسأل سؤالاً تشغيلياً أو سياسياً", "Ask an operational or policy question", arabic_default),
                value=str(st.session_state.get("rag_query", "")),
                key="rag_query_input",
            )
            st.session_state["rag_top_k"] = int(
                q_cols[1].selectbox(
                    bi("Top K", "Top K", arabic_default),
                    options=[3, 5, 8],
                    index=[3, 5, 8].index(int(st.session_state.get("rag_top_k", 5)))
                    if int(st.session_state.get("rag_top_k", 5)) in [3, 5, 8]
                    else 1,
                    key="rag_top_k_input",
                )
            )
            st.session_state["rag_department_hint"] = q_cols[2].selectbox(
                bi("تقييد الإدارة", "Department scope", arabic_default),
                options=dept_options,
                format_func=lambda v: dept_labels.get(v, v),
                index=dept_options.index(str(st.session_state.get("rag_department_hint", "AUTO")))
                if str(st.session_state.get("rag_department_hint", "AUTO")) in dept_options
                else 0,
                key="rag_department_hint_input",
            )
            ask_clicked = q_cols[3].button(bi("استرجاع", "Retrieve", arabic_default), key="rag_ask_btn")

        if ask_clicked:
            query_text = str(st.session_state.get("rag_query", "")).strip()
            if not query_text:
                st.warning(bi("أدخل سؤالاً أولاً.", "Enter a question first.", arabic_default))
            else:
                allowed_query, rate_limit_message = enforce_rag_rate_limit()
                if not allowed_query:
                    st.warning(bi(f"تم تقييد الطلب: {rate_limit_message}", f"Request throttled: {rate_limit_message}", arabic_default))
                else:
                    department_hint = str(st.session_state.get("rag_department_hint", "AUTO"))
                    if department_hint == "AUTO":
                        department_hint = str(selected_case.get("department_en", "")) if selected_case else ""
                    if department_hint == "all":
                        department_hint = ""
                    openai_api_key = str(st.session_state.get("ai_runtime_api_key", "")).strip() or str(
                        st.secrets.get("openai_api_key", "")
                    ).strip()
                    openai_model = str(st.session_state.get("ai_runtime_model", "gpt-4o-mini")).strip() or str(
                        st.secrets.get("openai_model", "gpt-4o-mini")
                    ).strip()
                    openai_embedding_model = str(
                        st.session_state.get("ai_runtime_embedding_model", "text-embedding-3-small")
                    ).strip() or str(st.secrets.get("openai_embedding_model", "text-embedding-3-small")).strip()
                    try:
                        result = answer_question(
                            query=query_text,
                            data_path=DOMAIN_KB_PATH,
                            language="ar" if arabic_default else "en",
                            top_k=int(st.session_state.get("rag_top_k", 5)),
                            department_hint=department_hint or None,
                            openai_api_key=openai_api_key or None,
                            openai_model=openai_model,
                            openai_embedding_model=openai_embedding_model,
                        )
                        st.session_state["rag_last_result"] = result
                        query_hash = hashlib.sha256(query_text.encode("utf-8")).hexdigest()[:12]
                        append_audit_event(
                            action="rag_query",
                            result="success",
                            case_id=str(selected_case.get("case_id", "")),
                            details={
                                "query_hash": query_hash,
                                "hits": len(result.get("hits", [])),
                                "used_llm": bool(result.get("used_llm")),
                                "ai_mode": "openai" if openai_api_key else "local",
                                "answer_model": openai_model if openai_api_key else "local_fallback",
                                "embedding_model": openai_embedding_model if openai_api_key else "tfidf",
                                "department_hint": department_hint or "none",
                                "top_k": int(st.session_state.get("rag_top_k", 5)),
                            },
                        )
                    except Exception as exc:  # pragma: no cover - runtime protection
                        append_audit_event(
                            action="rag_query",
                            result="failure",
                            case_id=str(selected_case.get("case_id", "")),
                            details={"reason": "runtime_error", "error": str(exc)[:180]},
                        )
                        st.error(
                            bi(
                                f"تعذر تنفيذ الاسترجاع: {exc}",
                                f"Retrieval failed: {exc}",
                                arabic_default,
                            )
                        )

        result = st.session_state.get("rag_last_result")
        with assistant_results_tab:
            if result:
                comparison_cols = st.columns(2)
                with comparison_cols[0]:
                    st.markdown(f"#### {bi('بدون استرجاع', 'Without Retrieval', arabic_default)}")
                    st.write(baseline_answer(str(st.session_state.get("rag_query", "")), "ar" if arabic_default else "en"))
                with comparison_cols[1]:
                    st.markdown(f"#### {bi('مع RAG', 'With RAG', arabic_default)}")
                    st.write(
                        bi(
                            "إجابة مؤرضة بالمصادر المسترجعة مع تتبع قرار واضح.",
                            "Grounded answer using retrieved sources with a clear decision trace.",
                            arabic_default,
                        )
                    )

                st.markdown(f"#### {bi('الإجابة', 'Answer', arabic_default)}")
                st.write(str(result.get("answer", "")))
                if result.get("policy_blocked"):
                    st.warning(
                        bi(
                            "تم حظر هذا الطلب لأن المساعد لا ينفذ إجراءات تشغيلية أو يكشف بيانات حساسة.",
                            "This request was blocked because the assistant cannot execute workflow actions or reveal sensitive data.",
                            arabic_default,
                        )
                    )
                if result.get("llm_error"):
                    st.caption(
                        bi(
                            f"ملاحظة LLM: {result['llm_error']}",
                            f"LLM note: {result['llm_error']}",
                            arabic_default,
                        )
                    )

                hits = list(result.get("hits", []))
                if hits:
                    st.markdown(f"#### {bi('المراجع المسترجعة', 'Retrieved Sources', arabic_default)}")
                    st.dataframe(
                        [
                            {
                                bi("الترتيب", "Rank", arabic_default): h.get("rank"),
                                bi("الوثيقة", "Document", arabic_default): h.get("doc_id"),
                                bi("المقطع", "Chunk", arabic_default): h.get("chunk_id"),
                                bi("العنوان", "Title", arabic_default): h.get("title"),
                                bi("الإدارة", "Department", arabic_default): h.get("department"),
                                bi("القاعدة", "Policy Rule", arabic_default): h.get("policy_rule"),
                                "Score": h.get("rerank_score"),
                            }
                            for h in hits
                        ],
                        width="stretch",
                        hide_index=True,
                    )
                    for h in hits:
                        with st.expander(
                            f"#{h.get('rank')} {h.get('doc_id')} / {h.get('chunk_id')} - {h.get('title')}",
                            expanded=False,
                        ):
                            st.write(str(h.get("text", "")))
                            st.caption(
                                bi(
                                    f"درجة الاسترجاع: {h.get('base_score')} | درجة إعادة الترتيب: {h.get('rerank_score')}",
                                    f"Base score: {h.get('base_score')} | Rerank score: {h.get('rerank_score')}",
                                    arabic_default,
                                )
                            )
            else:
                st.info(
                    bi(
                        "نفذ سؤالاً أولاً لعرض مقارنة الإجابة والمراجع المسترجعة.",
                        "Run a query first to view the answer comparison and retrieved sources.",
                        arabic_default,
                    )
                )

        with assistant_knowledge_tab:
            st.markdown(f"#### {bi('مصادر المعرفة', 'Knowledge Sources', arabic_default)}")
            st.caption(
                bi(
                    f"آخر تحديث للمعرفة: {knowledge_manifest['last_refresh_utc']}",
                    f"Knowledge last refresh: {knowledge_manifest['last_refresh_utc']}",
                    arabic_default,
                )
            )
            st.dataframe(
                [
                    {
                        bi("الوثيقة", "Document", arabic_default): row["document_id"],
                        bi("العنوان", "Title", arabic_default): row["title_ar"] if arabic_default else row["title_en"],
                        bi("النطاق", "Department Scope", arabic_default): row["department_scope"],
                        bi("الإصدار", "Version", arabic_default): row["version"],
                        bi("المقاطع", "Chunks", arabic_default): row["chunk_count"],
                    }
                    for row in knowledge_manifest["documents"]
                ],
                width="stretch",
                hide_index=True,
            )

    with right_col:
        policy = capability_guide("ar" if arabic_default else "en")
        assistant_side_eval_tab, assistant_side_guide_tab, assistant_side_trace_tab = st.tabs(
            [
                bi("التقييم", "Evaluation", arabic_default),
                bi("الدليل", "Guide", arabic_default),
                bi("التتبع", "Trace", arabic_default),
            ]
        )
        with assistant_side_eval_tab:
            st.markdown(f"### {bi('تقييم RAG', 'RAG Evaluation', arabic_default)}")
            st.markdown(
                "\n".join(
                    [
                        f"- {bi('الحالات المختبرة', 'Benchmarks', arabic_default)}: {rag_eval['total']}",
                        f"- {bi('النجاح', 'Passed', arabic_default)}: {rag_eval['passed']}",
                        f"- {bi('معدل النجاح', 'Pass rate', arabic_default)}: {rag_eval['pass_rate']}%",
                    ]
                )
            )
            with st.expander(bi("تفاصيل التقييم", "Evaluation Details", arabic_default), expanded=False):
                st.dataframe(rag_eval["rows"], width="stretch", hide_index=True)
        with assistant_side_guide_tab:
            st.markdown(f"### {bi('ما الذي يمكنه فعله', 'What It Can Do', arabic_default)}")
            st.markdown("\n".join(f"- {item}" for item in policy["can"]))
            st.markdown(f"### {bi('ما الذي لا يمكنه فعله', 'What It Cannot Do', arabic_default)}")
            st.markdown("\n".join(f"- {item}" for item in policy["cannot"]))
            st.markdown(f"### {bi('تدفق RAG', 'RAG Flow', arabic_default)}")
            st.markdown(
                "\n".join(
                    [
                        f"1. {bi('تقسيم سياسات التشغيل إلى مقاطع متداخلة.', 'Chunk policy knowledge into overlapping segments.', arabic_default)}",
                        f"2. {bi('تمثيل المقاطع متجهياً ثم استرجاع الأعلى صلة.', 'Vectorize chunks and retrieve the most relevant ones.', arabic_default)}",
                        f"3. {bi('إعادة ترتيب النتائج وتمريرها للإجابة مع المراجع.', 'Re-rank results and answer with citations.', arabic_default)}",
                    ]
                )
            )
            st.markdown(f"### {bi('قيود النموذج', 'LLM Limitations Guardrails', arabic_default)}")
            st.markdown(
                "\n".join(
                    [
                        f"- {bi('الإجابة يجب أن تعتمد على المقاطع المسترجعة فقط.', 'Answers must stay grounded in retrieved chunks only.', arabic_default)}",
                        f"- {bi('عند ضعف الأدلة، يصرح النظام بعدم كفاية المعلومات.', 'When evidence is weak, the assistant states insufficiency.', arabic_default)}",
                        f"- {bi('المخرجات تعرض مراجع DOC/CHUNK للتحقق التشغيلي.', 'Outputs show DOC/CHUNK citations for operator verification.', arabic_default)}",
                    ]
                )
            )
        with assistant_side_trace_tab:
            st.markdown(f"### {bi('أثر الاسترجاع', 'Retrieval Trace', arabic_default)}")
        result = st.session_state.get("rag_last_result")
        hits = list(result.get("hits", [])) if result else []
        if not hits:
            st.info(
                bi(
                    "نفذ سؤالاً لعرض أثر الاسترجاع وإعادة الترتيب.",
                    "Run a query to view retrieval and reranking trace.",
                    arabic_default,
                )
            )
        else:
            st.dataframe(
                [
                    {
                        bi("المقطع", "Chunk", arabic_default): h.get("chunk_id"),
                        bi("الدرجة الأساسية", "Base", arabic_default): h.get("base_score"),
                        bi("درجة إعادة الترتيب", "Rerank", arabic_default): h.get("rerank_score"),
                        bi("مطابقة كلمات", "Keyword Hits", arabic_default): ", ".join(h.get("keyword_hits", [])),
                        bi("الأسباب", "Reasons", arabic_default): ", ".join(h.get("reasons", [])),
                    }
                    for h in hits
                ],
                width="stretch",
                hide_index=True,
            )

elif selected_nav == "notifications":
    with main_col:
        st.markdown(f"### {bi('مركز التنبيهات', 'Notifications Center', arabic_default)}")
        show_acked = st.checkbox(
            bi("عرض التنبيهات المعترف بها", "Show acknowledged notifications", arabic_default),
            value=False,
            key="show_acked_notifications",
        )
        notifications = list_notifications(conn, include_acked=show_acked)
        if not notifications:
            st.info(bi("لا توجد تنبيهات حالياً.", "No notifications at the moment.", arabic_default))
        for notif in notifications:
            sev = str(notif.get("severity", "medium")).lower()
            sev_kind = "urgent" if sev == "high" else ("warning" if sev == "medium" else "ai")
            notif_title = str(notif.get("message_ar")) if arabic_default else str(notif.get("message_en"))
            notif_meta = f'{notif.get("type")} | {notif.get("created_at_utc")}'
            st.markdown(
                f'<div class="triage-card"><div class="request-text">{badge_html(sev.upper(), sev_kind)} {notif_title}</div><div class="explain">{notif_meta}</div><div class="explain">{bi("رقم الحالة", "Case", arabic_default)}: {notif.get("case_id") or "-"}</div></div>',
                unsafe_allow_html=True,
            )
            can_ack = role in {"supervisor", "auditor"}
            if can_ack and not notif.get("ack_at_utc"):
                if st.button(
                    bi("تأكيد التنبيه", "Acknowledge", arabic_default),
                    key=f'notify_ack_{notif["notification_id"]}',
                ):
                    if require_active_action("audit_export", "notification_ack", case_id=str(notif.get("case_id") or "")):
                        ok_ack, msg_ack = ack_notification(conn, str(notif["notification_id"]), current_user)
                        if ok_ack:
                            append_audit_event(
                                action="notification_ack",
                                result="success",
                                case_id=str(notif.get("case_id") or ""),
                                details={"notification_id": notif["notification_id"]},
                            )
                            st.rerun()
                        else:
                            append_audit_event(
                                action="notification_ack",
                                result="failure" if msg_ack.startswith("DB_") else "denied",
                                case_id=str(notif.get("case_id") or ""),
                                details={"notification_id": notif["notification_id"], "reason": msg_ack},
                            )
                            render_mutation_error(msg_ack, arabic_default)

    with right_col:
        open_notifications = list_notifications(conn, include_acked=False)
        st.markdown(f"### {bi('ملخص التنبيهات', 'Alerts Summary', arabic_default)}")
        st.markdown(
            "\n".join(
                [
                    f"- {bi('تنبيهات مفتوحة', 'Open alerts', arabic_default)}: {len(open_notifications)}",
                    f"- {bi('حالات SLA متجاوزة', 'SLA breached cases', arabic_default)}: {sum(1 for c in cases if compute_sla_state(c)['status'] == 'BREACHED')}",
                    f"- {bi('تصعيدات مفتوحة', 'Open escalations', arabic_default)}: {sum(1 for c in cases if c['state'] == 'ESCALATED')}",
                ]
            )
        )

elif selected_nav == "help":
    with main_col:
        st.markdown(f"### {bi('المساعدة', 'Help & About', arabic_default)}")
        help_tab_guide, help_tab_roles, help_tab_support = st.tabs(
            [
                bi("الدليل", "Guide", arabic_default),
                bi("الأدوار والحوكمة", "Roles & Governance", arabic_default),
                bi("الدعم", "Support", arabic_default),
            ]
        )
        with help_tab_guide:
            st.info(
                bi(
                    "دليل العرض: 1) افتح الطلبات الواردة، 2) اختر حالة عربية، 3) راجع أثر القرار، 4) افتح المساعد المعرفي لتوضيح RAG.",
                    "Demo guide: 1) Open Incoming Requests, 2) select an Arabic case, 3) review decision trace, 4) open Knowledge Assistant to explain the RAG flow.",
                    arabic_default,
                )
            )
            st.markdown(f"#### {bi('بدء سريع للحكام', 'Judge Quick Start', arabic_default)}")
            st.markdown(
                "\n".join(
                    [
                        f"1. {bi('سجل الدخول كمشرف لمشاهدة الإدارة والحوكمة.', 'Sign in as supervisor to view administration and governance.', arabic_default)}",
                        f"2. {bi('افتح الطلبات الواردة واختر طلباً عربياً عاجلاً.', 'Open Incoming Requests and select an urgent Arabic request.', arabic_default)}",
                        f"3. {bi('راجع أثر القرار ثم افتح شاشة المراجعة أو الإشعارات.', 'Review the decision trace, then open Review or Notifications.', arabic_default)}",
                        f"4. {bi('افتح المساعد المعرفي واسأل عن SLA أو سياسة التوجيه.', 'Open the Knowledge Assistant and ask about SLA or routing policy.', arabic_default)}",
                    ]
                )
            )
            st.markdown(f"#### {bi('دليل سريع لسير الفرز', 'Quick Triage Workflow', arabic_default)}")
            st.markdown(
                "\n".join(
                    [
                        f"1. {bi('افتح الطلبات الواردة وحدد حالة.', 'Open Incoming Requests and select a case.', arabic_default)}",
                        f"2. {bi('راجع أثر القرار والثقة.', 'Review decision trace and confidence.', arabic_default)}",
                        f"3. {bi('نفذ اعتماد/تجاوز/إسناد/انتقال حسب الدور.', 'Run approve/override/assign/transition by role.', arabic_default)}",
                        f"4. {bi('تابع الحالات في شاشة الطوابير والمراجعة.', 'Track cases in Queues and Review pages.', arabic_default)}",
                    ]
                )
            )
            st.markdown(f"#### {bi('استكشاف الأخطاء', 'Troubleshooting Shortcuts', arabic_default)}")
            st.code("./run_validation.sh", language="bash")
            st.code("./run_prototype.sh", language="bash")
        with help_tab_roles:
            st.markdown(f"#### {bi('مصفوفة الأدوار', 'Role Capability Matrix', arabic_default)}")
            role_rows = [
                {"role": "operator", "caps": "view/select/approve/assign/transition"},
                {"role": "supervisor", "caps": "operator + override/settings/review/reveal/export"},
                {"role": "auditor", "caps": "read-only + audit export"},
            ]
            st.dataframe(
                [
                    {
                        bi("الدور", "Role", arabic_default): r["role"],
                        bi("الصلاحيات", "Capabilities", arabic_default): r["caps"],
                    }
                    for r in role_rows
                ],
                width="stretch",
                hide_index=True,
            )
            st.markdown(f"#### {bi('الخصوصية والتدقيق', 'Privacy & Audit', arabic_default)}")
            st.markdown(
                "\n".join(
                    [
                        f"- {bi('إخفاء البيانات الحساسة مفعل افتراضياً.', 'PII masking is enabled by default.', arabic_default)}",
                        f"- {bi('كل الإجراءات الحساسة تسجل في سجل تدقيق.', 'All sensitive actions are written to audit log.', arabic_default)}",
                        f"- {bi('يمكن للمشرف إظهار البيانات الحساسة مع سبب.', 'Supervisor can reveal sensitive fields with a reason.', arabic_default)}",
                    ]
                )
            )
        with help_tab_support:
            st.markdown(f"#### {bi('إبلاغ عن مشكلة أو ملاحظة', 'Report an Issue or Feedback', arabic_default)}")
            with st.form("beta_feedback_form"):
                feedback_category = st.selectbox(
                    bi("الفئة", "Category", arabic_default),
                    options=["bug", "ux", "ai", "security", "other"],
                    format_func=lambda v: {
                        "bug": bi("خطأ", "Bug", arabic_default),
                        "ux": bi("تجربة الاستخدام", "UX", arabic_default),
                        "ai": bi("الذكاء الاصطناعي", "AI", arabic_default),
                        "security": bi("الأمن", "Security", arabic_default),
                        "other": bi("أخرى", "Other", arabic_default),
                    }[v],
                )
                feedback_summary = st.text_input(bi("ملخص قصير", "Short summary", arabic_default))
                feedback_details = st.text_area(bi("التفاصيل", "Details", arabic_default), height=120)
                feedback_rating = st.slider(
                    bi("تقييم الجاهزية", "Beta readiness score", arabic_default),
                    min_value=1,
                    max_value=5,
                    value=4,
                )
                feedback_submit = st.form_submit_button(bi("إرسال الملاحظة", "Submit Feedback", arabic_default), type="primary")
            if feedback_submit:
                if not feedback_summary.strip():
                    st.error(bi("الملخص مطلوب.", "Summary is required.", arabic_default))
                elif not feedback_details.strip():
                    st.error(bi("التفاصيل مطلوبة.", "Details are required.", arabic_default))
                else:
                    append_feedback_entry(feedback_category, feedback_summary, feedback_details, int(feedback_rating))
                    append_audit_event(
                        action="feedback_submit",
                        result="success",
                        details={"category": feedback_category, "rating": int(feedback_rating), "summary": feedback_summary[:120]},
                    )
                    st.success(bi("تم حفظ الملاحظة في سجل الدعم المحلي.", "Feedback saved to the local support log.", arabic_default))
                    st.rerun()

    with right_col:
        beta_snapshot = beta_readiness_snapshot(conn)
        st.markdown(f"### {bi('جاهزية النسخة التجريبية', 'Beta Readiness', arabic_default)}")
        st.markdown(
            "\n".join(
                [
                    f"- {bi('إصدار المخطط', 'Schema version', arabic_default)}: {beta_snapshot['schema_version']} / {beta_snapshot['schema_expected']}",
                    f"- {bi('سلامة التدقيق', 'Audit chain', arabic_default)}: {'OK' if beta_snapshot['audit_chain_ok'] else 'FAILED'}",
                    f"- {bi('الدليل المحلي', 'Local users', arabic_default)}: {beta_snapshot['local_user_count']}",
                    f"- {bi('مستخدمو MFA المحلي', 'Local MFA users', arabic_default)}: {beta_snapshot['local_mfa_enabled']}",
                    f"- {bi('OIDC', 'OIDC', arabic_default)}: {bi('مهيأ', 'Configured', arabic_default) if beta_snapshot['oidc_enabled'] else bi('غير مهيأ', 'Not configured', arabic_default)}",
                    f"- {bi('قاعدة المعرفة', 'Knowledge base', arabic_default)}: {beta_snapshot['knowledge_documents']} {bi('وثيقة', 'docs', arabic_default)} / {beta_snapshot['knowledge_chunks']} {bi('مقطع', 'chunks', arabic_default)}",
                    f"- {bi('ملاحظات البيتا', 'Beta feedback entries', arabic_default)}: {beta_snapshot['feedback_count']}",
                ]
            )
        )
        st.markdown(f"### {bi('لماذا هذا مهم', 'Why This Matters', arabic_default)}")
        st.markdown(
            "\n".join(
                [
                    f"- {bi('المشكلة', 'Problem', arabic_default)}: {bi('التصنيف اليدوي متعدد اللغات يسبب التأخير وسوء التوجيه ومخاطر SLA.', 'Manual multilingual triage causes delay, misrouting, and SLA risk.', arabic_default)}",
                    f"- {bi('منهج AI', 'AI Method', arabic_default)}: {bi('تصنيف ثنائي اللغة + استرجاع RAG للسياسات + تفسير قرار + إشراف بشري.', 'Bilingual classification + policy-grounded RAG + decision trace + human oversight.', arabic_default)}",
                    f"- {bi('الثقة والحوكمة', 'Trust & Governance', arabic_default)}: {bi('RBAC، تدقيق، إخفاء بيانات، MFA، وقيود على المساعد.', 'RBAC, audit, privacy masking, MFA, and constrained assistant behavior.', arabic_default)}",
                    f"- {bi('الأثر', 'Impact', arabic_default)}: {bi('تقليل زمن الاستجابة الأولى وتحسين التوجيه والامتثال التشغيلي.', 'Reduced first-response time, better routing, and stronger operational compliance.', arabic_default)}",
                ]
            )
        )
        st.markdown(f"### {bi('حول النظام', 'About System', arabic_default)}")
        st.markdown(
            "\n".join(
                [
                    f"- {bi('المنتج', 'Product', arabic_default)}: Malomatia Gov-Service Triage AI",
                    f"- {bi('النطاق', 'Scope', arabic_default)}: {bi('عمليات داخلية', 'Internal operations', arabic_default)}",
                    f"- {bi('التخزين', 'Storage', arabic_default)}: SQLite",
                    f"- {bi('الحوكمة', 'Governance', arabic_default)}: Audit + RBAC + Privacy masking",
                ]
            )
        )
elif selected_nav == "settings":
    with main_col:
        st.markdown(f"### {bi('إعدادات النظام', 'System Settings', arabic_default)}")
        st.caption(
            bi(
                "قسّم الاستخدام هنا إلى ثلاث مهام: الإعدادات العامة، حسابك الشخصي، ثم الإدارة والدعم عند الحاجة.",
                "Use this page in three steps: general settings, your account, then administration/support only when needed.",
                arabic_default,
            )
        )
        queue_options = {
            "all": bi("الكل", "All", arabic_default),
            "Immigration": bi("الهجرة", "Immigration", arabic_default),
            "Municipal": bi("البلدية", "Municipal", arabic_default),
            "Licensing": bi("الترخيص", "Licensing", arabic_default),
            "Human Review": bi("مراجعة بشرية", "Human Review", arabic_default),
        }
        queue_keys = list(queue_options.keys())
        current_queue_key = st.session_state.get("ui_default_queue", "all")
        queue_idx = queue_keys.index(current_queue_key) if current_queue_key in queue_keys else 0

        can_write_settings = has_permission("settings_write")
        current_user_record = get_user(conn, current_user)
        user_mfa_state = "-"
        if current_user_record:
            user_mfa_state = (
                bi("TOTP مفعل", "TOTP enabled", arabic_default)
                if int(current_user_record.get("mfa_required", 0)) == 1 and str(current_user_record.get("mfa_type", "none")) == "totp"
                else (
                    bi("MFA يدار من المزود", "MFA managed by provider", arabic_default)
                    if str(current_user_record.get("mfa_type", "none")) == "provider"
                    else bi("بدون MFA محلي", "No local MFA", arabic_default)
                )
            )

        summary_cols = st.columns(4)
        summary_cols[0].markdown(
            f'<div class="metric-card"><div>{bi("الوصول", "Access", arabic_default)}</div><div class="metric-value" style="font-size:16px">{role}</div></div>',
            unsafe_allow_html=True,
        )
        summary_cols[1].markdown(
            f'<div class="metric-card"><div>{bi("MFA", "MFA", arabic_default)}</div><div class="metric-value" style="font-size:16px">{user_mfa_state}</div></div>',
            unsafe_allow_html=True,
        )
        summary_cols[2].markdown(
            f'<div class="metric-card"><div>{bi("التسجيل العام", "Public Signup", arabic_default)}</div><div class="metric-value" style="font-size:16px">{bi("مفعل", "Enabled", arabic_default) if st.session_state["security_public_signup_enabled"] else bi("معطل", "Disabled", arabic_default)}</div></div>',
            unsafe_allow_html=True,
        )
        summary_cols[3].markdown(
            f'<div class="metric-card"><div>{bi("الإدارة", "Administration", arabic_default)}</div><div class="metric-value" style="font-size:16px">{bi("متاح", "Available", arabic_default) if can_write_settings else bi("قراءة فقط", "Read Only", arabic_default)}</div></div>',
            unsafe_allow_html=True,
        )

        settings_section = st.radio(
            bi("أقسام الإعدادات", "Settings Sections", arabic_default),
            options=["general", "account", "admin"],
            format_func=lambda value: {
                "general": bi("عام", "General", arabic_default),
                "account": bi("حسابي", "My Account", arabic_default),
                "admin": bi("الإدارة والدعم", "Administration & Support", arabic_default),
            }[value],
            horizontal=True,
            key="settings_section",
        )

        if settings_section == "general":
            with st.form("settings_form", clear_on_submit=False):
                c1, c2 = st.columns(2)
                sidebar_contrast = c1.checkbox(
                    bi("تباين عالٍ للشريط الجانبي", "High-contrast sidebar", arabic_default),
                    value=st.session_state["ui_sidebar_contrast"],
                    disabled=not can_write_settings,
                )
                compact_mode = c1.checkbox(
                    bi("وضع عرض مضغوط", "Compact layout mode", arabic_default),
                    value=st.session_state["ui_compact_mode"],
                    disabled=not can_write_settings,
                )
                confidence_precision_new = c2.selectbox(
                    bi("دقة عرض الثقة", "Confidence precision", arabic_default),
                    options=[1, 2, 3],
                    index=[1, 2, 3].index(st.session_state["ui_confidence_precision"]),
                    disabled=not can_write_settings,
                )
                default_queue_choice = c2.selectbox(
                    bi("الطابور الافتراضي", "Default queue", arabic_default),
                    options=list(queue_options.values()),
                    index=queue_idx,
                    disabled=not can_write_settings,
                )

                st.markdown(f"#### {bi('إعدادات الأمن والخصوصية', 'Security & Privacy Settings', arabic_default)}")
                session_idle_minutes = st.number_input(
                    bi("مهلة الخمول (دقيقة)", "Idle timeout (minutes)", arabic_default),
                    min_value=5,
                    max_value=120,
                    value=int(st.session_state["security_session_idle_minutes"]),
                    step=1,
                    disabled=not can_write_settings,
                )
                session_max_hours = st.number_input(
                    bi("الحد الأقصى للجلسة (ساعة)", "Max session duration (hours)", arabic_default),
                    min_value=1,
                    max_value=24,
                    value=int(st.session_state["security_session_max_hours"]),
                    step=1,
                    disabled=not can_write_settings,
                )
                audit_retention_days = st.number_input(
                    bi("مدة الاحتفاظ بسجل التدقيق (يوم)", "Audit retention (days)", arabic_default),
                    min_value=7,
                    max_value=365,
                    value=int(st.session_state["security_audit_retention_days"]),
                    step=1,
                    disabled=not can_write_settings,
                )
                privacy_masking_enabled = st.checkbox(
                    bi("تفعيل إخفاء البيانات الحساسة", "Enable privacy masking", arabic_default),
                    value=bool(st.session_state["security_privacy_masking_enabled"]),
                    disabled=not can_write_settings,
                )
                public_signup_enabled = c2.checkbox(
                    bi("تفعيل إنشاء الحسابات من صفحة الدخول", "Enable account creation from login page", arabic_default),
                    value=bool(st.session_state["security_public_signup_enabled"]),
                    disabled=not can_write_settings,
                )
                signup_requires_approval = c2.checkbox(
                    bi("تتطلب الحسابات الجديدة موافقة مشرف", "Require supervisor approval for new sign-ups", arabic_default),
                    value=bool(st.session_state["security_signup_requires_approval"]),
                    disabled=not can_write_settings or not public_signup_enabled,
                )
                save_clicked = st.form_submit_button(
                    bi("حفظ الإعدادات", "Save Settings", arabic_default),
                    type="primary",
                    disabled=not can_write_settings,
                )

            if save_clicked:
                if require_active_action("settings_write", "settings_save"):
                    st.session_state["ui_sidebar_contrast"] = sidebar_contrast
                    st.session_state["ui_compact_mode"] = compact_mode
                    st.session_state["ui_confidence_precision"] = int(confidence_precision_new)
                    st.session_state["ui_default_queue"] = {v: k for k, v in queue_options.items()}[default_queue_choice]
                    st.session_state["security_session_idle_minutes"] = int(session_idle_minutes)
                    st.session_state["security_session_max_hours"] = int(session_max_hours)
                    st.session_state["security_audit_retention_days"] = int(audit_retention_days)
                    st.session_state["security_privacy_masking_enabled"] = bool(privacy_masking_enabled)
                    st.session_state["security_public_signup_enabled"] = bool(public_signup_enabled)
                    st.session_state["security_signup_requires_approval"] = bool(signup_requires_approval)
                    append_audit_event(
                        action="settings_save",
                        result="success",
                        details={
                            "ui_sidebar_contrast": sidebar_contrast,
                            "ui_compact_mode": compact_mode,
                            "ui_confidence_precision": int(confidence_precision_new),
                            "ui_default_queue": st.session_state["ui_default_queue"],
                            "security_session_idle_minutes": int(session_idle_minutes),
                            "security_session_max_hours": int(session_max_hours),
                            "security_audit_retention_days": int(audit_retention_days),
                            "security_privacy_masking_enabled": bool(privacy_masking_enabled),
                            "security_public_signup_enabled": bool(public_signup_enabled),
                            "security_signup_requires_approval": bool(signup_requires_approval),
                        },
                    )
                    st.toast(bi("تم حفظ الإعدادات", "Settings saved", arabic_default))
                    st.rerun()

            if st.button(bi("إعادة الضبط الافتراضي", "Reset Defaults", arabic_default), disabled=not can_write_settings):
                if require_active_action("settings_write", "settings_reset"):
                    st.session_state["ui_sidebar_contrast"] = True
                    st.session_state["ui_compact_mode"] = False
                    st.session_state["ui_confidence_precision"] = 2
                    st.session_state["ui_default_queue"] = "all"
                    st.session_state["security_session_idle_minutes"] = 15
                    st.session_state["security_session_max_hours"] = 8
                    st.session_state["security_audit_retention_days"] = 90
                    st.session_state["security_privacy_masking_enabled"] = True
                    st.session_state["security_public_signup_enabled"] = False
                    st.session_state["security_signup_requires_approval"] = True
                    st.session_state["revealed_case_ids"] = set()
                    append_audit_event(action="settings_reset", result="success", details={"reason": "user_requested"})
                    st.rerun()

        elif settings_section == "account":
            st.markdown(f"### {bi('حسابي', 'My Account', arabic_default)}")
            if current_user_record:
                self_totp_state_key = f"self_totp_secret_{current_user}"
                if self_totp_state_key not in st.session_state:
                    st.session_state[self_totp_state_key] = str(current_user_record.get("totp_secret") or "") or generate_totp_secret()
                st.markdown(
                    "\n".join(
                        [
                            f"- {bi('المعرف', 'User ID', arabic_default)}: `{current_user_record['user_id']}`",
                            f"- {bi('الموفر', 'Provider', arabic_default)}: {current_user_record.get('auth_provider', 'local')}",
                            f"- {bi('الدور', 'Role', arabic_default)}: {current_user_record.get('role', '-')}",
                            f"- {bi('حالة MFA', 'MFA status', arabic_default)}: {user_mfa_state}",
                        ]
                    )
                )
                if str(current_user_record.get("auth_provider", "local")) == "local":
                    with st.form("self_service_password_form"):
                        current_password = st.text_input(
                            bi("كلمة المرور الحالية", "Current password", arabic_default),
                            type="password",
                        )
                        new_password = st.text_input(
                            bi("كلمة المرور الجديدة", "New password", arabic_default),
                            type="password",
                        )
                        confirm_password = st.text_input(
                            bi("تأكيد كلمة المرور", "Confirm password", arabic_default),
                            type="password",
                        )
                        password_submit = st.form_submit_button(
                            bi("تغيير كلمة المرور", "Change Password", arabic_default),
                            type="primary",
                        )
                    if password_submit:
                        if not verify_password(current_password, str(current_user_record.get("password_hash", ""))):
                            st.error(bi("كلمة المرور الحالية غير صحيحة.", "Current password is incorrect.", arabic_default))
                        elif len(new_password) < 8:
                            st.error(bi("يجب أن تكون كلمة المرور 8 أحرف على الأقل.", "Password must be at least 8 characters.", arabic_default))
                        elif new_password != confirm_password:
                            st.error(bi("تأكيد كلمة المرور غير مطابق.", "Password confirmation does not match.", arabic_default))
                        elif require_active_action("view", "change_password", case_id=None):
                            ok_pw, msg_pw, _ = reset_local_user_password(
                                conn,
                                current_user,
                                password_hash=hash_password_pbkdf2(new_password),
                            )
                            if ok_pw:
                                append_audit_event(action="change_password", result="success", actor_user_id=current_user, actor_role=role)
                                st.success(bi("تم تحديث كلمة المرور.", "Password updated.", arabic_default))
                                st.rerun()
                            else:
                                append_audit_event(
                                    action="change_password",
                                    result="failure" if msg_pw.startswith("DB_") else "denied",
                                    actor_user_id=current_user,
                                    actor_role=role,
                                    details={"reason": msg_pw},
                                )
                                render_mutation_error(msg_pw, arabic_default)
                    st.markdown(f"#### {bi('التحقق بخطوتين', 'Two-Step Verification', arabic_default)}")
                    st.caption(
                        bi(
                            "فعّل TOTP لاستخدام تطبيق مصادقة بعد كلمة المرور. إذا عطّلتها سيبقى تسجيل الدخول بكلمة المرور فقط.",
                            "Enable TOTP to require an authenticator-app code after your password. If you disable it, login stays password-only.",
                            arabic_default,
                        )
                    )
                    if st.button(bi("إنشاء سر MFA جديد", "Generate new MFA secret", arabic_default), key="self_generate_totp"):
                        st.session_state[self_totp_state_key] = generate_totp_secret()
                    with st.form("self_service_mfa_form"):
                        self_enable_mfa = st.checkbox(
                            bi("تفعيل التحقق بخطوتين", "Enable two-step verification", arabic_default),
                            value=bool(int(current_user_record.get("mfa_required", 0))),
                        )
                        self_totp_secret = st.text_input(
                            bi("سر تطبيق المصادقة (Base32)", "Authenticator app secret (Base32)", arabic_default),
                            value=str(st.session_state.get(self_totp_state_key, "")),
                            disabled=not self_enable_mfa,
                        ).strip()
                        mfa_submit = st.form_submit_button(
                            bi("حفظ إعدادات التحقق بخطوتين", "Save Two-Step Verification", arabic_default),
                            type="primary",
                        )
                    if mfa_submit and require_active_action("view", "self_manage_mfa", case_id=None):
                        normalized_self_totp = _normalize_totp_secret(self_totp_secret) if self_enable_mfa else None
                        if self_enable_mfa and (not normalized_self_totp or len(normalized_self_totp) < 16):
                            st.error(
                                bi(
                                    "أدخل سراً صالحاً لتطبيق المصادقة.",
                                    "Enter a valid authenticator secret.",
                                    arabic_default,
                                )
                            )
                        else:
                            ok_mfa, msg_mfa, updated_user = set_local_totp_requirement(
                                conn,
                                current_user,
                                mfa_required=self_enable_mfa,
                                totp_secret=normalized_self_totp,
                            )
                            if ok_mfa:
                                st.session_state[self_totp_state_key] = str((updated_user or {}).get("totp_secret") or st.session_state[self_totp_state_key])
                                append_audit_event(
                                    action="self_manage_mfa",
                                    result="success",
                                    actor_user_id=current_user,
                                    actor_role=role,
                                    details={"mfa_required": bool(self_enable_mfa)},
                                )
                                st.success(
                                    bi(
                                        "تم تحديث إعدادات التحقق بخطوتين.",
                                        "Two-step verification settings updated.",
                                        arabic_default,
                                    )
                                )
                                st.rerun()
                            else:
                                append_audit_event(
                                    action="self_manage_mfa",
                                    result="failure" if msg_mfa.startswith("DB_") else "denied",
                                    actor_user_id=current_user,
                                    actor_role=role,
                                    details={"reason": msg_mfa},
                                )
                                render_mutation_error(msg_mfa, arabic_default)
                else:
                    st.caption(
                        bi(
                            "إدارة كلمة المرور لحسابات Google/Microsoft تتم من مزود الهوية.",
                            "Password management for Google/Microsoft accounts is handled by the identity provider.",
                            arabic_default,
                        )
                    )

        else:
            if not can_write_settings:
                st.info(
                    bi(
                        "قسم الإدارة والدعم متاح للمشرف فقط.",
                        "Administration & Support is supervisor-only.",
                        arabic_default,
                    )
                )
            else:
                feedback_entries = read_feedback_entries()
                with st.expander(bi("صندوق دعم النسخة النهائية", "Final Release Support Inbox", arabic_default), expanded=True):
                    if feedback_entries:
                        recent_feedback = sorted(
                            feedback_entries,
                            key=lambda item: str(item.get("timestamp_utc", "")),
                            reverse=True,
                        )[:25]
                        st.dataframe(
                            [
                                {
                                    bi("الوقت", "Timestamp", arabic_default): row.get("timestamp_utc", "-"),
                                    bi("المستخدم", "User", arabic_default): row.get("user_id", "-"),
                                    bi("الدور", "Role", arabic_default): row.get("role", "-"),
                                    bi("الفئة", "Category", arabic_default): row.get("category", "-"),
                                    bi("التقييم", "Rating", arabic_default): row.get("rating", "-"),
                                    bi("الملخص", "Summary", arabic_default): row.get("summary", "-"),
                                }
                                for row in recent_feedback
                            ],
                            width="stretch",
                            hide_index=True,
                        )
                    else:
                        st.caption(
                            bi(
                                "لا توجد ملاحظات دعم مسجلة بعد.",
                                "No support feedback has been submitted yet.",
                                arabic_default,
                            )
                        )

                st.markdown(f"### {bi('إدارة الحسابات', 'Account Administration', arabic_default)}")
                st.caption(
                    bi(
                        "الوضع النهائي: إنشاء الحسابات من صفحة الدخول معطل افتراضياً. إذا فُعّل، يوصى بالإبقاء على موافقة المشرف للحسابات الجديدة.",
                        "Final release policy: login-page account creation is disabled by default. If enabled, keep supervisor approval on for new accounts.",
                        arabic_default,
                    )
                )
                with st.expander(bi("إنشاء مستخدم محلي", "Create Local User", arabic_default), expanded=False):
                    with st.form("create_local_user_form"):
                        new_user_id = st.text_input(bi("معرف المستخدم", "User ID", arabic_default)).strip().lower()
                        new_display_name = st.text_input(bi("الاسم المعروض", "Display Name", arabic_default)).strip()
                        new_role = st.selectbox(bi("الدور", "Role", arabic_default), options=list(ROLE_PERMISSIONS.keys()))
                        new_status = st.selectbox(
                            bi("الحالة", "Status", arabic_default),
                            options=["active", "inactive"],
                            format_func=lambda v: bi("نشط", "Active", arabic_default) if v == "active" else bi("غير نشط", "Inactive", arabic_default),
                        )
                        new_password = st.text_input(bi("كلمة المرور المؤقتة", "Temporary password", arabic_default), type="password")
                        new_mfa_required = st.checkbox(bi("تفعيل TOTP", "Require TOTP", arabic_default), value=False)
                        new_totp_secret = st.text_input(
                            bi("سر TOTP (Base32)", "TOTP secret (Base32)", arabic_default),
                            disabled=not new_mfa_required,
                        ).strip()
                        create_submit = st.form_submit_button(bi("إنشاء المستخدم", "Create User", arabic_default), type="primary")
                    st.caption(
                        bi(
                            "إذا فعّلت التحقق بخطوتين، شارك سر TOTP مع المستخدم ليضيفه إلى تطبيق المصادقة قبل أول تسجيل دخول.",
                            "If you require two-step verification, share the TOTP secret with the user so they can add it to an authenticator app before first login.",
                            arabic_default,
                        )
                    )
                    if create_submit:
                        if not new_user_id or not new_display_name:
                            st.error(bi("معرف المستخدم والاسم مطلوبان.", "User ID and display name are required.", arabic_default))
                        elif len(new_password) < 8:
                            st.error(bi("كلمة المرور المؤقتة يجب أن تكون 8 أحرف على الأقل.", "Temporary password must be at least 8 characters.", arabic_default))
                        elif new_mfa_required and not new_totp_secret:
                            st.error(bi("سر TOTP مطلوب عند تفعيل MFA.", "A TOTP secret is required when MFA is enabled.", arabic_default))
                        elif require_active_action("settings_write", "create_user"):
                            ok_new, msg_new, _ = create_local_user(
                                conn,
                                user_id=new_user_id,
                                display_name=new_display_name,
                                role=new_role,
                                password_hash=hash_password_pbkdf2(new_password),
                                status=new_status,
                                mfa_required=new_mfa_required,
                                totp_secret=_normalize_totp_secret(new_totp_secret) if new_mfa_required else None,
                            )
                            if ok_new:
                                append_audit_event(
                                    action="create_user",
                                    result="success",
                                    actor_user_id=current_user,
                                    actor_role=role,
                                    details={"target_user_id": new_user_id, "target_role": new_role, "mfa_required": new_mfa_required},
                                )
                                st.success(bi("تم إنشاء المستخدم المحلي.", "Local user created.", arabic_default))
                                st.rerun()
                            else:
                                append_audit_event(
                                    action="create_user",
                                    result="failure" if msg_new.startswith("DB_") else "denied",
                                    actor_user_id=current_user,
                                    actor_role=role,
                                    details={"target_user_id": new_user_id, "reason": msg_new},
                                )
                                render_mutation_error(msg_new, arabic_default)

                users_for_admin = list_users(conn)
                user_options = {f"{u['display_name']} ({u['user_id']})": u for u in users_for_admin}
                if user_options:
                    selected_admin_label = st.selectbox(
                        bi("اختر مستخدماً للإدارة", "Select user to manage", arabic_default),
                        options=list(user_options.keys()),
                    )
                    managed_user = user_options[selected_admin_label]
                    managed_totp_state_key = f"managed_totp_secret_{managed_user['user_id']}"
                    if managed_totp_state_key not in st.session_state:
                        st.session_state[managed_totp_state_key] = str(managed_user.get("totp_secret") or "") or generate_totp_secret()
                    is_local_managed = str(managed_user.get("auth_provider", "local")) == "local"
                    st.markdown(f"#### {bi('إدارة التحقق بخطوتين', 'Two-Step Verification Management', arabic_default)}")
                    if is_local_managed:
                        st.caption(
                            bi(
                                "يمكنك فرض TOTP أو تعطيله للمستخدم المحلي. بالنسبة لحسابات Google/Microsoft، تتم إدارة MFA من المزود الخارجي.",
                                "You can require or disable TOTP for local users. For Google/Microsoft accounts, MFA is managed by the external provider.",
                                arabic_default,
                            )
                        )
                        if st.button(
                            bi("إنشاء سر TOTP جديد للمستخدم", "Generate new TOTP secret for user", arabic_default),
                            key=f"generate_managed_totp_{managed_user['user_id']}",
                        ):
                            st.session_state[managed_totp_state_key] = generate_totp_secret()
                    else:
                        st.caption(
                            bi(
                                "هذا الحساب يعتمد على Google/Microsoft؛ لا يمكن إدارة TOTP المحلي له من داخل التطبيق.",
                                "This account uses Google/Microsoft; local TOTP cannot be managed from inside the app.",
                                arabic_default,
                            )
                        )
                    with st.form("manage_user_form"):
                        managed_role = st.selectbox(
                            bi("الدور", "Role", arabic_default),
                            options=list(ROLE_PERMISSIONS.keys()),
                            index=list(ROLE_PERMISSIONS.keys()).index(str(managed_user.get("role", "operator"))),
                        )
                        managed_status = st.selectbox(
                            bi("الحالة", "Status", arabic_default),
                            options=["active", "inactive"],
                            index=0 if str(managed_user.get("status", "active")) == "active" else 1,
                            format_func=lambda v: bi("نشط", "Active", arabic_default) if v == "active" else bi("غير نشط", "Inactive", arabic_default),
                        )
                        managed_mfa_required = st.checkbox(
                            bi("تفعيل TOTP المحلي", "Require local TOTP", arabic_default),
                            value=bool(int(managed_user.get("mfa_required", 0))),
                            disabled=not is_local_managed,
                        )
                        managed_totp_secret = st.text_input(
                            bi("سر TOTP (Base32)", "TOTP secret (Base32)", arabic_default),
                            value=str(st.session_state.get(managed_totp_state_key, "")),
                            disabled=not is_local_managed or not managed_mfa_required,
                        ).strip()
                        managed_reset_password = st.text_input(
                            bi("إعادة تعيين كلمة المرور", "Reset password", arabic_default),
                            type="password",
                            disabled=not is_local_managed,
                        )
                        manage_submit = st.form_submit_button(bi("حفظ تغييرات الحساب", "Save Account Changes", arabic_default), type="primary")
                    if manage_submit and require_active_action("settings_write", "manage_user"):
                        role_ok, role_msg, _ = set_user_role(conn, str(managed_user["user_id"]), managed_role)
                        status_ok, status_msg, _ = set_user_status(conn, str(managed_user["user_id"]), managed_status)
                        manage_error = ""
                        if not role_ok:
                            manage_error = role_msg
                        elif not status_ok:
                            manage_error = status_msg
                        else:
                            if is_local_managed:
                                totp_ok, totp_msg, _ = set_local_totp_requirement(
                                    conn,
                                    str(managed_user["user_id"]),
                                    mfa_required=managed_mfa_required,
                                    totp_secret=_normalize_totp_secret(managed_totp_secret) if managed_mfa_required else None,
                                )
                                if not totp_ok:
                                    manage_error = totp_msg
                                elif managed_reset_password.strip() and len(managed_reset_password.strip()) < 8:
                                    manage_error = bi(
                                        "كلمة المرور الجديدة يجب أن تكون 8 أحرف على الأقل.",
                                        "Reset password must be at least 8 characters.",
                                        arabic_default,
                                    )
                                elif managed_reset_password.strip():
                                    pw_ok, pw_msg, _ = reset_local_user_password(
                                        conn,
                                        str(managed_user["user_id"]),
                                        password_hash=hash_password_pbkdf2(managed_reset_password.strip()),
                                    )
                                    if not pw_ok:
                                        manage_error = pw_msg
                        if manage_error:
                            append_audit_event(
                                action="manage_user",
                                result="failure" if str(manage_error).startswith("DB_") else "denied",
                                actor_user_id=current_user,
                                actor_role=role,
                                details={"target_user_id": managed_user["user_id"], "reason": manage_error},
                            )
                            if str(manage_error).startswith("DB_"):
                                render_mutation_error(manage_error, arabic_default)
                            else:
                                st.error(str(manage_error))
                        else:
                            append_audit_event(
                                action="manage_user",
                                result="success",
                                actor_user_id=current_user,
                                actor_role=role,
                                details={
                                    "target_user_id": managed_user["user_id"],
                                    "role": managed_role,
                                    "status": managed_status,
                                    "mfa_required": managed_mfa_required if is_local_managed else None,
                                    "password_reset": bool(managed_reset_password.strip()) if is_local_managed else False,
                                },
                            )
                            st.success(bi("تم حفظ تغييرات الحساب.", "Account changes saved.", arabic_default))
                            st.rerun()

                with st.expander(bi("دليل المستخدمين", "User Directory", arabic_default), expanded=False):
                    st.dataframe(
                        [
                            {
                                bi("المعرف", "User ID", arabic_default): u["user_id"],
                                bi("الاسم", "Display Name", arabic_default): u["display_name"],
                                bi("الموفر", "Provider", arabic_default): u.get("auth_provider", "local"),
                                bi("MFA", "MFA", arabic_default): (
                                    "TOTP"
                                    if int(u.get("mfa_required", 0)) == 1 and str(u.get("mfa_type", "none")) == "totp"
                                    else str(u.get("mfa_type", "none"))
                                ),
                                bi("الدور", "Role", arabic_default): u["role"],
                                bi("الحالة", "Status", arabic_default): u["status"],
                                bi("فشل المحاولات", "Failed Attempts", arabic_default): u["failed_attempts"],
                                bi("آخر دخول", "Last Login", arabic_default): u["last_login_at_utc"] or "-",
                            }
                            for u in list_users(conn)
                        ],
                        width="stretch",
                        hide_index=True,
                    )

                with st.expander(bi("سجل أحداث سير العمل", "Workflow Events", arabic_default), expanded=False):
                    st.dataframe(list_workflow_events(conn, limit=100), width="stretch", hide_index=True)

    with right_col:
        auth_status = auth_status_snapshot(conn)
        status_snapshot = system_status_snapshot(conn)
        st.markdown(f"### {bi('حالة المصادقة', 'Auth Status', arabic_default)}")
        st.markdown(
            "\n".join(
                [
                    f"- {bi('الموفر الحالي', 'Current provider', arabic_default)}: {auth_status['current_provider']}",
                    f"- {bi('OIDC', 'OIDC', arabic_default)}: {bi('مفعل', 'Configured', arabic_default) if auth_status['oidc_enabled'] else bi('غير مفعل', 'Not configured', arabic_default)}",
                    f"- {bi('الموفرون', 'Providers', arabic_default)}: {', '.join(auth_status['providers']) if auth_status['providers'] else '-'}",
                    f"- {bi('مستخدمو TOTP المحلي', 'Local TOTP users', arabic_default)}: {auth_status['local_mfa_enabled']} / {auth_status['local_user_count']}",
                ]
            )
        )
        st.markdown(f"### {bi('حالة النظام', 'System Status', arabic_default)}")
        st.markdown(
            "\n".join(
                [
                    f"- {bi('الإصدار', 'App version', arabic_default)}: {status_snapshot['app_version']}",
                    f"- {bi('المرحلة', 'Release stage', arabic_default)}: {status_snapshot['release_stage']}",
                    f"- {bi('نسخة المخطط', 'Schema version', arabic_default)}: {status_snapshot['schema_version']} / {status_snapshot['schema_expected']}",
                    f"- {bi('سلامة التدقيق', 'Audit chain integrity', arabic_default)}: {'OK' if status_snapshot['audit_chain_ok'] else 'FAILED'}",
                    f"- {bi('سجل الدعم', 'Support log entries', arabic_default)}: {status_snapshot['feedback_count']}",
                    f"- {bi('إنشاء الحسابات العامة', 'Public sign-up', arabic_default)}: {bi('مفعل', 'Enabled', arabic_default) if status_snapshot['public_signup_enabled'] else bi('معطل', 'Disabled', arabic_default)}",
                    f"- {bi('موافقة المشرف', 'Supervisor approval', arabic_default)}: {bi('مطلوبة', 'Required', arabic_default) if status_snapshot['signup_requires_approval'] else bi('غير مطلوبة', 'Not required', arabic_default)}",
                    f"- {bi('OpenAI', 'OpenAI', arabic_default)}: {bi('مهيأ', 'Configured', arabic_default) if status_snapshot['openai_available'] else bi('غير مهيأ', 'Not configured', arabic_default)}",
                    f"- {bi('OIDC', 'OIDC', arabic_default)}: {bi('مهيأ', 'Configured', arabic_default) if status_snapshot['oidc_enabled'] else bi('غير مهيأ', 'Not configured', arabic_default)}",
                ]
            )
        )

        chain_ok, chain_message, chain_count = validate_audit_chain()
        audit_events = read_audit_events()
        kpis = compute_operational_kpis(cases, audit_events)

        st.markdown(f"### {bi('ملخص الأمان', 'Security Summary', arabic_default)}")
        st.markdown(
            "\n".join(
                [
                    f"- {bi('سلامة سلسلة التدقيق', 'Audit chain integrity', arabic_default)}: {'OK' if chain_ok else 'FAILED'}",
                    f"- {bi('رسالة التحقق', 'Validation message', arabic_default)}: {chain_message}",
                    f"- {bi('عدد أحداث التدقيق', 'Audit events', arabic_default)}: {chain_count}",
                    f"- {bi('الاحتفاظ', 'Retention', arabic_default)}: {st.session_state['security_audit_retention_days']} {bi('يوم', 'days', arabic_default)}",
                ]
            )
        )

        st.markdown(f"### {bi('سياسات التشفير والأمن', 'Encryption & Security Policies', arabic_default)}")
        st.markdown(
            "\n".join(
                [
                    f"- {bi('كلمات المرور لا تحفظ كنص خام، بل كـ PBKDF2 hashes.', 'Passwords are never stored in plaintext; PBKDF2 hashes are stored instead.', arabic_default)}",
                    f"- {bi('مستخدمو الدليل المحلي يمكن فرض TOTP MFA عليهم من النظام أو من ملف الأسرار.', 'Local directory users can be forced through TOTP MFA from the app or secrets bootstrap.', arabic_default)}",
                    f"- {bi('تسجيل الدخول عبر Google/Microsoft يستخدم OIDC، وMFA يدار من مزود الهوية.', 'Google/Microsoft sign-in uses OIDC, and MFA is managed by the identity provider.', arabic_default)}",
                    f"- {bi('بعد 5 محاولات فاشلة يتم قفل الحساب 15 دقيقة.', 'After 5 failed attempts, the account is locked for 15 minutes.', arabic_default)}",
                    f"- {bi('الجلسات تنتهي بالخمول وبحد أقصى زمني.', 'Sessions expire on idle timeout and maximum duration.', arabic_default)}",
                    f"- {bi('كل عمليات الدخول والخروج والإعدادات تسجل في التدقيق.', 'All login, logout, and settings events are audit logged.', arabic_default)}",
                    f"- {bi('البيانات الحساسة تبقى مخفية افتراضياً ولا يكشفها النظام تلقائياً.', 'Sensitive data remains masked by default and is never auto-revealed.', arabic_default)}",
                ]
            )
        )

        st.markdown(f"### {bi('صحة التشغيل', 'Operations Health', arabic_default)}")
        st.markdown(
            "\n".join(
                [
                    f"- {bi('متوسط زمن الفرز', 'Avg triage time', arabic_default)}: {kpis['avg_time_to_triage_minutes']:.1f} {bi('دقيقة', 'min', arabic_default)}",
                    f"- {bi('متوسط زمن أول إسناد', 'Avg first assignment', arabic_default)}: {kpis['avg_time_to_first_assignment_minutes']:.1f} {bi('دقيقة', 'min', arabic_default)}",
                    f"- {bi('نسبة تجاوز SLA', 'SLA breached %', arabic_default)}: {kpis['sla_breached_pct']:.1f}%",
                    f"- {bi('معدل التجاوز', 'Override rate', arabic_default)}: {kpis['override_rate_pct']:.1f}%",
                    f"- {bi('حجم المراجعة البشرية', 'Human review volume', arabic_default)}: {int(kpis['human_review_volume'])}",
                ]
            )
        )

        if has_permission("audit_export"):
            content = "\n".join(read_audit_lines())
            st.download_button(
                label=bi("تصدير سجل التدقيق", "Export Audit Log", arabic_default),
                data=content,
                file_name="audit.log.jsonl",
                mime="application/jsonl",
                width="stretch",
            )
            feedback_content = "\n".join(
                json.dumps(entry, ensure_ascii=False) for entry in read_feedback_entries()
            )
            st.download_button(
                label=bi("تصدير سجل الملاحظات", "Export Feedback Log", arabic_default),
                data=feedback_content,
                file_name="feedback.log.jsonl",
                mime="application/jsonl",
                width="stretch",
            )
            st.download_button(
                label=bi("تصدير الحالات", "Export Cases", arabic_default),
                data=json.dumps(list_cases(conn), ensure_ascii=False, indent=2),
                file_name="cases.export.json",
                mime="application/json",
                width="stretch",
            )
            st.download_button(
                label=bi("تصدير أحداث سير العمل", "Export Workflow Events", arabic_default),
                data=json.dumps(list_workflow_events(conn, limit=1000), ensure_ascii=False, indent=2),
                file_name="workflow_events.export.json",
                mime="application/json",
                width="stretch",
            )
            if DB_PATH.exists():
                st.download_button(
                    label=bi("تنزيل نسخة قاعدة البيانات", "Download Database Backup", arabic_default),
                    data=DB_PATH.read_bytes(),
                    file_name="triage.db",
                    mime="application/octet-stream",
                    width="stretch",
                )
        else:
            st.caption(bi("تصدير السجل متاح للمدقق أو المشرف فقط.", "Audit export is available to auditor/supervisor only.", arabic_default))

conn.close()
