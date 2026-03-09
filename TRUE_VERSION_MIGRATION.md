# True Version Migration Plan

The Streamlit app remains the competition and demo implementation.

This repo now also contains a production-direction scaffold:
- `api/` -> FastAPI backend
- `webapp/` -> Next.js frontend

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

- production auth and token issuance
- encrypted MFA secret storage
- PostgreSQL migrations
- background jobs / notifications
- real frontend data fetching and mutation flows
- CI/CD and container deployment
