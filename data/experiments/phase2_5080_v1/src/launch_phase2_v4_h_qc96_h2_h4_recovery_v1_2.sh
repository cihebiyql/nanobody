#!/usr/bin/env bash
set -Eeuo pipefail

MODE=${1:---preflight-only}
case "$MODE" in
  --preflight-only|--execute) ;;
  *) echo "usage: $0 [--preflight-only|--execute]" >&2; exit 64 ;;
esac

REPO_BASE=${PVRIG_REPO_BASE:-/mnt/d/work/抗体/data}
EXP="$REPO_BASE/experiments/phase2_5080_v1"
SELF_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SSH_EXE=${SSH_EXE:-/mnt/c/Windows/System32/OpenSSH/ssh.exe}
REMOTE_HOST=${REMOTE_HOST:-node1}
SOURCE_ROOT=/data1/qlyu/projects/pvrig_v4_h_qc96_h0_h3_v1_20260717
RECOVERY_ROOT=/data1/qlyu/projects/pvrig_v4_h_qc96_h2_h4_recovery_v1_2_20260717
EXPECTED_SCRIPT_SHA256=17db32bcc129668fac924e3253fa9ad76079b14a648eb502e0e5bd5b61264f81
EXPECTED_PREREG_SHA256=7f9bdb159e2f4ea7ae3b319b920fecff1392bebfcb92a2a0be0cc48b8782d4dc
EXPECTED_FREEZE_SHA256=8a2d408b13d754cdfb36af9d435ceb3bdb0b9aa04dd21fe7da9f98f5cd567e94
EXPECTED_REAL1440_FULL_RUN_SHA256=403d816a885e015fa108353c8e95254c6b4a9bd2125b77495370ca272da87d3e
EXPECTED_V1_1_FAILURE_RECEIPT_SHA256=0f5388ca7ad89b71fc359a5dd1e3ef7ba3d4edb14abeb4e73135af9f02be335d
EXPECTED_V1_1_PARTIAL_AUDIT_SHA256=fd50248b5d80b85a57229397a6aa998d97552b712015ca215658b1dd168a983a
EXPECTED_V1_1_PREFLIGHT_LOG_SHA256=dd8ebc618a904066a550c7b7da784cb26057757c92da3605344195cc4a294051
EXPECTED_V1_1_FAILURE_LOG_SHA256=5b9d80969805d6992bed6d66261d4141638499fb2ed47752c6950731bea4c43a

if [[ -f "$SELF_DIR/recover_phase2_v4_h_qc96_h2_h4_v1_2.py" && \
      -f "$SELF_DIR/PREREGISTRATION.json" && \
      -f "$SELF_DIR/IMPLEMENTATION_FREEZE.json" ]]; then
  SCRIPT="$SELF_DIR/recover_phase2_v4_h_qc96_h2_h4_v1_2.py"
  PREREG="$SELF_DIR/PREREGISTRATION.json"
  FREEZE="$SELF_DIR/IMPLEMENTATION_FREEZE.json"
  FULL_RUN="$SELF_DIR/REAL1440_FULL_RUN_REPLAY.json"
  V11_FAILURE_RECEIPT="$SELF_DIR/V1_1_FAILURE_RECEIPT.json"
  V11_PARTIAL_AUDIT="$SELF_DIR/V1_1_PARTIAL_PUBLICATION_AUDIT.json"
  V11_PREFLIGHT_LOG="$SELF_DIR/V1_1_EXECUTE_PREFLIGHT.log"
  V11_FAILURE_LOG="$SELF_DIR/V1_1_EXECUTION_FAILURE.log"
  LOG_DIR="$SELF_DIR"
else
  SCRIPT="$EXP/src/recover_phase2_v4_h_qc96_h2_h4_v1_2.py"
  PREREG="$EXP/audits/phase2_v4_h_qc96_h2_h4_recovery_v1_2_preregistration.json"
  FREEZE="$EXP/audits/phase2_v4_h_qc96_h2_h4_recovery_v1_2_implementation_freeze.json"
  FULL_RUN="$EXP/audits/phase2_v4_h_qc96_h2_h4_recovery_v1_2_real1440_full_run_replay.json"
  V11_FAILURE_RECEIPT="$EXP/audits/phase2_v4_h_qc96_h2_h4_recovery_v1_1_failure_receipt.json"
  V11_PARTIAL_AUDIT="$EXP/audits/phase2_v4_h_qc96_h2_h4_recovery_v1_1_partial_publication_audit.json"
  V11_PREFLIGHT_LOG="$EXP/audits/phase2_v4_h_qc96_h2_h4_recovery_v1_1_remote_execute_preflight.log"
  V11_FAILURE_LOG="$EXP/audits/phase2_v4_h_qc96_h2_h4_recovery_v1_1_remote_execution_failure.log"
  LOG_DIR="$EXP/audits"
fi

[[ -z ${PYTHONOPTIMIZE:-} || ${PYTHONOPTIMIZE:-0} == 0 ]]
[[ -x "$SSH_EXE" ]]
[[ $(sha256sum "$SCRIPT" | awk '{print $1}') == "$EXPECTED_SCRIPT_SHA256" ]]
[[ $(sha256sum "$PREREG" | awk '{print $1}') == "$EXPECTED_PREREG_SHA256" ]]
[[ $(sha256sum "$FREEZE" | awk '{print $1}') == "$EXPECTED_FREEZE_SHA256" ]]
[[ $(sha256sum "$FULL_RUN" | awk '{print $1}') == "$EXPECTED_REAL1440_FULL_RUN_SHA256" ]]
[[ $(sha256sum "$V11_FAILURE_RECEIPT" | awk '{print $1}') == "$EXPECTED_V1_1_FAILURE_RECEIPT_SHA256" ]]
[[ $(sha256sum "$V11_PARTIAL_AUDIT" | awk '{print $1}') == "$EXPECTED_V1_1_PARTIAL_AUDIT_SHA256" ]]
[[ $(sha256sum "$V11_PREFLIGHT_LOG" | awk '{print $1}') == "$EXPECTED_V1_1_PREFLIGHT_LOG_SHA256" ]]
[[ $(sha256sum "$V11_FAILURE_LOG" | awk '{print $1}') == "$EXPECTED_V1_1_FAILURE_LOG_SHA256" ]]

if [[ "$MODE" == "--preflight-only" ]]; then
  PREFLIGHT_LOG="$LOG_DIR/phase2_v4_h_qc96_h2_h4_recovery_v1_2_remote_preflight.log"
else
  PREFLIGHT_LOG="$LOG_DIR/phase2_v4_h_qc96_h2_h4_recovery_v1_2_remote_execute_preflight.log"
fi
[[ ! -e "$PREFLIGHT_LOG" ]]
"$SSH_EXE" "$REMOTE_HOST" "test -d '$SOURCE_ROOT' && test ! -e '$RECOVERY_ROOT'"
{
  "$SSH_EXE" "$REMOTE_HOST" \
    "env PYTHONOPTIMIZE=0 /usr/bin/python3 - --source-root '$SOURCE_ROOT' --recovery-root '$RECOVERY_ROOT' --preflight" \
    < "$SCRIPT"
} 2>&1 | tee "$PREFLIGHT_LOG"
grep -q 'PASS_V4_H_H2_H4_RECOVERY_V1_2_PREFLIGHT' "$PREFLIGHT_LOG"
"$SSH_EXE" "$REMOTE_HOST" "test ! -e '$RECOVERY_ROOT'"

if [[ "$MODE" == "--preflight-only" ]]; then
  echo 'PASS_V1_2_ZERO_WORK_PREFLIGHT_ONLY_REMOTE_RECOVERY_ROOT_ABSENT'
  exit 0
fi

EXECUTION_LOG="$LOG_DIR/phase2_v4_h_qc96_h2_h4_recovery_v1_2_remote_execution.log"
[[ ! -e "$EXECUTION_LOG" ]]
{
  "$SSH_EXE" "$REMOTE_HOST" \
    "env PYTHONOPTIMIZE=0 /usr/bin/python3 - --source-root '$SOURCE_ROOT' --recovery-root '$RECOVERY_ROOT'" \
    < "$SCRIPT"
} 2>&1 | tee "$EXECUTION_LOG"
"$SSH_EXE" "$REMOTE_HOST" \
  "test -f '$RECOVERY_ROOT/recovery.complete.json' && test -f '$RECOVERY_ROOT/qc96_manifest_v1.tsv' && test -f '$RECOVERY_ROOT/qc96_selected_source_provenance_v1.tsv' && test -f '$RECOVERY_ROOT/qc96_audit_v1.json' && test -f '$RECOVERY_ROOT/qc96_receipt_v1.json'"
