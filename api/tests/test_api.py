from __future__ import annotations

from fastapi.testclient import TestClient


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login_and_get_token(client: TestClient, username: str, password: str) -> str:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def first_case_id(client: TestClient, token: str) -> str:
    response = client.get("/cases?page=1&page_size=1", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items
    return items[0]["case_id"]


def test_login_success_and_me(client: TestClient):
    token = login_and_get_token(client, "operator_demo", "Operator@123")
    profile = client.get("/auth/me", headers=auth_headers(token))
    assert profile.status_code == 200, profile.text
    assert profile.json()["role"] == "operator"
    assert profile.json()["auth_provider"] == "local"
    assert profile.json()["status"] == "active"


def test_login_failure(client: TestClient):
    response = client.post("/auth/login", json={"username": "operator_demo", "password": "bad-password"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_register_pending_user_and_supervisor_approval(client: TestClient):
    register = client.post(
        "/auth/register",
        json={"username": "new_operator", "display_name": "New Operator", "password": "NewPassword@123", "enable_mfa": False},
    )
    assert register.status_code == 200, register.text
    assert register.json()["status"] == "pending"

    pending_login = client.post("/auth/login", json={"username": "new_operator", "password": "NewPassword@123"})
    assert pending_login.status_code == 403

    supervisor_token = login_and_get_token(client, "supervisor_demo", "Supervisor@123")
    approve = client.patch("/users/new_operator", json={"status": "active"}, headers=auth_headers(supervisor_token))
    assert approve.status_code == 200, approve.text

    active_login = client.post("/auth/login", json={"username": "new_operator", "password": "NewPassword@123"})
    assert active_login.status_code == 200, active_login.text
    assert active_login.json()["access_token"]


def test_mfa_login_flow(client: TestClient):
    from app.security import _hotp, generate_totp_secret
    from app.db import get_engine
    from app.models import User
    from sqlmodel import Session

    secret = generate_totp_secret()
    with Session(get_engine()) as session:
        user = session.get(User, "operator_demo")
        assert user is not None
        user.mfa_enabled = True
        user.mfa_secret = secret
        session.add(user)
        session.commit()

    first_step = client.post("/auth/login", json={"username": "operator_demo", "password": "Operator@123"})
    assert first_step.status_code == 200, first_step.text
    assert first_step.json()["mfa_required"] is True
    pending_token = first_step.json()["pending_token"]
    code = _hotp(secret, int(__import__("time").time() // 30))
    verify = client.post("/auth/mfa/verify", json={"pending_token": pending_token, "code": code})
    assert verify.status_code == 200, verify.text
    assert verify.json()["access_token"]


def test_login_lockout_after_repeated_failures(client: TestClient):
    for _ in range(5):
        client.post("/auth/login", json={"username": "operator_demo", "password": "bad-password"})
    locked = client.post("/auth/login", json={"username": "operator_demo", "password": "Operator@123"})
    assert locked.status_code == 423


def test_protected_routes_reject_missing_token(client: TestClient):
    response = client.get("/dashboard/summary")
    assert response.status_code == 401


def test_dashboard_summary_returns_seeded_counts(client: TestClient):
    token = login_and_get_token(client, "supervisor_demo", "Supervisor@123")
    response = client.get("/dashboard/summary", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["open_cases"] > 0
    assert "by_department" in payload


def test_case_filters_and_pagination_are_deterministic(client: TestClient):
    token = login_and_get_token(client, "operator_demo", "Operator@123")
    first = client.get(
        "/cases?department=Immigration&search=residency&page=1&page_size=2",
        headers=auth_headers(token),
    )
    second = client.get(
        "/cases?department=Immigration&search=residency&page=1&page_size=2",
        headers=auth_headers(token),
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json() == second.json()


def test_operator_can_assign_case(client: TestClient):
    token = login_and_get_token(client, "operator_demo", "Operator@123")
    case_id = first_case_id(client, token)
    assign = client.post(
        f"/cases/{case_id}/assign",
        json={"assigned_team": "Immigration", "assigned_user": "ops_imm_1", "reason": "queue routing"},
        headers=auth_headers(token),
    )
    assert assign.status_code == 200, assign.text
    payload = assign.json()["case"]
    assert payload["assigned_team"] == "Immigration"
    assert payload["assigned_user"] == "ops_imm_1"
    assert payload["state"] in {"ASSIGNED", "TRIAGED"}


def test_supervisor_can_transition_case(client: TestClient):
    token = login_and_get_token(client, "supervisor_demo", "Supervisor@123")
    case_id = first_case_id(client, token)
    assign = client.post(
        f"/cases/{case_id}/assign",
        json={"assigned_team": "Immigration", "assigned_user": "ops_imm_2", "reason": "assign first"},
        headers=auth_headers(token),
    )
    assert assign.status_code == 200, assign.text
    transition = client.post(
        f"/cases/{case_id}/transition",
        json={"to_state": "IN_PROGRESS", "reason": "work started"},
        headers=auth_headers(token),
    )
    assert transition.status_code == 200, transition.text
    assert transition.json()["case"]["state"] == "IN_PROGRESS"


def test_operator_can_approve_but_cannot_override(client: TestClient):
    token = login_and_get_token(client, "operator_demo", "Operator@123")
    case_id = first_case_id(client, token)

    approve = client.post(
        f"/cases/{case_id}/approve",
        json={"reason": "triage confirmed"},
        headers=auth_headers(token),
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["case"]["state"] in {"NEW", "TRIAGED"}

    override = client.post(
        f"/cases/{case_id}/override",
        json={"reason": "not allowed for operator"},
        headers=auth_headers(token),
    )
    assert override.status_code == 403


def test_supervisor_can_override_and_timeline_updates(client: TestClient):
    token = login_and_get_token(client, "supervisor_demo", "Supervisor@123")
    case_id = first_case_id(client, token)
    override = client.post(
        f"/cases/{case_id}/override",
        json={"reason": "send to human review"},
        headers=auth_headers(token),
    )
    assert override.status_code == 200, override.text
    assert override.json()["case"]["state"] == "ESCALATED"

    timeline = client.get(f"/cases/{case_id}/timeline", headers=auth_headers(token))
    assert timeline.status_code == 200, timeline.text
    events = timeline.json()["events"]
    assert any(event["event_type"] == "OVERRIDE" for event in events)


def test_review_summary_and_notifications_flow(client: TestClient):
    token = login_and_get_token(client, "supervisor_demo", "Supervisor@123")
    case_id = first_case_id(client, token)
    override = client.post(
        f"/cases/{case_id}/override",
        json={"reason": "send to human review"},
        headers=auth_headers(token),
    )
    assert override.status_code == 200, override.text

    review = client.get("/review/summary", headers=auth_headers(token))
    assert review.status_code == 200, review.text
    review_payload = review.json()
    assert review_payload["escalated"]
    assert review_payload["recently_overridden"]

    notifications = client.get("/notifications", headers=auth_headers(token))
    assert notifications.status_code == 200, notifications.text
    items = notifications.json()["items"]
    assert items
    notification_id = items[0]["notification_id"]

    ack = client.post(f"/notifications/{notification_id}/ack", headers=auth_headers(token))
    assert ack.status_code == 200, ack.text

    include_acked = client.get("/notifications?include_acked=true", headers=auth_headers(token))
    assert include_acked.status_code == 200, include_acked.text
    acked_items = include_acked.json()["items"]
    assert any(item["notification_id"] == notification_id and item["ack_by_user"] == "supervisor_demo" for item in acked_items)


def test_export_routes(client: TestClient):
    token = login_and_get_token(client, "auditor_demo", "Auditor@123")
    audit_export = client.get("/audit/export", headers=auth_headers(token))
    assert audit_export.status_code == 200, audit_export.text
    assert audit_export.text.strip() != ""

    cases_export = client.get("/cases/export.csv", headers=auth_headers(token))
    assert cases_export.status_code == 200, cases_export.text
    assert "case_id,request_text" in cases_export.text


def test_supervisor_can_list_users(client: TestClient):
    token = login_and_get_token(client, "supervisor_demo", "Supervisor@123")
    response = client.get("/users", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert any(item["user_id"] == "operator_demo" for item in items)


def test_rag_route_uses_local_fallback_without_openai_key(client: TestClient):
    token = login_and_get_token(client, "operator_demo", "Operator@123")
    response = client.post(
        "/rag/query",
        json={"query": "What is the SLA for urgent cases?", "language": "en", "top_k": 3},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["hits"]
    assert payload["used_llm"] is False


def test_rag_route_passes_configured_openai_key(client: TestClient, monkeypatch):
    from app.routers import rag as rag_router_module
    from app.config import reset_settings_cache

    monkeypatch.setenv("MALOMATIA_OPENAI_API_KEY", "test-openai-key")
    reset_settings_cache()

    captured: dict[str, object] = {}

    def fake_answer_question(**kwargs):
        captured.update(kwargs)
        return {
            "answer": "Grounded answer",
            "hits": [
                {
                    "rank": 1,
                    "doc_id": "DOC-SLA-01",
                    "chunk_id": "DOC-SLA-01::1",
                    "title": "SLA policy",
                    "department": "Operations",
                    "policy_rule": "PR-SLA-04",
                    "text": "Urgent SLA target is 4 hours.",
                    "base_score": 0.91,
                    "rerank_score": 1.15,
                    "keyword_hits": ["sla", "urgent"],
                    "reasons": ["semantic match"],
                }
            ],
            "used_llm": True,
            "insufficient_evidence": False,
            "policy_blocked": False,
            "llm_error": None,
        }

    monkeypatch.setattr(rag_router_module, "answer_question", fake_answer_question)
    token = login_and_get_token(client, "supervisor_demo", "Supervisor@123")
    response = client.post(
        "/rag/query",
        json={"query": "What is the SLA for urgent cases?", "language": "en", "top_k": 3},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    assert captured["openai_api_key"] == "test-openai-key"
    assert response.json()["used_llm"] is True
