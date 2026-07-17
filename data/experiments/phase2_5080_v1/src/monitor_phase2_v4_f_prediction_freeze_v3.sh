#!/usr/bin/env bash
set -Eeuo pipefail

CANONICAL_EXP_DIR=/mnt/d/work/抗体/data/experiments/phase2_5080_v1
CANONICAL_PYTHON=$CANONICAL_EXP_DIR/.venv-phase2-5080/bin/python
CANONICAL_FREEZER=$CANONICAL_EXP_DIR/src/freeze_phase2_v4_f_surrogate_predictions.py
CANONICAL_WATCHER=$CANONICAL_EXP_DIR/src/monitor_phase2_v4_f_prediction_freeze_v3.sh
EXP_DIR=${PVRIG_EXP_DIR:-$CANONICAL_EXP_DIR}
TEST_ONLY_UNFROZEN=${V4F_TEST_ONLY_ALLOW_UNFROZEN_INPUTS:-0}
V3_TEST_ONLY=${PVRIG_V4F_WATCHER_V3_TEST_ONLY:-0}
TEST_MODE=0
if [[ "$TEST_ONLY_UNFROZEN" == 1 || "$V3_TEST_ONLY" == 1 ]]; then
  TEST_MODE=1
fi

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

if [[ "$TEST_MODE" == 1 ]]; then
  [[ "$(realpath -m -- "$EXP_DIR")" != "$(realpath -m -- "$CANONICAL_EXP_DIR")" ]] || {
    echo "all test-only modes are forbidden for the production root" >&2
    exit 2
  }
  PYTHON=${PYTHON:-python3}
  FREEZER=${V4F_PREDICTION_FREEZER:-$EXP_DIR/src/freeze_phase2_v4_f_surrogate_predictions.py}
else
  case "${PYTHONOPTIMIZE:-}" in
    ""|0) ;;
    *) echo "production PYTHONOPTIMIZE must be unset or 0" >&2; exit 2 ;;
  esac
  [[ -z "${BASH_ENV:-}" ]] || { echo "production BASH_ENV override is forbidden" >&2; exit 2; }
  [[ -z "${PYTHONPATH:-}" ]] || { echo "production PYTHONPATH override is forbidden" >&2; exit 2; }
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

SURROGATE_STATUS=${V4D_SURROGATE_STATUS:-$EXP_DIR/status/pvrig_v4_d_surrogate_training_v3/status.json}
SURROGATE_COMPLETION_RECEIPT=${V4D_SURROGATE_V3_COMPLETION_RECEIPT:-$EXP_DIR/status/pvrig_v4_d_surrogate_training_v3/surrogate_v3_completion_receipt.json}
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
STATUS_DIR=${V4F_PREDICTION_STATUS_DIR:-$EXP_DIR/status/pvrig_v4_f_prediction_freeze_v3}
LOG_DIR=${V4F_PREDICTION_LOG_DIR:-$EXP_DIR/logs/pvrig_v4_f_prediction_freeze_v3}
EXPECTED_COUNT=${V4F_EXPECTED_COUNT:-96}
TRUST_ANCHOR=${V4F_V3_TRUST_ANCHOR:-$EXP_DIR/audits/phase2_v4_f_prediction_freeze_v3_implementation_trust_anchor.json}
EXPECTED_TRUST_ANCHOR_SHA=${V4F_V3_EXPECTED_TRUST_ANCHOR_SHA:-}
EXPECTED_SURROGATE_TRUST_ANCHOR_SHA=${V4D_V3_EXPECTED_TRUST_ANCHOR_SHA:-}

canonical_path() { realpath -m -- "$1"; }
require_canonical() {
  local label=$1 actual=$2 expected=$3
  [[ "$(canonical_path "$actual")" == "$(canonical_path "$expected")" ]] || {
    echo "production path override forbidden: $label actual=$actual expected=$expected" >&2
    exit 2
  }
}

if [[ "$TEST_MODE" != 1 ]]; then
  require_canonical EXP_DIR "$EXP_DIR" "$CANONICAL_EXP_DIR"
  require_canonical PYTHON "$PYTHON" "$CANONICAL_PYTHON"
  require_canonical FREEZER "$FREEZER" "$CANONICAL_FREEZER"
  require_canonical SURROGATE_STATUS "$SURROGATE_STATUS" "$CANONICAL_EXP_DIR/status/pvrig_v4_d_surrogate_training_v3/status.json"
  require_canonical SURROGATE_COMPLETION_RECEIPT "$SURROGATE_COMPLETION_RECEIPT" "$CANONICAL_EXP_DIR/status/pvrig_v4_d_surrogate_training_v3/surrogate_v3_completion_receipt.json"
  require_canonical MANIFEST "$MANIFEST" "$CANONICAL_EXP_DIR/data_splits/pvrig_v4_f/prospective_holdout96_manifest.tsv"
  require_canonical MANIFEST_AUDIT "$MANIFEST_AUDIT" "$CANONICAL_EXP_DIR/data_splits/pvrig_v4_f/prospective_holdout96_audit.json"
  require_canonical MANIFEST_RECEIPT "$MANIFEST_RECEIPT" "$CANONICAL_EXP_DIR/data_splits/pvrig_v4_f/prospective_holdout96_receipt.json"
  require_canonical BASE_OUT "$BASE_OUT" "$CANONICAL_EXP_DIR/runs/pvrig_v4_d_sequence_surrogate_v1"
  require_canonical EMBEDDING_OUT "$EMBEDDING_OUT" "$CANONICAL_EXP_DIR/runs/pvrig_v4_d_frozen_embedding_surrogate_v1"
  require_canonical CONTACT_OUT "$CONTACT_OUT" "$CANONICAL_EXP_DIR/runs/pvrig_v4_d_contact_fusion_surrogate_v1"
  require_canonical EMBEDDING_ROOT "$EMBEDDING_ROOT" "$CANONICAL_EXP_DIR/prepared/pvrig_teacher_formal_v1_candidates/model_inputs"
  require_canonical EMBEDDING_MANIFEST "$EMBEDDING_MANIFEST" "$CANONICAL_EXP_DIR/prepared/pvrig_teacher_formal_v1_candidates/model_inputs/meanpool_embeddings/embedding_manifest_v3.csv"
  require_canonical EMBEDDING_SUMMARY "$EMBEDDING_SUMMARY" "$CANONICAL_EXP_DIR/prepared/pvrig_teacher_formal_v1_candidates/model_inputs/meanpool_embeddings/embedding_summary_v3.json"
  require_canonical EMBEDDING_SEQUENCE_MANIFEST "$EMBEDDING_SEQUENCE_MANIFEST" "$CANONICAL_EXP_DIR/prepared/pvrig_teacher_formal_v1_candidates/model_inputs/sequence_manifest_v3.csv"
  require_canonical CONTACT_RECEIPT "$CONTACT_RECEIPT" "$CANONICAL_EXP_DIR/predictions/pvrig_candidate_v2_3_residue_contact_features_v3.receipt.json"
  require_canonical CONTACT_SCHEMA "$CONTACT_SCHEMA" "$CANONICAL_EXP_DIR/prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.json"
  require_canonical OUT_DIR "$OUT_DIR" "$CANONICAL_EXP_DIR/predictions/pvrig_v4_f_surrogate_predictions_v1"
  require_canonical STATUS_DIR "$STATUS_DIR" "$CANONICAL_EXP_DIR/status/pvrig_v4_f_prediction_freeze_v3"
  require_canonical LOG_DIR "$LOG_DIR" "$CANONICAL_EXP_DIR/logs/pvrig_v4_f_prediction_freeze_v3"
  require_canonical TRUST_ANCHOR "$TRUST_ANCHOR" "$CANONICAL_EXP_DIR/audits/phase2_v4_f_prediction_freeze_v3_implementation_trust_anchor.json"
  [[ "$EXPECTED_TRUST_ANCHOR_SHA" =~ ^[0-9a-f]{64}$ ]] || { echo "missing V4-F V3 trust-anchor SHA" >&2; exit 2; }
  [[ "$EXPECTED_SURROGATE_TRUST_ANCHOR_SHA" =~ ^[0-9a-f]{64}$ ]] || { echo "missing surrogate V3 trust-anchor SHA" >&2; exit 2; }
fi

mkdir -p "$STATUS_DIR" "$LOG_DIR" "$(dirname "$OUT_DIR")"
exec 9>"$STATUS_DIR/controller.lock"
flock -n 9 || { echo "V4-F prediction freezer already running" >&2; exit 75; }
printf '%s\n' "$$" >"$STATUS_DIR/controller.pid.tmp"
mv "$STATUS_DIR/controller.pid.tmp" "$STATUS_DIR/controller.pid"
STARTED_AT=$(date +%s)

trust_gate() {
  local stage=$1 output temporary
  output=$STATUS_DIR/implementation_trust_${stage}.json
  [[ -n "$EXPECTED_TRUST_ANCHOR_SHA" ]] || {
    [[ "$V3_TEST_ONLY" == 1 ]] && return 0
    return 2
  }
  temporary=$(mktemp "$STATUS_DIR/.trust-${stage}.XXXXXX")
  if ! "$PYTHON" - "$TRUST_ANCHOR" "$EXPECTED_TRUST_ANCHOR_SHA" \
      "$EXPECTED_SURROGATE_TRUST_ANCHOR_SHA" >"$temporary" <<'PY'
import hashlib, json, stat, sys
from pathlib import Path

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

anchor=Path(sys.argv[1]); expected=sys.argv[2]; expected_surrogate=sys.argv[3]
metadata=anchor.lstat()
require(stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode) and metadata.st_size>0, "trust_anchor_not_regular")
require(digest(anchor)==expected, "trust_anchor_hash_mismatch")
payload=json.loads(anchor.read_text())
require(payload.get("schema_version")=="phase2_v4_f_prediction_implementation_trust_anchor_v3", "trust_anchor_schema_invalid")
require(payload.get("status")=="FROZEN_BEFORE_V4F_PREDICTION_FREEZE", "trust_anchor_status_invalid")
require(payload.get("anchor_kind")=="v4f_prediction_freeze", "trust_anchor_kind_invalid")
required={
 "v3_watcher","freezer","base_trainer","embedding_trainer","contact_trainer",
 "contact_extractor","contact_scorer","v2_3_trainer","v4f_manifest",
 "v4f_manifest_audit","v4f_manifest_receipt","contact_schema",
 "contact_schema_receipt","contact_features","contact_feature_audit",
 "contact_feature_receipt","embedding_manifest","embedding_summary",
 "embedding_sequence_manifest","surrogate_v3_trust_anchor",
 *(f"embedding_shard_{index:05d}" for index in range(7)),
}
files=payload.get("files")
require(isinstance(files,dict) and set(files)==required, "trust_anchor_role_set_mismatch")
require(payload.get("file_count")==len(required), "trust_anchor_file_count_mismatch")
require(files["surrogate_v3_trust_anchor"].get("sha256")==expected_surrogate, "surrogate_trust_anchor_hash_mismatch")
observed={}; paths=set()
for role, item in sorted(files.items()):
    require(isinstance(item,dict), f"trust_entry_invalid:{role}")
    path=Path(str(item.get("path","")))
    require(path.is_absolute() and str(path)==str(path.resolve()), f"trust_path_invalid:{role}")
    require(path not in paths, f"trust_duplicate_path:{role}"); paths.add(path)
    meta=path.lstat()
    require(stat.S_ISREG(meta.st_mode) and not stat.S_ISLNK(meta.st_mode), f"trust_file_not_regular:{role}")
    require(meta.st_size==item.get("size") and meta.st_size>0, f"trust_file_size_mismatch:{role}")
    observed_digest=digest(path)
    require(observed_digest==item.get("sha256"), f"trust_file_hash_mismatch:{role}")
    observed[role]={"path":str(path),"size":meta.st_size,"sha256":observed_digest}
print(json.dumps({
 "schema_version":"phase2_v4_f_prediction_freeze_watcher_v3",
 "status":"PASS_V4F_V3_IMPLEMENTATION_TRUST_ANCHOR",
 "anchor_sha256":expected,
 "file_count":len(observed),
 "files":observed,
},sort_keys=True))
PY
  then
    mv "$temporary" "$STATUS_DIR/implementation_trust_${stage}_failure.json"
    return 2
  fi
  mv "$temporary" "$output"
}

verify_surrogate_completion_receipt() {
  "$PYTHON" - "$SURROGATE_COMPLETION_RECEIPT" "$EXPECTED_SURROGATE_TRUST_ANCHOR_SHA" \
    "$EXP_DIR/status/pvrig_v4_d_surrogate_training_v3" <<'PY'
import hashlib, json, stat, sys
from pathlib import Path

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def digest(item):
    return hashlib.sha256(item.read_bytes()).hexdigest()

path=Path(sys.argv[1]); expected=sys.argv[2]; status_dir=Path(sys.argv[3]).resolve()
meta=path.lstat()
require(stat.S_ISREG(meta.st_mode) and not stat.S_ISLNK(meta.st_mode) and meta.st_size>0, "completion_receipt_not_regular")
payload=json.loads(path.read_text())
require(payload.get("schema_version")=="phase2_v4_d_surrogate_v3_completion_receipt_v1", "completion_receipt_schema_invalid")
require(payload.get("status")=="PASS_V4_D_SURROGATE_V3_COMPLETE_TEST32_SEALED", "completion_receipt_status_invalid")
require(payload.get("implementation_trust_anchor_sha256")==expected, "completion_receipt_anchor_mismatch")
require(payload.get("prospective_test_labels_read") is False, "completion_receipt_test_labels_read")
require(payload.get("prospective_test_label_paths_accepted")==0, "completion_receipt_label_paths_nonzero")
stages=payload.get("stage_receipts")
require(isinstance(stages,dict) and set(stages)=={"base_stage","embedding_stage","contact_stage"}, "completion_stage_set_invalid")
for name, item in stages.items():
    stage=Path(str(item.get("path","")))
    require(stage.resolve()==status_dir/f"{name}.json", f"completion_stage_path_invalid:{name}")
    stage_meta=stage.lstat()
    require(stat.S_ISREG(stage_meta.st_mode) and not stat.S_ISLNK(stage_meta.st_mode) and stage_meta.st_size>0, f"completion_stage_not_regular:{name}")
    require(digest(stage)==item.get("sha256"), f"completion_stage_hash_mismatch:{name}")
    stage_payload=json.loads(stage.read_text())
    require(stage_payload.get("prospective_test_labels_read") is False, f"completion_stage_labels_read:{name}")
print(json.dumps({
 "status":"PASS_VERIFIED_SURROGATE_V3_COMPLETION_RECEIPT",
 "receipt_sha256":digest(path),
 "implementation_trust_anchor_sha256":expected,
 "prospective_test_labels_read":False,
},sort_keys=True))
PY
}

write_status() {
  local state=$1 reason=$2 receipt_sha=${3:-}
  STATE_VALUE=$state REASON_VALUE=$reason RECEIPT_SHA_VALUE=$receipt_sha STATUS_PATH=$STATUS_DIR/status.json PID_VALUE=$$ "$PYTHON" - <<'PY'
import json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path
path=Path(os.environ["STATUS_PATH"]); path.parent.mkdir(parents=True,exist_ok=True)
payload={
 "schema_version":"phase2_v4_f_prediction_freeze_watcher_v3",
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

trust_gate startup || { echo "V4-F V3 implementation trust gate failed" >&2; exit 2; }
write_status WAITING_V4_D_SURROGATES "V3 implementation trust verified; waiting for verified surrogate V3 completion receipt; V4-F labels remain sealed"
while true; do
  if ! trust_gate poll; then
    write_status BLOCKED_IMPLEMENTATION_TRUST "V4-F V3 implementation trust drift"
    exit 2
  fi
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
    if ! verify_surrogate_completion_receipt >"$STATUS_DIR/surrogate_v3_completion_verification.json" 2>&1; then
      write_status BLOCKED_INVALID_SURROGATE_V3_RECEIPT "surrogate status complete but V3 completion receipt failed verification"
      exit 2
    fi
    trust_gate before_freeze || {
      write_status BLOCKED_IMPLEMENTATION_TRUST "V4-F V3 implementation drift before freeze"
      exit 2
    }
    write_status RUNNING_V4_F_PREDICTION_FREEZE "all V4-D artifact receipts complete; generating 96 unlabeled predictions"
    run_freezer
    trust_gate after_freeze || {
      write_status BLOCKED_IMPLEMENTATION_TRUST "V4-F V3 implementation drift during freeze"
      exit 2
    }
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
