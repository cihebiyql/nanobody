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
  tests/test_v220_v1_3_4_lifecycle.py
)
(
  cd "$ROOT"
  sha256sum -c <<'SUMS'
4a5073a0f21623faa4a77195ffcc9282be2e1f5f1c2ecf4c679a9bd3d48c5189  tests/test_v220_shared_calibration_artifact_v1_3_1.py
2ee236504892cb63b9e0dfa1eeae2eea04d39a09810ee0fba0a7c4693bade2be  tests/test_v220_v1_3_4_lifecycle.py
SUMS
  [[ "$(sha256sum "$EXACT_FILE_RUNNER" | awk '{print $1}')" == "$EXPECTED_EXACT_FILE_RUNNER_SHA256" ]]
  "$PYTHON_BIN" "$EXACT_FILE_RUNNER" "$ROOT" "${REL_TEST_FILES[@]}" --verbosity 2
) 2>&1 | tee "$LOG"
grep -Eq '^Ran 44 tests in ' "$LOG"
grep -Eq '^OK$' "$LOG"
grep -Eq '^EXACT_FILE_TESTS_RUN=44$' "$LOG"
"$PYTHON_BIN" -m py_compile "$ROOT"/src/*.py "$ROOT"/tests/*.py
