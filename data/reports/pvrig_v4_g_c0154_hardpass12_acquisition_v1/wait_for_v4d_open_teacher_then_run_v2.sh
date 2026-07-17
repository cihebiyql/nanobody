#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=${PVRIG_V4G12_ROOT:?PVRIG_V4G12_ROOT required}
SOURCE=${PVRIG_V4D_SOURCE:-/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715}
OPEN_TEACHER=${PVRIG_V4D_OPEN_TEACHER_ROOT:-/data/qlyu/projects/pvrig_v4_d_open_teacher_postprocess_v1_20260716}
POLL=${PVRIG_V4G12_POLL_SECONDS:-300}
MAX_LOAD1=${PVRIG_V4G12_MAX_LOAD1:-16}
PYTHON=${PVRIG_V4G12_PYTHON:-/data/qlyu/anaconda3/envs/haddock3/bin/python}
ANCHOR="$ROOT/WAITER_TRUST_ANCHOR_V2.json"
VERIFIER="$ROOT/scripts/verify_open_teacher_release_v1.py"

mkdir -p "$ROOT/status" "$ROOT/logs"
echo $$ > "$ROOT/status/waiter_v2.pid"

while true; do
  set +e
  "$PYTHON" - "$ROOT" "$SOURCE" "$OPEN_TEACHER" "$MAX_LOAD1" "$0" "$VERIFIER" "$ANCHOR" <<'PY'
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

root, source, open_teacher = map(Path, sys.argv[1:4])
max_load = float(sys.argv[4])
self_path, verifier, anchor_path = map(Path, sys.argv[5:8])

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
assert anchor["status"] == "TRUST_ANCHOR_V2_FROZEN_BEFORE_WAITER_START"
assert sha(root / "ACQUISITION_PROTOCOL_LOCK.json") == anchor["acquisition_protocol_lock_sha256"]
assert sha(self_path) == anchor["waiter_v2_sha256"]
assert sha(verifier) == anchor["open_teacher_release_verifier_sha256"]
assert sha(root / "status/waiter_upgrade_v2_receipt.json") == anchor["waiter_upgrade_receipt_sha256"]
for item in anchor["open_teacher_code_bindings"]:
    path = Path(item["path"])
    assert sha(path) == item["sha256"], path

lock = json.loads((root / "ACQUISITION_PROTOCOL_LOCK.json").read_text(encoding="utf-8"))
assert lock["status"] == "LOCKED_ACQUISITION_ONLY_72_JOBS"
upgrade = json.loads((root / "status/waiter_upgrade_v2_receipt.json").read_text(encoding="utf-8"))
assert upgrade["status"] == "PASS_V1_WAITER_STOPPED_BEFORE_ACQUISITION_V2_READY"
assert upgrade["acquisition_jobs_started_before_upgrade"] == 0

controller = json.loads((source / "status/controller.json").read_text(encoding="utf-8"))
terminal = controller.get("status") in {"COMPLETE", "COMPLETE_WITH_FAILURES"}
counts = controller.get("counts") or controller.get("counts_before") or {}
closed = int(counts.get("SUCCESS", 0)) + int(counts.get("FAILED_MAX_ATTEMPTS", 0)) == 2022
no_active = all(int(counts.get(key, 0)) == 0 for key in ("RUNNING", "PENDING", "QUEUED"))

postprocess_status_path = open_teacher / "status/postprocess_status.json"
try:
    postprocess_status = json.loads(postprocess_status_path.read_text(encoding="utf-8"))
except (OSError, ValueError, json.JSONDecodeError):
    postprocess_status = {"status": "MISSING_OR_UNREADABLE"}

verification = subprocess.run(
    [sys.executable, str(verifier), "--root", str(open_teacher)],
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    check=False,
)
try:
    release_gate = json.loads(verification.stdout)
except (ValueError, json.JSONDecodeError):
    release_gate = {"status": "BLOCKED", "reasons": ["verifier_output_unreadable"]}
release_ready = (
    verification.returncode == 0
    and postprocess_status.get("status") == "COMPLETE"
    and release_gate.get("status") == "READY"
    and release_gate.get("test32_sealed") is True
)

load1 = os.getloadavg()[0]
payload = {
    "schema_version": "pvrig_v4_g_c0154_hardpass12_waiter_gate_v2",
    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    "source_status": controller.get("status"),
    "counts": counts,
    "terminal": terminal,
    "closed": closed,
    "no_active": no_active,
    "open_teacher_postprocess_status": postprocess_status.get("status"),
    "open_teacher_release_gate": release_gate,
    "open_teacher_ready_test32_sealed": release_ready,
    "load1": load1,
    "max_load1": max_load,
}
(root / "status/waiter_gate_v2.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)

ready = terminal and closed and no_active and release_ready and load1 <= max_load
raise SystemExit(0 if ready else 3)
PY
  rc=$?
  set -e
  if [[ $rc -eq 0 ]]; then
    break
  fi
  echo "WAIT_V4D_OPEN_TEACHER_TEST32_SEALED_OR_LOAD $(date -Is) rc=$rc" >> "$ROOT/logs/waiter_v2.log"
  sleep "$POLL"
done

echo "GATE_V2_PASS_START_ACQUISITION $(date -Is)" >> "$ROOT/logs/waiter_v2.log"
cd "$ROOT"
export PVRIG_PROJECT_ROOT="$ROOT"
exec "$PYTHON" scripts/run_controller.py \
  --max-parallel 12 --max-attempts 2 --poll-seconds 60 \
  >> "$ROOT/logs/acquisition_controller.log" 2>&1
