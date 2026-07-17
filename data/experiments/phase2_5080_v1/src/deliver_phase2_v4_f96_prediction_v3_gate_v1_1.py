#!/usr/bin/env python3
"""Verify the canonical V4-F V3 prediction release and deliver a Node23 gate.

No prediction value is used for selection and no Docking/experimental label
path is accepted.  The remote receipt is a start prerequisite only.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


EXP=Path("/mnt/d/work/抗体/data/experiments/phase2_5080_v1")
PYTHON=EXP/".venv-phase2-5080/bin/python"
VERIFIER=EXP/"src/run_phase2_v4_f_docking_with_prediction_gate.sh"
STATUS=EXP/"status/pvrig_v4_f_prediction_freeze_v3/status.json"
RECEIPT=EXP/"predictions/pvrig_v4_f_surrogate_predictions_v1/v4_f_96_frozen_surrogate_predictions.receipt.json"
LOCAL=EXP/"status/pvrig_v4_f96_dual_docking_v1_1/prediction_v3_gate.receipt.json"
SSH=Path("/mnt/c/Windows/System32/OpenSSH/ssh.exe")
REMOTE="/data/qlyu/projects/pvrig_v4_f96_dual_redocking_v1_1_20260717_gate/prediction_v3_gate.receipt.json"
EXPECTED_VERIFIER_SHA="9e0ac6eb4e72a85f186981ff74935075eaf30796cce64bc27acbab279306a2c4"
EXPECTED_MANIFEST_SHA="3f3c504844756703acecf586b2b218f2e2855c3a108ee22656c8f08e7f57e334"


def sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def regular(path:Path)->bool:
 try:m=path.lstat();return stat.S_ISREG(m.st_mode) and not stat.S_ISLNK(m.st_mode) and m.st_size>0
 except FileNotFoundError:return False


def verify()->dict:
 if os.environ.get("PYTHONOPTIMIZE","") not in {"","0"} or os.environ.get("BASH_ENV") or os.environ.get("PYTHONPATH"):raise RuntimeError("poison_environment_forbidden")
 if not all(regular(path) for path in (PYTHON,VERIFIER,STATUS,RECEIPT)):raise RuntimeError("canonical_prediction_gate_input_missing_or_nonregular")
 if sha(VERIFIER)!=EXPECTED_VERIFIER_SHA:raise RuntimeError("prediction_receipt_verifier_hash_mismatch")
 status_payload=json.loads(STATUS.read_text());receipt_sha=sha(RECEIPT)
 if status_payload.get("status")!="COMPLETE_V4_F_96_PREDICTIONS_FROZEN" or status_payload.get("prediction_receipt_sha256")!=receipt_sha:raise RuntimeError("v3_status_or_receipt_binding_invalid")
 completed=subprocess.run([str(VERIFIER)],cwd=EXP,env={"HOME":os.environ.get("HOME","/root"),"PATH":"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin","PYTHONOPTIMIZE":"0"},stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 if completed.returncode or "PASS_V4_F_PREDICTION_GATE_DOCKING_MAY_START" not in completed.stdout:raise RuntimeError(f"canonical_prediction_receipt_verification_failed:{completed.returncode}:{completed.stdout[-500:]}")
 receipt=json.loads(RECEIPT.read_text())
 if receipt.get("v4_f_labels_read") is not False or receipt.get("v4_f_label_paths_accepted")!=0 or receipt.get("row_count")!=96:raise RuntimeError("prediction_receipt_not_label_blind_96")
 if receipt.get("holdout",{}).get("manifest_sha256")!=EXPECTED_MANIFEST_SHA:raise RuntimeError("prediction_receipt_manifest_binding_invalid")
 return {"schema_version":"phase2_v4_f96_prediction_v3_docking_gate_receipt_v1_1","status":"PASS_V4_F96_PREDICTION_V3_COMPLETION_EXACTLY_VERIFIED","published_at_utc":datetime.now(timezone.utc).isoformat(),"prediction_receipt_sha256":receipt_sha,"prediction_v3_status_sha256":sha(STATUS),"canonical_verifier_sha256":sha(VERIFIER),"manifest_sha256":EXPECTED_MANIFEST_SHA,"row_count":96,"v4_f_labels_read":False,"v4_f_label_paths_accepted":0,"prediction_values_used_for_docking_subset":False,"claim_boundary":"Label-free prediction completion gate only; no Docking, binding, affinity, competition, experimental blocking, or Docking Gold evidence."}


def publish(payload:dict)->None:
 LOCAL.parent.mkdir(parents=True,exist_ok=True);fd,name=tempfile.mkstemp(prefix=f".{LOCAL.name}.",dir=LOCAL.parent)
 raw=(json.dumps(payload,indent=2,sort_keys=True)+"\n").encode()
 try:
  with os.fdopen(fd,"wb") as handle:handle.write(raw);handle.flush();os.fsync(handle.fileno())
  os.chmod(name,0o444);os.replace(name,LOCAL)
 finally:Path(name).unlink(missing_ok=True)
 command="install -d -m 0755 /data/qlyu/projects/pvrig_v4_f96_dual_redocking_v1_1_20260717_gate && umask 022 && cat > /data/qlyu/projects/pvrig_v4_f96_dual_redocking_v1_1_20260717_gate/.prediction.tmp && chmod 0444 /data/qlyu/projects/pvrig_v4_f96_dual_redocking_v1_1_20260717_gate/.prediction.tmp && mv /data/qlyu/projects/pvrig_v4_f96_dual_redocking_v1_1_20260717_gate/.prediction.tmp /data/qlyu/projects/pvrig_v4_f96_dual_redocking_v1_1_20260717_gate/prediction_v3_gate.receipt.json"
 completed=subprocess.run([str(SSH),"node23",command],input=raw,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 if completed.returncode:raise RuntimeError(f"node23_gate_delivery_failed:{completed.stderr.decode(errors='replace')}")


def main()->int:
 if "--smoke-test" in sys.argv:print(json.dumps({"status":"PASS_V4_F96_PREDICTION_V3_GATE_DELIVERY_SMOKE","canonical_status":str(STATUS),"canonical_receipt":str(RECEIPT),"remote":REMOTE,"label_paths_accepted":0},sort_keys=True));return 0
 payload=verify();publish(payload);print(json.dumps(payload,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
