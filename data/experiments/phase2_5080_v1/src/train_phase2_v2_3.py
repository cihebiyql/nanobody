#!/usr/bin/env python3
"""Train Phase 2 V2.3 from strict manifests and frozen cached ESM2 embeddings.

V2.3 keeps the V2 contact/site supervision, makes every data artifact an
explicit CLI/config input, and moves pair supervision to observed-positive-only
auxiliary BCE plus pairwise ranking over constructed triplets.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.nn.utils.rnn import pad_sequence
from torch.utils.data import DataLoader, Dataset

PAD_CDR = 0
REQUIRED_INPUTS = (
    "clustered_site_csv",
    "pair_csv",
    "ranking_triplets_csv",
    "contact_jsonl",
    "esm2_cache_manifest",
    "cdr_mask_csv",
)


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


def seq_hash(seq: str) -> str:
    return hashlib.sha256(clean(seq).upper().encode("utf-8")).hexdigest()


def parse_json_list(raw: Any, expected_len: int | None = None) -> list[int]:
    values = json.loads(clean(raw))
    if not isinstance(values, list):
        raise ValueError("CDR mask must decode to a JSON list")
    out = [int(v) for v in values]
    if expected_len is not None and len(out) != expected_len:
        raise ValueError(f"CDR mask length {len(out)} != sequence length {expected_len}")
    if any(v < 0 or v > 3 for v in out):
        raise ValueError("CDR mask values must be 0, 1, 2, or 3")
    return out


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


def ranking_metrics(groups: dict[str, list[tuple[float, int, str]]], hard_prefixes: tuple[str, ...] = ("N2", "hard")) -> dict[str, float]:
    rr: list[float] = []
    hits = {1: [], 5: [], 10: []}
    ndcg10: list[float] = []
    hard_wins: list[float] = []
    for rows in groups.values():
        if not rows or not any(label == 1 for _, label, _ in rows):
            continue
        ordered = sorted(rows, key=lambda item: item[0], reverse=True)
        labels = [label for _, label, _ in ordered]
        pos_rank = labels.index(1) + 1
        rr.append(1.0 / pos_rank)
        for k in hits:
            hits[k].append(1.0 if pos_rank <= k else 0.0)
        dcg = sum((2**label - 1) / math.log2(idx + 2) for idx, label in enumerate(labels[:10]))
        ideal = sorted(labels, reverse=True)
        idcg = sum((2**label - 1) / math.log2(idx + 2) for idx, label in enumerate(ideal[:10]))
        ndcg10.append(dcg / idcg if idcg > 0 else 0.0)
        pos_score = next(score for score, label, _ in rows if label == 1)
        hard = [score for score, label, nt in rows if label == 0 and any(clean(nt).lower().startswith(p.lower()) or p.lower() in clean(nt).lower() for p in hard_prefixes)]
        if hard:
            hard_wins.extend([1.0 if pos_score > score else 0.0 for score in hard])
    return {
        "ranking_groups": float(len(rr)),
        "ranking_mrr": float(np.mean(rr)) if rr else 0.0,
        "ranking_hit_at_1": float(np.mean(hits[1])) if hits[1] else 0.0,
        "ranking_hit_at_5": float(np.mean(hits[5])) if hits[5] else 0.0,
        "ranking_hit_at_10": float(np.mean(hits[10])) if hits[10] else 0.0,
        "ranking_ndcg_at_10": float(np.mean(ndcg10)) if ndcg10 else 0.0,
        "ranking_hard_negative_win_rate": float(np.mean(hard_wins)) if hard_wins else 0.0,
    }


@dataclass
class Config:
    root: str = "."
    out_root: str = "experiments/phase2_5080_v1"
    clustered_site_csv: str = ""
    pair_csv: str = ""
    ranking_triplets_csv: str = ""
    contact_jsonl: str = ""
    esm2_cache_manifest: str = ""
    cdr_mask_csv: str = ""
    seed: int = 43
    d_model: int = 160
    esm_dim: int = 320
    contact_dim: int = 96
    layers: int = 2
    cross_layers: int = 1
    heads: int = 4
    dropout: float = 0.1
    max_vhh_len: int = 180
    max_antigen_len: int = 768
    batch_site: int = 24
    batch_contact: int = 12
    batch_pair: int = 24
    batch_rank: int = 12
    epochs: int = 8
    lr: float = 2e-4
    weight_decay: float = 1e-2
    grad_accum_steps: int = 1
    contact_pos_sample: int = 64
    contact_neg_sample: int = 256
    site_weight: float = 0.6
    contact_weight: float = 2.0
    pair_bce_weight: float = 0.15
    ranking_weight: float = 1.0
    ranking_margin: float = 0.25
    selection_contact_weight: float = 1.0
    selection_ranking_weight: float = 1.0
    selection_paratope_weight: float = 0.3
    use_amp: bool = True
    num_workers: int = 0
    exclude_unresolved_cdr_pair_tasks: bool = True
    eval_contact_seed: int = 1729
    log_every_steps: int = 10


class ESM2Cache:
    def __init__(self, manifest_path: Path, expected_dim: int):
        if not manifest_path.exists():
            raise FileNotFoundError(f"Missing ESM2 cache manifest: {manifest_path}")
        self.manifest_path = manifest_path
        self.expected_dim = expected_dim
        self.rows: dict[str, dict[str, str]] = {}
        with manifest_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            required = {"sequence_sha256", "sequence_length", "shard_path", "shard_key"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"ESM2 cache manifest missing columns: {sorted(missing)}")
            for row in reader:
                self.rows[row["sequence_sha256"]] = row
        self._shards: dict[Path, dict[str, torch.Tensor]] = {}

    def has(self, sequence: str) -> bool:
        return seq_hash(sequence) in self.rows

    def cached_length_for(self, row: dict[str, str]) -> int:
        original_len = int(row["sequence_length"])
        cached_raw = clean(row.get("cached_length"))
        cached_len = int(cached_raw) if cached_raw else original_len
        if cached_len <= 0 or cached_len > original_len:
            raise ValueError(f"Invalid cached_length={cached_len} for original sequence_length={original_len}")
        policy = clean(row.get("truncation_policy")) or "full_length"
        if cached_len < original_len and policy in {"", "full_length", "none"}:
            raise ValueError(
                f"ESM2 cache row {row['sequence_sha256']} is prefix-truncated "
                f"({cached_len}/{original_len}) but truncation_policy={policy!r}"
            )
        return cached_len

    def get(self, sequence: str, max_len: int) -> torch.Tensor:
        # Lookup uses the full cleaned sequence hash even when only a prefix was cached.
        digest = seq_hash(sequence)
        row = self.rows.get(digest)
        if row is None:
            raise KeyError(f"Missing ESM2 cache row for sequence hash {digest}")
        shard_path = (self.manifest_path.parent / row["shard_path"]).resolve()
        if not shard_path.exists():
            raise FileNotFoundError(f"Missing ESM2 shard for {digest}: {shard_path}")
        if shard_path not in self._shards:
            payload = torch.load(shard_path, map_location="cpu", weights_only=False)
            # Convert each shard once instead of repeatedly expanding fp16 tensors
            # on every dataset access throughout all epochs.
            self._shards[shard_path] = {key: value.detach().float() for key, value in payload.items()}
        tensor = self._shards[shard_path][row.get("shard_key") or digest]
        if tensor.ndim != 2 or tensor.shape[1] != self.expected_dim:
            raise ValueError(f"ESM2 embedding for {digest} has shape {tuple(tensor.shape)}, expected (*,{self.expected_dim})")
        cached_len = self.cached_length_for(row)
        if tensor.shape[0] != cached_len:
            raise ValueError(f"ESM2 cached-prefix length mismatch for {digest}: tensor={tensor.shape[0]} manifest={cached_len}")
        return tensor[: min(max_len, cached_len)].contiguous()


class CDRMaskStore:
    def __init__(self, path: Path):
        if not path.exists():
            raise FileNotFoundError(f"Missing CDR mask CSV: {path}")
        self.rows: dict[str, list[int]] = {}
        self.statuses: dict[str, str] = {}
        df = pd.read_csv(path)
        required = {"sequence_hash", "vhh_len", "cdr_mask_json"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"CDR mask CSV missing columns: {sorted(missing)}")
        if "status" in df.columns:
            allowed = {"exact_annotation", "heuristic_fallback", "unresolved", "ok"}
            bad = df[~df["status"].astype(str).isin(allowed)]
            if len(bad):
                raise ValueError(f"CDR mask CSV contains unsupported status rows; first={bad.iloc[0]['sequence_hash']}")
        for _, row in df.iterrows():
            # Unresolved rows are explicit all-framework masks; use cdr_mask_json as provided.
            digest = clean(row["sequence_hash"])
            self.rows[digest] = parse_json_list(row["cdr_mask_json"], int(row["vhh_len"]))
            self.statuses[digest] = clean(row.get("status")) or "unknown"

    def has(self, sequence: str) -> bool:
        return seq_hash(sequence) in self.rows

    def get(self, sequence: str, max_len: int) -> torch.Tensor:
        digest = seq_hash(sequence)
        if digest not in self.rows:
            raise KeyError(f"Missing CDR mask for VHH sequence hash {digest}")
        return torch.tensor(self.rows[digest][:max_len], dtype=torch.long)

    def has_cdr3(self, sequence: str) -> bool:
        values = self.rows.get(seq_hash(sequence), [])
        return 3 in values and self.statuses.get(seq_hash(sequence), "") != "unresolved"

    def status_for(self, sequence: str) -> str:
        return self.statuses.get(seq_hash(sequence), "missing")


def mask_from_string(mask: str, target_len: int) -> torch.Tensor:
    vals = [1.0 if ch == "1" else 0.0 for ch in clean(mask)[:target_len]]
    if len(vals) < target_len:
        vals.extend([0.0] * (target_len - len(vals)))
    return torch.tensor(vals[:target_len], dtype=torch.float32)


class FeatureMixin:
    def __init__(self, cfg: Config, cache: ESM2Cache, cdrs: CDRMaskStore):
        self.cfg = cfg
        self.cache = cache
        self.cdrs = cdrs

    def vhh_features(self, seq: str) -> tuple[torch.Tensor, torch.Tensor]:
        emb = self.cache.get(seq, self.cfg.max_vhh_len)
        cdr = self.cdrs.get(seq, self.cfg.max_vhh_len)
        if cdr.shape[0] != emb.shape[0]:
            cdr = cdr[: emb.shape[0]]
        return emb, cdr

    def antigen_features(self, seq: str) -> torch.Tensor:
        return self.cache.get(seq, self.cfg.max_antigen_len)


class SiteDataset(Dataset, FeatureMixin):
    def __init__(self, path: Path, split: str, cfg: Config, cache: ESM2Cache, cdrs: CDRMaskStore):
        FeatureMixin.__init__(self, cfg, cache, cdrs)
        df = pd.read_csv(path)
        self.df = df[df["split"].astype(str) == split].reset_index(drop=True)
    def __len__(self) -> int: return len(self.df)
    def __getitem__(self, idx: int) -> dict[str, Any]:
        r = self.df.loc[idx]
        v, cdr = self.vhh_features(r["vhh_seq"])
        a = self.antigen_features(r["antigen_seq"])
        return {"id": clean(r["sample_id"]), "vhh": v, "vhh_cdr": cdr, "antigen": a, "paratope": mask_from_string(r["vhh_paratope_mask"], len(v)), "epitope": mask_from_string(r["antigen_epitope_mask"], len(a))}


class PairDataset(Dataset, FeatureMixin):
    def __init__(self, path: Path, split: str, cfg: Config, cache: ESM2Cache, cdrs: CDRMaskStore):
        FeatureMixin.__init__(self, cfg, cache, cdrs)
        df = pd.read_csv(path)
        self.df = df[df["split"].astype(str) == split].reset_index(drop=True)
        self.excluded_unresolved_cdr_rows = 0
        if cfg.exclude_unresolved_cdr_pair_tasks:
            keep = self.df["vhh_seq"].map(cdrs.has_cdr3)
            self.excluded_unresolved_cdr_rows = int((~keep).sum())
            self.df = self.df[keep].reset_index(drop=True)
    def __len__(self) -> int: return len(self.df)
    def __getitem__(self, idx: int) -> dict[str, Any]:
        r = self.df.loc[idx]
        v, cdr = self.vhh_features(r["vhh_seq"])
        label_state = clean(r.get("label_state", ""))
        ordinary = clean(r.get("ordinary_bce_eligible", "")).lower() == "yes"
        binding_raw = clean(r.get("binding_label"))
        binding_label = float(binding_raw) if binding_raw else -1.0
        bce_observed = bool(label_state == "observed_positive" and binding_label == 1.0 and ordinary)
        return {
            "id": clean(r["pair_id"]),
            "negative_type": clean(r.get("negative_type", "")),
            "vhh": v,
            "vhh_cdr": cdr,
            "antigen": self.antigen_features(r["antigen_seq"]),
            "label": torch.tensor(binding_label, dtype=torch.float32),
            "contrastive_target": torch.tensor(float(r["contrastive_target"]), dtype=torch.float32),
            "bce_mask": torch.tensor(bce_observed, dtype=torch.bool),
        }


class RankingTripletDataset(Dataset, FeatureMixin):
    def __init__(self, path: Path, split: str, cfg: Config, cache: ESM2Cache, cdrs: CDRMaskStore):
        FeatureMixin.__init__(self, cfg, cache, cdrs)
        df = pd.read_csv(path)
        self.df = df[df["split"].astype(str) == split].reset_index(drop=True)
        self.excluded_unresolved_cdr_rows = 0
        if cfg.exclude_unresolved_cdr_pair_tasks:
            keep = self.df["positive_vhh_seq"].map(cdrs.has_cdr3) & self.df["negative_vhh_seq"].map(cdrs.has_cdr3)
            self.excluded_unresolved_cdr_rows = int((~keep).sum())
            self.df = self.df[keep].reset_index(drop=True)
    def __len__(self) -> int: return len(self.df)
    def __getitem__(self, idx: int) -> dict[str, Any]:
        r = self.df.loc[idx]
        pv, pc = self.vhh_features(r["positive_vhh_seq"])
        nv, nc = self.vhh_features(r["negative_vhh_seq"])
        return {"group": clean(r["ranking_group_id"]), "negative_type": clean(r.get("negative_type", "")), "positive_id": clean(r["positive_pair_id"]), "negative_id": clean(r["negative_pair_id"]), "pos_vhh": pv, "pos_cdr": pc, "pos_antigen": self.antigen_features(r["positive_antigen_seq"]), "neg_vhh": nv, "neg_cdr": nc, "neg_antigen": self.antigen_features(r["negative_antigen_seq"])}


class ContactDataset(Dataset, FeatureMixin):
    def __init__(self, path: Path, split: str, cfg: Config, cache: ESM2Cache, cdrs: CDRMaskStore):
        FeatureMixin.__init__(self, cfg, cache, cdrs)
        self.records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("split") == split:
                    self.records.append(rec)
    def __len__(self) -> int: return len(self.records)
    def __getitem__(self, idx: int) -> dict[str, Any]:
        r = self.records[idx]
        v, cdr = self.vhh_features(r["vhh_seq"])
        a = self.antigen_features(r["antigen_seq"])
        pos = [(i, j) for i, j in r["positive_pairs"] if i < len(v) and j < len(a)]
        neg = [(i, j) for i, j in r["negative_pairs"] if i < len(v) and j < len(a)]
        return {"id": r["complex_id"], "vhh": v, "vhh_cdr": cdr, "antigen": a, "pos": pos, "neg": neg}


def collate_site(batch: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": [b["id"] for b in batch], "vhh": pad_sequence([b["vhh"] for b in batch], batch_first=True), "vhh_cdr": pad_sequence([b["vhh_cdr"] for b in batch], batch_first=True, padding_value=PAD_CDR), "antigen": pad_sequence([b["antigen"] for b in batch], batch_first=True), "paratope": pad_sequence([b["paratope"] for b in batch], batch_first=True, padding_value=-1.0), "epitope": pad_sequence([b["epitope"] for b in batch], batch_first=True, padding_value=-1.0)}


def collate_pair(batch: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": [b["id"] for b in batch], "negative_type": [b["negative_type"] for b in batch], "vhh": pad_sequence([b["vhh"] for b in batch], batch_first=True), "vhh_cdr": pad_sequence([b["vhh_cdr"] for b in batch], batch_first=True, padding_value=PAD_CDR), "antigen": pad_sequence([b["antigen"] for b in batch], batch_first=True), "label": torch.stack([b["label"] for b in batch]), "contrastive_target": torch.stack([b["contrastive_target"] for b in batch]), "bce_mask": torch.stack([b["bce_mask"] for b in batch])}


def collate_rank(batch: list[dict[str, Any]]) -> dict[str, Any]:
    return {"group": [b["group"] for b in batch], "negative_type": [b["negative_type"] for b in batch], "positive_id": [b["positive_id"] for b in batch], "negative_id": [b["negative_id"] for b in batch], "pos_vhh": pad_sequence([b["pos_vhh"] for b in batch], batch_first=True), "pos_cdr": pad_sequence([b["pos_cdr"] for b in batch], batch_first=True, padding_value=PAD_CDR), "pos_antigen": pad_sequence([b["pos_antigen"] for b in batch], batch_first=True), "neg_vhh": pad_sequence([b["neg_vhh"] for b in batch], batch_first=True), "neg_cdr": pad_sequence([b["neg_cdr"] for b in batch], batch_first=True, padding_value=PAD_CDR), "neg_antigen": pad_sequence([b["neg_antigen"] for b in batch], batch_first=True)}


def collate_contact(batch: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": [b["id"] for b in batch], "vhh": pad_sequence([b["vhh"] for b in batch], batch_first=True), "vhh_cdr": pad_sequence([b["vhh_cdr"] for b in batch], batch_first=True, padding_value=PAD_CDR), "antigen": pad_sequence([b["antigen"] for b in batch], batch_first=True), "pos": [b["pos"] for b in batch], "neg": [b["neg"] for b in batch]}


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
        return self.v_ln2(hv + self.v_ff(hv)), self.a_ln2(ha + self.a_ff(ha))


class CrossContactNetV23(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.esm_project = nn.Linear(cfg.esm_dim, cfg.d_model)
        self.cdr_type = nn.Embedding(4, cfg.d_model, padding_idx=PAD_CDR)
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

    def encode(self, vhh_emb: torch.Tensor, vhh_cdr: torch.Tensor, antigen_emb: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        b, lv, _ = vhh_emb.shape
        _, la, _ = antigen_emb.shape
        v_mask = vhh_emb.abs().sum(-1).eq(0)
        a_mask = antigen_emb.abs().sum(-1).eq(0)
        vp = torch.arange(lv, device=vhh_emb.device).unsqueeze(0).expand(b, lv).clamp(max=self.cfg.max_vhh_len - 1)
        ap = torch.arange(la, device=antigen_emb.device).unsqueeze(0).expand(b, la).clamp(max=self.cfg.max_antigen_len - 1)
        hv = self.esm_project(vhh_emb) + self.cdr_type(vhh_cdr.clamp(0, 3)) + self.v_pos(vp)
        ha = self.esm_project(antigen_emb) + self.a_pos(ap)
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
        return logits + self.contact_bias_v(hv) + self.contact_bias_a(ha).transpose(1, 2)

    def pair_logits_from_encoded(self, hv: torch.Tensor, ha: torch.Tensor, v_mask: torch.Tensor, a_mask: torch.Tensor, vhh_cdr: torch.Tensor) -> torch.Tensor:
        v_valid = (~v_mask).float().unsqueeze(-1)
        a_valid = (~a_mask).float().unsqueeze(-1)
        vp = (hv * v_valid).sum(1) / v_valid.sum(1).clamp_min(1.0)
        ap = (ha * a_valid).sum(1) / a_valid.sum(1).clamp_min(1.0)
        # Pair/ranking supervision is contrastive proxy evidence. It may use the
        # validated contact map as a feature, but must not update that head.
        cm = self.contact_logits(hv, ha).detach()
        valid_pair = (~v_mask).unsqueeze(2) & (~a_mask).unsqueeze(1)
        probs = torch.sigmoid(cm).masked_fill(~valid_pair, 0.0)
        flat = probs.masked_fill(~valid_pair, -1.0).flatten(1)
        k = min(50, flat.shape[1])
        top = torch.topk(flat, k=k, dim=1).values.clamp_min(0.0)
        top1 = top[:, :1].mean(1, keepdim=True)
        top5 = top[:, : min(5, k)].mean(1, keepdim=True)
        top20 = top[:, : min(20, k)].mean(1, keepdim=True)
        denom = valid_pair.float().sum((1, 2), keepdim=False).clamp_min(1.0).unsqueeze(1)
        mean_all = probs.sum((1, 2), keepdim=False).unsqueeze(1) / denom
        cdr3_stats = []
        for b in range(hv.shape[0]):
            cdr3_positions = (vhh_cdr[b] == 3) & (~v_mask[b])
            sub = probs[b, cdr3_positions]
            cdr3_stats.append(sub.max().reshape(1) if sub.numel() else torch.zeros(1, device=hv.device))
        cdr3_max = torch.stack(cdr3_stats, dim=0)
        entropy = -(probs.clamp_min(1e-6) * probs.clamp_min(1e-6).log()).sum((1, 2), keepdim=False).unsqueeze(1) / denom
        feat = torch.cat([vp, ap, torch.abs(vp - ap), vp * ap, top1, top5, top20, mean_all, cdr3_max, entropy, (top1 - mean_all)], dim=-1)
        return self.pair(feat).squeeze(-1)

    def pair_logits(self, vhh: torch.Tensor, cdr: torch.Tensor, antigen: torch.Tensor) -> torch.Tensor:
        hv, ha, vm, am = self.encode(vhh, cdr, antigen)
        return self.pair_logits_from_encoded(hv, ha, vm, am, cdr)


def bce_masked(logits: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    mask = labels >= 0
    if mask.sum() == 0:
        return logits.sum() * 0.0
    y = labels[mask]
    x = logits[mask]
    pos = y.sum().clamp_min(1.0)
    neg = (len(y) - y.sum()).clamp_min(1.0)
    return nn.functional.binary_cross_entropy_with_logits(x, y, pos_weight=(neg / pos).clamp(max=25.0))


def observed_positive_bce(logits: torch.Tensor, labels: torch.Tensor, observed_mask: torch.Tensor) -> torch.Tensor:
    mask = observed_mask.bool()
    if mask.sum() == 0:
        return logits.sum() * 0.0
    targets = torch.ones_like(logits[mask])
    return nn.functional.binary_cross_entropy_with_logits(logits[mask], targets)


def pairwise_ranking_loss(pos_logits: torch.Tensor, neg_logits: torch.Tensor, margin: float = 0.25) -> torch.Tensor:
    return nn.functional.softplus(margin - (pos_logits - neg_logits)).mean()


def sample_contact_indices(
    batch: dict[str, Any],
    cfg: Config,
    device: torch.device,
    rng: random.Random | None = None,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    sampler = rng if rng is not None else random
    bi: list[int] = []
    vi: list[int] = []
    ai: list[int] = []
    yy: list[float] = []
    for b, (pos, neg) in enumerate(zip(batch["pos"], batch["neg"])):
        pos_s = pos if len(pos) <= cfg.contact_pos_sample else sampler.sample(pos, cfg.contact_pos_sample)
        neg_s = neg if len(neg) <= cfg.contact_neg_sample else sampler.sample(neg, cfg.contact_neg_sample)
        for i, j in pos_s:
            bi.append(b); vi.append(i); ai.append(j); yy.append(1.0)
        for i, j in neg_s:
            bi.append(b); vi.append(i); ai.append(j); yy.append(0.0)
    if not yy:
        z = torch.zeros(0, dtype=torch.long, device=device)
        return z, z, z, torch.zeros(0, dtype=torch.float32, device=device)
    return torch.tensor(bi, dtype=torch.long, device=device), torch.tensor(vi, dtype=torch.long, device=device), torch.tensor(ai, dtype=torch.long, device=device), torch.tensor(yy, dtype=torch.float32, device=device)


def contact_loss(model: CrossContactNetV23, hv: torch.Tensor, ha: torch.Tensor, batch: dict[str, Any], cfg: Config, device: torch.device) -> torch.Tensor:
    cm = model.contact_logits(hv, ha)
    bi, vi, ai, yy = sample_contact_indices(batch, cfg, device)
    if len(yy) == 0:
        return cm.sum() * 0.0
    logits = cm[bi, vi, ai]
    pos = yy.sum().clamp_min(1.0)
    neg = (len(yy) - yy.sum()).clamp_min(1.0)
    return nn.functional.binary_cross_entropy_with_logits(logits, yy, pos_weight=(neg / pos).clamp(max=20.0))


def eval_site(model: CrossContactNetV23, loader: DataLoader, device: torch.device) -> dict[str, float]:
    model.eval(); py=[]; ps=[]; ey=[]; es=[]
    with torch.no_grad():
        for b in loader:
            v=b["vhh"].to(device); c=b["vhh_cdr"].to(device); a=b["antigen"].to(device); para=b["paratope"].to(device); epi=b["epitope"].to(device)
            hv,ha,_,_=model.encode(v,c,a); pl,el=model.site_logits(hv,ha)
            for logits, labels, yy, ss in [(pl,para,py,ps),(el,epi,ey,es)]:
                m=labels>=0; yy.append(labels[m].cpu().numpy()); ss.append(torch.sigmoid(logits[m]).cpu().numpy())
    out={}
    for pref, yy, ss in [("paratope",py,ps),("epitope",ey,es)]:
        m=binary_metrics(np.concatenate(yy), np.concatenate(ss)) if yy else binary_metrics(np.array([]),np.array([]))
        out.update({f"{pref}_{k}":v for k,v in m.items()})
    return out


def eval_contact(model: CrossContactNetV23, loader: DataLoader, device: torch.device, cfg: Config) -> dict[str, Any]:
    model.eval(); ys=[]; ss=[]; p_at=[]
    eval_rng = random.Random(cfg.eval_contact_seed)
    with torch.no_grad():
        for b in loader:
            v=b["vhh"].to(device); c=b["vhh_cdr"].to(device); a=b["antigen"].to(device)
            hv,ha,_,_=model.encode(v,c,a); cm=torch.sigmoid(model.contact_logits(hv,ha))
            bi,vi,ai,yy=sample_contact_indices(b,cfg,device,eval_rng)
            if len(yy):
                ys.append(yy.cpu().numpy()); ss.append(cm[bi,vi,ai].cpu().numpy())
            for idx,pos in enumerate(b["pos"]):
                if not pos: continue
                lv=int((b["vhh"][idx].abs().sum(-1)!=0).sum()); la=int((b["antigen"][idx].abs().sum(-1)!=0).sum())
                mat=cm[idx,:lv,:la].flatten(); k=min(max(1,len(pos)),50,mat.numel())
                top=torch.topk(mat,k=k).indices.cpu().numpy().tolist(); pred={(t//la,t%la) for t in top}; truth={tuple(x) for x in pos}
                p_at.append(len(pred & truth)/max(len(pred),1))
    m=binary_metrics(np.concatenate(ys), np.concatenate(ss)) if ys else binary_metrics(np.array([]),np.array([]))
    return {f"contact_{k}":v for k,v in m.items()} | {
        "contact_precision_at_poscount_or_50": float(np.mean(p_at)) if p_at else 0.0,
        "contact_eval_sampling_policy": f"deterministic_random_seed_{cfg.eval_contact_seed}",
    }


def eval_pair_proxy(model: CrossContactNetV23, loader: DataLoader, device: torch.device) -> dict[str, Any]:
    model.eval(); proxy_targets=[]; scores=[]; masks=[]; positive_scores=[]
    with torch.no_grad():
        for b in loader:
            logits=model.pair_logits(b["vhh"].to(device), b["vhh_cdr"].to(device), b["antigen"].to(device))
            batch_scores=torch.sigmoid(logits).cpu().numpy()
            batch_proxy=b["contrastive_target"].cpu().numpy()
            proxy_targets.extend(batch_proxy.tolist()); scores.extend(batch_scores.tolist()); masks.extend(b["bce_mask"].cpu().numpy().tolist())
            positive_scores.extend(batch_scores[batch_proxy == 1].tolist())
    y=np.array(proxy_targets); s=np.array(scores); out={f"pair_contrastive_proxy_{k}":v for k,v in binary_metrics(y,s).items()}
    out["pair_bce_observed_positive_rows"] = float(np.array(masks, dtype=bool).sum())
    out["pair_observed_positive_score_mean"] = float(np.mean(positive_scores)) if positive_scores else 0.0
    out["pair_metric_boundary"] = "constructed rows are unlabeled contrastive candidates, not verified non-binders"
    return out


def eval_ranking(model: CrossContactNetV23, loader: DataLoader, device: torch.device) -> dict[str, float]:
    model.eval(); groups: dict[str, list[tuple[float, int, str]]] = {}
    with torch.no_grad():
        for b in loader:
            pos=model.pair_logits(b["pos_vhh"].to(device), b["pos_cdr"].to(device), b["pos_antigen"].to(device))
            neg=model.pair_logits(b["neg_vhh"].to(device), b["neg_cdr"].to(device), b["neg_antigen"].to(device))
            for i, gid in enumerate(b["group"]):
                rows = groups.setdefault(gid, [])
                rows.append((float(pos[i].cpu()), 1, "positive"))
                rows.append((float(neg[i].cpu()), 0, b["negative_type"][i]))
    # Deduplicate repeated positive entries per ranking group while preserving every negative.
    deduped: dict[str, list[tuple[float, int, str]]] = {}
    for gid, rows in groups.items():
        pos_scores = [r[0] for r in rows if r[1] == 1]
        neg_rows = [r for r in rows if r[1] == 0]
        deduped[gid] = [(float(np.mean(pos_scores)), 1, "positive")] + neg_rows
    return ranking_metrics(deduped)


def _path(root: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else root / p


def load_config(path: Path | None) -> Config:
    cfg = Config()
    if path is None:
        return cfg
    raw = json.loads(path.read_text(encoding="utf-8"))
    allowed = {f.name for f in fields(Config)}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"Unknown config fields: {sorted(unknown)}")
    return Config(**{**asdict(cfg), **raw})


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    return pd.read_csv(path).to_dict("records")


def read_contact_rows(path: Path) -> list[dict[str, Any]]:
    rows=[]
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def fail_on_split_leakage(rows: Iterable[dict[str, Any]], name: str, key_columns: tuple[str, ...] = ("split_group_id", "vhh_cluster_id", "cdr3_proxy_cluster_id", "antigen_cluster_id")) -> None:
    seen: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        split = clean(row.get("split"))
        if not split:
            raise ValueError(f"{name}: row without split")
        for col in key_columns:
            value = clean(row.get(col))
            if value:
                seen.setdefault((col, value), set()).add(split)
    leaks = [(col, value, sorted(splits)) for (col, value), splits in seen.items() if len(splits) > 1]
    if leaks:
        col, value, splits = leaks[0]
        raise ValueError(f"{name}: split leakage on {col}={value}: {splits}")


def validate_pair_labels(rows: Iterable[dict[str, Any]]) -> None:
    for row in rows:
        label_state = clean(row.get("label_state"))
        label = float(row.get("binding_label", 0.0))
        ordinary = clean(row.get("ordinary_bce_eligible", "")).lower() == "yes"
        if label <= 0 and ordinary:
            raise ValueError(f"Constructed/non-positive row is BCE-eligible: {clean(row.get('pair_id'))}")
        if label_state != "observed_positive" and ordinary:
            raise ValueError(f"Only observed positives may be BCE-eligible: {clean(row.get('pair_id'))}")


def iter_required_sequences(site: list[dict[str, Any]], pair: list[dict[str, Any]], rank: list[dict[str, Any]], contact: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    vhh: set[str] = set(); antigen: set[str] = set()
    for row in site + pair:
        if clean(row.get("vhh_seq")): vhh.add(clean(row.get("vhh_seq")).upper())
        if clean(row.get("antigen_seq")): antigen.add(clean(row.get("antigen_seq")).upper())
    for row in rank:
        for col in ("positive_vhh_seq", "negative_vhh_seq"):
            if clean(row.get(col)): vhh.add(clean(row.get(col)).upper())
        for col in ("positive_antigen_seq", "negative_antigen_seq"):
            if clean(row.get(col)): antigen.add(clean(row.get(col)).upper())
    for row in contact:
        if clean(row.get("vhh_seq")): vhh.add(clean(row.get("vhh_seq")).upper())
        if clean(row.get("antigen_seq")): antigen.add(clean(row.get("antigen_seq")).upper())
    return vhh, antigen


def validate_inputs(cfg: Config) -> dict[str, Path]:
    root = Path(cfg.root).resolve()
    missing_cfg = [name for name in REQUIRED_INPUTS if not clean(getattr(cfg, name))]
    if missing_cfg:
        raise ValueError(f"V2.3 requires explicit CLI/config inputs: {missing_cfg}")
    paths = {name: _path(root, getattr(cfg, name)).resolve() for name in REQUIRED_INPUTS}
    for name, path in paths.items():
        if not path.exists():
            raise FileNotFoundError(f"Missing required V2.3 input {name}: {path}")
    site = read_csv_rows(paths["clustered_site_csv"])
    pair = read_csv_rows(paths["pair_csv"])
    rank = read_csv_rows(paths["ranking_triplets_csv"])
    contact = read_contact_rows(paths["contact_jsonl"])
    for name, rows in (("site", site), ("pair", pair), ("contact", contact)):
        fail_on_split_leakage(rows, name)
    fail_on_split_leakage(site + pair + contact, "combined_multitask")
    # Triplets inherit pair split groups; enforce stable group/pair placement by IDs.
    fail_on_split_leakage(rank, "ranking_triplets", key_columns=("ranking_group_id", "positive_pair_id", "negative_pair_id"))
    validate_pair_labels(pair)
    cache = ESM2Cache(paths["esm2_cache_manifest"], cfg.esm_dim)
    cdrs = CDRMaskStore(paths["cdr_mask_csv"])
    vhh, antigen = iter_required_sequences(site, pair, rank, contact)
    missing_cache = [seq_hash(seq) for seq in sorted(vhh | antigen) if not cache.has(seq)]
    if missing_cache:
        raise ValueError(f"Missing frozen ESM2 cache embeddings before training; first={missing_cache[0]} count={len(missing_cache)}")
    for digest in sorted(seq_hash(seq) for seq in (vhh | antigen)):
        row = cache.rows[digest]
        shard_path = (cache.manifest_path.parent / row["shard_path"]).resolve()
        if not shard_path.exists():
            raise FileNotFoundError(f"Missing frozen ESM2 shard before training for {digest}: {shard_path}")
        cache.cached_length_for(row)
    missing_cdr = [seq_hash(seq) for seq in sorted(vhh) if not cdrs.has(seq)]
    if missing_cdr:
        raise ValueError(f"Missing VHH CDR masks before training; first={missing_cdr[0]} count={len(missing_cdr)}")
    return paths


def make_loaders(cfg: Config, paths: dict[str, Path], cache: ESM2Cache, cdrs: CDRMaskStore) -> tuple[dict[str, Dataset], dict[str, DataLoader]]:
    ds: dict[str, Dataset] = {
        "site_train": SiteDataset(paths["clustered_site_csv"], "train", cfg, cache, cdrs),
        "site_val": SiteDataset(paths["clustered_site_csv"], "val", cfg, cache, cdrs),
        "site_test": SiteDataset(paths["clustered_site_csv"], "test", cfg, cache, cdrs),
        "pair_train": PairDataset(paths["pair_csv"], "train", cfg, cache, cdrs),
        "pair_val": PairDataset(paths["pair_csv"], "val", cfg, cache, cdrs),
        "pair_test": PairDataset(paths["pair_csv"], "test", cfg, cache, cdrs),
        "rank_train": RankingTripletDataset(paths["ranking_triplets_csv"], "train", cfg, cache, cdrs),
        "rank_val": RankingTripletDataset(paths["ranking_triplets_csv"], "val", cfg, cache, cdrs),
        "rank_test": RankingTripletDataset(paths["ranking_triplets_csv"], "test", cfg, cache, cdrs),
        "contact_train": ContactDataset(paths["contact_jsonl"], "train", cfg, cache, cdrs),
        "contact_val": ContactDataset(paths["contact_jsonl"], "val", cfg, cache, cdrs),
        "contact_test": ContactDataset(paths["contact_jsonl"], "test", cfg, cache, cdrs),
    }
    for key, value in ds.items():
        if len(value) == 0:
            raise ValueError(f"Empty required dataset split: {key}")
    kwargs = {"num_workers": cfg.num_workers}
    ld = {
        "site_train": DataLoader(ds["site_train"], batch_size=cfg.batch_site, shuffle=True, collate_fn=collate_site, **kwargs),
        "site_val": DataLoader(ds["site_val"], batch_size=cfg.batch_site, shuffle=False, collate_fn=collate_site, **kwargs),
        "site_test": DataLoader(ds["site_test"], batch_size=cfg.batch_site, shuffle=False, collate_fn=collate_site, **kwargs),
        "pair_train": DataLoader(ds["pair_train"], batch_size=cfg.batch_pair, shuffle=True, collate_fn=collate_pair, **kwargs),
        "pair_val": DataLoader(ds["pair_val"], batch_size=cfg.batch_pair, shuffle=False, collate_fn=collate_pair, **kwargs),
        "pair_test": DataLoader(ds["pair_test"], batch_size=cfg.batch_pair, shuffle=False, collate_fn=collate_pair, **kwargs),
        "rank_train": DataLoader(ds["rank_train"], batch_size=cfg.batch_rank, shuffle=True, collate_fn=collate_rank, **kwargs),
        "rank_val": DataLoader(ds["rank_val"], batch_size=cfg.batch_rank, shuffle=False, collate_fn=collate_rank, **kwargs),
        "rank_test": DataLoader(ds["rank_test"], batch_size=cfg.batch_rank, shuffle=False, collate_fn=collate_rank, **kwargs),
        "contact_train": DataLoader(ds["contact_train"], batch_size=cfg.batch_contact, shuffle=True, collate_fn=collate_contact, **kwargs),
        "contact_val": DataLoader(ds["contact_val"], batch_size=cfg.batch_contact, shuffle=False, collate_fn=collate_contact, **kwargs),
        "contact_test": DataLoader(ds["contact_test"], batch_size=cfg.batch_contact, shuffle=False, collate_fn=collate_contact, **kwargs),
    }
    return ds, ld


def device_metadata(device: torch.device) -> dict[str, Any]:
    return {
        "device": str(device),
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
        "deterministic_algorithms_warn_only": True,
    }


class NonFiniteLossError(FloatingPointError):
    def __init__(self, task: str, value: float):
        super().__init__(f"Non-finite {task} loss: {value}")
        self.task = task
        self.value = value


def ensure_finite_loss(task: str, loss: torch.Tensor) -> None:
    if not bool(torch.isfinite(loss.detach()).all()):
        raise NonFiniteLossError(task, float(loss.detach().cpu()))


def restore_resume_best_checkpoint(
    resume_path: Path,
    resume_ckpt: dict[str, Any],
    best_path: Path,
    device: torch.device,
) -> tuple[dict[str, Any], Path]:
    candidates: list[Path] = []
    declared = clean(resume_ckpt.get("best_checkpoint_path"))
    if declared:
        declared_path = Path(declared)
        candidates.append(declared_path)
        if not declared_path.is_absolute():
            candidates.append(resume_path.parent / declared_path.name)
    candidates.append(resume_path.parent / "best_checkpoint.pt")
    candidates.append(resume_path)

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        prior = resume_ckpt if resolved == resume_path.resolve() else torch.load(resolved, map_location=device, weights_only=False)
        if not isinstance(prior, dict) or not isinstance(prior.get("model"), dict):
            continue
        best_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(prior, best_path)
        return prior, resolved
    raise FileNotFoundError(f"Could not restore a best checkpoint from resume path {resume_path}")


def write_failure_artifacts(
    run_dir: Path,
    model: CrossContactNetV23,
    cfg: Config,
    diagnostic: dict[str, Any],
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "failure_diagnostic.json").write_text(
        json.dumps(diagnostic, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        cpu_state = {name: tensor.detach().cpu() for name, tensor in model.state_dict().items()}
        torch.save(
            {"model": cpu_state, "cfg": asdict(cfg), "diagnostic": diagnostic},
            run_dir / "failure_checkpoint.pt",
        )
    except Exception as exc:  # pragma: no cover - best-effort after a runtime failure
        diagnostic["failure_checkpoint_error"] = repr(exc)
        (run_dir / "failure_diagnostic.json").write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def train(cfg: Config, run_name: str, resume: str = "") -> dict[str, Any]:
    paths = validate_inputs(cfg)
    cache = ESM2Cache(paths["esm2_cache_manifest"], cfg.esm_dim)
    cdrs = CDRMaskStore(paths["cdr_mask_csv"])
    random.seed(cfg.seed); np.random.seed(cfg.seed); torch.manual_seed(cfg.seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.cuda.manual_seed_all(cfg.seed); torch.set_float32_matmul_precision("high")
    root = Path(cfg.root).resolve(); out_root = root / cfg.out_root
    run_id = run_name or time.strftime("phase2_v2_3_%Y%m%d_%H%M%S_seed") + str(cfg.seed)
    run_dir = out_root / "runs" / run_id; run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config_resolved.json").write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
    ds, ld = make_loaders(cfg, paths, cache, cdrs)
    model = CrossContactNetV23(cfg).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    scaler = torch.amp.GradScaler("cuda", enabled=(cfg.use_amp and device.type == "cuda"))
    start_epoch = 1; best = -1.0; best_path = run_dir / "best_checkpoint.pt"; history: list[dict[str, Any]] = []
    resume_best_source = ""
    if resume:
        resume_path = Path(resume).resolve()
        ckpt = torch.load(resume_path, map_location=device, weights_only=False)
        model.load_state_dict(ckpt["model"]); opt.load_state_dict(ckpt["optimizer"])
        if "scaler" in ckpt: scaler.load_state_dict(ckpt["scaler"])
        start_epoch = int(ckpt.get("epoch", 0)) + 1; best = float(ckpt.get("best_score", -1.0)); history = list(ckpt.get("history", []))
        prior_best, prior_best_path = restore_resume_best_checkpoint(resume_path, ckpt, best_path, device)
        best = max(best, float(prior_best.get("best_score", -1.0)))
        resume_best_source = str(prior_best_path)
    for epoch in range(start_epoch, cfg.epochs + 1):
        model.train(); total=0.0; steps=0; accum=0
        task_totals = {"contact": 0.0, "site": 0.0, "pair_bce": 0.0, "ranking": 0.0}
        site_it=iter(ld["site_train"]); pair_it=iter(ld["pair_train"]); rank_it=iter(ld["rank_train"])
        opt.zero_grad(set_to_none=True)
        for step_index, cb in enumerate(ld["contact_train"], start=1):
            try: sb=next(site_it)
            except StopIteration: site_it=iter(ld["site_train"]); sb=next(site_it)
            try: pb=next(pair_it)
            except StopIteration: pair_it=iter(ld["pair_train"]); pb=next(pair_it)
            try: rb=next(rank_it)
            except StopIteration: rank_it=iter(ld["rank_train"]); rb=next(rank_it)
            amp_enabled = cfg.use_amp and device.type == "cuda"
            loss_parts: list[torch.Tensor] = []
            task = "contact"
            try:
                with torch.amp.autocast(device_type=device.type, enabled=amp_enabled):
                    cv=cb["vhh"].to(device); cc=cb["vhh_cdr"].to(device); ca=cb["antigen"].to(device); chv,cha,_,_=model.encode(cv,cc,ca); c_loss=cfg.contact_weight*contact_loss(model,chv,cha,cb,cfg,device)
                ensure_finite_loss(task, c_loss); scaler.scale(c_loss/max(cfg.grad_accum_steps,1)).backward(); loss_parts.append(c_loss.detach()); task_totals[task] += float(c_loss.detach().cpu()); del cv, cc, ca, chv, cha, c_loss
                task = "site"
                with torch.amp.autocast(device_type=device.type, enabled=amp_enabled):
                    sv=sb["vhh"].to(device); sc=sb["vhh_cdr"].to(device); sa=sb["antigen"].to(device); para=sb["paratope"].to(device); epi=sb["epitope"].to(device); shv,sha,_,_=model.encode(sv,sc,sa); pl,el=model.site_logits(shv,sha); s_loss=cfg.site_weight*(bce_masked(pl,para)+bce_masked(el,epi))
                ensure_finite_loss(task, s_loss); scaler.scale(s_loss/max(cfg.grad_accum_steps,1)).backward(); loss_parts.append(s_loss.detach()); task_totals[task] += float(s_loss.detach().cpu()); del sv, sc, sa, para, epi, shv, sha, pl, el, s_loss
                task = "pair_bce"
                with torch.amp.autocast(device_type=device.type, enabled=amp_enabled):
                    pv=pb["vhh"].to(device); pc=pb["vhh_cdr"].to(device); pa=pb["antigen"].to(device); py=pb["label"].to(device); pm=pb["bce_mask"].to(device); p_logits=model.pair_logits(pv,pc,pa); p_loss=cfg.pair_bce_weight*observed_positive_bce(p_logits,py,pm)
                ensure_finite_loss(task, p_loss); scaler.scale(p_loss/max(cfg.grad_accum_steps,1)).backward(); loss_parts.append(p_loss.detach()); task_totals[task] += float(p_loss.detach().cpu()); del pv, pc, pa, py, pm, p_logits, p_loss
                task = "ranking"
                with torch.amp.autocast(device_type=device.type, enabled=amp_enabled):
                    rpos=model.pair_logits(rb["pos_vhh"].to(device), rb["pos_cdr"].to(device), rb["pos_antigen"].to(device)); rneg=model.pair_logits(rb["neg_vhh"].to(device), rb["neg_cdr"].to(device), rb["neg_antigen"].to(device)); r_loss=cfg.ranking_weight*pairwise_ranking_loss(rpos,rneg,cfg.ranking_margin)
                ensure_finite_loss(task, r_loss); scaler.scale(r_loss/max(cfg.grad_accum_steps,1)).backward(); loss_parts.append(r_loss.detach()); task_totals[task] += float(r_loss.detach().cpu()); del rpos, rneg, r_loss; accum+=1
            except (NonFiniteLossError, torch.cuda.OutOfMemoryError) as exc:
                opt.zero_grad(set_to_none=True)
                if device.type == "cuda":
                    torch.cuda.empty_cache()
                diagnostic = {
                    "status": "FAILED",
                    "reason": "cuda_oom" if isinstance(exc, torch.cuda.OutOfMemoryError) else "nonfinite_loss",
                    "message": repr(exc),
                    "task": getattr(exc, "task", task),
                    "epoch": epoch,
                    "step": step_index,
                    "batch_ids": {"contact": cb.get("id", []), "site": sb.get("id", []), "pair": pb.get("id", []), "ranking_group": rb.get("group", [])},
                    "device": device_metadata(device),
                }
                write_failure_artifacts(run_dir, model, cfg, diagnostic)
                raise
            if accum % max(cfg.grad_accum_steps,1) == 0:
                scaler.unscale_(opt); torch.nn.utils.clip_grad_norm_(model.parameters(),1.0); scaler.step(opt); scaler.update(); opt.zero_grad(set_to_none=True)
            total += float(torch.stack(loss_parts).sum().cpu()); steps += 1
            if cfg.log_every_steps > 0 and step_index % cfg.log_every_steps == 0:
                print(json.dumps({"event":"train_progress","epoch":epoch,"step":step_index,"steps_total":len(ld["contact_train"]),"mean_loss":total/max(steps,1)}, ensure_ascii=False), flush=True)
        if accum % max(cfg.grad_accum_steps,1) != 0:
            scaler.unscale_(opt); torch.nn.utils.clip_grad_norm_(model.parameters(),1.0); scaler.step(opt); scaler.update(); opt.zero_grad(set_to_none=True)
        val_contact=eval_contact(model,ld["contact_val"],device,cfg); val_site=eval_site(model,ld["site_val"],device); val_pair=eval_pair_proxy(model,ld["pair_val"],device); val_rank=eval_ranking(model,ld["rank_val"],device)
        rec={"epoch":epoch,"train_loss":total/max(steps,1),**{f"train_{name}_loss":value/max(steps,1) for name,value in task_totals.items()},**{f"val_{k}":v for k,v in val_contact.items()},**{f"val_{k}":v for k,v in val_site.items()},**{f"val_{k}":v for k,v in val_pair.items()},**{f"val_{k}":v for k,v in val_rank.items()}}
        history.append(rec)
        score=(
            cfg.selection_contact_weight*rec.get("val_contact_auprc",0)
            + cfg.selection_ranking_weight*rec.get("val_ranking_mrr",0)
            + cfg.selection_paratope_weight*rec.get("val_paratope_auprc",0)
        )
        ckpt={"model":model.state_dict(),"optimizer":opt.state_dict(),"scaler":scaler.state_dict(),"cfg":asdict(cfg),"epoch":epoch,"best_score":max(best,score),"best_checkpoint_path":str(best_path.resolve()),"run_id":run_id,"history":history,"env":device_metadata(device)}
        torch.save(ckpt, run_dir / "last_checkpoint.pt")
        if score > best:
            best = score; torch.save(ckpt, best_path)
        print(json.dumps({"epoch":epoch,"train_loss":rec["train_loss"],"val_contact_auprc":rec.get("val_contact_auprc"),"val_ranking_mrr":rec.get("val_ranking_mrr"),"val_ranking_hit_at_1":rec.get("val_ranking_hit_at_1"),"val_pair_bce_observed_positive_rows":rec.get("val_pair_bce_observed_positive_rows")}, ensure_ascii=False), flush=True)
    ckpt=torch.load(best_path,map_location=device,weights_only=False); model.load_state_dict(ckpt["model"])
    metrics={"dataset_sizes":{k:len(v) for k,v in ds.items()},"dataset_excluded_unresolved_cdr_rows":{k:int(getattr(v,"excluded_unresolved_cdr_rows",0)) for k,v in ds.items()},"checkpoint":str(best_path),"contact_test":eval_contact(model,ld["contact_test"],device,cfg),"site_test":eval_site(model,ld["site_test"],device),"pair_test":eval_pair_proxy(model,ld["pair_test"],device),"ranking_test":eval_ranking(model,ld["rank_test"],device)}
    env=device_metadata(device) | {"best_epoch": int(ckpt.get("epoch",-1)), "run_id": run_id, "resume_best_source": resume_best_source}
    (run_dir/"metrics_history.json").write_text(json.dumps(history,ensure_ascii=False,indent=2),encoding="utf-8")
    (run_dir/"test_metrics.json").write_text(json.dumps(metrics,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    report={"history":history,"test_metrics":metrics,"env":env,"strict_inputs":{k:str(v) for k,v in paths.items()}}
    (out_root/"reports/phase2_v2_3_metrics.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    torch.save(ckpt,out_root/"checkpoints/phase2_v2_3_best_checkpoint.pt")
    return {"status":"PASS","run_id":run_id,"best_epoch":env["best_epoch"],"metrics":str(run_dir/"test_metrics.json"),"checkpoint":str(best_path)}


def parse_args() -> argparse.Namespace:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--root", default=None)
    ap.add_argument("--run-name", default="")
    ap.add_argument("--resume", default="")
    ap.add_argument("--epochs", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--dry-validate", action="store_true", help="Validate strict manifests/cache/masks and exit before training")
    for name in REQUIRED_INPUTS:
        ap.add_argument("--" + name.replace("_", "-"), default=None)
    return ap.parse_args()


def main() -> None:
    args=parse_args(); cfg=load_config(args.config)
    if args.root is not None: cfg.root=args.root
    if args.epochs is not None: cfg.epochs=args.epochs
    if args.seed is not None: cfg.seed=args.seed
    for name in REQUIRED_INPUTS:
        val=getattr(args,name)
        if val is not None: setattr(cfg,name,val)
    if args.dry_validate:
        paths=validate_inputs(cfg)
        print(json.dumps({"status":"VALIDATED","strict_inputs":{k:str(v) for k,v in paths.items()}},ensure_ascii=False,indent=2,sort_keys=True))
        return
    print(json.dumps(train(cfg,args.run_name,args.resume),ensure_ascii=False,indent=2,sort_keys=True))


if __name__ == "__main__":
    main()
