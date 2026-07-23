#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LEGACY_ROOT="${V220_V1_2_ROOT:-$(cd "$ROOT/../v2_20_contact_shared_top5_challenger_v1_2_20260723" && pwd)}"

PYTHON_BIN="$PYTHON_BIN" "$LEGACY_ROOT/launchers/run_phase1_core_preflight_tests_v1_2.sh"
PYTHON_BIN="$PYTHON_BIN" "$ROOT/launchers/run_tests_v1_3_1.sh"
printf '%s\n' 'PASS_COMBINED_V220_LEGACY_102_PLUS_V1_3_1_32_TOTAL_134_NO_TRAINING'
