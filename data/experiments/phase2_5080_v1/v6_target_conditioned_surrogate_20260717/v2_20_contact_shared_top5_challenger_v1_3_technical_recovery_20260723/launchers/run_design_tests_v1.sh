#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" -m py_compile \
  "$ROOT/src/v220_shared_calibration_artifact_v1.py" \
  "$ROOT/src/materialize_v220_shared_fold_calibration_v1_3.py" \
  "$ROOT/src/run_v220_contact_shared_fold_v1_3.py" \
  "$ROOT/tests/test_v220_shared_calibration_artifact_v1.py"

bash -n "$ROOT/launchers/run_phase1_core_fold_pair_node1_v1_3.sh"

cd "$ROOT"
"$PYTHON_BIN" -m unittest -v tests/test_v220_shared_calibration_artifact_v1.py
