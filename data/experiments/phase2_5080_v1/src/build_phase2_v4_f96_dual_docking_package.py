#!/usr/bin/env python3
"""Build the label-blind V4-F96 dual-Docking Node1/Node23 waiter package."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HERE=Path(__file__).resolve(); SRC=HERE.parent; EXP=SRC.parent
PREREG=EXP/"audits/phase2_v4_f96_dual_docking_v1_preregistration.json"
NODE1=SRC/"prepare_phase2_v4_f96_docking_inputs_node1.py"
NODE23=SRC/"stage_run_phase2_v4_f96_dual_docking_node23.py"
DELIVER=SRC/"deliver_phase2_v4_f96_prediction_v3_gate.py"
NODE1_TEMPLATE=SRC/"templates/pvrig_v4_f96_docking_input_node1_waiter.sh.in"
NODE23_TEMPLATE=SRC/"templates/pvrig_v4_f96_dual_docking_node23_waiter.sh.in"
TEST=SRC/"test_build_phase2_v4_f96_dual_docking_package.py"
DEFAULT_OUT=EXP/"prepared/pvrig_v4_f96_dual_docking_v1"
DEFAULT_FREEZE=EXP/"audits/phase2_v4_f96_dual_docking_v1_implementation_freeze.json"
EXPECTED={
 "manifest":"3f3c504844756703acecf586b2b218f2e2855c3a108ee22656c8f08e7f57e334",
 "formal_prereg":"05d5727c7568ac9563c75d7ec7b916f172eefd915a728b829d29c25a12079fc3",
 "formal_evaluator":"e5594681e122e38834441f6e6aa53602a673a62615abc55a0cec20bb3650ef17",
 "formal_freeze":"2f43e8cea0bfbafb7a122a2d78c5850cb4f602598405d783b0432e8d3bbb6cf5",
 "formal_freeze_receipt":"182570215f94b399e9154cbdd1b3138594dce2a4d5baeb30a2595adbdce27a63",
 "formal_trust":"86066e7508c701d03f3c32e17df38be398455e92643c88f761ca96c109041651",
}
BOUND={
 "manifest":EXP/"data_splits/pvrig_v4_f/prospective_holdout96_manifest.tsv",
 "formal_prereg":EXP/"audits/phase2_v4_f96_formal_evaluator_v2_preregistration.json",
 "formal_evaluator":SRC/"evaluate_phase2_v4_f96_formal.py",
 "formal_freeze":EXP/"audits/phase2_v4_f96_formal_evaluator_v1_implementation_freeze.json",
 "formal_freeze_receipt":EXP/"audits/phase2_v4_f96_formal_evaluator_v1_implementation_freeze.receipt.json",
 "formal_trust":EXP/"audits/phase2_v4_f96_formal_evaluator_v1_runtime_trust_anchor.json",
}
CLAIM="Computational independent-dual-receptor Docking geometry only; not binding, affinity, competition, experimental blocking, Docking Gold, or final submission authority."
ZERO_ELIGIBILITY_SHA="c0ee3aae278836b91f77a3e33aa78823dd0dc6551b5f93e5458763f38c191aa7"
ZERO_ELIGIBILITY_PATH="/data1/qlyu/projects/pvrig_v4_f_holdout96_zero_eligible_terminal_v2_1_20260717/CANONICAL_ELIGIBILITY_RECEIPT.json"


def sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def now()->str:return datetime.now(timezone.utc).isoformat()
def atomic(path:Path,payload:Any,mode:int=0o444)->None:
 path.parent.mkdir(parents=True,exist_ok=True);fd,name=tempfile.mkstemp(prefix=f".{path.name}.",dir=path.parent)
 try:
  with os.fdopen(fd,"w") as h:json.dump(payload,h,indent=2,sort_keys=True);h.write("\n");h.flush();os.fsync(h.fileno())
  os.chmod(name,mode);os.replace(name,path)
 finally:Path(name).unlink(missing_ok=True)


def validate_inputs()->None:
 for key,path in BOUND.items():
  if not path.is_file() or path.is_symlink() or sha(path)!=EXPECTED[key]:raise RuntimeError(f"bound_hash_mismatch:{key}")
 prereg=json.loads(PREREG.read_text())
 if prereg.get("status")!="FROZEN_BEFORE_ANY_V4_F96_DOCKING_LABEL_GENERATION" or prereg.get("label_access_at_freeze")!={"formal_evaluator_executed":False,"v4_f96_docking_label_paths_accepted":0,"v4_f96_docking_labels_read":False}:raise RuntimeError("prereg_not_label_blind_frozen")
 if prereg["eligibility_policy"]["zero_eligible_branch"].find("NO_ELIGIBLE_DOCKING")<0:raise RuntimeError("zero_eligible_branch_not_frozen")


def render(template:Path,replacements:dict[str,str])->str:
 text=template.read_text()
 for old,new in replacements.items():
  if text.count(old)!=1:raise RuntimeError(f"template_placeholder_count:{old}:{text.count(old)}")
  text=text.replace(old,new)
 if "@" in "".join(part for part in text.split() if part.startswith("@")):raise RuntimeError("unresolved_placeholder")
 return text


def validate_package(out:Path)->dict[str,Any]:
 receipt=json.loads((out/"PACKAGE_RECEIPT.json").read_text());expected=set(receipt["files"])|{"PACKAGE_RECEIPT.json"};actual={str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()}
 if expected!=actual:raise RuntimeError(f"package_file_set_mismatch:{sorted(expected^actual)}")
 for rel,digest in receipt["files"].items():
  p=out/rel
  if p.is_symlink() or sha(p)!=digest:raise RuntimeError(f"package_hash_mismatch:{rel}")
 for rel in ("node1/wait_for_v4f96_fullqc_then_prepare_docking_inputs.sh","node23/wait_for_v4f96_gates_then_run_dual_docking.sh"):
  check=subprocess.run(["bash","-n",str(out/rel)],capture_output=True,text=True)
  if check.returncode:raise RuntimeError(f"shell_syntax:{rel}:{check.stderr}")
 return {"status":"PASS_V4_F96_DUAL_DOCKING_PACKAGE_HASH_CLOSED","package_receipt_sha256":sha(out/"PACKAGE_RECEIPT.json"),"implementation_freeze_sha256":sha(out/"IMPLEMENTATION_FREEZE.json"),"node1_waiter_sha256":sha(out/"node1/wait_for_v4f96_fullqc_then_prepare_docking_inputs.sh"),"node23_waiter_sha256":sha(out/"node23/wait_for_v4f96_gates_then_run_dual_docking.sh")}


def build(out:Path,freeze_path:Path)->dict[str,Any]:
 validate_inputs()
 if out.exists() and any(out.iterdir()):raise RuntimeError(f"nonempty_output:{out}")
 out.mkdir(parents=True,exist_ok=True);(out/"node1").mkdir();(out/"node23").mkdir()
 implementation={p.name:sha(p) for p in (HERE,PREREG,NODE1,NODE23,DELIVER,NODE1_TEMPLATE,NODE23_TEMPLATE,TEST)}
 freeze={"schema_version":"phase2_v4_f96_dual_docking_v1_implementation_freeze","status":"FROZEN_BEFORE_ANY_V4_F96_DOCKING_LABEL_GENERATION","frozen_at_utc":now(),"implementation_hashes":implementation,"bound_formal_hashes":EXPECTED,"current_expected_hard_pass_count":0,"zero_eligible_contract":{"canonical_receipt_path":ZERO_ELIGIBILITY_PATH,"canonical_receipt_sha256":ZERO_ELIGIBILITY_SHA,"status":"NO_ELIGIBLE_DOCKING","docking_jobs":0,"label_receipt":False,"formal_evaluator_run":False,"threshold_change":False,"trimming":False,"replacement":False},"future_nonzero_contract":{"prediction_v3_exact_gate":True,"full_qc_exact_gate":True,"all_hard_pass":True,"receptors":["8X6B","9E6Y"],"seeds":[917,1931,3253],"fixed_top8":True,"minimum_successful_seeds_per_receptor":2,"no_replacement":True},"claim_boundary":CLAIM}
 atomic(freeze_path,freeze);shutil.copyfile(freeze_path,out/"IMPLEMENTATION_FREEZE.json");freeze_sha=sha(out/"IMPLEMENTATION_FREEZE.json");prereg_sha=sha(PREREG)
 shutil.copyfile(PREREG,out/"PREREGISTRATION.json")
 shutil.copyfile(DELIVER,out/DELIVER.name);(out/DELIVER.name).chmod(0o555)
 for directory,source,name in (("node1",NODE1,NODE1.name),("node23",NODE23,NODE23.name)):
  shutil.copyfile(source,out/directory/name);(out/directory/name).chmod(0o555)
 shutil.copyfile(BOUND["manifest"],out/"node23/prospective_holdout96_manifest.tsv")
 n1=render(NODE1_TEMPLATE,{"@NODE1_RUNNER_SHA@":sha(NODE1),"@PREREG_SHA@":prereg_sha,"@FREEZE_SHA@":freeze_sha})
 n2=render(NODE23_TEMPLATE,{"@NODE23_RUNNER_SHA@":sha(NODE23),"@PREREG_SHA@":prereg_sha,"@FREEZE_SHA@":freeze_sha,"@ZERO_ELIGIBILITY_RECEIPT_SHA@":ZERO_ELIGIBILITY_SHA})
 (out/"node1/wait_for_v4f96_fullqc_then_prepare_docking_inputs.sh").write_text(n1);(out/"node1/wait_for_v4f96_fullqc_then_prepare_docking_inputs.sh").chmod(0o555)
 (out/"node23/wait_for_v4f96_gates_then_run_dual_docking.sh").write_text(n2);(out/"node23/wait_for_v4f96_gates_then_run_dual_docking.sh").chmod(0o555)
 files={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob("*")) if p.is_file()}
 atomic(out/"PACKAGE_RECEIPT.json",{"schema_version":"phase2_v4_f96_dual_docking_v1_package_receipt","status":"PASS_PACKAGE_FROZEN_LABEL_BLIND","created_at_utc":now(),"files":files,"label_paths_read":0,"scientific_work_started":False,"current_expected_terminal":"NO_ELIGIBLE_DOCKING","claim_boundary":CLAIM})
 return validate_package(out)


def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--output",type=Path,default=DEFAULT_OUT);p.add_argument("--freeze-out",type=Path,default=DEFAULT_FREEZE);p.add_argument("--verify-only",action="store_true");a=p.parse_args();result=validate_package(a.output) if a.verify_only else build(a.output,a.freeze_out);print(json.dumps(result,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
