#!/usr/bin/env bash
# Run formal Teacher500 postprocessing only after all remote docking jobs pass.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SSH_COMMAND=${SSH_COMMAND:-ssh.exe}
NODE_HOST=${NODE_HOST:-node1}
REMOTE_ROOT=${REMOTE_ROOT:-/data/qlyu/projects/pvrig_teacher_formal_v1_20260712/teacher500_docking}
POLL_SECONDS=${POLL_SECONDS:-120}
POSTPROCESS_SCRIPT=${POSTPROCESS_SCRIPT:-$ROOT/src/run_pvrig_formal_teacher500_postprocess.sh}
LOG=${LOG:-$ROOT/logs/pvrig_formal_teacher500_docking_monitor.log}
LOCK=${LOCK:-/tmp/pvrig_formal_teacher500_docking_monitor.lock}
PID_FILE=${PID_FILE:-$ROOT/logs/pvrig_formal_teacher500_docking_monitor.pid}
STATUS_SCRIPT=${STATUS_SCRIPT:-$ROOT/src/summarize_pvrig_teacher500_docking_status.py}
EXPECTED_CANDIDATES=${EXPECTED_CANDIDATES:-500}
MIN_MODELS=${MIN_MODELS:-4}

mkdir -p "$(dirname "$LOG")"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "Another Teacher500 docking monitor already owns $LOCK" >&2
  exit 4
fi
exec >>"$LOG" 2>&1
printf '%s\n' "$$" >"$PID_FILE"
cleanup_pid_file() {
  if [[ -f "$PID_FILE" ]] && [[ $(cat "$PID_FILE") == "$$" ]]; then
    rm -f "$PID_FILE"
  fi
}
trap cleanup_pid_file EXIT

poll_remote_status() {
  "$SSH_COMMAND" "$NODE_HOST" \
    "python3 - '$REMOTE_ROOT' --expected-candidates '$EXPECTED_CANDIDATES' --min-models '$MIN_MODELS'" \
    <"$STATUS_SCRIPT"
}

echo "DOCKING_MONITOR_START $(date -Is) remote=$NODE_HOST:$REMOTE_ROOT"
while true; do
  if ! status=$(poll_remote_status 2>&1); then
    echo "DOCKING_POLL_RETRY $(date -Is) detail=$(printf '%q' "$status")" >&2
    sleep "$POLL_SECONDS"
    continue
  fi
  read -r complete alive remote_pid expected unique_started latest_success latest_failed pending model_ready top_models extra <<<"$status"
  if [[ -n ${extra:-} ]] ||
    [[ ! ${complete:-} =~ ^[01]$ ]] ||
    [[ ! ${alive:-} =~ ^[01]$ ]] ||
    [[ ! ${remote_pid:-} =~ ^[0-9]+$ ]] ||
    [[ ! ${expected:-} =~ ^[0-9]+$ ]] ||
    [[ ! ${unique_started:-} =~ ^[0-9]+$ ]] ||
    [[ ! ${latest_success:-} =~ ^[0-9]+$ ]] ||
    [[ ! ${latest_failed:-} =~ ^[0-9]+$ ]] ||
    [[ ! ${pending:-} =~ ^[0-9]+$ ]] ||
    [[ ! ${model_ready:-} =~ ^[0-9]+$ ]] ||
    [[ ! ${top_models:-} =~ ^[0-9]+$ ]]; then
    echo "DOCKING_POLL_RETRY $(date -Is) detail=$(printf '%q' "$status")" >&2
    sleep "$POLL_SECONDS"
    continue
  fi
  echo "DOCKING_STATUS $(date -Is) complete=$complete alive=$alive remote_pid=$remote_pid expected=$expected unique_started=$unique_started latest_success=$latest_success latest_failed=$latest_failed pending=$pending model_ready=$model_ready top_models=$top_models"
  if (( complete == 1 )); then
    if (( expected != EXPECTED_CANDIDATES || latest_success != EXPECTED_CANDIDATES || latest_failed != 0 || pending != 0 || model_ready != EXPECTED_CANDIDATES )); then
      echo "DOCKING_COMPLETE_CONTRACT_FAILED expected=$expected latest_success=$latest_success latest_failed=$latest_failed pending=$pending model_ready=$model_ready" >&2
      exit 6
    fi
    break
  fi
  if (( alive == 0 )); then
    if (( expected == EXPECTED_CANDIDATES && latest_success == EXPECTED_CANDIDATES && latest_failed == 0 && pending == 0 && model_ready == EXPECTED_CANDIDATES )); then
      "$SSH_COMMAND" "$NODE_HOST" "ROOT='$REMOTE_ROOT'; tmp=\"\$ROOT/.docking.complete.tmp.\$\$\"; printf 'RECOVERED_COMPLETION_ATTESTATION %s latest_success=$latest_success model_ready=$model_ready\\n' \"\$(date -Is)\" >\"\$tmp\"; mv -f \"\$tmp\" \"\$ROOT/docking.complete\""
      echo "DOCKING_RECOVERED_COMPLETION_ATTESTED remote_pid=$remote_pid latest_success=$latest_success model_ready=$model_ready"
      break
    fi
    echo "DOCKING_CONTROLLER_DIED_WITHOUT_COMPLETE remote_pid=$remote_pid latest_success=$latest_success latest_failed=$latest_failed pending=$pending model_ready=$model_ready" >&2
    exit 5
  fi
  sleep "$POLL_SECONDS"
done

echo "POSTPROCESS_START $(date -Is)"
bash "$POSTPROCESS_SCRIPT"
echo "POSTPROCESS_COMPLETE $(date -Is)"
