#!/usr/bin/env bash
set -Eeuo pipefail

REPO_BASE=${PVRIG_REPO_BASE:-/mnt/d/work/抗体/data}
EXP="$REPO_BASE/experiments/phase2_5080_v1"
SELF_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SSH_EXE=${SSH_EXE:-/mnt/c/Windows/System32/OpenSSH/ssh.exe}
REMOTE_HOST=${REMOTE_HOST:-node1}
SOURCE_ROOT=/data1/qlyu/projects/pvrig_v4_h_qc96_h0_h3_v1_20260717
RECOVERY_ROOT=/data1/qlyu/projects/pvrig_v4_h_qc96_h2_h4_recovery_v1_20260717
EXPECTED_SCRIPT_SHA256=17960e1ea7b01c8354630ffeb7c63738622bc2675365bba368342a9f14b19d22
EXPECTED_PREREG_SHA256=f31fb16568d906204c44d451e2e679140c99ecc0ebf8e8f97ff9a460a3bcd6a3
EXPECTED_FREEZE_SHA256=78b572a16d148be949ce6385acfadfbe9b62731924bd26c8e848eda4f990dd73

if [[ -f "$SELF_DIR/recover_phase2_v4_h_qc96_h2_h4_v1.py" && \
      -f "$SELF_DIR/PREREGISTRATION.json" && \
      -f "$SELF_DIR/IMPLEMENTATION_FREEZE.json" ]]; then
  SCRIPT="$SELF_DIR/recover_phase2_v4_h_qc96_h2_h4_v1.py"
  PREREG="$SELF_DIR/PREREGISTRATION.json"
  FREEZE="$SELF_DIR/IMPLEMENTATION_FREEZE.json"
  EXECUTION_LOG="$SELF_DIR/REMOTE_EXECUTION.log"
else
  SCRIPT="$EXP/src/recover_phase2_v4_h_qc96_h2_h4_v1.py"
  PREREG="$EXP/audits/phase2_v4_h_qc96_h2_h4_recovery_v1_preregistration.json"
  FREEZE="$EXP/audits/phase2_v4_h_qc96_h2_h4_recovery_v1_implementation_freeze.json"
  EXECUTION_LOG="$EXP/audits/phase2_v4_h_qc96_h2_h4_recovery_v1_remote_execution.log"
fi

[[ -z ${PYTHONOPTIMIZE:-} || ${PYTHONOPTIMIZE:-0} == 0 ]]
[[ -x "$SSH_EXE" ]]
[[ $(sha256sum "$SCRIPT" | awk '{print $1}') == "$EXPECTED_SCRIPT_SHA256" ]]
[[ $(sha256sum "$PREREG" | awk '{print $1}') == "$EXPECTED_PREREG_SHA256" ]]
[[ $(sha256sum "$FREEZE" | awk '{print $1}') == "$EXPECTED_FREEZE_SHA256" ]]
[[ ! -e "$EXECUTION_LOG" ]]

"$SSH_EXE" "$REMOTE_HOST" \
  "test -d '$SOURCE_ROOT' && test ! -e '$RECOVERY_ROOT'"

"$SSH_EXE" "$REMOTE_HOST" \
  "env PYTHONOPTIMIZE=0 /usr/bin/python3 - --source-root '$SOURCE_ROOT' --recovery-root '$RECOVERY_ROOT' --preflight" \
  < "$SCRIPT"

"$SSH_EXE" "$REMOTE_HOST" \
  "env PYTHONOPTIMIZE=0 /usr/bin/python3 - --source-root '$SOURCE_ROOT' --recovery-root '$RECOVERY_ROOT'" \
  < "$SCRIPT" | tee "$EXECUTION_LOG"

"$SSH_EXE" "$REMOTE_HOST" \
  "test -f '$RECOVERY_ROOT/recovery.complete.json' && test -f '$RECOVERY_ROOT/qc96_manifest_v1.tsv' && test -f '$RECOVERY_ROOT/qc96_selected_source_provenance_v1.tsv' && test -f '$RECOVERY_ROOT/qc96_audit_v1.json' && test -f '$RECOVERY_ROOT/qc96_receipt_v1.json'"
