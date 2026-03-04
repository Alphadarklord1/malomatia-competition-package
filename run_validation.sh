#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"

cd "$PROJECT_DIR"

echo "Running smoke validation..."
"$PYTHON_BIN" "$PROJECT_DIR/validation_smoke.py"

if "$PYTHON_BIN" -c 'import pytest' >/dev/null 2>&1; then
  echo "Running pytest suite..."
  "$PYTHON_BIN" -m pytest -q
else
  echo "pytest not installed in .venv; skipped pytest suite."
  echo "Install with: $PYTHON_BIN -m pip install -r requirements-ui.txt"
fi
