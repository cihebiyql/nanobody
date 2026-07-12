#!/usr/bin/env bash
# Continue the formal PVRIG teacher pipeline after RFantibody generation closes.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SSH_COMMAND=${SSH_COMMAND:-ssh.exe}
NODE_HOST=${NODE_HOST:-node1}
REMOTE_BASE=${REMOTE_BASE:-/data/qlyu/projects/pvrig_teacher_formal_v1_20260712}
PRODUCTION="$REMOTE_BASE/rfantibody_generation/production"
REMOTE_TEACHER="$REMOTE_BASE/teacher500_docking"
POLL_SECONDS=${POLL_SECONDS:-120}
LOG=${LOG:-$ROOT/logs/pvrig_formal_teacher_pipeline_controller.log}
LOCK=${LOCK:-/tmp/pvrig_formal_teacher_pipeline_controller.lock}

mkdir -p "$(dirname "$LOG")"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "Another formal teacher controller already owns $LOCK" >&2
  exit 4
fi
exec > >(tee -a "$LOG") 2>&1

echo "CONTROLLER_START $(date -Is) production=$NODE_HOST:$PRODUCTION"
while true; do
  read -r complete failed workers < <(
    "$SSH_COMMAND" "$NODE_HOST" "ROOT='$PRODUCTION'; \
      printf '%s ' \"\$(find \"\$ROOT/tasks\" -name complete.json | wc -l)\"; \
      printf '%s ' \"\$(find \"\$ROOT/tasks\" -name failed.json | wc -l)\"; \
      pgrep -af 'run_worker[^ ]*\.sh' | grep -v pgrep | wc -l"
  )
  echo "GENERATION_STATUS $(date -Is) complete=$complete failed=$failed workers=$workers"
  if (( failed > 0 )); then
    echo "CONTROLLER_ABORT_GENERATION_FAILURE failed=$failed" >&2
    exit 5
  fi
  if (( complete == 240 )); then
    break
  fi
  if (( complete > 240 )); then
    echo "CONTROLLER_ABORT_INVALID_COMPLETE_COUNT complete=$complete" >&2
    exit 6
  fi
  sleep "$POLL_SECONDS"
done

while true; do
  workers=$("$SSH_COMMAND" "$NODE_HOST" "pgrep -af 'run_worker[^ ]*\.sh' | grep -v pgrep | wc -l")
  echo "WORKER_DRAIN_STATUS $(date -Is) workers=$workers"
  (( workers == 0 )) && break
  sleep 30
done

echo "FINALIZE_START $(date -Is)"
bash "$ROOT/src/run_pvrig_formal_teacher500_finalize.sh"
echo "FINALIZE_COMPLETE $(date -Is)"

echo "TEACHER500_NODE1_START $(date -Is)"
"$SSH_COMMAND" "$NODE_HOST" "set -euo pipefail; cd '$REMOTE_TEACHER'; \
  if test -f controller.pid && kill -0 \"\$(cat controller.pid)\" 2>/dev/null; then \
    echo TEACHER500_CONTROLLER_ALREADY_RUNNING pid=\$(cat controller.pid); \
  else \
    setsid bash run_teacher500_controller.sh all > controller.launch.log 2>&1 < /dev/null & \
    echo \$! > controller.pid; \
    echo TEACHER500_CONTROLLER_STARTED pid=\$!; \
  fi"
echo "CONTROLLER_HANDOFF_COMPLETE $(date -Is) remote=$NODE_HOST:$REMOTE_TEACHER"
