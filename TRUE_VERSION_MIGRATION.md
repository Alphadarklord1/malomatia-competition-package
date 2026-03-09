# True Version Migration Plan

The Streamlit app remains the competition and demo implementation.

This repo now also contains a working core-ops MVP for the true-version path:
- `api/` -> FastAPI backend MVP
- `webapp/` -> Next.js frontend MVP

## Why this split exists

The current Streamlit app is strong enough for prototype, judging, and pilot-style demonstrations, but it is not the correct runtime for:
- horizontal scale
- PostgreSQL-backed concurrency
- real reverse proxy / HTTPS deployment
- centralized auth and audit controls
- team maintainability

## Migration phases

1. Move auth, workflow, audit, and RAG orchestration into `api/`
2. Replace Streamlit views with React pages in `webapp/`
3. Move persistence from SQLite to PostgreSQL
4. Move session/rate-limit state to Redis
5. Replace file audit logging with database + centralized logging sink
6. Put the app behind Nginx / managed ingress with TLS and OIDC

## What is already reusable

- `workflow.py`
- `kpi.py`
- `rag_engine.py`
- `domain_knowledge.json`
- `knowledge_manifest.json`
- `rag_eval_set.json`

## What still needs implementation in the true version

- OIDC / enterprise SSO
- encrypted MFA secret storage
- Alembic-style PostgreSQL migrations
- background jobs / notifications
- settings/help/notifications/account admin pages in the webapp
- HTTP-only cookie auth if you move away from sessionStorage
- CI/CD and container deployment

## What already works in the true-version MVP

- local JWT auth
- seeded users and cases
- dashboard KPI summary
- queue filters and pagination
- case detail and timeline
- approve / override mutations with role checks
- RAG query endpoint with OpenAI-key support and local fallback
- Next.js frontend wired to the API
