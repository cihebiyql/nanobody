#!/usr/bin/env bash
set -Eeuo pipefail

: "${ROOT:?ROOT is required}"
: "${INPUT:?INPUT is required}"
: "${TASK_ID:?TASK_ID is required}"
: "${TASK_COUNT:?TASK_COUNT is required}"
ENV_ROOT="${ENV_ROOT:-$ROOT/env}"
OUT_ROOT="${OUT_ROOT:-$ROOT/results/sapiens_full}"
CPUS="${CPUS:-16}"

export OMP_NUM_THREADS="$CPUS"
export MKL_NUM_THREADS="$CPUS"
export OPENBLAS_NUM_THREADS="$CPUS"
export TRANSFORMERS_OFFLINE=1
export HF_HUB_OFFLINE=1
export CUDA_VISIBLE_DEVICES=""

TASK_DIR="$OUT_ROOT/task_$(printf '%03d' "$TASK_ID")"
mkdir -p "$TASK_DIR/input" "$TASK_DIR/output" "$TASK_DIR/logs"
"$ENV_ROOT/bin/python" "$ROOT/scripts/prepare_bxcpu_binding_shard.py" \
  "$INPUT" "$TASK_DIR/input" --shard-index "$TASK_ID" --shard-count "$TASK_COUNT"

/usr/bin/time -f 'elapsed_seconds=%e max_rss_kb=%M' -o "$TASK_DIR/logs/sapiens.time" \
  "$ENV_ROOT/bin/python" "$ROOT/vhh_eval_tools/sapiens_score.py" \
    "$TASK_DIR/input/nanobodies.fasta" \
    -o "$TASK_DIR/output/sapiens.csv" --chain H \
    --models-dir "$ROOT/models/Sapiens_models" \
    >"$TASK_DIR/logs/sapiens.stdout" 2>"$TASK_DIR/logs/sapiens.stderr"

"$ENV_ROOT/bin/python" - "$TASK_DIR" <<'PY'
import csv, hashlib, json, sys, time
from pathlib import Path
root=Path(sys.argv[1])
prepared=json.loads((root/'input/PREPARED.json').read_text())['records']
rows=list(csv.DictReader((root/'output/sapiens.csv').open(newline='')))
if len(rows) != prepared:
    raise SystemExit(f'row count mismatch: sapiens={len(rows)} prepared={prepared}')
for row in rows:
    score=float(row['mean_self_probability'])
    if not 0.0 <= score <= 1.0:
        raise SystemExit(f'invalid Sapiens score: {score}')
out=root/'output/sapiens.csv'
payload={'status':'PASS','records':len(rows),'completed_epoch':time.time(),
         'output_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),
         'scientific_boundary':'human-likeness/developability proxy; not measured expression or purity'}
(root/'COMPLETE.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
PY
