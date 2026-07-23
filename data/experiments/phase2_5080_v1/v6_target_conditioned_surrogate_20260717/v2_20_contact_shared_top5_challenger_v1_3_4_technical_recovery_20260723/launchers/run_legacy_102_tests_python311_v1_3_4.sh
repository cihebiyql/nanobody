#!/usr/bin/env bash
set -euo pipefail

LEGACY_ROOT="${1:?usage: PYTHON_BIN=/path/python $0 LEGACY_V1_2_ROOT}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PACKAGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXACT_FILE_RUNNER="$PACKAGE_ROOT/src/run_unittest_file_paths_v1_3_4.py"
EXPECTED_EXACT_FILE_RUNNER_SHA256="0cd9b79bc31c6ca3e4a62a1d5fbead6fffb26bcc4de3b2fa9f1b9b7a25fa1c7b"
[[ -d "$LEGACY_ROOT/tests" && -d "$LEGACY_ROOT/src" ]] || {
  echo "invalid_legacy_root:$LEGACY_ROOT" >&2
  exit 2
}
[[ -f "$EXACT_FILE_RUNNER" && ! -L "$EXACT_FILE_RUNNER" ]] || {
  echo "exact_file_runner_missing:$EXACT_FILE_RUNNER" >&2
  exit 4
}
[[ "$(sha256sum "$EXACT_FILE_RUNNER" | awk '{print $1}')" == "$EXPECTED_EXACT_FILE_RUNNER_SHA256" ]] || {
  echo "exact_file_runner_hash_mismatch:$EXACT_FILE_RUNNER" >&2
  exit 4
}
PYTHON_VERSION="$("$PYTHON_BIN" --version 2>&1)"
[[ "$PYTHON_VERSION" == "Python 3.11.14" ]] || {
  echo "python_version_mismatch:expected=Python 3.11.14:observed=$PYTHON_VERSION" >&2
  exit 3
}
CACHE_ROOT="$(mktemp -d)"
export PYTHONPYCACHEPREFIX="$CACHE_ROOT"

REL_TEST_FILES=(
  tests/test_calibrate_v220_contact_weight_v1.py
  tests/test_collect_v220_contact_shared_oof_v1.py
  tests/test_evaluate_v220_phase1_core_gate_v1.py
  tests/test_materialize_v220_paired_initial_state_v1.py
  tests/test_materialize_v220_production_initial_state_v1.py
  tests/test_materialize_v220_train_contact_teacher_v1.py
  tests/test_materialize_v220_train_contact_teacher_v1_1.py
  tests/test_materialize_v220_train_contact_teacher_v1_2.py
  tests/test_run_v220_contact_shared_fold_v1.py
  tests/test_v220_b0_replay_and_evaluator_v1.py
  tests/test_v220_contact_teacher_store_v1.py
  tests/test_validate_v220_paired_folds_v1.py
  tests/test_validate_v220_cross_process_initial_state_v1.py
)

"$PYTHON_BIN" - "$LEGACY_ROOT/tests" "${REL_TEST_FILES[@]}" <<'PY'
import sys
from pathlib import Path
root=Path(sys.argv[1]).resolve(strict=True)
relative=sys.argv[2:]
assert len(relative)==13 and len(set(relative))==13
assert all(Path(value).parent == Path('tests') for value in relative)
expected={Path(value).name for value in relative}
observed={p.name for p in root.glob('test_*.py') if p.is_file() and not p.is_symlink()}
assert observed==expected,(sorted(observed-expected),sorted(expected-observed))
for name in expected:
    path=root/name
    assert path.is_file() and not path.is_symlink(),name
PY

(
  cd "$LEGACY_ROOT"
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

LOG="$(mktemp)"
trap 'rm -f "$LOG"; rm -rf "$CACHE_ROOT"' EXIT
(
  cd "$LEGACY_ROOT"
  "$PYTHON_BIN" "$EXACT_FILE_RUNNER" "$LEGACY_ROOT" "${REL_TEST_FILES[@]}" --verbosity 2
) 2>&1 | tee "$LOG"
grep -Eq '^Ran 102 tests in ' "$LOG"
grep -Eq '^OK$' "$LOG"
grep -Eq '^EXACT_FILE_TESTS_RUN=102$' "$LOG"
"$PYTHON_BIN" -m py_compile "$LEGACY_ROOT"/src/*.py "${REL_TEST_FILES[@]/#/$LEGACY_ROOT/}"
printf 'PASS_LEGACY_102_PYTHON311_COMPATIBLE python=%s\n' "$PYTHON_VERSION"
