#!/usr/bin/env bash
set -Eeuo pipefail

EXP_DIR=${PVRIG_EXP_DIR:-/mnt/d/work/抗体/data/experiments/phase2_5080_v1}
PYTHON=${PYTHON:-python3}
FREEZER=${V4F_PREDICTION_FREEZER:-$EXP_DIR/src/freeze_phase2_v4_f_surrogate_predictions.py}
MANIFEST=${V4F_MANIFEST:-$EXP_DIR/data_splits/pvrig_v4_f/prospective_holdout96_manifest.tsv}
MANIFEST_AUDIT=${V4F_MANIFEST_AUDIT:-$EXP_DIR/data_splits/pvrig_v4_f/prospective_holdout96_audit.json}
MANIFEST_RECEIPT=${V4F_MANIFEST_RECEIPT:-$EXP_DIR/data_splits/pvrig_v4_f/prospective_holdout96_receipt.json}
PREDICTION_RECEIPT=${V4F_PREDICTION_RECEIPT:-$EXP_DIR/predictions/pvrig_v4_f_surrogate_predictions_v1/v4_f_96_frozen_surrogate_predictions.receipt.json}
EXPECTED_COUNT=${V4F_EXPECTED_COUNT:-96}
TEST_ONLY_UNFROZEN=${V4F_TEST_ONLY_ALLOW_UNFROZEN_INPUTS:-0}

verify=(
  "$PYTHON" "$FREEZER" verify-receipt
  --manifest "$MANIFEST"
  --manifest-audit "$MANIFEST_AUDIT"
  --manifest-receipt "$MANIFEST_RECEIPT"
  --receipt "$PREDICTION_RECEIPT"
  --expected-count "$EXPECTED_COUNT"
)
if [[ "$TEST_ONLY_UNFROZEN" == 1 ]]; then
  [[ "$EXP_DIR" != "/mnt/d/work/抗体/data/experiments/phase2_5080_v1" ]] || {
    echo "test-only unfrozen inputs are forbidden for the production root" >&2
    exit 2
  }
  verify+=(--test-only-allow-unfrozen-inputs)
fi

"${verify[@]}"
if [[ ${1:-} == -- ]]; then shift; fi
if (( $# == 0 )); then
  echo "PASS_V4_F_PREDICTION_GATE_DOCKING_MAY_START"
  exit 0
fi
exec "$@"
