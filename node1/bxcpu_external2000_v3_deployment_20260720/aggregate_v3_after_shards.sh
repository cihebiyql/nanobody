#!/usr/bin/env bash
# Run after the two V3 node shards and publish the shard-specific aggregation.
set -euo pipefail
umask 027

CACHE_ROOT="${PVRIG_BXCPU_CACHE:-$HOME/.local/opt}"
PROJECT_NAME=pvrig_v29_external2000_sequences_v3_20260720
BUNDLE_ARCHIVE="$HOME/${PROJECT_NAME}.tar.zst"
PUBLISH_ROOT="${PVRIG_V3_PUBLISH_ROOT:-$HOME/${PROJECT_NAME}_bxcpu_results}"
WORK_BASE="${SLURM_TMPDIR:-/tmp}/${USER}/${PROJECT_NAME}/aggregate_${SLURM_JOB_ID:-manual}"
LOCAL_ENV="$WORK_BASE/haddock3-env"
NUMPY_OVERLAY="$WORK_BASE/numpy-el7-overlay"
LOCAL_PROJECT="$WORK_BASE/$PROJECT_NAME"
mkdir -p "$WORK_BASE" "$LOCAL_ENV" "$NUMPY_OVERLAY" "$PUBLISH_ROOT/reports" "$PUBLISH_ROOT/markers"

for archive in haddock3_runtime_core.tar.gz haddock3_runtime_python.tar.gz haddock3_runtime_lib.tar.gz; do
    tar -xzf "$CACHE_ROOT/$archive" -C "$LOCAL_ENV"
done
tar -xzf "$CACHE_ROOT/numpy_el7_overlay_2.0.1.tar.gz" -C "$NUMPY_OVERLAY"
export PYTHONNOUSERSITE=1
export PYTHONPATH="$NUMPY_OVERLAY/lib/python3.11/site-packages"
"$LOCAL_ENV/bin/zstd" -dc "$BUNDLE_ARCHIVE" | tar -xf - -C "$WORK_BASE"

rsync -a "$PUBLISH_ROOT/status/jobs/" "$LOCAL_PROJECT/status/jobs/"
rsync -a "$PUBLISH_ROOT/results/" "$LOCAL_PROJECT/results/"
set +e
"$LOCAL_ENV/bin/python" "$LOCAL_PROJECT/scripts/aggregate_external2000_results.py" --root "$LOCAL_PROJECT"
aggregate_rc=$?
set -e
[[ "$aggregate_rc" == 0 || "$aggregate_rc" == 1 ]] || exit "$aggregate_rc"
"$LOCAL_ENV/bin/python" - "$LOCAL_PROJECT/reports/EXTERNAL2000_AGGREGATION.json" <<"PY"
import json, sys
p = json.load(open(sys.argv[1]))
assert p["status"] in {"NOT_READY", "COMPLETE", "COMPLETE_WITH_TECHNICAL_NA"}
assert p["unlockable"] is False
assert p["job_count"] == 4000 and p["candidate_count"] == 2000
assert p["gates"]["external_manifest"]["status"] == "PASS"
PY
rsync -a "$LOCAL_PROJECT/reports/external_job_results.tsv" \
    "$LOCAL_PROJECT/reports/external_pose_scores.tsv" \
    "$LOCAL_PROJECT/reports/external_candidate_dual.tsv" \
    "$LOCAL_PROJECT/reports/EXTERNAL2000_AGGREGATION.json" "$PUBLISH_ROOT/reports/"
printf 'aggregator_exit=%s completed_at=%s\n' "$aggregate_rc" "$(date -u +%FT%TZ)" \
    > "$PUBLISH_ROOT/markers/v3_aggregation.done"
