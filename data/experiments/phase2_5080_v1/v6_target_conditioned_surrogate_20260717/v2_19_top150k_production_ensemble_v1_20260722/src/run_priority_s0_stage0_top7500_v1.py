#!/usr/bin/env python3
"""Issue a priority Top7500 from frozen S0 plus already-computed label-free priors."""
from __future__ import annotations
import argparse,csv,hashlib,json,math,os,sys
from collections import Counter
from io import StringIO
from pathlib import Path
from typing import Any,Mapping,Sequence
import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import run_v2_11_production_multimodal_inference_v1 as mm

SCHEMA="pvrig_v2_19_priority_s0_stage0_top7500_v1"
CLAIM="Priority label-free S0 sequence Docking-geometry surrogate plus generic binding/naturalness/developability priors; not calibrated binding, Kd, experimental blocking probability, or Docking truth."

class PriorityError(RuntimeError):pass
def require(x,msg):
    if not x: raise PriorityError(msg)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def ranks(ids,values):
    order=sorted(range(len(ids)),key=lambda i:(-float(values[i]),ids[i])); out=np.empty(len(ids),dtype=int)
    for rank,i in enumerate(order,1):out[i]=rank
    return out,1.0-(out-1)/max(1,len(ids)-1)
def atom(path,payload):
    require(not path.exists(),f"output_exists:{path}");tmp=path.with_name(f".{path.name}.{os.getpid()}.tmp");tmp.write_bytes(payload);os.replace(tmp,path)
def table(rows,fields):
    b=StringIO();w=csv.DictWriter(b,fieldnames=fields,delimiter="\t",lineterminator="\n");w.writeheader();w.writerows(rows);return b.getvalue().encode()

def combine(stage_rows:Sequence[Mapping[str,str]],s0:np.ndarray,top:int)->tuple[list[dict[str,Any]],list[dict[str,Any]]]:
    ids=[r["candidate_id"] for r in stage_rows]; dual=np.minimum(s0[:,0],s0[:,1]); s0_rank,s0_u=ranks(ids,dual);n=len(ids)
    out=[]
    for i,r in enumerate(stage_rows):
        stage_rank=int(r["stage0_prior_rank"]);stage_u=1-(stage_rank-1)/max(1,n-1)
        score=.55*float(s0_u[i])+.45*stage_u
        s0_top=(s0_rank[i]-1)/max(1,n-1); stage_top=(stage_rank-1)/max(1,n-1)
        clear=r["tnp_review_tier"]=="CLEAR"
        if clear and s0_top<.10 and stage_top<.10:tier="A_HIGH_AGREEMENT"
        elif clear and ((s0_top<.20 and stage_top<.20) or (s0_top<.05 and stage_top<.30)):tier="B_SUPPORTED"
        else:tier="C_PRIORITY_RESCUE"
        out.append({
          "candidate_id":r["candidate_id"],"sequence":r["sequence"],"sequence_sha256":r["sequence_sha256"],
          "parent_framework_cluster":r["parent_framework_cluster"],"cdr3":r["cdr3"],"target_patch_id":r["target_patch_id"],
          "design_method":r["design_method"],"tnp_review_tier":r["tnp_review_tier"],
          "S0_R8":f"{s0[i,0]:.12g}","S0_R9":f"{s0[i,1]:.12g}","S0_Rdual_exact_min":f"{dual[i]:.12g}",
          "S0_rank":int(s0_rank[i]),"S0_rank_utility":f"{s0_u[i]:.12g}","stage0_prior_rank":stage_rank,
          "stage0_rank_utility":f"{stage_u:.12g}","priority_fusion_score":f"{score:.12g}",
          "confidence_tier":tier,"claim_boundary":CLAIM})
    out.sort(key=lambda r:(-float(r["priority_fusion_score"]),r["candidate_id"]))
    for i,r in enumerate(out,1):r["priority_global_rank"]=i;r["priority_top5_selected"]="true" if i<=top else "false"
    return out,out[:top]

def run(a):
    require(not a.output_dir.exists(),"output_dir_exists"); require(sha(a.stage0)==a.expected_stage0_sha256,"stage0_hash")
    raw_fields,raw=mm.load_tsv(a.stage0,"stage0_priority")
    required={"candidate_id","sequence","sequence_sha256","parent_framework_cluster","cdr3","target_patch_id","design_method","tnp_review_tier","stage0_prior_rank"}
    require(required<=set(raw_fields),"stage0_columns"); require(len(raw)==a.expected_rows,"row_count")
    rows,_=mm.load_manifest(a.stage0); require([r["candidate_id"] for r in rows]==sorted(r["candidate_id"] for r in raw),"manifest_order")
    raw_by={r["candidate_id"]:r for r in raw}; stage=[raw_by[r["candidate_id"]] for r in rows]
    emb,emb_audit=mm.load_embedding_cache(a.embedding_cache,rows); artifact,artifact_audit=mm.validate_artifact(a.artifact,a.expected_artifact_sha256)
    s0=mm.predict_s0(artifact["S0"],emb,mm.physchem(rows)); full,selected=combine(stage,s0,a.top_rows)
    a.output_dir.mkdir(parents=True);fields=list(full[0]); sf=list(selected[0])
    allp=a.output_dir/"FULL150K_PRIORITY_S0_STAGE0_SCORES.tsv"; topp=a.output_dir/"TOP7500_PRIORITY_DOCKING.tsv"; fasta=a.output_dir/"TOP7500_PRIORITY_DOCKING.fasta"
    atom(allp,table(full,fields));atom(topp,table(selected,sf));atom(fasta,"".join(f">{r['candidate_id']} rank={r['priority_global_rank']} tier={r['confidence_tier']}\n{r['sequence']}\n" for r in selected).encode())
    receipt={"schema_version":SCHEMA,"status":"PASS_PRIORITY_TOP7500_READY_FOR_DOCKING","claim_boundary":CLAIM,"rows":len(full),"selected_rows":len(selected),"weights":{"S0":.55,"stage0_multi_prior":.45},"confidence_tiers":dict(Counter(r["confidence_tier"] for r in selected)),"parent_counts":dict(Counter(r["parent_framework_cluster"] for r in selected)),"embedding":emb_audit,"artifact":artifact_audit,"outputs":{p.name:sha(p) for p in (allp,topp,fasta)},"docking_truth_access_count":0,"note":"Priority release; L1/B/M2/C2 refined release continues asynchronously."}
    rp=a.output_dir/"RUN_RECEIPT.json";atom(rp,(json.dumps(receipt,indent=2,sort_keys=True)+"\n").encode()); atom(a.output_dir/"SHA256SUMS","".join(f"{sha(p)}  {p.name}\n" for p in (allp,topp,fasta,rp)).encode());return receipt
def parser():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--stage0",type=Path,required=True);p.add_argument("--expected-stage0-sha256",required=True);p.add_argument("--embedding-cache",type=Path,required=True);p.add_argument("--artifact",type=Path,required=True);p.add_argument("--expected-artifact-sha256",required=True);p.add_argument("--expected-rows",type=int,default=150000);p.add_argument("--top-rows",type=int,default=7500);p.add_argument("--output-dir",type=Path,required=True);return p
if __name__=="__main__":print(json.dumps(run(parser().parse_args()),sort_keys=True))
