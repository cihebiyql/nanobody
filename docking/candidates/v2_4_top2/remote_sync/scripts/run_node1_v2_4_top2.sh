#!/usr/bin/env bash
set -uo pipefail
ROOT=/data/qlyu/projects/pvrig_v2_4_top2
BIN_BOLTZ=/data/qlyu/anaconda3/envs/boltz/bin
BIN_HADDOCK=/data/qlyu/anaconda3/envs/haddock3/bin
mkdir -p "$ROOT/logs" "$ROOT/reports" "$ROOT/monomer" "$ROOT/haddock3"
exec > >(tee -a "$ROOT/logs/run_node1_v2_4_top2.$(date +%Y%m%d_%H%M%S).log") 2>&1
cd "$ROOT" || exit 1
printf 'run_start=%s\n' "$(date -Is)"
hostname; whoami
printf 'gpu_snapshot_start\n'
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits || true
printf 'tool_versions\n'
"$BIN_BOLTZ/NanoBodyBuilder2" --help | head -n 3 || true
"$BIN_HADDOCK/haddock3" --help | head -n 3 || true
python3 scripts/make_candidate_haddock_assets.py
python3 - <<'PY' > manifests/remote_candidate_env.tsv
import csv, pathlib
root=pathlib.Path('/data/qlyu/projects/pvrig_v2_4_top2')
with (root/'manifests/selected_candidates_manifest.tsv').open(newline='') as f:
    rows=list(csv.DictReader(f, delimiter='\t'))
print('candidate_id\tsequence\texpected_sha256\tcdr3_range')
for r in rows:
    print(f"{r['candidate_id']}\t{r['vhh_seq']}\t{r['vhh_seq_sha256']}\t{r['cdr3_start_1based']}-{r['cdr3_end_1based']}")
PY
status=0
while IFS=$'\t' read -r cid seq sha cdr3range; do
  [[ "$cid" == candidate_id ]] && continue
  [[ -z "$cid" ]] && continue
  echo "===== candidate $cid seq_sha=$sha cdr3=$cdr3range ====="
  mkdir -p "monomer/$cid" "reports/$cid" "haddock3/$cid/data" "haddock3/$cid/logs"
  raw="monomer/$cid/${cid}_nanobodybuilder2_raw.pdb"
  norm="monomer/$cid/${cid}_nanobodybuilder2_chainA.pdb"
  if [[ ! -s "$raw" ]]; then
    echo "NBB2_START $cid $(date -Is)"
    CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-1} PATH="$BIN_BOLTZ:$PATH" "$BIN_BOLTZ/NanoBodyBuilder2" -H "$seq" -o "$raw" --n_threads 4 -v >"logs/${cid}_nanobodybuilder2.log" 2>&1
    rc=$?
    echo "NBB2_EXIT $cid rc=$rc $(date -Is)"
    if [[ $rc -ne 0 ]]; then status=1; tail -80 "logs/${cid}_nanobodybuilder2.log"; continue; fi
  else
    echo "NBB2_SKIP existing $raw"
  fi
  python3 scripts/normalize_pdb_chain.py --in-pdb "$raw" --out-pdb "$norm" --chain-id A --expected-residue-count 130 >"logs/${cid}_normalize.log" 2>&1
  rc=$?; echo "NORMALIZE_EXIT $cid rc=$rc"; if [[ $rc -ne 0 ]]; then status=1; cat "logs/${cid}_normalize.log"; continue; fi
  python3 scripts/validate_pdb_sequence.py --pdb "$norm" --chain A --expected-seq "$seq" --out-json "reports/$cid/${cid}_sequence_validation.json" >"logs/${cid}_sequence_validation.log" 2>&1
  rc=$?; echo "SEQ_VALIDATE_EXIT $cid rc=$rc"; if [[ $rc -ne 0 ]]; then status=1; cat "logs/${cid}_sequence_validation.log"; continue; fi
  python3 scripts/pdb_geometry_qc.py --pdb "$norm" --chain A --out-json "reports/$cid/${cid}_monomer_geometry_qc.json" >"logs/${cid}_monomer_geometry_qc.log" 2>&1
  cp "$norm" "haddock3/$cid/data/${cid}_vhh_chainA.pdb"
  cp inputs/pvrig_8x6b_chainB.pdb "haddock3/$cid/data/pvrig_8x6b_chainB.pdb"
  python3 scripts/pdb_geometry_qc.py --pdb "haddock3/$cid/data/pvrig_8x6b_chainB.pdb" --chain B --out-json "reports/$cid/${cid}_pvrig_receptor_geometry_qc.json" >"logs/${cid}_pvrig_receptor_geometry_qc.log" 2>&1
  echo "HADDOCK_START $cid $(date -Is)"
  (cd "haddock3/$cid" && "$BIN_HADDOCK/haddock3" "${cid}_pvrig_hotspot.cfg" >"logs/${cid}_haddock3_run.log" 2>&1)
  rc=$?; echo "HADDOCK_EXIT $cid rc=$rc $(date -Is)"
  if [[ $rc -ne 0 ]]; then status=1; tail -120 "haddock3/$cid/logs/${cid}_haddock3_run.log"; continue; fi
  find "haddock3/$cid/run_${cid}_pvrig_hotspot" -maxdepth 4 \( -name '*.pdb' -o -name '*.pdb.gz' -o -name '*.tsv' -o -name '*.out' -o -name '*.json' \) | sort >"reports/$cid/${cid}_haddock_outputs.txt"
  sha256sum "$norm" "haddock3/$cid/data/pvrig_8x6b_chainB.pdb" "haddock3/$cid/${cid}_pvrig_hotspot.cfg" >"reports/$cid/${cid}_asset_sha256.tsv"
done < manifests/remote_candidate_env.tsv
sha256sum inputs/* manifests/* scripts/*.py haddock3/*/*.cfg haddock3/*/data/* 2>/dev/null | sort > manifests/remote_project_sha256.tsv
printf 'gpu_snapshot_end\n'
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits || true
printf 'run_end=%s status=%s\n' "$(date -Is)" "$status"
exit "$status"
