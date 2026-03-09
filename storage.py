from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from workflow import can_transition

CURRENT_SCHEMA_VERSION = 7


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _sqlite_error_message(exc: sqlite3.Error) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    lowered = message.lower()
    if "database is locked" in lowered or "database table is locked" in lowered:
        return "DB_BUSY: database is locked, retry in a moment"
    return f"DB_ERROR: {message}"


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(r[1] == column_name for r in rows)


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    with conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_meta(version INTEGER NOT NULL)")
        conn.execute("DELETE FROM schema_meta")
        conn.execute("INSERT INTO schema_meta(version) VALUES (?)", (version,))


def get_schema_version(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "schema_meta"):
        return 0
    row = conn.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
    if row is None:
        return 0
    return int(row[0])


def init_db(conn: sqlite3.Connection, schema_path: Path) -> None:
    schema = schema_path.read_text(encoding="utf-8")
    with conn:
        for raw_statement in schema.split(";"):
            statement = raw_statement.strip()
            if not statement:
                continue
            sql = f"{statement};"
            try:
                conn.execute(sql)
            except sqlite3.OperationalError as exc:
                lowered = str(exc).lower()
                if statement.upper().startswith("CREATE INDEX") and "no such column" in lowered:
                    continue
                raise


def _infer_legacy_schema_version(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "cases") or not _table_exists(conn, "workflow_events"):
        return 0

    has_saved_views = _table_exists(conn, "saved_views")
    has_notifications = _table_exists(conn, "notifications")
    has_users = _table_exists(conn, "users")
    has_auth_provider = _column_exists(conn, "users", "auth_provider") if has_users else False
    has_mfa_required = _column_exists(conn, "users", "mfa_required") if has_users else False
    has_mfa_type = _column_exists(conn, "users", "mfa_type") if has_users else False
    has_totp_secret = _column_exists(conn, "users", "totp_secret") if has_users else False
    if has_saved_views and has_notifications and has_users and has_auth_provider and has_mfa_required and has_mfa_type and has_totp_secret:
        return 7
    if has_saved_views and has_notifications and has_users and has_auth_provider:
        return 6
    if has_saved_views and has_notifications and has_users:
        return 5
    if has_saved_views and has_notifications:
        return 4

    case_columns = {
        "state",
        "assigned_team",
        "assigned_user",
        "updated_at_utc",
        "triaged_at_utc",
        "assigned_at_utc",
        "resolved_at_utc",
        "closed_at_utc",
    }
    has_case_v2 = all(_column_exists(conn, "cases", c) for c in case_columns)
    has_event_meta = _column_exists(conn, "workflow_events", "meta_json")

    if has_case_v2 and has_event_meta:
        return 3
    if has_case_v2:
        return 2
    return 1


def _ensure_case_column(conn: sqlite3.Connection, column_name: str, ddl_suffix: str) -> None:
    if not _column_exists(conn, "cases", column_name):
        conn.execute(f"ALTER TABLE cases ADD COLUMN {column_name} {ddl_suffix}")


def _ensure_event_column(conn: sqlite3.Connection, column_name: str, ddl_suffix: str) -> None:
    if not _column_exists(conn, "workflow_events", column_name):
        conn.execute(f"ALTER TABLE workflow_events ADD COLUMN {column_name} {ddl_suffix}")


def _ensure_user_column(conn: sqlite3.Connection, column_name: str, ddl_suffix: str) -> None:
    if not _column_exists(conn, "users", column_name):
        conn.execute(f"ALTER TABLE users ADD COLUMN {column_name} {ddl_suffix}")


def apply_migrations(conn: sqlite3.Connection, from_version: int, to_version: int) -> None:
    if from_version >= to_version:
        return

    version = from_version
    while version < to_version:
        next_version = version + 1

        if next_version == 2:
            with conn:
                _ensure_case_column(conn, "state", "TEXT NOT NULL DEFAULT 'NEW'")
                _ensure_case_column(conn, "assigned_team", "TEXT")
                _ensure_case_column(conn, "assigned_user", "TEXT")
                _ensure_case_column(conn, "triaged_at_utc", "TEXT")
                _ensure_case_column(conn, "assigned_at_utc", "TEXT")
                _ensure_case_column(conn, "resolved_at_utc", "TEXT")
                _ensure_case_column(conn, "closed_at_utc", "TEXT")
                _ensure_case_column(conn, "updated_at_utc", "TEXT NOT NULL DEFAULT ''")

                now_iso = to_utc_iso(utc_now())
                conn.execute(
                    "UPDATE cases SET updated_at_utc = COALESCE(NULLIF(updated_at_utc, ''), created_at_utc, ?)",
                    (now_iso,),
                )

                conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_state ON cases(state)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_department ON cases(department_en)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_assigned_user ON cases(assigned_user)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_sla_deadline ON cases(sla_deadline_utc)")

        if next_version == 3:
            with conn:
                _ensure_event_column(conn, "meta_json", "TEXT NOT NULL DEFAULT '{}'")
                conn.execute("UPDATE workflow_events SET meta_json = COALESCE(NULLIF(meta_json, ''), '{}')")

                conn.execute("CREATE INDEX IF NOT EXISTS idx_events_case_id ON workflow_events(case_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON workflow_events(event_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON workflow_events(timestamp_utc)")

                conn.execute("CREATE TABLE IF NOT EXISTS schema_meta(version INTEGER NOT NULL)")

        if next_version == 4:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS saved_views (
                      view_id TEXT PRIMARY KEY,
                      user_id TEXT NOT NULL,
                      name TEXT NOT NULL,
                      filters_json TEXT NOT NULL,
                      is_default INTEGER NOT NULL DEFAULT 0,
                      created_at_utc TEXT NOT NULL,
                      updated_at_utc TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS notifications (
                      notification_id TEXT PRIMARY KEY,
                      case_id TEXT,
                      severity TEXT NOT NULL,
                      type TEXT NOT NULL,
                      message_ar TEXT NOT NULL,
                      message_en TEXT NOT NULL,
                      ack_by_user TEXT,
                      ack_at_utc TEXT,
                      created_at_utc TEXT NOT NULL,
                      updated_at_utc TEXT NOT NULL
                    )
                    """
                )
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_views_user_name ON saved_views(user_id, name)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_saved_views_user_default ON saved_views(user_id, is_default)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_case ON notifications(case_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_ack ON notifications(ack_at_utc)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at_utc)")
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_unique_key ON notifications(type, case_id)")

        if next_version == 5:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                      user_id TEXT PRIMARY KEY,
                      display_name TEXT NOT NULL,
                      auth_provider TEXT NOT NULL DEFAULT 'local',
                      role TEXT NOT NULL,
                      password_hash TEXT NOT NULL,
                      mfa_required INTEGER NOT NULL DEFAULT 0,
                      mfa_type TEXT NOT NULL DEFAULT 'none',
                      totp_secret TEXT,
                      status TEXT NOT NULL DEFAULT 'active',
                      failed_attempts INTEGER NOT NULL DEFAULT 0,
                      locked_until_utc TEXT,
                      password_changed_at_utc TEXT NOT NULL,
                      last_login_at_utc TEXT,
                      created_at_utc TEXT NOT NULL,
                      updated_at_utc TEXT NOT NULL
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")

        if next_version == 6:
            with conn:
                _ensure_user_column(conn, "auth_provider", "TEXT NOT NULL DEFAULT 'local'")
                conn.execute("UPDATE users SET auth_provider = COALESCE(NULLIF(auth_provider, ''), 'local')")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_users_provider ON users(auth_provider)")

        if next_version == 7:
            with conn:
                _ensure_user_column(conn, "mfa_required", "INTEGER NOT NULL DEFAULT 0")
                _ensure_user_column(conn, "mfa_type", "TEXT NOT NULL DEFAULT 'none'")
                _ensure_user_column(conn, "totp_secret", "TEXT")
                conn.execute("UPDATE users SET mfa_required = COALESCE(mfa_required, 0)")
                conn.execute(
                    """
                    UPDATE users
                    SET mfa_type = CASE
                        WHEN auth_provider != 'local' THEN 'provider'
                        WHEN COALESCE(NULLIF(totp_secret, ''), '') != '' OR COALESCE(mfa_required, 0) = 1 THEN 'totp'
                        ELSE 'none'
                    END
                    """
                )
                conn.execute(
                    """
                    UPDATE users
                    SET mfa_required = CASE
                        WHEN auth_provider = 'local' AND COALESCE(mfa_type, 'none') = 'totp' THEN 1
                        ELSE 0
                    END
                    """
                )

        version = next_version

    _set_schema_version(conn, to_version)


def ensure_schema(conn: sqlite3.Connection, schema_path: Path) -> None:
    # Infer legacy shape before init_db creates latest tables (which can mask legacy state).
    preexisting_version = get_schema_version(conn)
    inferred_legacy_version = _infer_legacy_schema_version(conn) if preexisting_version == 0 else 0

    init_db(conn, schema_path)

    version = get_schema_version(conn)
    if version == 0:
        if inferred_legacy_version == 0:
            _set_schema_version(conn, CURRENT_SCHEMA_VERSION)
            version = CURRENT_SCHEMA_VERSION
        else:
            _set_schema_version(conn, inferred_legacy_version)
            version = inferred_legacy_version

    if version < CURRENT_SCHEMA_VERSION:
        apply_migrations(conn, version, CURRENT_SCHEMA_VERSION)
    elif version > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {version} is newer than supported version {CURRENT_SCHEMA_VERSION}."
        )


def _deadline_for_urgency(urgency_en: str, created_at: datetime) -> datetime:
    if urgency_en.strip().lower() == "urgent":
        return created_at + timedelta(hours=4)
    return created_at + timedelta(hours=24)


def seed_cases_if_empty(conn: sqlite3.Connection, example_data_path: Path) -> None:
    count = conn.execute("SELECT COUNT(*) AS c FROM cases").fetchone()["c"]
    if count > 0:
        return

    raw = json.loads(example_data_path.read_text(encoding="utf-8"))
    now = utc_now()
    with conn:
        for idx, record in enumerate(raw):
            created_at = now - timedelta(minutes=idx * 7)
            deadline = _deadline_for_urgency(str(record["urgency_en"]), created_at)
            conn.execute(
                """
                INSERT INTO cases (
                  case_id, request_text_ar, request_text_en, intent_ar, intent_en,
                  urgency_ar, urgency_en, department_ar, department_en, confidence,
                  reason_ar, reason_en, detected_keywords_ar, detected_keywords_en,
                  detected_time_ar, detected_time_en, policy_rule, status_ar, status_en,
                  state, assigned_team, assigned_user, sla_deadline_utc, created_at_utc,
                  triaged_at_utc, assigned_at_utc, resolved_at_utc, closed_at_utc, updated_at_utc
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record["id"]),
                    str(record["request_ar"]),
                    str(record["request_en"]),
                    str(record["intent_ar"]),
                    str(record["intent_en"]),
                    str(record["urgency_ar"]),
                    str(record["urgency_en"]),
                    str(record["department_ar"]),
                    str(record["department_en"]),
                    float(record["confidence"]),
                    str(record["reason_ar"]),
                    str(record["reason_en"]),
                    str(record["detected_keywords_ar"]),
                    str(record["detected_keywords_en"]),
                    str(record["detected_time_ar"]),
                    str(record["detected_time_en"]),
                    str(record["policy_rule"]),
                    str(record["status_ar"]),
                    str(record["status_en"]),
                    "NEW",
                    None,
                    None,
                    to_utc_iso(deadline),
                    to_utc_iso(created_at),
                    None,
                    None,
                    None,
                    None,
                    to_utc_iso(created_at),
                ),
            )


def row_to_case(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def list_cases(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM cases ORDER BY updated_at_utc DESC, case_id ASC").fetchall()
    return [row_to_case(r) for r in rows]


def get_case(conn: sqlite3.Connection, case_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    return row_to_case(row) if row else None


def insert_workflow_event(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_user_id: str,
    actor_role: str,
    event_type: str,
    from_state: str | None,
    to_state: str | None,
    reason: str | None,
    meta: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO workflow_events (
                  event_id, case_id, actor_user_id, actor_role, event_type, from_state,
                  to_state, reason, timestamp_utc, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    case_id,
                    actor_user_id,
                    actor_role,
                    event_type,
                    from_state,
                    to_state,
                    reason,
                    to_utc_iso(utc_now()),
                    json.dumps(meta or {}, ensure_ascii=False),
                ),
            )
        return True, "ok"
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc)


def compute_sla_state(case: dict[str, Any]) -> dict[str, Any]:
    deadline = parse_utc_iso(str(case["sla_deadline_utc"]))
    created = parse_utc_iso(str(case["created_at_utc"]))
    now = utc_now()
    remaining_minutes = int((deadline - now).total_seconds() // 60)
    total_minutes = max(1, int((deadline - created).total_seconds() // 60))
    at_risk_threshold = int(total_minutes * 0.2)

    if remaining_minutes <= 0:
        status = "BREACHED"
    elif remaining_minutes <= max(60, at_risk_threshold):
        status = "AT_RISK"
    else:
        status = "ON_TRACK"

    return {
        "case_id": case["case_id"],
        "status": status,
        "deadline_utc": case["sla_deadline_utc"],
        "minutes_remaining": remaining_minutes,
    }


def transition_case_state(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    to_state: str,
    actor_user_id: str,
    actor_role: str,
    reason: str | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    case = get_case(conn, case_id)
    if not case:
        return False, "Case not found", None

    from_state = str(case["state"])
    if not can_transition(actor_role, from_state, to_state):
        return False, f"Transition {from_state} -> {to_state} not allowed for role {actor_role}", case

    now_iso = to_utc_iso(utc_now())
    updates: dict[str, Any] = {"state": to_state, "updated_at_utc": now_iso}
    if to_state == "TRIAGED" and not case.get("triaged_at_utc"):
        updates["triaged_at_utc"] = now_iso
    if to_state == "ASSIGNED" and not case.get("assigned_at_utc"):
        updates["assigned_at_utc"] = now_iso
    if to_state == "RESOLVED":
        updates["resolved_at_utc"] = now_iso
    if to_state == "CLOSED":
        updates["closed_at_utc"] = now_iso
    if to_state == "IN_PROGRESS" and from_state == "CLOSED":
        updates["closed_at_utc"] = None

    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
    params = list(updates.values()) + [case_id]

    try:
        with conn:
            conn.execute(f"UPDATE cases SET {set_clause} WHERE case_id = ?", params)
            conn.execute(
                """
                INSERT INTO workflow_events (
                  event_id, case_id, actor_user_id, actor_role, event_type, from_state,
                  to_state, reason, timestamp_utc, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    case_id,
                    actor_user_id,
                    actor_role,
                    "STATE_TRANSITION",
                    from_state,
                    to_state,
                    reason,
                    to_utc_iso(utc_now()),
                    json.dumps({"updates": list(updates.keys())}, ensure_ascii=False),
                ),
            )
        return True, "ok", get_case(conn, case_id)
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc), case


def assign_case(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    assigned_team: str,
    assigned_user: str | None,
    actor_user_id: str,
    actor_role: str,
    reason: str | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    case = get_case(conn, case_id)
    if not case:
        return False, "Case not found", None

    if assigned_team == "Human Review" and actor_role != "supervisor":
        return False, "Only supervisor can transfer to Human Review", case

    now_iso = to_utc_iso(utc_now())
    from_state = str(case["state"])
    to_state = from_state
    if assigned_team == "Human Review":
        to_state = "ESCALATED"
    elif from_state in {"NEW", "TRIAGED"}:
        to_state = "ASSIGNED"

    if not can_transition(actor_role, from_state, to_state):
        return False, f"Assignment would require disallowed transition {from_state} -> {to_state}", case

    updates: dict[str, Any] = {
        "assigned_team": assigned_team,
        "assigned_user": assigned_user,
        "updated_at_utc": now_iso,
    }
    if to_state != from_state:
        updates["state"] = to_state
    if to_state == "ASSIGNED" and not case.get("assigned_at_utc"):
        updates["assigned_at_utc"] = now_iso

    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
    params = list(updates.values()) + [case_id]

    event_type = "ASSIGN" if not case.get("assigned_user") and not case.get("assigned_team") else "REASSIGN"
    if assigned_team == "Human Review":
        event_type = "TRANSFER_HUMAN_REVIEW"

    try:
        with conn:
            conn.execute(f"UPDATE cases SET {set_clause} WHERE case_id = ?", params)
            conn.execute(
                """
                INSERT INTO workflow_events (
                  event_id, case_id, actor_user_id, actor_role, event_type, from_state,
                  to_state, reason, timestamp_utc, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    case_id,
                    actor_user_id,
                    actor_role,
                    event_type,
                    from_state,
                    to_state,
                    reason,
                    to_utc_iso(utc_now()),
                    json.dumps(
                        {"assigned_team": assigned_team, "assigned_user": assigned_user},
                        ensure_ascii=False,
                    ),
                ),
            )
        return True, "ok", get_case(conn, case_id)
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc), case


def approve_case(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_user_id: str,
    actor_role: str,
    reason: str | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    case = get_case(conn, case_id)
    if not case:
        return False, "Case not found", None

    from_state = str(case["state"])
    to_state = from_state
    now_iso = to_utc_iso(utc_now())
    updates: dict[str, Any] = {"updated_at_utc": now_iso}

    if from_state == "NEW":
        to_state = "TRIAGED"
        if not can_transition(actor_role, from_state, to_state):
            return False, f"Transition {from_state} -> {to_state} not allowed for role {actor_role}", case
        updates["state"] = to_state
        if not case.get("triaged_at_utc"):
            updates["triaged_at_utc"] = now_iso

    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
    params = list(updates.values()) + [case_id]

    try:
        with conn:
            conn.execute(f"UPDATE cases SET {set_clause} WHERE case_id = ?", params)
            conn.execute(
                """
                INSERT INTO workflow_events (
                  event_id, case_id, actor_user_id, actor_role, event_type, from_state,
                  to_state, reason, timestamp_utc, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    case_id,
                    actor_user_id,
                    actor_role,
                    "APPROVE",
                    from_state,
                    to_state,
                    reason,
                    to_utc_iso(utc_now()),
                    json.dumps({"updates": list(updates.keys())}, ensure_ascii=False),
                ),
            )
        return True, "ok", get_case(conn, case_id)
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc), case


def override_case(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_user_id: str,
    actor_role: str,
    reason: str | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    if actor_role != "supervisor":
        case = get_case(conn, case_id)
        return False, "Only supervisor can override", case

    case = get_case(conn, case_id)
    if not case:
        return False, "Case not found", None

    from_state = str(case["state"])
    to_state = "ESCALATED"
    if not can_transition(actor_role, from_state, to_state):
        return False, f"Transition {from_state} -> {to_state} not allowed for role {actor_role}", case

    now_iso = to_utc_iso(utc_now())
    try:
        with conn:
            conn.execute(
                """
                UPDATE cases
                SET state = ?, assigned_team = ?, assigned_user = ?, updated_at_utc = ?
                WHERE case_id = ?
                """,
                (to_state, "Human Review", None, now_iso, case_id),
            )
            conn.execute(
                """
                INSERT INTO workflow_events (
                  event_id, case_id, actor_user_id, actor_role, event_type, from_state,
                  to_state, reason, timestamp_utc, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    case_id,
                    actor_user_id,
                    actor_role,
                    "OVERRIDE",
                    from_state,
                    to_state,
                    reason,
                    to_utc_iso(utc_now()),
                    json.dumps({"assigned_team": "Human Review", "assigned_user": None}, ensure_ascii=False),
                ),
            )
        return True, "ok", get_case(conn, case_id)
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc), case


def record_case_select(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_user_id: str,
    actor_role: str,
) -> tuple[bool, str]:
    case = get_case(conn, case_id)
    if not case:
        return False, "Case not found"

    return insert_workflow_event(
        conn,
        case_id=case_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        event_type="SELECT",
        from_state=str(case["state"]),
        to_state=str(case["state"]),
        reason=None,
    )


def list_pending_escalations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM cases WHERE state = 'ESCALATED' ORDER BY updated_at_utc DESC"
    ).fetchall()
    return [row_to_case(r) for r in rows]


def list_low_confidence(conn: sqlite3.Connection, threshold: float = 0.75) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM cases
        WHERE confidence < ? AND state <> 'CLOSED'
        ORDER BY confidence ASC, updated_at_utc DESC
        """,
        (threshold,),
    ).fetchall()
    return [row_to_case(r) for r in rows]


def list_recent_overrides(conn: sqlite3.Connection, limit: int = 25) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event_id, case_id, actor_user_id, actor_role, event_type, from_state, to_state, reason, timestamp_utc
        FROM workflow_events
        WHERE event_type IN ('OVERRIDE', 'TRANSFER_HUMAN_REVIEW')
        ORDER BY timestamp_utc DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_workflow_events(conn: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event_id, case_id, actor_user_id, actor_role, event_type, from_state, to_state, reason, timestamp_utc, meta_json
        FROM workflow_events
        ORDER BY timestamp_utc DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_case_workflow_events(conn: sqlite3.Connection, case_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event_id, case_id, actor_user_id, actor_role, event_type, from_state, to_state, reason, timestamp_utc, meta_json
        FROM workflow_events
        WHERE case_id = ?
        ORDER BY timestamp_utc DESC
        LIMIT ?
        """,
        (case_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def list_saved_views(conn: sqlite3.Connection, user_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT view_id, user_id, name, filters_json, is_default, created_at_utc, updated_at_utc
        FROM saved_views
        WHERE user_id = ?
        ORDER BY is_default DESC, name ASC
        """,
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_users(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT user_id, display_name, role, status, failed_attempts, locked_until_utc,
               mfa_required, mfa_type, totp_secret,
               auth_provider, password_changed_at_utc, last_login_at_utc, created_at_utc, updated_at_utc
        FROM users
        ORDER BY display_name ASC, user_id ASC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_user(conn: sqlite3.Connection, user_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT user_id, display_name, auth_provider, role, password_hash, status, failed_attempts, locked_until_utc,
               mfa_required, mfa_type, totp_secret,
               password_changed_at_utc, last_login_at_utc, created_at_utc, updated_at_utc
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def bootstrap_auth_users(conn: sqlite3.Connection, auth_users: dict[str, dict[str, Any]]) -> tuple[bool, str]:
    now_iso = to_utc_iso(utc_now())
    try:
        with conn:
            for user_id, payload in auth_users.items():
                role = str(payload.get("role", "")).strip().lower()
                password_hash = str(payload.get("password_hash", "")).strip()
                display_name = str(payload.get("display_name", "")).strip() or user_id.replace("_", " ").title()
                status = str(payload.get("status", "active")).strip().lower() or "active"
                totp_secret = str(payload.get("totp_secret", "")).strip() or None
                mfa_required = 1 if totp_secret else 0
                mfa_type = "totp" if totp_secret else "none"
                if not role or not password_hash:
                    continue

                existing = conn.execute(
                    "SELECT user_id, password_changed_at_utc, created_at_utc FROM users WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                if existing:
                    password_changed_at_utc = (
                        now_iso
                        if password_hash != conn.execute(
                            "SELECT password_hash FROM users WHERE user_id = ?",
                            (user_id,),
                        ).fetchone()[0]
                        else existing["password_changed_at_utc"]
                    )
                    conn.execute(
                        """
                        UPDATE users
                        SET display_name = ?, auth_provider = 'local', role = ?, password_hash = ?, mfa_required = ?, mfa_type = ?, totp_secret = ?, status = ?, password_changed_at_utc = ?, updated_at_utc = ?
                        WHERE user_id = ?
                        """,
                        (display_name, role, password_hash, mfa_required, mfa_type, totp_secret, status, password_changed_at_utc, now_iso, user_id),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO users (
                          user_id, display_name, auth_provider, role, password_hash, mfa_required, mfa_type, totp_secret, status, failed_attempts,
                          locked_until_utc, password_changed_at_utc, last_login_at_utc, created_at_utc, updated_at_utc
                        ) VALUES (?, ?, 'local', ?, ?, ?, ?, ?, ?, 0, NULL, ?, NULL, ?, ?)
                        """,
                        (user_id, display_name, role, password_hash, mfa_required, mfa_type, totp_secret, status, now_iso, now_iso, now_iso),
                    )
        return True, "ok"
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc)


def upsert_external_user(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    display_name: str,
    auth_provider: str,
    role: str,
    status: str = "active",
) -> tuple[bool, str, dict[str, Any] | None]:
    now_iso = to_utc_iso(utc_now())
    try:
        with conn:
            existing = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE users
                    SET display_name = ?, auth_provider = ?, role = ?, mfa_required = 0, mfa_type = 'provider', totp_secret = NULL, status = ?, updated_at_utc = ?
                    WHERE user_id = ?
                    """,
                    (display_name, auth_provider, role, status, now_iso, user_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO users (
                      user_id, display_name, auth_provider, role, password_hash, mfa_required, mfa_type, totp_secret, status, failed_attempts,
                      locked_until_utc, password_changed_at_utc, last_login_at_utc, created_at_utc, updated_at_utc
                    ) VALUES (?, ?, ?, ?, ?, 0, 'provider', NULL, ?, 0, NULL, ?, NULL, ?, ?)
                    """,
                    (user_id, display_name, auth_provider, role, "oidc$managed", status, now_iso, now_iso, now_iso),
                )
        return True, "ok", get_user(conn, user_id)
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc), None


def record_login_failure(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    lockout_after: int = 5,
    lockout_minutes: int = 15,
) -> tuple[bool, str, dict[str, Any] | None]:
    try:
        with conn:
            row = conn.execute(
                """
                SELECT user_id, display_name, auth_provider, role, password_hash, status, failed_attempts, locked_until_utc,
                       mfa_required, mfa_type, totp_secret,
                       password_changed_at_utc, last_login_at_utc, created_at_utc, updated_at_utc
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if not row:
                return False, "User not found", None

            failed_attempts = int(row["failed_attempts"]) + 1
            locked_until_utc = row["locked_until_utc"]
            if failed_attempts >= max(1, lockout_after):
                locked_until_utc = to_utc_iso(utc_now() + timedelta(minutes=max(1, lockout_minutes)))
            conn.execute(
                """
                UPDATE users
                SET failed_attempts = ?, locked_until_utc = ?, updated_at_utc = ?
                WHERE user_id = ?
                """,
                (failed_attempts, locked_until_utc, to_utc_iso(utc_now()), user_id),
            )
        return True, "ok", get_user(conn, user_id)
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc), None


def create_local_user(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    display_name: str,
    role: str,
    password_hash: str,
    status: str = "active",
    mfa_required: bool = False,
    totp_secret: str | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    now_iso = to_utc_iso(utc_now())
    mfa_type = "totp" if mfa_required else "none"
    try:
        with conn:
            existing = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if existing:
                return False, "User already exists", None
            conn.execute(
                """
                INSERT INTO users (
                  user_id, display_name, auth_provider, role, password_hash, mfa_required, mfa_type, totp_secret, status,
                  failed_attempts, locked_until_utc, password_changed_at_utc, last_login_at_utc, created_at_utc, updated_at_utc
                ) VALUES (?, ?, 'local', ?, ?, ?, ?, ?, ?, 0, NULL, ?, NULL, ?, ?)
                """,
                (
                    user_id,
                    display_name,
                    role,
                    password_hash,
                    1 if mfa_required else 0,
                    mfa_type,
                    totp_secret if mfa_required else None,
                    status,
                    now_iso,
                    now_iso,
                    now_iso,
                ),
            )
        return True, "ok", get_user(conn, user_id)
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc), None


def set_user_status(conn: sqlite3.Connection, user_id: str, status: str) -> tuple[bool, str, dict[str, Any] | None]:
    try:
        with conn:
            row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not row:
                return False, "User not found", None
            conn.execute(
                "UPDATE users SET status = ?, updated_at_utc = ? WHERE user_id = ?",
                (status, to_utc_iso(utc_now()), user_id),
            )
        return True, "ok", get_user(conn, user_id)
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc), None


def set_user_role(conn: sqlite3.Connection, user_id: str, role: str) -> tuple[bool, str, dict[str, Any] | None]:
    try:
        with conn:
            row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not row:
                return False, "User not found", None
            conn.execute(
                "UPDATE users SET role = ?, updated_at_utc = ? WHERE user_id = ?",
                (role, to_utc_iso(utc_now()), user_id),
            )
        return True, "ok", get_user(conn, user_id)
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc), None


def reset_local_user_password(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    password_hash: str,
) -> tuple[bool, str, dict[str, Any] | None]:
    now_iso = to_utc_iso(utc_now())
    try:
        with conn:
            row = conn.execute("SELECT user_id, auth_provider FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not row:
                return False, "User not found", None
            if str(row["auth_provider"]) != "local":
                return False, "Password reset is local-only", None
            conn.execute(
                """
                UPDATE users
                SET password_hash = ?, failed_attempts = 0, locked_until_utc = NULL, password_changed_at_utc = ?, updated_at_utc = ?
                WHERE user_id = ?
                """,
                (password_hash, now_iso, now_iso, user_id),
            )
        return True, "ok", get_user(conn, user_id)
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc), None


def set_local_totp_requirement(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    mfa_required: bool,
    totp_secret: str | None,
) -> tuple[bool, str, dict[str, Any] | None]:
    try:
        with conn:
            row = conn.execute("SELECT user_id, auth_provider FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not row:
                return False, "User not found", None
            if str(row["auth_provider"]) != "local":
                return False, "TOTP management is local-only", None
            effective_secret = (totp_secret or "").strip() or None
            effective_required = bool(mfa_required and effective_secret)
            conn.execute(
                """
                UPDATE users
                SET mfa_required = ?, mfa_type = ?, totp_secret = ?, updated_at_utc = ?
                WHERE user_id = ?
                """,
                (
                    1 if effective_required else 0,
                    "totp" if effective_required else "none",
                    effective_secret if effective_required else None,
                    to_utc_iso(utc_now()),
                    user_id,
                ),
            )
        return True, "ok", get_user(conn, user_id)
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc), None


def record_login_success(conn: sqlite3.Connection, user_id: str) -> tuple[bool, str, dict[str, Any] | None]:
    now_iso = to_utc_iso(utc_now())
    try:
        with conn:
            row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not row:
                return False, "User not found", None
            conn.execute(
                """
                UPDATE users
                SET failed_attempts = 0, locked_until_utc = NULL, last_login_at_utc = ?, updated_at_utc = ?
                WHERE user_id = ?
                """,
                (now_iso, now_iso, user_id),
            )
        return True, "ok", get_user(conn, user_id)
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc), None


def upsert_saved_view(
    conn: sqlite3.Connection,
    user_id: str,
    name: str,
    filters: dict[str, Any],
    is_default: bool,
) -> tuple[bool, str]:
    now_iso = to_utc_iso(utc_now())
    filters_json = json.dumps(filters, ensure_ascii=False, sort_keys=True)
    try:
        with conn:
            if is_default:
                conn.execute("UPDATE saved_views SET is_default = 0 WHERE user_id = ?", (user_id,))

            existing = conn.execute(
                "SELECT view_id FROM saved_views WHERE user_id = ? AND name = ?",
                (user_id, name),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE saved_views
                    SET filters_json = ?, is_default = ?, updated_at_utc = ?
                    WHERE view_id = ?
                    """,
                    (filters_json, 1 if is_default else 0, now_iso, existing["view_id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO saved_views (
                      view_id, user_id, name, filters_json, is_default, created_at_utc, updated_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        user_id,
                        name,
                        filters_json,
                        1 if is_default else 0,
                        now_iso,
                        now_iso,
                    ),
                )
        return True, "ok"
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc)


def delete_saved_view(conn: sqlite3.Connection, user_id: str, view_id: str) -> tuple[bool, str]:
    try:
        with conn:
            row = conn.execute(
                "SELECT view_id FROM saved_views WHERE view_id = ? AND user_id = ?",
                (view_id, user_id),
            ).fetchone()
            if not row:
                return False, "Saved view not found"
            conn.execute("DELETE FROM saved_views WHERE view_id = ?", (view_id,))
        return True, "ok"
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc)


def upsert_notification(
    conn: sqlite3.Connection,
    *,
    case_id: str | None,
    severity: str,
    notif_type: str,
    message_ar: str,
    message_en: str,
) -> tuple[bool, str]:
    now_iso = to_utc_iso(utc_now())
    try:
        with conn:
            existing = conn.execute(
                "SELECT notification_id FROM notifications WHERE type = ? AND case_id IS ?",
                (notif_type, case_id),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE notifications
                    SET severity = ?, message_ar = ?, message_en = ?, updated_at_utc = ?
                    WHERE notification_id = ?
                    """,
                    (severity, message_ar, message_en, now_iso, existing["notification_id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO notifications (
                      notification_id, case_id, severity, type, message_ar, message_en,
                      ack_by_user, ack_at_utc, created_at_utc, updated_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        case_id,
                        severity,
                        notif_type,
                        message_ar,
                        message_en,
                        None,
                        None,
                        now_iso,
                        now_iso,
                    ),
                )
        return True, "ok"
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc)


def list_notifications(conn: sqlite3.Connection, include_acked: bool = False) -> list[dict[str, Any]]:
    if include_acked:
        rows = conn.execute(
            """
            SELECT notification_id, case_id, severity, type, message_ar, message_en,
                   ack_by_user, ack_at_utc, created_at_utc, updated_at_utc
            FROM notifications
            ORDER BY created_at_utc DESC
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT notification_id, case_id, severity, type, message_ar, message_en,
                   ack_by_user, ack_at_utc, created_at_utc, updated_at_utc
            FROM notifications
            WHERE ack_at_utc IS NULL
            ORDER BY created_at_utc DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def ack_notification(conn: sqlite3.Connection, notification_id: str, user_id: str) -> tuple[bool, str]:
    now_iso = to_utc_iso(utc_now())
    try:
        with conn:
            row = conn.execute(
                "SELECT notification_id FROM notifications WHERE notification_id = ?",
                (notification_id,),
            ).fetchone()
            if not row:
                return False, "Notification not found"
            conn.execute(
                """
                UPDATE notifications
                SET ack_by_user = ?, ack_at_utc = ?, updated_at_utc = ?
                WHERE notification_id = ?
                """,
                (user_id, now_iso, now_iso, notification_id),
            )
        return True, "ok"
    except sqlite3.Error as exc:
        return False, _sqlite_error_message(exc)


def export_cases_csv_rows(cases: list[dict[str, Any]], arabic_default: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        rows.append(
            {
                ("رقم الحالة" if arabic_default else "Case ID"): str(case.get("case_id", "")),
                ("الطلب" if arabic_default else "Request"): str(
                    case.get("request_text_ar") if arabic_default else case.get("request_text_en")
                ),
                ("النية" if arabic_default else "Intent"): str(
                    case.get("intent_ar") if arabic_default else case.get("intent_en")
                ),
                ("الأولوية" if arabic_default else "Urgency"): str(
                    case.get("urgency_ar") if arabic_default else case.get("urgency_en")
                ),
                ("الإدارة" if arabic_default else "Department"): str(
                    case.get("department_ar") if arabic_default else case.get("department_en")
                ),
                ("الحالة" if arabic_default else "State"): str(case.get("state", "")),
                ("المستخدم المسند" if arabic_default else "Assigned User"): str(case.get("assigned_user") or ""),
                "SLA": str(compute_sla_state(case).get("status", "")),
            }
        )
    return rows
