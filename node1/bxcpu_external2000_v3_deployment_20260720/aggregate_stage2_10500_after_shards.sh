#!/usr/bin/env bash
set -euo pipefail
DEPLOY="$HOME/.local/share/bxcpu_external2000_v3_deployment_20260720"
NAME=pvrig_v29_bxcpu_stage2_10500_v1_20260720
ARCHIVE="$HOME/$NAME.tar.zst"
PUBLISH_ROOT="${PVRIG_STAGE2_PUBLISH_ROOT:-$HOME/${NAME}_bxcpu_results}"
TMP="${SLURM_TMPDIR:-/tmp}/${USER}/${NAME}/aggregate_${SLURM_JOB_ID:-manual}"
mkdir -p "$TMP" "$PUBLISH_ROOT/reports" "$PUBLISH_ROOT/markers"
~/.local/opt/haddock3-2025.11.0/bin/zstd -dc -q "$ARCHIVE" | tar -xf - -C "$TMP"
python3 "$DEPLOY/aggregate_stage2_10500.py" --publish-root "$PUBLISH_ROOT" --manifest "$TMP/$NAME/manifests/stage2_jobs.tsv"
printf 'aggregate_job=%s completed_at=%s\n' "${SLURM_JOB_ID:-manual}" "$(date -u +%FT%TZ)" > "$PUBLISH_ROOT/markers/stage2_10500_aggregation.done"
