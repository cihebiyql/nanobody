#!/usr/bin/env python3
"""Reuse the frozen V2.19/V2.11 multimodal functions for Top30K C2 inference."""

from __future__ import annotations

import argparse, csv, hashlib, importlib.util, io, json, os
from pathlib import Path
from typing import Any
import numpy as np

SCHEMA="pvrig_v2_19_top30k_v2_11_c2_adapter_v1"
STATUS="PASS_TOP30K_V2_11_C2_MULTIMODAL_INFERENCE"
CLAIM="Label-free monomer/fixed-target C2 and frozen multimodal surrogate predictions only; not Docking truth, binding, or experimental blocking probability."
S0="S0_MATCHED_ESM2_650M_PCA_ELASTICNET"
M2="M2_STRUCTURE_ALPHA10"
FORBIDDEN=("truth","teacher","docking_gold","experimental")

class AdapterError(RuntimeError): pass
def require(ok,msg):
    if not ok: raise AdapterError(msg)
def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()
def read(path,role):
    require(Path(path).is_file() and not Path(path).is_symlink(),f"{role}_not_regular")
    with Path(path).open(newline="",encoding="utf-8-sig") as f:
        r=csv.DictReader(f,delimiter="\t"); fields=list(r.fieldnames or []); rows=list(r)
    require(fields and rows and len(fields)==len(set(fields)),f"{role}_invalid")
    require(not any(token in field.lower() for field in fields for token in FORBIDDEN),f"{role}_forbidden_field")
    return fields,rows
def index(rows,role):
    out={}
    for row in rows:
        candidate=row.get("candidate_id",""); require(candidate and candidate not in out,f"{role}_duplicate:{candidate}"); out[candidate]=row
    return out
def atomic(path,payload):
    require(not path.exists() and not path.is_symlink(),f"output_exists:{path}"); path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temp.open("xb") as f:f.write(payload);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)
def tsv(rows):
    s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=list(rows[0]),delimiter="\t",lineterminator="\n");w.writeheader();w.writerows(rows);return s.getvalue().encode()
def receipt_output(receipt_path,status,name,path):
    payload=json.loads(Path(receipt_path).read_text()); require(payload.get("status")==status,f"receipt_status:{status}")
    expected=payload.get("outputs",{}).get(name) if "outputs" in payload else payload.get("output",{}).get("sha256")
    require(expected==sha(path),f"receipt_output_hash:{name}")

def run(args):
    require(not args.output_dir.exists() and not args.output_dir.is_symlink(),"output_exists")
    require(sha(args.vendor_adapter)==args.vendor_adapter_sha256,"vendor_adapter_hash")
    spec=importlib.util.spec_from_file_location("frozen_v2_11_adapter",args.vendor_adapter); require(spec and spec.loader,"vendor_spec")
    vendor=importlib.util.module_from_spec(spec); spec.loader.exec_module(vendor)
    artifact,artifact_audit=vendor.validate_artifact(args.model_artifact,args.model_artifact_sha256)
    require(sha(args.c2_features)==args.c2_features_sha256,"c2_hash")
    _,stage_rows=read(args.stage1,"stage1"); require(len(stage_rows)==args.expected_rows,"stage1_rows")
    stage=index(stage_rows,"stage1"); ordered=[row["candidate_id"] for row in stage_rows]
    _,base_rows=read(args.base_predictions,"base"); base=index(base_rows,"base")
    require(set(ordered)<=set(base),"base_candidate_closure")
    manifest=[{"candidate_id":c,"sequence_sha256":stage[c]["sequence_sha256"],"parent_framework_cluster":stage[c]["parent_framework_cluster"]} for c in ordered]
    c2,c2audit=vendor.load_feature_matrix(args.c2_features,"c2_features",artifact["c2_feature_names"],manifest)
    bases={
      "S0":np.asarray([[float(base[c][f"{S0}__R8"]),float(base[c][f"{S0}__R9"])] for c in ordered]),
      "M2":np.asarray([[float(base[c][f"{M2}__R8"]),float(base[c][f"{M2}__R9"])] for c in ordered]),
    }
    for c in ordered:
        require(base[c]["sequence_sha256"]==stage[c]["sequence_sha256"],f"base_sequence_hash:{c}")
        require(base[c]["parent_framework_cluster"]==stage[c]["parent_framework_cluster"],f"base_parent:{c}")
    bases["C2"]=vendor.predict_c2(artifact["C2"],c2)
    predictions={
      vendor.C2_LANES[0]:bases["C2"],
      vendor.C2_LANES[1]:vendor.predict_convex(artifact["fusion_m2c2"],{"M2":bases["M2"],"C2":bases["C2"]}),
      vendor.C2_LANES[2]:vendor.predict_convex(artifact["fusion_all"],bases),
      vendor.C2_LANES[3]:vendor.predict_gbdt(artifact["gbdt"],vendor.meta_features(bases)),
    }
    ranks={lane:vendor.competition_ranks(ordered,vendor.exact_min(pred)) for lane,pred in predictions.items()}
    output=[]
    for i,c in enumerate(ordered):
        row={"candidate_id":c,"sequence_sha256":stage[c]["sequence_sha256"],"parent_framework_cluster":stage[c]["parent_framework_cluster"],"claim_boundary":CLAIM}
        for lane,pred in predictions.items():
            rank,pct=ranks[lane]; row.update({f"{lane}__R8":f"{pred[i,0]:.12g}",f"{lane}__R9":f"{pred[i,1]:.12g}",f"{lane}__Rdual_exact_min":f"{min(pred[i]):.12g}",f"{lane}__Rdual_rank":int(rank[i]),f"{lane}__Rdual_rank_percentile":f"{pct[i]:.12g}"})
        output.append(row)
    args.output_dir.mkdir(parents=True); table=args.output_dir/"TOP30000_C2_MULTIMODAL_PREDICTIONS.tsv"; atomic(table,tsv(output))
    receipt={"schema_version":SCHEMA,"status":STATUS,"claim_boundary":CLAIM,"counts":{"rows":len(output),"lanes":len(predictions),"c2_features":32},"lanes":list(predictions),"inputs":{"vendor_adapter":{"path":str(args.vendor_adapter.resolve()),"sha256":args.vendor_adapter_sha256},"artifact":artifact_audit,"c2_features":c2audit,"stage1_sha256":sha(args.stage1),"base_predictions_sha256":sha(args.base_predictions)},"output":{"path":str(table.resolve()),"sha256":sha(table)},"invariants":{"candidate_set_exact":True,"sequence_sha256_join_exact":True,"parent_join_exact":True,"exact_min_derived":True,"teacher_label_values_read":0,"candidate_docking_pose_files_opened":0}}
    rp=args.output_dir/"RUN_RECEIPT.json";atomic(rp,(json.dumps(receipt,indent=2,sort_keys=True)+"\n").encode());atomic(args.output_dir/"SHA256SUMS",f"{sha(table)}  {table.name}\n{sha(rp)}  {rp.name}\n".encode())
    return {"status":STATUS,"rows":len(output),"output_sha256":sha(table)}
def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage1",type=Path,required=True);p.add_argument("--base-predictions",type=Path,required=True)
    p.add_argument("--c2-features",type=Path,required=True);p.add_argument("--c2-features-sha256",required=True)
    p.add_argument("--vendor-adapter",type=Path,required=True);p.add_argument("--vendor-adapter-sha256",required=True)
    p.add_argument("--model-artifact",type=Path,required=True);p.add_argument("--model-artifact-sha256",required=True)
    p.add_argument("--output-dir",type=Path,required=True);p.add_argument("--expected-rows",type=int,default=30000);return p
if __name__=="__main__":print(json.dumps(run(parser().parse_args()),sort_keys=True))
