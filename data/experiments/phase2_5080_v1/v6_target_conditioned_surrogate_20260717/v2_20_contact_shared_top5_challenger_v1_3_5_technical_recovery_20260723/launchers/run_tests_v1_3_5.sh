#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
EXACT_FILE_RUNNER="$ROOT/src/run_unittest_file_paths_v1_3_4.py"
EXPECTED_EXACT_FILE_RUNNER_SHA256="0cd9b79bc31c6ca3e4a62a1d5fbead6fffb26bcc4de3b2fa9f1b9b7a25fa1c7b"
LOG="$(mktemp)"
CACHE_ROOT="$(mktemp -d)"
trap 'rm -f "$LOG"; rm -rf "$CACHE_ROOT"' EXIT
export PYTHONPYCACHEPREFIX="$CACHE_ROOT"

REL_TEST_FILES=(
  tests/test_v220_shared_calibration_artifact_v1_3_1.py
  tests/test_v220_v1_3_5_lifecycle.py
)
(
  cd "$ROOT"
  sha256sum -c <<'SUMS'
bc10d8d116404f37743244e32b2fca797e5cd196cffbaf4c9406ad66c71ae6df  tests/test_v220_shared_calibration_artifact_v1_3_1.py
d2de9a6371da782efef2f6267be11d0aa12a549fff7443b0d535f280dbf00c82  tests/test_v220_v1_3_5_lifecycle.py
SUMS
  [[ "$(sha256sum "$EXACT_FILE_RUNNER" | awk '{print $1}')" == "$EXPECTED_EXACT_FILE_RUNNER_SHA256" ]]
  "$PYTHON_BIN" "$EXACT_FILE_RUNNER" "$ROOT" "${REL_TEST_FILES[@]}" --verbosity 2
) 2>&1 | tee "$LOG"
grep -Eq '^Ran 46 tests in ' "$LOG"
grep -Eq '^OK$' "$LOG"
grep -Eq '^EXACT_FILE_TESTS_RUN=46$' "$LOG"
"$PYTHON_BIN" -m py_compile "$ROOT"/src/*.py "$ROOT"/tests/*.py
