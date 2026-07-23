#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT

"$PYTHON_BIN" -m unittest \
  "$ROOT/tests/test_v220_shared_calibration_artifact_v1_3_1.py" \
  "$ROOT/tests/test_v220_v1_3_1_lifecycle.py" -v 2>&1 | tee "$LOG"
grep -Eq '^Ran 32 tests in ' "$LOG"
grep -Eq '^OK$' "$LOG"
"$PYTHON_BIN" -m py_compile "$ROOT"/src/*.py "$ROOT"/tests/*.py
