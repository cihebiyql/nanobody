#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712}
MAX_LOAD1=${MAX_LOAD1:-240}
GPU_MEMORY_GATE_MB=${GPU_MEMORY_GATE_MB:-12000}
POLL_SECONDS=${POLL_SECONDS:-60}
export MAX_LOAD1 GPU_MEMORY_GATE_MB
mkdir -p "$RUN_ROOT"/{logs,status}

exec 9>"$RUN_ROOT/status/generation_controller.lock"
if ! flock -n 9; then
  echo "Generation controller is already running"
  exit 0
fi

wait_for_capacity() {
  while true; do
    load1=$(cut -d' ' -f1 /proc/loadavg)
    busy=()
    for gpu in 1 2 3 5; do
      used=$(nvidia-smi --id="$gpu" --query-gpu=memory.used --format=csv,noheader,nounits | tr -d ' ')
      [[ "$used" -lt "$GPU_MEMORY_GATE_MB" ]] || busy+=("$gpu:$used")
    done
    if awk -v load="$load1" -v limit="$MAX_LOAD1" 'BEGIN { exit !(load < limit) }' && [[ ${#busy[@]} -eq 0 ]]; then
      return
    fi
    echo "CAPACITY_WAIT load1=$load1 max_load1=$MAX_LOAD1 busy_gpus=${busy[*]:-none} time=$(date -Is)"
    sleep "$POLL_SECONDS"
  done
}

write_state() {
  local state=$1 message=${2:-}
  python3 - "$RUN_ROOT/status/generation_controller.json" "$state" "$message" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "state": sys.argv[2],
    "message": sys.argv[3],
    "pid": os.getppid(),
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
tmp = path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
tmp.replace(path)
PY
}

write_state waiting_for_capacity "waiting before FR4 scaffold refreeze"
wait_for_capacity

write_state scaffold_refreeze "regenerating VTVSS scaffold artifacts"
/data/qlyu/anaconda3/envs/rfdiffusion2/bin/python "$RUN_ROOT/scripts/make_scaffold_variants.py" \
  --source "$RUN_ROOT/inputs/scaffolds/h-NbBCII10_source.pdb" \
  --output-dir "$RUN_ROOT/inputs/scaffolds" \
  --manifest "$RUN_ROOT/inputs/scaffolds/scaffold_manifest.json" \
  >"$RUN_ROOT/logs/scaffold_refreeze.log" 2>&1

python3 - "$RUN_ROOT/inputs/scaffolds/scaffold_manifest.json" "$RUN_ROOT/inputs/scaffolds/scaffolds.fasta" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.load(open(sys.argv[1]))
fasta = []
for row in manifest["variants"]:
    sequence = row["sequence"]
    if not sequence.endswith("VTVSS"):
        raise SystemExit(f"{row['scaffold_id']} lacks canonical VTVSS FR4")
    fasta.extend((f">{row['scaffold_id']}", sequence))
Path(sys.argv[2]).write_text("\n".join(fasta) + "\n", encoding="ascii")
PY
/data/qlyu/software/vhh_eval_tools/bin/vhh-eval \
  "$RUN_ROOT/inputs/scaffolds/scaffolds.fasta" \
  -o "$RUN_ROOT/inputs/scaffolds/scaffold_vhh_eval.tsv" \
  --json "$RUN_ROOT/inputs/scaffolds/scaffold_vhh_eval.json" \
  >"$RUN_ROOT/logs/scaffold_vhh_eval.log" 2>&1
python3 - "$RUN_ROOT/inputs/scaffolds/scaffold_vhh_eval.tsv" <<'PY'
import csv
import sys

rows = {row["id"]: row for row in csv.DictReader(open(sys.argv[1]), delimiter="\t")}
for scaffold_id in ("qrg", "ekg", "qkg"):
    row = rows[scaffold_id]
    if float(row["fr2_hallmark_score"]) != 1.0 or int(row["hydrophobic_5_count"]) != 0:
        raise SystemExit(f"{scaffold_id} failed scaffold preflight")
PY
date -Is > "$RUN_ROOT/status/scaffold_refreeze.complete"

if [[ ! -s "$RUN_ROOT/smoke_fr4/status/smoke.complete" ]]; then
  write_state smoke_fr4 "running RFdiffusion ProteinMPNN and sequence-QC smoke"
  SMOKE_ROOT="$RUN_ROOT/smoke_fr4" bash "$RUN_ROOT/scripts/run_generation_smoke.sh"
fi

write_state full_generation "running 48 arms on six GPU lanes"
bash "$RUN_ROOT/scripts/launch_generation_multi_gpu.sh"

write_state freeze_1024 "collecting and freezing the exact-unique docking cohort"
/data/qlyu/anaconda3/envs/rfdiffusion2/bin/python \
  "$RUN_ROOT/scripts/collect_and_freeze_candidates.py" --run-root "$RUN_ROOT" --target 1024 \
  >"$RUN_ROOT/logs/collect_and_freeze_candidates.log" 2>&1

write_state complete "1024-candidate generation cohort frozen"
date -Is > "$RUN_ROOT/status/generation_controller.complete"
