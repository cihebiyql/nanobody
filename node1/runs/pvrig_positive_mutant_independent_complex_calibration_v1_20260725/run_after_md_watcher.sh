#!/usr/bin/env bash
set -euo pipefail

ROOT="${CALIBRATION_ROOT:-/data/qlyu/projects/pvrig_positive_mutant_independent_complex_calibration_v1_20260725}"
MD_ROOT="${MD_ROOT:-/data/qlyu/projects/pvrig_top10_md_completion_v1_20260725}"
REFERENCE_ROOT="${REFERENCE_ROOT:-/data1/qlyu/projects/pvrig_priority_top7500_dualreceptor_multiseed_handoff_v3_20260722}"
GPUS="${CALIBRATION_GPUS:-1,2,3,4,6}"
STATUS="$ROOT/WATCHER_STATUS.json"
mkdir -p "$ROOT"
exec 9>"$ROOT/WATCHER.lock"
if ! flock -n 9; then
  echo "another calibration watcher owns the lock" >&2
  exit 75
fi

write_status() {
  local state="$1" detail="${2:-}"
  python3 - "$STATUS.tmp.$$" "$state" "$detail" <<'PY'
import json,os,sys
from datetime import datetime,timezone
json.dump(
    {
        "schema_version":"pvrig.control.independent_complex.watcher.v1",
        "state":sys.argv[2],
        "detail":sys.argv[3],
        "pid":os.getppid(),
        "updated_at":datetime.now(timezone.utc).isoformat(),
    },
    open(sys.argv[1],"w"),
    indent=2,
)
PY
  mv "$STATUS.tmp.$$" "$STATUS"
}

fail() {
  local rc=$?
  write_status FAILED "stage=${STAGE:-UNKNOWN};rc=$rc"
  exit "$rc"
}
trap fail ERR

STAGE=WAIT_MD
while [[ ! -s "$MD_ROOT/COMPLETE.json" ]]; do
  if [[ -s "$MD_ROOT/CONTROLLER_STATUS.json" ]] &&
     grep -q '"state": "FAILED"' "$MD_ROOT/CONTROLLER_STATUS.json"; then
    echo "upstream Top10 MD completion failed" >&2
    exit 70
  fi
  write_status WAITING_FOR_MD "$MD_ROOT/COMPLETE.json"
  sleep 60
done

STAGE=WAIT_GPUS
IFS=',' read -r -a gpu_ids <<<"$GPUS"
while true; do
  mapfile -t used < <(
    nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits |
    awk -F',' '{gsub(/ /,"",$1); gsub(/ /,"",$2); print $1" "$2}'
  )
  busy=0
  for gpu in "${gpu_ids[@]}"; do
    memory=999999
    for row in "${used[@]}"; do
      read -r index value <<<"$row"
      if [[ "$index" == "$gpu" ]]; then memory="$value"; break; fi
    done
    if (( memory >= 500 )); then busy=1; fi
  done
  (( busy == 0 )) && break
  write_status WAITING_FOR_GPUS "gpus=$GPUS;threshold_mib=500"
  sleep 60
done

STAGE=RAW_PREDICTIONS
write_status RUNNING_RAW_PREDICTIONS "gpus=$GPUS"
python3 "$ROOT/run_control_independent_complex_controller.py" \
  --project "$ROOT" --script-root "$ROOT" --gpus "$GPUS"
python3 - "$ROOT/STATUS.json" <<'PY'
import json,sys
x=json.load(open(sys.argv[1]))
assert x["state"]=="RAW_PREDICTIONS_COMPLETE"
assert x["boltz_pdb_count"]==9 and x["chai_cif_count"]==18
PY

STAGE=SCORING
write_status RUNNING_SCORING "$REFERENCE_ROOT"
python3 "$ROOT/score_control_independent_complex.py" \
  --project "$ROOT" --reference-root "$REFERENCE_ROOT"

STAGE=SUMMARIZE
write_status RUNNING_SUMMARY ""
python3 "$ROOT/summarize_control_calibration.py" --project "$ROOT"

STAGE=COMPLETE
python3 - "$ROOT" "$ROOT/COMPLETE.json.tmp.$$" <<'PY'
import hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
root=Path(sys.argv[1]); out=Path(sys.argv[2])
files=[
 root/"READY.json",
 root/"STATUS.json",
 root/"reports/CONTROL_INDEPENDENT_COMPLEX_POSE_SCORES.tsv",
 root/"reports/CONTROL_INDEPENDENT_COMPLEX_CANDIDATE_SUMMARY.tsv",
 root/"reports/CONTROL_INDEPENDENT_COMPLEX_SCORING_SUMMARY.json",
 root/"reports/CONTROL_MATCHED_MUTATION_DELTAS.tsv",
 root/"reports/CONTROL_CALIBRATION_RANGES.json",
]
assert all(path.is_file() for path in files)
json.dump(
 {
  "schema_version":"pvrig.control.independent_complex.complete.v1",
  "state":"COMPLETE",
  "created_at":datetime.now(timezone.utc).isoformat(),
  "candidate_count":9,
  "positive_count":5,
  "disruptive_control_count":4,
  "boltz_pose_count":9,
  "chai_pose_count":18,
  "hashes":{path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
  "claim_boundary":"Computational calibration only; not experimental affinity/blocking.",
 },
 open(out,"w"),
 indent=2,
)
PY
mv "$ROOT/COMPLETE.json.tmp.$$" "$ROOT/COMPLETE.json"
write_status COMPLETE "$ROOT/COMPLETE.json"
trap - ERR
