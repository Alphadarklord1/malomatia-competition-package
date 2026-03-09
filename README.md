# Malomatia Gov-Service Triage Prototype

Internal pilot prototype for Qatar public-service AI triage operations with:

- authentication + RBAC + session safety
- persisted user directory with hashed passwords, lockout policy, local TOTP MFA, optional OIDC SSO, and supervisor account management
- privacy masking + audit chain logging
- SQLite persistence + schema migrations
- workflow lifecycle + SLA monitoring
- manifest-backed RAG knowledge management + benchmark evaluation
- Arabic-first single-language mode toggle (`ar`/`en`)
- final release controls: public sign-up policy, approval-based self-sign-up, support inbox, release status, and backup/export actions

## Quick Start

```bash
cd "/path/to/malomatia-competition-package"
./setup_demo.sh   # creates secrets.toml with working demo credentials
./run_prototype.sh
```

App URL: `http://localhost:8501`

`setup_demo.sh` copies `secrets.example.toml` to `secrets.toml` with pre-generated demo password hashes. `run_prototype.sh` always uses the project virtualenv (`.venv`) and pinned Streamlit runtime (`1.54.0`).

## Sign-In

Credentials are loaded from:

- `.streamlit/secrets.toml`

Local demo users:

- `operator_demo` / `Operator@123`
- `supervisor_demo` / `Supervisor@123`
- `auditor_demo` / `Auditor@123`

If login fails, verify `auth_users` exists in secrets file with valid password hashes.
Template:

- `.streamlit/secrets.example.toml`

Optional auth upgrades:

- Local 2-step verification: add `totp_secret` per user in `auth_users`
- Google / Microsoft SSO: configure `[auth]`, `[auth.google]`, `[auth.microsoft]`
- OIDC role mapping: configure `[oidc_roles]` lists for supervisors and auditors
- Supervisors can create local users, reset passwords, set roles/status, and manage local TOTP from the Settings page
- Final release default: login-page self-sign-up is disabled unless a supervisor enables it in Settings
- If self-sign-up is enabled, new accounts require supervisor approval by default before first login

For Streamlit OIDC login, install/runtime-pin `Authlib==1.6.0`.

## Navigation

- `Dashboard`: KPI/status/operations health snapshot
- `Incoming Requests`: triage cards + per-case actions + explanation panel
- `Queues`: table-first operations view + filters + CSV export + bulk actions
- `Review`: escalations, low-confidence, and override follow-up
- `Knowledge Assistant`: domain RAG assistant (chunking, vector search, reranking, cited answers)
- `Notifications`: SLA/quality alerts with acknowledge flow
- `Help`: role matrix, workflow quick guide, privacy/audit notes
- `Settings`: visual controls + security/privacy controls + auth status + support inbox + export/backup actions
- Mobile support: responsive stacking for cards, controls, and panels on narrow screens

## Session 3 RAG Deliverable

- Domain data source: `domain_knowledge.json`
- Knowledge manifest: `knowledge_manifest.json`
- Evaluation set: `rag_eval_set.json`
- Retrieval engine: `rag_engine.py`
- Implemented pipeline:
  - chunking (token-window with overlap)
  - TF-IDF vectorization per chunk
  - top-k retrieval by cosine similarity
  - rule-aware reranking (keyword/policy/department boosts)
  - grounded response with DOC/CHUNK citations
  - manifest-backed knowledge source inventory
  - benchmark evaluation with pass-rate summary
  - in-app before/after comparison (`Without Retrieval` vs `With RAG`)
- Optional LLM synthesis:
  - add `openai_api_key` to secrets for generated grounded answers
  - optional `openai_model` and `openai_embedding_model`
  - can also paste API key in Assistant page (`AI Runtime Settings`) for session-only testing
  - runtime UI keys are session-only and are not persisted as permanent app settings
  - use `Test AI` in the Assistant page to verify embeddings + answer model connectivity
  - without key, assistant uses deterministic grounded fallback
  - strict guardrails block action execution, PII reveal, secret extraction, and out-of-policy answers

## Search, Filters, and Pagination

- Global search supports case ID and request text.
- Unified filters are shared across Incoming/Queues/Review:
  - department
  - state
  - urgency
  - SLA status
  - assigned user
  - queue scope
- Pagination controls:
  - page size defaults to `10`
  - page size options: `10`, `25`, `50`
  - deterministic next/previous navigation
- Saved views are user-scoped and can be set as default.

## Local vs Cloud Secrets

- Local run reads `.streamlit/secrets.toml`
- Streamlit Community uses the cloud secrets panel
- Do not commit secrets; `.streamlit/secrets.toml` is ignored in `.gitignore`

## Real Product MVP

This repo now contains a separate real-product path so the Streamlit prototype can remain stable:

- `api/` -> FastAPI backend MVP
- `webapp/` -> Next.js frontend MVP
- `docker-compose.yml` -> local Postgres + Redis runtime
- `TRUE_VERSION_MIGRATION.md` -> migration phases and architecture notes

These folders are intentionally separate from the Streamlit app. They provide the first working non-Streamlit slice of the platform, not full parity with the prototype.

Run the real product MVP locally:

```bash
docker compose up -d postgres redis
./run_api.sh
./run_webapp.sh
```

Product URLs:

- API: `http://localhost:8000`
- Web app: `http://localhost:3000`

Core MVP coverage:

- local JWT login, pending approval signup, and MFA verification (`/auth/login`, `/auth/register`, `/auth/mfa/verify`, `/auth/me`)
- KPI summary (`/dashboard/summary`)
- filterable queue list (`/cases`)
- incoming triage view with approve/assign/override
- case detail + approve/override actions (`/cases/{case_id}`)
- generic state transition endpoint (`/cases/{case_id}/transition`)
- CSV case export and audit export (`/cases/export.csv`, `/audit/export`)
- review summary (`/review/summary`)
- notifications and acknowledge flow (`/notifications`)
- supervisor user administration (`/users`)
- webapp Settings and Help pages
- English/Arabic language toggle with RTL mode in the webapp
- Alembic migration scaffold for the Postgres path (`api/alembic`)
- workflow + audit timeline (`/cases/{case_id}/timeline`)
- grounded RAG endpoint (`/rag/query`)

## Open Source

- License: `LICENSE`
- Contribution guide: `CONTRIBUTING.md`
- Collaboration standards: `CODE_OF_CONDUCT.md`

## Validation and Tests

Run smoke + tests:

```bash
cd "/path/to/malomatia-competition-package"
./run_validation.sh
```

Run tests directly:

```bash
cd "/path/to/malomatia-competition-package"
./.venv/bin/python -m pytest -q
```

Coverage includes:

- RBAC transition enforcement
- schema migration safety and idempotence
- SQLite lock contention handling
- saved views + notifications storage behavior
- RAG retrieval/indexing behavior
- UI contract checks for single-language mode, navigation, pagination, and guarded mutations
- final release controls for approval-based sign-up, support inbox, release status, and export actions
- FastAPI real-product API login, queue, workflow, and RAG route behavior
- FastAPI signup, MFA, user-management, export, and transition behavior

## Migration Verification

```bash
cd "/path/to/malomatia-competition-package"
./.venv/bin/python - <<'PY'
from pathlib import Path
from storage import connect_db, ensure_schema, get_schema_version
base = Path('.').resolve()
conn = connect_db(base / 'triage.db')
ensure_schema(conn, base / 'schema.sql')
print('schema_version=', get_schema_version(conn))
conn.close()
PY
```

Expected: `schema_version= 7`

## DB Lock Troubleshooting

If an action returns `DB_BUSY`:

1. Retry after a moment (busy timeout enabled).
2. Avoid concurrent heavy writers.
3. Check for stuck Streamlit processes:

```bash
ps aux | rg streamlit
```

4. Restart app with `./run_prototype.sh`.

## Operational Notes

- Storage: local SQLite (`triage.db`)
- Audit log: `audit.log.jsonl` (append-only, hash-chained)
- Audit archive: `audit.archive.jsonl`
- Support log: `feedback.log.jsonl`
- Mock seed source: `example_data.json`
- Scope: local pilot only, no external backend

## Restore Guidance

- Restore database: replace `triage.db` with a known-good backup while the app is stopped
- Restore audit log: replace `audit.log.jsonl` and keep `audit.archive.jsonl` alongside it if you are preserving old events
- Restore support log: replace `feedback.log.jsonl`
- Official local backup path:
  - `Export Audit Log`
  - `Export Feedback Log`
  - `Export Cases`
  - `Export Workflow Events`
  - `Download Database Backup`

## Pilot Readiness Checklist

1. Startup works with one command.
2. Login works and invalid credentials are rejected.
3. Session timeout/logout blocks stale mutations.
4. Workflow actions respect RBAC and are audited.
5. Search/filter/pagination behavior is deterministic.
6. Notifications and saved views work per role/user rules.
7. Existing `triage.db` migrates to schema v7 safely.
8. Local MFA and optional Google/Microsoft SSO are configured correctly for the target environment.
9. RAG manifest and evaluation set are visible and passing.
10. `./run_validation.sh` passes.

## Final Release Notes

- Version: `1.0.0`
- Release stage: `final`
- Supported login methods:
  - local username/password
  - local username/password + TOTP
  - Google OIDC when configured
  - Microsoft OIDC when configured
- Required secrets for hardened deployment:
  - local user password hashes
  - `audit_signing_salt`
  - `cookie_secret`
  - OIDC client/secret pairs if using Google/Microsoft
  - optional OpenAI key/model settings
- RAG behavior:
  - without OpenAI: deterministic grounded retrieval fallback
  - with OpenAI: grounded answer generation using configured key or session-only runtime key

## Real Product Notes

- Backend defaults read from `api/.env`
- Frontend defaults read from `webapp/.env.local`
- Demo API users:
  - `operator_demo` / `Operator@123`
  - `supervisor_demo` / `Supervisor@123`
  - `auditor_demo` / `Auditor@123`
- `run_validation.sh` now validates:
  - root smoke checks
  - Python test suite
  - FastAPI module compilation
  - Next.js production build when `webapp/node_modules/` is installed

## Shareable Deployment

See:

- `DEPLOYMENT.md`
