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

If the public URL redirects to `share.streamlit.io/-/auth/app`, the app is still protected by Streamlit platform auth. Change the app sharing/access setting to allow judge access with the direct link.

## 3. Configure Cloud Secrets

Use a production-safe version of `.streamlit/secrets.toml` in the Secrets panel.

```toml
[auth_users.operator_demo]
display_name = "Operator Demo"
role = "operator"
password_hash = "pbkdf2_sha256$..."
totp_secret = "BASE32_TOTP_SECRET"

[auth_users.supervisor_demo]
display_name = "Supervisor Demo"
role = "supervisor"
password_hash = "pbkdf2_sha256$..."
totp_secret = "BASE32_TOTP_SECRET"

[auth_users.auditor_demo]
display_name = "Auditor Demo"
role = "auditor"
password_hash = "pbkdf2_sha256$..."
totp_secret = "BASE32_TOTP_SECRET"

[auth]
redirect_uri = "https://YOUR-APP.streamlit.app/oauth2callback"
cookie_secret = "replace-with-random-cookie-secret"

[auth.google]
client_id = "GOOGLE_CLIENT_ID"
client_secret = "GOOGLE_CLIENT_SECRET"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

[auth.microsoft]
client_id = "MICROSOFT_CLIENT_ID"
client_secret = "MICROSOFT_CLIENT_SECRET"
server_metadata_url = "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration"

[oidc_roles]
supervisors = ["supervisor@example.com"]
auditors = ["auditor@example.com"]

audit_signing_salt = "replace-with-random-long-string"
openai_api_key = "optional-openai-key"
openai_model = "gpt-4o-mini"
openai_embedding_model = "text-embedding-3-small"
```

Never commit real secrets.

## 4. Post-Deploy Verification

1. App boots with no import/runtime errors.
2. Sign-in page appears.
3. Test users can log in with local credentials.
4. Local users with `totp_secret` are prompted for a valid 6-digit verification code.
5. Google and Microsoft sign-in buttons appear when OIDC secrets are configured.
6. OIDC logins create or refresh the matching user record with the correct provider and role.
7. Arabic default mode is active and English toggle works.
8. Sidebar pages render correctly and distinctly:
   - Dashboard
   - Incoming Requests
   - Queues
   - Review
   - Knowledge Assistant
   - Notifications
   - Help
   - Settings
9. Search/filter/pagination controls work on Incoming/Queues/Review.
10. RAG assistant returns cited results from domain knowledge.
11. Saved view create/apply/default/delete works.
12. Notifications show and acknowledge works for supervisor/auditor.
13. Role restrictions are enforced (operator/auditor cannot run unauthorized writes).
14. Audit export works for supervisor/auditor.
15. Settings page shows Auth Status, My Account, Final Release Support Inbox, and Account Administration sections.
16. Settings page shows System Status with OIDC/OpenAI configuration state.
17. Knowledge Assistant shows knowledge sources and RAG evaluation summary.
18. If login-page self-sign-up is enabled, new accounts are inactive by default until supervisor approval when approval mode is on.
19. Export/download actions work:
   - audit log
   - feedback log
   - cases
   - workflow events
   - database backup

## 5. Local vs Cloud Secrets Handling

- Local: `/Users/armankhan/Documents/malomatia-competition-package/.streamlit/secrets.toml`
- Cloud: Streamlit secrets panel
- Shared template: `/Users/armankhan/Documents/malomatia-competition-package/.streamlit/secrets.example.toml`

## 6. Demo Fallback

- Local start: `./run_prototype.sh`
- Local validation evidence: `./run_validation.sh`

## 7. Restore / Recovery Guidance

- Stop the app before replacing backup files.
- Restore `triage.db` from the downloaded database backup if you need full state recovery.
- Restore `audit.log.jsonl` and `feedback.log.jsonl` from exported backups if you need log recovery.
- After restore, restart the app and rerun `./run_validation.sh`.
