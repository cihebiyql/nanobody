#!/usr/bin/env bash
set -Eeuo pipefail

CANONICAL_EXP_DIR=/mnt/d/work/抗体/data/experiments/phase2_5080_v1
CANONICAL_PYTHON=$CANONICAL_EXP_DIR/.venv-phase2-5080/bin/python
TEST_ONLY=${PVRIG_V4D_WATCHER_TEST_ONLY:-0}
EXP_DIR=${PVRIG_EXP_DIR:-$CANONICAL_EXP_DIR}
PYTHON=${PYTHON:-$CANONICAL_PYTHON}
POLL_SECONDS=${POLL_SECONDS:-300}
MAX_WAIT_SECONDS=${MAX_WAIT_SECONDS:-604800}
TRAIN_TIMEOUT_SECONDS=${TRAIN_TIMEOUT_SECONDS:-21600}
ONCE=${ONCE:-0}

HELPER=${WATCHER_HELPER:-$EXP_DIR/src/phase2_v4_d_surrogate_watcher_helper_v3.py}
BASE_TRAINER=${BASE_TRAINER:-$EXP_DIR/src/train_phase2_v4_d_surrogate.py}
EMBEDDING_TRAINER=${EMBEDDING_TRAINER:-$EXP_DIR/src/train_phase2_v4_d_frozen_embedding_surrogate.py}
CONTACT_TRAINER=${CONTACT_TRAINER:-$EXP_DIR/src/train_phase2_v4_d_contact_feature_surrogate.py}

DELIVERY_ROOT=${V4D_OPEN_DELIVERY_ROOT:-$EXP_DIR/prepared/pvrig_v4_d_open_teacher_v1/remote_delivery_v1/current/outputs}
TEACHER=${V4D_OPEN_TEACHER:-$DELIVERY_ROOT/v4d_open_teacher.tsv}
TEACHER_AUDIT=${V4D_OPEN_TEACHER_AUDIT:-$DELIVERY_ROOT/v4d_open_teacher.tsv.audit.json}
RELEASE_RECEIPT=${V4D_OPEN_RELEASE_RECEIPT:-$DELIVERY_ROOT/open_teacher_postprocess_receipt.json}
EVALUATOR=${V4D_OPEN_EVALUATOR:-$DELIVERY_ROOT/EVALUATOR_STABLE.json}
SPLIT_MANIFEST=${V4D_SPLIT_MANIFEST:-$EXP_DIR/data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv}

FEATURE_SCHEMA=${V4D_FEATURE_SCHEMA:-$EXP_DIR/prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.json}
FEATURE_SCHEMA_RECEIPT=${V4D_FEATURE_SCHEMA_RECEIPT:-$EXP_DIR/prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.receipt.json}
CONTACT_FEATURES=${V4D_CONTACT_FEATURES:-$EXP_DIR/predictions/pvrig_candidate_v2_3_residue_contact_features_v3.csv}
CONTACT_FEATURE_AUDIT=${V4D_CONTACT_FEATURE_AUDIT:-$EXP_DIR/predictions/pvrig_candidate_v2_3_residue_contact_features_v3.audit.json}
CONTACT_FEATURE_RECEIPT=${V4D_CONTACT_FEATURE_RECEIPT:-$EXP_DIR/predictions/pvrig_candidate_v2_3_residue_contact_features_v3.receipt.json}
CONTACT_FEATURE_VERIFICATION=${V4D_CONTACT_FEATURE_VERIFICATION:-$EXP_DIR/predictions/pvrig_candidate_v2_3_residue_contact_features_v3.verification.json}

EMBEDDING_ROOT=${V4D_EMBEDDING_ROOT:-$EXP_DIR/prepared/pvrig_teacher_formal_v1_candidates/model_inputs}
EMBEDDING_MANIFEST=${V4D_EMBEDDING_MANIFEST:-$EMBEDDING_ROOT/meanpool_embeddings/embedding_manifest_v3.csv}
EMBEDDING_SUMMARY=${V4D_EMBEDDING_SUMMARY:-$EMBEDDING_ROOT/meanpool_embeddings/embedding_summary_v3.json}
EMBEDDING_SEQUENCE_MANIFEST=${V4D_EMBEDDING_SEQUENCE_MANIFEST:-$EMBEDDING_ROOT/sequence_manifest_v3.csv}
EMBEDDING_SHARD_DIR=${V4D_EMBEDDING_SHARD_DIR:-$EMBEDDING_ROOT/meanpool_embeddings/shards}

BASE_OUT=${V4D_BASE_SURROGATE_OUT:-$EXP_DIR/runs/pvrig_v4_d_sequence_surrogate_v1}
EMBEDDING_OUT=${V4D_EMBEDDING_SURROGATE_OUT:-$EXP_DIR/runs/pvrig_v4_d_frozen_embedding_surrogate_v1}
CONTACT_OUT=${V4D_CONTACT_SURROGATE_OUT:-$EXP_DIR/runs/pvrig_v4_d_contact_fusion_surrogate_v1}
STATUS_DIR=${V4D_SURROGATE_STATUS_DIR:-$EXP_DIR/status/pvrig_v4_d_surrogate_training_v3}
LOG_DIR=${V4D_SURROGATE_LOG_DIR:-$EXP_DIR/logs/pvrig_v4_d_surrogate_training_v3}
TEST_HASH_LOCKS=${V4D_TEST_ONLY_HASH_LOCKS:-}
TRUST_ANCHOR=${V4D_V3_TRUST_ANCHOR:-$EXP_DIR/audits/phase2_v4_d_surrogate_training_v3_implementation_trust_anchor.json}
EXPECTED_TRUST_ANCHOR_SHA=${V4D_V3_EXPECTED_TRUST_ANCHOR_SHA:-}

canonical_path() { realpath -m -- "$1"; }
require_canonical() {
  local label=$1 actual=$2 expected=$3
  [[ "$(canonical_path "$actual")" == "$(canonical_path "$expected")" ]] || {
    echo "production path override forbidden: $label actual=$actual expected=$expected" >&2
    exit 2
  }
}

if [[ "$TEST_ONLY" == 1 ]]; then
  [[ "$(canonical_path "$EXP_DIR")" != "$(canonical_path "$CANONICAL_EXP_DIR")" ]] || {
    echo "test-only watcher is forbidden for the production experiment root" >&2
    exit 2
  }
else
  case "${PYTHONOPTIMIZE:-}" in
    ""|0) ;;
    *) echo "production PYTHONOPTIMIZE must be unset or 0" >&2; exit 2 ;;
  esac
  [[ -z "${BASH_ENV:-}" ]] || { echo "production BASH_ENV override is forbidden" >&2; exit 2; }
  [[ -z "${PYTHONPATH:-}" ]] || { echo "production PYTHONPATH override is forbidden" >&2; exit 2; }
  require_canonical EXP_DIR "$EXP_DIR" "$CANONICAL_EXP_DIR"
  require_canonical PYTHON "$PYTHON" "$CANONICAL_PYTHON"
  require_canonical HELPER "$HELPER" "$CANONICAL_EXP_DIR/src/phase2_v4_d_surrogate_watcher_helper_v3.py"
  require_canonical BASE_TRAINER "$BASE_TRAINER" "$CANONICAL_EXP_DIR/src/train_phase2_v4_d_surrogate.py"
  require_canonical EMBEDDING_TRAINER "$EMBEDDING_TRAINER" "$CANONICAL_EXP_DIR/src/train_phase2_v4_d_frozen_embedding_surrogate.py"
  require_canonical CONTACT_TRAINER "$CONTACT_TRAINER" "$CANONICAL_EXP_DIR/src/train_phase2_v4_d_contact_feature_surrogate.py"
  require_canonical DELIVERY_ROOT "$DELIVERY_ROOT" "$CANONICAL_EXP_DIR/prepared/pvrig_v4_d_open_teacher_v1/remote_delivery_v1/current/outputs"
  require_canonical TEACHER "$TEACHER" "$CANONICAL_EXP_DIR/prepared/pvrig_v4_d_open_teacher_v1/remote_delivery_v1/current/outputs/v4d_open_teacher.tsv"
  require_canonical TEACHER_AUDIT "$TEACHER_AUDIT" "$CANONICAL_EXP_DIR/prepared/pvrig_v4_d_open_teacher_v1/remote_delivery_v1/current/outputs/v4d_open_teacher.tsv.audit.json"
  require_canonical RELEASE_RECEIPT "$RELEASE_RECEIPT" "$CANONICAL_EXP_DIR/prepared/pvrig_v4_d_open_teacher_v1/remote_delivery_v1/current/outputs/open_teacher_postprocess_receipt.json"
  require_canonical EVALUATOR "$EVALUATOR" "$CANONICAL_EXP_DIR/prepared/pvrig_v4_d_open_teacher_v1/remote_delivery_v1/current/outputs/EVALUATOR_STABLE.json"
  require_canonical SPLIT_MANIFEST "$SPLIT_MANIFEST" "$CANONICAL_EXP_DIR/data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv"
  require_canonical FEATURE_SCHEMA "$FEATURE_SCHEMA" "$CANONICAL_EXP_DIR/prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.json"
  require_canonical FEATURE_SCHEMA_RECEIPT "$FEATURE_SCHEMA_RECEIPT" "$CANONICAL_EXP_DIR/prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.receipt.json"
  require_canonical CONTACT_FEATURES "$CONTACT_FEATURES" "$CANONICAL_EXP_DIR/predictions/pvrig_candidate_v2_3_residue_contact_features_v3.csv"
  require_canonical CONTACT_FEATURE_AUDIT "$CONTACT_FEATURE_AUDIT" "$CANONICAL_EXP_DIR/predictions/pvrig_candidate_v2_3_residue_contact_features_v3.audit.json"
  require_canonical CONTACT_FEATURE_RECEIPT "$CONTACT_FEATURE_RECEIPT" "$CANONICAL_EXP_DIR/predictions/pvrig_candidate_v2_3_residue_contact_features_v3.receipt.json"
  require_canonical CONTACT_FEATURE_VERIFICATION "$CONTACT_FEATURE_VERIFICATION" "$CANONICAL_EXP_DIR/predictions/pvrig_candidate_v2_3_residue_contact_features_v3.verification.json"
  require_canonical EMBEDDING_ROOT "$EMBEDDING_ROOT" "$CANONICAL_EXP_DIR/prepared/pvrig_teacher_formal_v1_candidates/model_inputs"
  require_canonical EMBEDDING_MANIFEST "$EMBEDDING_MANIFEST" "$CANONICAL_EXP_DIR/prepared/pvrig_teacher_formal_v1_candidates/model_inputs/meanpool_embeddings/embedding_manifest_v3.csv"
  require_canonical EMBEDDING_SUMMARY "$EMBEDDING_SUMMARY" "$CANONICAL_EXP_DIR/prepared/pvrig_teacher_formal_v1_candidates/model_inputs/meanpool_embeddings/embedding_summary_v3.json"
  require_canonical EMBEDDING_SEQUENCE_MANIFEST "$EMBEDDING_SEQUENCE_MANIFEST" "$CANONICAL_EXP_DIR/prepared/pvrig_teacher_formal_v1_candidates/model_inputs/sequence_manifest_v3.csv"
  require_canonical EMBEDDING_SHARD_DIR "$EMBEDDING_SHARD_DIR" "$CANONICAL_EXP_DIR/prepared/pvrig_teacher_formal_v1_candidates/model_inputs/meanpool_embeddings/shards"
  require_canonical BASE_OUT "$BASE_OUT" "$CANONICAL_EXP_DIR/runs/pvrig_v4_d_sequence_surrogate_v1"
  require_canonical EMBEDDING_OUT "$EMBEDDING_OUT" "$CANONICAL_EXP_DIR/runs/pvrig_v4_d_frozen_embedding_surrogate_v1"
  require_canonical CONTACT_OUT "$CONTACT_OUT" "$CANONICAL_EXP_DIR/runs/pvrig_v4_d_contact_fusion_surrogate_v1"
  require_canonical STATUS_DIR "$STATUS_DIR" "$CANONICAL_EXP_DIR/status/pvrig_v4_d_surrogate_training_v3"
  require_canonical LOG_DIR "$LOG_DIR" "$CANONICAL_EXP_DIR/logs/pvrig_v4_d_surrogate_training_v3"
  require_canonical TRUST_ANCHOR "$TRUST_ANCHOR" "$CANONICAL_EXP_DIR/audits/phase2_v4_d_surrogate_training_v3_implementation_trust_anchor.json"
  [[ -z "$TEST_HASH_LOCKS" ]] || { echo "test hash locks forbidden in production" >&2; exit 2; }
  [[ "$EXPECTED_TRUST_ANCHOR_SHA" =~ ^[0-9a-f]{64}$ ]] || {
    echo "production launcher must provide a valid V4D_V3_EXPECTED_TRUST_ANCHOR_SHA" >&2
    exit 2
  }
fi

mkdir -p "$STATUS_DIR" "$LOG_DIR" "$(dirname "$BASE_OUT")" "$(dirname "$EMBEDDING_OUT")" "$(dirname "$CONTACT_OUT")"
exec 9>"$STATUS_DIR/controller.lock"
flock -n 9 || { echo "V4-D surrogate training watcher already running" >&2; exit 75; }
printf '%s\n' "$$" >"$STATUS_DIR/controller.pid.tmp"
mv "$STATUS_DIR/controller.pid.tmp" "$STATUS_DIR/controller.pid"
STARTED_AT=$(date +%s)

[[ -x "$PYTHON" ]] || command -v "$PYTHON" >/dev/null
[[ -s "$HELPER" ]] || { echo "watcher helper missing: $HELPER" >&2; exit 2; }
[[ -s "$BASE_TRAINER" ]] || { echo "base trainer missing: $BASE_TRAINER" >&2; exit 2; }
[[ -s "$EMBEDDING_TRAINER" ]] || { echo "embedding trainer missing: $EMBEDDING_TRAINER" >&2; exit 2; }

if [[ -n "$TEST_HASH_LOCKS" ]]; then
  [[ "$TEST_ONLY" == 1 ]] || {
    echo "test hash locks require PVRIG_V4D_WATCHER_TEST_ONLY=1" >&2
    exit 2
  }
  [[ "$EXP_DIR" != "/mnt/d/work/抗体/data/experiments/phase2_5080_v1" ]] || {
    echo "test hash locks are forbidden for the production experiment root" >&2
    exit 2
  }
fi

PREFLIGHT=$STATUS_DIR/preflight.json
BASE_STAGE=$STATUS_DIR/base_stage.json
EMBEDDING_STAGE=$STATUS_DIR/embedding_stage.json
CONTACT_STAGE=$STATUS_DIR/contact_stage.json
CONTACT_INPUTS=$STATUS_DIR/contact_inputs.json
TRUST_INITIAL=$STATUS_DIR/implementation_trust_initial.json
COMPLETION_RECEIPT=$STATUS_DIR/surrogate_v3_completion_receipt.json

trust_gate() {
  local stage=$1 output temporary rc
  output=$STATUS_DIR/implementation_trust_${stage}.json
  [[ -n "$EXPECTED_TRUST_ANCHOR_SHA" ]] || {
    [[ "$TEST_ONLY" == 1 ]] && return 0
    echo "missing production trust-anchor SHA" >&2
    return 2
  }
  temporary=$(mktemp "$STATUS_DIR/.trust-${stage}.XXXXXX")
  if "$PYTHON" "$HELPER" verify-trust-anchor \
      --anchor "$TRUST_ANCHOR" \
      --expected-sha "$EXPECTED_TRUST_ANCHOR_SHA" >"$temporary"; then
    mv "$temporary" "$output"
  else
    rc=$?
    mv "$temporary" "$STATUS_DIR/implementation_trust_${stage}_failure.json"
    return "$rc"
  fi
  if [[ -s "$TRUST_INITIAL" && "$output" != "$TRUST_INITIAL" ]]; then
    cmp -s "$TRUST_INITIAL" "$output" || {
      echo "implementation trust closure changed at stage=$stage" >&2
      return 2
    }
  elif [[ "$output" != "$TRUST_INITIAL" ]]; then
    cp "$output" "$TRUST_INITIAL"
  fi
}

write_state() {
  local state=$1 reason=$2
  local command=(
    "$PYTHON" "$HELPER" write-state
    --path "$STATUS_DIR/status.json"
    --status "$state"
    --reason "$reason"
    --controller-pid "$$"
  )
  [[ -s "$PREFLIGHT" ]] && command+=(--preflight "$PREFLIGHT")
  [[ -s "$BASE_STAGE" ]] && command+=(--base "$BASE_STAGE")
  [[ -s "$EMBEDDING_STAGE" ]] && command+=(--embedding "$EMBEDDING_STAGE")
  [[ -s "$CONTACT_STAGE" ]] && command+=(--contact "$CONTACT_STAGE")
  "${command[@]}" >/dev/null
}

failure_trap() {
  local rc=$? line=$1
  trap - ERR
  write_state FAILED_WATCHER "unexpected_error_line=$line rc=$rc" || true
  exit "$rc"
}
trap 'failure_trap $LINENO' ERR

preflight_command() {
  local output=$1
  trust_gate preflight || {
    write_state FAILED_IMPLEMENTATION_TRUST "implementation trust gate failed before preflight"
    exit 2
  }
  local command=(
    "$PYTHON" "$HELPER" preflight
    --teacher "$TEACHER"
    --teacher-audit "$TEACHER_AUDIT"
    --release-receipt "$RELEASE_RECEIPT"
    --evaluator "$EVALUATOR"
    --split-manifest "$SPLIT_MANIFEST"
    --feature-schema "$FEATURE_SCHEMA"
    --feature-schema-receipt "$FEATURE_SCHEMA_RECEIPT"
    --contact-features "$CONTACT_FEATURES"
    --contact-feature-audit "$CONTACT_FEATURE_AUDIT"
    --contact-feature-receipt "$CONTACT_FEATURE_RECEIPT"
    --contact-feature-verification "$CONTACT_FEATURE_VERIFICATION"
    --embedding-manifest "$EMBEDDING_MANIFEST"
    --embedding-summary "$EMBEDDING_SUMMARY"
    --embedding-sequence-manifest "$EMBEDDING_SEQUENCE_MANIFEST"
    --embedding-shard-dir "$EMBEDDING_SHARD_DIR"
  )
  [[ -n "$TEST_HASH_LOCKS" ]] && command+=(--test-only-hash-locks "$TEST_HASH_LOCKS")
  if [[ -n "$EXPECTED_TRUST_ANCHOR_SHA" ]]; then
    command+=(--trust-anchor "$TRUST_ANCHOR" --expected-trust-anchor-sha "$EXPECTED_TRUST_ANCHOR_SHA")
  fi
  local temporary rc
  temporary=$(mktemp "$STATUS_DIR/.preflight.XXXXXX")
  if "${command[@]}" >"$temporary"; then
    mv "$temporary" "$output"
    return 0
  else
    rc=$?
  fi
  mv "$temporary" "$STATUS_DIR/preflight_failure.json"
  return "$rc"
}

preflight_or_wait() {
  local rc reason
  if preflight_command "$PREFLIGHT"; then
    return 0
  else
    rc=$?
  fi
  reason=$(
    "$PYTHON" - "$STATUS_DIR/preflight_failure.json" <<'PY'
import json, sys
try: print(json.load(open(sys.argv[1])).get("reason", "preflight failed"))
except Exception: print("preflight failed without valid diagnostic")
PY
  )
  if [[ $rc -eq 4 ]]; then
    write_state WAITING_OPEN_TEACHER "$reason"
    return 4
  fi
  write_state FAILED_INPUT_VALIDATION "$reason"
  exit "$rc"
}

recheck_preflight() {
  local stage=$1
  local after=$STATUS_DIR/preflight_after_${stage}.json
  local compare=$STATUS_DIR/preflight_compare_${stage}.json
  local temporary rc
  if preflight_command "$after"; then
    :
  else
    rc=$?
    write_state FAILED_INPUT_CHANGED "stage=$stage preflight_recheck_rc=$rc"
    exit "$rc"
  fi
  temporary=$(mktemp "$STATUS_DIR/.compare.XXXXXX")
  if "$PYTHON" "$HELPER" compare-preflight --before "$PREFLIGHT" --after "$after" >"$temporary"; then
    mv "$temporary" "$compare"
  else
    rc=$?
    mv "$temporary" "$STATUS_DIR/preflight_compare_${stage}_failure.json"
    write_state FAILED_INPUT_CHANGED "stage=$stage frozen input closure changed"
    exit "$rc"
  fi
}

contact_inputs_command() {
  local output=$1 temporary rc
  local command=(
    "$PYTHON" "$HELPER" verify-contact-inputs
    --feature-schema "$FEATURE_SCHEMA"
    --feature-schema-receipt "$FEATURE_SCHEMA_RECEIPT"
    --contact-features "$CONTACT_FEATURES"
    --contact-feature-audit "$CONTACT_FEATURE_AUDIT"
    --contact-feature-receipt "$CONTACT_FEATURE_RECEIPT"
    --contact-feature-verification "$CONTACT_FEATURE_VERIFICATION"
  )
  [[ -n "$TEST_HASH_LOCKS" ]] && command+=(--test-only-hash-locks "$TEST_HASH_LOCKS")
  temporary=$(mktemp "$STATUS_DIR/.contact-inputs.XXXXXX")
  if "${command[@]}" >"$temporary"; then
    mv "$temporary" "$output"
    return 0
  else
    rc=$?
  fi
  mv "$temporary" "$STATUS_DIR/contact_inputs_failure.json"
  return "$rc"
}

contact_inputs_or_wait() {
  local rc reason
  if contact_inputs_command "$CONTACT_INPUTS"; then
    return 0
  else
    rc=$?
  fi
  reason=$(
    "$PYTHON" - "$STATUS_DIR/contact_inputs_failure.json" <<'PY'
import json, sys
try: print(json.load(open(sys.argv[1])).get("reason", "contact input validation failed"))
except Exception: print("contact input validation failed without valid diagnostic")
PY
  )
  if [[ $rc -eq 4 ]]; then
    write_state WAITING_CONTACT_TRAINER "$reason"
    return 4
  fi
  write_state FAILED_CONTACT_INPUT_VALIDATION "$reason"
  exit "$rc"
}

recheck_contact_inputs() {
  local after=$STATUS_DIR/contact_inputs_after_training.json
  local temporary=$STATUS_DIR/.contact-inputs-compare.$$ rc
  if contact_inputs_command "$after"; then
    :
  else
    rc=$?
    write_state FAILED_INPUT_CHANGED "contact input recheck failed rc=$rc"
    exit "$rc"
  fi
  if "$PYTHON" "$HELPER" compare-preflight --before "$CONTACT_INPUTS" --after "$after" >"$temporary"; then
    mv "$temporary" "$STATUS_DIR/contact_inputs_compare.json"
  else
    rc=$?
    mv "$temporary" "$STATUS_DIR/contact_inputs_compare_failure.json"
    write_state FAILED_INPUT_CHANGED "contact feature input closure changed during training"
    exit "$rc"
  fi
}

verify_stage() {
  local stage=$1 out_dir=$2 result=$3 temporary rc
  local expected_inputs=()
  case "$stage" in
    base)
      expected_inputs=("$TEACHER" "$TEACHER_AUDIT" "$SPLIT_MANIFEST" "$BASE_TRAINER")
      ;;
    embedding)
      expected_inputs=(
        "$TEACHER" "$TEACHER_AUDIT" "$RELEASE_RECEIPT" "$SPLIT_MANIFEST"
        "$EMBEDDING_MANIFEST" "$EMBEDDING_SUMMARY" "$EMBEDDING_SEQUENCE_MANIFEST"
        "$EMBEDDING_TRAINER"
      )
      ;;
    contact)
      expected_inputs=(
        "$TEACHER" "$TEACHER_AUDIT" "$SPLIT_MANIFEST" "$CONTACT_FEATURE_RECEIPT"
        "$FEATURE_SCHEMA" "$FEATURE_SCHEMA_RECEIPT" "$EMBEDDING_MANIFEST"
        "$EMBEDDING_SUMMARY" "$CONTACT_TRAINER"
      )
      ;;
  esac
  local command=("$PYTHON" "$HELPER" verify-stage --stage "$stage" --out-dir "$out_dir")
  local input
  for input in "${expected_inputs[@]}"; do command+=(--expected-input "$input"); done
  temporary=$(mktemp "$STATUS_DIR/.${stage}.verify.XXXXXX")
  if "${command[@]}" >"$temporary"; then
    mv "$temporary" "$result"
    return 0
  else
    rc=$?
  fi
  if [[ $rc -eq 4 ]]; then
    rm -f "$temporary"
    return 4
  fi
  mv "$temporary" "$STATUS_DIR/${stage}_verification_failure.json"
  write_state FAILED_STAGE_VALIDATION "stage=$stage artifact verification failed rc=$rc"
  exit "$rc"
}

run_logged_stage() {
  local stage=$1
  shift
  local temporary rc
  temporary=$(mktemp "$LOG_DIR/.${stage}.XXXXXX")
  if timeout --preserve-status "$TRAIN_TIMEOUT_SECONDS" "$@" >"$temporary" 2>&1; then
    mv "$temporary" "$LOG_DIR/${stage}.log"
    return 0
  else
    rc=$?
  fi
  mv "$temporary" "$LOG_DIR/${stage}.log"
  write_state FAILED_TRAINER "stage=$stage rc=$rc log=$LOG_DIR/${stage}.log"
  exit "$rc"
}

run_base_if_needed() {
  trust_gate before_base || {
    write_state FAILED_IMPLEMENTATION_TRUST "implementation trust drift before base"
    exit 2
  }
  if verify_stage base "$BASE_OUT" "$BASE_STAGE"; then
    return 0
  fi
  write_state RUNNING_BASE_SURROGATE "validated open258 teacher; fitting OPEN_TRAIN and selecting on OPEN_DEVELOPMENT"
  run_logged_stage base \
    "$PYTHON" "$BASE_TRAINER" \
    --teacher "$TEACHER" \
    --teacher-audit "$TEACHER_AUDIT" \
    --split-manifest "$SPLIT_MANIFEST" \
    --out-dir "$BASE_OUT"
  trust_gate after_base || {
    write_state FAILED_IMPLEMENTATION_TRUST "implementation trust drift during base"
    exit 2
  }
  recheck_preflight base
  verify_stage base "$BASE_OUT" "$BASE_STAGE"
}

run_embedding_if_needed() {
  trust_gate before_embedding || {
    write_state FAILED_IMPLEMENTATION_TRUST "implementation trust drift before embedding"
    exit 2
  }
  if verify_stage embedding "$EMBEDDING_OUT" "$EMBEDDING_STAGE"; then
    return 0
  fi
  write_state RUNNING_FROZEN_EMBEDDING_SURROGATE "base artifact verified; fitting frozen embedding models"
  run_logged_stage embedding \
    "$PYTHON" "$EMBEDDING_TRAINER" \
    --teacher "$TEACHER" \
    --teacher-audit "$TEACHER_AUDIT" \
    --release-receipt "$RELEASE_RECEIPT" \
    --split-manifest "$SPLIT_MANIFEST" \
    --embedding-manifest "$EMBEDDING_MANIFEST" \
    --embedding-summary "$EMBEDDING_SUMMARY" \
    --sequence-manifest "$EMBEDDING_SEQUENCE_MANIFEST" \
    --out-dir "$EMBEDDING_OUT"
  trust_gate after_embedding || {
    write_state FAILED_IMPLEMENTATION_TRUST "implementation trust drift during embedding"
    exit 2
  }
  recheck_preflight embedding
  verify_stage embedding "$EMBEDDING_OUT" "$EMBEDDING_STAGE"
}

run_contact_if_ready() {
  trust_gate before_contact || {
    write_state FAILED_IMPLEMENTATION_TRUST "implementation trust drift before contact"
    exit 2
  }
  if verify_stage contact "$CONTACT_OUT" "$CONTACT_STAGE"; then
    return 0
  fi
  if [[ ! -s "$CONTACT_TRAINER" ]]; then
    write_state WAITING_CONTACT_TRAINER "base and embedding artifacts verified; contact/fusion trainer script missing"
    return 4
  fi
  if ! contact_inputs_or_wait; then
    return 4
  fi
  write_state RUNNING_CONTACT_FUSION_SURROGATE "verified V3 contact release and frozen v2 allowlist; fitting contact/fusion models"
  run_logged_stage contact \
    "$PYTHON" "$CONTACT_TRAINER" \
    --teacher "$TEACHER" \
    --teacher-audit "$TEACHER_AUDIT" \
    --split-manifest "$SPLIT_MANIFEST" \
    --contact-receipt "$CONTACT_FEATURE_RECEIPT" \
    --contact-schema "$FEATURE_SCHEMA" \
    --embedding-manifest "$EMBEDDING_MANIFEST" \
    --embedding-summary "$EMBEDDING_SUMMARY" \
    --out-dir "$CONTACT_OUT"
  trust_gate after_contact || {
    write_state FAILED_IMPLEMENTATION_TRUST "implementation trust drift during contact"
    exit 2
  }
  recheck_preflight contact
  recheck_contact_inputs
  verify_stage contact "$CONTACT_OUT" "$CONTACT_STAGE"
}

trust_gate startup || { echo "V3 implementation trust-anchor verification failed" >&2; exit 2; }
write_state WAITING_OPEN_TEACHER "V3 implementation trust verified; waiting for hash-closed open258 teacher; test32 labels remain sealed"
while true; do
  if preflight_or_wait; then
    run_base_if_needed
    run_embedding_if_needed
    if run_contact_if_ready; then
      trust_gate completion || {
        write_state FAILED_IMPLEMENTATION_TRUST "implementation trust drift before completion"
        exit 2
      }
      "$PYTHON" - "$COMPLETION_RECEIPT" "$EXPECTED_TRUST_ANCHOR_SHA" \
        "$BASE_STAGE" "$EMBEDDING_STAGE" "$CONTACT_STAGE" <<'PY'
import hashlib, json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

path=Path(sys.argv[1])
anchor_sha=sys.argv[2]
stages=[Path(item) for item in sys.argv[3:]]
def digest(item): return hashlib.sha256(item.read_bytes()).hexdigest()
payload={
 "schema_version":"phase2_v4_d_surrogate_v3_completion_receipt_v1",
 "status":"PASS_V4_D_SURROGATE_V3_COMPLETE_TEST32_SEALED",
 "implementation_trust_anchor_sha256":anchor_sha,
 "stage_receipts":{item.stem:{"path":str(item.resolve()),"sha256":digest(item)} for item in stages},
 "prospective_test_labels_read":False,
 "prospective_test_label_paths_accepted":0,
 "completed_at":datetime.now(timezone.utc).isoformat(),
 "claim_boundary":"Computational docking-geometry surrogate only; not binding, affinity, competition, Docking Gold, or experimental blocking truth.",
}
path.parent.mkdir(parents=True,exist_ok=True)
with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=path.parent,delete=False) as handle:
 json.dump(payload,handle,indent=2,sort_keys=True); handle.write("\n"); tmp=Path(handle.name)
os.replace(tmp,path)
PY
      write_state COMPLETE_V4_D_SURROGATE_TRAINING_TEST32_SEALED \
        "V3 trust receipt plus base, frozen embedding, and contact/fusion artifacts verified; scientific open-gate statuses recorded separately"
      exit 0
    fi
  fi
  if [[ "$ONCE" == 1 ]]; then
    exit 4
  fi
  if (( $(date +%s) - STARTED_AT > MAX_WAIT_SECONDS )); then
    write_state BLOCKED_WAIT_TIMEOUT "wait exceeded MAX_WAIT_SECONDS=$MAX_WAIT_SECONDS"
    exit 3
  fi
  sleep "$POLL_SECONDS"
done
