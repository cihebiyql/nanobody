#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712}
MAX_LOAD1=${MAX_LOAD1:-240}
POLL_SECONDS=${POLL_SECONDS:-120}
MIN_SUCCESS=${MIN_SUCCESS:-1000}
POSTPROCESS_MAX_PARALLEL=${POSTPROCESS_MAX_PARALLEL:-2}
PYTHON=${PYTHON:-/data/qlyu/anaconda3/envs/boltz/bin/python}
mkdir -p "$RUN_ROOT"/{logs,status,data,reports}

exec 9>"$RUN_ROOT/status/postprocess_controller.lock"
if ! flock -n 9; then
  echo "Postprocess controller is already running"
  exit 0
fi

write_state() {
  local state=$1 message=${2:-}
  python3 - "$RUN_ROOT/status/postprocess_controller.json" "$state" "$message" <<'PY'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1])
payload = {"state": sys.argv[2], "message": sys.argv[3], "pid": os.getppid(), "updated_at": datetime.now(timezone.utc).isoformat()}
tmp = path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
tmp.replace(path)
PY
}

while [[ ! -s "$RUN_ROOT/status/downstream_controller.raw_docking_complete" ]]; do
  write_state waiting_for_docking "waiting for at least 1000 completed HADDOCK candidates"
  sleep "$POLL_SECONDS"
done

while true; do
  load1=$(cut -d' ' -f1 /proc/loadavg)
  if awk -v current="$load1" -v limit="$MAX_LOAD1" 'BEGIN { exit !(current < limit) }'; then break; fi
  echo "POSTPROCESS_LOAD_WAIT load1=$load1 threshold=$MAX_LOAD1 time=$(date -Is)"
  sleep "$POLL_SECONDS"
done

MANIFEST="$RUN_ROOT/docking/manifests/docking_candidates.tsv"
SMOKE_CID=$(python3 - "$RUN_ROOT" "$MANIFEST" <<'PY'
import csv, json, sys
from pathlib import Path
root=Path(sys.argv[1])
for row in csv.DictReader(open(sys.argv[2], newline=""), delimiter="\t"):
    state=root / "docking/state/haddock" / f"{row['candidate_id']}.json"
    try: status=json.load(open(state)).get("status")
    except Exception: status=""
    if status == "success":
        print(row["candidate_id"]); break
PY
)
[[ -n "$SMOKE_CID" ]] || { write_state failed "no successful HADDOCK candidate for postprocess smoke"; exit 2; }

if [[ ! -s "$RUN_ROOT/docking/postprocessed/$SMOKE_CID/reports/${SMOKE_CID}_8x6b_9e6y_consensus.csv" ]]; then
  write_state postprocess_smoke "scoring one candidate against 8X6B and 9E6Y references"
  IFS=$'\t' read -r _ _ _ _ c1s c1e c2s c2e c3s c3e _ < <(awk -F $'\t' -v cid="$SMOKE_CID" 'NR==1 || $1==cid {if (NR==1) next; print; exit}' "$MANIFEST")
  "$PYTHON" "$RUN_ROOT/scripts/postprocess_candidate_dual_baseline.py" \
    --run-root "$RUN_ROOT" --candidate-id "$SMOKE_CID" \
    --cdr1 "$c1s-$c1e" --cdr2 "$c2s-$c2e" --cdr3 "$c3s-$c3e" --top-n 4 \
    >"$RUN_ROOT/logs/postprocess_smoke.log" 2>&1
fi

write_state postprocess_full "running load-aware dual-reference scoring"
"$PYTHON" "$RUN_ROOT/scripts/run_postprocess_load_aware.py" \
  --run-root "$RUN_ROOT" --python "$PYTHON" --max-load1 "$MAX_LOAD1" \
  --cores-per-job 2 --max-parallel "$POSTPROCESS_MAX_PARALLEL" --poll-seconds "$POLL_SECONDS" --max-attempts 3 \
  >"$RUN_ROOT/logs/postprocess_load_aware.log" 2>&1

"$PYTHON" "$RUN_ROOT/scripts/aggregate_dual_baseline.py" --run-root "$RUN_ROOT" \
  >"$RUN_ROOT/logs/aggregate_dual_baseline.log" 2>&1
success=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["postprocess_success_candidates"])' "$RUN_ROOT/data/dual_baseline_summary.json")
if [[ "$success" -lt "$MIN_SUCCESS" ]]; then
  write_state incomplete "dual-baseline successes=$success below $MIN_SUCCESS"
  exit 3
fi

write_state final_dataset "building leakage-safe final training tables"
"$PYTHON" "$RUN_ROOT/scripts/build_training_dataset.py" \
  --input-dir "$RUN_ROOT/data" --output-dir "$RUN_ROOT/data/training_dataset" \
  --haddock-root "$RUN_ROOT/docking/haddock" --mode final \
  >"$RUN_ROOT/logs/build_training_dataset_final.log" 2>&1

"$PYTHON" "$RUN_ROOT/scripts/write_final_report.py" --run-root "$RUN_ROOT" \
  >"$RUN_ROOT/logs/write_final_report.log" 2>&1

write_state complete "raw docking and dual-reference training dataset complete"
date -Is > "$RUN_ROOT/status/postprocess_controller.complete"
