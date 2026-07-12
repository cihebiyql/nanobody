#!/usr/bin/env bash
set -uo pipefail

ROOT=${DOCKING_SHARD_ROOT:?DOCKING_SHARD_ROOT is required}
MODE=${DOCKING_MODE:-all}
GPU_ID=${DOCKING_GPU_ID:-1}
MAX_LOAD1=${DOCKING_MAX_LOAD1:-64}
LOAD_WAIT_SECONDS=${DOCKING_LOAD_WAIT_SECONDS:-60}
NBB2=/data/qlyu/anaconda3/envs/boltz/bin/NanoBodyBuilder2
HADDOCK3=/data/qlyu/anaconda3/envs/haddock3/bin/haddock3
EVIDENCE_BOUNDARY=guided_docking_geometry_proxy_not_binding_or_blocker_proof

mkdir -p "$ROOT"/{logs,reports,monomer,haddock3,manifests}
exec > >(tee -a "$ROOT/logs/${MODE}.$(date +%Y%m%d_%H%M%S).log") 2>&1
cd "$ROOT" || exit 1

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

wait_for_gpu() {
  while true; do
    used_mb=$(nvidia-smi --id="$GPU_ID" --query-gpu=memory.used --format=csv,noheader,nounits | tr -d ' ')
    if [[ "$used_mb" -lt 1000 ]]; then
      return
    fi
    echo "GPU_GATE_WAIT gpu=$GPU_ID memory_used_mb=$used_mb time=$(date -Is)"
    sleep "$LOAD_WAIT_SECONDS"
  done
}

status=0
if [[ "$MODE" == "monomer" || "$MODE" == "all" ]]; then
  while IFS=$'\t' read -r cid seq sha cdr3range selection_rank; do
    [[ "$cid" == candidate_id ]] && continue
    [[ -z "$cid" ]] && continue
    raw="monomer/$cid/${cid}_nanobodybuilder2_raw.pdb"
    norm="monomer/$cid/${cid}_nanobodybuilder2_chainA.pdb"
    mkdir -p "monomer/$cid" "reports/$cid" "haddock3/$cid/data" "haddock3/$cid/logs"
    if [[ ! -s "$raw" ]]; then
      wait_for_load
      wait_for_gpu
      echo "NBB2_START cid=$cid gpu=$GPU_ID time=$(date -Is)"
      CUDA_VISIBLE_DEVICES="$GPU_ID" "$NBB2" -H "$seq" -o "$raw" --n_threads 2 -v >"logs/${cid}_nanobodybuilder2.log" 2>&1
      rc=$?
      if [[ $rc -ne 0 ]]; then
        CUDA_VISIBLE_DEVICES="$GPU_ID" "$NBB2" -H "$seq" -o "$raw" --n_threads 2 -u -v >"logs/${cid}_nanobodybuilder2_unrefined.log" 2>&1
        rc=$?
      fi
      echo "NBB2_EXIT cid=$cid rc=$rc time=$(date -Is)"
      if [[ $rc -ne 0 ]]; then status=1; continue; fi
    fi
    python3 scripts/normalize_pdb_chain.py --in-pdb "$raw" --out-pdb "$norm" --chain-id A --expected-residue-count "${#seq}" >"logs/${cid}_normalize.log" 2>&1 || { status=1; continue; }
    python3 scripts/validate_pdb_sequence.py --pdb "$norm" --chain A --expected-seq "$seq" --out-json "reports/$cid/${cid}_sequence_validation.json" >"logs/${cid}_sequence_validation.log" 2>&1 || { status=1; continue; }
    python3 scripts/pdb_geometry_qc.py --pdb "$norm" --chain A --out-json "reports/$cid/${cid}_monomer_geometry_qc.json" >"logs/${cid}_geometry.log" 2>&1 || { status=1; continue; }
    cp "$norm" "haddock3/$cid/data/${cid}_vhh_chainA.pdb"
    cp inputs/pvrig_8x6b_chainB.pdb "haddock3/$cid/data/pvrig_8x6b_chainB.pdb"
  done < manifests/runtime_candidates.tsv
  [[ "$status" == 0 ]] && touch monomer.complete
fi

if [[ "$MODE" == "docking" || "$MODE" == "all" ]]; then
  while IFS=$'\t' read -r cid seq sha cdr3range selection_rank; do
    [[ "$cid" == candidate_id ]] && continue
    [[ -z "$cid" ]] && continue
    selected_dir="haddock3/$cid/run_${cid}_pvrig_hotspot/6_seletopclusts"
    if find "$selected_dir" -maxdepth 1 \( -name 'cluster_*_model_*.pdb' -o -name 'cluster_*_model_*.pdb.gz' \) -print -quit 2>/dev/null | grep -q .; then
      echo "HADDOCK_SKIP_COMPLETE cid=$cid"
      continue
    fi
    if [[ ! -s "haddock3/$cid/data/${cid}_vhh_chainA.pdb" ]]; then
      echo "HADDOCK_MISSING_MONOMER cid=$cid"
      status=1
      continue
    fi
    wait_for_load
    echo "HADDOCK_START cid=$cid time=$(date -Is)"
    (cd "haddock3/$cid" && "$HADDOCK3" "${cid}_pvrig_hotspot.cfg" >"logs/${cid}_haddock3.log" 2>&1)
    rc=$?
    echo "HADDOCK_EXIT cid=$cid rc=$rc time=$(date -Is)"
    [[ $rc -eq 0 ]] || status=1
  done < manifests/runtime_candidates.tsv
  [[ "$status" == 0 ]] && touch docking.complete
fi

echo "SHARD_COMPLETE mode=$MODE status=$status evidence_boundary=$EVIDENCE_BOUNDARY time=$(date -Is)"
exit "$status"
