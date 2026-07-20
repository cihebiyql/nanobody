#!/usr/bin/env bash
set -euo pipefail
DEPLOY=$(cd "$(dirname "$0")" && pwd)
NAME=pvrig_v29_bxcpu_stage2_10500_v1_20260720
ROOT="${PVRIG_STAGE2_PUBLISH_ROOT:-$HOME/${NAME}_bxcpu_results}"
ARCHIVE="$HOME/$NAME.tar.zst"
EXPECTED=e61156725be19e5f9ca564c176f2d2104dadd303d2bde16aebaa1b0143b466e0
[[ $(sha256sum "$ARCHIVE" | awk '{print $1}') == "$EXPECTED" ]] || { echo archive_hash_mismatch >&2; exit 65; }
mkdir -p "$ROOT" "$ROOT/markers"
active=$(squeue -h -u "$USER" -n pvrig-v29-s2-10500 | wc -l)
[[ "$active" -eq 0 ]] || { echo "Stage2 already active: $active" >&2; exit 66; }
array=$(sbatch --parsable --partition=amd_256q --job-name=pvrig-v29-s2-10500 --nodes=1 --ntasks=1 --cpus-per-task=64 --mem=230G --exclusive --time=24:00:00 --array=1-8%8 --output="$ROOT/slurm-%x-%A_%a.out" --error="$ROOT/slurm-%x-%A_%a.err" --export=ALL,PVRIG_V3_NODE_CONCURRENCY=16,PVRIG_V3_PUBLISH_ROOT="$ROOT" "$DEPLOY/bxcpu_stage2_10500_eight_node_worker.sh")
array=${array%%;*}
dep=afterany;for s in {1..8};do dep+=:${array}_${s};done
agg=$(sbatch --parsable --dependency="$dep" --partition=amd_256q --job-name=pvrig-v29-s2-agg --nodes=1 --ntasks=1 --cpus-per-task=1 --mem=4G --exclusive --time=02:00:00 --output="$ROOT/slurm-%x-%j.out" --error="$ROOT/slurm-%x-%j.err" "$DEPLOY/aggregate_stage2_10500_after_shards.sh")
agg=${agg%%;*}
printf 'array_job_id=%s\naggregate_job_id=%s\nsubmitted_at=%s\n' "$array" "$agg" "$(date -u +%FT%TZ)" | tee "$ROOT/markers/stage2_10500_submission.receipt"
