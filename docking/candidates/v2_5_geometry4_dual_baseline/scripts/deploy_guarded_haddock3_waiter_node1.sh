#!/usr/bin/env bash
set -euo pipefail

MODE=${1:---deploy}
if [[ "$MODE" != "--deploy" && "$MODE" != "--status" ]]; then
  echo "usage: $0 [--deploy|--status]" >&2
  exit 2
fi

SSH_BIN=${GEOMETRY4_SSH_BIN:-}
if [[ -z "$SSH_BIN" ]]; then
  if command -v ssh.exe >/dev/null 2>&1; then
    SSH_BIN=ssh.exe
  else
    SSH_BIN=ssh
  fi
fi

HOST=${GEOMETRY4_SSH_HOST:-node1}
MAX_LOAD1=${GEOMETRY4_MAX_LOAD1:-64}
POLL_SECONDS=${GEOMETRY4_POLL_SECONDS:-60}
MAX_WAIT_SECONDS=${GEOMETRY4_MAX_WAIT_SECONDS:-86400}
REMOTE_ROOT=/data/qlyu/projects/pvrig_v2_5_pose_batch
REMOTE_RUNNER="$REMOTE_ROOT/scripts/node1_guarded_haddock3_waiter.sh"
SESSION=pvrig_v25_geometry4_waiter
TMUX_SOCKET=pvrig_v25_geometry4
LOCAL_RUNNER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/node1_guarded_haddock3_waiter.sh"

show_status() {
  "$SSH_BIN" "$HOST" bash -s -- "$TMUX_SOCKET" "$SESSION" "$REMOTE_ROOT" <<'REMOTE'
set -euo pipefail
socket=$1
session=$2
root=$3
if tmux -L "$socket" has-session -t "$session" 2>/dev/null; then
  echo "WAITER_SESSION RUNNING socket=$socket session=$session"
else
  echo "WAITER_SESSION NOT_RUNNING socket=$socket session=$session"
fi
if [[ -s "$root/geometry4_waiter/status.env" ]]; then
  cat "$root/geometry4_waiter/status.env"
else
  echo "status=NOT_AVAILABLE"
fi
if [[ -s "$root/geometry4_waiter/latest_log.txt" ]]; then
  log=$(cat "$root/geometry4_waiter/latest_log.txt")
  echo "latest_log=$log"
  tail -n 20 "$log" 2>/dev/null || true
fi
REMOTE
}

if [[ "$MODE" == "--status" ]]; then
  show_status
  exit 0
fi

python3 - "$MAX_LOAD1" "$POLL_SECONDS" "$MAX_WAIT_SECONDS" <<'PY'
import math
import re
import sys

try:
    threshold = float(sys.argv[1])
except ValueError as exc:
    raise SystemExit("GEOMETRY4_MAX_LOAD1 must be numeric") from exc
if not math.isfinite(threshold) or threshold <= 0 or threshold > 64:
    raise SystemExit("GEOMETRY4_MAX_LOAD1 must be in (0, 64]")
if not re.fullmatch(r"[1-9][0-9]*", sys.argv[2]) or not re.fullmatch(r"[1-9][0-9]*", sys.argv[3]):
    raise SystemExit("GEOMETRY4_POLL_SECONDS and GEOMETRY4_MAX_WAIT_SECONDS must be positive base-10 integers")
poll_seconds = int(sys.argv[2])
max_wait_seconds = int(sys.argv[3])
if poll_seconds < 10:
    raise SystemExit("GEOMETRY4_POLL_SECONDS must be >= 10")
if max_wait_seconds < poll_seconds:
    raise SystemExit("GEOMETRY4_MAX_WAIT_SECONDS must be >= GEOMETRY4_POLL_SECONDS")
PY

test -s "$LOCAL_RUNNER" || { echo "missing local runner: $LOCAL_RUNNER" >&2; exit 3; }
local_sha=$(sha256sum "$LOCAL_RUNNER" | cut -d ' ' -f1)

"$SSH_BIN" "$HOST" "set -e; mkdir -p '$REMOTE_ROOT/scripts'; cat > '$REMOTE_RUNNER.tmp'; chmod 755 '$REMOTE_RUNNER.tmp'; mv '$REMOTE_RUNNER.tmp' '$REMOTE_RUNNER'" < "$LOCAL_RUNNER"
remote_sha=$("$SSH_BIN" "$HOST" "sha256sum '$REMOTE_RUNNER' | cut -d ' ' -f1" | tr -d '\r')
if [[ "$local_sha" != "$remote_sha" ]]; then
  echo "runner hash mismatch: local=$local_sha remote=$remote_sha" >&2
  exit 4
fi

"$SSH_BIN" "$HOST" bash -s -- "$TMUX_SOCKET" "$SESSION" "$REMOTE_ROOT" "$REMOTE_RUNNER" "$MAX_LOAD1" "$POLL_SECONDS" "$MAX_WAIT_SECONDS" <<'REMOTE'
set -euo pipefail
socket=$1
session=$2
root=$3
runner=$4
max_load1=$5
poll_seconds=$6
max_wait_seconds=$7

if tmux -L "$socket" has-session -t "$session" 2>/dev/null; then
  echo "WAITER_ALREADY_RUNNING socket=$socket session=$session"
  exit 0
fi

mkdir -p "$root/logs" "$root/geometry4_waiter"
log="$root/logs/geometry4_guarded_waiter_$(date +%Y%m%d_%H%M%S).log"
printf '%s\n' "$log" > "$root/geometry4_waiter/latest_log.txt"
printf -v launch_command \
  'GEOMETRY4_MAX_LOAD1=%q GEOMETRY4_POLL_SECONDS=%q GEOMETRY4_MAX_WAIT_SECONDS=%q bash %q >> %q 2>&1' \
  "$max_load1" "$poll_seconds" "$max_wait_seconds" "$runner" "$log"
tmux -L "$socket" new-session -d -s "$session" \
  "$launch_command"
echo "WAITER_DEPLOYED socket=$socket session=$session log=$log threshold=$max_load1 poll=$poll_seconds max_wait=$max_wait_seconds"
REMOTE

printf 'runner_sha256=%s\n' "$local_sha"
show_status
