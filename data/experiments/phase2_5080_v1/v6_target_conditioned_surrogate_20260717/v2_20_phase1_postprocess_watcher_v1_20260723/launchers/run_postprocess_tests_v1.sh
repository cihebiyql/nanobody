#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
TMP_LOG="$(mktemp)"
trap 'rm -f "$TMP_LOG"' EXIT

(
  cd "$ROOT"
  sha256sum -c <<'SUMS'
d224508b83e7c8dbe654c45c5079b89afe41041b2170ca48c9411b3b23a5c48a  tests/test_run_v220_phase1_postprocess_watcher_v1.py
SUMS
)

"$PYTHON_BIN" -m unittest \
  "$ROOT/tests/test_run_v220_phase1_postprocess_watcher_v1.py" -v \
  2>&1 | tee "$TMP_LOG"
grep -Eq '^Ran 10 tests in ' "$TMP_LOG"
grep -Eq '^OK$' "$TMP_LOG"
"$PYTHON_BIN" -m py_compile \
  "$ROOT/src/run_v220_phase1_postprocess_watcher_v1.py" \
  "$ROOT/tests/test_run_v220_phase1_postprocess_watcher_v1.py"
