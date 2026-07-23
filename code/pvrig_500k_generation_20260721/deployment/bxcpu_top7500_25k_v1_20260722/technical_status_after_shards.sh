#!/usr/bin/env bash
set -euo pipefail
DEPLOY=$(cd "$(dirname "$0")" && pwd)
PYTHON=${PVRIG_TOP7500_AUDIT_PYTHON:-$HOME/.local/opt/haddock3-2025.11.0/bin/python}
"$PYTHON" "$DEPLOY/technical_status_top7500_25k.py"
