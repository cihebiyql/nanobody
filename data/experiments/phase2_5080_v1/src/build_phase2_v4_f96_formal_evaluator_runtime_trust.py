#!/usr/bin/env python3
"""Create/verify the non-circular V4-F96 formal evaluator runtime trust root."""
from __future__ import annotations
import argparse, hashlib, json, os, stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE=Path(__file__).resolve(); SRC=HERE.parent; EXP=SRC.parent
FREEZE=EXP/'audits/phase2_v4_f96_formal_evaluator_v1_implementation_freeze.json'
FREEZE_RECEIPT=EXP/'audits/phase2_v4_f96_formal_evaluator_v1_implementation_freeze.receipt.json'
ANCHOR=EXP/'audits/phase2_v4_f96_formal_evaluator_v1_runtime_trust_anchor.json'
LAUNCHER=SRC/'launch_phase2_v4_f96_formal_evaluation_v1.sh'
DEPLOYMENT=EXP/'audits/phase2_v4_f96_formal_evaluator_v1_runtime_trust_deployment_receipt.json'
PYTHON=EXP/'.venv-phase2-5080/bin/python'

def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def meta(p:Path)->dict[str,Any]:
 if not p.is_file() or p.is_symlink(): raise RuntimeError(f'bad_file:{p}')
 return {'path':str(p.resolve()),'sha256':sha(p),'size_bytes':p.stat().st_size}
def write(p:Path,x:Any,mode:int=0o444):
 p.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n'); p.chmod(mode)
def verify()->dict[str,Any]:
 for p in (ANCHOR,LAUNCHER,DEPLOYMENT):
  if not p.is_file() or p.is_symlink(): raise RuntimeError(f'missing_runtime_trust_artifact:{p}')
 a=json.loads(ANCHOR.read_text()); d=json.loads(DEPLOYMENT.read_text())
 if a.get('status')!='PASS_NONCIRCULAR_RUNTIME_TRUST_ANCHOR_FROZEN':raise RuntimeError('anchor_status')
 for role,item in a['files'].items():
  p=Path(item['path'])
  if not p.is_file() or p.is_symlink() or sha(p)!=item['sha256']:raise RuntimeError(f'anchor_file_mismatch:{role}')
 if d.get('status')!='PASS_V4_F96_FORMAL_RUNTIME_TRUST_DEPLOYED':raise RuntimeError('deployment_status')
 if d['runtime_trust_anchor_sha256']!=sha(ANCHOR) or d['launcher_sha256']!=sha(LAUNCHER):raise RuntimeError('deployment_hash_mismatch')
 return {'status':'PASS_V4_F96_FORMAL_RUNTIME_TRUST_VERIFIED','anchor_sha256':sha(ANCHOR),'launcher_sha256':sha(LAUNCHER),'deployment_receipt_sha256':sha(DEPLOYMENT)}
def build()->dict[str,Any]:
 if any(p.exists() for p in (ANCHOR,LAUNCHER,DEPLOYMENT)):raise RuntimeError('runtime_trust_artifact_exists_refuse_overwrite')
 f=json.loads(FREEZE.read_text()); r=json.loads(FREEZE_RECEIPT.read_text())
 if f.get('status')!='PASS_IMPLEMENTATION_FROZEN_BEFORE_V4F96_LABEL_UNSEAL':raise RuntimeError('freeze_status')
 if r.get('status')!='PASS_COMPLETE_HASH_CLOSURE_BEFORE_V4F96_LABEL_UNSEAL' or r['implementation_freeze']['sha256']!=sha(FREEZE):raise RuntimeError('freeze_receipt')
 files={k:v for k,v in f['implementation_files'].items()}
 files.update({'implementation_freeze':meta(FREEZE),'implementation_freeze_receipt':meta(FREEZE_RECEIPT)})
 anchor={'schema_version':'phase2_v4_f96_formal_evaluator_runtime_trust_anchor_v1','status':'PASS_NONCIRCULAR_RUNTIME_TRUST_ANCHOR_FROZEN','created_at':datetime.now(timezone.utc).isoformat(),'files':files,'label_access':{'v4_f96_docking_labels_read':False,'formal_evaluation_executed':False},'authority':'The canonical launcher hardcodes this anchor SHA. Direct evaluator execution is non-authoritative.'}
 write(ANCHOR,anchor)
 ah=sha(ANCHOR)
 script=f'''#!/usr/bin/env bash
set -Eeuo pipefail
ANCHOR={ANCHOR}
EXPECTED={ah}
PYTHON={PYTHON}
EVALUATOR={SRC/'evaluate_phase2_v4_f96_formal.py'}
observed=$(sha256sum "$ANCHOR" | awk '{{print $1}}')
[[ "$observed" == "$EXPECTED" ]] || {{ echo runtime_trust_anchor_hash_mismatch >&2; exit 2; }}
"$PYTHON" - "$ANCHOR" <<'PYVERIFY'
import hashlib,json,sys
from pathlib import Path
a=Path(sys.argv[1]); x=json.loads(a.read_text())
assert x['status']=='PASS_NONCIRCULAR_RUNTIME_TRUST_ANCHOR_FROZEN'
for role,item in x['files'].items():
 p=Path(item['path']); assert p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256'], role
print('PASS_V4_F96_RUNTIME_TRUST_ANCHOR')
PYVERIFY
[[ "${{1:-}}" == "--verify-trust-only" ]] && exit 0
(( $# == 0 )) || {{ echo launcher_accepts_no_runtime_overrides >&2; exit 2; }}
export V4F96_FORMAL_TRUST_ANCHOR_SHA256="$EXPECTED"
exec "$PYTHON" "$EVALUATOR" --trust-anchor "$ANCHOR"
'''
 LAUNCHER.write_text(script); LAUNCHER.chmod(0o555)
 dep={'schema_version':'phase2_v4_f96_formal_evaluator_runtime_trust_deployment_receipt_v1','status':'PASS_V4_F96_FORMAL_RUNTIME_TRUST_DEPLOYED','created_at':datetime.now(timezone.utc).isoformat(),'runtime_trust_anchor_sha256':ah,'launcher_sha256':sha(LAUNCHER),'trust_builder_sha256':sha(HERE),'implementation_freeze_sha256':sha(FREEZE),'implementation_freeze_receipt_sha256':sha(FREEZE_RECEIPT),'canonical_launcher':str(LAUNCHER.resolve()),'canonical_output':str((EXP/'runs/pvrig_v4_f96_formal_evaluation_v1').resolve()),'label_access':{'v4_f96_docking_labels_read':False,'formal_evaluation_executed':False}}
 write(DEPLOYMENT,dep)
 return verify()
def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--verify-only',action='store_true');a=p.parse_args()
 try:r=verify() if a.verify_only else build()
 except Exception as e:print(json.dumps({'status':'FAIL_CLOSED','error':f'{type(e).__name__}:{e}'}));return 2
 print(json.dumps(r,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
