#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:?RUN_ROOT is required}
RF_PYTHON=${RF_PYTHON:-/data/qlyu/anaconda3/envs/rfdiffusion2/bin/python}
MAIN_ARMS="$RUN_ROOT/config/generation_arms_primary.tsv"
SMOKE_ARMS="$RUN_ROOT/config/generation_arms_smoke21.tsv"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1

write_state() {
  python3 - "$RUN_ROOT" "$1" "${2:-}" <<'PY'
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
root=Path(sys.argv[1])
payload={'state':sys.argv[2], 'message':sys.argv[3], 'pid':os.getppid(),
         'updated_at':datetime.now(timezone.utc).isoformat()}
(root/'status/controller.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
PY
}
fail_state() { rc=$?; write_state FAILED "return_code=$rc" || true; exit "$rc"; }
trap fail_state ERR

write_state SMOKE_3X "7 GPUs x 3 workers; 21 arms; 1 backbone x 16 sequences"
RUN_ROOT="$RUN_ROOT" ARM_TABLE="$SMOKE_ARMS" \
  ARM_OUTPUT_BASE="$RUN_ROOT/smoke_3x/arms" STATUS_NAMESPACE=smoke_3x \
  GPU_IDS=1,2,3,4,5,6,7 WORKERS_PER_GPU=3 GPU_MEMORY_GATE_MB=20000 MAX_LOAD1=180 \
  bash "$RUN_ROOT/scripts/launch_rfantibody_multiworker_gpu.sh"

python3 - "$RUN_ROOT" <<'PY'
from pathlib import Path
root=Path(__import__('sys').argv[1])/'smoke_3x'/'arms'
arms=list(root.glob('*/complete.json'))
pdbs=list(root.glob('*/backbones/design_*.pdb'))
seqs=list(root.glob('*/sequences/design_*_dldesign_*.pdb'))
if (len(arms),len(pdbs),len(seqs)) != (21,21,336):
    raise SystemExit('3x smoke count mismatch arms={} backbones={} sequences={}'.format(len(arms),len(pdbs),len(seqs)))
PY

write_state GENERATING "RFantibody 75k raw target 90432; 36 arms; 157 backbones x 16 sequences; 7 GPUs x 3 workers"
RUN_ROOT="$RUN_ROOT" ARM_TABLE="$MAIN_ARMS" ARM_OUTPUT_BASE="$RUN_ROOT/generation/arms" \
  STATUS_NAMESPACE=generation GPU_IDS=1,2,3,4,5,6,7 WORKERS_PER_GPU=3 \
  GPU_MEMORY_GATE_MB=20000 MAX_LOAD1=180 \
  bash "$RUN_ROOT/scripts/launch_rfantibody_multiworker_gpu.sh"

write_state FREEZING "balanced exact-unique RFantibody target 75000"
"$RF_PYTHON" "$RUN_ROOT/scripts/collect_and_freeze_candidates.py" \
  --run-root "$RUN_ROOT" --arms-path "$MAIN_ARMS" --target 75000 \
  >"$RUN_ROOT/logs/collect_and_freeze_candidates.log" 2>&1

write_state COMPLETE "75000 exact-unique RFantibody candidates frozen"
date -Is > "$RUN_ROOT/status/controller.complete"
trap - ERR

