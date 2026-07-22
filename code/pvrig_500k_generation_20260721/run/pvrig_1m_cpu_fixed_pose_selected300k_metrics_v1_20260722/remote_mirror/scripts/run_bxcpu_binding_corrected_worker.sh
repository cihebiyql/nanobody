#!/usr/bin/env bash
set -Eeuo pipefail
: "${ROOT:?}"; : "${INPUT:?}"; : "${TASK_ID:?}"; : "${TASK_COUNT:?}"
ENV_ROOT=${ENV_ROOT:-$ROOT/env}; MODEL_ROOT=${MODEL_ROOT:-$ROOT/models}; OUT_ROOT=${OUT_ROOT:-$ROOT/results/binding_corrected}; CPUS=${CPUS:-16}
export OMP_NUM_THREADS="$CPUS" MKL_NUM_THREADS="$CPUS" OPENBLAS_NUM_THREADS="$CPUS" NUMEXPR_NUM_THREADS="$CPUS"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 CUDA_VISIBLE_DEVICES=""
TASK_DIR="$OUT_ROOT/task_$(printf '%03d' "$TASK_ID")"; mkdir -p "$TASK_DIR/input" "$TASK_DIR/output" "$TASK_DIR/logs"
"$ENV_ROOT/bin/python" "$ROOT/scripts/prepare_bxcpu_binding_shard.py" "$INPUT" "$TASK_DIR/input" --shard-index "$TASK_ID" --shard-count "$TASK_COUNT"
/usr/bin/time -f 'elapsed_seconds=%e max_rss_kb=%M' -o "$TASK_DIR/logs/deepnano.time" \
 "$ENV_ROOT/bin/python" "$ROOT/scripts/predict_deepnano_length_bucketed.py" --deepnano-root "$MODEL_ROOT/DeepNano" \
 --fasta "$TASK_DIR/input/deepnano_input.fasta" --pairs "$TASK_DIR/input/deepnano_pairs.tsv" \
 --output "$TASK_DIR/output/deepnano_binding.csv" --batch-size 32 >"$TASK_DIR/logs/deepnano.stdout" 2>"$TASK_DIR/logs/deepnano.stderr"
cd "$MODEL_ROOT/NanoBind"
/usr/bin/time -f 'elapsed_seconds=%e max_rss_kb=%M' -o "$TASK_DIR/logs/nanobind.time" \
 "$ENV_ROOT/bin/python" predict_seq.py --nb "$TASK_DIR/input/nanobodies.fasta" --ag "$TASK_DIR/input/antigens.fasta" \
 --output "$TASK_DIR/output/nanobind_binding.csv" >"$TASK_DIR/logs/nanobind.stdout" 2>"$TASK_DIR/logs/nanobind.stderr"
"$ENV_ROOT/bin/python" - "$TASK_DIR" <<'PY'
import csv,hashlib,json,sys,time
from pathlib import Path
r=Path(sys.argv[1]); expected=json.loads((r/'input/PREPARED.json').read_text())['records']
def rows(p): return list(csv.DictReader(p.open(newline='')))
d=rows(r/'output/deepnano_binding.csv'); n=rows(r/'output/nanobind_binding.csv')
if len(d)!=expected or len(n)!=expected: raise SystemExit(f'count mismatch {len(d)} {len(n)} {expected}')
if {x['Nanobody ID'] for x in d}!={x['nanobody_id'] for x in n}: raise SystemExit('ID mismatch')
p={'status':'PASS','records':expected,'deepnano_sha256':hashlib.sha256((r/'output/deepnano_binding.csv').read_bytes()).hexdigest(),
 'nanobind_sha256':hashlib.sha256((r/'output/nanobind_binding.csv').read_bytes()).hexdigest(),'completed_epoch':time.time(),
 'deepnano_inference_semantics':'exact-length buckets; batch-composition invariant',
 'scientific_boundary':'weak binding priors; not Kd, IC50, or blocking evidence'}
(r/'COMPLETE.json').write_text(json.dumps(p,indent=2,sort_keys=True)+'\n')
PY
