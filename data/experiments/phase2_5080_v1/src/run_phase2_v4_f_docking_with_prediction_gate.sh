#!/usr/bin/env bash
set -Eeuo pipefail

CANONICAL_EXP_DIR=/mnt/d/work/抗体/data/experiments/phase2_5080_v1
CANONICAL_PYTHON=$CANONICAL_EXP_DIR/.venv-phase2-5080/bin/python
CANONICAL_FREEZER=$CANONICAL_EXP_DIR/src/freeze_phase2_v4_f_surrogate_predictions.py
EXP_DIR=${PVRIG_EXP_DIR:-$CANONICAL_EXP_DIR}
TEST_ONLY_UNFROZEN=${V4F_TEST_ONLY_ALLOW_UNFROZEN_INPUTS:-0}

resolve_executable() {
  local candidate=$1 resolved
  if [[ "$candidate" == */* ]]; then
    resolved=$(realpath -e -- "$candidate" 2>/dev/null) || return 1
  else
    candidate=$(command -v -- "$candidate" 2>/dev/null) || return 1
    resolved=$(realpath -e -- "$candidate" 2>/dev/null) || return 1
  fi
  printf '%s\n' "$resolved"
}

if [[ "$TEST_ONLY_UNFROZEN" == 1 ]]; then
  [[ "$(realpath -m -- "$EXP_DIR")" != "$(realpath -m -- "$CANONICAL_EXP_DIR")" ]] || {
    echo "test-only unfrozen inputs are forbidden for the production root" >&2
    exit 2
  }
  PYTHON=${PYTHON:-python3}
  FREEZER=${V4F_PREDICTION_FREEZER:-$EXP_DIR/src/freeze_phase2_v4_f_surrogate_predictions.py}
else
  [[ "$(realpath -e -- "$EXP_DIR" 2>/dev/null || true)" == "$(realpath -e -- "$CANONICAL_EXP_DIR")" ]] || {
    echo "production docking gate requires canonical PVRIG_EXP_DIR=$CANONICAL_EXP_DIR" >&2
    exit 2
  }
  [[ -x "$CANONICAL_PYTHON" && -f "$CANONICAL_FREEZER" ]] || {
    echo "canonical production Python or V4-F verifier is missing" >&2
    exit 2
  }
  if [[ -v PYTHON ]]; then
    [[ "$(resolve_executable "$PYTHON" 2>/dev/null || true)" == "$(resolve_executable "$CANONICAL_PYTHON")" ]] || {
      echo "production PYTHON override is forbidden; canonical interpreter is required" >&2
      exit 2
    }
  fi
  if [[ -v V4F_PREDICTION_FREEZER ]]; then
    [[ "$(realpath -e -- "$V4F_PREDICTION_FREEZER" 2>/dev/null || true)" == "$(realpath -e -- "$CANONICAL_FREEZER")" ]] || {
      echo "production V4F_PREDICTION_FREEZER override is forbidden; canonical verifier is required" >&2
      exit 2
    }
  fi
  PYTHON=$CANONICAL_PYTHON
  FREEZER=$CANONICAL_FREEZER
fi
MANIFEST=${V4F_MANIFEST:-$EXP_DIR/data_splits/pvrig_v4_f/prospective_holdout96_manifest.tsv}
MANIFEST_AUDIT=${V4F_MANIFEST_AUDIT:-$EXP_DIR/data_splits/pvrig_v4_f/prospective_holdout96_audit.json}
MANIFEST_RECEIPT=${V4F_MANIFEST_RECEIPT:-$EXP_DIR/data_splits/pvrig_v4_f/prospective_holdout96_receipt.json}
BASE_OUT=${V4D_BASE_SURROGATE_OUT:-$EXP_DIR/runs/pvrig_v4_d_sequence_surrogate_v1}
EMBEDDING_OUT=${V4D_EMBEDDING_SURROGATE_OUT:-$EXP_DIR/runs/pvrig_v4_d_frozen_embedding_surrogate_v1}
CONTACT_OUT=${V4D_CONTACT_SURROGATE_OUT:-$EXP_DIR/runs/pvrig_v4_d_contact_fusion_surrogate_v1}
EMBEDDING_ROOT=${V4D_EMBEDDING_ROOT:-$EXP_DIR/prepared/pvrig_teacher_formal_v1_candidates/model_inputs}
EMBEDDING_MANIFEST=${V4D_EMBEDDING_MANIFEST:-$EMBEDDING_ROOT/meanpool_embeddings/embedding_manifest_v3.csv}
EMBEDDING_SUMMARY=${V4D_EMBEDDING_SUMMARY:-$EMBEDDING_ROOT/meanpool_embeddings/embedding_summary_v3.json}
EMBEDDING_SEQUENCE_MANIFEST=${V4D_EMBEDDING_SEQUENCE_MANIFEST:-$EMBEDDING_ROOT/sequence_manifest_v3.csv}
CONTACT_RECEIPT=${V4D_CONTACT_FEATURE_RECEIPT:-$EXP_DIR/predictions/pvrig_candidate_v2_3_residue_contact_features_v3.receipt.json}
CONTACT_SCHEMA=${V4D_CONTACT_SCHEMA:-$EXP_DIR/prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.json}
PREDICTION_RECEIPT=${V4F_PREDICTION_RECEIPT:-$EXP_DIR/predictions/pvrig_v4_f_surrogate_predictions_v1/v4_f_96_frozen_surrogate_predictions.receipt.json}
EXPECTED_COUNT=${V4F_EXPECTED_COUNT:-96}

verify=(
  "$PYTHON" "$FREEZER" verify-receipt
  --manifest "$MANIFEST"
  --manifest-audit "$MANIFEST_AUDIT"
  --manifest-receipt "$MANIFEST_RECEIPT"
  --receipt "$PREDICTION_RECEIPT"
  --expected-count "$EXPECTED_COUNT"
  --base-out "$BASE_OUT"
  --embedding-out "$EMBEDDING_OUT"
  --contact-out "$CONTACT_OUT"
  --embedding-manifest "$EMBEDDING_MANIFEST"
  --embedding-summary "$EMBEDDING_SUMMARY"
  --embedding-sequence-manifest "$EMBEDDING_SEQUENCE_MANIFEST"
  --contact-receipt "$CONTACT_RECEIPT"
  --contact-schema "$CONTACT_SCHEMA"
)
if [[ "$TEST_ONLY_UNFROZEN" == 1 ]]; then
  verify+=(--test-only-allow-unfrozen-inputs)
fi

"${verify[@]}"
if [[ ${1:-} == -- ]]; then shift; fi
if (( $# == 0 )); then
  echo "PASS_V4_F_PREDICTION_GATE_DOCKING_MAY_START"
  exit 0
fi
exec "$@"
