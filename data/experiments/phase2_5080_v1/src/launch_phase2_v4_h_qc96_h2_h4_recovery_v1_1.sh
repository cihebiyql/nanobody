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
RECOVERY_ROOT=/data1/qlyu/projects/pvrig_v4_h_qc96_h2_h4_recovery_v1_1_20260717
EXPECTED_SCRIPT_SHA256=9df6cd31b5af7a26d08a7cadd22b0be9b321509e6f4e9104f0acd963ea38d066
EXPECTED_PREREG_SHA256=32979ecf1810529e16a9283894faf7295df1d9d321444adf846e509dfe007ac9
EXPECTED_FREEZE_SHA256=8cfa84cee865d857255f07e87c47e17f0a9f927cfca5da87f05c1f79853dbfd3
EXPECTED_REAL1440_PARITY_SHA256=e68aa1bdfb5426f155ae387b9297cdf21d06ff394f77ace3fd0b2e6812f72021
EXPECTED_V1_FAILURE_RECEIPT_SHA256=00c9645821158c0b48784261f9ed32f64479ab0696376f5e55f64830791be439
EXPECTED_V1_FAILURE_LOG_SHA256=cf2e08705d986d2748e1334f0207738c24e1fa4f209d6196bfd2bcd80dcfaeb1

if [[ -f "$SELF_DIR/recover_phase2_v4_h_qc96_h2_h4_v1_1.py" && \
      -f "$SELF_DIR/PREREGISTRATION.json" && \
      -f "$SELF_DIR/IMPLEMENTATION_FREEZE.json" ]]; then
  SCRIPT="$SELF_DIR/recover_phase2_v4_h_qc96_h2_h4_v1_1.py"
  PREREG="$SELF_DIR/PREREGISTRATION.json"
  FREEZE="$SELF_DIR/IMPLEMENTATION_FREEZE.json"
  PARITY="$SELF_DIR/REAL1440_SELECTION_PARITY.json"
  V1_FAILURE_RECEIPT="$SELF_DIR/V1_PREFLIGHT_FAILURE_RECEIPT.json"
  V1_FAILURE_LOG="$SELF_DIR/V1_PREFLIGHT_FAILURE.log"
  LOG_DIR="$SELF_DIR"
else
  SCRIPT="$EXP/src/recover_phase2_v4_h_qc96_h2_h4_v1_1.py"
  PREREG="$EXP/audits/phase2_v4_h_qc96_h2_h4_recovery_v1_1_preregistration.json"
  FREEZE="$EXP/audits/phase2_v4_h_qc96_h2_h4_recovery_v1_1_implementation_freeze.json"
  PARITY="$EXP/audits/phase2_v4_h_qc96_h2_h4_recovery_v1_1_real1440_selection_parity.json"
  V1_FAILURE_RECEIPT="$EXP/audits/phase2_v4_h_qc96_h2_h4_recovery_v1_preflight_failure_receipt.json"
  V1_FAILURE_LOG="$EXP/audits/phase2_v4_h_qc96_h2_h4_recovery_v1_remote_preflight_failure.log"
  LOG_DIR="$EXP/audits"
fi

[[ -z ${PYTHONOPTIMIZE:-} || ${PYTHONOPTIMIZE:-0} == 0 ]]
[[ -x "$SSH_EXE" ]]
[[ $(sha256sum "$SCRIPT" | awk '{print $1}') == "$EXPECTED_SCRIPT_SHA256" ]]
[[ $(sha256sum "$PREREG" | awk '{print $1}') == "$EXPECTED_PREREG_SHA256" ]]
[[ $(sha256sum "$FREEZE" | awk '{print $1}') == "$EXPECTED_FREEZE_SHA256" ]]
[[ $(sha256sum "$PARITY" | awk '{print $1}') == "$EXPECTED_REAL1440_PARITY_SHA256" ]]
[[ $(sha256sum "$V1_FAILURE_RECEIPT" | awk '{print $1}') == "$EXPECTED_V1_FAILURE_RECEIPT_SHA256" ]]
[[ $(sha256sum "$V1_FAILURE_LOG" | awk '{print $1}') == "$EXPECTED_V1_FAILURE_LOG_SHA256" ]]

if [[ "$MODE" == "--preflight-only" ]]; then
  PREFLIGHT_LOG="$LOG_DIR/phase2_v4_h_qc96_h2_h4_recovery_v1_1_remote_preflight.log"
else
  PREFLIGHT_LOG="$LOG_DIR/phase2_v4_h_qc96_h2_h4_recovery_v1_1_remote_execute_preflight.log"
fi
[[ ! -e "$PREFLIGHT_LOG" ]]
"$SSH_EXE" "$REMOTE_HOST" "test -d '$SOURCE_ROOT' && test ! -e '$RECOVERY_ROOT'"
{
  "$SSH_EXE" "$REMOTE_HOST" \
    "env PYTHONOPTIMIZE=0 /usr/bin/python3 - --source-root '$SOURCE_ROOT' --recovery-root '$RECOVERY_ROOT' --preflight" \
    < "$SCRIPT"
} 2>&1 | tee "$PREFLIGHT_LOG"
grep -q 'PASS_V4_H_H2_H4_RECOVERY_V1_1_PREFLIGHT' "$PREFLIGHT_LOG"
"$SSH_EXE" "$REMOTE_HOST" "test ! -e '$RECOVERY_ROOT'"

if [[ "$MODE" == "--preflight-only" ]]; then
  echo 'PASS_V1_1_ZERO_WORK_PREFLIGHT_ONLY_REMOTE_RECOVERY_ROOT_ABSENT'
  exit 0
fi

EXECUTION_LOG="$LOG_DIR/phase2_v4_h_qc96_h2_h4_recovery_v1_1_remote_execution.log"
[[ ! -e "$EXECUTION_LOG" ]]
{
  "$SSH_EXE" "$REMOTE_HOST" \
    "env PYTHONOPTIMIZE=0 /usr/bin/python3 - --source-root '$SOURCE_ROOT' --recovery-root '$RECOVERY_ROOT'" \
    < "$SCRIPT"
} 2>&1 | tee "$EXECUTION_LOG"
"$SSH_EXE" "$REMOTE_HOST" \
  "test -f '$RECOVERY_ROOT/recovery.complete.json' && test -f '$RECOVERY_ROOT/qc96_manifest_v1.tsv' && test -f '$RECOVERY_ROOT/qc96_selected_source_provenance_v1.tsv' && test -f '$RECOVERY_ROOT/qc96_audit_v1.json' && test -f '$RECOVERY_ROOT/qc96_receipt_v1.json'"
