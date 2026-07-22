#!/usr/bin/env python3
"""Whole-parent OOF raw-feature reranking inside a multimodal hard-negative pool."""

from __future__ import annotations

import argparse,csv,hashlib,importlib.util,json,math,os,pickle,shutil,sys,tempfile
from pathlib import Path
from typing import Any,Mapping,Sequence
import numpy as np


HERE=Path(__file__).resolve().parent
V215_PATH=HERE.parents[1]/"v2_15_raw_multimodal_top5_v1_20260722"/"src"/"run_v215_raw_multimodal_top5_oof_v1.py"
SPEC=importlib.util.spec_from_file_location("v215_core_for_v216",V215_PATH)
if SPEC is None or SPEC.loader is None:raise RuntimeError("v215_import")
V215=importlib.util.module_from_spec(SPEC);sys.modules[SPEC.name]=V215;SPEC.loader.exec_module(V215)

SCHEMA="pvrig_v2_16_raw_hard_negative_top5_oof_v1"
CONTRACT_SCHEMA="pvrig_v2_16_raw_hard_negative_top5_contract_v1"
METHODS=("R0_L1","R1_HGB_U20_RAW","R2_EXTRA_U20_RAW","R3_HGB_U30_RAW","R4_EXTRA_U30_RAW","R5_U20_MEAN","R6_U20_L1_BLEND","R7_U30_MEAN")


class V216Error(RuntimeError):pass
def require(c:bool,m:str)->None:
    if not c:raise V216Error(m)


def component_dual(data:Mapping[str,Any],idx:np.ndarray)->np.ndarray:
    return np.column_stack((data["base"][idx,2],data["base"][idx,5],data["base"][idx,8],data["l1"][idx,2]))


def pool_mask(data:Mapping[str,Any],train:np.ndarray,idx:np.ndarray,fraction:float)->np.ndarray:
    train_values=component_dual(data,train);values=component_dual(data,idx)
    ranks=np.column_stack([V215.percentile_from_train(train_values[:,j],values[:,j]) for j in range(4)])
    mask=np.any(ranks>=1.0-fraction,axis=1)
    minimum=math.ceil(.05*len(idx))
    if int(mask.sum())<minimum:
        supplement=np.argsort(-np.max(ranks,axis=1),kind="stable")[:minimum]
        mask[supplement]=True
    require(int(mask.sum())>=minimum,f"pool_budget:{fraction}")
    return mask


def fit_classifier(kind:str,data:Mapping[str,Any],train:np.ndarray,fraction:float,contract:Mapping[str,Any])->tuple[Any,int]:
    mask=pool_mask(data,train,train,fraction);pool=train[mask]
    x=V215.augmented_features(data,train,pool);truth=np.min(data["truth"][train],axis=1)
    threshold=np.sort(truth)[-max(1,math.ceil(.1*len(train)))]
    labels=(np.min(data["truth"][pool],axis=1)>=threshold).astype(np.int64)
    weights=V215.balanced_weights(data["weights"][pool],labels)
    model=V215.make_hgb_classifier(contract["hgb_classifier"]) if kind=="hgb" else V215.make_extra_trees(contract["extra_trees"])
    model.fit(x,labels,sample_weight=weights);return model,len(pool)


def predict_classifier(model:Any,data:Mapping[str,Any],train:np.ndarray,test:np.ndarray,fraction:float)->tuple[np.ndarray,int]:
    mask=pool_mask(data,train,test,fraction);pool=test[mask]
    score=np.full(len(test),-1.0,dtype=np.float64)
    score[mask]=model.predict_proba(V215.augmented_features(data,train,pool))[:,1]
    if np.any(~mask):
        tail=np.mean(np.column_stack([V215.percentile_from_train(component_dual(data,train)[:,j],component_dual(data,test)[:,j]) for j in range(4)]),axis=1)
        score[~mask]=-1.0+1e-3*tail[~mask]
    return score,len(pool)


def run_oof(data:Mapping[str,Any],contract:Mapping[str,Any])->tuple[dict[str,np.ndarray],dict[str,Any],dict[str,Any]]:
    n=len(data["candidate_ids"]);scores={name:np.full(n,np.nan) for name in METHODS};models={};audit={}
    for fold in range(int(contract["data"]["expected_folds"])):
        train=np.flatnonzero(data["folds"]!=fold);test=np.flatnonzero(data["folds"]==fold)
        require(not(set(data["parents"][train])&set(data["parents"][test])),f"parent_overlap:{fold}")
        scores["R0_L1"][test]=data["l1"][test,2]
        fold_models={};fold_audit={};observed={}
        for fraction,label in ((.2,"U20"),(.3,"U30")):
            for kind in ("hgb","extra"):
                model,train_pool=fit_classifier(kind,data,train,fraction,contract)
                prediction,test_pool=predict_classifier(model,data,train,test,fraction)
                key=f"{label}_{kind}";observed[key]=prediction;fold_models[key]=model;fold_audit[key]={"train_pool":train_pool,"test_pool":test_pool}
        scores["R1_HGB_U20_RAW"][test]=observed["U20_hgb"]
        scores["R2_EXTRA_U20_RAW"][test]=observed["U20_extra"]
        scores["R3_HGB_U30_RAW"][test]=observed["U30_hgb"]
        scores["R4_EXTRA_U30_RAW"][test]=observed["U30_extra"]
        u20=.5*V215.percentile_rank(observed["U20_hgb"])+.5*V215.percentile_rank(observed["U20_extra"])
        u30=.5*V215.percentile_rank(observed["U30_hgb"])+.5*V215.percentile_rank(observed["U30_extra"])
        scores["R5_U20_MEAN"][test]=u20
        scores["R6_U20_L1_BLEND"][test]=.8*u20+.2*V215.percentile_rank(data["l1"][test,2])
        scores["R7_U30_MEAN"][test]=u30
        models[str(fold)]=fold_models;audit[str(fold)]=fold_audit
    require(all(np.isfinite(v).all() for v in scores.values()),"nonfinite_oof")
    return scores,models,audit


def write_tsv(path:Path,rows:Sequence[Mapping[str,Any]])->None:
    with path.open("w",newline="",encoding="utf-8") as h:
        w=csv.DictWriter(h,fieldnames=list(rows[0]),delimiter="\t",lineterminator="\n");w.writeheader();w.writerows(rows)


def run(contract_path:Path,raw_path:Path,assignment_path:Path,legacy_path:Path,l1_path:Path,output_dir:Path)->dict[str,Any]:
    require(not output_dir.exists(),"output_exists");contract=json.loads(contract_path.read_text())
    require(contract.get("schema_version")==CONTRACT_SCHEMA and contract.get("status")=="FROZEN_BEFORE_V2_16_OOF_EXECUTION","contract")
    for path,key in ((raw_path,"raw_multimodal_sha256"),(assignment_path,"assignment_sha256"),(legacy_path,"legacy_oof_sha256"),(l1_path,"l1_oof_sha256")):
        require(V215.sha256_file(path)==contract["input_bindings"][key],f"input_hash:{key}")
    data=V215.load_inputs(raw_path,assignment_path,legacy_path,l1_path,contract)
    require(data["raw_rows_scanned"]-len(data["candidate_ids"])==int(contract["data"]["open_rows_excluded_before_value_parsing"]),"firewall")
    scores,models,audit=run_oof(data,contract);truth=np.min(data["truth"],axis=1)
    observed={name:V215.metrics(data["candidate_ids"],data["folds"],truth,score) for name,score in scores.items()}
    selected=max(METHODS,key=lambda n:(observed[n]["pooled_ef5"],observed[n]["binary_ndcg_true_top10_at_budget5"],observed[n]["median_fold_ef5"],observed[n]["worst_fold_ef5"],observed[n]["pooled_ef10"],observed[n]["spearman"],-METHODS.index(n)))
    output_dir.parent.mkdir(parents=True,exist_ok=True);staging=Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.",dir=output_dir.parent))
    try:
        rows=[]
        for i,c in enumerate(data["candidate_ids"]):
            row={"candidate_id":c,"parent_framework_cluster":data["parents"][i],"fold_id":int(data["folds"][i]),"truth_Rdual_exact_min":truth[i]}
            for name in METHODS:row[f"{name}__frontscreen_score"]=scores[name][i]
            rows.append(row)
        pred=staging/"V2_16_RAW_HARD_NEGATIVE_TOP5_OOF_PREDICTIONS.tsv";write_tsv(pred,rows)
        report={"schema_version":SCHEMA,"status":"PASS_V2_16_RAW_HARD_NEGATIVE_TOP5_OOF","claim_boundary":V215.CLAIM,"counts":{"rows":len(rows),"parents":len(set(data["parents"])),"folds":5,"raw_numeric_features":len(data["raw_feature_names"])},"methods":observed,"selected_method":selected,"target_ef5":5.0,"target_achieved_in_this_oof":observed[selected]["pooled_ef5"]>=5.0,"pool_audit":audit,"input_access":contract["input_access"]}
        metric=staging/"V2_16_RAW_HARD_NEGATIVE_TOP5_METRICS.json";metric.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
        with (staging/"V2_16_FOLD_MODELS.pkl").open("wb") as h:pickle.dump({"models":models,"raw_feature_names":data["raw_feature_names"]},h,pickle.HIGHEST_PROTOCOL)
        receipt={"schema_version":SCHEMA,"status":report["status"],"selected_method":selected,"target_achieved_in_this_oof":report["target_achieved_in_this_oof"],"input_access":report["input_access"],"outputs":{}}
        for name in (pred.name,metric.name,"V2_16_FOLD_MODELS.pkl"):receipt["outputs"][name]=V215.sha256_file(staging/name)
        (staging/"RUN_RECEIPT.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
        os.replace(staging,output_dir);return report
    finally:
        if staging.exists():shutil.rmtree(staging)


def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--contract",type=Path,required=True);p.add_argument("--raw-multimodal",type=Path,required=True);p.add_argument("--assignment",type=Path,required=True);p.add_argument("--legacy-oof",type=Path,required=True);p.add_argument("--l1-oof",type=Path,required=True);p.add_argument("--output-dir",type=Path,required=True)
    a=p.parse_args();r=run(a.contract,a.raw_multimodal,a.assignment,a.legacy_oof,a.l1_oof,a.output_dir);print(json.dumps({"status":r["status"],"selected_method":r["selected_method"],"ef5":r["methods"][r["selected_method"]]["pooled_ef5"],"target_achieved":r["target_achieved_in_this_oof"]},sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
