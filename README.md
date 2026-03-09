# Malomatia Gov-Service Triage Prototype

Internal pilot prototype for Qatar public-service AI triage operations with:

- authentication + RBAC + session safety
- privacy masking + audit chain logging
- SQLite persistence + schema migrations
- workflow lifecycle + SLA monitoring
- Arabic-first single-language mode toggle (`ar`/`en`)

## Deterministic Startup

```bash
cd "/Users/armankhan/Documents/malomatia-competition-package"
./run_prototype.sh
```

App URL: `http://localhost:8501`

`run_prototype.sh` always uses the project virtualenv (`.venv`) and pinned Streamlit runtime (`1.54.0`).

## Sign-In

Credentials are loaded from:

- `/Users/armankhan/Documents/malomatia-competition-package/.streamlit/secrets.toml`

Local demo users:

- `operator_demo` / `Operator@123`
- `supervisor_demo` / `Supervisor@123`
- `auditor_demo` / `Auditor@123`

If login fails, verify `auth_users` exists in secrets file with valid password hashes.
Template:

- `/Users/armankhan/Documents/malomatia-competition-package/.streamlit/secrets.example.toml`

## Navigation

- `Dashboard`: KPI/status/operations health snapshot
- `Incoming Requests`: triage cards + per-case actions + explanation panel
- `Queues`: table-first operations view + filters + CSV export + bulk actions
- `Review`: escalations, low-confidence, and override follow-up
- `Knowledge Assistant`: domain RAG assistant (chunking, vector search, reranking, cited answers)
- `Notifications`: SLA/quality alerts with acknowledge flow
- `Help`: role matrix, workflow quick guide, privacy/audit notes
- `Settings`: visual controls + security/privacy controls + audit export
- Mobile support: responsive stacking for cards, controls, and panels on narrow screens

## Session 3 RAG Deliverable

- Domain data source: `/Users/armankhan/Documents/malomatia-competition-package/domain_knowledge.json`
- Retrieval engine: `/Users/armankhan/Documents/malomatia-competition-package/rag_engine.py`
- Implemented pipeline:
  - chunking (token-window with overlap)
  - TF-IDF vectorization per chunk
  - top-k retrieval by cosine similarity
  - rule-aware reranking (keyword/policy/department boosts)
  - grounded response with DOC/CHUNK citations
  - in-app before/after comparison (`Without Retrieval` vs `With RAG`)
- Optional LLM synthesis:
  - add `openai_api_key` to secrets for generated grounded answers
  - optional `openai_model` and `openai_embedding_model`
  - can also paste API key in Assistant page (`AI Runtime Settings`) for session-only testing
  - without key, assistant uses deterministic grounded fallback

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

- Local run reads `/Users/armankhan/Documents/malomatia-competition-package/.streamlit/secrets.toml`
- Streamlit Community uses the cloud secrets panel
- Do not commit secrets; `.streamlit/secrets.toml` is ignored in `.gitignore`

## Validation and Tests

Run smoke + tests:

```bash
cd "/Users/armankhan/Documents/malomatia-competition-package"
./run_validation.sh
```

Run tests directly:

```bash
cd "/Users/armankhan/Documents/malomatia-competition-package"
./.venv/bin/python -m pytest -q
```

Coverage includes:

- RBAC transition enforcement
- schema migration safety and idempotence
- SQLite lock contention handling
- saved views + notifications storage behavior
- RAG retrieval/indexing behavior
- UI contract checks for single-language mode, navigation, pagination, and guarded mutations

## Migration Verification

```bash
cd "/Users/armankhan/Documents/malomatia-competition-package"
./.venv/bin/python - <<'PY'
from pathlib import Path
from storage import connect_db, ensure_schema, get_schema_version
base = Path('/Users/armankhan/Documents/malomatia-competition-package')
conn = connect_db(base / 'triage.db')
ensure_schema(conn, base / 'schema.sql')
print('schema_version=', get_schema_version(conn))
conn.close()
PY
```

Expected: `schema_version= 4`

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
- Mock seed source: `example_data.json`
- Scope: local pilot only, no external backend

## Pilot Readiness Checklist

1. Startup works with one command.
2. Login works and invalid credentials are rejected.
3. Session timeout/logout blocks stale mutations.
4. Workflow actions respect RBAC and are audited.
5. Search/filter/pagination behavior is deterministic.
6. Notifications and saved views work per role/user rules.
7. Existing `triage.db` migrates to schema v4 safely.
8. `./run_validation.sh` passes.

## Shareable Deployment

See:

- `/Users/armankhan/Documents/malomatia-competition-package/DEPLOYMENT.md`
