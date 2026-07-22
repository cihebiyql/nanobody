#!/usr/bin/env bash
set -Eeuo pipefail
: "${ROOT:?}"; : "${INPUT:?}"; : "${TASK_ID:?}"; : "${TASK_COUNT:?}"
ENV_ROOT="${ENV_ROOT:-$ROOT/env}"; CPUS="${CPUS:-16}"
OUT_ROOT="${OUT_ROOT:-$ROOT/results/deepnano_corrected_full}"
export OMP_NUM_THREADS="$CPUS" MKL_NUM_THREADS="$CPUS" OPENBLAS_NUM_THREADS="$CPUS"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 CUDA_VISIBLE_DEVICES=""
TASK_DIR="$OUT_ROOT/task_$(printf '%03d' "$TASK_ID")"
mkdir -p "$TASK_DIR/input" "$TASK_DIR/output" "$TASK_DIR/logs"
"$ENV_ROOT/bin/python" "$ROOT/scripts/prepare_bxcpu_binding_shard.py" "$INPUT" "$TASK_DIR/input" \
  --shard-index "$TASK_ID" --shard-count "$TASK_COUNT" --limit "${LIMIT:-0}"
/usr/bin/time -f 'elapsed_seconds=%e max_rss_kb=%M' -o "$TASK_DIR/logs/deepnano.time" \
  "$ENV_ROOT/bin/python" "$ROOT/scripts/predict_deepnano_length_bucketed.py" \
  --deepnano-root "$ROOT/models/DeepNano" --fasta "$TASK_DIR/input/deepnano_input.fasta" \
  --pairs "$TASK_DIR/input/deepnano_pairs.tsv" --output "$TASK_DIR/output/deepnano_binding.csv" \
  --batch-size "${BATCH_SIZE:-32}" >"$TASK_DIR/logs/stdout" 2>"$TASK_DIR/logs/stderr"
"$ENV_ROOT/bin/python" - "$TASK_DIR" <<'PY'
import csv, hashlib, json, sys, time
from pathlib import Path
root=Path(sys.argv[1]); expected=json.loads((root/'input/PREPARED.json').read_text())['records']
output=root/'output/deepnano_binding.csv'; rows=list(csv.DictReader(output.open()))
if len(rows)!=expected: raise SystemExit(f'{len(rows)} != {expected}')
payload={'status':'PASS','records':expected,'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
         'completed_epoch':time.time(),'inference_semantics':'exact-length buckets; batch-composition invariant',
         'scientific_boundary':'weak binding prior; not Kd, IC50, or blocking evidence'}
(root/'COMPLETE.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
PY
