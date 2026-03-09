# Production API MVP

This folder is the working backend for the non-Streamlit product path.

Implemented:
- local username/password login with JWT
- `/auth/me`
- dashboard summary
- filterable case list with pagination
- assignment route
- case detail
- approve / override workflow actions
- review summary
- notifications + ACK flow
- workflow + audit timeline
- grounded RAG query endpoint
- Postgres-first runtime with seeded demo users and cases
- Redis-backed RAG rate limiting with in-process fallback

## Run

```bash
docker compose up -d postgres redis
cd api
cp .env.example .env
../.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

## Environment

Key settings in `.env`:
- `MALOMATIA_DATABASE_URL`
- `MALOMATIA_REDIS_URL`
- `MALOMATIA_JWT_SECRET_KEY`
- `MALOMATIA_CORS_ORIGINS`
- `MALOMATIA_OPENAI_API_KEY`
- `MALOMATIA_OPENAI_MODEL`
- `MALOMATIA_OPENAI_EMBEDDING_MODEL`

## Demo Accounts

- `operator_demo` / `Operator@123`
- `supervisor_demo` / `Supervisor@123`
- `auditor_demo` / `Auditor@123`

## Main Routes

- `POST /auth/login`
- `GET /auth/me`
- `GET /dashboard/summary`
- `GET /cases`
- `GET /cases/{case_id}`
- `POST /cases/{case_id}/assign`
- `POST /cases/{case_id}/approve`
- `POST /cases/{case_id}/override`
- `GET /cases/{case_id}/timeline`
- `GET /review/summary`
- `GET /notifications`
- `POST /notifications/{notification_id}/ack`
- `POST /rag/query`

## Validation

Run API tests from the repo root:

```bash
../.venv/bin/python -m pytest -q api/tests
```
