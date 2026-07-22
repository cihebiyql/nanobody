#!/usr/bin/env python3
"""Whole-parent OOF hard-negative reranking inside a label-free multimodal union."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import pickle
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("v213_nested_stack_core_for_hard_negative", HERE / "run_nested_multimodal_top5_stack_v1.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("core_import")
CORE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)

SCHEMA = "pvrig_v2_13_hard_negative_top5_reranker_v1"
CONTRACT_SCHEMA = "pvrig_v2_13_hard_negative_top5_contract_v1"
METHODS = (
    "H0_EQUAL_RANK4",
    "H1_HGB_UNION10",
    "H2_HGB_UNION20",
    "H3_HGB_UNION30",
    "H4_EXTRA_TREES_UNION20",
    "H5_LOGISTIC_UNION20",
    "H6_HGB20_RANK_BLEND",
)
CLAIM = CORE.CLAIM


class RerankerError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RerankerError(message)


def sha256_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"regular_file_required:{path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pool_mask(data: CORE.Dataset, indices: np.ndarray, fraction: float) -> np.ndarray:
    ranks = np.column_stack([CORE.percentile_rank(CORE.exact_min(data.bases[name][indices])) for name in CORE.BASES])
    mask = np.any(ranks >= 1.0-fraction, axis=1)
    require(int(mask.sum()) >= math.ceil(0.05*len(indices)), "pool_below_top5_budget")
    return mask


def expanded_raw(data: CORE.Dataset, indices: np.ndarray, sorted_dual: Sequence[np.ndarray]) -> np.ndarray:
    core = CORE.raw_meta_features(data, indices, sorted_dual)
    ranks = core[:, 8:12]
    products = []
    differences = []
    for left in range(4):
        for right in range(left+1,4):
            products.append(ranks[:,left]*ranks[:,right])
            differences.append(np.abs(ranks[:,left]-ranks[:,right]))
    votes = np.column_stack([(ranks >= threshold).sum(1) for threshold in (0.70,0.80,0.90)])
    ordered = np.sort(ranks,axis=1)
    tail = np.column_stack([ordered[:,:2].mean(1),ordered[:,-2:].mean(1)])
    result = np.column_stack([core,np.column_stack(products),np.column_stack(differences),votes,tail])
    require(result.shape[1] == 36 and np.isfinite(result).all(), "expanded_feature_shape")
    return result


@dataclass
class ExpandedTransform:
    sorted_dual: list[np.ndarray]
    scaler: StandardScaler


def fit_expanded_transform(data: CORE.Dataset, train: np.ndarray) -> ExpandedTransform:
    sorted_dual = [np.sort(CORE.exact_min(data.bases[name][train])) for name in CORE.BASES]
    scaler = StandardScaler().fit(expanded_raw(data,train,sorted_dual))
    return ExpandedTransform(sorted_dual,scaler)


def transform(data: CORE.Dataset, indices: np.ndarray, fitted: ExpandedTransform) -> np.ndarray:
    return fitted.scaler.transform(expanded_raw(data,indices,fitted.sorted_dual))


def labels_for_pool(data: CORE.Dataset, all_train: np.ndarray, pool_train: np.ndarray) -> np.ndarray:
    truth = CORE.exact_min(data.truth[all_train])
    threshold = np.sort(truth)[-max(1,math.ceil(0.10*len(truth)))]
    return (CORE.exact_min(data.truth[pool_train]) >= threshold).astype(np.int64)


def weights_for_pool(data: CORE.Dataset, pool_train: np.ndarray, labels: np.ndarray) -> np.ndarray:
    weights = CORE.parent_weights(data.parents,pool_train)
    positive = int(labels.sum())
    require(0 < positive < len(labels), "pool_class_balance")
    weights[labels==1] *= len(labels)/(2*positive)
    weights[labels==0] *= len(labels)/(2*(len(labels)-positive))
    return weights


def fit_model(kind: str, data: CORE.Dataset, all_train: np.ndarray, fraction: float, config: Mapping[str,Any]) -> tuple[ExpandedTransform,Any,int]:
    mask = pool_mask(data,all_train,fraction)
    pool_train = all_train[mask]
    fitted = fit_expanded_transform(data,pool_train)
    labels = labels_for_pool(data,all_train,pool_train)
    weights = weights_for_pool(data,pool_train,labels)
    if kind == "hgb":
        model = HistGradientBoostingClassifier(
            max_depth=int(config["max_depth"]),max_iter=int(config["max_iter"]),learning_rate=float(config["learning_rate"]),
            min_samples_leaf=int(config["min_samples_leaf"]),l2_regularization=float(config["l2_regularization"]),
            early_stopping=False,random_state=43,
        )
    elif kind == "extra_trees":
        model = ExtraTreesClassifier(
            n_estimators=int(config["n_estimators"]),max_depth=int(config["max_depth"]),
            min_samples_leaf=int(config["min_samples_leaf"]),max_features=float(config["max_features"]),
            bootstrap=False,n_jobs=int(config["n_jobs"]),random_state=43,
        )
    elif kind == "logistic":
        model = LogisticRegression(C=float(config["C"]),penalty="l2",solver="lbfgs",max_iter=3000,random_state=43)
    else:
        raise RerankerError(f"model_kind:{kind}")
    model.fit(transform(data,pool_train,fitted),labels,sample_weight=weights)
    return fitted,model,len(pool_train)


def predict_pool(model: Any, fitted: ExpandedTransform, data: CORE.Dataset, test: np.ndarray, fraction: float) -> tuple[np.ndarray,int]:
    mask = pool_mask(data,test,fraction)
    pool_test = test[mask]
    score = np.full(len(test),-1.0,dtype=np.float64)
    score[mask] = model.predict_proba(transform(data,pool_test,fitted))[:,1]
    # The top-5 budget is fully inside the union; this deterministic tail is label free.
    if np.any(~mask):
        tail = CORE.rank_score(data.bases,test,np.full(4,0.25))
        score[~mask] = -1.0 + 1e-3*tail[~mask]
    return score,len(pool_test)


def oof(data: CORE.Dataset, contract: Mapping[str,Any]) -> tuple[dict[str,np.ndarray],dict[str,Any],dict[str,Any]]:
    scores={method:np.full(len(data.candidate_ids),np.nan) for method in METHODS}
    audit={}; models={}
    for fold in range(5):
        train=np.flatnonzero(data.folds!=fold); test=np.flatnonzero(data.folds==fold)
        equal=CORE.rank_score(data.bases,test,np.full(4,0.25)); scores["H0_EQUAL_RANK4"][test]=equal
        fold_models={}; fold_audit={}
        hgb20_score=None
        for method,fraction in (("H1_HGB_UNION10",0.10),("H2_HGB_UNION20",0.20),("H3_HGB_UNION30",0.30)):
            fitted,model,train_pool=fit_model("hgb",data,train,fraction,contract["hgb"])
            score,test_pool=predict_pool(model,fitted,data,test,fraction); scores[method][test]=score
            fold_models[method]=(fitted,model); fold_audit[method]={"train_pool":train_pool,"test_pool":test_pool,"fraction":fraction}
            if method=="H2_HGB_UNION20": hgb20_score=score
        fitted,model,train_pool=fit_model("extra_trees",data,train,0.20,contract["extra_trees"])
        score,test_pool=predict_pool(model,fitted,data,test,0.20); scores["H4_EXTRA_TREES_UNION20"][test]=score
        fold_models["H4_EXTRA_TREES_UNION20"]=(fitted,model); fold_audit["H4_EXTRA_TREES_UNION20"]={"train_pool":train_pool,"test_pool":test_pool,"fraction":0.20}
        fitted,model,train_pool=fit_model("logistic",data,train,0.20,contract["logistic"])
        score,test_pool=predict_pool(model,fitted,data,test,0.20); scores["H5_LOGISTIC_UNION20"][test]=score
        fold_models["H5_LOGISTIC_UNION20"]=(fitted,model); fold_audit["H5_LOGISTIC_UNION20"]={"train_pool":train_pool,"test_pool":test_pool,"fraction":0.20}
        require(hgb20_score is not None,"hgb20_missing")
        scores["H6_HGB20_RANK_BLEND"][test]=0.70*CORE.percentile_rank(hgb20_score)+0.30*equal
        models[str(fold)]=fold_models; audit[str(fold)]=fold_audit
    require(all(np.isfinite(score).all() for score in scores.values()),"nonfinite_oof")
    return scores,audit,models


def select(observed: Mapping[str,Mapping[str,Any]], contract: Mapping[str,Any]) -> tuple[str,dict[str,Any]]:
    baseline=observed["H0_EQUAL_RANK4"]; eligible=[]; audit={}; complexity={name:i for i,name in enumerate(METHODS)}
    gate=contract["promotion_gate"]
    for method in METHODS[1:]:
        value=observed[method]; delta=np.asarray(value["fold_ef5"])-np.asarray(baseline["fold_ef5"])
        checks={
            "ef5_increment":value["pooled_ef5"]>=baseline["pooled_ef5"]+float(gate["minimum_ef5_increment"]),
            "ef10":value["pooled_ef10"]>=baseline["pooled_ef10"]-float(gate["maximum_ef10_decrement"]),
            "fold_count":int(np.sum(delta>=-0.5))>=int(gate["minimum_folds_with_delta_at_least_minus_0p5"]),
            "single_fold":float(delta.min())>=float(gate["minimum_single_fold_delta"]),
        }
        audit[method]={"checks":checks,"eligible":all(checks.values()),"fold_delta":delta.tolist()}
        if all(checks.values()): eligible.append(method)
    if not eligible:return "H0_EQUAL_RANK4",audit
    key=lambda method:(observed[method]["pooled_ef5"],observed[method]["binary_ndcg_true_top10_at_budget5"],observed[method]["median_fold_ef5"],observed[method]["worst_fold_ef5"],observed[method]["pooled_ef10"],observed[method]["spearman"],-complexity[method])
    return max(eligible,key=key),audit


def write_tsv(path: Path, rows: Sequence[Mapping[str,Any]]) -> None:
    with path.open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]),delimiter="\t",lineterminator="\n"); writer.writeheader(); writer.writerows(rows)


def run(contract_path: Path, legacy_path: Path, b_path: Path, clean_reference_path: Path, assignment_path: Path, output_dir: Path, b_mode: str, phase_b_receipt: Path|None=None) -> dict[str,Any]:
    require(not output_dir.exists(),"output_exists")
    contract=json.loads(contract_path.read_text()); require(contract.get("schema_version")==CONTRACT_SCHEMA and contract.get("status")=="FROZEN_BEFORE_HARD_NEGATIVE_OOF","contract")
    bindings=contract["input_bindings"]
    CORE.verify(legacy_path,bindings["legacy_oof_sha256"],"legacy_oof"); CORE.verify(assignment_path,bindings["assignment_sha256"],"assignment"); CORE.verify(clean_reference_path,bindings["clean_b_oof_sha256"],"clean_reference")
    if b_mode=="clean_seed43": CORE.verify(b_path,bindings["clean_b_oof_sha256"],"clean_b")
    else:
        require(phase_b_receipt is not None,"phase_b_receipt_required"); receipt=json.loads(phase_b_receipt.read_text())
        require(receipt.get("status")=="PASS_PHASE_B_PROMOTED_TO_PHASE_C","phase_b_not_promoted")
        require(receipt.get("input_access")=={"open_development_rows":0,"frozen_test_rows":0},"phase_b_access")
        require(sha256_file(b_path) in set((receipt.get("outputs") or {}).values()),"phase_b_output_binding")
        require((receipt.get("input_bindings") or {}).get("promotion_contract_sha256")==bindings["phase_b_promotion_contract_sha256"],"promotion_binding")
    data=CORE.load_dataset(legacy_path,b_path,clean_reference_path,assignment_path,b_mode)
    scores,pool_audit,models=oof(data,contract); truth=CORE.exact_min(data.truth)
    observed={name:CORE.metrics(data.candidate_ids,data.folds,truth,score) for name,score in scores.items()}; selected,promotion=select(observed,contract)
    output_dir.parent.mkdir(parents=True,exist_ok=True); staging=Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.",dir=output_dir.parent))
    try:
        rows=[]
        for i,candidate in enumerate(data.candidate_ids):
            row={"candidate_id":candidate,"sequence_sha256":data.sequence_sha256[i],"parent_framework_cluster":data.parents[i],"fold_id":int(data.folds[i]),"truth_Rdual_exact_min":truth[i]}
            for method in METHODS:row[f"{method}__frontscreen_score"]=scores[method][i]
            rows.append(row)
        prediction=staging/"HARD_NEGATIVE_TOP5_OOF_PREDICTIONS.tsv"; write_tsv(prediction,rows)
        report={"schema_version":SCHEMA,"status":"PASS_HARD_NEGATIVE_TOP5_OOF","claim_boundary":CLAIM,"b_mode":b_mode,"counts":{"rows":len(rows),"parents":len(set(data.parents)),"folds":5},"methods":observed,"selected_method":selected,"target_ef5":5.0,"target_achieved_in_this_oof":observed[selected]["pooled_ef5"]>=5.0,"promotion_audit":promotion,"pool_audit":pool_audit,"input_access":{"open_development_rows":0,"frozen_test_rows":0}}
        report_path=staging/"HARD_NEGATIVE_TOP5_METRICS.json"; report_path.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
        with (staging/"HARD_NEGATIVE_FOLD_MODELS.pkl").open("wb") as handle:pickle.dump({"schema_version":SCHEMA,"models":models},handle,pickle.HIGHEST_PROTOCOL)
        receipt={"schema_version":SCHEMA,"status":report["status"],"selected_method":selected,"target_achieved_in_this_oof":report["target_achieved_in_this_oof"],"input_access":report["input_access"],"outputs":{}}
        for name in (prediction.name,report_path.name,"HARD_NEGATIVE_FOLD_MODELS.pkl"):receipt["outputs"][name]=sha256_file(staging/name)
        receipt_path=staging/"RUN_RECEIPT.json"; receipt_path.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
        hashes={path.name:sha256_file(path) for path in staging.iterdir() if path.is_file()};(staging/"SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name,digest in sorted(hashes.items())))
        os.replace(staging,output_dir);return report
    finally:
        if staging.exists():shutil.rmtree(staging)


def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--contract",type=Path,required=True);p.add_argument("--legacy-oof",type=Path,required=True);p.add_argument("--b-oof",type=Path,required=True);p.add_argument("--clean-b-reference",type=Path,required=True);p.add_argument("--assignment",type=Path,required=True);p.add_argument("--output-dir",type=Path,required=True);p.add_argument("--b-mode",choices=("clean_seed43","phase_b_3seed"),required=True);p.add_argument("--phase-b-receipt",type=Path)
    args=p.parse_args();result=run(args.contract,args.legacy_oof,args.b_oof,args.clean_b_reference,args.assignment,args.output_dir,args.b_mode,args.phase_b_receipt);print(json.dumps({"status":result["status"],"selected_method":result["selected_method"],"target_achieved":result["target_achieved_in_this_oof"]},sort_keys=True));return 0


if __name__=="__main__":raise SystemExit(main())
