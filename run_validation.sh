#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"

cd "$PROJECT_DIR"

echo "Running smoke validation..."
"$PYTHON_BIN" "$PROJECT_DIR/validation_smoke.py"

echo "Compiling FastAPI product path..."
"$PYTHON_BIN" -m py_compile \
  "$PROJECT_DIR"/api/app/*.py \
  "$PROJECT_DIR"/api/app/routers/*.py

if "$PYTHON_BIN" -c 'import pytest' >/dev/null 2>&1; then
  echo "Running pytest suite..."
  "$PYTHON_BIN" -m pytest -q
else
  echo "pytest not installed in .venv; skipped pytest suite."
  echo "Install with: $PYTHON_BIN -m pip install -r requirements-ui.txt"
fi

if command -v npm >/dev/null 2>&1 && [ -d "$PROJECT_DIR/webapp/node_modules" ]; then
  echo "Building Next.js webapp..."
  (cd "$PROJECT_DIR/webapp" && npm run build)
else
  echo "Skipping Next.js build (npm missing or webapp/node_modules not installed)."
fi
