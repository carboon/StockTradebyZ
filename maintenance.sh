#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

exec /usr/bin/python3 "$SCRIPT_DIR/deploy/scripts/maintenance_rebuild_and_restart.py" "$@"
