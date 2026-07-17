#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/data/qlyu/projects/pvrig_v4_g_c0154_hardpass12_dual_redocking_v1_20260717
SOURCE=/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715
OPEN_TEACHER=/data/qlyu/projects/pvrig_v4_d_open_teacher_postprocess_v1_20260716
PYTHON_REQUESTED=/data/qlyu/anaconda3/envs/haddock3/bin/python
PYTHON_RESOLVED=/data/qlyu/anaconda3/envs/haddock3/bin/python3.11
WAITER="$ROOT/scripts/wait_for_v4d_open_teacher_then_run_v3.py"

EXPECTED_WAITER_V3_SHA256=8a6d5354c8bb017c3ce90621f3edd1aac5dc674babbca24a4f4a3316f3048e1a
EXPECTED_V2_ANCHOR_SHA256=7144e6a6adc0fa72e13c9a4f6edb4bde3913281bdea64e70cd18e2e58d9a4e3b
EXPECTED_V2_FREEZE_SHA256=b15c5b32a0d5f6a00c3abe26bbbb9ee149b48724e0ec7fa08d717eccba352b99
EXPECTED_V2_STOP_RECEIPT_SHA256=0a1ead8e7849ff90dd768e3462be4fddc55c7bbc583cb07a4c35ed314a48c43b
EXPECTED_V3_ANCHOR_SHA256=5b149b478f5550559822a33223ae1fca81d564927e7e7a6b99770cc5c57f9242
EXPECTED_V3_POLICY_FREEZE_SHA256=0ef462a5d7e1b8d73580b9bfb169bb2bf1cd624cde9e91a12d1751024ad7d7ab
EXPECTED_V3_IMPLEMENTATION_FREEZE_SHA256=7c7060274af988e758a6ea428dc1b03db72871ceb4e2511eac1dca5f3c1ffcbd
EXPECTED_V3_ZERO_JOB_PREFLIGHT_RECEIPT_SHA256=a180fa0b507a2f6cd89fb91e942b978b421ba6e2450c6d7bc57ce893cd63f5e4
EXPECTED_PYTHON_SHA256=377159f8604e0fbfe362218df369a651be2123158a25296f6ace4b5c58c6c62a

verify_sha() {
  local path=$1 expected=$2 label=$3
  [[ -f "$path" && ! -L "$path" ]] || { echo "nonregular_or_symlink:$label" >&2; exit 70; }
  local observed
  observed=$(sha256sum "$path" | awk '{print $1}')
  [[ "$observed" == "$expected" ]] || { echo "sha256_mismatch:$label:$observed" >&2; exit 71; }
}

for directory in "$ROOT" "$SOURCE" "$OPEN_TEACHER"; do
  [[ -d "$directory" && ! -L "$directory" ]] || { echo "runtime_directory_invalid:$directory" >&2; exit 72; }
  [[ "$(readlink -f "$directory")" == "$directory" ]] || { echo "runtime_directory_drift:$directory" >&2; exit 72; }
done
[[ "$(readlink -f "$PYTHON_REQUESTED")" == "$PYTHON_RESOLVED" ]] || { echo python_resolved_drift >&2; exit 72; }
verify_sha "$PYTHON_RESOLVED" "$EXPECTED_PYTHON_SHA256" python
verify_sha "$WAITER" "$EXPECTED_WAITER_V3_SHA256" waiter_v3
verify_sha "$ROOT/WAITER_TRUST_ANCHOR_V2.json" "$EXPECTED_V2_ANCHOR_SHA256" v2_anchor
verify_sha "$ROOT/WAITER_V2_IMPLEMENTATION_FREEZE.json" "$EXPECTED_V2_FREEZE_SHA256" v2_freeze
verify_sha "$ROOT/status/waiter_v2_stopped_for_v3_security_fix.json" "$EXPECTED_V2_STOP_RECEIPT_SHA256" v2_stop_receipt
verify_sha "$ROOT/WAITER_TRUST_ANCHOR_V3.json" "$EXPECTED_V3_ANCHOR_SHA256" v3_anchor
verify_sha "$ROOT/WAITER_V3_POLICY_FREEZE.json" "$EXPECTED_V3_POLICY_FREEZE_SHA256" v3_policy_freeze
verify_sha "$ROOT/WAITER_V3_IMPLEMENTATION_FREEZE.json" "$EXPECTED_V3_IMPLEMENTATION_FREEZE_SHA256" v3_implementation_freeze
verify_sha "$ROOT/status/waiter_v3_zero_job_preflight_receipt.json" "$EXPECTED_V3_ZERO_JOB_PREFLIGHT_RECEIPT_SHA256" v3_zero_job_preflight_receipt

[[ ! -e "$ROOT/status/controller.json" && ! -L "$ROOT/status/controller.json" ]] || { echo controller_state_exists >&2; exit 73; }
[[ $(find "$ROOT/status/jobs" -type f 2>/dev/null | wc -l) -eq 0 ]] || { echo job_state_not_zero >&2; exit 73; }
[[ $(find "$ROOT/runs" -mindepth 1 2>/dev/null | wc -l) -eq 0 ]] || { echo runs_not_zero >&2; exit 73; }
[[ $(find "$ROOT/results" -mindepth 1 2>/dev/null | wc -l) -eq 0 ]] || { echo results_not_zero >&2; exit 73; }

cd "$ROOT"
exec /usr/bin/env -i \
  HOME=/data/qlyu USER=qlyu LOGNAME=qlyu LANG=C.UTF-8 OMP_NUM_THREADS=1 \
  PATH=/data/qlyu/anaconda3/envs/haddock3/bin:/usr/local/bin:/usr/bin:/bin \
  PVRIG_PROJECT_ROOT="$ROOT" \
  PVRIG_V4G12_ROOT="$ROOT" \
  PVRIG_V4D_SOURCE="$SOURCE" \
  PVRIG_V4D_OPEN_TEACHER_ROOT="$OPEN_TEACHER" \
  PVRIG_V4G12_PYTHON="$PYTHON_REQUESTED" \
  PVRIG_V4G12_MAX_LOAD1=16 \
  PVRIG_V4G12_POLL_SECONDS=300 \
  /usr/bin/nice -n 15 "$PYTHON_RESOLVED" "$WAITER"
