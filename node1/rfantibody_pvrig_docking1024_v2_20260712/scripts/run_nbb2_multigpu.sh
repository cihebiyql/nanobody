#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
DOCKING_ROOT=${DOCKING_ROOT:-$RUN_ROOT/docking}
MANIFEST=${MANIFEST:-$DOCKING_ROOT/manifests/docking_candidates.tsv}
GPU_IDS=${GPU_IDS:-1,2,3,4,5,7}
GPU_MEMORY_GATE_MB=${GPU_MEMORY_GATE_MB:-12000}
GPU_WAIT_SECONDS=${GPU_WAIT_SECONDS:-60}
NBB2=${NBB2:-/data/qlyu/anaconda3/envs/boltz/bin/NanoBodyBuilder2}
BOLTZ_BIN=${BOLTZ_BIN:-/data/qlyu/anaconda3/envs/boltz/bin}
NBB2_THREADS=${NBB2_THREADS:-2}
MAX_LOAD1=${MAX_LOAD1:-240}
LOAD_WAIT_SECONDS=${LOAD_WAIT_SECONDS:-60}
HELPERS=${HELPERS:-$RUN_ROOT/scripts/docking_helpers}
CANDIDATE_LIMIT=${CANDIDATE_LIMIT:-0}
CPU_NICE=${CPU_NICE:-10}

mkdir -p "$DOCKING_ROOT"/{locks/nbb2,state/nbb2,logs/nbb2,monomer,reports}
[[ -s "$MANIFEST" ]] || { echo "Missing manifest: $MANIFEST" >&2; exit 2; }

json_state() {
  local path=$1 cid=$2 status=$3 gpu=$4 rc=${5:-0} message=${6:-}
  python3 - "$path" "$cid" "$status" "$gpu" "$rc" "$message" <<'PY'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1])
payload = {
    "candidate_id": sys.argv[2],
    "stage": "nbb2",
    "status": sys.argv[3],
    "gpu_id": sys.argv[4],
    "pid": os.getppid(),
    "return_code": int(sys.argv[5]),
    "message": sys.argv[6],
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
tmp = path.with_name(f".{path.name}.tmp")
tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
tmp.replace(path)
PY
}

wait_for_gpu() {
  local gpu=$1 used
  while true; do
    used=$(nvidia-smi --id="$gpu" --query-gpu=memory.used --format=csv,noheader,nounits | tr -d ' ')
    if [[ "$used" -lt "$GPU_MEMORY_GATE_MB" ]]; then
      return
    fi
    echo "GPU_GATE_WAIT gpu=$gpu memory_used_mb=$used threshold=$GPU_MEMORY_GATE_MB time=$(date -Is)"
    sleep "$GPU_WAIT_SECONDS"
  done
}

wait_for_load() {
  while true; do
    load1=$(cut -d' ' -f1 /proc/loadavg)
    if awk -v load="$load1" -v limit="$MAX_LOAD1" 'BEGIN { exit !(load < limit) }'; then
      return
    fi
    echo "LOAD_GATE_WAIT load1=$load1 threshold=$MAX_LOAD1 time=$(date -Is)"
    sleep "$LOAD_WAIT_SECONDS"
  done
}

run_candidate() {
  (
  local cid=$1 seq=$2 gpu=$3
  local lockdir="$DOCKING_ROOT/locks/nbb2/$cid.lock"
  local state="$DOCKING_ROOT/state/nbb2/$cid.json"
  local outdir="$DOCKING_ROOT/monomer/$cid"
  local raw="$outdir/${cid}_nanobodybuilder2_raw.pdb"
  local final="$outdir/${cid}_vhh_chainA.pdb"
  local haddock_data="$DOCKING_ROOT/haddock/$cid/data"
  if [[ -s "$final" && -s "$state" ]] && grep -q '"status": "success"' "$state"; then
    echo "NBB2_SKIP_SUCCESS cid=$cid gpu=$gpu"
    return 0
  fi
  if ! mkdir "$lockdir" 2>/dev/null; then
    echo "NBB2_SKIP_LOCKED cid=$cid gpu=$gpu"
    return 0
  fi
  trap 'rmdir "$lockdir" 2>/dev/null || true' EXIT
  mkdir -p "$outdir" "$haddock_data"
  json_state "$state" "$cid" running "$gpu" 0 ""
  wait_for_load
  wait_for_gpu "$gpu"
  echo "NBB2_START cid=$cid gpu=$gpu time=$(date -Is)"
  set +e
  CUDA_VISIBLE_DEVICES="$gpu" PATH="$BOLTZ_BIN:$PATH" nice -n "$CPU_NICE" "$NBB2" -H "$seq" -o "$raw" --n_threads "$NBB2_THREADS" -v >"$DOCKING_ROOT/logs/nbb2/${cid}.log" 2>&1
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    CUDA_VISIBLE_DEVICES="$gpu" PATH="$BOLTZ_BIN:$PATH" nice -n "$CPU_NICE" "$NBB2" -H "$seq" -o "$raw" --n_threads "$NBB2_THREADS" -u -v >"$DOCKING_ROOT/logs/nbb2/${cid}.unrefined.log" 2>&1
    rc=$?
  fi
  set -e
  if [[ $rc -eq 0 && -s "$raw" ]]; then
    seq_report="$DOCKING_ROOT/reports/${cid}_sequence_validation.json"
    geometry_report="$DOCKING_ROOT/reports/${cid}_monomer_geometry_qc.json"
    set +e
    python3 "$HELPERS/normalize_pdb_chain.py" \
      --in-pdb "$raw" --out-pdb "$final" --chain-id A --expected-residue-count "${#seq}" \
      >"$DOCKING_ROOT/logs/nbb2/${cid}.normalize.log" 2>&1
    rc=$?
    if [[ $rc -eq 0 ]]; then
      python3 "$HELPERS/validate_pdb_sequence.py" \
        --pdb "$final" --chain A --expected-seq "$seq" --out-json "$seq_report" \
        >"$DOCKING_ROOT/logs/nbb2/${cid}.sequence_validation.log" 2>&1
      rc=$?
    fi
    if [[ $rc -eq 0 ]]; then
      python3 "$HELPERS/pdb_geometry_qc.py" \
        --pdb "$final" --chain A --out-json "$geometry_report" \
        >"$DOCKING_ROOT/logs/nbb2/${cid}.geometry.log" 2>&1
      rc=$?
      if [[ $rc -eq 0 ]]; then
        python3 - "$geometry_report" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1]))
chain = report.get("chains", {}).get("A", {})
if not chain.get("likely_sane_backbone") or chain.get("adjacent_ca_distance_gt_6A", 1) != 0:
    raise SystemExit(2)
PY
        rc=$?
      fi
    fi
    set -e
    if [[ $rc -eq 0 ]]; then
      cp "$final" "$haddock_data/${cid}_vhh_chainA.pdb"
      json_state "$state" "$cid" success "$gpu" 0 "sequence_and_geometry_validated"
    else
      json_state "$state" "$cid" failed "$gpu" "$rc" "NBB2 output failed chain/sequence/geometry validation"
    fi
  else
    json_state "$state" "$cid" failed "$gpu" "$rc" "NanoBodyBuilder2 failed or did not write output"
  fi
  echo "NBB2_EXIT cid=$cid gpu=$gpu rc=$rc time=$(date -Is)"
  return 0
  )
}

run_gpu_lane() {
  local gpu=$1 ordinal=$2 total=$3 index=0
  exec > >(tee -a "$DOCKING_ROOT/logs/nbb2/gpu_${gpu}.log") 2>&1
  echo "NBB2_GPU_LANE_START gpu=$gpu ordinal=$ordinal total=$total time=$(date -Is)"
  while IFS=$'\t' read -r cid seq _rest; do
    [[ "$cid" == candidate_id ]] && continue
    [[ -z "$cid" ]] && continue
    if (( CANDIDATE_LIMIT > 0 && index >= CANDIDATE_LIMIT )); then
      break
    fi
    if (( index % total == ordinal )); then
      run_candidate "$cid" "$seq" "$gpu"
    fi
    index=$((index + 1))
  done < "$MANIFEST"
  echo "NBB2_GPU_LANE_COMPLETE gpu=$gpu time=$(date -Is)"
}

IFS=',' read -r -a gpu_array <<< "$GPU_IDS"
pids=()
for i in "${!gpu_array[@]}"; do
  gpu=${gpu_array[$i]}
  run_gpu_lane "$gpu" "$i" "${#gpu_array[@]}" &
  pids+=("$!")
done
rc=0
for pid in "${pids[@]}"; do
  wait "$pid" || rc=1
done
exit "$rc"
