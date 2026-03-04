from __future__ import annotations

from pathlib import Path

from storage import (
    assign_case,
    connect_db,
    ensure_schema,
    get_case,
    list_cases,
    override_case,
    seed_cases_if_empty,
    transition_case_state,
)
from workflow import can_transition

BASE_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BASE_DIR / "schema.sql"
DATA_PATH = BASE_DIR / "example_data.json"


def _seeded_conn(tmp_path):
    db_path = tmp_path / "triage_workflow.db"
    conn = connect_db(db_path)
    ensure_schema(conn, SCHEMA_PATH)
    seed_cases_if_empty(conn, DATA_PATH)
    return conn


def test_operator_cannot_escalate_or_close(tmp_path):
    conn = _seeded_conn(tmp_path)
    try:
        case = list_cases(conn)[0]
        case_id = str(case["case_id"])

        ok_escalate, msg_escalate, _ = transition_case_state(
            conn,
            case_id=case_id,
            to_state="ESCALATED",
            actor_user_id="op1",
            actor_role="operator",
            reason="test",
        )
        assert not ok_escalate
        assert "not allowed" in msg_escalate

        ok_close, msg_close, _ = transition_case_state(
            conn,
            case_id=case_id,
            to_state="CLOSED",
            actor_user_id="op1",
            actor_role="operator",
            reason="test",
        )
        assert not ok_close
        assert "not allowed" in msg_close
        assert not can_transition("operator", "RESOLVED", "CLOSED")
    finally:
        conn.close()


def test_supervisor_escalation_and_reassign_succeeds(tmp_path):
    conn = _seeded_conn(tmp_path)
    try:
        case = list_cases(conn)[0]
        case_id = str(case["case_id"])

        ok_override, msg_override, _ = override_case(
            conn,
            case_id=case_id,
            actor_user_id="sup1",
            actor_role="supervisor",
            reason="needs_human_review",
        )
        assert ok_override, msg_override

        escalated = get_case(conn, case_id)
        assert escalated is not None
        assert escalated["state"] == "ESCALATED"
        assert escalated["assigned_team"] == "Human Review"

        ok_reassign, msg_reassign, _ = assign_case(
            conn,
            case_id=case_id,
            assigned_team="Licensing",
            assigned_user="ops_lic_1",
            actor_user_id="sup1",
            actor_role="supervisor",
            reason="reroute_after_review",
        )
        assert ok_reassign, msg_reassign

        reassigned = get_case(conn, case_id)
        assert reassigned is not None
        assert reassigned["assigned_team"] == "Licensing"
        assert reassigned["assigned_user"] == "ops_lic_1"
    finally:
        conn.close()


def test_human_review_transfer_supervisor_only(tmp_path):
    conn = _seeded_conn(tmp_path)
    try:
        case = list_cases(conn)[0]
        case_id = str(case["case_id"])

        ok_op, msg_op, _ = assign_case(
            conn,
            case_id=case_id,
            assigned_team="Human Review",
            assigned_user=None,
            actor_user_id="op1",
            actor_role="operator",
            reason="try_transfer",
        )
        assert not ok_op
        assert "Only supervisor" in msg_op

        ok_sup, msg_sup, _ = assign_case(
            conn,
            case_id=case_id,
            assigned_team="Human Review",
            assigned_user=None,
            actor_user_id="sup1",
            actor_role="supervisor",
            reason="approved_transfer",
        )
        assert ok_sup, msg_sup
    finally:
        conn.close()
