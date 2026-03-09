#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/api"
../.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
