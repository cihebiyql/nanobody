#!/usr/bin/env bash
set -euo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_validation_20260712}
BATCH_ROOT=${BATCH_ROOT:-$RUN_ROOT/rf2/batch_10recycle_blind}
RF2_BIN=${RF2_BIN:-/data/qlyu/software/RFantibody/bin/rf2}
MAX_LOAD1=${MAX_LOAD1:-64}
GPU_IDS=${GPU_IDS:-1,2,3,4,6,7}

[[ -x "$RF2_BIN" ]] || { echo "Missing RF2 executable: $RF2_BIN" >&2; exit 2; }
[[ -f "$BATCH_ROOT/rf2_input_manifest.tsv" ]] || {
  echo "Missing RF2 manifest: $BATCH_ROOT/rf2_input_manifest.tsv" >&2
  exit 2
}

load1=$(cut -d' ' -f1 /proc/loadavg)
if ! awk -v load="$load1" -v limit="$MAX_LOAD1" 'BEGIN { exit !(load < limit) }'; then
  echo "Refusing RF2 launch: node1 load1=$load1 is not below gate $MAX_LOAD1" >&2
  exit 3
fi

mkdir -p "$BATCH_ROOT/manifests"
{
  echo "captured_at=$(date -Is)"
  echo "hostname=$(hostname)"
  echo "loadavg=$(cat /proc/loadavg)"
  sha256sum "$BATCH_ROOT/rf2_input_manifest.tsv" "$RF2_BIN"
  nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader
} > "$BATCH_ROOT/manifests/launch_snapshot.txt"

IFS=',' read -r -a gpu_array <<< "$GPU_IDS"
launched=0
for gpu_id in "${gpu_array[@]}"; do
  shard=$BATCH_ROOT/shards/gpu_$gpu_id
  input_dir=$shard/input
  output_dir=$shard/output
  log_dir=$shard/logs
  pid_file=$shard/rf2.pid
  exit_file=$shard/rf2.exit_code
  [[ -d "$input_dir" ]] || continue
  input_count=$(find "$input_dir" -maxdepth 1 -type l -name '*.pdb' | wc -l)
  [[ "$input_count" -gt 0 ]] || continue
  if [[ -s "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    echo "gpu_$gpu_id already running pid=$(cat "$pid_file")"
    continue
  fi
  used_mb=$(nvidia-smi --id="$gpu_id" --query-gpu=memory.used --format=csv,noheader,nounits | tr -d ' ')
  if [[ "$used_mb" -ge 1000 ]]; then
    echo "Skipping gpu_$gpu_id: memory.used=${used_mb}MiB" >&2
    continue
  fi
  mkdir -p "$output_dir" "$log_dir"
  rm -f "$exit_file"
  command_file=$shard/rf2_command.sh
  cat > "$command_file" <<EOF
CUDA_VISIBLE_DEVICES=$gpu_id $RF2_BIN --input-dir $input_dir --output-dir $output_dir --num-recycles 10 --hotspot-show-prop 0 --seed 42
EOF
  (
    export CUDA_VISIBLE_DEVICES="$gpu_id"
    "$RF2_BIN" \
      --input-dir "$input_dir" \
      --output-dir "$output_dir" \
      --num-recycles 10 \
      --hotspot-show-prop 0 \
      --seed 42
    rc=$?
    echo "$rc" > "$exit_file"
    exit "$rc"
  ) > "$log_dir/rf2.log" 2>&1 < /dev/null &
  pid=$!
  echo "$pid" > "$pid_file"
  echo "launched gpu_$gpu_id pid=$pid inputs=$input_count"
  launched=$((launched + 1))
  sleep 2
done

echo "launched_shards=$launched"

