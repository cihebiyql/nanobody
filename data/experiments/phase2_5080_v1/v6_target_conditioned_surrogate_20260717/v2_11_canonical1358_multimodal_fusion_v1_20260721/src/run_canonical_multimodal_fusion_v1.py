#!/usr/bin/env python3
"""Strict open-only sequence/M2/C2 fusion with whole-parent OOF meta fitting."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pickle
import numpy as np
import torch
from scipy.optimize import minimize
from scipy.stats import spearmanr
from sklearn.decomposition import PCA
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

SCHEMA = "pvrig_v2_11_canonical_multimodal_fusion_v1"
CLAIM = (
    "Open-development approximation of independent 8X6B/9E6Y computational "
    "Docking geometry only; not binding, affinity, experimental blocking, "
    "Docking Gold, frozen-test, sealed truth, or submission evidence."
)
FORBIDDEN_PATH_TOKENS = ("test32", "sealed_truth", "frozen_test", "frozen-test", "v4_f")
MODEL_NAMES = (
    "S0_MATCHED_ESM2_650M_PCA_ELASTICNET",
    "M2_STRUCTURE_ALPHA10",
    "C2_COARSE_POSE_PCA8",
    "M2_C2_CONVEX",
    "S0_M2_C2_CONVEX",
    "SHALLOW_GBDT_CHALLENGER",
)
AA = "ACDEFGHIKLMNPQRSTVWY"
HYDROPHOBIC = set("AVILMFWY"); AROMATIC = set("FWY"); POSITIVE = set("KRH"); NEGATIVE = set("DE")

class FusionError(RuntimeError):
    pass

def require(condition: bool, message: str) -> None:
    if not condition:
        raise FusionError(message)

def reject_path(path: Path, role: str) -> None:
    normalized = str(path.resolve()).lower().replace("-", "_")
    for token in FORBIDDEN_PATH_TOKENS:
        require(token.replace("-", "_") not in normalized, f"forbidden_{role}_path:{token}")

def require_regular(path: Path, role: str) -> None:
    reject_path(path, role); require(path.is_file() and not path.is_symlink(), f"{role}_not_regular:{path}")

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()

def load_tsv(path: Path, role: str) -> tuple[list[str], list[dict[str, str]]]:
    require_regular(path, role)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or []); rows = [dict(row) for row in reader]
    require(fields and rows, f"{role}_empty"); return fields, rows

def load_cache(cache_dir: Path, expected: Mapping[str, str]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    reject_path(cache_dir, "embedding_cache")
    receipt_path = cache_dir / "embedding_cache_receipt.json"; require_regular(receipt_path, "embedding_receipt")
    receipt = json.loads(receipt_path.read_text())
    require(receipt.get("schema_version") == "pvrig_v6_esm_embedding_cache_v1", "embedding_schema")
    values: dict[str, np.ndarray] = {}; hashes: dict[str, str] = {}; width = None
    for item in receipt.get("shards", []):
        shard = Path(item["path"]); require(shard.parent.resolve() == (cache_dir / "shards").resolve(), "shard_outside_cache")
        require_regular(shard, "embedding_shard"); require(sha256_file(shard) == item["sha256"], "shard_hash")
        payload = torch.load(shard, map_location="cpu", weights_only=False)
        matrix = payload["embeddings"].float().numpy(); ids = payload["metadata"]["candidate_ids"]
        sequence_hashes = payload["metadata"]["sequence_sha256"]
        require(matrix.ndim == 2 and matrix.shape[0] == len(ids) == len(sequence_hashes), "embedding_shape")
        width = matrix.shape[1] if width is None else width; require(matrix.shape[1] == width and np.isfinite(matrix).all(), "embedding_finite_width")
        for candidate, sequence_sha, vector in zip(ids, sequence_hashes, matrix):
            require(candidate not in values, f"duplicate_embedding:{candidate}")
            values[str(candidate)] = vector.astype(np.float64); hashes[str(candidate)] = str(sequence_sha)
    require(int(receipt.get("rows", -1)) == len(values), "cache_row_count")
    require(set(expected) <= set(values), "cache_candidate_missing")
    for candidate, sequence_sha in expected.items(): require(hashes[candidate] == sequence_sha, f"cache_sequence:{candidate}")
    return values, {"receipt_sha256": sha256_file(receipt_path), "cache_rows": len(values), "width": width}

def region_features(sequence: str) -> list[float]:
    n = len(sequence); require(n > 0, "empty_region")
    counts = {aa: sequence.count(aa) for aa in AA}; probs = [counts[a] / n for a in AA]
    entropy = -sum(p * math.log(p + 1e-12) for p in probs) / math.log(len(AA))
    return [float(n), *probs, sum(counts[x] for x in HYDROPHOBIC)/n,
            sum(counts[x] for x in AROMATIC)/n, sum(counts[x] for x in POSITIVE)/n,
            sum(counts[x] for x in NEGATIVE)/n,
            (sum(counts[x] for x in POSITIVE)-sum(counts[x] for x in NEGATIVE))/n,
            counts["G"]/n, counts["P"]/n, counts["C"]/n, entropy, max(counts.values())/n]

def physchem(rows: Sequence[Mapping[str, str]]) -> np.ndarray:
    result = []
    for row in rows:
        feature = []
        for name in ("sequence", "cdr1", "cdr2", "cdr3"):
            region = row[name].strip().upper(); require(region and set(region) <= set(AA), f"invalid_region:{row['candidate_id']}:{name}")
            require(name == "sequence" or region in row["sequence"], f"region_not_in_sequence:{row['candidate_id']}:{name}")
            feature.extend(region_features(region))
        result.append(feature)
    matrix = np.asarray(result, dtype=np.float64); require(np.isfinite(matrix).all(), "physchem_nonfinite"); return matrix

def hierarchical_weights(rows: Sequence[Mapping[str, str]]) -> np.ndarray:
    groups: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for i, row in enumerate(rows): groups[row["teacher_source"]][row["parent_framework_cluster"]].append(i)
    weights = np.zeros(len(rows), dtype=np.float64)
    for parents in groups.values():
        for indices in parents.values():
            for i in indices: weights[i] = 1.0 / len(groups) / len(parents) / len(indices)
    reliability = np.asarray([float(row["sample_weight"]) for row in rows])
    require(np.all(reliability > 0) and np.isfinite(reliability).all(), "sample_weight_invalid")
    weights *= reliability; weights /= weights.mean()
    return weights

def exact_min(pred: np.ndarray) -> np.ndarray:
    require(pred.ndim == 2 and pred.shape[1] == 2, "prediction_shape"); return np.minimum(pred[:, 0], pred[:, 1])

def fit_scaled_ridge(x: np.ndarray, y: np.ndarray, weights: np.ndarray, alpha: float) -> dict[str, Any]:
    scaler = StandardScaler().fit(x, sample_weight=weights)
    model = Ridge(alpha=alpha, solver="lsqr").fit(scaler.transform(x), y, sample_weight=weights)
    return {"scaler": scaler, "model": model, "alpha": alpha}

def predict_scaled(bundle: Mapping[str, Any], x: np.ndarray) -> np.ndarray:
    result = np.asarray(bundle["model"].predict(bundle["scaler"].transform(x)), dtype=np.float64)
    require(result.shape == (len(x), 2) and np.isfinite(result).all(), "ridge_prediction"); return result

def fit_s0(x_emb: np.ndarray, x_phys: np.ndarray, y: np.ndarray, weights: np.ndarray, seed: int) -> dict[str, Any]:
    components = min(128, len(x_emb)-1, x_emb.shape[1]); require(components >= 1, "s0_pca_components")
    pca = PCA(n_components=components, whiten=True, svd_solver="randomized", random_state=seed)
    reduced = pca.fit_transform(x_emb); joined = np.concatenate((reduced, x_phys), axis=1)
    scaler = StandardScaler().fit(joined); z = scaler.transform(joined); models = []
    for target in range(2):
        model = ElasticNet(alpha=0.003, l1_ratio=0.10, max_iter=20000, tol=1e-6, random_state=seed)
        model.fit(z, y[:, target], sample_weight=weights); models.append(model)
    return {"pca": pca, "scaler": scaler, "models": models, "seed": seed}

def predict_s0(bundle: Mapping[str, Any], x_emb: np.ndarray, x_phys: np.ndarray) -> np.ndarray:
    joined = np.concatenate((bundle["pca"].transform(x_emb), x_phys), axis=1)
    z = bundle["scaler"].transform(joined)
    result = np.column_stack([model.predict(z) for model in bundle["models"]])
    require(result.shape == (len(x_emb), 2) and np.isfinite(result).all(), "s0_prediction"); return result

def fit_pca8(x: np.ndarray) -> dict[str, Any]:
    mean = x.mean(0); scale = x.std(0); retained = np.flatnonzero(scale > 1e-8)
    require(len(retained) >= 8, "c2_fewer_than_8_nonconstant")
    z = (x[:, retained]-mean[retained])/scale[retained]; _, singular, right = np.linalg.svd(z, full_matrices=False)
    axes = right[:8].copy()
    for i in range(len(axes)):
        anchor = int(np.argmax(np.abs(axes[i]))); axes[i] *= -1 if axes[i, anchor] < 0 else 1
    return {"mean": mean, "scale": scale, "retained": retained, "axes": axes, "singular": singular[:8]}

def transform_pca8(x: np.ndarray, state: Mapping[str, Any]) -> np.ndarray:
    z = (x[:, state["retained"]]-state["mean"][state["retained"]])/state["scale"][state["retained"]]
    result = z @ state["axes"].T; require(np.isfinite(result).all(), "c2_transform_nonfinite"); return result

def fit_c2(x: np.ndarray, y: np.ndarray, weights: np.ndarray, alpha: float) -> dict[str, Any]:
    pca = fit_pca8(x); ridge = fit_scaled_ridge(transform_pca8(x, pca), y, weights, alpha)
    return {"pca": pca, "ridge": ridge, "alpha": alpha}

def predict_c2(bundle: Mapping[str, Any], x: np.ndarray) -> np.ndarray:
    return predict_scaled(bundle["ridge"], transform_pca8(x, bundle["pca"]))

def parent_macro_loss(rows: Sequence[Mapping[str, str]], truth: np.ndarray, pred: np.ndarray) -> float:
    by = defaultdict(list)
    for i, row in enumerate(rows): by[row["parent_framework_cluster"]].append(i)
    values = []
    for indices in by.values():
        values.append(np.mean([mean_absolute_error(truth[indices, j], pred[indices, j]) for j in range(2)] + [mean_absolute_error(exact_min(truth[indices]), exact_min(pred[indices]))]))
    return float(np.mean(values))

def fit_convex(truth: np.ndarray, bases: Mapping[str, np.ndarray], weights: np.ndarray, fallback: str, l2: float) -> dict[str, Any]:
    names = tuple(name for name in bases if name != fallback); base = bases[fallback]
    delta = np.stack([bases[name]-base for name in names], axis=2); residual = truth-base
    normalized = weights/weights.sum()
    def objective(beta: np.ndarray) -> float:
        error = np.einsum("nrb,b->nr", delta, beta)-residual
        return float(np.sum(normalized[:,None]*error*error)+l2*beta@beta)
    def gradient(beta: np.ndarray) -> np.ndarray:
        error = np.einsum("nrb,b->nr", delta, beta)-residual
        return 2*np.einsum("n,nr,nrb->b", normalized,error,delta)+2*l2*beta
    result = minimize(objective, np.zeros(len(names)), jac=gradient, method="SLSQP", bounds=[(0,1)]*len(names), constraints=[{"type":"ineq","fun":lambda b:1-float(b.sum()),"jac":lambda b:-np.ones_like(b)}], options={"ftol":1e-14,"maxiter":2000})
    require(bool(result.success), f"convex_fit:{result.message}"); beta=np.maximum(result.x,0); beta[beta<1e-12]=0
    require(beta.sum() <= 1+1e-9, "convex_sum")
    return {"fallback": fallback, "branches": names, "weights": beta, "fallback_weight": 1-float(beta.sum()), "l2": l2}

def predict_convex(model: Mapping[str, Any], bases: Mapping[str, np.ndarray]) -> np.ndarray:
    result = bases[model["fallback"]].copy()
    for name, weight in zip(model["branches"], model["weights"]): result += weight*(bases[name]-bases[model["fallback"]])
    require(np.isfinite(result).all(), "convex_prediction"); return result

def meta_features(bases: Mapping[str, np.ndarray]) -> np.ndarray:
    s0,m2,c2=(bases[n] for n in ("S0","M2","C2"))
    result=np.column_stack([s0,m2,c2,np.abs(s0[:,0]-s0[:,1]),np.abs(m2[:,0]-m2[:,1]),np.abs(c2[:,0]-c2[:,1]),np.mean(np.abs(s0-m2),1),np.mean(np.abs(s0-c2),1),np.mean(np.abs(m2-c2),1)])
    require(result.shape[1]==12 and np.isfinite(result).all(), "meta_feature_shape"); return result

def fit_gbdt(x: np.ndarray, y: np.ndarray, weights: np.ndarray, args: argparse.Namespace) -> list[Any]:
    models=[]
    for target in range(2):
        model=HistGradientBoostingRegressor(max_depth=args.gbdt_max_depth,max_iter=args.gbdt_max_iter,learning_rate=args.gbdt_learning_rate,min_samples_leaf=args.gbdt_min_samples_leaf,l2_regularization=args.gbdt_l2,random_state=args.seed)
        model.fit(x,y[:,target],sample_weight=weights);models.append(model)
    return models

def predict_gbdt(models: Sequence[Any], x: np.ndarray) -> np.ndarray:
    result=np.column_stack([m.predict(x) for m in models]);require(np.isfinite(result).all(),"gbdt_prediction");return result

def ranked(candidate_ids: Sequence[str], values: np.ndarray) -> list[int]:
    return sorted(range(len(values)),key=lambda i:(-float(values[i]),candidate_ids[i]))

def enrichment(candidate_ids: Sequence[str], truth: np.ndarray, score: np.ndarray) -> list[dict[str, Any]]:
    result=[];n=len(truth);to=ranked(candidate_ids,truth);po=ranked(candidate_ids,score)
    for tf in (0.10,0.20):
        positives=max(1,math.ceil(n*tf)); truth_set=set(to[:positives]); prevalence=positives/n
        for budget in (0.05,0.10,0.20):
            selected=max(1,math.ceil(n*budget));hits=len(truth_set&set(po[:selected]));precision=hits/selected
            result.append({"true_top_fraction":tf,"predicted_budget_fraction":budget,"n":n,"positives":positives,"selected":selected,"hits":hits,"precision":precision,"recall":hits/positives,"enrichment_factor":precision/prevalence})
    return result

def metrics(rows: Sequence[Mapping[str,str]], truth: np.ndarray, pred: np.ndarray) -> dict[str,Any]:
    ids=[r["candidate_id"] for r in rows]; dual_t=exact_min(truth);dual_p=exact_min(pred); table=enrichment(ids,dual_t,dual_p)
    def sp(a,b):
        v=spearmanr(a,b).statistic;return float(v) if np.isfinite(v) else 0.0
    by=defaultdict(list)
    for i,r in enumerate(rows):by[r["parent_framework_cluster"]].append(i)
    recalls=[]
    for indices in by.values():
        k=max(1,math.ceil(len(indices)*.2)); true=set(sorted(indices,key=lambda i:(-dual_t[i],ids[i]))[:k]); pr=set(sorted(indices,key=lambda i:(-dual_p[i],ids[i]))[:k]);recalls.append(len(true&pr)/k)
    return {"R8":{"spearman":sp(truth[:,0],pred[:,0]),"mae":float(mean_absolute_error(truth[:,0],pred[:,0]))},"R9":{"spearman":sp(truth[:,1],pred[:,1]),"mae":float(mean_absolute_error(truth[:,1],pred[:,1]))},"Rdual_exact_min":{"spearman":sp(dual_t,dual_p),"mae":float(mean_absolute_error(dual_t,dual_p)),"rmse":float(mean_squared_error(dual_t,dual_p)**.5)},"early_enrichment":table,"within_parent_top20_macro_recall":float(np.mean(recalls)),"exact_min_violation_count":0}

def parse_full_prediction(raw: str) -> tuple[int,Path]:
    left,sep,right=raw.partition("=");require(sep and left.isdigit() and right,"full_prediction_arg");return int(left),Path(right)

def load_full_s0(inputs: Sequence[tuple[int,Path]], dev_rows: Sequence[Mapping[str,str]], model: str) -> tuple[np.ndarray|None,dict[str,Any]]:
    if not inputs:return None,{"status":"NOT_PROVIDED","files":0}
    ids={r["candidate_id"]:r for r in dev_rows}; matrices=[];audits=[]
    for seed,path in inputs:
        fields,rows=load_tsv(path,f"full_s0_seed_{seed}");require(f"{model}__R8" in fields and f"{model}__R9" in fields,"full_s0_model_columns")
        by={};
        for row in rows:
            candidate=row["candidate_id"];require(candidate not in by,"full_s0_duplicate")
            if candidate in ids:
                require(row["parent_framework_cluster"]==ids[candidate]["parent_framework_cluster"],f"full_s0_parent:{candidate}")
                by[candidate]=(float(row[f"{model}__R8"]),float(row[f"{model}__R9"]))
        require(set(by)==set(ids),f"full_s0_dev_closure:{seed}:{len(by)}")
        matrices.append(np.asarray([by[r["candidate_id"]] for r in dev_rows]));audits.append({"seed":seed,"path":str(path),"sha256":sha256_file(path)})
    return np.mean(np.stack(matrices),axis=0),{"status":"PASS_FULL9849_S0_BASE_ONLY","files":len(inputs),"inputs":audits,"used_for_fusion_weight_fit":False}

def write_tsv(path:Path,rows:list[dict[str,Any]])->None:
    with path.open("w",newline="") as h:
        w=csv.DictWriter(h,fieldnames=list(rows[0]),delimiter="\t",lineterminator="\n");w.writeheader();w.writerows(rows)

def run(args: argparse.Namespace) -> dict[str,Any]:
    reject_path(args.output_dir,"output");require(not args.output_dir.exists(),"output_exists")
    fields,rows=load_tsv(args.multimodal_tsv,"multimodal");require(sha256_file(args.multimodal_tsv)==args.expected_multimodal_sha256,"multimodal_hash")
    require_regular(args.materialization_receipt,"materialization_receipt")
    require(sha256_file(args.materialization_receipt)==args.expected_materialization_receipt_sha256,"materialization_receipt_hash")
    receipt=json.loads(args.materialization_receipt.read_text())
    require(receipt.get("status")=="PASS_OPEN_MULTIMODAL_INTERSECTION_MATERIALIZED","materialization_status")
    require(int(receipt["rows"])==len(rows),"materialization_rows")
    require(receipt.get("output_table_sha256")==args.expected_multimodal_sha256,"materialization_table_hash")
    structure_names=list(receipt["structure_feature_names"]);c2_names=[f"C2__{n}" for n in receipt["coarse_model_feature_names"]]
    require(len(structure_names)==126 and len(c2_names)==32,"feature_contract")
    train_rows=[r for r in rows if r["model_split"]=="train"];dev_rows=[r for r in rows if r["model_split"]=="development"]
    require(len(train_rows)==int(receipt["train_rows"]) and len(dev_rows)==int(receipt["development_rows"]),"split_counts")
    train_parents={r["parent_framework_cluster"] for r in train_rows};dev_parents={r["parent_framework_cluster"] for r in dev_rows};require(train_parents.isdisjoint(dev_parents),"parent_leakage")
    # Matrix indices below intentionally use one contiguous train block followed
    # by the untouched development block.  The materialized TSV itself remains
    # candidate-sorted and is never assumed to have split-contiguous rows.
    rows = [*train_rows, *dev_rows]
    cache,audit=load_cache(args.esm2_650m_cache,{r["candidate_id"]:r["sequence_sha256"] for r in rows})
    require(audit["receipt_sha256"]==receipt["embedding_cache"]["receipt_sha256"],"embedding_receipt_changed_since_materialization")
    xemb=np.stack([cache[r["candidate_id"]] for r in rows]);xphys=physchem(rows);xm2=np.asarray([[float(r[n]) for n in structure_names] for r in rows]);xc2=np.asarray([[float(r[n]) for n in c2_names] for r in rows]);y=np.asarray([[float(r["R_8X6B"]),float(r["R_9E6Y"])] for r in rows])
    require(all(np.isfinite(v).all() for v in (xemb,xphys,xm2,xc2,y)),"matrix_nonfinite")
    ntrain=len(train_rows);train_idx=np.arange(ntrain);dev_idx=np.arange(ntrain,len(rows));groups=np.asarray([r["parent_framework_cluster"] for r in train_rows]);fold_count=min(args.folds,len(set(groups)));require(fold_count>=2,"too_few_train_parents")
    oof={"S0":np.empty((ntrain,2)),"M2":np.empty((ntrain,2))};c2_oof={a:np.empty((ntrain,2)) for a in args.c2_alphas};fold_audit=[]
    splitter=GroupKFold(fold_count)
    for fold,(fit,score) in enumerate(splitter.split(train_idx,groups=groups)):
        fit_rows=[train_rows[i] for i in fit];weights=hierarchical_weights(fit_rows);require(set(groups[fit]).isdisjoint(set(groups[score])),"inner_parent_leakage")
        s0=fit_s0(xemb[fit],xphys[fit],y[fit],weights,args.seed+fold);oof["S0"][score]=predict_s0(s0,xemb[score],xphys[score])
        m2=fit_scaled_ridge(xm2[fit],y[fit],weights,10.0);oof["M2"][score]=predict_scaled(m2,xm2[score])
        for alpha in args.c2_alphas:
            c2=fit_c2(xc2[fit],y[fit],weights,alpha);c2_oof[alpha][score]=predict_c2(c2,xc2[score])
        fold_audit.append({"fold":fold,"fit_rows":len(fit),"score_rows":len(score),"fit_parents":len(set(groups[fit])),"score_parents":len(set(groups[score])),"parent_overlap":0})
    require(all(np.isfinite(v).all() for v in [*oof.values(),*c2_oof.values()]),"oof_incomplete")
    losses={a:parent_macro_loss(train_rows,y[train_idx],p) for a,p in c2_oof.items()};best_loss=min(losses.values());selected=max(a for a,v in losses.items() if abs(v-best_loss)<=1e-12);oof["C2"]=c2_oof[selected]
    train_weights=hierarchical_weights(train_rows)
    fusion_m2c2=fit_convex(y[train_idx],{"M2":oof["M2"],"C2":oof["C2"]},train_weights,"M2",args.fusion_l2)
    fusion_all=fit_convex(y[train_idx],oof,train_weights,"M2",args.fusion_l2)
    oof_predictions={MODEL_NAMES[0]:oof["S0"],MODEL_NAMES[1]:oof["M2"],MODEL_NAMES[2]:oof["C2"],MODEL_NAMES[3]:predict_convex(fusion_m2c2,{"M2":oof["M2"],"C2":oof["C2"]}),MODEL_NAMES[4]:predict_convex(fusion_all,oof)}
    gbdt=fit_gbdt(meta_features(oof),y[train_idx],train_weights,args);oof_predictions[MODEL_NAMES[5]]=predict_gbdt(gbdt,meta_features(oof))
    full_s0=fit_s0(xemb[train_idx],xphys[train_idx],y[train_idx],train_weights,args.seed);full_m2=fit_scaled_ridge(xm2[train_idx],y[train_idx],train_weights,10.0);full_c2=fit_c2(xc2[train_idx],y[train_idx],train_weights,selected)
    dev_base={"S0":predict_s0(full_s0,xemb[dev_idx],xphys[dev_idx]),"M2":predict_scaled(full_m2,xm2[dev_idx]),"C2":predict_c2(full_c2,xc2[dev_idx])}
    dev_predictions={MODEL_NAMES[0]:dev_base["S0"],MODEL_NAMES[1]:dev_base["M2"],MODEL_NAMES[2]:dev_base["C2"],MODEL_NAMES[3]:predict_convex(fusion_m2c2,{"M2":dev_base["M2"],"C2":dev_base["C2"]}),MODEL_NAMES[4]:predict_convex(fusion_all,dev_base),MODEL_NAMES[5]:predict_gbdt(gbdt,meta_features(dev_base))}
    full_inputs=[parse_full_prediction(x) for x in args.full_stage0_prediction];full_pred,full_audit=load_full_s0(full_inputs,dev_rows,args.full_stage0_model)
    if full_pred is not None:dev_predictions["S0_FULL9849_FROZEN_ENSEMBLE_BASE_ONLY"]=full_pred
    dev_metrics={name:metrics(dev_rows,y[dev_idx],pred) for name,pred in dev_predictions.items()};oof_metrics={name:metrics(train_rows,y[train_idx],pred) for name,pred in oof_predictions.items()}
    args.output_dir.mkdir(parents=True)
    out=[]
    for i,row in enumerate(dev_rows):
        item={"candidate_id":row["candidate_id"],"parent_framework_cluster":row["parent_framework_cluster"],"teacher_source":row["teacher_source"],"teacher_reliability":row["teacher_reliability"],"truth_R8":y[dev_idx[i],0],"truth_R9":y[dev_idx[i],1],"truth_Rdual_exact_min":min(y[dev_idx[i]])}
        for name,pred in dev_predictions.items():item[f"{name}__R8"]=pred[i,0];item[f"{name}__R9"]=pred[i,1];item[f"{name}__Rdual_exact_min"]=min(pred[i])
        out.append(item)
    write_tsv(args.output_dir/"OPEN_DEVELOPMENT_PREDICTIONS.tsv",out)
    oof_rows=[]
    for i,row in enumerate(train_rows):
        item={"candidate_id":row["candidate_id"],"parent_framework_cluster":row["parent_framework_cluster"],"teacher_source":row["teacher_source"],"truth_R8":y[i,0],"truth_R9":y[i,1],"truth_Rdual_exact_min":min(y[i])}
        for name,pred in oof_predictions.items():item[f"{name}__R8"]=pred[i,0];item[f"{name}__R9"]=pred[i,1];item[f"{name}__Rdual_exact_min"]=min(pred[i])
        oof_rows.append(item)
    write_tsv(args.output_dir/"TRAIN_INNER_OOF_PREDICTIONS.tsv",oof_rows)
    payload={"schema_version":SCHEMA,"status":"PASS_OPEN_MULTIMODAL_FUSION_DEVELOPMENT_COMPLETE","claim_boundary":CLAIM,"rows":len(rows),"train_rows":ntrain,"development_rows":len(dev_rows),"train_parent_count":len(train_parents),"development_parent_count":len(dev_parents),"folds":fold_count,"fold_audit":fold_audit,"C2_alpha_selection":{"grid":list(args.c2_alphas),"train_oof_parent_macro_loss":{str(k):v for k,v in losses.items()},"selected":selected},"fusion":{"M2_C2":{**fusion_m2c2,"weights":list(map(float,fusion_m2c2["weights"]))},"S0_M2_C2":{**fusion_all,"weights":list(map(float,fusion_all["weights"]))},"weights_fit_on":"train inner whole-parent OOF only","development_used_for_fit_or_selection":False},"gbdt":{"role":"CHALLENGER_ONLY","features":12,"max_depth":args.gbdt_max_depth,"max_iter":args.gbdt_max_iter,"learning_rate":args.gbdt_learning_rate,"min_samples_leaf":args.gbdt_min_samples_leaf,"l2":args.gbdt_l2},"train_oof_metrics":oof_metrics,"open_development_metrics":dev_metrics,"full9849_s0":full_audit,"embedding_cache":audit,"inputs":{"multimodal_tsv_sha256":sha256_file(args.multimodal_tsv),"materialization_receipt_sha256":sha256_file(args.materialization_receipt)},"frozen_test_access_count":0,"sealed_truth_access_count":0}
    (args.output_dir/"METRICS.json").write_text(json.dumps(payload,indent=2,sort_keys=True,allow_nan=False)+"\n")
    with (args.output_dir/"MODEL_ARTIFACT.pkl").open("wb") as handle:
        pickle.dump({"schema_version":SCHEMA,"claim_boundary":CLAIM,"S0":full_s0,"M2":full_m2,"C2":full_c2,"C2_selected_alpha":selected,"fusion_m2c2":fusion_m2c2,"fusion_all":fusion_all,"gbdt":gbdt,"structure_feature_names":structure_names,"c2_feature_names":c2_names},handle,protocol=pickle.HIGHEST_PROTOCOL)
    receipt_out={"schema_version":SCHEMA,"status":payload["status"],"rows":len(rows),"train_rows":ntrain,"development_rows":len(dev_rows),"development_used_for_fit_or_selection":False,"exact_min_violation_count":0,"full9849_s0_status":full_audit["status"],"claim_boundary":CLAIM}
    (args.output_dir/"RUN_RECEIPT.json").write_text(json.dumps(receipt_out,indent=2,sort_keys=True)+"\n")
    sums={p.name:sha256_file(p) for p in args.output_dir.iterdir() if p.is_file() and p.name!="SHA256SUMS"};(args.output_dir/"SHA256SUMS").write_text("".join(f"{d}  {n}\n" for n,d in sorted(sums.items())))
    return {"status":payload["status"],"rows":len(rows),"train_rows":ntrain,"development_rows":len(dev_rows),"selected_c2_alpha":selected,"output_dir":str(args.output_dir)}

def parse_alphas(raw:str)->tuple[float,...]:
    values=tuple(float(x) for x in raw.split(",") if x.strip());require(values and all(x>0 for x in values) and len(set(values))==len(values),"c2_alpha_grid");return values

def parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--multimodal-tsv",type=Path,required=True);p.add_argument("--expected-multimodal-sha256",required=True);p.add_argument("--materialization-receipt",type=Path,required=True);p.add_argument("--expected-materialization-receipt-sha256",required=True);p.add_argument("--esm2-650m-cache",type=Path,required=True);p.add_argument("--output-dir",type=Path,required=True);p.add_argument("--folds",type=int,default=5);p.add_argument("--seed",type=int,default=193);p.add_argument("--c2-alphas",type=parse_alphas,default=parse_alphas("0.0001,0.001,0.01,0.1,1,10,100"));p.add_argument("--fusion-l2",type=float,default=0.001);p.add_argument("--gbdt-max-depth",type=int,default=2);p.add_argument("--gbdt-max-iter",type=int,default=64);p.add_argument("--gbdt-learning-rate",type=float,default=0.05);p.add_argument("--gbdt-min-samples-leaf",type=int,default=64);p.add_argument("--gbdt-l2",type=float,default=2.0);p.add_argument("--full-stage0-prediction",action="append",default=[]);p.add_argument("--full-stage0-model",default="ELASTICNET_ESM2_650M_PCA");return p

def main()->int:
    result=run(parser().parse_args());print(json.dumps(result,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
