#!/usr/bin/env bash
set -euo pipefail
umask 027

DEPLOY_ROOT="${PVRIG_TOP200_DEPLOY_ROOT:-$HOME/.local/share/bxcpu_top200_seed_completion_v1_20260725/runtime}"
# shellcheck source=bxcpu_runtime_common.sh
source "$DEPLOY_ROOT/bxcpu_runtime_common.sh"

CACHE_ROOT="${PVRIG_BXCPU_CACHE:-$HOME/.local/opt}"
PROJECT_NAME="${PVRIG_TOP200_PROJECT_NAME:-pvrig_top200_common4_seed_completion106_handoff_v1_20260725}"
PUBLISH_ROOT="${PVRIG_TOP200_PUBLISH_ROOT:-$HOME/${PROJECT_NAME}_bxcpu_results}"
MANIFEST="${PVRIG_TOP200_MANIFEST_PATH:-$HOME/${PROJECT_NAME}.manifest.tsv}"
MANIFEST_SHA256="${PVRIG_TOP200_MANIFEST_SHA256:?manifest SHA256 is required}"
OUTPUT="${PVRIG_TOP200_AUDIT_OUTPUT:-$PUBLISH_ROOT/reports/TECHNICAL_COMPLETION.json}"
WORK_BASE="${SLURM_TMPDIR:-/tmp}/${USER}/${PROJECT_NAME}/audit_${SLURM_JOB_ID:-manual}_$$"
mkdir -p "$WORK_BASE"
trap 'rm -rf "$WORK_BASE"' EXIT

pvrig_unpack_runtime "$CACHE_ROOT" "$WORK_BASE"
pvrig_validate_runtime

"$LOCAL_ENV/bin/python" "$DEPLOY_ROOT/runtime_contract.py" audit \
    --result-root "$PUBLISH_ROOT" \
    --manifest "$MANIFEST" \
    --manifest-sha256 "$MANIFEST_SHA256" \
    --output "$OUTPUT"
