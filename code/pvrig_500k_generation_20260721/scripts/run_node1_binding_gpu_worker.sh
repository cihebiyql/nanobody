#!/usr/bin/env bash
set -Eeuo pipefail

: "${ROOT:?}"
: "${INPUT:?}"
: "${MODEL:?}"
: "${TASK_ID:?}"
: "${TASK_COUNT:?}"
: "${GPU:?}"

PY=${PY:-/data1/qlyu/software/envs/deepnano/bin/python}
DEEPNANO_ROOT=${DEEPNANO_ROOT:-/data1/qlyu/software/DeepNano_8M_minimal}
NANOBIND_ROOT=${NANOBIND_ROOT:-/data1/qlyu/software/NanoBind}
DEEPNANO_BATCH_SIZE=${DEEPNANO_BATCH_SIZE:-512}
NANOBIND_BATCH_SIZE=${NANOBIND_BATCH_SIZE:-256}
TASK_DIR="$ROOT/$MODEL/task_$(printf '%03d' "$TASK_ID")"

mkdir -p "$TASK_DIR/input" "$TASK_DIR/output" "$TASK_DIR/logs"
export CUDA_VISIBLE_DEVICES="$GPU"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2

"$PY" "$ROOT/scripts/prepare_bxcpu_binding_shard.py" \
  "$INPUT" "$TASK_DIR/input" \
  --shard-index "$TASK_ID" \
  --shard-count "$TASK_COUNT"

case "$MODEL" in
  deepnano)
    /usr/bin/time -f 'elapsed_seconds=%e max_rss_kb=%M' -o "$TASK_DIR/logs/model.time" \
      "$PY" "$ROOT/scripts/predict_deepnano_length_bucketed.py" \
      --deepnano-root "$DEEPNANO_ROOT" \
      --fasta "$TASK_DIR/input/deepnano_input.fasta" \
      --pairs "$TASK_DIR/input/deepnano_pairs.tsv" \
      --output "$TASK_DIR/output/deepnano_binding.csv" \
      --batch-size "$DEEPNANO_BATCH_SIZE" \
      --device cuda \
      >"$TASK_DIR/logs/model.stdout" 2>"$TASK_DIR/logs/model.stderr"
    ;;
  nanobind)
    /usr/bin/time -f 'elapsed_seconds=%e max_rss_kb=%M' -o "$TASK_DIR/logs/model.time" \
      "$PY" "$ROOT/scripts/predict_nanobind_length_bucketed.py" \
      --nanobind-root "$NANOBIND_ROOT" \
      --nanobody-fasta "$TASK_DIR/input/nanobodies.fasta" \
      --antigen-fasta "$TASK_DIR/input/antigens.fasta" \
      --output "$TASK_DIR/output/nanobind_binding.csv" \
      --batch-size "$NANOBIND_BATCH_SIZE" \
      --device cuda \
      >"$TASK_DIR/logs/model.stdout" 2>"$TASK_DIR/logs/model.stderr"
    ;;
  *)
    echo "Unsupported MODEL=$MODEL" >&2
    exit 2
    ;;
esac

"$PY" - "$TASK_DIR" "$MODEL" <<'PY'
import csv
import hashlib
import json
import sys
import time
from pathlib import Path

task = Path(sys.argv[1])
model = sys.argv[2]
expected = json.loads((task / "input" / "PREPARED.json").read_text())["records"]
if model == "deepnano":
    path = task / "output" / "deepnano_binding.csv"
    id_column = "Nanobody ID"
else:
    path = task / "output" / "nanobind_binding.csv"
    id_column = "nanobody_id"
with path.open(newline="") as handle:
    rows = list(csv.DictReader(handle))
ids = [row[id_column] for row in rows]
if len(rows) != expected or len(set(ids)) != expected:
    raise SystemExit(
        f"{model} count/uniqueness mismatch: rows={len(rows)} "
        f"unique={len(set(ids))} expected={expected}"
    )
receipt = {
    "status": "PASS",
    "model": model,
    "records": expected,
    "output": str(path),
    "output_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    "completed_epoch": time.time(),
    "inference_semantics": "exact-length buckets; batch-composition invariant",
    "scientific_boundary": "weak binding prior; not Kd, IC50, or blocking evidence",
}
(task / "COMPLETE.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
PY
