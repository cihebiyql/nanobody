#!/usr/bin/env python3
"""Strict whole-parent nested multimodal stacking for Docking Top5 enrichment."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import pickle
import shutil
import tempfile
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import rankdata
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler


SCHEMA = "pvrig_v2_13_nested_multimodal_top5_stack_v1"
CONTRACT_SCHEMA = "pvrig_v2_13_nested_multimodal_top5_contract_v1"
BASES = ("S0", "M2", "C2", "B")
LEGACY = {
    "S0": "S0_MATCHED_ESM2_650M_PCA_ELASTICNET",
    "M2": "M2_STRUCTURE_ALPHA10",
    "C2": "C2_COARSE_POSE_PCA8",
}
METHODS = (
    "F0_EQUAL_RANK4",
    "F1_NESTED_WEIGHTED_RANK4",
    "F2_NESTED_POSITIVE_RIDGE4",
    "F3_NESTED_LOGISTIC_TOP10",
    "F4_SHALLOW_HGB_TOP10",
)
FORBIDDEN_PATH_TOKENS = ("open_development", "test32", "sealed_truth", "frozen_test", "v4_f")
CLAIM = (
    "Whole-parent OOF computational dual-receptor Docking-geometry meta-surrogate; "
    "not binding, affinity, experimental blocking, Docking Gold, or sealed-test evidence."
)


class StackError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StackError(message)


def sha256_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"regular_file_required:{path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reject_path(path: Path, role: str) -> None:
    value = str(path.resolve()).lower().replace("-", "_")
    for token in FORBIDDEN_PATH_TOKENS:
        require(token not in value, f"forbidden_{role}_path:{token}")


def verify(path: Path, digest: str, role: str) -> None:
    reject_path(path, role)
    require(len(digest) == 64 and sha256_file(path) == digest.lower(), f"{role}_sha256")


def read_tsv(path: Path, role: str) -> tuple[list[str], list[dict[str, str]]]:
    reject_path(path, role)
    require(path.is_file() and not path.is_symlink(), f"{role}_invalid")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields, rows = list(reader.fieldnames or ()), [dict(row) for row in reader]
    require(fields and rows, f"{role}_empty")
    return fields, rows


def exact_min(values: np.ndarray) -> np.ndarray:
    require(values.ndim == 2 and values.shape[1] == 2, "receptor_shape")
    return np.minimum(values[:, 0], values[:, 1])


def stable_order(candidate_ids: Sequence[str], score: np.ndarray) -> list[int]:
    return sorted(range(len(score)), key=lambda index: (-float(score[index]), candidate_ids[index]))


def early_metric(candidate_ids: Sequence[str], truth: np.ndarray, score: np.ndarray, budget: float) -> dict[str, float | int]:
    count = len(truth)
    positives = max(1, math.ceil(0.10 * count))
    selected = max(1, math.ceil(budget * count))
    truth_set = set(stable_order(candidate_ids, truth)[:positives])
    predicted = stable_order(candidate_ids, score)[:selected]
    hits = len(truth_set & set(predicted))
    relevance = np.asarray([1.0 if index in truth_set else 0.0 for index in predicted])
    discounts = np.log2(np.arange(2, selected + 2, dtype=np.float64))
    ideal_count = min(positives, selected)
    ideal = float(np.sum(1.0 / np.log2(np.arange(2, ideal_count + 2, dtype=np.float64))))
    return {
        "selected": selected,
        "positives": positives,
        "hits": hits,
        "precision": hits / selected,
        "recall": hits / positives,
        "ef": (hits / selected) / (positives / count),
        "binary_ndcg": float(np.sum(relevance / discounts)) / ideal,
    }


def spearman(truth: np.ndarray, score: np.ndarray) -> float:
    left, right = rankdata(truth), rankdata(score)
    if np.std(left) == 0 or np.std(right) == 0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def metrics(candidate_ids: Sequence[str], folds: np.ndarray, truth: np.ndarray, score: np.ndarray) -> dict[str, Any]:
    pooled5 = early_metric(candidate_ids, truth, score, 0.05)
    pooled10 = early_metric(candidate_ids, truth, score, 0.10)
    fold5 = []
    for fold in sorted(set(folds.tolist())):
        index = np.flatnonzero(folds == fold)
        fold5.append(float(early_metric([candidate_ids[i] for i in index], truth[index], score[index], 0.05)["ef"]))
    return {
        "pooled_ef5": float(pooled5["ef"]),
        "pooled_ef10": float(pooled10["ef"]),
        "pooled_top5_hits": int(pooled5["hits"]),
        "pooled_top5_selected": int(pooled5["selected"]),
        "pooled_top5_precision": float(pooled5["precision"]),
        "pooled_top5_recall": float(pooled5["recall"]),
        "binary_ndcg_true_top10_at_budget5": float(pooled5["binary_ndcg"]),
        "spearman": spearman(truth, score),
        "fold_ef5": fold5,
        "median_fold_ef5": float(np.median(fold5)),
        "worst_fold_ef5": float(np.min(fold5)),
    }


@dataclass(frozen=True)
class Dataset:
    candidate_ids: list[str]
    sequence_sha256: list[str]
    parents: list[str]
    folds: np.ndarray
    truth: np.ndarray
    bases: dict[str, np.ndarray]
    b_seed_std: np.ndarray
    b_mean_seed_rank: np.ndarray
    b43_dual: np.ndarray


def _pair(row: Mapping[str, str], prefix: str) -> tuple[float, float]:
    pair = (float(row[f"{prefix}__R8"]), float(row[f"{prefix}__R9"]))
    require(all(math.isfinite(value) for value in pair), f"nonfinite_pair:{row.get('candidate_id')}:{prefix}")
    return pair


def load_dataset(legacy_path: Path, b_path: Path, clean_reference_path: Path, assignment_path: Path, b_mode: str) -> Dataset:
    legacy_fields, legacy_rows = read_tsv(legacy_path, "legacy_oof")
    b_fields, b_rows = read_tsv(b_path, "b_oof")
    assignment_fields, assignment_rows = read_tsv(assignment_path, "assignment")
    clean_fields, clean_rows = read_tsv(clean_reference_path, "clean_b_reference")
    require(len(legacy_rows) == len(b_rows) == len(assignment_rows) == 9849, "row_count")
    require(len(clean_rows) == 9849, "clean_reference_row_count")
    require({"candidate_id", "parent_framework_cluster", "truth_R8", "truth_R9"} <= set(legacy_fields), "legacy_fields")
    require({"candidate_id", "sequence_sha256", "parent_framework_cluster", "fold_id"} <= set(assignment_fields), "assignment_fields")
    require({"candidate_id", "truth_R8", "truth_R9", "B_CLEAN_TARGET_ATTENTION__R8", "B_CLEAN_TARGET_ATTENTION__R9"} <= set(clean_fields), "clean_reference_fields")
    if b_mode == "clean_seed43":
        require({"candidate_id", "truth_R8", "truth_R9", "B_CLEAN_TARGET_ATTENTION__R8", "B_CLEAN_TARGET_ATTENTION__R9"} <= set(b_fields), "clean_b_fields")
    elif b_mode == "phase_b_3seed":
        require({"candidate_id", "truth_R8", "truth_R9", "mean_R8", "mean_R9", "primary_Rdual_exact_min", "mean_seed_rank", "seed_Rdual_std"} <= set(b_fields), "phase_b_fields")
    else:
        raise StackError("b_mode")
    legacy = {row["candidate_id"]: row for row in legacy_rows}
    b = {row["candidate_id"]: row for row in b_rows}
    assignment = {row["candidate_id"]: row for row in assignment_rows}
    clean = {row["candidate_id"]: row for row in clean_rows}
    require(len(legacy) == len(b) == len(assignment) == len(clean) == 9849 and set(legacy) == set(b) == set(assignment) == set(clean), "candidate_exact_closure")
    candidate_ids = sorted(legacy)
    sequence_sha, parents, folds, truth = [], [], [], []
    bases: dict[str, list[tuple[float, float]]] = {name: [] for name in BASES}
    b_std, b_rank, b43_dual = [], [], []
    for candidate in candidate_ids:
        old, new, assigned, clean_row = legacy[candidate], b[candidate], assignment[candidate], clean[candidate]
        require(old["parent_framework_cluster"] == assigned["parent_framework_cluster"], f"legacy_parent:{candidate}")
        old_truth = (float(old["truth_R8"]), float(old["truth_R9"]))
        new_truth = (float(new["truth_R8"]), float(new["truth_R9"]))
        require(max(abs(a-b_) for a,b_ in zip(old_truth,new_truth)) <= 4e-8, f"truth_mismatch:{candidate}")
        sequence_sha.append(assigned["sequence_sha256"]); parents.append(assigned["parent_framework_cluster"]); folds.append(int(assigned["fold_id"])); truth.append(old_truth)
        for name, prefix in LEGACY.items():
            bases[name].append(_pair(old, prefix))
        clean_truth = (float(clean_row["truth_R8"]), float(clean_row["truth_R9"]))
        require(max(abs(a-b_) for a,b_ in zip(old_truth,clean_truth)) <= 4e-8, f"clean_truth_mismatch:{candidate}")
        clean_pair = _pair(clean_row, "B_CLEAN_TARGET_ATTENTION")
        if b_mode == "clean_seed43":
            pair = _pair(new, "B_CLEAN_TARGET_ATTENTION")
            seed_std, seed_rank = 0.0, 0.5
            clean_reference = pair
        else:
            pair = (float(new["mean_R8"]), float(new["mean_R9"]))
            require(abs(float(new["primary_Rdual_exact_min"])-min(pair)) <= 4e-8, f"phase_b_exact_min:{candidate}")
            seed_std, seed_rank = float(new["seed_Rdual_std"]), float(new["mean_seed_rank"])
            clean_reference = clean_pair
        bases["B"].append(pair); b_std.append(seed_std); b_rank.append(seed_rank); b43_dual.append(min(clean_reference))
    fold_array = np.asarray(folds, dtype=np.int64)
    require(set(fold_array.tolist()) == set(range(5)), "five_folds")
    for fold in range(5):
        train_parents = {parents[i] for i in np.flatnonzero(fold_array != fold)}
        score_parents = {parents[i] for i in np.flatnonzero(fold_array == fold)}
        require(train_parents.isdisjoint(score_parents), f"parent_overlap:{fold}")
    return Dataset(candidate_ids, sequence_sha, parents, fold_array, np.asarray(truth), {name: np.asarray(value) for name,value in bases.items()}, np.asarray(b_std), np.asarray(b_rank), np.asarray(b43_dual))


def percentile_rank(values: np.ndarray) -> np.ndarray:
    return (rankdata(values, method="average") - 1.0) / max(1, len(values)-1)


def rank_score(bases: Mapping[str, np.ndarray], indices: np.ndarray, weights: np.ndarray) -> np.ndarray:
    ranks = np.column_stack([percentile_rank(exact_min(bases[name][indices])) for name in BASES])
    return ranks @ weights


def weight_grid() -> list[np.ndarray]:
    result = []
    for values in product((0.1,0.2,0.3,0.4,0.5), repeat=4):
        if abs(sum(values)-1.0) <= 1e-9:
            result.append(np.asarray(values, dtype=np.float64))
    return result


def inner_objective(fold_metrics: Sequence[dict[str, Any]]) -> tuple[float, float]:
    ef5 = np.asarray([item["pooled_ef5"] for item in fold_metrics])
    ef10 = np.asarray([item["pooled_ef10"] for item in fold_metrics])
    return float(ef5.mean()-0.5*ef5.std()), float(ef10.mean())


def choose_rank_weights(data: Dataset, outer_fold: int, candidates: Sequence[np.ndarray]) -> tuple[np.ndarray, dict[str, Any]]:
    inner_folds = [fold for fold in range(5) if fold != outer_fold]
    evaluated = []
    for weights in candidates:
        observed = []
        for fold in inner_folds:
            index = np.flatnonzero(data.folds == fold)
            observed.append(metrics([data.candidate_ids[i] for i in index], np.zeros(len(index),dtype=int), exact_min(data.truth[index]), rank_score(data.bases,index,weights)))
        objective, ef10 = inner_objective(observed)
        evaluated.append((objective,ef10,-float(np.sum((weights-0.25)**2)),tuple(-weights),weights,observed))
    selected = max(evaluated, key=lambda item: item[:4])
    return selected[4], {"objective":selected[0],"mean_ef10":selected[1],"weights":selected[4].tolist(),"inner_fold_metrics":selected[5]}


def parent_weights(parents: Sequence[str], indices: np.ndarray) -> np.ndarray:
    counts: dict[str,int] = {}
    for index in indices: counts[parents[index]] = counts.get(parents[index],0)+1
    weights = np.asarray([1.0/counts[parents[index]] for index in indices],dtype=np.float64)
    return weights/weights.mean()


def fit_ridge(data: Dataset, train: np.ndarray, alpha: float) -> list[Ridge]:
    result=[]; weights=parent_weights(data.parents,train)
    for receptor in range(2):
        x=np.column_stack([data.bases[name][train,receptor] for name in BASES])
        model=Ridge(alpha=alpha,positive=True,solver="lbfgs")
        model.fit(x,data.truth[train,receptor],sample_weight=weights); result.append(model)
    return result


def predict_ridge(models: Sequence[Ridge], data: Dataset, index: np.ndarray) -> np.ndarray:
    return np.column_stack([model.predict(np.column_stack([data.bases[name][index,receptor] for name in BASES])) for receptor,model in enumerate(models)])


def choose_ridge_alpha(data: Dataset, outer_fold: int, alphas: Sequence[float]) -> tuple[float,dict[str,Any]]:
    outer_train=np.flatnonzero(data.folds!=outer_fold); inner_folds=[fold for fold in range(5) if fold!=outer_fold]
    evaluated=[]
    for alpha in alphas:
        observed=[]
        for fold in inner_folds:
            validation=np.flatnonzero(data.folds==fold); fit=np.asarray([i for i in outer_train if data.folds[i]!=fold],dtype=int)
            prediction=predict_ridge(fit_ridge(data,fit,alpha),data,validation)
            observed.append(metrics([data.candidate_ids[i] for i in validation],np.zeros(len(validation),dtype=int),exact_min(data.truth[validation]),exact_min(prediction)))
        objective,ef10=inner_objective(observed); evaluated.append((objective,ef10,-alpha,alpha,observed))
    selected=max(evaluated,key=lambda item:item[:3])
    return selected[3],{"objective":selected[0],"mean_ef10":selected[1],"alpha":selected[3],"inner_fold_metrics":selected[4]}


@dataclass
class FeatureTransform:
    sorted_dual: list[np.ndarray]
    scaler: StandardScaler


def raw_meta_features(data: Dataset, index: np.ndarray, sorted_dual: Sequence[np.ndarray]) -> np.ndarray:
    dual=np.column_stack([exact_min(data.bases[name][index]) for name in BASES])
    gap=np.column_stack([np.abs(data.bases[name][index,0]-data.bases[name][index,1]) for name in BASES])
    ranks=np.column_stack([np.searchsorted(sorted_dual[column],dual[:,column],side="right")/max(1,len(sorted_dual[column])) for column in range(4)])
    aggregates=np.column_stack([dual.mean(1),dual.std(1),dual.min(1),dual.max(1)])
    extras=np.column_stack([data.b_seed_std[index],data.b_mean_seed_rank[index],dual[:,3]-data.b43_dual[index]])
    result=np.column_stack([dual,gap,ranks,aggregates,extras])
    require(result.shape[1]==19 and np.isfinite(result).all(),"meta_features")
    return result


def fit_transform(data: Dataset, train: np.ndarray) -> FeatureTransform:
    sorted_dual=[np.sort(exact_min(data.bases[name][train])) for name in BASES]
    scaler=StandardScaler().fit(raw_meta_features(data,train,sorted_dual))
    return FeatureTransform(sorted_dual,scaler)


def transform_features(data: Dataset, index: np.ndarray, transform: FeatureTransform) -> np.ndarray:
    return transform.scaler.transform(raw_meta_features(data,index,transform.sorted_dual))


def binary_labels(data: Dataset, train: np.ndarray) -> np.ndarray:
    truth=exact_min(data.truth[train]); threshold=np.sort(truth)[-max(1,math.ceil(0.10*len(truth)))]
    return (truth>=threshold).astype(np.int64)


def classifier_weights(data: Dataset, train: np.ndarray, labels: np.ndarray) -> np.ndarray:
    weights=parent_weights(data.parents,train); positive=int(labels.sum())
    require(0<positive<len(labels),"class_balance")
    weights[labels==1]*=len(labels)/(2*positive); weights[labels==0]*=len(labels)/(2*(len(labels)-positive))
    return weights


def fit_logistic(data: Dataset, train: np.ndarray, c_value: float) -> tuple[FeatureTransform,LogisticRegression]:
    transform=fit_transform(data,train); labels=binary_labels(data,train)
    model=LogisticRegression(C=c_value,penalty="l2",solver="lbfgs",max_iter=2000,random_state=43)
    model.fit(transform_features(data,train,transform),labels,sample_weight=classifier_weights(data,train,labels))
    return transform,model


def choose_logistic_c(data: Dataset, outer_fold: int, c_values: Sequence[float]) -> tuple[float,dict[str,Any]]:
    outer_train=np.flatnonzero(data.folds!=outer_fold); inner_folds=[fold for fold in range(5) if fold!=outer_fold]
    evaluated=[]
    for c_value in c_values:
        observed=[]
        for fold in inner_folds:
            validation=np.flatnonzero(data.folds==fold); fit=np.asarray([i for i in outer_train if data.folds[i]!=fold],dtype=int)
            transform,model=fit_logistic(data,fit,c_value)
            score=model.predict_proba(transform_features(data,validation,transform))[:,1]
            observed.append(metrics([data.candidate_ids[i] for i in validation],np.zeros(len(validation),dtype=int),exact_min(data.truth[validation]),score))
        objective,ef10=inner_objective(observed); evaluated.append((objective,ef10,-c_value,c_value,observed))
    selected=max(evaluated,key=lambda item:item[:3])
    return selected[3],{"objective":selected[0],"mean_ef10":selected[1],"C":selected[3],"inner_fold_metrics":selected[4]}


def fit_hgb(data: Dataset, train: np.ndarray, config: Mapping[str,Any]) -> tuple[FeatureTransform,HistGradientBoostingClassifier]:
    transform=fit_transform(data,train); labels=binary_labels(data,train)
    model=HistGradientBoostingClassifier(
        max_depth=int(config["max_depth"]),max_iter=int(config["max_iter"]),learning_rate=float(config["learning_rate"]),
        min_samples_leaf=int(config["min_samples_leaf"]),l2_regularization=float(config["l2_regularization"]),
        early_stopping=False,random_state=43,
    )
    model.fit(transform_features(data,train,transform),labels,sample_weight=classifier_weights(data,train,labels))
    return transform,model


def nested_oof(data: Dataset, contract: Mapping[str,Any]) -> tuple[dict[str,np.ndarray],dict[str,Any],dict[str,Any]]:
    scores={method:np.full(len(data.candidate_ids),np.nan,dtype=np.float64) for method in METHODS}
    fold_models: dict[str,Any]={}; hyperparameters: dict[str,Any]={}
    for outer in range(5):
        train=np.flatnonzero(data.folds!=outer); test=np.flatnonzero(data.folds==outer)
        scores["F0_EQUAL_RANK4"][test]=rank_score(data.bases,test,np.full(4,0.25))
        weights,rank_audit=choose_rank_weights(data,outer,weight_grid())
        scores["F1_NESTED_WEIGHTED_RANK4"][test]=rank_score(data.bases,test,weights)
        alpha,ridge_audit=choose_ridge_alpha(data,outer,contract["positive_ridge_alpha_grid"])
        ridge_models=fit_ridge(data,train,alpha); scores["F2_NESTED_POSITIVE_RIDGE4"][test]=exact_min(predict_ridge(ridge_models,data,test))
        c_value,logistic_audit=choose_logistic_c(data,outer,contract["logistic_c_grid"])
        logistic_transform,logistic=fit_logistic(data,train,c_value); scores["F3_NESTED_LOGISTIC_TOP10"][test]=logistic.predict_proba(transform_features(data,test,logistic_transform))[:,1]
        hgb_transform,hgb=fit_hgb(data,train,contract["hgb"]); scores["F4_SHALLOW_HGB_TOP10"][test]=hgb.predict_proba(transform_features(data,test,hgb_transform))[:,1]
        hyperparameters[str(outer)]={"rank":rank_audit,"ridge":ridge_audit,"logistic":logistic_audit}
        fold_models[str(outer)]={"rank_weights":weights,"ridge":ridge_models,"logistic_transform":logistic_transform,"logistic":logistic,"hgb_transform":hgb_transform,"hgb":hgb}
    require(all(np.isfinite(score).all() for score in scores.values()),"oof_nonfinite")
    return scores,hyperparameters,fold_models


def select_method(observed: Mapping[str,Mapping[str,Any]], contract: Mapping[str,Any]) -> tuple[str,dict[str,Any]]:
    baseline=observed["F0_EQUAL_RANK4"]; eligible=[]; audit={}
    complexity={name:index for index,name in enumerate(METHODS)}
    for method in METHODS[1:]:
        value=observed[method]; delta=np.asarray(value["fold_ef5"])-np.asarray(baseline["fold_ef5"])
        checks={
            "ef5_increment":value["pooled_ef5"]>=baseline["pooled_ef5"]+float(contract["promotion_gate"]["minimum_ef5_increment"]),
            "ef10":value["pooled_ef10"]>=baseline["pooled_ef10"]-float(contract["promotion_gate"]["maximum_ef10_decrement"]),
            "median_fold":value["median_fold_ef5"]>=baseline["median_fold_ef5"]-float(contract["promotion_gate"]["maximum_median_fold_ef5_decrement"]),
            "worst_fold":value["worst_fold_ef5"]>=baseline["worst_fold_ef5"]-float(contract["promotion_gate"]["maximum_worst_fold_ef5_decrement"]),
            "fold_count":int(np.sum(delta>=-0.5))>=int(contract["promotion_gate"]["minimum_folds_with_delta_at_least_minus_0p5"]),
            "single_fold":float(delta.min())>=float(contract["promotion_gate"]["minimum_single_fold_delta"]),
        }
        audit[method]={"checks":checks,"eligible":all(checks.values()),"fold_delta":delta.tolist()}
        if all(checks.values()): eligible.append(method)
    if not eligible: return "F0_EQUAL_RANK4",audit
    key=lambda method:(observed[method]["pooled_ef5"],observed[method]["binary_ndcg_true_top10_at_budget5"],observed[method]["median_fold_ef5"],observed[method]["worst_fold_ef5"],observed[method]["pooled_ef10"],observed[method]["spearman"],-complexity[method])
    return max(eligible,key=key),audit


def write_tsv(path: Path, rows: Sequence[Mapping[str,Any]]) -> None:
    with path.open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]),delimiter="\t",lineterminator="\n"); writer.writeheader(); writer.writerows(rows)


def run(
    contract_path: Path,
    legacy_path: Path,
    b_path: Path,
    clean_reference_path: Path,
    assignment_path: Path,
    output_dir: Path,
    b_mode: str,
    phase_b_receipt: Path | None = None,
) -> dict[str,Any]:
    require(not output_dir.exists(),"output_exists")
    contract=json.loads(contract_path.read_text())
    require(contract.get("schema_version")==CONTRACT_SCHEMA and contract.get("status")=="FROZEN_BEFORE_META_OOF_EXECUTION","contract")
    require(contract["b_modes_allowed"].get(b_mode) is True,"b_mode_contract")
    bindings=contract["input_bindings"]
    verify(legacy_path,bindings["legacy_oof_sha256"],"legacy_oof")
    verify(assignment_path,bindings["assignment_sha256"],"assignment")
    verify(clean_reference_path,bindings["clean_b_oof_sha256"],"clean_b_reference")
    if b_mode=="clean_seed43":
        verify(b_path,bindings["clean_b_oof_sha256"],"clean_b_oof")
    else:
        require(phase_b_receipt is not None,"phase_b_receipt_required")
        receipt=json.loads(phase_b_receipt.read_text())
        require(receipt.get("schema_version")=="pvrig_v2_13_phase_b_3seed_aggregate_v1","phase_b_receipt_schema")
        require(receipt.get("status")=="PASS_PHASE_B_PROMOTED_TO_PHASE_C","phase_b_not_promoted")
        require(receipt.get("input_access")=={"open_development_rows":0,"frozen_test_rows":0},"phase_b_access")
        require(sha256_file(b_path) in set((receipt.get("outputs") or {}).values()),"phase_b_output_binding")
        require((receipt.get("input_bindings") or {}).get("promotion_contract_sha256")==bindings["phase_b_promotion_contract_sha256"],"phase_b_promotion_binding")
    data=load_dataset(legacy_path,b_path,clean_reference_path,assignment_path,b_mode)
    scores,hyperparameters,fold_models=nested_oof(data,contract)
    truth=exact_min(data.truth); observed={name:metrics(data.candidate_ids,data.folds,truth,score) for name,score in scores.items()}
    selected,promotion=select_method(observed,contract)
    output_dir.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.",dir=output_dir.parent))
    try:
        rows=[]
        for index,candidate in enumerate(data.candidate_ids):
            row={"candidate_id":candidate,"sequence_sha256":data.sequence_sha256[index],"parent_framework_cluster":data.parents[index],"fold_id":int(data.folds[index]),"truth_R8":data.truth[index,0],"truth_R9":data.truth[index,1],"truth_Rdual_exact_min":truth[index]}
            for method in METHODS: row[f"{method}__frontscreen_score"]=scores[method][index]
            rows.append(row)
        prediction=staging/"NESTED_MULTIMODAL_TOP5_OOF_PREDICTIONS.tsv"; write_tsv(prediction,rows)
        report={"schema_version":SCHEMA,"status":"PASS_NESTED_MULTIMODAL_TOP5_OOF","claim_boundary":CLAIM,"b_mode":b_mode,"counts":{"rows":len(rows),"parents":len(set(data.parents)),"folds":5},"methods":observed,"selected_method":selected,"target_ef5":5.0,"target_achieved_in_this_oof":observed[selected]["pooled_ef5"]>=5.0,"promotion_audit":promotion,"inner_selection":hyperparameters,"input_access":{"open_development_rows":0,"frozen_test_rows":0}}
        report_path=staging/"NESTED_MULTIMODAL_TOP5_METRICS.json"; report_path.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
        with (staging/"NESTED_FOLD_MODELS.pkl").open("wb") as handle: pickle.dump({"schema_version":SCHEMA,"b_mode":b_mode,"methods":METHODS,"fold_models":fold_models},handle,pickle.HIGHEST_PROTOCOL)
        receipt={"schema_version":SCHEMA,"status":report["status"],"selected_method":selected,"target_achieved_in_this_oof":report["target_achieved_in_this_oof"],"input_bindings":{"contract_sha256":sha256_file(contract_path),"legacy_oof_sha256":sha256_file(legacy_path),"b_oof_sha256":sha256_file(b_path),"assignment_sha256":sha256_file(assignment_path)},"input_access":report["input_access"],"outputs":{}}
        for name in (prediction.name,report_path.name,"NESTED_FOLD_MODELS.pkl"): receipt["outputs"][name]=sha256_file(staging/name)
        receipt_path=staging/"RUN_RECEIPT.json"; receipt_path.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
        hashes={path.name:sha256_file(path) for path in staging.iterdir() if path.is_file()}; (staging/"SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name,digest in sorted(hashes.items())))
        os.replace(staging,output_dir); return report
    finally:
        if staging.exists(): shutil.rmtree(staging)


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract",type=Path,required=True); parser.add_argument("--legacy-oof",type=Path,required=True)
    parser.add_argument("--b-oof",type=Path,required=True); parser.add_argument("--clean-b-reference",type=Path,required=True); parser.add_argument("--assignment",type=Path,required=True)
    parser.add_argument("--phase-b-receipt",type=Path)
    parser.add_argument("--output-dir",type=Path,required=True); parser.add_argument("--b-mode",choices=("clean_seed43","phase_b_3seed"),required=True)
    args=parser.parse_args(); result=run(args.contract,args.legacy_oof,args.b_oof,args.clean_b_reference,args.assignment,args.output_dir,args.b_mode,args.phase_b_receipt)
    print(json.dumps({"status":result["status"],"selected_method":result["selected_method"],"target_achieved":result["target_achieved_in_this_oof"]},sort_keys=True)); return 0


if __name__=="__main__": raise SystemExit(main())
