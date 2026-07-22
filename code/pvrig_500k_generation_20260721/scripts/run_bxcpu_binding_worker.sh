#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${ROOT:?ROOT is required}"
INPUT="${INPUT:?INPUT is required}"
TASK_ID="${TASK_ID:?TASK_ID is required}"
TASK_COUNT="${TASK_COUNT:?TASK_COUNT is required}"
LIMIT="${LIMIT:-0}"
CPUS="${CPUS:-16}"
ENV_ROOT="${ENV_ROOT:-$ROOT/env}"
MODEL_ROOT="${MODEL_ROOT:-$ROOT/models}"
OUT_ROOT="${OUT_ROOT:-$ROOT/results/full}"

export OMP_NUM_THREADS="$CPUS"
export MKL_NUM_THREADS="$CPUS"
export OPENBLAS_NUM_THREADS="$CPUS"
export NUMEXPR_NUM_THREADS="$CPUS"
export TRANSFORMERS_OFFLINE=1
export HF_HUB_OFFLINE=1
export CUDA_VISIBLE_DEVICES=""

TASK_DIR="$OUT_ROOT/task_$(printf '%03d' "$TASK_ID")"
mkdir -p "$TASK_DIR/input" "$TASK_DIR/output" "$TASK_DIR/logs"

"$ENV_ROOT/bin/python" "$ROOT/scripts/prepare_bxcpu_binding_shard.py" \
  "$INPUT" "$TASK_DIR/input" --shard-index "$TASK_ID" --shard-count "$TASK_COUNT" --limit "$LIMIT"

cd "$MODEL_ROOT/DeepNano"
/usr/bin/time -f 'elapsed_seconds=%e max_rss_kb=%M' -o "$TASK_DIR/logs/deepnano.time" \
  "$ENV_ROOT/bin/python" predict.py --model 1 --esm2 8M \
    --fasta_path "$TASK_DIR/input/deepnano_input.fasta" \
    --pair_path "$TASK_DIR/input/deepnano_pairs.tsv" \
    --output_path "$TASK_DIR/output/deepnano_binding.csv" \
    --esm2_path "$MODEL_ROOT/DeepNano/models/esm2_t6_8M_UR50D" \
    >"$TASK_DIR/logs/deepnano.stdout" 2>"$TASK_DIR/logs/deepnano.stderr"

cd "$MODEL_ROOT/NanoBind"
/usr/bin/time -f 'elapsed_seconds=%e max_rss_kb=%M' -o "$TASK_DIR/logs/nanobind.time" \
  "$ENV_ROOT/bin/python" predict_seq.py \
    --nb "$TASK_DIR/input/nanobodies.fasta" \
    --ag "$TASK_DIR/input/antigens.fasta" \
    --output "$TASK_DIR/output/nanobind_binding.csv" \
    >"$TASK_DIR/logs/nanobind.stdout" 2>"$TASK_DIR/logs/nanobind.stderr"

"$ENV_ROOT/bin/python" - "$TASK_DIR" <<'PY'
import csv, hashlib, json, sys, time
from pathlib import Path
root=Path(sys.argv[1])
prepared=json.loads((root/'input/PREPARED.json').read_text())
def count(path):
    with path.open() as handle:
        return sum(1 for _ in csv.DictReader(handle))
deep=root/'output/deepnano_binding.csv'; nano=root/'output/nanobind_binding.csv'
counts={'prepared':prepared['records'], 'deepnano':count(deep), 'nanobind':count(nano)}
if len(set(counts.values())) != 1:
    raise SystemExit('row count mismatch: '+repr(counts))
payload={'status':'PASS','counts':counts,'completed_epoch':time.time(),
         'deepnano_sha256':hashlib.sha256(deep.read_bytes()).hexdigest(),
         'nanobind_sha256':hashlib.sha256(nano.read_bytes()).hexdigest(),
         'scientific_boundary':'weak binding priors; not Kd, IC50, or blocking evidence'}
(root/'COMPLETE.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
PY
