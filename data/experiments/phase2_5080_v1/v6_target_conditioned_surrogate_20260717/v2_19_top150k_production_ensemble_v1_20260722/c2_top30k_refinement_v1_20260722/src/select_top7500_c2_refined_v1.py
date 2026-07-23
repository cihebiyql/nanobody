#!/usr/bin/env python3
"""Issue the frozen C2-refined Top7500 without reading labels or Docking truth."""
from __future__ import annotations
import argparse,csv,hashlib,io,json,os,statistics
from collections import Counter,defaultdict
from pathlib import Path

SCHEMA="pvrig_v2_19_c2_refined_top7500_v1"; STATUS="PASS_C2_REFINED_TOP7500_DOCKING_READY"
CLAIM="C2-refined consensus of label-free computational Docking-geometry surrogates; not calibrated binding or experimental blocking probability."
ALL="S0_M2_C2_CONVEX__Rdual_rank_percentile"; M2C2="M2_C2_CONVEX__Rdual_rank_percentile"
class SelectionError(RuntimeError):pass
def req(x,m):
    if not x:raise SelectionError(m)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):
    req(Path(p).is_file() and not Path(p).is_symlink(),"input_not_regular")
    with Path(p).open(newline="",encoding="utf-8-sig") as f:r=csv.DictReader(f,delimiter="\t");fields=list(r.fieldnames or []);rows=list(r)
    req(rows and not any(x in f.lower() for f in fields for x in ("truth","teacher","experimental","docking_gold")),"forbidden_or_empty");return fields,rows
def idx(rows):
    d={}
    for r in rows:req(r["candidate_id"] not in d,"duplicate");d[r["candidate_id"]]=r
    return d
def atom(p,b):
    req(not p.exists(),"output_exists");t=p.with_name(f".{p.name}.{os.getpid()}.tmp");t.write_bytes(b);os.replace(t,p)
def tsv(rows,fields=None):
    fields=list(fields or rows[0]);s=io.StringIO(newline="");w=csv.DictWriter(s,fieldnames=fields,delimiter="\t",lineterminator="\n");w.writeheader();w.writerows(rows);return s.getvalue().encode()
def diverse(pool,n):
    groups=defaultdict(list)
    for r in pool:groups[r["parent_framework_cluster"]].append(r)
    out=[]
    while len(out)<n:
        moved=False
        for key in sorted(groups,key=lambda k:(len([r for r in out if r["parent_framework_cluster"]==k]),k)):
            if groups[key]:out.append(groups[key].pop(0));moved=True
            if len(out)==n:break
        req(moved,"diversity_exhausted")
    return out
def run(a):
    req(not a.output_dir.exists(),"output_dir_exists");_,base_rows=read(a.stage1);_,c2rows=read(a.c2);req(len(base_rows)==len(c2rows)==a.stage1_rows,"rows")
    c2=idx(c2rows);records=[]
    for row in base_rows:
        c=row["candidate_id"];req(c in c2 and row["sequence_sha256"]==c2[c]["sequence_sha256"],f"closure:{c}")
        b=float(row["four_model_ensemble_utility"]);allv=float(c2[c][ALL]);m2c2=float(c2[c][M2C2]);score=.80*b+.15*allv+.05*m2c2
        values=[float(row[x]) for x in ("l1_utility","b_utility","s0_utility","m2_utility")]+[allv,m2c2]
        result=dict(row);result.update({"c2_s0_m2_convex_utility":f"{allv:.12g}","c2_m2_convex_utility":f"{m2c2:.12g}","c2_refined_utility":f"{score:.12g}","six_lane_rank_spread":f"{statistics.pstdev(values):.12g}","six_lane_top5_support_count":sum(v>=.95 for v in values),"claim_boundary":CLAIM});records.append(result)
    records.sort(key=lambda r:(-float(r["c2_refined_utility"]),r["candidate_id"]));used=set();chosen=[]
    for r in records[:a.exploitation]:r["selection_channel"]="C2_REFINED_CONSENSUS";chosen.append(r);used.add(r["candidate_id"])
    rescue=sorted((r for r in records if r["candidate_id"] not in used),key=lambda r:(-(.7*max(float(r["l1_utility"]),float(r["b_utility"]))+.3*float(r["c2_s0_m2_convex_utility"])),r["candidate_id"]))
    for r in rescue[:a.rescue]:r["selection_channel"]="TARGET_MODEL_C2_SUPPORTED_RESCUE";chosen.append(r);used.add(r["candidate_id"])
    pool=[r for r in records if r["candidate_id"] not in used]
    for r in diverse(pool,a.diversity):r["selection_channel"]="PARENT_BALANCED_C2_DIVERSITY";chosen.append(r);used.add(r["candidate_id"])
    req(len(chosen)==a.final_rows and len(used)==a.final_rows,"quota");chosen.sort(key=lambda r:(-float(r["c2_refined_utility"]),r["candidate_id"]))
    for i,r in enumerate(chosen,1):r["final_c2_refined_rank"]=i;r["high_confidence_core_flag"]="true" if int(r["six_lane_top5_support_count"])>=3 and float(r["six_lane_rank_spread"])<=.18 and r["tnp_review_tier"]!="HIGH_RISK_REVIEW" else "false"
    a.output_dir.mkdir(parents=True);table=a.output_dir/"TOP7500_C2_REFINED.tsv";fasta=a.output_dir/"TOP7500_C2_REFINED.fasta";core=a.output_dir/"TOP7500_C2_REFINED_HIGH_CONFIDENCE_CORE.tsv"
    core_rows=[r for r in chosen if r["high_confidence_core_flag"]=="true"]
    atom(table,tsv(chosen));atom(core,tsv(core_rows,list(chosen[0])))
    atom(fasta,"".join(f">{r['candidate_id']} rank={r['final_c2_refined_rank']} channel={r['selection_channel']}\n{r['sequence']}\n" for r in chosen).encode())
    receipt={"schema_version":SCHEMA,"status":STATUS,"claim_boundary":CLAIM,"rows":len(chosen),"weights":{"four_model":.80,"S0_M2_C2":.15,"M2_C2":.05},"channels":dict(Counter(r["selection_channel"] for r in chosen)),"parents":dict(Counter(r["parent_framework_cluster"] for r in chosen)),"high_confidence_core_rows":sum(r["high_confidence_core_flag"]=="true" for r in chosen),"inputs":{"stage1_sha256":sha(a.stage1),"c2_sha256":sha(a.c2)},"outputs":{p.name:sha(p) for p in (table,fasta,core)},"invariants":{"candidate_set_subset_of_frozen_top30000":True,"sequence_sha256_join_exact":True,"final_quota_exact":True,"teacher_label_values_read":0,"candidate_docking_pose_files_opened":0}}
    rp=a.output_dir/"RUN_RECEIPT.json";atom(rp,(json.dumps(receipt,indent=2,sort_keys=True)+"\n").encode());atom(a.output_dir/"SHA256SUMS","".join(f"{sha(p)}  {p.name}\n" for p in (table,fasta,core,rp)).encode());return receipt
def parser():
 p=argparse.ArgumentParser();p.add_argument("--stage1",type=Path,required=True);p.add_argument("--c2",type=Path,required=True);p.add_argument("--output-dir",type=Path,required=True);p.add_argument("--stage1-rows",type=int,default=30000);p.add_argument("--final-rows",type=int,default=7500);p.add_argument("--exploitation",type=int,default=6750);p.add_argument("--rescue",type=int,default=500);p.add_argument("--diversity",type=int,default=250);return p
if __name__=="__main__":print(json.dumps(run(parser().parse_args()),sort_keys=True))
