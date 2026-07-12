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
  "$SSH_COMMAND" "$NODE_HOST" "ROOT='$REMOTE_ROOT'; \
    complete=0; test -f \"\$ROOT/docking.complete\" && complete=1; \
    pid=0; test -s \"\$ROOT/controller.pid\" && pid=\$(cat \"\$ROOT/controller.pid\"); \
    alive=0; test \"\$pid\" != 0 && kill -0 \"\$pid\" 2>/dev/null && alive=1; \
    starts=\$(grep -Rh '^HADDOCK_START ' \"\$ROOT\"/shard_*/logs/run_node1_v2_5_pose_batch.*.log 2>/dev/null | wc -l); \
    success=\$(grep -Rh '^HADDOCK_EXIT .* rc=0 ' \"\$ROOT\"/shard_*/logs/run_node1_v2_5_pose_batch.*.log 2>/dev/null | wc -l); \
    failed=\$(grep -Rh '^HADDOCK_EXIT .* rc=[^0] ' \"\$ROOT\"/shard_*/logs/run_node1_v2_5_pose_batch.*.log 2>/dev/null | wc -l); \
    top_models=\$(find \"\$ROOT\" -path '*/6_seletopclusts/cluster_*_model_*.pdb*' -type f 2>/dev/null | wc -l); \
    printf '%s %s %s %s %s %s %s\\n' \"\$complete\" \"\$alive\" \"\$pid\" \"\$starts\" \"\$success\" \"\$failed\" \"\$top_models\""
}

echo "DOCKING_MONITOR_START $(date -Is) remote=$NODE_HOST:$REMOTE_ROOT"
while true; do
  if ! status=$(poll_remote_status 2>&1); then
    echo "DOCKING_POLL_RETRY $(date -Is) detail=$(printf '%q' "$status")" >&2
    sleep "$POLL_SECONDS"
    continue
  fi
  read -r complete alive remote_pid starts success failed top_models extra <<<"$status"
  if [[ -n ${extra:-} ]] ||
    [[ ! ${complete:-} =~ ^[01]$ ]] ||
    [[ ! ${alive:-} =~ ^[01]$ ]] ||
    [[ ! ${remote_pid:-} =~ ^[0-9]+$ ]] ||
    [[ ! ${starts:-} =~ ^[0-9]+$ ]] ||
    [[ ! ${success:-} =~ ^[0-9]+$ ]] ||
    [[ ! ${failed:-} =~ ^[0-9]+$ ]] ||
    [[ ! ${top_models:-} =~ ^[0-9]+$ ]]; then
    echo "DOCKING_POLL_RETRY $(date -Is) detail=$(printf '%q' "$status")" >&2
    sleep "$POLL_SECONDS"
    continue
  fi
  echo "DOCKING_STATUS $(date -Is) complete=$complete alive=$alive remote_pid=$remote_pid starts=$starts success=$success failed=$failed top_models=$top_models"
  if (( complete == 1 )); then
    if (( success != 500 || failed != 0 )); then
      echo "DOCKING_COMPLETE_CONTRACT_FAILED success=$success failed=$failed" >&2
      exit 6
    fi
    break
  fi
  if (( alive == 0 )); then
    echo "DOCKING_CONTROLLER_DIED_WITHOUT_COMPLETE remote_pid=$remote_pid success=$success failed=$failed" >&2
    exit 5
  fi
  sleep "$POLL_SECONDS"
done

echo "POSTPROCESS_START $(date -Is)"
bash "$POSTPROCESS_SCRIPT"
echo "POSTPROCESS_COMPLETE $(date -Is)"

