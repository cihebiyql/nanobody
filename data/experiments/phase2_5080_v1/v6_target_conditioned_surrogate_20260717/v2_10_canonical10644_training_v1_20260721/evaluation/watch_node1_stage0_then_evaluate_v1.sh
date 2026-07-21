#!/usr/bin/env bash
# Wait for the immutable V2.10 Stage0 run, then evaluate open development only.
set -euo pipefail

ROOT="${ROOT:-/data1/qlyu/projects/pvrig_v29_canonical_merged_teacher_v1_20260721}"
PY="${PY:-/data1/qlyu/software/envs/pvrig-v6-tc/bin/python}"
TRAIN_ROOT="${TRAIN_ROOT:-$ROOT/training/stage0_sequence_v2_10_3seed_v1}"
EVALUATOR="${EVALUATOR:-$ROOT/evaluation/evaluate_v2_10_open_development.py}"
TEACHER="${TEACHER:-$ROOT/prepared/primary_D1_canonical10644_teacher.tsv}"
SPLIT="${SPLIT:-$ROOT/prepared/primary_D1_canonical10644_split_manifest.json}"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT/evaluation_outputs/stage0_open_development_v1}"
STATUS_DIR="${STATUS_DIR:-$ROOT/status/stage0_open_development_evaluation_v1}"
TRAIN_PID_FILE="${TRAIN_PID_FILE:-$ROOT/status/stage0_sequence_v2_10_3seed_v1.pid}"
POLL_SECONDS="${POLL_SECONDS:-30}"
EXPECTED_TEACHER_SHA256="${EXPECTED_TEACHER_SHA256:-46bc32276a574e21bb92d7e6672b18aa68323c778b4f65d2415a384144ab95c3}"

mkdir -p "$STATUS_DIR"
test -x "$PY"
test -f "$EVALUATOR"
test -f "$TEACHER"
test -f "$SPLIT"
test ! -e "$OUTPUT_DIR"
test "$(sha256sum "$TEACHER" | awk '{print $1}')" = "$EXPECTED_TEACHER_SHA256"

write_status() {
  local status="$1"
  local detail="$2"
  STATUS_PATH="$STATUS_DIR/watcher_status.json" \
  STATUS_VALUE="$status" DETAIL_VALUE="$detail" \
  TRAIN_ROOT_VALUE="$TRAIN_ROOT" OUTPUT_DIR_VALUE="$OUTPUT_DIR" \
  "$PY" - <<'PY'
import json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path

path = Path(os.environ["STATUS_PATH"])
payload = {
    "schema_version": "pvrig_v2_10_stage0_evaluation_watcher_v1",
    "status": os.environ["STATUS_VALUE"],
    "detail": os.environ["DETAIL_VALUE"],
    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    "training_root": os.environ["TRAIN_ROOT_VALUE"],
    "output_dir": os.environ["OUTPUT_DIR_VALUE"],
    "frozen_test_access_count": 0,
    "sealed_truth_access_count": 0,
}
path.parent.mkdir(parents=True, exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
os.close(fd)
Path(temporary).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
os.replace(temporary, path)
PY
}

on_error() {
  local rc="$?"
  write_status "FAILED_EVALUATION_WATCHER" "line=$1 rc=$rc"
  exit "$rc"
}
trap 'on_error $LINENO' ERR

write_status "WAITING_STAGE0_MULTISEED" "waiting for PASS_MULTISEED_COMPLETE"
while [[ ! -f "$TRAIN_ROOT/MULTISEED_SUMMARY.json" ]]; do
  if [[ -f "$TRAIN_PID_FILE" ]]; then
    train_pid="$(cat "$TRAIN_PID_FILE")"
    if ! kill -0 "$train_pid" 2>/dev/null; then
      write_status "FAILED_STAGE0_TERMINATED" "training PID exited without MULTISEED_SUMMARY.json"
      exit 3
    fi
  fi
  sleep "$POLL_SECONDS"
done

"$PY" - "$TRAIN_ROOT/MULTISEED_SUMMARY.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
if payload.get("status") != "PASS_MULTISEED_COMPLETE":
    raise SystemExit("multiseed_status_not_pass")
if payload.get("seeds") != [43, 97, 193]:
    raise SystemExit("multiseed_seed_contract")
PY

write_status "RUNNING_OPEN_DEVELOPMENT_EVALUATION" "Stage0 complete; evaluating seed ensemble"
"$PY" "$EVALUATOR" \
  --teacher-tsv "$TEACHER" \
  --expected-teacher-sha256 "$EXPECTED_TEACHER_SHA256" \
  --split-manifest "$SPLIT" \
  --prediction "43=$TRAIN_ROOT/seed_43/OPEN_SCORE_PREDICTIONS.tsv" \
  --prediction "97=$TRAIN_ROOT/seed_97/OPEN_SCORE_PREDICTIONS.tsv" \
  --prediction "193=$TRAIN_ROOT/seed_193/OPEN_SCORE_PREDICTIONS.tsv" \
  --expected-seeds 43,97,193 \
  --output-dir "$OUTPUT_DIR"

"$PY" - "$OUTPUT_DIR" "$STATUS_DIR/terminal.json" <<'PY'
import hashlib, json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

out = Path(sys.argv[1])
terminal = Path(sys.argv[2])
metrics = json.loads((out / "DEVELOPMENT_METRICS.json").read_text())
if metrics.get("status") != "PASS_V2_10_OPEN_DEVELOPMENT_EVALUATION":
    raise SystemExit("development_evaluation_not_pass")
access = metrics.get("input_access", {})
if access.get("frozen_test_truth_rows") != 0 or access.get("sealed_truth_files") != 0:
    raise SystemExit("development_evaluation_firewall")

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

payload = {
    "schema_version": "pvrig_v2_10_stage0_evaluation_terminal_v1",
    "status": "PASS_STAGE0_AND_OPEN_DEVELOPMENT_EVALUATION",
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "selected_model": metrics["development_selected_model"],
    "development_rows": metrics["counts"]["development"],
    "frozen_test_access_count": 0,
    "sealed_truth_access_count": 0,
    "artifacts": {
        "DEVELOPMENT_METRICS.json": sha(out / "DEVELOPMENT_METRICS.json"),
        "MODEL_SELECTION.tsv": sha(out / "MODEL_SELECTION.tsv"),
        "SHA256SUMS": sha(out / "SHA256SUMS"),
    },
}
terminal.parent.mkdir(parents=True, exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix=f".{terminal.name}.", dir=terminal.parent)
os.close(fd)
Path(temporary).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
os.replace(temporary, terminal)
PY

write_status "PASS_STAGE0_AND_OPEN_DEVELOPMENT_EVALUATION" "terminal.json published"
