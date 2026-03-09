from __future__ import annotations

import sqlite3
import sys
import uuid
from pathlib import Path

from storage import (
    CURRENT_SCHEMA_VERSION,
    approve_case,
    assign_case,
    connect_db,
    ensure_schema,
    get_schema_version,
    override_case,
    seed_cases_if_empty,
    transition_case_state,
)
from rag_engine import build_index, build_knowledge_manifest, run_rag_evaluation


def fail(message: str) -> int:
    print(f"FAIL: {message}")
    return 1


def main() -> int:
    base = Path(__file__).resolve().parent
    schema = base / "schema.sql"
    data = base / "example_data.json"
    kb = base / "domain_knowledge.json"
    manifest = base / "knowledge_manifest.json"
    rag_eval = base / "rag_eval_set.json"
    db_path = Path(f"/tmp/malomatia_validation_{uuid.uuid4().hex}.db")
    if db_path.exists():
        db_path.unlink()

    conn = connect_db(db_path)
    try:
        ensure_schema(conn, schema)
        if get_schema_version(conn) != CURRENT_SCHEMA_VERSION:
            return fail("schema version mismatch")

        seed_cases_if_empty(conn, data)
        first = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        seed_cases_if_empty(conn, data)
        second = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        if first <= 0 or first != second:
            return fail("seed is not idempotent")

        case_id = conn.execute("SELECT case_id FROM cases LIMIT 1").fetchone()[0]

        ok, msg, _ = transition_case_state(
            conn,
            case_id=case_id,
            to_state="ESCALATED",
            actor_user_id="operator_demo",
            actor_role="operator",
            reason="validation",
        )
        if ok or "not allowed" not in msg:
            return fail("operator escalation guard failed")

        ok, msg, _ = override_case(
            conn,
            case_id=case_id,
            actor_user_id="supervisor_demo",
            actor_role="supervisor",
            reason="validation",
        )
        if not ok:
            return fail(f"supervisor override failed: {msg}")

        ok, msg, _ = assign_case(
            conn,
            case_id=case_id,
            assigned_team="Licensing",
            assigned_user="ops_lic_1",
            actor_user_id="supervisor_demo",
            actor_role="supervisor",
            reason="validation",
        )
        if not ok:
            return fail(f"supervisor reassignment failed: {msg}")

        locker = sqlite3.connect(str(db_path), timeout=0.0, isolation_level=None)
        locker.execute("PRAGMA journal_mode=WAL")
        locker.execute("BEGIN EXCLUSIVE")
        locker.execute("UPDATE cases SET updated_at_utc = updated_at_utc WHERE case_id = ?", (case_id,))
        contender = connect_db(db_path)
        contender.execute("PRAGMA busy_timeout = 50")
        try:
            ok, msg, _ = approve_case(
                contender,
                case_id=case_id,
                actor_user_id="operator_demo",
                actor_role="operator",
                reason="validation_lock",
            )
            if ok or not msg.startswith("DB_BUSY:"):
                return fail("lock contention did not return controlled DB_BUSY result")
        finally:
            locker.execute("ROLLBACK")
            locker.close()
            contender.close()

        app_source = (base / "gov_triage_dashboard.py").read_text(encoding="utf-8")
        required_ui_contract = [
            '"ui_language_mode": "ar"',
            '"ui_search_query": ""',
            '"ui_page_size": 10',
            '"ui_page_index": 0',
            'options=["ar", "en"]',
            'key="ui_language_mode"',
            'direction = "rtl" if arabic_default else "ltr"',
            'if selected_nav == "dashboard":',
            'elif selected_nav in {"incoming", "queues"}:',
            'elif selected_nav == "review":',
            'elif selected_nav == "assistant":',
            'elif selected_nav == "notifications":',
            'elif selected_nav == "help":',
            'elif selected_nav == "settings":',
            "def paginate_cases(",
            "def render_pagination_controls(",
            "Domain RAG Assistant",
            "from rag_engine import",
            "Auth Status",
        ]
        for snippet in required_ui_contract:
            if snippet not in app_source:
                return fail(f"ui/navigation contract missing snippet: {snippet}")

        required_action_guards = [
            'require_active_action("approve"',
            'require_active_action("override"',
            'require_active_action("select"',
            'require_active_action("assign"',
            'require_active_action("transition"',
            'require_active_action("review_actions"',
            'require_active_action("settings_write"',
        ]
        for guard in required_action_guards:
            if guard not in app_source:
                return fail(f"session gate missing on action block: {guard}")

        if not kb.exists():
            return fail("domain_knowledge.json is missing")
        if not manifest.exists():
            return fail("knowledge_manifest.json is missing")
        if not rag_eval.exists():
            return fail("rag_eval_set.json is missing")
        if not (base / "docker-compose.yml").exists():
            return fail("docker-compose.yml is missing")
        if not (base / "run_api.sh").exists():
            return fail("run_api.sh is missing")
        if not (base / "run_webapp.sh").exists():
            return fail("run_webapp.sh is missing")
        if not (base / "api" / "alembic.ini").exists():
            return fail("api/alembic.ini is missing")
        if not (base / "webapp" / "app" / "settings" / "page.tsx").exists():
            return fail("webapp settings page is missing")
        if not (base / "webapp" / "app" / "help" / "page.tsx").exists():
            return fail("webapp help page is missing")
        api_env_example = (base / "api" / ".env.example").read_text(encoding="utf-8")
        for snippet in ("MALOMATIA_OPENAI_API_KEY", "MALOMATIA_CORS_ORIGINS"):
            if snippet not in api_env_example:
                return fail(f"API env example missing snippet: {snippet}")
        kb_index = build_index(str(kb), "en")
        if len(kb_index.get("chunks", [])) <= 0:
            return fail("RAG knowledge index has no chunks")
        manifest_info = build_knowledge_manifest(kb, manifest)
        if not manifest_info.get("documents"):
            return fail("knowledge manifest has no documents")
        eval_summary = run_rag_evaluation(eval_path=rag_eval, data_path=kb, language="en")
        if eval_summary.get("pass_rate", 0.0) < 75.0:
            return fail("RAG evaluation pass rate below threshold")

        secrets_example = (base / ".streamlit" / "secrets.example.toml").read_text(encoding="utf-8")
        for snippet in ("[auth.google]", "[auth.microsoft]", "[oidc_roles]"):
            if snippet not in secrets_example:
                return fail(f"OIDC secrets template missing snippet: {snippet}")

        required_tables = {"saved_views", "notifications"}
        found_tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        missing_tables = sorted(required_tables - found_tables)
        if missing_tables:
            return fail(f"schema contract missing tables: {', '.join(missing_tables)}")

    finally:
        conn.close()

    print("PASS: smoke validation checks completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
