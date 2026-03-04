#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"

cd "$PROJECT_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Creating virtual environment at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import streamlit
raise SystemExit(0 if streamlit.__version__ == "1.54.0" else 1)
PY
then
  echo "Installing pinned Streamlit runtime dependency (1.54.0)..."
  "$PIP_BIN" install "streamlit==1.54.0" >/dev/null
fi

echo "Starting Malomatia Gov-Service Triage prototype on http://localhost:8501"
exec "$PYTHON_BIN" -m streamlit run "$PROJECT_DIR/gov_triage_dashboard.py"
