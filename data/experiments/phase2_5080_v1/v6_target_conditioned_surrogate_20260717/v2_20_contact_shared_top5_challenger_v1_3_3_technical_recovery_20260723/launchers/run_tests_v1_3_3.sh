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
  tests/test_v220_v1_3_3_lifecycle.py
)
(
  cd "$ROOT"
  sha256sum -c <<'SUMS'
097f345bdd0bac6b0799f5488012d2780d6f99cf6d61bc0e280f16b1b535533a  tests/test_v220_shared_calibration_artifact_v1_3_1.py
d0fc5bee3a97fa6b10dfc6115ea643ea264e1465a24e1863e43a35cd5928bfbc  tests/test_v220_v1_3_3_lifecycle.py
SUMS
  "$PYTHON_BIN" -m unittest "${REL_TEST_FILES[@]}" -v
) 2>&1 | tee "$LOG"
grep -Eq '^Ran 44 tests in ' "$LOG"
grep -Eq '^OK$' "$LOG"
"$PYTHON_BIN" -m py_compile "$ROOT"/src/*.py "$ROOT"/tests/*.py
