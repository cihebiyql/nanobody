#!/usr/bin/env bash
set -Eeuo pipefail
BASE=${BASE:-/mnt/d/work/抗体/code/pvrig_500k_generation_20260721}
ROOT=${ROOT:-$BASE/run/pvrig_1m_cpu_fixed_pose_selected300k_metrics_v1_20260722}
MIRROR="$ROOT/remote_mirror"; OUT="$ROOT/aggregated"; SELECT="$BASE/run/pvrig_1m_fixed_pose_top150k_structure_input_v1_20260722"
LOCK_DIR=${LOCK_DIR:-$BASE/run/.locks}
mkdir -p "$LOCK_DIR"
exec 9>"$LOCK_DIR/pvrig_fixed_pose300k_metrics_finalize.lock"
if ! flock -n 9; then
 echo "another fixed-pose 300k metrics finalizer is active" >&2
 exit 0
fi
while [[ ! -s "$ROOT/METRICS_SYNC_COMPLETE.json" ]]; do sleep 60; done
mkdir -p "$OUT"
python3 - "$ROOT/JOB_CHAIN.json" >"$OUT/job_paths.env" <<'PY'
import json,sys
j=json.load(open(sys.argv[1]))['jobs']
for k,v in j.items(): print(f'{k.upper()}={v}')
PY
source "$OUT/job_paths.env"
python3 "$BASE/scripts/aggregate_bxcpu_sapiens_results.py" "$MIRROR/results/sapiens_full_$SAPIENS" -o "$OUT/sapiens_all.tsv.gz" --expected-records 300000
python3 "$BASE/scripts/aggregate_bxcpu_abnativ_results.py" "$MIRROR/results/abnativ_full_$ABNATIV" -o "$OUT/abnativ_all.tsv.gz" --expected-records 300000
python3 "$BASE/scripts/build_bxcpu_prefilter_table.py" \
 --candidates "$ROOT/input/fixed_pose_selected300k_candidates.tsv.gz" \
 --risk "$MIRROR/results/risk_$RISK/sequence_risk_proxy_all.tsv.gz" \
 --binding "$MIRROR/results/binding_priors_$BINDING.tsv.gz" \
 --sapiens "$OUT/sapiens_all.tsv.gz" --abnativ "$OUT/abnativ_all.tsv.gz" \
 --anarci "$MIRROR/anarci300k_v1/aggregated_$ANARCI/anarci_imgt_qc_all.tsv.gz" \
 --output "$OUT/fixed_pose300k_prefilter_all.tsv.gz" --summary "$OUT/PREFILTER_SUMMARY.json"
python3 "$BASE/scripts/select_fixed_pose300k_for_structure.py" --input "$OUT/fixed_pose300k_prefilter_all.tsv.gz" --output-dir "$SELECT" --target 150000 \
 >"$ROOT/select_structure.log" 2>&1
/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe node1 "mkdir -p /data/qlyu/projects/pvrig_1m_fixed_pose_top150k_structure_input_v1_20260722"
rsync -a --partial --append-verify -e /mnt/c/WINDOWS/System32/OpenSSH/ssh.exe "$SELECT/" node1:/data/qlyu/projects/pvrig_1m_fixed_pose_top150k_structure_input_v1_20260722/
