# Contributing

## Scope

This repository currently contains two tracks:

- Streamlit prototype in the repo root
- production-direction scaffold in `api/` and `webapp/`

Keep changes scoped to one track unless the change is intentionally shared.

## Getting Started

1. Fork the repository or create a feature branch.
2. Read `README.md` and `TRUE_VERSION_MIGRATION.md`.
3. For the prototype, create local secrets with:

```bash
./setup_demo.sh
```

4. Run validation before opening a pull request:

```bash
./run_validation.sh
```

## Contribution Rules

- Do not commit `.streamlit/secrets.toml`.
- Do not commit real API keys, TOTP secrets, passwords, or cloud credentials.
- Keep UI changes aligned with the Qatar GovTech design direction already established.
- Prefer small, reviewable pull requests.
- Add or update tests when changing workflow, storage, auth, or RAG behavior.
- If changing docs, keep paths relative and user-facing instructions reproducible.

## Suggested Branch Naming

- `feature/...`
- `fix/...`
- `docs/...`
- `refactor/...`

## Pull Request Checklist

- Code is focused and does not revert unrelated work.
- Validation passes locally.
- New behavior is documented if it affects setup, auth, workflow, or deployment.
- Screenshots are included for meaningful UI changes.

## Review Focus

Reviewers should prioritize:

- security regressions
- workflow correctness
- RAG grounding and guardrails
- auth/RBAC integrity
- deployment and setup clarity
