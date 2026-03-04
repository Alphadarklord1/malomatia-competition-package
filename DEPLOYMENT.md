# Streamlit Community Deployment Runbook

This runbook packages the prototype for a shareable judge link while preserving local parity.

## 1. Prepare Repository

1. Push project files to GitHub.
2. Keep `.streamlit/secrets.toml` out of git.
3. Ensure repo root includes:
   - `gov_triage_dashboard.py`
   - `requirements.txt`
   - `requirements-ui.txt`
   - `run_validation.sh`
   - `.streamlit/secrets.example.toml`

## 2. Create Streamlit Community App

1. Open Streamlit Community Cloud.
2. Create **New app**.
3. Select repo and branch.
4. Set entrypoint file:
   - `gov_triage_dashboard.py`
5. Deploy.

## 3. Configure Cloud Secrets

Use a production-safe version of `.streamlit/secrets.toml` in the Secrets panel.

```toml
[auth_users.operator_demo]
role = "operator"
password_hash = "pbkdf2_sha256$..."

[auth_users.supervisor_demo]
role = "supervisor"
password_hash = "pbkdf2_sha256$..."

[auth_users.auditor_demo]
role = "auditor"
password_hash = "pbkdf2_sha256$..."

audit_signing_salt = "replace-with-random-long-string"
```

Never commit real secrets.

## 4. Post-Deploy Verification

1. App boots with no import/runtime errors.
2. Sign-in page appears.
3. Test users can log in.
4. Arabic default mode is active and English toggle works.
5. Sidebar pages render correctly and distinctly:
   - Dashboard
   - Incoming Requests
   - Queues
   - Review
   - Knowledge Assistant
   - Notifications
   - Help
   - Settings
6. Search/filter/pagination controls work on Incoming/Queues/Review.
7. RAG assistant returns cited results from domain knowledge.
8. Saved view create/apply/default/delete works.
9. Notifications show and acknowledge works for supervisor/auditor.
10. Role restrictions are enforced (operator/auditor cannot run unauthorized writes).
11. Audit export works for supervisor/auditor.

## 5. Local vs Cloud Secrets Handling

- Local: `/Users/armankhan/Documents/malomatia-competition-package/.streamlit/secrets.toml`
- Cloud: Streamlit secrets panel
- Shared template: `/Users/armankhan/Documents/malomatia-competition-package/.streamlit/secrets.example.toml`

## 6. Demo Fallback

- Local start: `./run_prototype.sh`
- Local validation evidence: `./run_validation.sh`
