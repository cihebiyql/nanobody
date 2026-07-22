#!/usr/bin/env bash
set -Eeuo pipefail
: "${JOB_ID:?JOB_ID is required}"
BASE=${BASE:-/mnt/d/work/抗体/code/pvrig_500k_generation_20260721}
SYNC="$BASE/run/pvrig_1m_cpu_fixed_pose500k_raw_v4_20260722/bxcpu_results_${JOB_ID}"
OUT="$BASE/run/pvrig_1m_screening_pool_exact1m_v1_20260722"
while [[ ! -s "$SYNC/SYNC_COMPLETE.json" ]]; do sleep 30; done
python3 "$BASE/scripts/finalize_cpu_fixed_pose_screening_1m.py" \
  --sync-root "$SYNC" \
  --existing "$BASE/run/pvrig_500k_cpu_control_combined394k_v1_20260721/combined_exact_unique_fast_qc_pass.tsv.gz" \
  --existing "$BASE/run/pvrig_1m_cpu_topup305705_v1_20260722_frozen/route_quota_exact_unique.tsv.gz" \
  --positive-cdr "$BASE/run/pvrig_1m_cpu_fixed_pose500k_raw_v4_20260722/inputs/positive11_cdr_imgt.tsv" \
  --positive-fasta "$BASE/run/pvrig_1m_cpu_fixed_pose500k_raw_v4_20260722/inputs/positive11.fasta" \
  --output-dir "$OUT" --target-new 300000 \
  >"$BASE/run/pvrig_1m_cpu_fixed_pose500k_raw_v4_20260722/finalize.log" 2>&1
/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe node1 "mkdir -p /data/qlyu/projects/pvrig_1m_screening_pool_exact1m_v1_20260722"
rsync -a --partial --append-verify -e /mnt/c/WINDOWS/System32/OpenSSH/ssh.exe \
  "$OUT/" node1:/data/qlyu/projects/pvrig_1m_screening_pool_exact1m_v1_20260722/
