#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LOG="$(mktemp)"
CACHE_ROOT="$(mktemp -d)"
trap 'rm -f "$LOG"; rm -rf "$CACHE_ROOT"' EXIT
export PYTHONPYCACHEPREFIX="$CACHE_ROOT"

REL_TEST_FILES=(
  tests/test_v220_shared_calibration_artifact_v1_3_1.py
  tests/test_v220_v1_3_2_lifecycle.py
)
(
  cd "$ROOT"
  sha256sum -c <<'SUMS'
84d2214843a47e3a7129611a2f03564fcca362ac10c4f3e689e2754eadb6ee5a  tests/test_v220_shared_calibration_artifact_v1_3_1.py
a598db664194a774908213d05c2250057284990d09ceb814548affc3eb0909e6  tests/test_v220_v1_3_2_lifecycle.py
SUMS
  "$PYTHON_BIN" -m unittest "${REL_TEST_FILES[@]}" -v
) 2>&1 | tee "$LOG"
grep -Eq '^Ran 43 tests in ' "$LOG"
grep -Eq '^OK$' "$LOG"
"$PYTHON_BIN" -m py_compile "$ROOT"/src/*.py "$ROOT"/tests/*.py
