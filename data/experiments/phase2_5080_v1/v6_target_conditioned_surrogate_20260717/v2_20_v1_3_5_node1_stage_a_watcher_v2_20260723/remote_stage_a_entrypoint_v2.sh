#!/usr/bin/env bash
set -euo pipefail

RUNTIME="${1:?runtime}"
PACKAGE="${2:?package}"
EVIDENCE="${3:?evidence}"
FREEZE_NAME="${4:?freeze name}"
FREEZE_SHA="${5:?freeze sha}"
GPU="${6:?physical gpu}"

[[ "$GPU" =~ ^[1-7]$ ]] || { echo "invalid_physical_gpu:$GPU" >&2; exit 64; }
[[ ! -e "$RUNTIME" ]] || { echo "runtime_already_exists:$RUNTIME" >&2; exit 65; }
[[ ! -e "$EVIDENCE" ]] || { echo "evidence_already_exists:$EVIDENCE" >&2; exit 66; }
mkdir -m 700 "$EVIDENCE"

set +e
(
  cd "$PACKAGE"
  CUDA_VISIBLE_DEVICES="$GPU" \
  OMP_NUM_THREADS=4 \
  PYTHONDONTWRITEBYTECODE=1 \
    ./launchers/run_phase1_preflight_node1_v1_3_5.sh \
      "$RUNTIME" "$PACKAGE/$FREEZE_NAME" "$FREEZE_SHA"
) >"$EVIDENCE/PREFLIGHT_LAUNCHER.log.tmp" 2>&1
rc=$?
set -e
mv "$EVIDENCE/PREFLIGHT_LAUNCHER.log.tmp" "$EVIDENCE/PREFLIGHT_LAUNCHER.log"
printf '%s\n' "$rc" >"$EVIDENCE/PREFLIGHT_LAUNCHER.rc.tmp"
mv "$EVIDENCE/PREFLIGHT_LAUNCHER.rc.tmp" "$EVIDENCE/PREFLIGHT_LAUNCHER.rc"
exit "$rc"
