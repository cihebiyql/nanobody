#!/usr/bin/env bash
set -euo pipefail
ROOT=${1:?usage: run_phase0_14_tests_v1.sh ROOT PYTHON OUTPUT_LOG}
PYTHON=${2:?}
LOG=${3:?}
test ! -e "$LOG"
test -x "$PYTHON"
test -f "$ROOT/src/materialize_v220_train_contact_teacher_v1.py"
test -f "$ROOT/tests/test_materialize_v220_train_contact_teacher_v1.py"
umask 022
{
  echo 'schema_version=pvrig_v2_20_phase0_single_immutable_14_test_log_v1'
  echo 'status=RUNNING'
  echo "python=$PYTHON"
  "$PYTHON" --version
  "$PYTHON" - <<'PY'
import numpy
print('numpy='+numpy.__version__)
PY
  sha256sum \
    "$ROOT/src/materialize_v220_train_contact_teacher_v1.py" \
    "$ROOT/tests/test_materialize_v220_train_contact_teacher_v1.py" \
    "$ROOT/PHASE0_TEACHER_MATERIALIZATION_CONTRACT_V1.json"
  cd "$ROOT"
  "$PYTHON" -m unittest -v tests/test_materialize_v220_train_contact_teacher_v1.py
  echo 'tests_run=14'
  echo 'status=PASS'
  echo 'oof_training_authorized=false'
} > "$LOG" 2>&1
chmod 0444 "$LOG"
sha256sum "$LOG"
