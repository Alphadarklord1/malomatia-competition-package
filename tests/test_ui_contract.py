from __future__ import annotations

import ast
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
APP_PATH = BASE_DIR / "gov_triage_dashboard.py"
THEME_PATH = BASE_DIR / "theme.css"


def _source() -> str:
    return APP_PATH.read_text(encoding="utf-8")


def _theme() -> str:
    return THEME_PATH.read_text(encoding="utf-8")


def _module() -> ast.Module:
    return ast.parse(_source())


def _function_names() -> set[str]:
    return {node.name for node in ast.walk(_module()) if isinstance(node, ast.FunctionDef)}


def _string_constants() -> set[str]:
    return {
        node.value
        for node in ast.walk(_module())
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _session_defaults() -> dict[str, object]:
    module = _module()
    for node in module.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "ensure_session_defaults":
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name) or stmt.targets[0].id != "defaults":
                    continue
                value = stmt.value
            elif isinstance(stmt, ast.AnnAssign):
                if not isinstance(stmt.target, ast.Name) or stmt.target.id != "defaults":
                    continue
                value = stmt.value
            else:
                continue
            if not isinstance(value, ast.Dict):
                continue
            return {
                ast.literal_eval(key): ast.literal_eval(item)
                for key, item in zip(value.keys, value.values, strict=True)
                if key is not None
            }
    raise AssertionError("Could not locate ensure_session_defaults defaults dict")


def test_single_language_mode_contract_present() -> None:
    source = _source()
    defaults = _session_defaults()
    assert defaults["ui_language_mode"] == "ar"
    assert defaults["ui_nav"] == "dashboard"
    assert defaults["ui_search_query"] == ""
    assert defaults["ui_page_size"] == 10
    assert defaults["ui_page_index"] == 0
    assert 'options=["ar", "en"]' in source
    assert 'key="ui_language_mode"' in source


def test_navigation_and_direction_contract_present() -> None:
    source = _source()
    strings = _string_constants()
    assert 'direction = "rtl" if arabic_default else "ltr"' in source
    for nav_key in {"dashboard", "incoming", "queues", "review", "assistant", "notifications", "help", "settings"}:
        assert nav_key in source
    for label in {"Dashboard", "Incoming Requests", "Queues", "Review", "Knowledge Assistant", "Notifications", "Help", "Settings"}:
        assert label in strings


def test_mutation_actions_are_session_guarded() -> None:
    source = _source()
    expected_guards = [
        'require_active_action("approve"',
        'require_active_action("override"',
        'require_active_action("select"',
        'require_active_action("assign"',
        'require_active_action("transition"',
        'require_active_action("review_actions"',
        'require_active_action("settings_write"',
    ]
    for guard in expected_guards:
        assert guard in source


def test_search_and_pagination_contract_present() -> None:
    functions = _function_names()
    assert "paginate_cases" in functions
    assert "render_pagination_controls" in functions


def test_rag_assistant_contract_present() -> None:
    source = _source()
    strings = _string_constants()
    assert "from rag_engine import" in source
    assert "Domain RAG Assistant" in strings
    assert "rag_query" in source
    assert "Test AI" in strings
    assert "What It Cannot Do" in strings
    assert "Knowledge Sources" in strings
    assert "RAG Evaluation" in strings


def test_real_auth_directory_contract_present() -> None:
    source = _source()
    strings = _string_constants()
    functions = _function_names()
    for fn_name in {
        "bootstrap_auth_users",
        "record_login_failure",
        "record_login_success",
        "upsert_external_user",
        "create_local_user",
        "reset_local_user_password",
        "set_local_totp_requirement",
    }:
        assert fn_name in source
    for text in {
        "User Directory",
        "Auth Status",
        "Account Administration",
        "Encryption & Security Policies",
        "Verification Code",
        "Verify code",
        "Username and password verified. Enter your verification code to continue.",
        "Single Sign-On",
        "Google and Microsoft sign-in will appear here when OIDC is configured for this deployment.",
        "Google or Microsoft MFA is enforced",
        "Create Account",
        "Create account",
        "Enable two-step verification (TOTP)",
        "Two-Step Verification",
        "Save Two-Step Verification",
        "Generate new MFA secret",
        "New account creation is currently disabled by the administrator.",
        "New local accounts require supervisor approval before first login.",
    }:
        assert text in source
    assert "pending_mfa_user_id" in _session_defaults()
    assert "st.login(provider)" in source
    assert "security_public_signup_enabled" in source
    assert "security_signup_requires_approval" in source
    assert "clear_auth_state" in functions


def test_beta_support_contract_present() -> None:
    source = _source()
    strings = _string_constants()
    for text in {
        "Judge Quick Start",
        "Guide",
        "Overview",
        "Trends",
        "Activity",
        "Results",
        "Knowledge",
        "Evaluation",
        "Trace",
        "Roles & Governance",
        "Open Incoming",
        "Report an Issue or Feedback",
        "Submit Feedback",
        "Beta Readiness",
        "System Status",
        "Export Feedback Log",
        "Release Status",
        "Export Cases",
        "Export Workflow Events",
        "Download Database Backup",
        "Final Release Support Inbox",
        "Use this page in three steps",
    }:
        assert text in source
    assert "feedback.log.jsonl" in source


def test_mobile_responsive_theme_contract_present() -> None:
    theme = _theme()
    assert "@media (max-width: 900px)" in theme
    assert '@media (max-width: 640px)' in theme
    assert '[data-testid="stHorizontalBlock"]' in theme
    assert '[data-testid="column"]' in theme
    assert '[data-testid="stSidebar"]' in theme
    assert '[data-testid="stForm"] [data-testid="stHorizontalBlock"]' in theme
    assert '[data-testid="stDownloadButton"] > button' in theme
    assert ".trace-row" in theme
    assert "overflow-wrap: anywhere" in theme
    assert "word-break: break-word" in theme
