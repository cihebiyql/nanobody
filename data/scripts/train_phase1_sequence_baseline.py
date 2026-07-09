#!/usr/bin/env python3
"""Train Phase 1 pure-NumPy sequence-only baselines.

Outputs:
- residue logistic heads for VHH paratope and antigen epitope masks
- VHH-only ridge score head from ZYMScott VHH affinity split
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

AA = "ACDEFGHIKLMNPQRSTVWY"
AA_TO_IDX = {aa: i for i, aa in enumerate(AA)}
UNK_IDX = len(AA)
FEAT_AA = len(AA) + 1
EPS = 1e-8


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -40, 40)))


def aa_onehot(ch: str) -> np.ndarray:
    vec = np.zeros(FEAT_AA, dtype=np.float32)
    vec[AA_TO_IDX.get(ch, UNK_IDX)] = 1.0
    return vec


def aa_composition(seq: str) -> np.ndarray:
    vec = np.zeros(FEAT_AA, dtype=np.float32)
    if not isinstance(seq, str) or not seq:
        vec[UNK_IDX] = 1.0
        return vec
    for ch in seq:
        vec[AA_TO_IDX.get(ch, UNK_IDX)] += 1.0
    total = vec.sum()
    if total > 0:
        vec /= total
    return vec


def residue_features(seq: str, partner_seq: str, max_len_scale: float = 512.0) -> np.ndarray:
    """Local residue features: AA window +/-2, position, length and partner composition."""
    seq = seq if isinstance(seq, str) else ""
    partner = partner_seq if isinstance(partner_seq, str) else ""
    partner_comp = aa_composition(partner)
    own_comp = aa_composition(seq)
    n = len(seq)
    feats = []
    for i, ch in enumerate(seq):
        parts = []
        for off in [-2, -1, 0, 1, 2]:
            j = i + off
            parts.append(aa_onehot(seq[j]) if 0 <= j < n else np.zeros(FEAT_AA, dtype=np.float32))
        pos = 0.0 if n <= 1 else i / (n - 1)
        numeric = np.array(
            [
                pos,
                1.0 - pos,
                math.sin(2 * math.pi * pos),
                math.cos(2 * math.pi * pos),
                min(n / max_len_scale, 2.0),
                min(len(partner) / max_len_scale, 2.0),
            ],
            dtype=np.float32,
        )
        parts.extend([numeric, partner_comp, own_comp])
        feats.append(np.concatenate(parts))
    if not feats:
        dim = FEAT_AA * 5 + 6 + FEAT_AA * 2
        return np.zeros((0, dim), dtype=np.float32)
    return np.vstack(feats).astype(np.float32)


def mask_to_array(mask: str, expected_len: int) -> np.ndarray:
    if not isinstance(mask, str):
        return np.zeros(expected_len, dtype=np.float32)
    arr = np.array([1.0 if c == "1" else 0.0 for c in mask[:expected_len]], dtype=np.float32)
    if len(arr) < expected_len:
        arr = np.pad(arr, (0, expected_len - len(arr)))
    return arr


def build_residue_dataset(df: pd.DataFrame, target: str) -> tuple[np.ndarray, np.ndarray, list[tuple[str, int]]]:
    xs = []
    ys = []
    groups: list[tuple[str, int]] = []
    if target == "paratope":
        seq_col, partner_col, mask_col = "seq_nanobody", "seq_antigen", "paratope"
    elif target == "epitope":
        seq_col, partner_col, mask_col = "seq_antigen", "seq_nanobody", "epitope"
    else:
        raise ValueError(target)
    for ridx, rec in df.iterrows():
        seq = str(rec.get(seq_col, ""))
        partner = str(rec.get(partner_col, ""))
        mask = str(rec.get(mask_col, ""))
        if not seq or len(seq) != len(mask):
            continue
        x = residue_features(seq, partner)
        y = mask_to_array(mask, len(seq))
        xs.append(x)
        ys.append(y)
        groups.extend([(str(rec.get("pdb", ridx)), len(seq))])
    if not xs:
        return np.zeros((0, 0), dtype=np.float32), np.zeros(0, dtype=np.float32), []
    return np.vstack(xs), np.concatenate(ys), groups


def fit_standardizer(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std[std < 1e-6] = 1.0
    return mean.astype(np.float32), std.astype(np.float32)


def standardize(x: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return ((x - mean) / std).astype(np.float32)


def train_logistic_adam(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    epochs: int,
    lr: float,
    batch_size: int,
    seed: int,
) -> tuple[np.ndarray, float, list[dict[str, float]]]:
    rng = np.random.default_rng(seed)
    n, d = x_train.shape
    w = rng.normal(0, 0.01, size=d).astype(np.float32)
    b = np.float32(0.0)
    m_w = np.zeros_like(w)
    v_w = np.zeros_like(w)
    m_b = np.float32(0.0)
    v_b = np.float32(0.0)
    pos = max(float(y_train.sum()), 1.0)
    neg = max(float(len(y_train) - y_train.sum()), 1.0)
    pos_weight = min(neg / pos, 25.0)
    history = []
    t = 0
    best = (w.copy(), float(b), -1.0)
    for epoch in range(1, epochs + 1):
        order = rng.permutation(n)
        for start in range(0, n, batch_size):
            idx = order[start : start + batch_size]
            xb = x_train[idx]
            yb = y_train[idx]
            logits = xb @ w + b
            p = sigmoid(logits).astype(np.float32)
            weights = np.where(yb > 0.5, pos_weight, 1.0).astype(np.float32)
            grad_logits = (p - yb) * weights / max(float(weights.sum()), 1.0)
            grad_w = xb.T @ grad_logits + 1e-4 * w
            grad_b = grad_logits.sum()
            t += 1
            beta1, beta2 = 0.9, 0.999
            m_w = beta1 * m_w + (1 - beta1) * grad_w
            v_w = beta2 * v_w + (1 - beta2) * (grad_w * grad_w)
            m_b = beta1 * m_b + (1 - beta1) * grad_b
            v_b = beta2 * v_b + (1 - beta2) * (grad_b * grad_b)
            mw_hat = m_w / (1 - beta1**t)
            vw_hat = v_w / (1 - beta2**t)
            mb_hat = m_b / (1 - beta1**t)
            vb_hat = v_b / (1 - beta2**t)
            w -= lr * mw_hat / (np.sqrt(vw_hat) + 1e-8)
            b -= lr * mb_hat / (math.sqrt(float(vb_hat)) + 1e-8)
        if epoch == 1 or epoch % 5 == 0 or epoch == epochs:
            val_pred = sigmoid(x_val @ w + b) if len(y_val) else np.array([])
            val_metrics = binary_metrics(y_val, val_pred) if len(y_val) else {}
            train_pred = sigmoid(x_train[: min(n, 50000)] @ w + b)
            train_metrics = binary_metrics(y_train[: min(n, 50000)], train_pred)
            rec = {"epoch": float(epoch), "train_auprc": train_metrics.get("auprc", 0.0), "val_auprc": val_metrics.get("auprc", 0.0), "val_auroc": val_metrics.get("auroc", 0.0)}
            history.append(rec)
            if rec["val_auprc"] > best[2]:
                best = (w.copy(), float(b), rec["val_auprc"])
    return best[0], best[1], history


def binary_metrics(y: np.ndarray, score: np.ndarray, threshold: float = 0.5) -> dict[str, float]:
    y = y.astype(np.float64)
    score = score.astype(np.float64)
    pred = (score >= threshold).astype(np.float64)
    tp = float(((pred == 1) & (y == 1)).sum())
    fp = float(((pred == 1) & (y == 0)).sum())
    fn = float(((pred == 0) & (y == 1)).sum())
    tn = float(((pred == 0) & (y == 0)).sum())
    precision = tp / (tp + fp + EPS)
    recall = tp / (tp + fn + EPS)
    f1 = 2 * precision * recall / (precision + recall + EPS)
    return {
        "n": float(len(y)),
        "positive_rate": float(y.mean()) if len(y) else 0.0,
        "precision_at_0p5": precision,
        "recall_at_0p5": recall,
        "f1_at_0p5": f1,
        "auroc": auroc(y, score),
        "auprc": auprc(y, score),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def auroc(y: np.ndarray, score: np.ndarray) -> float:
    y = y.astype(np.int8)
    pos = int(y.sum())
    neg = len(y) - pos
    if pos == 0 or neg == 0:
        return 0.0
    order = np.argsort(score)
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(score) + 1)
    rank_sum_pos = ranks[y == 1].sum()
    return float((rank_sum_pos - pos * (pos + 1) / 2) / (pos * neg))


def auprc(y: np.ndarray, score: np.ndarray) -> float:
    y = y.astype(np.int8)
    pos = int(y.sum())
    if pos == 0:
        return 0.0
    order = np.argsort(-score)
    ys = y[order]
    tp = np.cumsum(ys)
    fp = np.cumsum(1 - ys)
    precision = tp / np.maximum(tp + fp, EPS)
    recall = tp / pos
    recall_prev = np.concatenate([[0.0], recall[:-1]])
    return float(np.sum((recall - recall_prev) * precision))


def vhh_score_features(seq: str, cdr1: str, cdr2: str, cdr3: str) -> np.ndarray:
    seq = seq if isinstance(seq, str) else ""
    cdr1 = cdr1 if isinstance(cdr1, str) else ""
    cdr2 = cdr2 if isinstance(cdr2, str) else ""
    cdr3 = cdr3 if isinstance(cdr3, str) else ""
    comps = [aa_composition(x) for x in [seq, cdr1, cdr2, cdr3]]
    lengths = np.array([len(seq), len(cdr1), len(cdr2), len(cdr3)], dtype=np.float32) / 150.0
    flags = np.array(
        [
            1.0 if "N" in cdr3 else 0.0,
            1.0 if "C" in cdr3 else 0.0,
            1.0 if "W" in cdr3 else 0.0,
            float(seq.count("C")) / max(len(seq), 1),
        ],
        dtype=np.float32,
    )
    return np.concatenate([*comps, lengths, flags]).astype(np.float32)


def build_vhh_score_dataset(path: Path) -> tuple[np.ndarray, np.ndarray]:
    df = pd.read_csv(path)
    feats = []
    labels = []
    for _, rec in df.iterrows():
        score = rec.get("score")
        try:
            y = float(score)
        except Exception:
            continue
        feats.append(vhh_score_features(str(rec.get("seq", "")), str(rec.get("CDR1", "")), str(rec.get("CDR2", "")), str(rec.get("CDR3", ""))))
        labels.append(y)
    return np.vstack(feats).astype(np.float32), np.array(labels, dtype=np.float32)


def fit_ridge(x: np.ndarray, y: np.ndarray, lam: float = 1.0) -> tuple[np.ndarray, float, np.ndarray, np.ndarray, float, float]:
    mean, std = fit_standardizer(x)
    xs = standardize(x, mean, std)
    y_mean = float(y.mean())
    y_std = float(y.std() if y.std() > 1e-6 else 1.0)
    ys = (y - y_mean) / y_std
    xb = np.concatenate([xs, np.ones((len(xs), 1), dtype=np.float32)], axis=1)
    eye = np.eye(xb.shape[1], dtype=np.float32)
    eye[-1, -1] = 0.0
    coef = np.linalg.solve(xb.T @ xb + lam * eye, xb.T @ ys).astype(np.float32)
    return coef[:-1], float(coef[-1]), mean, std, y_mean, y_std


def regression_metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    rmse = float(np.sqrt(np.mean((pred - y) ** 2)))
    mae = float(np.mean(np.abs(pred - y)))
    pearson = corr(y, pred)
    spearman = corr(rankdata(y), rankdata(pred))
    return {"n": float(len(y)), "rmse": rmse, "mae": mae, "pearson": pearson, "spearman": spearman}


def corr(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    if len(a) < 2 or a.std() < EPS or b.std() < EPS:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def rankdata(a: np.ndarray) -> np.ndarray:
    order = np.argsort(a)
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(len(a), dtype=np.float64)
    return ranks


def predict_ridge(x: np.ndarray, w: np.ndarray, b: float, mean: np.ndarray, std: np.ndarray, y_mean: float, y_std: float) -> np.ndarray:
    return (standardize(x, mean, std) @ w + b) * y_std + y_mean


def save_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def markdown_metrics_table(metrics: dict[str, dict[str, float]]) -> str:
    keys = sorted({k for m in metrics.values() for k in m.keys()})
    lines = ["| split | " + " | ".join(keys) + " |", "| --- | " + " | ".join(["---"] * len(keys)) + " |"]
    for split, vals in metrics.items():
        cells = []
        for k in keys:
            v = vals.get(k, "")
            if isinstance(v, float):
                cells.append(f"{v:.4f}")
            else:
                cells.append(str(v))
        lines.append("| " + split + " | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=8192)
    parser.add_argument("--lr", type=float, default=0.01)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    model_dir = root / "models/phase1_sequence_baseline"
    report_dir = root / "reports"
    model_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(exist_ok=True)

    base = root / "datasets/49_hf_broad_antibody/ZYMScott_Paratope"
    para_results: dict[str, Any] = {}
    for target in ["paratope", "epitope"]:
        train_df = pd.read_csv(base / "train.csv")
        val_df = pd.read_csv(base / "val.csv")
        test_df = pd.read_csv(base / "test.csv")
        x_train_raw, y_train, _ = build_residue_dataset(train_df, target)
        x_val_raw, y_val, _ = build_residue_dataset(val_df, target)
        x_test_raw, y_test, _ = build_residue_dataset(test_df, target)
        mean, std = fit_standardizer(x_train_raw)
        x_train = standardize(x_train_raw, mean, std)
        x_val = standardize(x_val_raw, mean, std)
        x_test = standardize(x_test_raw, mean, std)
        w, b, history = train_logistic_adam(
            x_train,
            y_train,
            x_val,
            y_val,
            epochs=args.epochs,
            lr=args.lr,
            batch_size=args.batch_size,
            seed=args.seed + (0 if target == "paratope" else 100),
        )
        metrics = {
            "train": binary_metrics(y_train, sigmoid(x_train @ w + b)),
            "val": binary_metrics(y_val, sigmoid(x_val @ w + b)),
            "test": binary_metrics(y_test, sigmoid(x_test @ w + b)),
        }
        np.savez_compressed(model_dir / f"{target}_logistic_head.npz", w=w, b=np.array([b], dtype=np.float32), mean=mean, std=std)
        para_results[target] = {"metrics": metrics, "history": history, "feature_dim": int(x_train.shape[1])}

    # VHH-only score head from cluster-aware affinity-seq split.
    aff_base = root / "datasets/49_hf_broad_antibody/ZYMScott_vhh_affinity-seq"
    x_train, y_train = build_vhh_score_dataset(aff_base / "train.csv")
    x_val, y_val = build_vhh_score_dataset(aff_base / "val.csv")
    x_test, y_test = build_vhh_score_dataset(aff_base / "test.csv")
    rw, rb, rmean, rstd, ymean, ystd = fit_ridge(x_train, y_train, lam=10.0)
    pred_train = predict_ridge(x_train, rw, rb, rmean, rstd, ymean, ystd)
    pred_val = predict_ridge(x_val, rw, rb, rmean, rstd, ymean, ystd)
    pred_test = predict_ridge(x_test, rw, rb, rmean, rstd, ymean, ystd)
    score_metrics = {
        "train": regression_metrics(y_train, pred_train),
        "val": regression_metrics(y_val, pred_val),
        "test": regression_metrics(y_test, pred_test),
    }
    np.savez_compressed(
        model_dir / "vhh_score_ridge_head.npz",
        w=rw,
        b=np.array([rb], dtype=np.float32),
        mean=rmean,
        std=rstd,
        y_mean=np.array([ymean], dtype=np.float32),
        y_std=np.array([ystd], dtype=np.float32),
    )

    metadata = {
        "model_name": "phase1_sequence_baseline_numpy",
        "created_for": "PVRIG VHH-antigen small model Phase 1",
        "feature_spec": {
            "residue_heads": "AA one-hot window +/-2 + normalized position/sin/cos + own/partner AA composition",
            "vhh_score_head": "full sequence and CDR1/2/3 amino-acid composition + lengths + simple CDR3 flags",
        },
        "datasets": {
            "paratope_epitope": "datasets/49_hf_broad_antibody/ZYMScott_Paratope",
            "vhh_score": "datasets/49_hf_broad_antibody/ZYMScott_vhh_affinity-seq",
        },
        "limitations": [
            "No pretrained protein language model is used in this dependency-free baseline.",
            "VHH score head is VHH-only because ZYMScott_vhh_affinity-seq has no antigen sequence field.",
            "This is not a calibrated absolute Kd predictor.",
        ],
        "args": vars(args),
    }
    save_json(model_dir / "metadata.json", metadata)

    all_metrics = {"paratope": para_results["paratope"], "epitope": para_results["epitope"], "vhh_score": {"metrics": score_metrics}}
    save_json(model_dir / "metrics.json", all_metrics)

    report = [
        "# Phase 1 Sequence-only Baseline 训练报告",
        "",
        "本阶段目标：不依赖 PyTorch/sklearn，先用纯 NumPy 跑通一个可训练、可保存、可评估的小模型闭环。",
        "",
        "## 模型组成",
        "",
        "- `paratope_logistic_head.npz`：VHH 每个残基是否为 paratope 的 logistic head。",
        "- `epitope_logistic_head.npz`：抗原每个残基是否为 epitope 的 logistic head。",
        "- `vhh_score_ridge_head.npz`：基于 VHH/CDR 组成特征的 VHH-only score ridge head。",
        "",
        "## Paratope Metrics",
        "",
        markdown_metrics_table(para_results["paratope"]["metrics"]),
        "",
        "## Epitope Metrics",
        "",
        markdown_metrics_table(para_results["epitope"]["metrics"]),
        "",
        "## VHH-only Score Metrics",
        "",
        markdown_metrics_table(score_metrics),
        "",
        "## 重要解释",
        "",
        "- 这只是 baseline，不是最终模型；它证明当前数据可以进入训练闭环。",
        "- paratope/epitope 头是 residue-level 二分类，主训练数据是 ZYMScott Paratope。",
        "- VHH score 头不是任意 VHH-antigen pair 亲和力模型，因为源数据没有 antigen 序列字段。",
        "- 后续应补 SAbDab2 single-domain 结构接触抽取，并替换/增强为 ESM/AntiBERTy embedding + cross-attention。",
        "",
    ]
    (report_dir / "phase1_sequence_baseline_eval.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps({"model_dir": str(model_dir), "report": str(report_dir / "phase1_sequence_baseline_eval.md"), "metrics": all_metrics}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
