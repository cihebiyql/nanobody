#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

ACTION="${1:-status}"
SESSION="${NANOBODY_SYNC_TMUX_SESSION:-nanobody-lightweight-sync}"
INTERVAL="${NANOBODY_SYNC_INTERVAL:-120}"
LOG_FILE="${NANOBODY_SYNC_LOG:-$ROOT/.omx/logs/lightweight-sync-daemon.log}"
STATE_FILE="${NANOBODY_SYNC_STATE:-$ROOT/.omx/state/lightweight-sync-daemon.json}"
SYNC_SCRIPT="$ROOT/scripts/sync_lightweight_to_github.sh"

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$STATE_FILE")"

write_state() {
  local daemon_status="$1"
  local phase="$2"
  local started_at="$3"
  local finished_at="$4"
  local exit_code="$5"
  local head="$6"
  python3 - "$STATE_FILE" "$daemon_status" "$phase" "$started_at" "$finished_at" "$exit_code" "$head" "$INTERVAL" "$SESSION" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "daemon_status": sys.argv[2],
    "phase": sys.argv[3],
    "last_sync_started_at": sys.argv[4] or None,
    "last_sync_finished_at": sys.argv[5] or None,
    "last_exit_code": int(sys.argv[6]) if sys.argv[6] else None,
    "last_head": sys.argv[7] or None,
    "interval_seconds": int(sys.argv[8]),
    "tmux_session": sys.argv[9],
}
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(tmp, path)
PY
}

rotate_log_if_needed() {
  local max_bytes=$((5 * 1024 * 1024))
  if [[ -f "$LOG_FILE" ]] && (( $(stat -c '%s' "$LOG_FILE") > max_bytes )); then
    tail -n 5000 "$LOG_FILE" > "$LOG_FILE.tmp"
    mv "$LOG_FILE.tmp" "$LOG_FILE"
  fi
}

run_loop() {
  local started_at=""
  local finished_at=""
  local exit_code=""
  local head=""

  on_exit() {
    head="$(git rev-parse HEAD 2>/dev/null || true)"
    write_state "stopped" "idle" "$started_at" "$finished_at" "$exit_code" "$head"
  }
  trap 'exit 0' INT TERM HUP
  trap on_exit EXIT

  while true; do
    rotate_log_if_needed
    started_at="$(date --iso-8601=seconds)"
    head="$(git rev-parse HEAD 2>/dev/null || true)"
    write_state "running" "syncing" "$started_at" "" "" "$head"
    {
      printf '\n[%s] lightweight sync cycle started\n' "$started_at"
      set +e
      "$SYNC_SCRIPT" "Keep GitHub progress current with lightweight workspace updates"
      exit_code=$?
      set -e
      finished_at="$(date --iso-8601=seconds)"
      head="$(git rev-parse HEAD 2>/dev/null || true)"
      printf '[%s] lightweight sync cycle finished rc=%s head=%s\n' "$finished_at" "$exit_code" "$head"
    } >> "$LOG_FILE" 2>&1
    write_state "running" "idle" "$started_at" "$finished_at" "$exit_code" "$head"
    sleep "$INTERVAL"
  done
}

start_daemon() {
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Lightweight sync daemon is already running in tmux session: $SESSION"
    return 0
  fi
  local command
  printf -v command 'cd %q && NANOBODY_SYNC_INTERVAL=%q ./scripts/lightweight_sync_daemon.sh run' "$ROOT" "$INTERVAL"
  tmux new-session -d -s "$SESSION" "$command"
  echo "Started lightweight sync daemon in tmux session: $SESSION (interval=${INTERVAL}s)"
}

stop_daemon() {
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-session -t "$SESSION"
    echo "Stopped lightweight sync daemon: $SESSION"
  else
    echo "Lightweight sync daemon is not running: $SESSION"
  fi
}

show_status() {
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "tmux_status=running session=$SESSION"
  else
    echo "tmux_status=stopped session=$SESSION"
  fi
  if [[ -f "$STATE_FILE" ]]; then
    cat "$STATE_FILE"
  else
    echo "state_file_missing=$STATE_FILE"
  fi
  if [[ -f "$LOG_FILE" ]]; then
    echo "--- latest log ---"
    tail -n 20 "$LOG_FILE"
  fi
}

case "$ACTION" in
  run) run_loop ;;
  start) start_daemon ;;
  stop) stop_daemon ;;
  restart) stop_daemon; start_daemon ;;
  status) show_status ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|run}" >&2
    exit 2
    ;;
esac
