#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST=${REMOTE_HOST:-node1}
REMOTE_ROOT=${REMOTE_ROOT:-/data/qlyu/projects/pvrig_rfantibody_validation_20260712}

ssh.exe "$REMOTE_HOST" "REMOTE_ROOT='$REMOTE_ROOT' bash -s" <<'REMOTE'
set -euo pipefail
pid_file=$REMOTE_ROOT/manifests/sequence_qc.pid
log_file=$REMOTE_ROOT/logs/sequence_qc.log
out=$REMOTE_ROOT/qc/cascade

if [[ -s "$pid_file" ]]; then
  pid=$(cat "$pid_file")
  if kill -0 "$pid" 2>/dev/null; then
    echo "status=RUNNING pid=$pid"
  else
    echo "status=NOT_RUNNING last_pid=$pid"
  fi
else
  echo "status=NOT_STARTED"
fi
echo "loadavg=$(cat /proc/loadavg)"
[[ -f "$out/cascade_state.json" ]] && cat "$out/cascade_state.json"
echo "--- recent log ---"
[[ -f "$log_file" ]] && tail -n 40 "$log_file" || true
echo "--- output files ---"
find "$out" -maxdepth 1 -type f -printf '%f %s bytes\n' 2>/dev/null | sort || true
REMOTE

