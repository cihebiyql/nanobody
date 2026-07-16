#!/usr/bin/env bash
set -Eeuo pipefail

EXP_DIR=${PVRIG_EXP_DIR:-/mnt/d/work/抗体/data/experiments/phase2_5080_v1}
PYTHON=${PYTHON:-python3}
SCORER=${V4D_DEPLOYMENT_SCORER:-$EXP_DIR/src/score_phase2_v4_d_deployment.py}
SURROGATE_STATUS=${V4D_SURROGATE_STATUS:-$EXP_DIR/status/pvrig_v4_d_surrogate_training_v1/status.json}
OUT_DIR=${V4D_DEPLOYMENT_OUT:-$EXP_DIR/runs/pvrig_v4_d_deployment_scoring_v1}
STATUS_DIR=${V4D_DEPLOYMENT_STATUS_DIR:-$EXP_DIR/status/pvrig_v4_d_deployment_scoring_v1}
POLL_SECONDS=${POLL_SECONDS:-300}
MAX_WAIT_SECONDS=${MAX_WAIT_SECONDS:-604800}
ONCE=${ONCE:-0}

mkdir -p "$STATUS_DIR" "$OUT_DIR"
exec 9>"$STATUS_DIR/controller.lock"
flock -n 9 || { echo "V4-D deployment scoring watcher already running" >&2; exit 75; }
printf '%s\n' "$$" >"$STATUS_DIR/controller.pid.tmp"
mv "$STATUS_DIR/controller.pid.tmp" "$STATUS_DIR/controller.pid"
STARTED_AT=$(date +%s)

write_state() {
  local state=$1 reason=$2
  "$PYTHON" - "$STATUS_DIR/status.json" "$state" "$reason" "$SURROGATE_STATUS" "$OUT_DIR" <<'PY'
import json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "schema_version": "phase2_v4_d_deployment_scoring_watcher_v1",
    "status": sys.argv[2],
    "reason": sys.argv[3],
    "surrogate_status_path": str(Path(sys.argv[4]).resolve()),
    "deployment_output_directory": str(Path(sys.argv[5]).resolve()),
    "prospective_test_labels_read": False,
    "prospective_test_label_paths_accepted": 0,
    "v4f_labels_read": False,
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "claim_boundary": (
        "Watcher control state for label-free V4-D deployment scoring only; "
        "not binding, affinity, competition, Docking Gold, or experimental blocking evidence."
    ),
}
path.parent.mkdir(parents=True, exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
}

surrogate_state() {
  "$PYTHON" - "$SURROGATE_STATUS" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
if not path.is_file():
    print("MISSING")
else:
    try: print(json.loads(path.read_text(encoding="utf-8")).get("status", "INVALID"))
    except Exception: print("INVALID")
PY
}

run_scorer() {
  local run_output=$STATUS_DIR/scorer_run.json
  local temporary
  temporary=$(mktemp "$STATUS_DIR/.scorer-run.XXXXXX")
  if "$PYTHON" "$SCORER" --out-dir "$OUT_DIR" >"$temporary"; then
    mv "$temporary" "$run_output"
  else
    local rc=$?
    mv "$temporary" "$STATUS_DIR/scorer_failure.log"
    write_state FAILED_DEPLOYMENT_SCORER "scorer exited rc=$rc"
    return "$rc"
  fi
  "$PYTHON" - "$run_output" <<'PY'
import json, sys
print(json.loads(open(sys.argv[1], encoding="utf-8").read()).get("status", "INVALID"))
PY
}

verify_release() {
  local temporary
  temporary=$(mktemp "$STATUS_DIR/.verify.XXXXXX")
  if "$PYTHON" "$SCORER" --verify-only --out-dir "$OUT_DIR" >"$temporary"; then
    mv "$temporary" "$STATUS_DIR/release_verification.json"
    return 0
  fi
  local rc=$?
  mv "$temporary" "$STATUS_DIR/release_verification_failure.log"
  write_state FAILED_DEPLOYMENT_RELEASE_VERIFICATION "receipt verification exited rc=$rc"
  return "$rc"
}

write_state WAITING_SURROGATE_COMPLETE "waiting for COMPLETE_V4_D_SURROGATE_TRAINING_TEST32_SEALED"
while true; do
  state=$(surrogate_state)
  if [[ "$state" == COMPLETE_V4_D_SURROGATE_TRAINING_TEST32_SEALED ]]; then
    scoring_status=$(run_scorer) || exit $?
    if [[ "$scoring_status" == WAITING_FROZEN_MODEL_ARTIFACTS ]]; then
      write_state WAITING_FROZEN_MODEL_ARTIFACTS \
        "surrogate status claimed complete but scorer dynamically found missing artifacts"
      [[ "$ONCE" == 1 ]] && exit 4
    elif [[ "$scoring_status" == PASS_DEPLOYMENT_SCORES_ROUTED || "$scoring_status" == PASS_INFERENCE_ONLY_SCORES_EXPLOITATION_BLOCKED ]]; then
      verify_release || exit $?
      write_state COMPLETE_V4_D_DEPLOYMENT_SCORING \
        "scorer replayed all artifacts and receipt hash closure passed"
      exit 0
    else
      write_state FAILED_DEPLOYMENT_SCORER "unexpected scorer status=$scoring_status"
      exit 2
    fi
  else
    write_state WAITING_SURROGATE_COMPLETE "observed surrogate status=$state"
    [[ "$ONCE" == 1 ]] && exit 4
  fi
  if (( $(date +%s) - STARTED_AT > MAX_WAIT_SECONDS )); then
    write_state BLOCKED_WAIT_TIMEOUT "wait exceeded MAX_WAIT_SECONDS=$MAX_WAIT_SECONDS"
    exit 3
  fi
  sleep "$POLL_SECONDS"
done
