#!/usr/bin/env bash
set -euo pipefail

EXP_DIR=/mnt/d/work/抗体/data/experiments/phase2_5080_v1
DELIVERY=$EXP_DIR/src/deliver_phase2_v4_d_dev1_open258_from_node23.py
FREEZE=$EXP_DIR/audits/phase2_v4_d_dev1_open258_launch_authorized_freeze.json
PYTHON=${PVRIG_V4D_DEV1_LOCAL_PYTHON:-/usr/bin/python3}
DELIVERY_ROOT=$EXP_DIR/prepared/pvrig_v4_d_dev1_open258_v1/delivery_dev1
SSH_EXE=/mnt/c/Windows/System32/OpenSSH/ssh.exe

# Candidate freeze is intentionally insufficient.  The Python delivery layer
# independently rechecks the same launch-authorized status and hashes.
"$PYTHON" - "$FREEZE" "$DELIVERY" "$0" <<'PY'
import hashlib, json, stat, sys
from pathlib import Path
freeze_path,delivery,launcher=map(Path,sys.argv[1:])
def digest(path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
for path in (freeze_path,delivery,launcher):
 st=path.lstat()
 if not stat.S_ISREG(st.st_mode): raise SystemExit(f"not_regular:{path}")
freeze=json.loads(freeze_path.read_text())
if freeze.get("status")!="FROZEN_FOR_DEV1_REMOTE_EXECUTION" or freeze.get("remote_execution_authorized") is not True:
 raise SystemExit("launch_authorization_missing")
if freeze.get("test32_raw_job_files_opened")!=0 or freeze.get("formal_v4_f_unlock_eligible") is not False:
 raise SystemExit("launch_freeze_boundary_invalid")
files=freeze.get("files") or {}
for key,path in (("delivery",delivery),("delivery_launcher",launcher)):
 if (files.get(key) or {}).get("sha256")!=digest(path): raise SystemExit(f"launch_freeze_hash_mismatch:{key}")
PY

exec "$PYTHON" "$DELIVERY" \
  --watch --production \
  --freeze "$FREEZE" \
  --delivery-root "$DELIVERY_ROOT" \
  --ssh-exe "$SSH_EXE" \
  --remote-host node23 \
  --remote-root /data/qlyu/projects/pvrig_v4_d_dev1_open258_v1_20260717 \
  --poll-seconds 60
