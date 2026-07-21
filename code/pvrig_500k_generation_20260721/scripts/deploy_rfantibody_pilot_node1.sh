#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_ROOT=/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712
RUN_ROOT=/data1/qlyu/projects/pvrig_500k_rfantibody_pilot_v1_20260721
RF_PYTHON=/data/qlyu/anaconda3/envs/rfdiffusion2/bin/python

test -d "$SOURCE_ROOT/scripts"
test -d "$SOURCE_ROOT/inputs"
test -x /data/qlyu/software/RFantibody/bin/rfdiffusion
test -x /data/qlyu/software/RFantibody/bin/proteinmpnn
test -x "$RF_PYTHON"

mkdir -p "$RUN_ROOT"/{config,inputs,logs,status,generation,data,scripts}
if [[ ! -s "$RUN_ROOT/status/DEPLOYED.json" ]]; then
  cp -a "$SOURCE_ROOT/scripts/." "$RUN_ROOT/scripts/"
  cp -a "$SOURCE_ROOT/inputs/." "$RUN_ROOT/inputs/"
fi

"$RF_PYTHON" "$RUN_ROOT/scripts/create_generation_arms.py" \
  --out "$RUN_ROOT/config/generation_arms.tsv" \
  --summary "$RUN_ROOT/config/generation_design_summary.json" \
  --backbones-per-arm 24 \
  --sequences-per-backbone 8

python3 - "$RUN_ROOT" <<'PY'
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
source = root / "config" / "generation_arms.tsv"
target = root / "config" / "generation_arms_primary.tsv"
with source.open(newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
primary = [row for row in rows if row["scaffold_lane"] == "primary_vhhified"]
with target.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
    writer.writeheader()
    writer.writerows(primary)
if len(primary) != 36:
    raise SystemExit(f"expected 36 primary arms, found {len(primary)}")
expected = sum(int(row["target_backbones"]) * int(row["seqs_per_backbone"]) for row in primary)
if expected != 6912:
    raise SystemExit(f"expected 6912 raw sequences, found {expected}")
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
policy = {
    "schema_version": 1,
    "campaign_id": root.name,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "run_root": str(root),
    "source_pipeline": "/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712",
    "primary_arm_count": len(primary),
    "backbones_per_arm": 24,
    "sequences_per_backbone": 8,
    "raw_sequence_target": expected,
    "exact_unique_freeze_target": 5000,
    "gpu_ids": [1, 2, 3, 4, 5, 7],
    "omp_threads_per_lane": 1,
    "arm_table_sha256": digest(target),
    "claim_boundary": "epitope-conditioned computational generation; not binding or blocking evidence",
}
(root / "config" / "generation_execution_policy.json").write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n")
deploy = {
    "status": "DEPLOYED",
    "run_root": str(root),
    "arm_table": str(target),
    "arm_table_sha256": digest(target),
    "raw_sequence_target": expected,
    "freeze_target": 5000,
}
(root / "status" / "DEPLOYED.json").write_text(json.dumps(deploy, indent=2, sort_keys=True) + "\n")
PY

cat >"$RUN_ROOT/scripts/run_pilot_controller.sh" <<'EOS'
#!/usr/bin/env bash
set -Eeuo pipefail
RUN_ROOT=/data1/qlyu/projects/pvrig_500k_rfantibody_pilot_v1_20260721
RF_PYTHON=/data/qlyu/anaconda3/envs/rfdiffusion2/bin/python
ARM_TABLE="$RUN_ROOT/config/generation_arms_primary.tsv"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1

write_state() {
  python3 - "$RUN_ROOT" "$1" "${2:-}" <<'PY'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
root=Path(sys.argv[1])
payload={"state":sys.argv[2],"message":sys.argv[3],"pid":os.getppid(),"updated_at":datetime.now(timezone.utc).isoformat()}
(root/"status"/"controller.json").write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
PY
}
fail_state() { rc=$?; write_state FAILED "return_code=$rc" || true; exit "$rc"; }
trap fail_state ERR

write_state SMOKE "four-arm RFdiffusion ProteinMPNN and fast-QC smoke"
if [[ ! -s "$RUN_ROOT/smoke_v1/status/smoke.complete" ]]; then
  RUN_ROOT="$RUN_ROOT" SMOKE_ROOT="$RUN_ROOT/smoke_v1" \
    bash "$RUN_ROOT/scripts/run_generation_smoke.sh"
fi

write_state GENERATING "36 primary arms; 24 backbones x 8 sequences; GPUs 1,2,3,4,5,7"
RUN_ROOT="$RUN_ROOT" ARM_TABLE="$ARM_TABLE" GPU_IDS=1,2,3,4,5,7 \
  MAX_LOAD1=110 GPU_MEMORY_GATE_MB=12000 \
  bash "$RUN_ROOT/scripts/launch_generation_multi_gpu.sh"

write_state FREEZING "balanced exact-unique 5000-candidate RFantibody cohort"
"$RF_PYTHON" "$RUN_ROOT/scripts/collect_and_freeze_candidates.py" \
  --run-root "$RUN_ROOT" \
  --arms-path "$ARM_TABLE" \
  --target 5000 \
  >"$RUN_ROOT/logs/collect_and_freeze_candidates.log" 2>&1

write_state COMPLETE "5000 exact-unique RFantibody candidates frozen"
date -Is > "$RUN_ROOT/status/controller.complete"
trap - ERR
EOS
chmod +x "$RUN_ROOT/scripts/run_pilot_controller.sh"

if [[ -s "$RUN_ROOT/status/controller.pid" ]] && kill -0 "$(cat "$RUN_ROOT/status/controller.pid")" 2>/dev/null; then
  echo "controller already running pid=$(cat "$RUN_ROOT/status/controller.pid")"
else
  nohup "$RUN_ROOT/scripts/run_pilot_controller.sh" >"$RUN_ROOT/logs/controller.log" 2>&1 &
  echo $! > "$RUN_ROOT/status/controller.pid"
fi

cat "$RUN_ROOT/status/DEPLOYED.json"
echo "controller_pid=$(cat "$RUN_ROOT/status/controller.pid")"
