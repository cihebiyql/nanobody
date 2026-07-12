#!/usr/bin/env bash
set -euo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712}
BATCH_ROOT=${BATCH_ROOT:-$RUN_ROOT/rf2/multiseed}
MANIFEST=${MANIFEST:-$BATCH_ROOT/rf2_multiseed_manifest.tsv}
RF2_BIN=${RF2_BIN:-/data/qlyu/software/RFantibody/bin/rf2}
GPU_IDS=${GPU_IDS:-1,2,3,4,5,7}
SEEDS=${SEEDS:-42}
ENABLE_ENRICHMENT_SEEDS=${ENABLE_ENRICHMENT_SEEDS:-0}
MIN_SEED42_OUTPUTS=${MIN_SEED42_OUTPUTS:-1000}
MAX_LOAD1=${MAX_LOAD1:-64}
MAX_GPU_USED_MB=${MAX_GPU_USED_MB:-1000}
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-2}
export MKL_NUM_THREADS=${MKL_NUM_THREADS:-2}
export OPENBLAS_NUM_THREADS=${OPENBLAS_NUM_THREADS:-2}

[[ -x "$RF2_BIN" ]] || { echo "Missing RF2 executable: $RF2_BIN" >&2; exit 2; }
[[ -f "$MANIFEST" ]] || { echo "Missing RF2 multiseed manifest: $MANIFEST" >&2; exit 2; }

load1=$(cut -d' ' -f1 /proc/loadavg)
if ! awk -v load="$load1" -v limit="$MAX_LOAD1" 'BEGIN { exit !(load < limit) }'; then
  echo "Refusing RF2 launch: load1=$load1 is not below gate $MAX_LOAD1" >&2
  exit 3
fi

mkdir -p "$BATCH_ROOT/manifests"
{
  echo "captured_at=$(date -Is)"
  echo "hostname=$(hostname)"
  echo "loadavg=$(cat /proc/loadavg)"
  echo "gpu_ids=$GPU_IDS"
  echo "seeds=$SEEDS"
  sha256sum "$MANIFEST" "$RF2_BIN"
  nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader || true
} > "$BATCH_ROOT/manifests/rf2_multigpu_launch_snapshot.txt"

count_seed_outputs() {
  local seed=$1
  local seed_dir="$BATCH_ROOT/seeds/seed_$seed/shards"
  [[ -d "$seed_dir" ]] || { echo 0; return; }
  find "$seed_dir" -path '*/output/*_best.pdb' -type f | wc -l
}

seed42_outputs=$(count_seed_outputs 42 | tr -d ' ')
seed42_ready=0
if [[ "$seed42_outputs" -ge "$MIN_SEED42_OUTPUTS" ]]; then
  seed42_ready=1
fi

IFS=',' read -r -a seed_array <<< "$SEEDS"
IFS=',' read -r -a gpu_array <<< "$GPU_IDS"
launched=0
skipped_enrichment=0

for seed in "${seed_array[@]}"; do
  seed=${seed//[[:space:]]/}
  [[ -n "$seed" ]] || continue
  if [[ "$seed" != "42" ]]; then
    if [[ "$ENABLE_ENRICHMENT_SEEDS" != "1" || "$seed42_ready" != "1" ]]; then
      echo "Skipping seed_$seed enrichment: seed42_outputs=$seed42_outputs min_required=$MIN_SEED42_OUTPUTS enable=$ENABLE_ENRICHMENT_SEEDS"
      skipped_enrichment=$((skipped_enrichment + 1))
      continue
    fi
  fi

  for gpu_id in "${gpu_array[@]}"; do
    gpu_id=${gpu_id//[[:space:]]/}
    [[ -n "$gpu_id" ]] || continue
    shard="$BATCH_ROOT/seeds/seed_$seed/shards/gpu_$gpu_id"
    input_dir="$shard/input"
    output_dir="$shard/output"
    todo_dir="$shard/todo_input"
    log_dir="$shard/logs"
    pid_file="$shard/rf2.pid"
    exit_file="$shard/rf2.exit_code"
    [[ -d "$input_dir" ]] || continue
    if [[ -s "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
      echo "seed_$seed/gpu_$gpu_id already running pid=$(cat "$pid_file")"
      continue
    fi

    if command -v nvidia-smi >/dev/null 2>&1; then
      used_mb=$(nvidia-smi --id="$gpu_id" --query-gpu=memory.used --format=csv,noheader,nounits | tr -d ' ' || echo 999999)
      if [[ "$used_mb" -ge "$MAX_GPU_USED_MB" ]]; then
        echo "Skipping seed_$seed/gpu_$gpu_id: memory.used=${used_mb}MiB" >&2
        continue
      fi
    fi

    mkdir -p "$todo_dir" "$output_dir" "$log_dir"
    find "$todo_dir" -maxdepth 1 -type l -name '*.pdb' -delete
    python3 - "$MANIFEST" "$seed" "$gpu_id" "$todo_dir" <<'PY'
import csv
import os
import sys
from pathlib import Path
manifest, seed, gpu_id, todo_dir = sys.argv[1:]
todo = Path(todo_dir)
queued = 0
with open(manifest, newline='', encoding='utf-8') as handle:
    for row in csv.DictReader(handle, delimiter='\t'):
        if row['seed'] != seed or row['gpu_id'] != gpu_id:
            continue
        expected = Path(row['expected_output_pdb'])
        if expected.is_file():
            continue
        link = todo / Path(row['staged_pdb']).name
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink(row['staged_pdb'], link)
        queued += 1
print(queued)
PY
    todo_count=$(find "$todo_dir" -maxdepth 1 -type l -name '*.pdb' | wc -l | tr -d ' ')
    if [[ "$todo_count" -eq 0 ]]; then
      echo "seed_$seed/gpu_$gpu_id complete: no missing outputs to queue"
      continue
    fi

    rm -f "$exit_file"
    command_file="$shard/rf2_command.sh"
    cat > "$command_file" <<EOF
CUDA_VISIBLE_DEVICES=$gpu_id $RF2_BIN --input-dir $todo_dir --output-dir $output_dir --num-recycles 10 --hotspot-show-prop 0 --seed $seed
EOF
    (
      export CUDA_VISIBLE_DEVICES="$gpu_id"
      set +e
      "$RF2_BIN" \
        --input-dir "$todo_dir" \
        --output-dir "$output_dir" \
        --num-recycles 10 \
        --hotspot-show-prop 0 \
        --seed "$seed"
      rc=$?
      set -e
      echo "$rc" > "$exit_file"
      exit "$rc"
    ) > "$log_dir/rf2_seed_${seed}.log" 2>&1 < /dev/null &
    pid=$!
    echo "$pid" > "$pid_file"
    echo "launched seed_$seed/gpu_$gpu_id pid=$pid queued_missing=$todo_count existing_seed42_outputs=$seed42_outputs"
    launched=$((launched + 1))
    sleep 2
  done
done

echo "launched_shards=$launched"
echo "seed42_outputs=$seed42_outputs"
echo "seed42_enrichment_ready=$seed42_ready"
echo "skipped_enrichment_seeds=$skipped_enrichment"
