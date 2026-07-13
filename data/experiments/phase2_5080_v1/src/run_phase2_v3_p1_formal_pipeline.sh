#!/usr/bin/env bash
# Run the sealed V3-P full and label-null training lanes, then evaluate once.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT/../.."
PYTHON_BIN=${PYTHON_BIN:-python}
CONFIG=${CONFIG:-$ROOT/configs/phase2_v3_p1_formal.json}
DATA_DIR=${DATA_DIR:-$ROOT/prepared/phase2_v3_p1_formal}
RUN_STAMP=${RUN_STAMP:-$(date +%Y%m%dT%H%M%S)}
RUN_ROOT=${RUN_ROOT:-$ROOT/runs/phase2_v3_p1_formal/formal_$RUN_STAMP}
FULL_RUN="$RUN_ROOT/full"
LABEL_RUN="$RUN_ROOT/label_shuffle"
BUNDLE="$RUN_ROOT/evaluation_bundle"
EVALUATION="$RUN_ROOT/formal_evaluation"
LOG="$RUN_ROOT/formal_pipeline.log"

mkdir -p "$RUN_ROOT"
exec > >(tee -a "$LOG") 2>&1

"$PYTHON_BIN" - "$CONFIG" <<'PY'
import json
import sys

config = json.load(open(sys.argv[1]))
if config.get("device") == "cuda":
    import torch

    if not torch.cuda.is_available():
        raise SystemExit(
            f"CUDA preflight failed for {sys.executable}: torch={torch.__version__}"
        )
    print(
        "V3P_CUDA_PREFLIGHT "
        f"python={sys.executable} torch={torch.__version__} "
        f"cuda={torch.version.cuda} device={torch.cuda.get_device_name(0)}"
    )
PY

if [[ -e "$EVALUATION/formal_evaluation.json" ]]; then
  echo "Refusing to unseal/evaluate the same formal run twice: $EVALUATION" >&2
  exit 8
fi

"$PYTHON_BIN" "$ROOT/src/prepare_phase2_v3_p1_formal_data.py"

"$PYTHON_BIN" "$ROOT/src/train_phase2_v3_p1_formal.py" \
  --config "$CONFIG" --run-dir "$FULL_RUN" --control full

"$PYTHON_BIN" "$ROOT/src/train_phase2_v3_p1_formal.py" \
  --config "$CONFIG" --run-dir "$LABEL_RUN" --control label_shuffle

"$PYTHON_BIN" "$ROOT/src/build_phase2_v3_p1_formal_bundle.py" \
  --full-training-summary "$FULL_RUN/training_summary.json" \
  --label-shuffle-training-summary "$LABEL_RUN/training_summary.json" \
  --preregistration "$ROOT/audits/phase2_v3_p1_preregistration.json" \
  --test-spec "$ROOT/audits/phase2_v3_p1_test_spec.json" \
  --config "$CONFIG" \
  --teacher-open "$DATA_DIR/pvrig_teacher_train_dev_v1.csv" \
  --teacher-test-sealed "$DATA_DIR/pvrig_teacher_formal_labels_sealed_v1.csv" \
  --formal-data-audit "$ROOT/audits/phase2_v3_p1_formal_data_audit.json" \
  --model-input-validation "$ROOT/prepared/pvrig_teacher_formal_v1/model_inputs/model_input_validation.json" \
  --trainer-source "$ROOT/src/train_phase2_v3_p1_formal.py" \
  --model-source "$ROOT/src/phase2_v3_p1_model.py" \
  --evaluator-source "$ROOT/src/evaluate_phase2_v3_p1_formal.py" \
  --bundle-builder-source "$ROOT/src/build_phase2_v3_p1_formal_bundle.py" \
  --output-dir "$BUNDLE"

"$PYTHON_BIN" "$ROOT/src/evaluate_phase2_v3_p1_formal.py" \
  --teacher-open "$DATA_DIR/pvrig_teacher_train_dev_v1.csv" \
  --teacher-test-sealed "$DATA_DIR/pvrig_teacher_formal_labels_sealed_v1.csv" \
  --seed-prediction "83=$FULL_RUN/seed_83/test_predictions.csv" \
  --seed-prediction "89=$FULL_RUN/seed_89/test_predictions.csv" \
  --seed-prediction "97=$FULL_RUN/seed_97/test_predictions.csv" \
  --baseline-predictions "$BUNDLE/baseline_predictions.csv" \
  --control-predictions "$BUNDLE/control_predictions.csv" \
  --generic-replay-retention "$BUNDLE/generic_replay_retention.json" \
  --artifact-manifest "$BUNDLE/formal_artifact_manifest.json" \
  --output-dir "$EVALUATION"

"$PYTHON_BIN" - "$RUN_ROOT" "$CONFIG" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root, config = map(Path, sys.argv[1:])

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

evaluation = json.loads((root / "formal_evaluation/formal_evaluation.json").read_text())
payload = {
    "status": "PASS_V3_P1_FORMAL_PIPELINE_EXECUTED",
    "formal_gate_status": evaluation["status"],
    "run_root": str(root),
    "config_sha256": sha(config),
    "artifact_manifest_sha256": sha(root / "evaluation_bundle/formal_artifact_manifest.json"),
    "formal_evaluation_sha256": sha(root / "formal_evaluation/formal_evaluation.json"),
    "claim_boundary": evaluation["claim_boundary"],
}
(root / "pipeline_summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
print(json.dumps(payload, indent=2, sort_keys=True))
PY

printf '%s\n' "$RUN_ROOT" >"$ROOT/logs/phase2_v3_p1_latest_formal_run.txt"
touch "$RUN_ROOT/formal_pipeline.complete"
echo "PASS_PHASE2_V3_P1_FORMAL_PIPELINE run_root=$RUN_ROOT"
