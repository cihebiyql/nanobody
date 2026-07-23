#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LEGACY_ROOT="${V220_V1_2_ROOT:-$(cd "$ROOT/../v2_20_contact_shared_top5_challenger_v1_2_20260723" && pwd)}"

PYTHON_BIN="$PYTHON_BIN" "$ROOT/launchers/run_legacy_102_tests_python311_v1_3_4.sh" "$LEGACY_ROOT"
PYTHON_BIN="$PYTHON_BIN" "$ROOT/launchers/run_tests_v1_3_5.sh"
printf '%s\n' 'PASS_COMBINED_V220_LEGACY_102_PLUS_V1_3_5_NO_TRAINING'
