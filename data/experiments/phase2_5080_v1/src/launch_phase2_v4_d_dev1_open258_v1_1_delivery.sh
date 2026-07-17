#!/usr/bin/env bash
set -euo pipefail

EXP_DIR=/mnt/d/work/抗体/data/experiments/phase2_5080_v1
DELIVERY=$EXP_DIR/src/deliver_phase2_v4_d_dev1_open258_v1_1_from_node23.py
FREEZE=$EXP_DIR/audits/phase2_v4_d_dev1_open258_v1_1_launch_authorized_freeze.json
PYTHON=${PVRIG_V4D_DEV1_V11_LOCAL_PYTHON:-/usr/bin/python3}
DELIVERY_ROOT=$EXP_DIR/prepared/pvrig_v4_d_dev1_open258_v1_1/delivery_dev1_v1_1
SSH_EXE=/mnt/c/Windows/System32/OpenSSH/ssh.exe

# This launcher cannot consume the candidate freeze.  The Python delivery
# validator independently rechecks the launch-authorized freeze and every
# immutable development-only boundary before opening SSH.
"$PYTHON" - "$FREEZE" "$DELIVERY" "$0" <<'PY'
import hashlib,json,stat,sys
from pathlib import Path
freeze_path,delivery,launcher=map(Path,sys.argv[1:])
def digest(path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
 return h.hexdigest()
for path in (freeze_path,delivery,launcher):
 if not stat.S_ISREG(path.lstat().st_mode): raise SystemExit(f"not_regular:{path}")
freeze=json.loads(freeze_path.read_text(encoding="utf-8"))
if freeze.get("status")!="FROZEN_FOR_DEV1_V1_1_REMOTE_EXECUTION": raise SystemExit("v1_1_launch_freeze_status_invalid")
if freeze.get("remote_execution_authorized") is not True or freeze.get("remote_execution_started") is not False: raise SystemExit("v1_1_launch_authorization_invalid")
for field in ("test32_raw_job_files_opened","test32_metric_values_read","test32_label_rows_emitted"):
 if freeze.get(field)!=0: raise SystemExit(f"v1_1_launch_boundary_nonzero:{field}")
if freeze.get("source_evaluator_status")!="FAIL" or freeze.get("source_evaluator_unlockable") is not False: raise SystemExit("v1_1_source_evaluator_boundary_invalid")
if freeze.get("formal_v4_f_unlock_eligible") is not False or freeze.get("final_submission_authority") is not False: raise SystemExit("v1_1_authority_boundary_invalid")
files=freeze.get("files") or {}
for key,path in (("delivery",delivery),("delivery_launcher",launcher)):
 if (files.get(key) or {}).get("sha256")!=digest(path): raise SystemExit(f"v1_1_launch_freeze_hash_mismatch:{key}")
PY

exec "$PYTHON" "$DELIVERY" \
  --watch --production \
  --freeze "$FREEZE" \
  --delivery-root "$DELIVERY_ROOT" \
  --ssh-exe "$SSH_EXE" \
  --remote-host node23 \
  --remote-root /data/qlyu/projects/pvrig_v4_d_dev1_open258_v1_1_20260717 \
  --poll-seconds 60
