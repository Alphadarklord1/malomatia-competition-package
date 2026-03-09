# Production API Scaffold

This folder is the production-direction replacement for the Streamlit backend.

Target stack:
- FastAPI
- PostgreSQL
- Redis
- OIDC / enterprise auth
- service-side audit logging

Current state:
- runnable FastAPI scaffold
- typed case/auth/RAG schemas
- placeholder auth route
- example case endpoints
- RAG endpoint reusing the existing retrieval engine

Run locally after installing dependencies:

```bash
cd api
python -m uvicorn app.main:app --reload --port 8000
```

This is intentionally separate from the Streamlit prototype so migration can happen incrementally.
