#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
ACTION="${1:-status}"
BEGIN_MARKER="# BEGIN NANOBODY_LIGHTWEIGHT_SYNC"
END_MARKER="# END NANOBODY_LIGHTWEIGHT_SYNC"
SCHEDULE="0 10,12,14,16,18,20,22 * * *"

install_schedule() {
  "$ROOT/scripts/lightweight_sync_daemon.sh" stop >/dev/null 2>&1 || true
  local tmp
  tmp="$(mktemp)"
  crontab -l 2>/dev/null | sed "/^$BEGIN_MARKER$/,/^$END_MARKER$/d" > "$tmp" || true
  {
    cat "$tmp"
    [[ ! -s "$tmp" ]] || printf '\n'
    printf '%s\n' "$BEGIN_MARKER"
    printf '%s cd %q && /usr/bin/bash ./scripts/run_scheduled_lightweight_sync.sh\n' "$SCHEDULE" "$ROOT"
    printf '%s\n' "$END_MARKER"
  } | crontab -
  rm -f "$tmp"
  echo "Installed daily lightweight sync schedule at 10,12,14,16,18,20,22:00 Asia/Shanghai."
}

remove_schedule() {
  local tmp
  tmp="$(mktemp)"
  crontab -l 2>/dev/null | sed "/^$BEGIN_MARKER$/,/^$END_MARKER$/d" > "$tmp" || true
  crontab "$tmp"
  rm -f "$tmp"
  echo "Removed the lightweight sync cron schedule."
}

show_status() {
  printf 'cron_service='; systemctl is-active cron 2>/dev/null || true
  printf 'timezone='; timedatectl show --property=Timezone --value 2>/dev/null || date +%Z
  printf '%s\n' '--- configured block ---'
  crontab -l 2>/dev/null | sed -n "/^$BEGIN_MARKER$/,/^$END_MARKER$/p" || true
  if [[ -f "$ROOT/.omx/state/lightweight-sync-schedule.json" ]]; then
    printf '%s\n' '--- latest scheduled run ---'
    cat "$ROOT/.omx/state/lightweight-sync-schedule.json"
  fi
}

case "$ACTION" in
  install) install_schedule ;;
  remove) remove_schedule ;;
  status) show_status ;;
  *)
    echo "Usage: $0 {install|remove|status}" >&2
    exit 2
    ;;
esac
