#!/usr/bin/env bash
set -Eeuo pipefail

UPSTREAM_ROOT=${UPSTREAM_ROOT:-/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714}
NEW_ROOT=${NEW_ROOT:-/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715}
PYTHON_BIN=${PYTHON_BIN:-/data/qlyu/anaconda3/envs/haddock3/bin/python}
HADDOCK3_BIN=${HADDOCK3_BIN:-/data/qlyu/anaconda3/envs/haddock3/bin/haddock3}
SCRATCH_ROOT=${SCRATCH_ROOT:-/tmp/pvrig_v4d_fullqc290_haddock}
MAX_PARALLEL=${MAX_PARALLEL:-12}
POLL_SECONDS=${POLL_SECONDS:-60}
LOG_FILE="$NEW_ROOT/logs/chained_launch_watcher.log"
LOCK_FILE="$NEW_ROOT/status/chained_launch_watcher.lock"
PID_FILE="$NEW_ROOT/status/chained_launch_watcher.pid"
STATUS_FILE="$NEW_ROOT/status/chained_launch.json"

mkdir -p "$NEW_ROOT/logs" "$NEW_ROOT/status"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "another V4-D chained-launch watcher holds $LOCK_FILE" >&2
  exit 75
fi
echo $$ >"$PID_FILE"

log() {
  printf '%s %s\n' "$(date --iso-8601=seconds)" "$*" | tee -a "$LOG_FILE"
}

write_status() {
  local status=$1
  local reason=$2
  local upstream_evaluator=${3:-}
  STATUS_VALUE="$status" REASON_VALUE="$reason" EVALUATOR_VALUE="$upstream_evaluator" \
    UPSTREAM_VALUE="$UPSTREAM_ROOT" NEW_VALUE="$NEW_ROOT" \
    "$PYTHON_BIN" - "$STATUS_FILE" <<'PY'
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

target = Path(sys.argv[1])
evaluator = Path(os.environ["EVALUATOR_VALUE"]) if os.environ["EVALUATOR_VALUE"] else None
payload = {
    "status": os.environ["STATUS_VALUE"],
    "reason": os.environ["REASON_VALUE"],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "upstream_root": os.environ["UPSTREAM_VALUE"],
    "new_root": os.environ["NEW_VALUE"],
    "upstream_evaluator_path": str(evaluator) if evaluator else "",
    "upstream_evaluator_sha256": (
        hashlib.sha256(evaluator.read_bytes()).hexdigest()
        if evaluator and evaluator.is_file()
        else ""
    ),
}
target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

upstream_state() {
  "$PYTHON_BIN" - "$UPSTREAM_ROOT/status/summary.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    print("WAIT 1050 0 missing_status_summary")
    raise SystemExit(0)
payload = json.loads(path.read_text())
counts = payload.get("counts")
if not isinstance(counts, dict):
    raise SystemExit("upstream_status_counts_missing")
known = ("SUCCESS", "FAILED_MAX_ATTEMPTS", "RUNNING", "PENDING", "QUEUED", "FAILED")
values = {name: int(counts.get(name, 0) or 0) for name in known}
if sum(values.values()) != 1050:
    raise SystemExit(f"upstream_status_total_not_1050:{values}")
nonterminal = sum(values[name] for name in ("RUNNING", "PENDING", "QUEUED", "FAILED"))
terminal = values["SUCCESS"] + values["FAILED_MAX_ATTEMPTS"]
state = "TERMINAL" if nonterminal == 0 and terminal == 1050 else "WAIT"
print(state, nonterminal, terminal, json.dumps(values, sort_keys=True))
PY
}

evaluator_state() {
  "$PYTHON_BIN" - "$UPSTREAM_ROOT/reports/EVALUATOR_STABLE.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    print("WAIT evaluator_missing")
    raise SystemExit(0)
payload = json.loads(path.read_text())
gates = payload.get("gates")
terminal = gates.get("all_jobs_terminal", {}) if isinstance(gates, dict) else {}
if int(payload.get("job_count", 0) or 0) != 1050 or terminal.get("status") not in {"PASS", "FAIL"}:
    print("WAIT evaluator_not_fresh_terminal")
    raise SystemExit(0)
all_gates_pass = isinstance(gates, dict) and gates and all(
    isinstance(value, dict) and value.get("status") == "PASS" for value in gates.values()
)
ready = (
    payload.get("status") == "PASS"
    and payload.get("unlockable") is True
    and payload.get("evidence_mode") == "production_pose_backed"
    and all_gates_pass
)
if ready:
    print("READY evaluator_pass")
else:
    reasons = [name for name, value in (gates or {}).items() if value.get("status") != "PASS"]
    print("BLOCKED evaluator_not_releasable:" + ",".join(sorted(reasons)))
PY
}

log "watcher_started upstream=$UPSTREAM_ROOT new=$NEW_ROOT max_parallel=$MAX_PARALLEL"
write_status "WAITING_UPSTREAM_TERMINAL" "V4-C campaign still running"

while true; do
  state=$(upstream_state)
  log "upstream_state=$state"
  if [[ "$state" != TERMINAL* ]]; then
    sleep "$POLL_SECONDS"
    continue
  fi
  eval_state=$(evaluator_state)
  log "evaluator_state=$eval_state"
  if [[ "$eval_state" == WAIT* ]]; then
    sleep "$POLL_SECONDS"
    continue
  fi
  if [[ "$eval_state" == BLOCKED* ]]; then
    write_status "BLOCKED_UPSTREAM_EVALUATOR" "$eval_state" "$UPSTREAM_ROOT/reports/EVALUATOR_STABLE.json"
    exit 2
  fi
  break
done

cd "$NEW_ROOT"
sha256sum -c <<'EOF'
adf5d2efcdcb4d6b187dff990a64e126061c8765c6ad65350ad9484860447e6b  governance/phase2_v4_d_preregistration.json
767117dc2c506cfdfc83fce8e12931514d268941348d69a9abbda5a6500bdd24  PROTOCOL_CORE_LOCK.json
11a392c4f0ae1b9eea1c563caf409798532eb6a73f3dc6b6cb5a4e8539ff9ab3  PROTOCOL_LOCK.json
96fec07a5535615f50bff40ac48bb323a94213e06a7b12726ae5b4b2d1161737  manifests/docking_jobs.tsv
c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd  inputs/candidates_290.tsv
ebc07ccb7ba36dee84714fbf27911e82b560d1cc184a8d45e054d8577f1d70f0  inputs/candidate_monomers_manifest.tsv
c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd  inputs/fullqc290_split_manifest.tsv
e0fa1b2558e8dd1f6c934f709822706beb26ae69e4859fad3bdc4d5abaa3df37  inputs/fullqc290_split_audit.json
EOF

PVRIG_PROJECT_ROOT="$NEW_ROOT" "$PYTHON_BIN" scripts/validate_protocol.py --expected-total-jobs 2022
if find status/jobs -type f -print -quit | grep -q . || find results -type f -print -quit | grep -q .; then
  write_status "BLOCKED_DIRTY_PRELAUNCH" "V4-D status/jobs or results is not empty"
  exit 3
fi

mkdir -p "$SCRATCH_ROOT"
test -w "$SCRATCH_ROOT"
case "$(stat -f -c %T "$SCRATCH_ROOT")" in
  nfs*)
    write_status "BLOCKED_NFS_SCRATCH" "$SCRATCH_ROOT is on NFS"
    exit 4
    ;;
esac

if test -s status/smoke_then_full.pid && kill -0 "$(cat status/smoke_then_full.pid)" 2>/dev/null; then
  write_status "ALREADY_RUNNING" "existing smoke_then_full process is alive" "$UPSTREAM_ROOT/reports/EVALUATOR_STABLE.json"
  exit 0
fi

write_status "STARTING" "upstream evaluator passed; launching frozen V4-D" "$UPSTREAM_ROOT/reports/EVALUATOR_STABLE.json"
nohup env \
  PVRIG_PROJECT_ROOT="$NEW_ROOT" \
  HADDOCK3="$HADDOCK3_BIN" \
  PATH="/data/qlyu/anaconda3/envs/haddock3/bin:$PATH" \
  PVRIG_LOCAL_SCRATCH_ROOT="$SCRATCH_ROOT" \
  PVRIG_MAX_PARALLEL="$MAX_PARALLEL" \
  "$PYTHON_BIN" scripts/orchestrate_smoke_then_full.py \
  >logs/smoke_then_full.log 2>&1 < /dev/null &
child=$!
echo "$child" >status/smoke_then_full.pid
write_status "LAUNCHED" "V4-D smoke-then-full started with pid=$child" "$UPSTREAM_ROOT/reports/EVALUATOR_STABLE.json"
log "launched_pid=$child"
