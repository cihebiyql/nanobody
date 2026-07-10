#!/usr/bin/env python3
"""Train Phase 2 VHH-Ag CrossContactNet V1 on RTX 5080.

V1 scope:
- Transformer residue encoders for VHH and antigen sequences.
- Paratope and epitope residue heads on ZYMScott site masks.
- Weak contact proxy head sampled from paratope-positive x epitope-positive pairs.
- Pair binding head trained with cognate positives and constructed N1/N2/N3 negatives.
- PVRIG candidate inference with hotspot-weighted epitope/contact scores.

This is the first GPU-trainable architecture upgrade. True structure contact-map
training is prepared by manifests but reserved for V2 once chain sequence mapping
is expanded beyond the MVP contact extractor.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.nn.utils.rnn import pad_sequence
from torch.utils.data import DataLoader, Dataset

AA = "ACDEFGHIKLMNPQRSTVWY"
PAD_IDX = 0
UNK_IDX = len(AA) + 1
AA_TO_IDX = {aa: i + 1 for i, aa in enumerate(AA)}


def clean(v: Any) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    text = str(v).strip()
    if text.lower() in {"nan", "none", "na", "n/a"}:
        return ""
    return text


def encode_seq(seq: str, max_len: int) -> torch.Tensor:
    seq = clean(seq).upper()[:max_len]
    ids = [AA_TO_IDX.get(ch, UNK_IDX) for ch in seq]
    if not ids:
        ids = [UNK_IDX]
    return torch.tensor(ids, dtype=torch.long)


def encode_mask(mask: str, max_len: int, target_len: int) -> torch.Tensor:
    text = clean(mask)[:max_len]
    vals = [1.0 if ch == "1" else 0.0 for ch in text]
    if len(vals) < target_len:
        vals.extend([0.0] * (target_len - len(vals)))
    return torch.tensor(vals[:target_len], dtype=torch.float32)


def binary_metrics(y: np.ndarray, score: np.ndarray, threshold: float = 0.5) -> dict[str, float]:
    y = y.astype(np.float64)
    score = score.astype(np.float64)
    if len(y) == 0:
        return {"n": 0.0, "auroc": 0.0, "auprc": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0, "positive_rate": 0.0}
    pred = (score >= threshold).astype(np.float64)
    tp = float(((pred == 1) & (y == 1)).sum())
    fp = float(((pred == 1) & (y == 0)).sum())
    fn = float(((pred == 0) & (y == 1)).sum())
    tn = float(((pred == 0) & (y == 0)).sum())
    precision = tp / max(tp + fp, 1e-8)
    recall = tp / max(tp + fn, 1e-8)
    f1 = 2 * precision * recall / max(precision + recall, 1e-8)
    return {
        "n": float(len(y)),
        "positive_rate": float(y.mean()),
        "auroc": auroc(y, score),
        "auprc": auprc(y, score),
        "precision": precision,
        "recall": recall,
        "f1": f1,
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
    return float((rank_sum_pos - pos * (pos + 1) / 2) / max(pos * neg, 1))


def auprc(y: np.ndarray, score: np.ndarray) -> float:
    y = y.astype(np.int8)
    pos = int(y.sum())
    if pos == 0:
        return 0.0
    order = np.argsort(-score)
    ys = y[order]
    tp = np.cumsum(ys)
    fp = np.cumsum(1 - ys)
    precision = tp / np.maximum(tp + fp, 1e-8)
    recall = tp / pos
    recall_prev = np.concatenate([[0.0], recall[:-1]])
    return float(np.sum((recall - recall_prev) * precision))


@dataclass
class Config:
    root: str = "."
    out_root: str = "experiments/phase2_5080_v1"
    seed: int = 7
    d_model: int = 192
    layers: int = 3
    heads: int = 4
    dropout: float = 0.1
    max_vhh_len: int = 160
    max_antigen_len: int = 512
    batch_size_site: int = 24
    batch_size_pair: int = 48
    epochs: int = 8
    lr: float = 2e-4
    weight_decay: float = 1e-2
    contact_pos_per_sample: int = 32
    contact_neg_per_sample: int = 128
    site_loss_weight: float = 1.0
    contact_loss_weight: float = 0.5
    pair_loss_weight: float = 1.0
    use_amp: bool = True


class SiteDataset(Dataset):
    def __init__(self, path: Path, split: str, cfg: Config):
        df = pd.read_csv(path)
        self.df = df[df["split"].astype(str) == split].reset_index(drop=True)
        self.cfg = cfg

    def __len__(self) -> int:
        return len(self.df)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        r = self.df.loc[idx]
        v = encode_seq(r["vhh_seq"], self.cfg.max_vhh_len)
        a = encode_seq(r["antigen_seq"], self.cfg.max_antigen_len)
        return {
            "sample_id": clean(r["sample_id"]),
            "vhh": v,
            "antigen": a,
            "paratope": encode_mask(r["vhh_paratope_mask"], self.cfg.max_vhh_len, len(v)),
            "epitope": encode_mask(r["antigen_epitope_mask"], self.cfg.max_antigen_len, len(a)),
        }


class PairDataset(Dataset):
    def __init__(self, path: Path, split: str, cfg: Config):
        df = pd.read_csv(path)
        self.df = df[df["split"].astype(str) == split].reset_index(drop=True)
        self.cfg = cfg

    def __len__(self) -> int:
        return len(self.df)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        r = self.df.loc[idx]
        return {
            "pair_id": clean(r["pair_id"]),
            "negative_type": clean(r.get("negative_type", "")),
            "vhh": encode_seq(r["vhh_seq"], self.cfg.max_vhh_len),
            "antigen": encode_seq(r["antigen_seq"], self.cfg.max_antigen_len),
            "label": torch.tensor(float(r["binding_label"]), dtype=torch.float32),
        }


def collate_site(batch: list[dict[str, Any]]) -> dict[str, Any]:
    vhh = pad_sequence([b["vhh"] for b in batch], batch_first=True, padding_value=PAD_IDX)
    antigen = pad_sequence([b["antigen"] for b in batch], batch_first=True, padding_value=PAD_IDX)
    para = pad_sequence([b["paratope"] for b in batch], batch_first=True, padding_value=-1.0)
    epi = pad_sequence([b["epitope"] for b in batch], batch_first=True, padding_value=-1.0)
    return {"sample_id": [b["sample_id"] for b in batch], "vhh": vhh, "antigen": antigen, "paratope": para, "epitope": epi}


def collate_pair(batch: list[dict[str, Any]]) -> dict[str, Any]:
    vhh = pad_sequence([b["vhh"] for b in batch], batch_first=True, padding_value=PAD_IDX)
    antigen = pad_sequence([b["antigen"] for b in batch], batch_first=True, padding_value=PAD_IDX)
    label = torch.stack([b["label"] for b in batch])
    return {"pair_id": [b["pair_id"] for b in batch], "negative_type": [b["negative_type"] for b in batch], "vhh": vhh, "antigen": antigen, "label": label}


class CrossContactNet(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        vocab = len(AA) + 2
        self.aa = nn.Embedding(vocab, cfg.d_model, padding_idx=PAD_IDX)
        self.v_pos = nn.Embedding(cfg.max_vhh_len, cfg.d_model)
        self.a_pos = nn.Embedding(cfg.max_antigen_len, cfg.d_model)
        enc_layer_v = nn.TransformerEncoderLayer(cfg.d_model, cfg.heads, dim_feedforward=cfg.d_model * 4, dropout=cfg.dropout, batch_first=True, activation="gelu")
        enc_layer_a = nn.TransformerEncoderLayer(cfg.d_model, cfg.heads, dim_feedforward=cfg.d_model * 4, dropout=cfg.dropout, batch_first=True, activation="gelu")
        self.v_enc = nn.TransformerEncoder(enc_layer_v, num_layers=cfg.layers)
        self.a_enc = nn.TransformerEncoder(enc_layer_a, num_layers=cfg.layers)
        self.paratope = nn.Linear(cfg.d_model, 1)
        self.epitope = nn.Linear(cfg.d_model, 1)
        pair_dim = cfg.d_model * 4
        self.contact = nn.Sequential(nn.Linear(pair_dim, cfg.d_model), nn.GELU(), nn.Dropout(cfg.dropout), nn.Linear(cfg.d_model, 1))
        self.pair = nn.Sequential(nn.Linear(pair_dim, cfg.d_model), nn.GELU(), nn.Dropout(cfg.dropout), nn.Linear(cfg.d_model, 1))

    def encode(self, vhh: torch.Tensor, antigen: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        b, lv = vhh.shape
        _, la = antigen.shape
        v_mask = vhh.eq(PAD_IDX)
        a_mask = antigen.eq(PAD_IDX)
        v_pos = torch.arange(lv, device=vhh.device).unsqueeze(0).expand(b, lv).clamp(max=self.cfg.max_vhh_len - 1)
        a_pos = torch.arange(la, device=antigen.device).unsqueeze(0).expand(b, la).clamp(max=self.cfg.max_antigen_len - 1)
        hv = self.aa(vhh) + self.v_pos(v_pos)
        ha = self.aa(antigen) + self.a_pos(a_pos)
        hv = self.v_enc(hv, src_key_padding_mask=v_mask)
        ha = self.a_enc(ha, src_key_padding_mask=a_mask)
        return hv, ha, v_mask, a_mask

    def site_logits(self, hv: torch.Tensor, ha: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        return self.paratope(hv).squeeze(-1), self.epitope(ha).squeeze(-1)

    def pair_logits(self, hv: torch.Tensor, ha: torch.Tensor, v_mask: torch.Tensor, a_mask: torch.Tensor) -> torch.Tensor:
        v_valid = (~v_mask).float().unsqueeze(-1)
        a_valid = (~a_mask).float().unsqueeze(-1)
        vp = (hv * v_valid).sum(1) / v_valid.sum(1).clamp_min(1.0)
        ap = (ha * a_valid).sum(1) / a_valid.sum(1).clamp_min(1.0)
        feat = torch.cat([vp, ap, torch.abs(vp - ap), vp * ap], dim=-1)
        return self.pair(feat).squeeze(-1)

    def contact_logits_for_indices(self, hv: torch.Tensor, ha: torch.Tensor, batch_idx: torch.Tensor, v_idx: torch.Tensor, a_idx: torch.Tensor) -> torch.Tensor:
        x = hv[batch_idx, v_idx]
        y = ha[batch_idx, a_idx]
        feat = torch.cat([x, y, torch.abs(x - y), x * y], dim=-1)
        return self.contact(feat).squeeze(-1)

    def contact_matrix(self, hv: torch.Tensor, ha: torch.Tensor, batch: int = 0) -> torch.Tensor:
        x = hv[batch]
        y = ha[batch]
        lv, la = x.shape[0], y.shape[0]
        xe = x[:, None, :].expand(lv, la, -1)
        ye = y[None, :, :].expand(lv, la, -1)
        feat = torch.cat([xe, ye, torch.abs(xe - ye), xe * ye], dim=-1)
        return self.contact(feat).squeeze(-1)


def bce_masked(logits: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    mask = labels >= 0
    if mask.sum() == 0:
        return logits.sum() * 0.0
    y = labels[mask]
    x = logits[mask]
    pos = y.sum().clamp_min(1.0)
    neg = (len(y) - y.sum()).clamp_min(1.0)
    pos_weight = (neg / pos).clamp(max=25.0)
    return nn.functional.binary_cross_entropy_with_logits(x, y, pos_weight=pos_weight)


def sample_weak_contacts(batch: dict[str, Any], cfg: Config, device: torch.device) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    rng = random.Random(17)
    bsz = batch["vhh"].shape[0]
    b_list: list[int] = []
    v_list: list[int] = []
    a_list: list[int] = []
    y_list: list[float] = []
    para = batch["paratope"].cpu().numpy()
    epi = batch["epitope"].cpu().numpy()
    for b in range(bsz):
        p_pos = np.where(para[b] > 0.5)[0].tolist()
        e_pos = np.where(epi[b] > 0.5)[0].tolist()
        p_neg = np.where(para[b] == 0.0)[0].tolist()
        e_neg = np.where(epi[b] == 0.0)[0].tolist()
        for _ in range(min(cfg.contact_pos_per_sample, len(p_pos) * max(len(e_pos), 1))):
            if not p_pos or not e_pos:
                break
            b_list.append(b); v_list.append(rng.choice(p_pos)); a_list.append(rng.choice(e_pos)); y_list.append(1.0)
        for _ in range(min(cfg.contact_neg_per_sample, len(p_neg) * max(len(e_neg), 1))):
            if not p_neg or not e_neg:
                break
            b_list.append(b); v_list.append(rng.choice(p_neg)); a_list.append(rng.choice(e_neg)); y_list.append(0.0)
    if not b_list:
        return torch.zeros(0, dtype=torch.long, device=device), torch.zeros(0, dtype=torch.long, device=device), torch.zeros(0, dtype=torch.long, device=device), torch.zeros(0, dtype=torch.float32, device=device)
    return (
        torch.tensor(b_list, dtype=torch.long, device=device),
        torch.tensor(v_list, dtype=torch.long, device=device),
        torch.tensor(a_list, dtype=torch.long, device=device),
        torch.tensor(y_list, dtype=torch.float32, device=device),
    )


def run_site_eval(model: CrossContactNet, loader: DataLoader, device: torch.device, cfg: Config) -> dict[str, float]:
    model.eval()
    para_y: list[np.ndarray] = []
    para_s: list[np.ndarray] = []
    epi_y: list[np.ndarray] = []
    epi_s: list[np.ndarray] = []
    cont_y: list[np.ndarray] = []
    cont_s: list[np.ndarray] = []
    with torch.no_grad():
        for batch in loader:
            v = batch["vhh"].to(device)
            a = batch["antigen"].to(device)
            para = batch["paratope"].to(device)
            epi = batch["epitope"].to(device)
            hv, ha, _, _ = model.encode(v, a)
            pl, el = model.site_logits(hv, ha)
            for logits, labels, yy, ss in [(pl, para, para_y, para_s), (el, epi, epi_y, epi_s)]:
                mask = labels >= 0
                yy.append(labels[mask].detach().cpu().numpy())
                ss.append(torch.sigmoid(logits[mask]).detach().cpu().numpy())
            bi, vi, ai, cy = sample_weak_contacts(batch, cfg, device)
            if len(cy):
                cl = model.contact_logits_for_indices(hv, ha, bi, vi, ai)
                cont_y.append(cy.detach().cpu().numpy())
                cont_s.append(torch.sigmoid(cl).detach().cpu().numpy())
    out: dict[str, float] = {}
    for prefix, yy, ss in [("paratope", para_y, para_s), ("epitope", epi_y, epi_s), ("weak_contact", cont_y, cont_s)]:
        y = np.concatenate(yy) if yy else np.array([])
        s = np.concatenate(ss) if ss else np.array([])
        m = binary_metrics(y, s)
        out.update({f"{prefix}_{k}": v for k, v in m.items()})
    return out


def run_pair_eval(model: CrossContactNet, loader: DataLoader, device: torch.device) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    model.eval()
    ys: list[float] = []
    ss: list[float] = []
    types: list[str] = []
    with torch.no_grad():
        for batch in loader:
            v = batch["vhh"].to(device)
            a = batch["antigen"].to(device)
            label = batch["label"].to(device)
            hv, ha, vm, am = model.encode(v, a)
            logits = model.pair_logits(hv, ha, vm, am)
            ys.extend(label.detach().cpu().numpy().tolist())
            ss.extend(torch.sigmoid(logits).detach().cpu().numpy().tolist())
            types.extend(batch["negative_type"])
    y = np.array(ys)
    s = np.array(ss)
    overall = {f"pair_{k}": v for k, v in binary_metrics(y, s).items()}
    by_type: dict[str, dict[str, float]] = {}
    for nt in sorted(set(types)):
        idx = np.array([t == nt or t == "positive_cognate_pair" for t in types])
        if nt == "positive_cognate_pair":
            continue
        yy = y[idx]
        sc = s[idx]
        by_type[nt] = binary_metrics(yy, sc)
    return overall, by_type


def read_fasta(path: Path) -> str:
    parts = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith(">"):
            parts.append(line)
    return "".join(parts)


def score_pvrig_candidates(model: CrossContactNet, cfg: Config, device: torch.device, out_root: Path) -> pd.DataFrame:
    candidates = pd.read_csv(Path(cfg.root) / "reports/mvp_pvrig_top_candidates_v0.csv")
    pvrig = read_fasta(Path(cfg.root) / "model_data/pvrig_target_sequence_v0.fasta")
    mask_df = pd.read_csv(Path(cfg.root) / "model_data/pvrig_full_sequence_mask_v0.csv")
    target_positions = [int(i) for i, v in enumerate(mask_df["in_target_epitope"].astype(str).tolist()[: cfg.max_antigen_len]) if v == "yes"]
    rows = []
    model.eval()
    with torch.no_grad():
        for _, r in candidates.iterrows():
            seq = clean(r.get("vhh_seq"))
            v = encode_seq(seq, cfg.max_vhh_len).unsqueeze(0).to(device)
            a = encode_seq(pvrig, cfg.max_antigen_len).unsqueeze(0).to(device)
            hv, ha, vm, am = model.encode(v, a)
            pair_prob = float(torch.sigmoid(model.pair_logits(hv, ha, vm, am))[0].detach().cpu())
            _, epi_logits = model.site_logits(hv, ha)
            epi_prob = torch.sigmoid(epi_logits[0]).detach().cpu().numpy()
            target_mass = float(epi_prob[target_positions].sum()) if target_positions else 0.0
            cdr3 = clean(r.get("cdr3"))
            start = seq.find(cdr3) if cdr3 else -1
            cdr3_idx = list(range(start, min(start + len(cdr3), cfg.max_vhh_len))) if start >= 0 else list(range(max(0, len(seq) - 30), min(len(seq), cfg.max_vhh_len)))
            blocker_mass = 0.0
            if target_positions and cdr3_idx:
                cm = torch.sigmoid(model.contact_matrix(hv, ha, 0)).detach().cpu().numpy()
                blocker_mass = float(cm[np.ix_(cdr3_idx, target_positions)].mean())
            rows.append(
                {
                    "candidate_id": clean(r.get("candidate_id")),
                    "phase2_pair_binding_probability": pair_prob,
                    "phase2_pvrig_target_epitope_mass": target_mass,
                    "phase2_cdr3_hotspot_contact_mean": blocker_mass,
                    "phase1_mvp_rank_score": r.get("mvp_rank_score", ""),
                    "leakage_label": clean(r.get("leakage_label")),
                }
            )
    out = pd.DataFrame(rows)
    if not out.empty:
        for col in ["phase2_pair_binding_probability", "phase2_pvrig_target_epitope_mass", "phase2_cdr3_hotspot_contact_mean", "phase1_mvp_rank_score"]:
            vals = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
            lo, hi = vals.min(), vals.max()
            out[col + "_norm"] = 0.0 if hi - lo < 1e-12 else (vals - lo) / (hi - lo)
        out["phase2_combined_rank_score"] = (
            0.35 * out["phase2_cdr3_hotspot_contact_mean_norm"]
            + 0.25 * out["phase2_pair_binding_probability_norm"]
            + 0.20 * out["phase2_pvrig_target_epitope_mass_norm"]
            + 0.20 * out["phase1_mvp_rank_score_norm"]
        )
        out = out.sort_values("phase2_combined_rank_score", ascending=False)
    path = out_root / "predictions/pvrig_top_candidates_phase2_v1.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)
    return out


def save_report(out_root: Path, cfg: Config, history: list[dict[str, Any]], test_metrics: dict[str, Any], pvrig: pd.DataFrame, env: dict[str, Any]) -> None:
    report_path = out_root / "reports/phase2_v1_eval.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Phase 2 V1 训练评估报告",
        "",
        "Updated: 2026-07-09",
        "",
        "## 结论边界",
        "",
        "本报告对应第一版 GPU 可训练架构 `VHH-Ag CrossContactNetV1`。它已经在 RTX 5080 上完成一次 site + weak-contact + pair-binding 训练/评估。",
        "当前 contact head 使用 ZYM paratope/epitope mask 构造 weak contact proxy，不等价于真实 heavy-atom contact-map；真实结构 contact-map 训练将在 V2 接入 `prepared/structure_contact_pairs_mvp_v1.csv` 的序列映射后完成。",
        "",
        "## 环境",
        "",
        "```json",
        json.dumps(env, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 配置",
        "",
        "```json",
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
        "```",
        "",
        "## 最终 Test 指标",
        "",
        "```json",
        json.dumps(test_metrics, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## 训练历史",
        "",
        "| epoch | train_loss | val_paratope_auprc | val_epitope_auprc | val_weak_contact_auprc | val_pair_auprc | val_pair_auroc |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for h in history:
        lines.append(
            f"| {h['epoch']} | {h['train_loss']:.4f} | {h.get('val_paratope_auprc', 0):.4f} | {h.get('val_epitope_auprc', 0):.4f} | {h.get('val_weak_contact_auprc', 0):.4f} | {h.get('val_pair_auprc', 0):.4f} | {h.get('val_pair_auroc', 0):.4f} |"
        )
    lines.extend([
        "",
        "## PVRIG Top 候选 Phase2 重评分预览",
        "",
    ])
    preview_cols = ["candidate_id", "phase2_combined_rank_score", "phase2_pair_binding_probability", "phase2_pvrig_target_epitope_mass", "phase2_cdr3_hotspot_contact_mean", "phase1_mvp_rank_score"]
    if pvrig.empty:
        lines.append("(empty)")
    else:
        prev = pvrig[preview_cols].head(20)
        lines.append("| " + " | ".join(preview_cols) + " |")
        lines.append("| " + " | ".join(["---"] * len(preview_cols)) + " |")
        for _, row in prev.iterrows():
            lines.append("| " + " | ".join(str(row.get(c, "")) for c in preview_cols) + " |")
    lines.extend([
        "",
        "## 不能过度解释",
        "",
        "- 这些指标是计算训练/验证指标，不是实验 Kd/IC50。",
        "- PVRIG 候选的 Phase2 分数是进入结构预测/docking 的优先级，不是最终 blocker 证明。",
        "- hard negative 是构造负样本，不是全部实验 confirmed non-binder。",
        "",
    ])
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--d-model", type=int, default=192)
    parser.add_argument("--layers", type=int, default=3)
    parser.add_argument("--batch-size-site", type=int, default=24)
    parser.add_argument("--batch-size-pair", type=int, default=48)
    parser.add_argument("--run-name", default="")
    args = parser.parse_args()

    cfg = Config(root=str(Path(args.root).resolve()), epochs=args.epochs, d_model=args.d_model, layers=args.layers, batch_size_site=args.batch_size_site, batch_size_pair=args.batch_size_pair)
    random.seed(cfg.seed)
    np.random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.cuda.manual_seed_all(cfg.seed)
        torch.set_float32_matmul_precision("high")

    root = Path(cfg.root)
    out_root = root / cfg.out_root
    run_id = args.run_name or time.strftime("phase2_v1_%Y%m%d_%H%M%S_seed") + str(cfg.seed)
    run_dir = out_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config_resolved.json").write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")

    site_path = out_root / "data_splits/zym_site_split_manifest_v1.csv"
    pair_path = out_root / "data_splits/pair_binding_split_v1.csv"
    datasets = {
        "site_train": SiteDataset(site_path, "train", cfg),
        "site_val": SiteDataset(site_path, "val", cfg),
        "site_test": SiteDataset(site_path, "test", cfg),
        "pair_train": PairDataset(pair_path, "train", cfg),
        "pair_val": PairDataset(pair_path, "val", cfg),
        "pair_test": PairDataset(pair_path, "test", cfg),
    }
    loaders = {
        "site_train": DataLoader(datasets["site_train"], batch_size=cfg.batch_size_site, shuffle=True, collate_fn=collate_site),
        "site_val": DataLoader(datasets["site_val"], batch_size=cfg.batch_size_site, shuffle=False, collate_fn=collate_site),
        "site_test": DataLoader(datasets["site_test"], batch_size=cfg.batch_size_site, shuffle=False, collate_fn=collate_site),
        "pair_train": DataLoader(datasets["pair_train"], batch_size=cfg.batch_size_pair, shuffle=True, collate_fn=collate_pair),
        "pair_val": DataLoader(datasets["pair_val"], batch_size=cfg.batch_size_pair, shuffle=False, collate_fn=collate_pair),
        "pair_test": DataLoader(datasets["pair_test"], batch_size=cfg.batch_size_pair, shuffle=False, collate_fn=collate_pair),
    }
    model = CrossContactNet(cfg).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    scaler = torch.cuda.amp.GradScaler(enabled=(cfg.use_amp and device.type == "cuda"))

    history: list[dict[str, Any]] = []
    best_score = -1.0
    best_path = run_dir / "best_checkpoint.pt"
    pair_iter = None
    for epoch in range(1, cfg.epochs + 1):
        model.train()
        total_loss = 0.0
        steps = 0
        pair_iter = iter(loaders["pair_train"])
        for site_batch in loaders["site_train"]:
            try:
                pair_batch = next(pair_iter)
            except StopIteration:
                pair_iter = iter(loaders["pair_train"])
                pair_batch = next(pair_iter)
            opt.zero_grad(set_to_none=True)
            with torch.cuda.amp.autocast(enabled=(cfg.use_amp and device.type == "cuda")):
                v = site_batch["vhh"].to(device)
                a = site_batch["antigen"].to(device)
                para = site_batch["paratope"].to(device)
                epi = site_batch["epitope"].to(device)
                hv, ha, vm, am = model.encode(v, a)
                pl, el = model.site_logits(hv, ha)
                site_loss = bce_masked(pl, para) + bce_masked(el, epi)
                bi, vi, ai, cy = sample_weak_contacts(site_batch, cfg, device)
                if len(cy):
                    cl = model.contact_logits_for_indices(hv, ha, bi, vi, ai)
                    contact_loss = nn.functional.binary_cross_entropy_with_logits(cl, cy)
                else:
                    contact_loss = site_loss * 0.0
                pv = pair_batch["vhh"].to(device)
                pa = pair_batch["antigen"].to(device)
                py = pair_batch["label"].to(device)
                phv, pha, pvm, pam = model.encode(pv, pa)
                pair_logits = model.pair_logits(phv, pha, pvm, pam)
                pair_pos = py.sum().clamp_min(1.0)
                pair_neg = (len(py) - py.sum()).clamp_min(1.0)
                pair_loss = nn.functional.binary_cross_entropy_with_logits(pair_logits, py, pos_weight=(pair_neg / pair_pos).clamp(max=10.0))
                loss = cfg.site_loss_weight * site_loss + cfg.contact_loss_weight * contact_loss + cfg.pair_loss_weight * pair_loss
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
            total_loss += float(loss.detach().cpu())
            steps += 1
        val_site = run_site_eval(model, loaders["site_val"], device, cfg)
        val_pair, val_pair_by_type = run_pair_eval(model, loaders["pair_val"], device)
        rec = {"epoch": epoch, "train_loss": total_loss / max(steps, 1), **{f"val_{k}": v for k, v in val_site.items()}, **{f"val_{k}": v for k, v in val_pair.items()}}
        history.append(rec)
        score = rec.get("val_weak_contact_auprc", 0.0) + rec.get("val_pair_auprc", 0.0) + rec.get("val_paratope_auprc", 0.0)
        if score > best_score:
            best_score = score
            torch.save({"model": model.state_dict(), "cfg": asdict(cfg), "epoch": epoch, "best_score": best_score}, best_path)
        print(json.dumps({"epoch": epoch, "train_loss": rec["train_loss"], "val_paratope_auprc": rec.get("val_paratope_auprc"), "val_epitope_auprc": rec.get("val_epitope_auprc"), "val_weak_contact_auprc": rec.get("val_weak_contact_auprc"), "val_pair_auprc": rec.get("val_pair_auprc"), "val_pair_auroc": rec.get("val_pair_auroc")}, ensure_ascii=False))

    ckpt = torch.load(best_path, map_location=device)
    model.load_state_dict(ckpt["model"])
    test_site = run_site_eval(model, loaders["site_test"], device, cfg)
    test_pair, test_pair_by_type = run_pair_eval(model, loaders["pair_test"], device)
    val_pair, val_pair_by_type = run_pair_eval(model, loaders["pair_val"], device)
    pvrig = score_pvrig_candidates(model, cfg, device, out_root)
    env = {
        "device": str(device),
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
        "best_epoch": int(ckpt.get("epoch", -1)),
        "run_id": run_id,
    }
    test_metrics: dict[str, Any] = {
        "site_test": test_site,
        "pair_test": test_pair,
        "pair_test_by_negative_type": test_pair_by_type,
        "pair_val_by_negative_type": val_pair_by_type,
        "dataset_sizes": {k: len(v) for k, v in datasets.items()},
        "checkpoint": str(best_path),
        "pvrig_prediction_rows": int(len(pvrig)),
    }
    (run_dir / "metrics_history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "test_metrics.json").write_text(json.dumps(test_metrics, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (out_root / "reports/phase2_v1_metrics.json").write_text(json.dumps({"history": history, "test_metrics": test_metrics, "env": env}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    save_report(out_root, cfg, history, test_metrics, pvrig, env)
    print(json.dumps({"status": "PASS", "run_id": run_id, "best_epoch": env["best_epoch"], "test_metrics_path": str(run_dir / "test_metrics.json"), "report": str(out_root / "reports/phase2_v1_eval.md"), "pvrig_predictions": str(out_root / "predictions/pvrig_top_candidates_phase2_v1.csv")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
