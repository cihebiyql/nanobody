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
    echo "production prediction watcher requires canonical PVRIG_EXP_DIR=$CANONICAL_EXP_DIR" >&2
    exit 2
  }
  [[ -x "$CANONICAL_PYTHON" && -f "$CANONICAL_FREEZER" ]] || {
    echo "canonical production Python or V4-F freezer is missing" >&2
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
      echo "production V4F_PREDICTION_FREEZER override is forbidden; canonical freezer is required" >&2
      exit 2
    }
  fi
  PYTHON=$CANONICAL_PYTHON
  FREEZER=$CANONICAL_FREEZER
fi
POLL_SECONDS=${POLL_SECONDS:-300}
MAX_WAIT_SECONDS=${MAX_WAIT_SECONDS:-604800}
FREEZE_TIMEOUT_SECONDS=${FREEZE_TIMEOUT_SECONDS:-7200}
ONCE=${ONCE:-0}

SURROGATE_STATUS=${V4D_SURROGATE_STATUS:-$EXP_DIR/status/pvrig_v4_d_surrogate_training_v1/status.json}
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
OUT_DIR=${V4F_PREDICTION_OUT:-$EXP_DIR/predictions/pvrig_v4_f_surrogate_predictions_v1}
STATUS_DIR=${V4F_PREDICTION_STATUS_DIR:-$EXP_DIR/status/pvrig_v4_f_prediction_freeze_v1}
LOG_DIR=${V4F_PREDICTION_LOG_DIR:-$EXP_DIR/logs/pvrig_v4_f_prediction_freeze_v1}
EXPECTED_COUNT=${V4F_EXPECTED_COUNT:-96}

mkdir -p "$STATUS_DIR" "$LOG_DIR" "$(dirname "$OUT_DIR")"
exec 9>"$STATUS_DIR/controller.lock"
flock -n 9 || { echo "V4-F prediction freezer already running" >&2; exit 75; }
printf '%s\n' "$$" >"$STATUS_DIR/controller.pid.tmp"
mv "$STATUS_DIR/controller.pid.tmp" "$STATUS_DIR/controller.pid"
STARTED_AT=$(date +%s)

write_status() {
  local state=$1 reason=$2 receipt_sha=${3:-}
  STATE_VALUE=$state REASON_VALUE=$reason RECEIPT_SHA_VALUE=$receipt_sha STATUS_PATH=$STATUS_DIR/status.json PID_VALUE=$$ "$PYTHON" - <<'PY'
import json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path
path=Path(os.environ["STATUS_PATH"]); path.parent.mkdir(parents=True,exist_ok=True)
payload={
 "schema_version":"phase2_v4_f_prediction_freeze_watcher_v1",
 "status":os.environ["STATE_VALUE"],
 "reason":os.environ["REASON_VALUE"],
 "updated_at":datetime.now(timezone.utc).isoformat(),
 "controller_pid":int(os.environ["PID_VALUE"]),
 "v4_f_labels_read":False,
 "v4_f_label_paths_accepted":0,
}
if os.environ.get("RECEIPT_SHA_VALUE"):
 payload["prediction_receipt_sha256"]=os.environ["RECEIPT_SHA_VALUE"]
with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=path.parent,delete=False) as handle:
 json.dump(payload,handle,indent=2,sort_keys=True); handle.write("\n"); temporary=Path(handle.name)
temporary.replace(path)
PY
}

trap 'rc=$?; write_status FAILED_WATCHER "unexpected_error_rc=$rc line=$LINENO" || true; exit "$rc"' ERR

surrogate_state() {
  "$PYTHON" - "$SURROGATE_STATUS" <<'PY'
import json,sys
from pathlib import Path
path=Path(sys.argv[1])
try: print(json.loads(path.read_text()).get("status","MISSING"))
except Exception: print("MISSING")
PY
}

freezer_common=(
  --manifest "$MANIFEST"
  --manifest-audit "$MANIFEST_AUDIT"
  --manifest-receipt "$MANIFEST_RECEIPT"
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
  freezer_common+=(--test-only-allow-unfrozen-inputs)
fi

verify_existing() {
  local receipt=$OUT_DIR/v4_f_96_frozen_surrogate_predictions.receipt.json receipt_mode
  if [[ ! -e "$receipt" && ! -L "$receipt" ]]; then
    return 4
  fi
  receipt_mode=$(stat -c '%a' -- "$receipt" 2>/dev/null || true)
  if [[ -L "$receipt" || ! -f "$receipt" || ! -s "$receipt" || -z "$receipt_mode" ]] \
    || (( (8#$receipt_mode & 0444) == 0 )) \
    || ! head -c 1 -- "$receipt" >/dev/null 2>&1; then
    echo "existing prediction receipt is corrupt: expected a non-empty readable regular file: $receipt" >&2
    return 2
  fi
  "$PYTHON" "$FREEZER" verify-receipt "${freezer_common[@]}" --receipt "$receipt"
}

run_freezer() {
  local temporary rc
  temporary=$(mktemp "$LOG_DIR/.prediction-freeze.XXXXXX")
  if timeout --preserve-status "$FREEZE_TIMEOUT_SECONDS" \
    "$PYTHON" "$FREEZER" freeze "${freezer_common[@]}" \
      --out-dir "$OUT_DIR" >"$temporary" 2>&1; then
    mv "$temporary" "$LOG_DIR/prediction_freeze.log"
    return 0
  else
    rc=$?
  fi
  mv "$temporary" "$LOG_DIR/prediction_freeze.log"
  write_status FAILED_PREDICTION_FREEZE "freezer rc=$rc; see $LOG_DIR/prediction_freeze.log"
  exit "$rc"
}

write_status WAITING_V4_D_SURROGATES "waiting for all V4-D artifact receipts; V4-F labels remain sealed"
while true; do
  if verify_existing >"$STATUS_DIR/verification.tmp" 2>&1; then
    receipt_sha=$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["receipt_sha256"])' "$STATUS_DIR/verification.tmp")
    mv "$STATUS_DIR/verification.tmp" "$STATUS_DIR/verification.json"
    write_status COMPLETE_V4_F_96_PREDICTIONS_FROZEN "prediction receipt verified; V4-F Docking launch gate may open" "$receipt_sha"
    exit 0
  else
    verify_rc=$?
    if [[ $verify_rc -eq 2 ]]; then
      mv "$STATUS_DIR/verification.tmp" "$STATUS_DIR/verification.invalid.json"
      write_status BLOCKED_INVALID_PREDICTION_RECEIPT "existing prediction receipt failed verification"
      exit 2
    elif [[ $verify_rc -ne 4 ]]; then
      mv "$STATUS_DIR/verification.tmp" "$STATUS_DIR/verification.invalid.json"
      write_status FAILED_PREDICTION_RECEIPT_VERIFIER "prediction receipt verifier rc=$verify_rc"
      exit "$verify_rc"
    fi
    rm -f "$STATUS_DIR/verification.tmp"
  fi
  state=$(surrogate_state)
  if [[ "$state" == COMPLETE_V4_D_SURROGATE_TRAINING_TEST32_SEALED ]]; then
    write_status RUNNING_V4_F_PREDICTION_FREEZE "all V4-D artifact receipts complete; generating 96 unlabeled predictions"
    run_freezer
    if verify_existing >"$STATUS_DIR/verification.tmp" 2>&1; then
      receipt_sha=$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["receipt_sha256"])' "$STATUS_DIR/verification.tmp")
      mv "$STATUS_DIR/verification.tmp" "$STATUS_DIR/verification.json"
      write_status COMPLETE_V4_F_96_PREDICTIONS_FROZEN "prediction receipt verified; V4-F Docking launch gate may open" "$receipt_sha"
      exit 0
    fi
    verify_rc=$?
    mv "$STATUS_DIR/verification.tmp" "$STATUS_DIR/verification.invalid.json"
    if [[ $verify_rc -eq 2 ]]; then
      write_status BLOCKED_INVALID_PREDICTION_RECEIPT "freezer returned success but receipt verification failed"
      exit 2
    fi
    write_status FAILED_PREDICTION_RECEIPT "freezer returned success but verifier rc=$verify_rc"
    exit "$verify_rc"
  elif [[ "$state" == FAILED* || "$state" == BLOCKED* ]]; then
    write_status BLOCKED_V4_D_SURROGATES "upstream surrogate state=$state"
    exit 2
  else
    write_status WAITING_V4_D_SURROGATES "upstream surrogate state=$state; V4-F labels remain sealed"
  fi
  if [[ "$ONCE" == 1 ]]; then exit 4; fi
  if (( $(date +%s) - STARTED_AT > MAX_WAIT_SECONDS )); then
    write_status BLOCKED_WAIT_TIMEOUT "wait exceeded MAX_WAIT_SECONDS=$MAX_WAIT_SECONDS"
    exit 3
  fi
  sleep "$POLL_SECONDS"
done
