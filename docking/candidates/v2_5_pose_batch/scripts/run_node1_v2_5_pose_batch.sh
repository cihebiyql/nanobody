#!/usr/bin/env bash
set -uo pipefail

ROOT=${V2_5_REMOTE_ROOT:-/data/qlyu/projects/pvrig_v2_5_pose_batch}
BIN_BOLTZ=${V2_5_BIN_BOLTZ:-/data/qlyu/anaconda3/envs/boltz/bin}
BIN_HADDOCK=${V2_5_BIN_HADDOCK:-/data/qlyu/anaconda3/envs/haddock3/bin}
GPU_DEVICES=${V2_5_CUDA_DEVICES:-1}
NBB2_THREADS=${V2_5_NBB2_THREADS:-4}
RUN_HADDOCK3=${V2_5_RUN_HADDOCK3:-0}
MAX_LOAD1=${V2_5_MAX_LOAD1:-32}
ALLOW_NBB2_UNREFINED_FALLBACK=${V2_5_ALLOW_NBB2_UNREFINED_FALLBACK:-1}
EVIDENCE_BOUNDARY=computational_pose_qc_proxy_not_binding_or_blocker_proof

mkdir -p "$ROOT/logs" "$ROOT/reports" "$ROOT/monomer" "$ROOT/haddock3" "$ROOT/manifests"
exec > >(tee -a "$ROOT/logs/run_node1_v2_5_pose_batch.$(date +%Y%m%d_%H%M%S).log") 2>&1
cd "$ROOT" || exit 1

printf 'run_start=%s\n' "$(date -Is)"
printf 'remote_root=%s\n' "$ROOT"
printf 'evidence_boundary=%s\n' "$EVIDENCE_BOUNDARY"
printf 'gpu_devices=%s nbb2_threads=%s run_haddock3=%s max_load1=%s\n' "$GPU_DEVICES" "$NBB2_THREADS" "$RUN_HADDOCK3" "$MAX_LOAD1"
hostname; whoami
printf 'gpu_snapshot_start\n'
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits || true
printf 'tool_versions\n'
"$BIN_BOLTZ/NanoBodyBuilder2" --help | head -n 3 || true
"$BIN_HADDOCK/haddock3" --help | head -n 3 || true

python3 scripts/make_candidate_haddock_assets.py
V2_5_REMOTE_ROOT_FOR_PY="$ROOT" python3 - <<'PY' > manifests/remote_candidate_env.tsv
import csv
import os
from pathlib import Path
root = Path(os.environ['V2_5_REMOTE_ROOT_FOR_PY'])
with (root / 'manifests/selected_candidates_manifest.tsv').open(newline='') as f:
    rows = list(csv.DictReader(f, delimiter='\t'))
print('candidate_id\tsequence\texpected_sha256\tcdr3_range\tselection_rank\tevidence_boundary')
for row in rows:
    print(f"{row['candidate_id']}\t{row['vhh_seq']}\t{row['vhh_seq_sha256']}\t{row['cdr3_start_1based']}-{row['cdr3_end_1based']}\t{row['selection_rank']}\t{row['evidence_boundary']}")
PY

check_load_gate() {
  python3 - "$MAX_LOAD1" <<'PY'
import sys
threshold = float(sys.argv[1])
with open('/proc/loadavg') as f:
    load1 = float(f.read().split()[0])
if load1 > threshold:
    print(f'LOAD_GATE_REFUSE load1={load1} threshold={threshold}')
    sys.exit(2)
print(f'LOAD_GATE_OK load1={load1} threshold={threshold}')
PY
}

run_nbb2() {
  local cid="$1" seq="$2" raw="$3" log="$4"
  CUDA_VISIBLE_DEVICES="$GPU_DEVICES" PATH="$BIN_BOLTZ:$PATH" \
    "$BIN_BOLTZ/NanoBodyBuilder2" -H "$seq" -o "$raw" --n_threads "$NBB2_THREADS" -v >"$log" 2>&1
}

status=0
while IFS=$'\t' read -r cid seq sha cdr3range selection_rank evidence_boundary; do
  [[ "$cid" == candidate_id ]] && continue
  [[ -z "$cid" ]] && continue
  echo "===== candidate $selection_rank $cid seq_sha=$sha cdr3=$cdr3range ====="
  echo "EVIDENCE_BOUNDARY $cid $evidence_boundary"
  mkdir -p "monomer/$cid" "reports/$cid" "haddock3/$cid/data" "haddock3/$cid/logs"
  raw="monomer/$cid/${cid}_nanobodybuilder2_raw.pdb"
  norm="monomer/$cid/${cid}_nanobodybuilder2_chainA.pdb"
  if [[ ! -s "$raw" ]]; then
    echo "NBB2_START $cid $(date -Is)"
    run_nbb2 "$cid" "$seq" "$raw" "logs/${cid}_nanobodybuilder2.log"
    rc=$?
    echo "NBB2_EXIT $cid rc=$rc $(date -Is)"
    if [[ $rc -ne 0 && "$ALLOW_NBB2_UNREFINED_FALLBACK" == "1" ]]; then
      echo "NBB2_FALLBACK_UNREFINED_START $cid $(date -Is)"
      CUDA_VISIBLE_DEVICES="$GPU_DEVICES" PATH="$BIN_BOLTZ:$PATH" \
        "$BIN_BOLTZ/NanoBodyBuilder2" -H "$seq" -o "$raw" --n_threads "$NBB2_THREADS" -u -v >"logs/${cid}_nanobodybuilder2_unrefined_fallback.log" 2>&1
      rc=$?
      echo "NBB2_FALLBACK_UNREFINED_EXIT $cid rc=$rc $(date -Is)"
    fi
    if [[ $rc -ne 0 ]]; then status=1; tail -80 "logs/${cid}_nanobodybuilder2.log"; continue; fi
  else
    echo "NBB2_SKIP existing $raw"
  fi

  python3 scripts/normalize_pdb_chain.py --in-pdb "$raw" --out-pdb "$norm" --chain-id A --expected-residue-count 130 >"logs/${cid}_normalize.log" 2>&1
  rc=$?; echo "NORMALIZE_EXIT $cid rc=$rc"; if [[ $rc -ne 0 ]]; then status=1; cat "logs/${cid}_normalize.log"; continue; fi
  python3 scripts/validate_pdb_sequence.py --pdb "$norm" --chain A --expected-seq "$seq" --out-json "reports/$cid/${cid}_sequence_validation.json" >"logs/${cid}_sequence_validation.log" 2>&1
  rc=$?; echo "SEQ_VALIDATE_EXIT $cid rc=$rc"; if [[ $rc -ne 0 ]]; then status=1; cat "logs/${cid}_sequence_validation.log"; continue; fi
  python3 scripts/pdb_geometry_qc.py --pdb "$norm" --chain A --out-json "reports/$cid/${cid}_monomer_geometry_qc.json" >"logs/${cid}_monomer_geometry_qc.log" 2>&1
  rc=$?; echo "MONOMER_GEOMETRY_QC_EXIT $cid rc=$rc"; if [[ $rc -ne 0 ]]; then status=1; cat "logs/${cid}_monomer_geometry_qc.log"; continue; fi
  cp "$norm" "haddock3/$cid/data/${cid}_vhh_chainA.pdb"
  cp inputs/pvrig_8x6b_chainB.pdb "haddock3/$cid/data/pvrig_8x6b_chainB.pdb"
  python3 scripts/pdb_geometry_qc.py --pdb "haddock3/$cid/data/pvrig_8x6b_chainB.pdb" --chain B --out-json "reports/$cid/${cid}_pvrig_receptor_geometry_qc.json" >"logs/${cid}_pvrig_receptor_geometry_qc.log" 2>&1
  rc=$?; echo "PVRIG_RECEPTOR_GEOMETRY_QC_EXIT $cid rc=$rc"; if [[ $rc -ne 0 ]]; then status=1; cat "logs/${cid}_pvrig_receptor_geometry_qc.log"; continue; fi
  sha256sum "$norm" "haddock3/$cid/data/pvrig_8x6b_chainB.pdb" "haddock3/$cid/${cid}_pvrig_hotspot.cfg" >"reports/$cid/${cid}_asset_sha256.tsv"

done < manifests/remote_candidate_env.tsv

if [[ "$RUN_HADDOCK3" != "1" ]]; then
  echo "HADDOCK3_GATED_SKIP set V2_5_RUN_HADDOCK3=1 after monomer/sequence/geometry QC review"
else
  while IFS=$'\t' read -r cid seq sha cdr3range selection_rank evidence_boundary; do
    [[ "$cid" == candidate_id ]] && continue
    [[ -z "$cid" ]] && continue
    echo "HADDOCK_GATE_CHECK $cid $(date -Is)"
    check_load_gate || exit $?
    if [[ ! -s "haddock3/$cid/data/${cid}_vhh_chainA.pdb" || ! -s "haddock3/$cid/data/pvrig_8x6b_chainB.pdb" ]]; then
      echo "HADDOCK_REFUSE_MISSING_QC_ASSETS $cid"
      status=1
      continue
    fi
    echo "HADDOCK_START $cid $(date -Is)"
    (cd "haddock3/$cid" && "$BIN_HADDOCK/haddock3" "${cid}_pvrig_hotspot.cfg" >"logs/${cid}_haddock3_run.log" 2>&1)
    rc=$?; echo "HADDOCK_EXIT $cid rc=$rc $(date -Is)"
    if [[ $rc -ne 0 ]]; then status=1; tail -120 "haddock3/$cid/logs/${cid}_haddock3_run.log"; continue; fi
    find "haddock3/$cid/run_${cid}_pvrig_hotspot" -maxdepth 4 \( -name '*.pdb' -o -name '*.pdb.gz' -o -name '*.tsv' -o -name '*.out' -o -name '*.json' \) | sort >"reports/$cid/${cid}_haddock_outputs.txt"
  done < manifests/remote_candidate_env.tsv
fi

sha256sum inputs/* manifests/* scripts/*.py scripts/*.sh haddock3/*/*.cfg haddock3/*/data/* 2>/dev/null | sort > manifests/remote_project_sha256.tsv
printf 'gpu_snapshot_end\n'
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits || true
printf 'run_end=%s status=%s\n' "$(date -Is)" "$status"
exit "$status"
