from __future__ import annotations

import sqlite3
from pathlib import Path

from storage import CURRENT_SCHEMA_VERSION, connect_db, ensure_schema, get_schema_version

BASE_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BASE_DIR / "schema.sql"


def _legacy_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE cases (
              case_id TEXT PRIMARY KEY,
              request_text_ar TEXT NOT NULL,
              request_text_en TEXT NOT NULL,
              intent_ar TEXT NOT NULL,
              intent_en TEXT NOT NULL,
              urgency_ar TEXT NOT NULL,
              urgency_en TEXT NOT NULL,
              department_ar TEXT NOT NULL,
              department_en TEXT NOT NULL,
              confidence REAL NOT NULL,
              reason_ar TEXT NOT NULL,
              reason_en TEXT NOT NULL,
              detected_keywords_ar TEXT NOT NULL,
              detected_keywords_en TEXT NOT NULL,
              detected_time_ar TEXT NOT NULL,
              detected_time_en TEXT NOT NULL,
              policy_rule TEXT NOT NULL,
              status_ar TEXT NOT NULL,
              status_en TEXT NOT NULL,
              sla_deadline_utc TEXT NOT NULL,
              created_at_utc TEXT NOT NULL
            );

            CREATE TABLE workflow_events (
              event_id TEXT PRIMARY KEY,
              case_id TEXT NOT NULL,
              actor_user_id TEXT NOT NULL,
              actor_role TEXT NOT NULL,
              event_type TEXT NOT NULL,
              from_state TEXT,
              to_state TEXT,
              reason TEXT,
              timestamp_utc TEXT NOT NULL
            );
            """
        )

        conn.execute(
            """
            INSERT INTO cases (
              case_id, request_text_ar, request_text_en, intent_ar, intent_en,
              urgency_ar, urgency_en, department_ar, department_en, confidence,
              reason_ar, reason_en, detected_keywords_ar, detected_keywords_en,
              detected_time_ar, detected_time_en, policy_rule, status_ar, status_en,
              sla_deadline_utc, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-1",
                "طلب قديم",
                "Legacy request",
                "خدمة",
                "Service",
                "عاجل",
                "Urgent",
                "الهجرة",
                "Immigration",
                0.81,
                "سبب",
                "Reason",
                "تنتهي",
                "expires",
                "غدا",
                "tomorrow",
                "PR-17 urgency",
                "في الانتظار",
                "In Queue",
                "2026-03-01T00:00:00Z",
                "2026-02-25T00:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_migrates_legacy_schema_to_current(tmp_path):
    db_path = tmp_path / "legacy.db"
    _legacy_db(db_path)

    conn = connect_db(db_path)
    try:
        ensure_schema(conn, SCHEMA_PATH)

        assert get_schema_version(conn) == CURRENT_SCHEMA_VERSION

        case_columns = {row[1] for row in conn.execute("PRAGMA table_info(cases)").fetchall()}
        assert "state" in case_columns
        assert "assigned_team" in case_columns
        assert "assigned_user" in case_columns
        assert "updated_at_utc" in case_columns

        event_columns = {row[1] for row in conn.execute("PRAGMA table_info(workflow_events)").fetchall()}
        assert "meta_json" in event_columns

        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='saved_views'"
        ).fetchone()
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='notifications'"
        ).fetchone()

        count = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        state = conn.execute("SELECT state FROM cases WHERE case_id = 'legacy-1'").fetchone()[0]
        assert count == 1
        assert state == "NEW"
    finally:
        conn.close()


def test_ensure_schema_is_idempotent(tmp_path):
    db_path = tmp_path / "idempotent.db"
    conn = connect_db(db_path)
    try:
        ensure_schema(conn, SCHEMA_PATH)
        first = get_schema_version(conn)
        ensure_schema(conn, SCHEMA_PATH)
        second = get_schema_version(conn)
        assert first == CURRENT_SCHEMA_VERSION
        assert second == CURRENT_SCHEMA_VERSION
    finally:
        conn.close()
