#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

export PYTHONPATH="${PYTHONPATH:-}:$(pwd):$(pwd)/backend"

if [ -x ".venv/bin/python" ]; then
  .venv/bin/python backend/scripts/rebuild_recent_120_data.py "$@"
else
  python backend/scripts/rebuild_recent_120_data.py "$@"
fi
