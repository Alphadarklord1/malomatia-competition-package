from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = PROJECT_ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    database_path = tmp_path / "api_test.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("MALOMATIA_DATABASE_URL", database_url)
    monkeypatch.setenv("MALOMATIA_REDIS_URL", "redis://localhost:6399/0")
    monkeypatch.setenv("MALOMATIA_SEED_DEMO_DATA", "true")
    monkeypatch.setenv("MALOMATIA_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    monkeypatch.delenv("MALOMATIA_OPENAI_API_KEY", raising=False)

    from fastapi.testclient import TestClient
    from sqlmodel import Session

    from app.config import reset_settings_cache
    from app.db import get_engine, init_db, reset_engine
    from app.main import create_app
    from app.rate_limit import rate_limiter
    from app.seed import reset_demo_data

    reset_settings_cache()
    reset_engine(database_url)
    init_db()
    with Session(get_engine()) as session:
        reset_demo_data(session)
    rate_limiter.reset()

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    rate_limiter.reset()
    reset_settings_cache()
