#!/usr/bin/env bash
set -euo pipefail
DEPLOY=$(cd "$(dirname "$0")" && pwd)
PROJECT=pvrig_priority_top7500_dualreceptor_multiseed_handoff_v3_20260722
ROOT="${PVRIG_TOP7500_PUBLISH_ROOT:-$HOME/${PROJECT}_bxcpu_results}"
ARCHIVE="$HOME/$PROJECT.tar.zst"
EXPECTED=359a695f4d6d823ae7f0cf76abaf45e7665ec404bf4a38f5179d66abc86f6919
[[ $(sha256sum "$ARCHIVE" | awk '{print $1}') == "$EXPECTED" ]] || { echo archive_hash_mismatch >&2; exit 65; }
mkdir -p "$ROOT" "$ROOT/markers" "$ROOT/status/jobs" "$ROOT/results" "$ROOT/compressed_queue" "$ROOT/reports"
[[ $(squeue -h -u "$USER" -n pvrig-top7500-25k | wc -l) -eq 0 ]] || { echo active_campaign_exists >&2; exit 66; }
array=$(sbatch --parsable --partition=amd_256q --job-name=pvrig-top7500-25k \
    --nodes=1 --ntasks=1 --cpus-per-task=64 --mem=230G --exclusive --time=24:00:00 \
    --array=1-8%8 --output="$ROOT/slurm-%x-%A_%a.out" --error="$ROOT/slurm-%x-%A_%a.err" \
    --export=ALL,PVRIG_TOP7500_NODE_CONCURRENCY=16,PVRIG_TOP7500_PUBLISH_ROOT="$ROOT",PVRIG_TOP7500_ARCHIVE_SHA256="$EXPECTED" \
    "$DEPLOY/bxcpu_top7500_25k_eight_node_worker.sh")
array=${array%%;*}
dep=afterany; for shard in {1..8}; do dep+=:${array}_${shard}; done
audit=$(sbatch --parsable --dependency="$dep" --partition=amd_256q --job-name=pvrig-top7500-audit \
    --nodes=1 --ntasks=1 --cpus-per-task=1 --mem=4G --exclusive --time=01:00:00 \
    --output="$ROOT/slurm-%x-%j.out" --error="$ROOT/slurm-%x-%j.err" \
    --export=ALL,PVRIG_TOP7500_PUBLISH_ROOT="$ROOT" "$DEPLOY/technical_status_after_shards.sh")
audit=${audit%%;*}
printf 'array_job_id=%s\naudit_job_id=%s\narchive_sha256=%s\nresult_root=%s\nsubmitted_at=%s\n' \
    "$array" "$audit" "$EXPECTED" "$ROOT" "$(date -u +%FT%TZ)" | tee "$ROOT/markers/SUBMISSION_RECEIPT.txt"
