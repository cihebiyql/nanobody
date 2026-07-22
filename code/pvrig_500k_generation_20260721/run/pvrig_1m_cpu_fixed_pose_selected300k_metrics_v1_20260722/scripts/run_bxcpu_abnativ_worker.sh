#!/usr/bin/env bash
set -Eeuo pipefail
: "${ROOT:?ROOT is required}"
: "${INPUT:?INPUT is required}"
: "${TASK_ID:?TASK_ID is required}"
: "${TASK_COUNT:?TASK_COUNT is required}"
ENV_ROOT="${ENV_ROOT:-$ROOT/env}"
OUT_ROOT="${OUT_ROOT:-$ROOT/results/abnativ_full}"
CPUS="${CPUS:-16}"

if [[ -n "${LOCAL_ROOT:-}" && -d "$LOCAL_ROOT/python/anarci" ]]; then
  export PYTHONPATH="$LOCAL_ROOT/python${PYTHONPATH:+:$PYTHONPATH}"
  export ABNATIV_MODELS_DIR="$LOCAL_ROOT/models"
  export PATH="$LOCAL_ROOT/bin:$PATH"
else
  export ABNATIV_MODELS_DIR="$ROOT/models/AbNatiV"
  export PATH="$ROOT/tools/hmmer-3.3.2/bin:$PATH"
fi
export OMP_NUM_THREADS="$CPUS"
export MKL_NUM_THREADS="$CPUS"
export OPENBLAS_NUM_THREADS="$CPUS"
export CUDA_VISIBLE_DEVICES=""

TASK_DIR="$OUT_ROOT/task_$(printf '%03d' "$TASK_ID")"
mkdir -p "$TASK_DIR/input" "$TASK_DIR/output" "$TASK_DIR/logs"
"$ENV_ROOT/bin/python" "$ROOT/scripts/prepare_bxcpu_binding_shard.py" \
  "$INPUT" "$TASK_DIR/input" --shard-index "$TASK_ID" --shard-count "$TASK_COUNT" \
  --limit "${LIMIT:-0}"

SUBPROCESSES="${SUBPROCESSES_PER_TASK:-1}"
if (( SUBPROCESSES > 1 )); then
  /usr/bin/time -f 'elapsed_seconds=%e max_rss_kb=%M' -o "$TASK_DIR/logs/abnativ.time" \
    "$ENV_ROOT/bin/python" "$ROOT/scripts/run_abnativ_subshards.py" \
      "$TASK_DIR/input/nanobodies.fasta" "$TASK_DIR/output/abnativ.csv" \
      --workers "$SUBPROCESSES" --python "$ENV_ROOT/bin/python" \
      --scorer "$ROOT/scripts/abnativ_score_direct.py" \
      >"$TASK_DIR/logs/abnativ.stdout" 2>"$TASK_DIR/logs/abnativ.stderr"
else
  /usr/bin/time -f 'elapsed_seconds=%e max_rss_kb=%M' -o "$TASK_DIR/logs/abnativ.time" \
    "$ENV_ROOT/bin/python" "$ROOT/scripts/abnativ_score_direct.py" \
      "$TASK_DIR/input/nanobodies.fasta" -o "$TASK_DIR/output/abnativ.csv" \
      --ncpu "$CPUS" --batch-size 128 \
      >"$TASK_DIR/logs/abnativ.stdout" 2>"$TASK_DIR/logs/abnativ.stderr"
fi

"$ENV_ROOT/bin/python" - "$TASK_DIR" <<'PY'
import csv, hashlib, json, sys, time
from pathlib import Path
root=Path(sys.argv[1]); prepared=json.loads((root/'input/PREPARED.json').read_text())['records']
rows=list(csv.DictReader((root/'output/abnativ.csv').open(newline='')))
if len(rows)!=prepared: raise SystemExit(f'row count mismatch: {len(rows)} != {prepared}')
status_counts={}
for row in rows:
    status=row['abnativ_status']; status_counts[status]=status_counts.get(status,0)+1
    if status=='PASS':
        score=float(row['AbNatiV VHH Score'])
        if not 0 <= score <= 1: raise SystemExit(f'invalid AbNatiV score {score}')
    elif status=='NA':
        if row['AbNatiV VHH Score'] or not row['abnativ_failure_reason']:
            raise SystemExit('invalid AbNatiV NA semantics')
    else: raise SystemExit(f'unknown AbNatiV status {status}')
out=root/'output/abnativ.csv'
payload={'status':'PASS','records':len(rows),'status_counts':status_counts,'completed_epoch':time.time(),
         'output_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),
         'scientific_boundary':'VHH nativeness/developability proxy; not measured expression or purity'}
(root/'COMPLETE.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
PY
