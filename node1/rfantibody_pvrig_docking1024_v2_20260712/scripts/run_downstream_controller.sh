#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712}
MAX_LOAD1=${MAX_LOAD1:-240}
HADDOCK_MAX_LOAD1=${HADDOCK_MAX_LOAD1:-240}
GPU_MEMORY_GATE_MB=${GPU_MEMORY_GATE_MB:-12000}
POLL_SECONDS=${POLL_SECONDS:-120}
RF2_MIN_COMPLETE=${RF2_MIN_COMPLETE:-1000}
NBB2_MIN_SUCCESS=${NBB2_MIN_SUCCESS:-1000}
HADDOCK_MIN_SUCCESS=${HADDOCK_MIN_SUCCESS:-1000}
HADDOCK_MAX_PARALLEL=${HADDOCK_MAX_PARALLEL:-2}
export MAX_LOAD1 GPU_MEMORY_GATE_MB
BATCH_ROOT="$RUN_ROOT/rf2/multiseed"
mkdir -p "$RUN_ROOT"/{logs,status,data,rf2,docking,qc,reports}

exec 9>"$RUN_ROOT/status/downstream_controller.lock"
if ! flock -n 9; then
  echo "Downstream controller is already running"
  exit 0
fi

write_state() {
  local state=$1 message=${2:-}
  python3 - "$RUN_ROOT/status/downstream_controller.json" "$state" "$message" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1])
payload = {"state": sys.argv[2], "message": sys.argv[3], "pid": os.getppid(), "updated_at": datetime.now(timezone.utc).isoformat()}
tmp = path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
tmp.replace(path)
PY
}

wait_for_generation() {
  while [[ ! -s "$RUN_ROOT/status/generation_controller.complete" || ! -s "$RUN_ROOT/data/candidates.tsv" ]]; do
    write_state waiting_for_generation "waiting for frozen 1024-candidate cohort"
    sleep "$POLL_SECONDS"
  done
}

wait_for_load() {
  while true; do
    load1=$(cut -d' ' -f1 /proc/loadavg)
    if awk -v load="$load1" -v limit="$MAX_LOAD1" 'BEGIN { exit !(load < limit) }'; then return; fi
    echo "LOAD_WAIT load1=$load1 threshold=$MAX_LOAD1 time=$(date -Is)"
    sleep "$POLL_SECONDS"
  done
}

wait_for_gpus() {
  while true; do
    busy=()
    for gpu in 1 2 3 4 5 7; do
      used=$(nvidia-smi --id="$gpu" --query-gpu=memory.used --format=csv,noheader,nounits | tr -d ' ')
      [[ "$used" -lt "$GPU_MEMORY_GATE_MB" ]] || busy+=("$gpu:$used")
    done
    [[ ${#busy[@]} -eq 0 ]] && return
    echo "GPU_WAIT busy=${busy[*]} time=$(date -Is)"
    sleep "$POLL_SECONDS"
  done
}

rf2_count() {
  local seed=$1
  find "$BATCH_ROOT/seeds/seed_$seed/shards" -path '*/output/*_best.pdb' -type f 2>/dev/null | wc -l | tr -d ' '
}

rf2_running() {
  local seed=$1 running=0
  for pidfile in "$BATCH_ROOT"/seeds/seed_"$seed"/shards/gpu_*/rf2.pid; do
    [[ -e "$pidfile" ]] || continue
    kill -0 "$(cat "$pidfile")" 2>/dev/null && running=$((running + 1))
  done
  echo "$running"
}

wait_rf2_seed() {
  local seed=$1
  while true; do
    count=$(rf2_count "$seed")
    running=$(rf2_running "$seed")
    echo "RF2_PROGRESS seed=$seed outputs=$count running_shards=$running time=$(date -Is)"
    [[ "$running" -eq 0 ]] && return
    sleep "$POLL_SECONDS"
  done
}

run_rf2_seed42() {
  local count=0
  for attempt in 1 2 3; do
    wait_for_load
    wait_for_gpus
    RUN_ROOT="$RUN_ROOT" BATCH_ROOT="$BATCH_ROOT" SEEDS=42 \
      bash "$RUN_ROOT/scripts/run_rf2_multigpu.sh"
    wait_rf2_seed 42
    count=$(rf2_count 42)
    [[ "$count" -ge "$RF2_MIN_COMPLETE" ]] && break
    echo "RF2_RETRY seed=42 attempt=$attempt outputs=$count"
  done
  [[ "$count" -ge "$RF2_MIN_COMPLETE" ]] || {
    write_state failed_rf2_seed42 "seed42 outputs=$count below $RF2_MIN_COMPLETE"
    return 1
  }
}

run_rf2_enrichment() {
  wait_for_load
  wait_for_gpus
  RUN_ROOT="$RUN_ROOT" BATCH_ROOT="$BATCH_ROOT" SEEDS=43 ENABLE_ENRICHMENT_SEEDS=1 \
    bash "$RUN_ROOT/scripts/run_rf2_multigpu.sh"
  wait_rf2_seed 43
  wait_for_load
  wait_for_gpus
  RUN_ROOT="$RUN_ROOT" BATCH_ROOT="$BATCH_ROOT" SEEDS=44 ENABLE_ENRICHMENT_SEEDS=1 \
    bash "$RUN_ROOT/scripts/run_rf2_multigpu.sh"
  wait_rf2_seed 44
  python3 "$RUN_ROOT/scripts/parse_rf2_multiseed.py" \
    "$BATCH_ROOT/rf2_multiseed_manifest.tsv" "$RUN_ROOT/rf2/results" \
    >"$RUN_ROOT/logs/parse_rf2_enrichment.log" 2>&1
}

nbb2_success_count() {
  python3 "$RUN_ROOT/scripts/status_docking.py" --run-root "$RUN_ROOT" --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["nbb2_counts"]["success"])'
}

haddock_success_count() {
  python3 "$RUN_ROOT/scripts/status_docking.py" --run-root "$RUN_ROOT" --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["haddock_counts"]["success"])'
}

wait_for_generation

write_state sequence_qc "running full-cohort fast sequence QC"
bash "$RUN_ROOT/scripts/run_sequence_qc_fast.sh"

write_state rf2_prepare "staging the same 1024 candidates for three RF2 seeds"
python3 "$RUN_ROOT/scripts/prepare_rf2_multiseed.py" \
  "$RUN_ROOT/data/candidates.tsv" "$BATCH_ROOT" \
  --gpu-ids 1,2,3,4,5,7 --seeds 42,43,44 --expected-candidates 1024 \
  >"$RUN_ROOT/logs/prepare_rf2_multiseed.log" 2>&1

write_state rf2_seed42 "running primary RF2 seed42 to at least 1000 outputs"
run_rf2_seed42
python3 "$RUN_ROOT/scripts/parse_rf2_multiseed.py" \
  "$BATCH_ROOT/rf2_multiseed_manifest.tsv" "$RUN_ROOT/rf2/results" \
  >"$RUN_ROOT/logs/parse_rf2_seed42.log" 2>&1
cp "$RUN_ROOT/rf2/results/rf2_multiseed_metrics.tsv" "$RUN_ROOT/data/rf2_metrics.tsv"
cp "$RUN_ROOT/rf2/results/rf2_multiseed_candidate_gates.tsv" "$RUN_ROOT/data/rf2_candidate_gates.tsv"

write_state docking_package "building 1024-candidate NBB2 and HADDOCK package"
python3 "$RUN_ROOT/scripts/build_docking_package.py" --run-root "$RUN_ROOT" --expected-count 1024 \
  >"$RUN_ROOT/logs/build_docking_package.log" 2>&1

write_state nbb2_haddock_smoke "validating one exact sequence through NBB2 and HADDOCK"
wait_for_load
wait_for_gpus
RUN_ROOT="$RUN_ROOT" CANDIDATE_LIMIT=1 bash "$RUN_ROOT/scripts/run_nbb2_multigpu.sh"
SMOKE_CID=$(awk -F $'\t' 'NR==2 {print $1}' "$RUN_ROOT/docking/manifests/docking_candidates.tsv")
wait_for_load
RUN_ROOT="$RUN_ROOT" MAX_LOAD1="$HADDOCK_MAX_LOAD1" \
  bash "$RUN_ROOT/scripts/run_haddock_one.sh" "$SMOKE_CID"

write_state nbb2_full "running NBB2 on the full frozen cohort"
for attempt in 1 2 3; do
  wait_for_load
  wait_for_gpus
  RUN_ROOT="$RUN_ROOT" bash "$RUN_ROOT/scripts/run_nbb2_multigpu.sh"
  nbb2_count=$(nbb2_success_count)
  echo "NBB2_PROGRESS success=$nbb2_count attempt=$attempt"
  [[ "$nbb2_count" -ge "$NBB2_MIN_SUCCESS" ]] && break
done
[[ "$nbb2_count" -ge "$NBB2_MIN_SUCCESS" ]] || {
  write_state failed_nbb2 "NBB2 successes=$nbb2_count below $NBB2_MIN_SUCCESS"
  exit 5
}

write_state docking_full "running load-aware HADDOCK and RF2 enrichment"
run_rf2_enrichment >"$RUN_ROOT/logs/rf2_enrichment_controller.log" 2>&1 &
enrichment_pid=$!
python3 "$RUN_ROOT/scripts/run_haddock_load_aware.py" \
  --run-root "$RUN_ROOT" --max-load1 "$HADDOCK_MAX_LOAD1" --cores-per-job 4 \
  --max-parallel "$HADDOCK_MAX_PARALLEL" --poll-seconds "$POLL_SECONDS" --retry-failed --max-attempts 3 \
  >"$RUN_ROOT/logs/haddock_load_aware.log" 2>&1
wait "$enrichment_pid" || true
cp "$RUN_ROOT/rf2/results/rf2_multiseed_metrics.tsv" "$RUN_ROOT/data/rf2_metrics.tsv"
cp "$RUN_ROOT/rf2/results/rf2_multiseed_candidate_gates.tsv" "$RUN_ROOT/data/rf2_candidate_gates.tsv"

haddock_count=$(haddock_success_count)
if [[ "$haddock_count" -lt "$HADDOCK_MIN_SUCCESS" ]]; then
  write_state docking_retry "retrying failed HADDOCK candidates up to five attempts"
  python3 "$RUN_ROOT/scripts/run_haddock_load_aware.py" \
    --run-root "$RUN_ROOT" --max-load1 "$HADDOCK_MAX_LOAD1" --cores-per-job 4 \
    --max-parallel "$HADDOCK_MAX_PARALLEL" --poll-seconds "$POLL_SECONDS" --retry-failed --max-attempts 5 \
    >>"$RUN_ROOT/logs/haddock_load_aware.log" 2>&1
  haddock_count=$(haddock_success_count)
fi

python3 "$RUN_ROOT/scripts/status_docking.py" --run-root "$RUN_ROOT" --json \
  --export-dir "$RUN_ROOT/data" >"$RUN_ROOT/reports/docking_status.json"
python3 "$RUN_ROOT/scripts/build_training_dataset.py" \
  --input-dir "$RUN_ROOT/data" --output-dir "$RUN_ROOT/data/training_dataset" \
  --haddock-root "$RUN_ROOT/docking/haddock" --mode partial \
  >"$RUN_ROOT/logs/build_training_dataset_partial.log" 2>&1

if [[ "$haddock_count" -lt "$HADDOCK_MIN_SUCCESS" ]]; then
  write_state incomplete_docking "HADDOCK successes=$haddock_count below $HADDOCK_MIN_SUCCESS"
  exit 6
fi
write_state raw_docking_complete "RF2 NBB2 and HADDOCK raw data complete for at least 1000 candidates"
date -Is > "$RUN_ROOT/status/downstream_controller.raw_docking_complete"
