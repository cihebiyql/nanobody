#!/usr/bin/env bash
set -u

DEPLOY=$(cd "$(dirname "$0")" && pwd)
BASE=${PVRIG_TOP7500_MONITOR_ROOT:-/mnt/d/work/抗体/node1/pvrig_top7500_25k_bxcpu_incremental_spool_20260722/monitor}
INTERVAL=${PVRIG_TOP7500_MONITOR_INTERVAL_SECONDS:-1800}
NODE1_CONTROL=/data1/qlyu/projects/pvrig_priority_top7500_dualreceptor_multiseed_docking_results_v1_20260722/run_control
SSH=/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe
STORAGE_PAUSE="$BASE/NODE1_STORAGE_PAUSE"
WLAN_PROFILE=${PVRIG_NODE1_WLAN_PROFILE:-ECUST-dorm.1x}
mkdir -p "$BASE"

ensure_node1_wlan() {
    local state
    state=$(powershell.exe -NoProfile -Command '(Get-NetAdapter -Name "WLAN" -ErrorAction SilentlyContinue).Status' 2>/dev/null | tr -d '\r' | tail -1)
    if [[ "$state" != Up ]]; then
        printf '%s WLAN is %s; requesting reconnect to %s\n' "$(date -Is)" "${state:-UNKNOWN}" "$WLAN_PROFILE"
        cmd.exe /c "netsh wlan connect name=\"$WLAN_PROFILE\" ssid=\"$WLAN_PROFILE\" interface=\"WLAN\"" >/dev/null 2>&1 || true
        sleep 10
    fi
}

storage_alert_present() {
    [[ -f "$BASE/MONITOR_STATUS.json" ]] || return 1
    python3 - "$BASE/MONITOR_STATUS.json" <<'PY'
import json, sys
try:
    alerts=set(json.load(open(sys.argv[1])).get("alerts", []))
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if any(x.startswith("NODE1_FREE_SPACE_BELOW_") for x in alerts) else 1)
PY
}

refresh_storage_pause() {
    [[ -f "$STORAGE_PAUSE" ]] || return 0
    if [[ -f "$BASE/MONITOR_STATUS.json" ]] && ! storage_alert_present; then
        if ! python3 - "$BASE/MONITOR_STATUS.json" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
alerts=set(d.get("alerts", []))
p=d.get("storage_projection", {})
free=int(d.get("node1", {}).get("free_bytes", 0))
required=int(p.get("projected_required_free_bytes", 0))
safe=("NODE1_CHECK_FAILED" not in alerts and required > 0 and free >= required)
raise SystemExit(0 if safe else 1)
PY
        then
            return 0
        fi
        rm -f "$STORAGE_PAUSE"
        printf '%s Node1 storage recovered; relay pause cleared\n' "$(date -Is)"
    fi
}

restart_stale_relays() {
    local i session status stale=0
    if [[ -f "$STORAGE_PAUSE" ]]; then
        printf '%s relay restart suppressed by Node1 storage pause\n' "$(date -Is)"
        return 0
    fi
    for i in 00 01 02 03; do
        session="pvrig-top7500-result-sync-$i"
        status="${BASE%/monitor}/shard$i/state/SYNC_STATUS.shard${i}of04.json"
        if ! tmux has-session -t "$session" 2>/dev/null; then
            stale=1
        elif [[ ! -f "$status" ]] || find "$status" -mmin +20 -print -quit | grep -q .; then
            printf '%s stale relay session restarted: %s\n' "$(date -Is)" "$session"
            tmux kill-session -t "$session" 2>/dev/null || true
            stale=1
        fi
    done
    if [[ "$stale" == 1 ]]; then
        PVRIG_BXCPU_SYNC_SHARDS=4 \
        PVRIG_BXCPU_SYNC_BATCH_SIZE=20 \
        PVRIG_BXCPU_SYNC_STABLE_AGE_SECONDS=60 \
        PVRIG_BXCPU_SYNC_POLL_SECONDS=5 \
            "$DEPLOY/start_top7500_results_sync_sharded.sh"
    fi
}

while :; do
    ensure_node1_wlan
    refresh_storage_pause
    restart_stale_relays
    python3 "$DEPLOY/collect_top7500_failed_evidence.py" || true
    python3 "$DEPLOY/healthcheck_top7500_live.py"
    rc=$?
    if storage_alert_present; then
        printf '%s Node1 storage floor reached; pausing relay sessions\n' "$(date -Is)" | tee "$STORAGE_PAUSE"
        for i in 00 01 02 03; do
            tmux kill-session -t "pvrig-top7500-result-sync-$i" 2>/dev/null || true
        done
    fi
    if [[ -f "$BASE/MONITOR_STATUS.json" ]]; then
        "$SSH" -o BatchMode=yes -o ConnectTimeout=20 node1 "mkdir -p '$NODE1_CONTROL'" >/dev/null 2>&1 && \
            rsync -a -e "$SSH" "$BASE/MONITOR_STATUS.json" \
                "node1:$NODE1_CONTROL/MONITOR_STATUS.json" || true
    fi
    printf '%s healthcheck_rc=%s\n' "$(date -Is)" "$rc"
    [[ "${PVRIG_MONITOR_ONCE:-0}" == 1 ]] && exit "$rc"
    sleep "$INTERVAL"
done
