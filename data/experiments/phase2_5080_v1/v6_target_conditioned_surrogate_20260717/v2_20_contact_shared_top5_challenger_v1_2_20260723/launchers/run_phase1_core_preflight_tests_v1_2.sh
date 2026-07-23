#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
TMP_LOG="$(mktemp)"
trap 'rm -f "$TMP_LOG"' EXIT

(
  cd "$ROOT"
  sha256sum -c <<'SUMS'
395c220b67e7b5b35f8e47876fe48069758c1ba918b615b9ef2022720b6657cf  tests/test_calibrate_v220_contact_weight_v1.py
20460edb51de4ab0b5ca3c4a165da5b4e8a2f25f71bcea307f3788568f017409  tests/test_collect_v220_contact_shared_oof_v1.py
5dead1f038ed51f05e5a8e1b9731cffe6d550976145c038a0d23d51fecb1820d  tests/test_evaluate_v220_phase1_core_gate_v1.py
e1b698cd699977373e0e29e122dce622400313b7f79a900cecda6361477a864c  tests/test_materialize_v220_paired_initial_state_v1.py
4caa937b89733aa9d0404307ba5f9f9f232de1b67cffd5440a5574303b1f614f  tests/test_materialize_v220_production_initial_state_v1.py
39d9d88a598c602980593af17cbb7970881189e2cc3539c85b21c08b16c0cf10  tests/test_materialize_v220_train_contact_teacher_v1.py
1e00a0406a47c0deaf7a461790d9dc7bfda5233bdf987ca9ab39adf68f77836a  tests/test_materialize_v220_train_contact_teacher_v1_1.py
bee430e43c30301259100904aa9429a3e29e9cf1864bc5f1e9645c0a8a1dd51c  tests/test_materialize_v220_train_contact_teacher_v1_2.py
9240728322aedc2daffaf99992e724d2c0bb53382e551c41490fba7b05552023  tests/test_run_v220_contact_shared_fold_v1.py
67d3b895d3a65919248e9d8d9718e5c6d6f7194d28a5e6c4658b38f9986520bc  tests/test_v220_b0_replay_and_evaluator_v1.py
0afd87119450ee58bd2fe55e85177f0edfec57a4cc79293486ae9589ecb8114e  tests/test_v220_contact_teacher_store_v1.py
ec24ccdfe0acd011f1a1e086e94a313930b16b1e6b84f3451f85d9700796c0eb  tests/test_validate_v220_paired_folds_v1.py
340409ac3508c6840c88ab77deb2c65b1346dc61b6f00aba518424905316fb13  tests/test_validate_v220_cross_process_initial_state_v1.py
SUMS
)

TEST_FILES=(
  "$ROOT/tests/test_calibrate_v220_contact_weight_v1.py"
  "$ROOT/tests/test_collect_v220_contact_shared_oof_v1.py"
  "$ROOT/tests/test_evaluate_v220_phase1_core_gate_v1.py"
  "$ROOT/tests/test_materialize_v220_paired_initial_state_v1.py"
  "$ROOT/tests/test_materialize_v220_production_initial_state_v1.py"
  "$ROOT/tests/test_materialize_v220_train_contact_teacher_v1.py"
  "$ROOT/tests/test_materialize_v220_train_contact_teacher_v1_1.py"
  "$ROOT/tests/test_materialize_v220_train_contact_teacher_v1_2.py"
  "$ROOT/tests/test_run_v220_contact_shared_fold_v1.py"
  "$ROOT/tests/test_v220_b0_replay_and_evaluator_v1.py"
  "$ROOT/tests/test_v220_contact_teacher_store_v1.py"
  "$ROOT/tests/test_validate_v220_paired_folds_v1.py"
  "$ROOT/tests/test_validate_v220_cross_process_initial_state_v1.py"
)

"$PYTHON_BIN" -m unittest "${TEST_FILES[@]}" -v 2>&1 | tee "$TMP_LOG"
grep -Eq '^Ran 102 tests in ' "$TMP_LOG"
grep -Eq '^OK$' "$TMP_LOG"
"$PYTHON_BIN" -m py_compile "$ROOT"/src/*.py "${TEST_FILES[@]}"

