#!/usr/bin/env python3
"""Validate the frozen V2.9 100k pool, 10k panel, split, provenance and 25k allocation."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import pandas as pd


AA=set("ACDEFGHIKLMNPQRSTVWY")
METHODS={"NATURAL_CDR_DONOR_REDESIGN":4000,"CONSERVATIVE_PROFILE_LOCAL_REDESIGN":2500,"RFANTIBODY_RFDIFFUSION_PROTEINMPNN":2000,"DE_NOVO_CDR_EXPLORATION":1000,"FIXED_FRAMEWORK_CDR_PERTURBATION":500}
MODES={"H3":4000,"H1H3":3500,"H1H2H3":2500}
ACQ={"EXPLOITATION_HIGH":4000,"BOUNDARY_MIDDLE":2000,"QC_PASS_LOW_RANDOM_CONTROL":1500,"MODEL_DISAGREEMENT_UNCERTAINTY":1500,"NEW_PARENT_PATCH_METHOD_EXPLORATION":1000}
REQUIRED_PROVENANCE={"candidate_id","sequence","sequence_sha256","parent_id","parent_sequence","parent_framework_cluster","design_method","design_seed","target_patch","design_mode","designed_regions","cdr1_before","cdr2_before","cdr3_before","cdr1_after","cdr2_after","cdr3_after","generator_name","generator_version","generation_batch","model_split","near_cdr3_family"}


def sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def require(value:bool,message:str)->None:
    if not value: raise RuntimeError(message)


def run(root:Path,teacher:Path)->dict[str,object]:
    pool_path=root/"prepared/exploration_pool100k_v1/exploration_pool100k.tsv"
    panel_path=root/"prepared/structure_inputs10k_v1/structure_candidates10000.tsv"
    allocation_path=root/"prepared/final_panel10k_v3/docking_allocation25000.tsv"
    split_path=root/"prepared/final_panel10k_v3/parent_split_manifest.tsv"
    pool=pd.read_csv(pool_path,sep="\t",dtype=str).fillna(""); panel=pd.read_csv(panel_path,sep="\t",dtype=str).fillna("")
    allocation=pd.read_csv(allocation_path,sep="\t",dtype=str).fillna(""); split=pd.read_csv(split_path,sep="\t",dtype=str).fillna("")
    training=pd.read_csv(teacher,sep="\t",dtype=str).fillna("")
    require(len(pool)==100000 and pool.sequence.nunique()==100000,"pool_count_or_unique")
    require(pool.sequence.map(lambda x:95<=len(x)<=160 and not(set(x)-AA)).all(),"pool_sequence_admission")
    require(len(panel)==10000 and panel.candidate_id.nunique()==10000 and panel.sequence_sha256.nunique()==10000,"panel_count_or_unique")
    require(REQUIRED_PROVENANCE<=set(panel.columns),"provenance_columns")
    require(panel.sequence.map(lambda x:hashlib.sha256(x.encode()).hexdigest()).equals(panel.sequence_sha256),"panel_sequence_hash")
    require((panel.anarci_imgt_pass.str.lower()=="true").all() and (panel.anarci_chain_type=="H").all(),"panel_anarci")
    require((pd.to_numeric(panel.max_positive_cdr_identity)<0.75).all(),"positive_cdr_formal_gate")
    require(Counter(panel.design_method)==Counter(METHODS),"method_quotas")
    require(Counter(panel.design_mode)==Counter(MODES),"mode_quotas")
    require(Counter(panel.acquisition_lane)==Counter(ACQ),"acquisition_quotas")
    require(panel.parent_framework_cluster.nunique()==65 and Counter(panel.groupby("parent_framework_cluster").size())==Counter({154:55,153:10}),"parent_capacity")
    require((panel.parent_is_existing_open3388.str.lower()=="false").mean()>=0.5,"new_parent_fraction")
    require(len(split)==65 and Counter(split.model_split)==Counter({"train":45,"development":10,"frozen_test":10}),"split_counts")
    require(panel.groupby("parent_framework_cluster").model_split.nunique().max()==1,"parent_split_leakage")
    require(set(panel.parent_framework_cluster)==set(split.parent_framework_cluster),"split_parent_closure")
    require(len(allocation)==25000 and allocation.job_id.nunique()==25000,"allocation_count_or_unique")
    require(Counter(allocation.seed)==Counter({"917":20000,"1931":4000,"3253":1000}),"allocation_seed_counts")
    require(Counter(allocation.receptor)==Counter({"8x6b":12500,"9e6y":12500}),"allocation_receptor_counts")
    require(set(allocation.candidate_id)==set(panel.candidate_id),"allocation_candidate_closure")
    by=allocation.groupby(["candidate_id","seed"]).receptor.agg(lambda x:set(x))
    require(all(value=={"8x6b","9e6y"} for value in by),"allocation_dual_receptor_pairs")
    seed_sets=allocation.assign(seed_int=allocation.seed.astype(int)).groupby("candidate_id").seed_int.agg(set)
    require(all(917 in values for values in seed_sets),"seed917_all_candidates")
    require(not(set(panel.sequence)&set(training.sequence)),"open3388_sequence_overlap")
    report={
        "schema_version":"pvrig_v29_release_acceptance_v1","status":"PASS_V29_SEQUENCE_PANEL_ALLOCATION_ACCEPTANCE",
        "pool_rows":len(pool),"panel_rows":len(panel),"parent_count":65,"near_cdr3_family_count":int(panel.near_cdr3_family.nunique()),
        "new_parent_fraction":float((panel.parent_is_existing_open3388.str.lower()=="false").mean()),"allocation_rows":len(allocation),
        "split_parent_counts":dict(Counter(split.model_split)),"input_hashes":{"pool":sha(pool_path),"panel":sha(panel_path),"allocation":sha(allocation_path),"split":sha(split_path),"teacher":sha(teacher)},
        "scientific_boundary":"Sequence/panel/allocation acceptance only; not proof of binding, affinity, blocking, expression or purity.",
    }
    (root/"ACCEPTANCE_REPORT.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--root",type=Path,required=True);p.add_argument("--teacher",type=Path,required=True);a=p.parse_args()
    print(json.dumps(run(a.root,a.teacher),indent=2,sort_keys=True))
