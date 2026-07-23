#!/usr/bin/env bash
set -euo pipefail
umask 027

CAMPAIGN=pvrig_c2_new4220_seed42_3047_v1_20260723
PACKAGE_NAME=c2_new4220_dualreceptor_seed42_3047_handoff_v1
DEPLOY_ROOT="${PVRIG_C2_EXTRA_DEPLOY_ROOT:-$HOME/.local/share/$CAMPAIGN}"
BUNDLE_ARCHIVE="${PVRIG_C2_EXTRA_ARCHIVE:-$HOME/${PACKAGE_NAME}_20260723.tar.gz}"
PUBLISH_ROOT="${PVRIG_C2_EXTRA_PUBLISH_ROOT:-$HOME/${CAMPAIGN}_bxcpu_results}"
EXPECTED_ARCHIVE_SHA256="${PVRIG_C2_EXTRA_ARCHIVE_SHA256:?archive SHA256 is required}"
EXPECTED_MANIFEST_SHA256="${PVRIG_C2_EXTRA_MANIFEST_SHA256:?manifest SHA256 is required}"
PYTHON="$HOME/.local/opt/haddock3-2025.11.0/bin/python"
WORK="${SLURM_TMPDIR:-/tmp}/${USER}/${CAMPAIGN}_audit/${SLURM_JOB_ID:-manual}"
mkdir -p "$WORK" "$PUBLISH_ROOT/reports"
[[ $(sha256sum "$BUNDLE_ARCHIVE" | awk '{print $1}') == "$EXPECTED_ARCHIVE_SHA256" ]]
tar -xzf "$BUNDLE_ARCHIVE" -C "$WORK"
"$PYTHON" "$DEPLOY_ROOT/technical_audit_seed42_3047.py" \
    --manifest "$WORK/$PACKAGE_NAME/manifests/docking_jobs.tsv" \
    --publish-root "$PUBLISH_ROOT" --manifest-sha256 "$EXPECTED_MANIFEST_SHA256" \
    --output "$PUBLISH_ROOT/reports/TECHNICAL_COMPLETION.json"
"$PYTHON" - "$PUBLISH_ROOT/reports/TECHNICAL_COMPLETION.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert d["status"]=="COMPLETE_WITH_TECHNICAL_NA"
assert d["expected_jobs"]==16880 and d["technical_failure_semantics"]=="NA_not_negative"
PY
