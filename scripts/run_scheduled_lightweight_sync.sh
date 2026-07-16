#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

LOG_FILE="${NANOBODY_SCHEDULED_SYNC_LOG:-$ROOT/.omx/logs/lightweight-sync-schedule.log}"
STATE_FILE="${NANOBODY_SCHEDULED_SYNC_STATE:-$ROOT/.omx/state/lightweight-sync-schedule.json}"
mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$STATE_FILE")"

started_at="$(date --iso-8601=seconds)"
rotate_limit=$((5 * 1024 * 1024))
if [[ -f "$LOG_FILE" ]] && (( $(stat -c '%s' "$LOG_FILE") > rotate_limit )); then
  tail -n 5000 "$LOG_FILE" > "$LOG_FILE.tmp"
  mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

set +e
{
  printf '\n[%s] scheduled lightweight sync started\n' "$started_at"
  "$ROOT/scripts/sync_lightweight_to_github.sh" \
    "Publish lightweight progress at the configured daily checkpoint"
} >> "$LOG_FILE" 2>&1
exit_code=$?
set -e

finished_at="$(date --iso-8601=seconds)"
head="$(git rev-parse HEAD 2>/dev/null || true)"
printf '[%s] scheduled lightweight sync finished rc=%s head=%s\n' \
  "$finished_at" "$exit_code" "$head" >> "$LOG_FILE"

python3 - "$STATE_FILE" "$started_at" "$finished_at" "$exit_code" "$head" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "last_sync_started_at": sys.argv[2],
    "last_sync_finished_at": sys.argv[3],
    "last_exit_code": int(sys.argv[4]),
    "last_head": sys.argv[5] or None,
    "schedule": "0 10,12,14,16,18,20,22 * * *",
    "timezone": "Asia/Shanghai",
}
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(tmp, path)
PY

exit "$exit_code"
