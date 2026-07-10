#!/usr/bin/env python3
"""Train Phase 2 V2 with real heavy-atom contact maps and top-k contact pooling.

V2 improvements over V1:
- Real sequence-indexed heavy-atom contact supervision from SAbDab2 mmCIF.
- Cross-attention between VHH and antigen tokens.
- Efficient bilinear contact-map head.
- Pair binding head uses top-k contact probabilities instead of only mean pooling.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
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
        return {"n": 0.0, "positive_rate": 0.0, "auroc": 0.0, "auprc": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0}
    pred = (score >= threshold).astype(np.float64)
    tp = float(((pred == 1) & (y == 1)).sum())
    fp = float(((pred == 1) & (y == 0)).sum())
    fn = float(((pred == 0) & (y == 1)).sum())
    tn = float(((pred == 0) & (y == 0)).sum())
    precision = tp / max(tp + fp, 1e-8)
    recall = tp / max(tp + fn, 1e-8)
    f1 = 2 * precision * recall / max(precision + recall, 1e-8)
    return {"n": float(len(y)), "positive_rate": float(y.mean()), "auroc": auroc(y, score), "auprc": auprc(y, score), "precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn, "tn": tn}


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
    seed: int = 17
    d_model: int = 160
    contact_dim: int = 96
    layers: int = 2
    cross_layers: int = 1
    heads: int = 4
    dropout: float = 0.1
    max_vhh_len: int = 180
    max_antigen_len: int = 512
    batch_site: int = 24
    batch_contact: int = 12
    batch_pair: int = 24
    epochs: int = 10
    lr: float = 2e-4
    weight_decay: float = 1e-2
    contact_pos_sample: int = 64
    contact_neg_sample: int = 256
    site_weight: float = 0.6
    contact_weight: float = 2.0
    pair_weight: float = 1.0
    use_amp: bool = True


class SiteDataset(Dataset):
    def __init__(self, path: Path, split: str, cfg: Config):
        df = pd.read_csv(path)
        self.df = df[df["split"].astype(str) == split].reset_index(drop=True)
        self.cfg = cfg
    def __len__(self) -> int: return len(self.df)
    def __getitem__(self, idx: int) -> dict[str, Any]:
        r = self.df.loc[idx]
        v = encode_seq(r["vhh_seq"], self.cfg.max_vhh_len)
        a = encode_seq(r["antigen_seq"], self.cfg.max_antigen_len)
        return {"id": clean(r["sample_id"]), "vhh": v, "antigen": a, "paratope": encode_mask(r["vhh_paratope_mask"], self.cfg.max_vhh_len, len(v)), "epitope": encode_mask(r["antigen_epitope_mask"], self.cfg.max_antigen_len, len(a))}


class PairDataset(Dataset):
    def __init__(self, path: Path, split: str, cfg: Config):
        df = pd.read_csv(path)
        self.df = df[df["split"].astype(str) == split].reset_index(drop=True)
        self.cfg = cfg
    def __len__(self) -> int: return len(self.df)
    def __getitem__(self, idx: int) -> dict[str, Any]:
        r = self.df.loc[idx]
        return {"id": clean(r["pair_id"]), "negative_type": clean(r.get("negative_type", "")), "vhh": encode_seq(r["vhh_seq"], self.cfg.max_vhh_len), "antigen": encode_seq(r["antigen_seq"], self.cfg.max_antigen_len), "label": torch.tensor(float(r["binding_label"]), dtype=torch.float32)}


class ContactDataset(Dataset):
    def __init__(self, path: Path, split: str, cfg: Config):
        self.records = []
        self.cfg = cfg
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                if rec.get("split") == split:
                    self.records.append(rec)
    def __len__(self) -> int: return len(self.records)
    def __getitem__(self, idx: int) -> dict[str, Any]:
        r = self.records[idx]
        v = encode_seq(r["vhh_seq"], self.cfg.max_vhh_len)
        a = encode_seq(r["antigen_seq"], self.cfg.max_antigen_len)
        pos = [(i, j) for i, j in r["positive_pairs"] if i < len(v) and j < len(a)]
        neg = [(i, j) for i, j in r["negative_pairs"] if i < len(v) and j < len(a)]
        return {"id": r["complex_id"], "vhh": v, "antigen": a, "pos": pos, "neg": neg}


def collate_site(batch: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": [b["id"] for b in batch], "vhh": pad_sequence([b["vhh"] for b in batch], batch_first=True, padding_value=PAD_IDX), "antigen": pad_sequence([b["antigen"] for b in batch], batch_first=True, padding_value=PAD_IDX), "paratope": pad_sequence([b["paratope"] for b in batch], batch_first=True, padding_value=-1.0), "epitope": pad_sequence([b["epitope"] for b in batch], batch_first=True, padding_value=-1.0)}


def collate_pair(batch: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": [b["id"] for b in batch], "negative_type": [b["negative_type"] for b in batch], "vhh": pad_sequence([b["vhh"] for b in batch], batch_first=True, padding_value=PAD_IDX), "antigen": pad_sequence([b["antigen"] for b in batch], batch_first=True, padding_value=PAD_IDX), "label": torch.stack([b["label"] for b in batch])}


def collate_contact(batch: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": [b["id"] for b in batch], "vhh": pad_sequence([b["vhh"] for b in batch], batch_first=True, padding_value=PAD_IDX), "antigen": pad_sequence([b["antigen"] for b in batch], batch_first=True, padding_value=PAD_IDX), "pos": [b["pos"] for b in batch], "neg": [b["neg"] for b in batch]}


class CrossAttentionBlock(nn.Module):
    def __init__(self, d: int, heads: int, dropout: float):
        super().__init__()
        self.v_to_a = nn.MultiheadAttention(d, heads, dropout=dropout, batch_first=True)
        self.a_to_v = nn.MultiheadAttention(d, heads, dropout=dropout, batch_first=True)
        self.v_ln = nn.LayerNorm(d)
        self.a_ln = nn.LayerNorm(d)
        self.v_ff = nn.Sequential(nn.Linear(d, d * 4), nn.GELU(), nn.Dropout(dropout), nn.Linear(d * 4, d))
        self.a_ff = nn.Sequential(nn.Linear(d, d * 4), nn.GELU(), nn.Dropout(dropout), nn.Linear(d * 4, d))
        self.v_ln2 = nn.LayerNorm(d)
        self.a_ln2 = nn.LayerNorm(d)
    def forward(self, hv: torch.Tensor, ha: torch.Tensor, v_mask: torch.Tensor, a_mask: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        dv, _ = self.v_to_a(hv, ha, ha, key_padding_mask=a_mask, need_weights=False)
        da, _ = self.a_to_v(ha, hv, hv, key_padding_mask=v_mask, need_weights=False)
        hv = self.v_ln(hv + dv)
        ha = self.a_ln(ha + da)
        hv = self.v_ln2(hv + self.v_ff(hv))
        ha = self.a_ln2(ha + self.a_ff(ha))
        return hv, ha


class CrossContactNetV2(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        vocab = len(AA) + 2
        self.aa = nn.Embedding(vocab, cfg.d_model, padding_idx=PAD_IDX)
        self.v_pos = nn.Embedding(cfg.max_vhh_len, cfg.d_model)
        self.a_pos = nn.Embedding(cfg.max_antigen_len, cfg.d_model)
        enc = lambda: nn.TransformerEncoderLayer(cfg.d_model, cfg.heads, cfg.d_model * 4, cfg.dropout, batch_first=True, activation="gelu")
        self.v_enc = nn.TransformerEncoder(enc(), cfg.layers)
        self.a_enc = nn.TransformerEncoder(enc(), cfg.layers)
        self.cross = nn.ModuleList([CrossAttentionBlock(cfg.d_model, cfg.heads, cfg.dropout) for _ in range(cfg.cross_layers)])
        self.para = nn.Linear(cfg.d_model, 1)
        self.epi = nn.Linear(cfg.d_model, 1)
        self.q = nn.Linear(cfg.d_model, cfg.contact_dim)
        self.k = nn.Linear(cfg.d_model, cfg.contact_dim)
        self.contact_bias_v = nn.Linear(cfg.d_model, 1)
        self.contact_bias_a = nn.Linear(cfg.d_model, 1)
        pair_in = cfg.d_model * 4 + 7
        self.pair = nn.Sequential(nn.Linear(pair_in, cfg.d_model), nn.GELU(), nn.Dropout(cfg.dropout), nn.Linear(cfg.d_model, cfg.d_model // 2), nn.GELU(), nn.Linear(cfg.d_model // 2, 1))

    def encode(self, vhh: torch.Tensor, antigen: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        b, lv = vhh.shape
        _, la = antigen.shape
        v_mask = vhh.eq(PAD_IDX)
        a_mask = antigen.eq(PAD_IDX)
        vp = torch.arange(lv, device=vhh.device).unsqueeze(0).expand(b, lv).clamp(max=self.cfg.max_vhh_len - 1)
        ap = torch.arange(la, device=antigen.device).unsqueeze(0).expand(b, la).clamp(max=self.cfg.max_antigen_len - 1)
        hv = self.aa(vhh) + self.v_pos(vp)
        ha = self.aa(antigen) + self.a_pos(ap)
        hv = self.v_enc(hv, src_key_padding_mask=v_mask)
        ha = self.a_enc(ha, src_key_padding_mask=a_mask)
        for block in self.cross:
            hv, ha = block(hv, ha, v_mask, a_mask)
        return hv, ha, v_mask, a_mask

    def site_logits(self, hv: torch.Tensor, ha: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        return self.para(hv).squeeze(-1), self.epi(ha).squeeze(-1)

    def contact_logits(self, hv: torch.Tensor, ha: torch.Tensor) -> torch.Tensor:
        q = self.q(hv)
        k = self.k(ha)
        logits = torch.bmm(q, k.transpose(1, 2)) / math.sqrt(float(q.shape[-1]))
        logits = logits + self.contact_bias_v(hv) + self.contact_bias_a(ha).transpose(1, 2)
        return logits

    def pair_logits_from_encoded(self, hv: torch.Tensor, ha: torch.Tensor, v_mask: torch.Tensor, a_mask: torch.Tensor) -> torch.Tensor:
        v_valid = (~v_mask).float().unsqueeze(-1)
        a_valid = (~a_mask).float().unsqueeze(-1)
        vp = (hv * v_valid).sum(1) / v_valid.sum(1).clamp_min(1.0)
        ap = (ha * a_valid).sum(1) / a_valid.sum(1).clamp_min(1.0)
        cm = self.contact_logits(hv, ha)
        valid_pair = (~v_mask).unsqueeze(2) & (~a_mask).unsqueeze(1)
        probs = torch.sigmoid(cm).masked_fill(~valid_pair, 0.0)
        flat = probs.masked_fill(~valid_pair, -1.0).flatten(1)
        k = min(50, flat.shape[1])
        top = torch.topk(flat, k=k, dim=1).values.clamp_min(0.0)
        top1 = top[:, :1].mean(1, keepdim=True)
        top5 = top[:, : min(5, k)].mean(1, keepdim=True)
        top20 = top[:, : min(20, k)].mean(1, keepdim=True)
        mean_all = probs.sum((1, 2), keepdim=False).unsqueeze(1) / valid_pair.float().sum((1, 2), keepdim=False).clamp_min(1.0).unsqueeze(1)
        lv = (~v_mask).sum(1).clamp_min(1)
        cdr3_stats = []
        for b in range(hv.shape[0]):
            start = max(0, int(lv[b].item()) - 30)
            sub = probs[b, start:int(lv[b].item())]
            cdr3_stats.append(sub.max().reshape(1) if sub.numel() else torch.zeros(1, device=hv.device))
        cdr3_max = torch.stack(cdr3_stats, dim=0)
        entropy = -(probs.clamp_min(1e-6) * probs.clamp_min(1e-6).log()).sum((1, 2), keepdim=False).unsqueeze(1) / valid_pair.float().sum((1, 2), keepdim=False).clamp_min(1.0).unsqueeze(1)
        feat = torch.cat([vp, ap, torch.abs(vp - ap), vp * ap, top1, top5, top20, mean_all, cdr3_max, entropy, (top1 - mean_all)], dim=-1)
        return self.pair(feat).squeeze(-1)


def bce_masked(logits: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    mask = labels >= 0
    if mask.sum() == 0:
        return logits.sum() * 0.0
    y = labels[mask]
    x = logits[mask]
    pos = y.sum().clamp_min(1.0)
    neg = (len(y) - y.sum()).clamp_min(1.0)
    return nn.functional.binary_cross_entropy_with_logits(x, y, pos_weight=(neg / pos).clamp(max=25.0))


def sample_contact_indices(batch: dict[str, Any], cfg: Config, device: torch.device) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    rng = random.Random(random.randint(0, 10**9))
    bi: list[int] = []
    vi: list[int] = []
    ai: list[int] = []
    yy: list[float] = []
    for b, (pos, neg) in enumerate(zip(batch["pos"], batch["neg"])):
        pos_s = pos if len(pos) <= cfg.contact_pos_sample else rng.sample(pos, cfg.contact_pos_sample)
        neg_s = neg if len(neg) <= cfg.contact_neg_sample else rng.sample(neg, cfg.contact_neg_sample)
        for i, j in pos_s:
            bi.append(b); vi.append(i); ai.append(j); yy.append(1.0)
        for i, j in neg_s:
            bi.append(b); vi.append(i); ai.append(j); yy.append(0.0)
    if not yy:
        z = torch.zeros(0, dtype=torch.long, device=device)
        return z, z, z, torch.zeros(0, dtype=torch.float32, device=device)
    return torch.tensor(bi, dtype=torch.long, device=device), torch.tensor(vi, dtype=torch.long, device=device), torch.tensor(ai, dtype=torch.long, device=device), torch.tensor(yy, dtype=torch.float32, device=device)


def contact_loss(model: CrossContactNetV2, hv: torch.Tensor, ha: torch.Tensor, batch: dict[str, Any], cfg: Config, device: torch.device) -> torch.Tensor:
    cm = model.contact_logits(hv, ha)
    bi, vi, ai, yy = sample_contact_indices(batch, cfg, device)
    if len(yy) == 0:
        return cm.sum() * 0.0
    logits = cm[bi, vi, ai]
    pos = yy.sum().clamp_min(1.0)
    neg = (len(yy) - yy.sum()).clamp_min(1.0)
    return nn.functional.binary_cross_entropy_with_logits(logits, yy, pos_weight=(neg / pos).clamp(max=20.0))


def eval_site(model: CrossContactNetV2, loader: DataLoader, device: torch.device) -> dict[str, float]:
    model.eval(); py=[]; ps=[]; ey=[]; es=[]
    with torch.no_grad():
        for b in loader:
            v=b["vhh"].to(device); a=b["antigen"].to(device); para=b["paratope"].to(device); epi=b["epitope"].to(device)
            hv,ha,_,_=model.encode(v,a); pl,el=model.site_logits(hv,ha)
            for logits, labels, yy, ss in [(pl,para,py,ps),(el,epi,ey,es)]:
                m=labels>=0; yy.append(labels[m].cpu().numpy()); ss.append(torch.sigmoid(logits[m]).cpu().numpy())
    out={}
    for pref, yy, ss in [("paratope",py,ps),("epitope",ey,es)]:
        m=binary_metrics(np.concatenate(yy), np.concatenate(ss)) if yy else binary_metrics(np.array([]),np.array([]))
        out.update({f"{pref}_{k}":v for k,v in m.items()})
    return out


def eval_contact(model: CrossContactNetV2, loader: DataLoader, device: torch.device, cfg: Config) -> dict[str, float]:
    model.eval(); ys=[]; ss=[]; p_at=[]
    with torch.no_grad():
        for b in loader:
            v=b["vhh"].to(device); a=b["antigen"].to(device)
            hv,ha,_,_=model.encode(v,a); cm=torch.sigmoid(model.contact_logits(hv,ha))
            bi,vi,ai,yy=sample_contact_indices(b,cfg,device)
            if len(yy):
                ys.append(yy.cpu().numpy()); ss.append(cm[bi,vi,ai].cpu().numpy())
            for idx,pos in enumerate(b["pos"]):
                if not pos: continue
                mat=cm[idx,:len(b["vhh"][idx].nonzero()),:len(b["antigen"][idx].nonzero())].flatten()
                k=min(max(1,len(pos)), 50, mat.numel())
                top=torch.topk(mat,k=k).indices.cpu().numpy().tolist()
                la=int((b["antigen"][idx]!=PAD_IDX).sum())
                pred={(t//la,t%la) for t in top}
                truth={tuple(x) for x in pos}
                p_at.append(len(pred & truth)/max(len(pred),1))
    m=binary_metrics(np.concatenate(ys), np.concatenate(ss)) if ys else binary_metrics(np.array([]),np.array([]))
    return {f"contact_{k}":v for k,v in m.items()} | {"contact_precision_at_poscount_or_50": float(np.mean(p_at)) if p_at else 0.0}


def eval_pair(model: CrossContactNetV2, loader: DataLoader, device: torch.device) -> tuple[dict[str,float], dict[str,dict[str,float]]]:
    model.eval(); ys=[]; ss=[]; nts=[]
    with torch.no_grad():
        for b in loader:
            v=b["vhh"].to(device); a=b["antigen"].to(device); y=b["label"].to(device)
            hv,ha,vm,am=model.encode(v,a); logits=model.pair_logits_from_encoded(hv,ha,vm,am)
            ys.extend(y.cpu().numpy().tolist()); ss.extend(torch.sigmoid(logits).cpu().numpy().tolist()); nts.extend(b["negative_type"])
    y=np.array(ys); s=np.array(ss); overall={f"pair_{k}":v for k,v in binary_metrics(y,s).items()}
    by={}
    for nt in sorted(set(nts)):
        if nt=="positive_cognate_pair": continue
        idx=np.array([t==nt or t=="positive_cognate_pair" for t in nts])
        by[nt]=binary_metrics(y[idx],s[idx])
    return overall,by


def read_fasta(path: Path) -> str:
    return "".join(line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip() and not line.startswith(">"))


def score_pvrig(model: CrossContactNetV2, cfg: Config, device: torch.device, out_root: Path, variant: str) -> pd.DataFrame:
    cand=pd.read_csv(Path(cfg.root)/"reports/mvp_pvrig_top_candidates_v0.csv")
    pvrig=read_fasta(Path(cfg.root)/"model_data/pvrig_target_sequence_v0.fasta")
    mask=pd.read_csv(Path(cfg.root)/"model_data/pvrig_full_sequence_mask_v0.csv")
    target=[i for i,v in enumerate(mask["in_target_epitope"].astype(str).tolist()[:cfg.max_antigen_len]) if v=="yes"]
    rows=[]; model.eval()
    with torch.no_grad():
        for _,r in cand.iterrows():
            seq=clean(r.get("vhh_seq")); cdr3=clean(r.get("cdr3")); start=seq.find(cdr3) if cdr3 else -1
            v=encode_seq(seq,cfg.max_vhh_len).unsqueeze(0).to(device); a=encode_seq(pvrig,cfg.max_antigen_len).unsqueeze(0).to(device)
            hv,ha,vm,am=model.encode(v,a); pair=float(torch.sigmoid(model.pair_logits_from_encoded(hv,ha,vm,am))[0].cpu())
            _,el=model.site_logits(hv,ha); epi=torch.sigmoid(el[0]).cpu().numpy(); target_mass=float(epi[target].sum()) if target else 0.0
            cm=torch.sigmoid(model.contact_logits(hv,ha))[0].cpu().numpy()
            if start>=0: cdr_idx=list(range(start,min(start+len(cdr3),cm.shape[0])))
            else: cdr_idx=list(range(max(0,len(seq)-30),min(len(seq),cm.shape[0])))
            hot=float(cm[np.ix_(cdr_idx,target)].mean()) if cdr_idx and target else 0.0
            rows.append({"candidate_id":clean(r.get("candidate_id")),"phase2_v2_pair_binding_probability":pair,"phase2_v2_pvrig_target_epitope_mass":target_mass,"phase2_v2_cdr3_hotspot_contact_mean":hot,"phase1_mvp_rank_score":r.get("mvp_rank_score",0),"leakage_label":clean(r.get("leakage_label"))})
    out=pd.DataFrame(rows)
    if not out.empty:
        for col in ["phase2_v2_pair_binding_probability","phase2_v2_pvrig_target_epitope_mass","phase2_v2_cdr3_hotspot_contact_mean","phase1_mvp_rank_score"]:
            vals=pd.to_numeric(out[col], errors="coerce").fillna(0.0); lo,hi=vals.min(),vals.max(); out[col+"_norm"]=0.0 if hi-lo<1e-12 else (vals-lo)/(hi-lo)
        out["phase2_v2_combined_rank_score"]=0.35*out["phase2_v2_cdr3_hotspot_contact_mean_norm"]+0.25*out["phase2_v2_pair_binding_probability_norm"]+0.20*out["phase2_v2_pvrig_target_epitope_mass_norm"]+0.20*out["phase1_mvp_rank_score_norm"]
        out=out.sort_values("phase2_v2_combined_rank_score", ascending=False)
    path=out_root/f"predictions/pvrig_top_candidates_{variant}.csv"; path.parent.mkdir(parents=True,exist_ok=True); out.to_csv(path,index=False,quoting=csv.QUOTE_MINIMAL)
    return out


def save_report(out_root: Path, cfg: Config, history: list[dict[str,Any]], metrics: dict[str,Any], pvrig: pd.DataFrame, env: dict[str,Any], variant: str) -> None:
    comp_path=out_root/"reports/phase2_v1_phase1_comparison.json"
    phase1_comp=json.loads(comp_path.read_text()) if comp_path.exists() else {}
    lines=[f"# Phase 2 {variant} 真实结构 Contact-map 训练评估报告","","Updated: 2026-07-09","","## 结论","", "V2 已接入真实 SAbDab2 heavy-atom contact-map 监督；contact labels 来自同一复合物 residue pair 距离 <=4.5 A，负样本来自 >=8.0 A。pair head 使用 top-k contact pooling。","", "## 环境","","```json",json.dumps(env,ensure_ascii=False,indent=2),"```","", "## 配置","","```json",json.dumps(asdict(cfg),ensure_ascii=False,indent=2),"```","", "## Test 指标","","```json",json.dumps(metrics,ensure_ascii=False,indent=2,sort_keys=True),"```","", "## 与 V1 / Phase1 对照","","```json",json.dumps({"phase1_v1_reference":phase1_comp,"v2_paratope_auprc":metrics["site_test"].get("paratope_auprc"),"v2_epitope_auprc":metrics["site_test"].get("epitope_auprc"),"v2_real_contact_auprc":metrics["contact_test"].get("contact_auprc"),"v2_pair_auroc":metrics["pair_test"].get("pair_auroc"),"v2_pair_auprc":metrics["pair_test"].get("pair_auprc")},ensure_ascii=False,indent=2),"```","", "## 训练历史","","| epoch | train_loss | val_contact_auprc | val_contact_auroc | val_pair_auprc | val_pair_auroc | val_paratope_auprc | val_epitope_auprc |","| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for h in history:
        lines.append(f"| {h['epoch']} | {h['train_loss']:.4f} | {h.get('val_contact_auprc',0):.4f} | {h.get('val_contact_auroc',0):.4f} | {h.get('val_pair_auprc',0):.4f} | {h.get('val_pair_auroc',0):.4f} | {h.get('val_paratope_auprc',0):.4f} | {h.get('val_epitope_auprc',0):.4f} |")
    lines += ["", "## PVRIG V2 Top 预览", ""]
    cols=["candidate_id","phase2_v2_combined_rank_score","phase2_v2_pair_binding_probability","phase2_v2_pvrig_target_epitope_mass","phase2_v2_cdr3_hotspot_contact_mean","phase1_mvp_rank_score"]
    if pvrig.empty: lines.append("(empty)")
    else:
        lines.append("| "+" | ".join(cols)+" |"); lines.append("| "+" | ".join(["---"]*len(cols))+" |")
        for _,r in pvrig[cols].head(20).iterrows(): lines.append("| "+" | ".join(str(r.get(c,"")) for c in cols)+" |")
    lines += ["", "## 边界", "", "- V2 已经是真实 heavy-atom contact-map 训练，但仍不是实验 Kd/IC50 或细胞阻断证明。", "- Pair negatives 仍是 constructed negatives；hard-negative 分项必须单独看。", "- PVRIG 分数是 docking 前优先级，不是最终 blocker 判定。", ""]
    path=out_root/f"reports/{variant}_eval.md"; path.parent.mkdir(parents=True,exist_ok=True); path.write_text("\n".join(lines),encoding="utf-8")


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root",default="."); ap.add_argument("--epochs",type=int,default=10); ap.add_argument("--d-model",type=int,default=160); ap.add_argument("--layers",type=int,default=2); ap.add_argument("--run-name",default=""); ap.add_argument("--variant",default="phase2_v2"); ap.add_argument("--contact-jsonl",default=""); ap.add_argument("--contact-weight",type=float,default=None); ap.add_argument("--site-weight",type=float,default=None); ap.add_argument("--pair-weight",type=float,default=None)
    args=ap.parse_args(); cfg=Config(root=str(Path(args.root).resolve()),epochs=args.epochs,d_model=args.d_model,layers=args.layers)
    if args.contact_weight is not None: cfg.contact_weight=args.contact_weight
    if args.site_weight is not None: cfg.site_weight=args.site_weight
    if args.pair_weight is not None: cfg.pair_weight=args.pair_weight
    random.seed(cfg.seed); np.random.seed(cfg.seed); torch.manual_seed(cfg.seed)
    device=torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type=="cuda": torch.cuda.manual_seed_all(cfg.seed); torch.set_float32_matmul_precision("high")
    root=Path(cfg.root); out_root=root/cfg.out_root; run_id=args.run_name or time.strftime("phase2_v2_%Y%m%d_%H%M%S_seed")+str(cfg.seed); run_dir=out_root/"runs"/run_id; run_dir.mkdir(parents=True,exist_ok=True)
    (run_dir/"config_resolved.json").write_text(json.dumps(asdict(cfg),ensure_ascii=False,indent=2),encoding="utf-8")
    site_path=out_root/"data_splits/zym_site_split_manifest_v1.csv"; pair_path=out_root/"data_splits/pair_binding_split_v1.csv"; contact_path=Path(args.contact_jsonl) if args.contact_jsonl else out_root/"prepared/structure_contact_maps_v2.jsonl"
    ds={
        "site_train":SiteDataset(site_path,"train",cfg),"site_val":SiteDataset(site_path,"val",cfg),"site_test":SiteDataset(site_path,"test",cfg),
        "pair_train":PairDataset(pair_path,"train",cfg),"pair_val":PairDataset(pair_path,"val",cfg),"pair_test":PairDataset(pair_path,"test",cfg),
        "contact_train":ContactDataset(contact_path,"train",cfg),"contact_val":ContactDataset(contact_path,"val",cfg),"contact_test":ContactDataset(contact_path,"test",cfg)}
    ld={
        "site_train":DataLoader(ds["site_train"],batch_size=cfg.batch_site,shuffle=True,collate_fn=collate_site),"site_val":DataLoader(ds["site_val"],batch_size=cfg.batch_site,shuffle=False,collate_fn=collate_site),"site_test":DataLoader(ds["site_test"],batch_size=cfg.batch_site,shuffle=False,collate_fn=collate_site),
        "pair_train":DataLoader(ds["pair_train"],batch_size=cfg.batch_pair,shuffle=True,collate_fn=collate_pair),"pair_val":DataLoader(ds["pair_val"],batch_size=cfg.batch_pair,shuffle=False,collate_fn=collate_pair),"pair_test":DataLoader(ds["pair_test"],batch_size=cfg.batch_pair,shuffle=False,collate_fn=collate_pair),
        "contact_train":DataLoader(ds["contact_train"],batch_size=cfg.batch_contact,shuffle=True,collate_fn=collate_contact),"contact_val":DataLoader(ds["contact_val"],batch_size=cfg.batch_contact,shuffle=False,collate_fn=collate_contact),"contact_test":DataLoader(ds["contact_test"],batch_size=cfg.batch_contact,shuffle=False,collate_fn=collate_contact)}
    model=CrossContactNetV2(cfg).to(device); opt=torch.optim.AdamW(model.parameters(),lr=cfg.lr,weight_decay=cfg.weight_decay); scaler=torch.cuda.amp.GradScaler(enabled=(cfg.use_amp and device.type=="cuda"))
    best=-1; best_path=run_dir/"best_checkpoint.pt"; history=[]
    for epoch in range(1,cfg.epochs+1):
        model.train(); total=0; steps=0; site_it=iter(ld["site_train"]); pair_it=iter(ld["pair_train"])
        for cb in ld["contact_train"]:
            try: sb=next(site_it)
            except StopIteration: site_it=iter(ld["site_train"]); sb=next(site_it)
            try: pb=next(pair_it)
            except StopIteration: pair_it=iter(ld["pair_train"]); pb=next(pair_it)
            opt.zero_grad(set_to_none=True)
            with torch.cuda.amp.autocast(enabled=(cfg.use_amp and device.type=="cuda")):
                cv=cb["vhh"].to(device); ca=cb["antigen"].to(device); chv,cha,_,_=model.encode(cv,ca); c_loss=contact_loss(model,chv,cha,cb,cfg,device)
                sv=sb["vhh"].to(device); sa=sb["antigen"].to(device); para=sb["paratope"].to(device); epi=sb["epitope"].to(device); shv,sha,_,_=model.encode(sv,sa); pl,el=model.site_logits(shv,sha); s_loss=bce_masked(pl,para)+bce_masked(el,epi)
                pv=pb["vhh"].to(device); pa=pb["antigen"].to(device); py=pb["label"].to(device); phv,pha,pvm,pam=model.encode(pv,pa); p_logits=model.pair_logits_from_encoded(phv,pha,pvm,pam); pos=py.sum().clamp_min(1); neg=(len(py)-py.sum()).clamp_min(1); p_loss=nn.functional.binary_cross_entropy_with_logits(p_logits,py,pos_weight=(neg/pos).clamp(max=10))
                loss=cfg.contact_weight*c_loss+cfg.site_weight*s_loss+cfg.pair_weight*p_loss
            scaler.scale(loss).backward(); scaler.unscale_(opt); torch.nn.utils.clip_grad_norm_(model.parameters(),1.0); scaler.step(opt); scaler.update(); total+=float(loss.detach().cpu()); steps+=1
        val_contact=eval_contact(model,ld["contact_val"],device,cfg); val_site=eval_site(model,ld["site_val"],device); val_pair,val_pair_by=eval_pair(model,ld["pair_val"],device)
        rec={"epoch":epoch,"train_loss":total/max(steps,1),**{f"val_{k}":v for k,v in val_contact.items()},**{f"val_{k}":v for k,v in val_site.items()},**{f"val_{k}":v for k,v in val_pair.items()}}
        history.append(rec); score=rec.get("val_contact_auprc",0)+rec.get("val_pair_auprc",0)+0.3*rec.get("val_paratope_auprc",0)
        if score>best: best=score; torch.save({"model":model.state_dict(),"cfg":asdict(cfg),"epoch":epoch,"best_score":best},best_path)
        print(json.dumps({"epoch":epoch,"train_loss":rec["train_loss"],"val_contact_auprc":rec.get("val_contact_auprc"),"val_contact_auroc":rec.get("val_contact_auroc"),"val_pair_auprc":rec.get("val_pair_auprc"),"val_pair_auroc":rec.get("val_pair_auroc"),"val_paratope_auprc":rec.get("val_paratope_auprc"),"val_epitope_auprc":rec.get("val_epitope_auprc")},ensure_ascii=False))
    ckpt=torch.load(best_path,map_location=device); model.load_state_dict(ckpt["model"])
    test_contact=eval_contact(model,ld["contact_test"],device,cfg); test_site=eval_site(model,ld["site_test"],device); test_pair,test_pair_by=eval_pair(model,ld["pair_test"],device); val_pair,val_pair_by=eval_pair(model,ld["pair_val"],device); pvrig=score_pvrig(model,cfg,device,out_root,args.variant)
    env={"device":str(device),"torch":torch.__version__,"cuda_available":torch.cuda.is_available(),"cuda_version":torch.version.cuda,"gpu_name":torch.cuda.get_device_name(0) if torch.cuda.is_available() else "","best_epoch":int(ckpt.get("epoch",-1)),"run_id":run_id}
    metrics={"dataset_sizes":{k:len(v) for k,v in ds.items()},"checkpoint":str(best_path),"contact_test":test_contact,"site_test":test_site,"pair_test":test_pair,"pair_test_by_negative_type":test_pair_by,"pair_val_by_negative_type":val_pair_by,"pvrig_prediction_rows":int(len(pvrig))}
    (run_dir/"metrics_history.json").write_text(json.dumps(history,ensure_ascii=False,indent=2),encoding="utf-8"); (run_dir/"test_metrics.json").write_text(json.dumps(metrics,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8"); (out_root/f"reports/{args.variant}_metrics.json").write_text(json.dumps({"history":history,"test_metrics":metrics,"env":env},ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8"); save_report(out_root,cfg,history,metrics,pvrig,env,args.variant); torch.save(ckpt,out_root/f"checkpoints/{args.variant}_best_checkpoint.pt")
    print(json.dumps({"status":"PASS","run_id":run_id,"best_epoch":env["best_epoch"],"report":str(out_root/f"reports/{args.variant}_eval.md"),"metrics":str(run_dir/"test_metrics.json"),"pvrig_predictions":str(out_root/f"predictions/pvrig_top_candidates_{args.variant}.csv")},ensure_ascii=False,indent=2))


if __name__=="__main__": main()
