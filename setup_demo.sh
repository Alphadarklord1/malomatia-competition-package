#!/usr/bin/env bash
# Sets up a working demo environment from a clean clone.
# Usage: ./setup_demo.sh

set -euo pipefail
cd "$(dirname "$0")"

SECRETS_FILE=".streamlit/secrets.toml"
EXAMPLE_FILE=".streamlit/secrets.example.toml"

if [ -f "$SECRETS_FILE" ]; then
  echo "secrets.toml already exists — skipping."
else
  if [ ! -f "$EXAMPLE_FILE" ]; then
    echo "ERROR: $EXAMPLE_FILE not found."
    exit 1
  fi
  cp "$EXAMPLE_FILE" "$SECRETS_FILE"
  echo "Created $SECRETS_FILE from template."
  echo "Demo credentials:"
  echo "  operator_demo  / Operator@123"
  echo "  supervisor_demo / Supervisor@123"
  echo "  auditor_demo   / Auditor@123"
fi

echo ""
echo "Run the app with: ./run_prototype.sh"
