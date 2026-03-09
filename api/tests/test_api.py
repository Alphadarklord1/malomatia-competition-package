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


def test_login_failure(client: TestClient):
    response = client.post("/auth/login", json={"username": "operator_demo", "password": "bad-password"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


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
        "/cases?department=Immigration&page=1&page_size=2",
        headers=auth_headers(token),
    )
    second = client.get(
        "/cases?department=Immigration&page=1&page_size=2",
        headers=auth_headers(token),
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json() == second.json()


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
