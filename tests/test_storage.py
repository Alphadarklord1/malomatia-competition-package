from __future__ import annotations

import sqlite3
from pathlib import Path

from storage import (
    ack_notification,
    approve_case,
    connect_db,
    delete_saved_view,
    ensure_schema,
    export_cases_csv_rows,
    list_notifications,
    list_saved_views,
    seed_cases_if_empty,
    upsert_notification,
    upsert_saved_view,
)

BASE_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BASE_DIR / "schema.sql"
DATA_PATH = BASE_DIR / "example_data.json"


def test_connect_db_sets_reliability_pragmas(tmp_path):
    conn = connect_db(tmp_path / "pragmas.db")
    try:
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]

        assert busy_timeout == 10000
        assert journal_mode == "wal"
        assert synchronous in {1, 2}  # NORMAL may return 1 or 2 depending on SQLite build
        assert foreign_keys == 1
    finally:
        conn.close()


def test_seed_is_idempotent(tmp_path):
    conn = connect_db(tmp_path / "seed.db")
    try:
        ensure_schema(conn, SCHEMA_PATH)
        seed_cases_if_empty(conn, DATA_PATH)
        first = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]

        seed_cases_if_empty(conn, DATA_PATH)
        second = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]

        assert first > 0
        assert second == first
    finally:
        conn.close()


def test_lock_contention_returns_controlled_error(tmp_path):
    db_path = tmp_path / "lock.db"

    conn_writer = connect_db(db_path)
    ensure_schema(conn_writer, SCHEMA_PATH)
    seed_cases_if_empty(conn_writer, DATA_PATH)
    case_id = conn_writer.execute("SELECT case_id FROM cases LIMIT 1").fetchone()[0]

    locker = sqlite3.connect(str(db_path), timeout=0.0, isolation_level=None)
    locker.execute("PRAGMA journal_mode=WAL")
    locker.execute("BEGIN EXCLUSIVE")
    locker.execute("UPDATE cases SET updated_at_utc = updated_at_utc WHERE case_id = ?", (case_id,))

    conn_contender = connect_db(db_path)
    conn_contender.execute("PRAGMA busy_timeout = 50")

    try:
        ok, msg, _ = approve_case(
            conn_contender,
            case_id=case_id,
            actor_user_id="op1",
            actor_role="operator",
            reason="contention_test",
        )
        assert not ok
        assert msg.startswith("DB_BUSY:"), msg
    finally:
        locker.execute("ROLLBACK")
        locker.close()
        conn_contender.close()
        conn_writer.close()


def test_saved_views_are_user_scoped_and_defaultable(tmp_path):
    conn = connect_db(tmp_path / "saved_views.db")
    try:
        ensure_schema(conn, SCHEMA_PATH)
        ok, msg = upsert_saved_view(
            conn,
            user_id="operator_demo",
            name="My Licensing",
            filters={"department": "Licensing", "queue_scope": "my_queue"},
            is_default=True,
        )
        assert ok, msg

        views = list_saved_views(conn, "operator_demo")
        assert len(views) == 1
        assert views[0]["name"] == "My Licensing"
        assert int(views[0]["is_default"]) == 1

        # Other user should not see this view.
        assert list_saved_views(conn, "other_user") == []

        ok, msg = delete_saved_view(conn, "operator_demo", str(views[0]["view_id"]))
        assert ok, msg
        assert list_saved_views(conn, "operator_demo") == []
    finally:
        conn.close()


def test_notifications_ack_and_listing(tmp_path):
    conn = connect_db(tmp_path / "notifications.db")
    try:
        ensure_schema(conn, SCHEMA_PATH)
        ok, msg = upsert_notification(
            conn,
            case_id="case-1",
            severity="high",
            notif_type="sla_breached",
            message_ar="تم تجاوز SLA",
            message_en="SLA breached",
        )
        assert ok, msg

        open_notifications = list_notifications(conn, include_acked=False)
        assert len(open_notifications) == 1
        notification_id = str(open_notifications[0]["notification_id"])

        ok, msg = ack_notification(conn, notification_id, "auditor_demo")
        assert ok, msg

        # Acked item should not appear in open list, but must remain in full list.
        assert list_notifications(conn, include_acked=False) == []
        all_notifications = list_notifications(conn, include_acked=True)
        assert len(all_notifications) == 1
        assert all_notifications[0]["ack_by_user"] == "auditor_demo"
        assert all_notifications[0]["ack_at_utc"] is not None
    finally:
        conn.close()


def test_export_cases_csv_rows_returns_labeled_rows(tmp_path):
    conn = connect_db(tmp_path / "csv_rows.db")
    try:
        ensure_schema(conn, SCHEMA_PATH)
        seed_cases_if_empty(conn, DATA_PATH)
        rows = [dict(r) for r in conn.execute("SELECT * FROM cases LIMIT 2").fetchall()]
        csv_rows = export_cases_csv_rows(rows, arabic_default=False)
        assert len(csv_rows) == 2
        assert "Case ID" in csv_rows[0]
        assert "Request" in csv_rows[0]
        assert "SLA" in csv_rows[0]
    finally:
        conn.close()
