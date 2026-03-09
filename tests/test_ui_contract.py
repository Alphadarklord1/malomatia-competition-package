from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
APP_PATH = BASE_DIR / "gov_triage_dashboard.py"
THEME_PATH = BASE_DIR / "theme.css"


def _source() -> str:
    return APP_PATH.read_text(encoding="utf-8")


def _theme() -> str:
    return THEME_PATH.read_text(encoding="utf-8")


def test_single_language_mode_contract_present() -> None:
    source = _source()
    assert '"ui_language_mode": "ar"' in source
    assert '"ui_search_query": ""' in source
    assert '"ui_page_size": 10' in source
    assert '"ui_page_index": 0' in source
    assert 'options=["ar", "en"]' in source
    assert 'key="ui_language_mode"' in source


def test_navigation_and_direction_contract_present() -> None:
    source = _source()
    assert 'direction = "rtl" if arabic_default else "ltr"' in source
    assert 'if selected_nav == "dashboard":' in source
    assert 'elif selected_nav in {"incoming", "queues"}:' in source
    assert 'elif selected_nav == "review":' in source
    assert 'elif selected_nav == "assistant":' in source
    assert 'elif selected_nav == "notifications":' in source
    assert 'elif selected_nav == "help":' in source
    assert 'elif selected_nav == "settings":' in source


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
    source = _source()
    assert "def paginate_cases(" in source
    assert "def render_pagination_controls(" in source


def test_rag_assistant_contract_present() -> None:
    source = _source()
    assert "from rag_engine import" in source
    assert "Domain RAG Assistant" in source
    assert "rag_query" in source
    assert "Test AI" in source
    assert "What It Cannot Do" in source
    assert "Knowledge Sources" in source
    assert "RAG Evaluation" in source


def test_real_auth_directory_contract_present() -> None:
    source = _source()
    assert "bootstrap_auth_users" in source
    assert "record_login_failure" in source
    assert "record_login_success" in source
    assert "upsert_external_user" in source
    assert "create_local_user" in source
    assert "reset_local_user_password" in source
    assert "set_local_totp_requirement" in source
    assert "User Directory" in source
    assert "Auth Status" in source
    assert "Account Administration" in source
    assert "Encryption & Security Policies" in source
    assert "Verification Code" in source
    assert "Single Sign-On" in source
    assert "st.login(provider)" in source
    assert "Google or Microsoft MFA is enforced" in source


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
