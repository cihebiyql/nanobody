#!/usr/bin/env python3
"""Train Phase 2 V2.4 with complete-group listwise proxy ranking.

V2.4 warm-starts the validated V2.3 contact/site backbone and replaces
independent triplet updates with one-positive-versus-all-available-negatives
ranking groups. Constructed candidates remain ranking proxies, never verified
non-binders or calibrated blocker labels.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.nn.utils.rnn import pad_sequence
from torch.utils.data import DataLoader, Dataset

from build_phase2_v2_4_manifests import validate_control_isolation
from train_phase2_v2_3 import (
    CDRMaskStore,
    Config as ConfigV23,
    ContactDataset,
    CrossContactNetV23,
    ESM2Cache,
    FeatureMixin,
    NonFiniteLossError,
    PairDataset,
    SiteDataset,
    bce_masked,
    clean,
    collate_contact,
    collate_pair,
    collate_site,
    contact_loss,
    device_metadata,
    ensure_finite_loss,
    eval_contact,
    eval_pair_proxy,
    eval_site,
    make_loaders as make_loaders_v23,
    observed_positive_bce,
    ranking_metrics,
    restore_resume_best_checkpoint,
    validate_inputs as validate_inputs_v23,
    write_failure_artifacts,
)


V24_REQUIRED_INPUTS = ("ranking_groups_csv", "pvrig_controls_csv")


@dataclass
class Config(ConfigV23):
    ranking_groups_csv: str = ""
    pvrig_controls_csv: str = ""
    init_checkpoint: str = ""
    batch_rank: int = 16
    epochs: int = 4
    lr: float = 1e-4
    pair_bce_weight: float = 0.10
    listwise_weight: float = 1.0
    typed_margin_weight: float = 0.50
    ranking_temperature: float = 0.50
    selection_hard_negative_weight: float = 0.25
    warmstart_required: bool = True


class RankingGroupDataset(Dataset, FeatureMixin):
    def __init__(self, path: Path, split: str, cfg: Config, cache: ESM2Cache, cdrs: CDRMaskStore):
        FeatureMixin.__init__(self, cfg, cache, cdrs)
        frame = pd.read_csv(path)
        required = {
            "ranking_group_id", "split", "candidate_pair_id", "candidate_role", "negative_type",
            "vhh_seq", "antigen_seq", "proxy_label_policy", "ranking_weight", "ranking_margin",
            "ordinary_bce_eligible",
        }
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"V2.4 ranking groups missing columns: {sorted(missing)}")
        frame = frame[frame["split"].astype(str) == split].copy()
        self.groups: list[dict[str, Any]] = []
        self.excluded_unresolved_cdr_rows = 0
        self.excluded_unresolved_cdr_groups = 0
        for group_id, group in frame.groupby("ranking_group_id", sort=False):
            positives = group[group["candidate_role"].astype(str) == "observed_cognate_positive"]
            negatives = group[group["candidate_role"].astype(str) == "constructed_contrastive_candidate"]
            if len(positives) != 1:
                raise ValueError(f"Ranking group {group_id} must have exactly one positive anchor")
            positive = positives.iloc[0]
            positive_seq = clean(positive["vhh_seq"]).upper()
            if cfg.exclude_unresolved_cdr_pair_tasks and not cdrs.has_cdr3(positive_seq):
                self.excluded_unresolved_cdr_rows += 1
                self.excluded_unresolved_cdr_groups += 1
                continue
            kept_negatives: list[dict[str, Any]] = []
            for _, negative in negatives.iterrows():
                negative_seq = clean(negative["vhh_seq"]).upper()
                if cfg.exclude_unresolved_cdr_pair_tasks and not cdrs.has_cdr3(negative_seq):
                    self.excluded_unresolved_cdr_rows += 1
                    continue
                if clean(negative["proxy_label_policy"]) != "constructed_preference_not_verified_nonbinder":
                    raise ValueError(f"Ranking group {group_id} has invalid proxy semantics")
                if clean(negative["ordinary_bce_eligible"]).lower() != "no":
                    raise ValueError(f"Constructed ranking candidate is BCE eligible in group {group_id}")
                kept_negatives.append(negative.to_dict())
            if not kept_negatives:
                self.excluded_unresolved_cdr_groups += 1
                continue
            self.groups.append({"group_id": clean(group_id), "positive": positive.to_dict(), "negatives": kept_negatives})

    def __len__(self) -> int:
        return len(self.groups)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        group = self.groups[idx]
        positive = group["positive"]
        pos_vhh, pos_cdr = self.vhh_features(clean(positive["vhh_seq"]).upper())
        negatives = []
        for row in group["negatives"]:
            neg_vhh, neg_cdr = self.vhh_features(clean(row["vhh_seq"]).upper())
            negatives.append(
                {
                    "candidate_id": clean(row["candidate_pair_id"]),
                    "negative_type": clean(row["negative_type"]),
                    "vhh": neg_vhh,
                    "cdr": neg_cdr,
                    "antigen": self.antigen_features(clean(row["antigen_seq"]).upper()),
                    "weight": float(row["ranking_weight"]),
                    "margin": float(row["ranking_margin"]),
                }
            )
        return {
            "group": group["group_id"],
            "positive_id": clean(positive["candidate_pair_id"]),
            "pos_vhh": pos_vhh,
            "pos_cdr": pos_cdr,
            "pos_antigen": self.antigen_features(clean(positive["antigen_seq"]).upper()),
            "negatives": negatives,
        }


def collate_rank_groups(batch: list[dict[str, Any]]) -> dict[str, Any]:
    neg_vhh: list[torch.Tensor] = []
    neg_cdr: list[torch.Tensor] = []
    neg_antigen: list[torch.Tensor] = []
    neg_owner: list[int] = []
    neg_weight: list[float] = []
    neg_margin: list[float] = []
    negative_type: list[str] = []
    negative_id: list[str] = []
    for owner, item in enumerate(batch):
        for negative in item["negatives"]:
            neg_vhh.append(negative["vhh"])
            neg_cdr.append(negative["cdr"])
            neg_antigen.append(negative["antigen"])
            neg_owner.append(owner)
            neg_weight.append(float(negative["weight"]))
            neg_margin.append(float(negative["margin"]))
            negative_type.append(negative["negative_type"])
            negative_id.append(negative["candidate_id"])
    if not neg_vhh:
        raise ValueError("V2.4 ranking batch contains no constructed candidates")
    return {
        "group": [item["group"] for item in batch],
        "positive_id": [item["positive_id"] for item in batch],
        "pos_vhh": pad_sequence([item["pos_vhh"] for item in batch], batch_first=True),
        "pos_cdr": pad_sequence([item["pos_cdr"] for item in batch], batch_first=True, padding_value=0),
        "pos_antigen": pad_sequence([item["pos_antigen"] for item in batch], batch_first=True),
        "negative_id": negative_id,
        "negative_type": negative_type,
        "neg_vhh": pad_sequence(neg_vhh, batch_first=True),
        "neg_cdr": pad_sequence(neg_cdr, batch_first=True, padding_value=0),
        "neg_antigen": pad_sequence(neg_antigen, batch_first=True),
        "neg_owner": torch.tensor(neg_owner, dtype=torch.long),
        "neg_weight": torch.tensor(neg_weight, dtype=torch.float32),
        "neg_margin": torch.tensor(neg_margin, dtype=torch.float32),
    }


def masked_mean(values: torch.Tensor, valid: torch.Tensor) -> torch.Tensor:
    weight = valid.float().unsqueeze(-1)
    return (values * weight).sum(1) / weight.sum(1).clamp_min(1.0)


def weighted_mean(values: torch.Tensor, weights: torch.Tensor) -> torch.Tensor:
    weights = weights.clamp_min(0.0)
    return (values * weights.unsqueeze(-1)).sum(1) / weights.sum(1, keepdim=True).clamp_min(1e-6)


class CrossContactNetV24(CrossContactNetV23):
    def __init__(self, cfg: Config):
        super().__init__(cfg)
        del self.pair
        pair_in = cfg.d_model * 10 + 11
        self.pair_encoder = nn.Sequential(
            nn.LayerNorm(pair_in),
            nn.Linear(pair_in, cfg.d_model * 2),
            nn.GELU(),
            nn.Dropout(cfg.dropout),
            nn.Linear(cfg.d_model * 2, cfg.d_model),
            nn.GELU(),
        )
        self.pair_rank_head = nn.Sequential(
            nn.Linear(cfg.d_model, cfg.d_model // 2),
            nn.GELU(),
            nn.Linear(cfg.d_model // 2, 1),
        )

    def pair_logits_from_encoded(
        self,
        hv: torch.Tensor,
        ha: torch.Tensor,
        v_mask: torch.Tensor,
        a_mask: torch.Tensor,
        vhh_cdr: torch.Tensor,
    ) -> torch.Tensor:
        v_valid = ~v_mask
        a_valid = ~a_mask
        vp = masked_mean(hv, v_valid)
        ap = masked_mean(ha, a_valid)
        cdr_valid = v_valid & vhh_cdr.gt(0)
        cdr3_valid = v_valid & vhh_cdr.eq(3)
        cdr_pool = masked_mean(hv, cdr_valid)
        cdr3_pool = masked_mean(hv, cdr3_valid)

        # Proxy ranking may consume contact evidence but cannot update the
        # validated contact head with constructed negative semantics.
        contact = torch.sigmoid(self.contact_logits(hv, ha).detach())
        valid_pair = v_valid.unsqueeze(2) & a_valid.unsqueeze(1)
        contact = contact.masked_fill(~valid_pair, 0.0)
        v_contact_weight = contact.max(dim=2).values.masked_fill(~v_valid, 0.0)
        a_contact_weight = contact.max(dim=1).values.masked_fill(~a_valid, 0.0)
        v_contact_pool = weighted_mean(hv, v_contact_weight)
        a_contact_pool = weighted_mean(ha, a_contact_weight)

        flat = contact.masked_fill(~valid_pair, -1.0).flatten(1)
        k = min(50, flat.shape[1])
        top = torch.topk(flat, k=k, dim=1).values.clamp_min(0.0)
        top1 = top[:, :1].mean(1, keepdim=True)
        top5 = top[:, : min(5, k)].mean(1, keepdim=True)
        top20 = top[:, : min(20, k)].mean(1, keepdim=True)
        denom = valid_pair.float().sum((1, 2)).clamp_min(1.0).unsqueeze(1)
        mean_all = contact.sum((1, 2)).unsqueeze(1) / denom
        entropy = -(contact.clamp_min(1e-6) * contact.clamp_min(1e-6).log()).sum((1, 2)).unsqueeze(1) / denom
        cdr3_pair_mask = cdr3_valid.unsqueeze(2) & a_valid.unsqueeze(1)
        cdr3_flat = contact.masked_fill(~cdr3_pair_mask, -1.0).flatten(1)
        cdr3_max = cdr3_flat.max(1).values.clamp_min(0.0).unsqueeze(1)
        cdr3_denom = cdr3_pair_mask.float().sum((1, 2)).clamp_min(1.0).unsqueeze(1)
        cdr3_mean = contact.masked_fill(~cdr3_pair_mask, 0.0).sum((1, 2)).unsqueeze(1) / cdr3_denom
        v_len = v_valid.float().sum(1, keepdim=True) / float(self.cfg.max_vhh_len)
        a_len = a_valid.float().sum(1, keepdim=True) / float(self.cfg.max_antigen_len)
        cdr3_fraction = cdr3_valid.float().sum(1, keepdim=True) / v_valid.float().sum(1, keepdim=True).clamp_min(1.0)
        scalar = torch.cat(
            [top1, top5, top20, mean_all, cdr3_max, cdr3_mean, entropy, top1 - mean_all, v_len, a_len, cdr3_fraction],
            dim=1,
        )
        vectors = [
            vp, ap, torch.abs(vp - ap), vp * ap, cdr_pool, cdr3_pool,
            v_contact_pool, a_contact_pool, torch.abs(cdr3_pool - a_contact_pool), cdr3_pool * a_contact_pool,
        ]
        hidden = self.pair_encoder(torch.cat([*vectors, scalar], dim=1))
        return self.pair_rank_head(hidden).squeeze(-1)

    def pair_logits(self, vhh: torch.Tensor, cdr: torch.Tensor, antigen: torch.Tensor) -> torch.Tensor:
        hv, ha, v_mask, a_mask = self.encode(vhh, cdr, antigen)
        return self.pair_logits_from_encoded(hv, ha, v_mask, a_mask, cdr)


def listwise_group_ranking_loss(
    positive_logits: torch.Tensor,
    negative_logits: torch.Tensor,
    negative_owner: torch.Tensor,
    negative_weights: torch.Tensor,
    temperature: float,
) -> torch.Tensor:
    if positive_logits.numel() == 0 or negative_logits.numel() == 0:
        return positive_logits.sum() * 0.0
    temperature = max(float(temperature), 1e-4)
    losses: list[torch.Tensor] = []
    for group_index in range(int(positive_logits.shape[0])):
        mask = negative_owner.eq(group_index)
        if not bool(mask.any()):
            continue
        scores = torch.cat([positive_logits[group_index : group_index + 1], negative_logits[mask]]) / temperature
        log_weights = torch.cat(
            [torch.zeros(1, device=scores.device, dtype=scores.dtype), negative_weights[mask].to(scores).clamp_min(1e-6).log()]
        )
        losses.append(-torch.log_softmax(scores + log_weights, dim=0)[0])
    return torch.stack(losses).mean() if losses else positive_logits.sum() * 0.0


def typed_pairwise_margin_loss(
    positive_logits: torch.Tensor,
    negative_logits: torch.Tensor,
    negative_owner: torch.Tensor,
    negative_margins: torch.Tensor,
    negative_weights: torch.Tensor,
) -> torch.Tensor:
    if negative_logits.numel() == 0:
        return positive_logits.sum() * 0.0
    positive_for_negative = positive_logits[negative_owner]
    raw = nn.functional.softplus(negative_margins - (positive_for_negative - negative_logits))
    weights = negative_weights.clamp_min(1e-6)
    return (raw * weights).sum() / weights.sum()


def random_ranking_baselines(group_sizes: list[int]) -> dict[str, float]:
    valid = [int(size) for size in group_sizes if int(size) > 0]
    if not valid:
        return {"ranking_mrr": 0.0, "ranking_hit_at_1": 0.0, "ranking_hard_negative_win_rate": 0.5}
    reciprocal = [sum(1.0 / rank for rank in range(1, size + 1)) / size for size in valid]
    return {
        "ranking_mrr": float(np.mean(reciprocal)),
        "ranking_hit_at_1": float(np.mean([1.0 / size for size in valid])),
        "ranking_hard_negative_win_rate": 0.5,
    }


def eval_ranking_groups(model: CrossContactNetV24, loader: DataLoader, device: torch.device) -> dict[str, float | str]:
    model.eval()
    groups: dict[str, list[tuple[float, int, str]]] = {}
    group_sizes: list[int] = []
    with torch.no_grad():
        for batch in loader:
            pos = model.pair_logits(batch["pos_vhh"].to(device), batch["pos_cdr"].to(device), batch["pos_antigen"].to(device))
            neg = model.pair_logits(batch["neg_vhh"].to(device), batch["neg_cdr"].to(device), batch["neg_antigen"].to(device))
            owners = batch["neg_owner"].tolist()
            for group_index, group_id in enumerate(batch["group"]):
                rows: list[tuple[float, int, str]] = [(float(pos[group_index].cpu()), 1, "positive_anchor")]
                for negative_index, owner in enumerate(owners):
                    if owner == group_index:
                        rows.append((float(neg[negative_index].cpu()), 0, batch["negative_type"][negative_index]))
                groups[group_id] = rows
                group_sizes.append(len(rows))
    metrics = ranking_metrics(groups, hard_prefixes=("N2", "N3", "hard"))
    baseline = random_ranking_baselines(group_sizes)
    metrics.update({f"ranking_random_{key.removeprefix('ranking_')}": value for key, value in baseline.items()})
    metrics["ranking_mrr_delta_vs_random"] = float(metrics["ranking_mrr"] - baseline["ranking_mrr"])
    metrics["ranking_hit_at_1_delta_vs_random"] = float(metrics["ranking_hit_at_1"] - baseline["ranking_hit_at_1"])
    metrics["ranking_metric_boundary"] = "complete-group ranking over constructed contrast candidates; negatives are not verified non-binders"
    return metrics


def load_v23_warmstart(model: CrossContactNetV24, checkpoint_path: Path) -> dict[str, Any]:
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    source = checkpoint.get("model")
    if not isinstance(source, dict):
        raise ValueError(f"Warm-start checkpoint has no model state: {checkpoint_path}")
    target = model.state_dict()
    matched: dict[str, torch.Tensor] = {}
    skipped: list[str] = []
    for name, value in source.items():
        if name.startswith("pair.") or name not in target or target[name].shape != value.shape:
            skipped.append(name)
            continue
        matched[name] = value
    missing_before = sorted(set(target) - set(matched))
    model.load_state_dict(matched, strict=False)
    return {
        "source": str(checkpoint_path),
        "loaded_keys": len(matched),
        "target_keys_not_loaded": missing_before,
        "skipped_source_keys": sorted(skipped),
        "source_epoch": int(checkpoint.get("epoch", -1)),
    }


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def load_config(path: Path | None) -> Config:
    cfg = Config()
    if path is None:
        return cfg
    raw = json.loads(path.read_text(encoding="utf-8"))
    allowed = {field.name for field in fields(Config)}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"Unknown V2.4 config fields: {sorted(unknown)}")
    return Config(**{**asdict(cfg), **raw})


def validate_inputs(cfg: Config) -> dict[str, Path]:
    paths = validate_inputs_v23(cfg)
    root = Path(cfg.root).resolve()
    for name in V24_REQUIRED_INPUTS:
        value = clean(getattr(cfg, name))
        if not value:
            raise ValueError(f"V2.4 requires explicit input: {name}")
        path = _resolve(root, value)
        if not path.exists():
            raise FileNotFoundError(f"Missing V2.4 input {name}: {path}")
        paths[name] = path
    ranking = pd.read_csv(paths["ranking_groups_csv"])
    controls = pd.read_csv(paths["pvrig_controls_csv"])
    if ranking.groupby("ranking_group_id")["split"].nunique().max() != 1:
        raise ValueError("V2.4 ranking group crosses strict splits")
    validate_control_isolation(ranking, controls)
    negative = ranking[ranking["candidate_role"].astype(str) == "constructed_contrastive_candidate"]
    if set(negative["proxy_label_policy"].astype(str)) != {"constructed_preference_not_verified_nonbinder"}:
        raise ValueError("V2.4 constructed ranking proxy semantics are invalid")
    if set(negative["ordinary_bce_eligible"].astype(str).str.lower()) != {"no"}:
        raise ValueError("V2.4 constructed ranking candidates became BCE eligible")
    return paths


def make_loaders(
    cfg: Config,
    paths: dict[str, Path],
    cache: ESM2Cache,
    cdrs: CDRMaskStore,
) -> tuple[dict[str, Dataset], dict[str, DataLoader]]:
    datasets, loaders = make_loaders_v23(cfg, paths, cache, cdrs)
    kwargs = {"num_workers": cfg.num_workers}
    for split in ("train", "val", "test"):
        key = f"rank_{split}"
        dataset = RankingGroupDataset(paths["ranking_groups_csv"], split, cfg, cache, cdrs)
        if len(dataset) == 0:
            raise ValueError(f"Empty required V2.4 ranking split: {split}")
        datasets[key] = dataset
        loaders[key] = DataLoader(
            dataset,
            batch_size=cfg.batch_rank,
            shuffle=(split == "train"),
            collate_fn=collate_rank_groups,
            **kwargs,
        )
    return datasets, loaders


def train(cfg: Config, run_name: str, resume: str = "") -> dict[str, Any]:
    if resume and clean(cfg.init_checkpoint):
        raise ValueError("Use either --resume or --init-checkpoint, not both")
    paths = validate_inputs(cfg)
    cache = ESM2Cache(paths["esm2_cache_manifest"], cfg.esm_dim)
    cdrs = CDRMaskStore(paths["cdr_mask_csv"])
    random.seed(cfg.seed)
    np.random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.cuda.manual_seed_all(cfg.seed)
        torch.set_float32_matmul_precision("high")
    root = Path(cfg.root).resolve()
    out_root = root / cfg.out_root
    run_id = run_name or time.strftime("phase2_v2_4_%Y%m%d_%H%M%S_seed") + str(cfg.seed)
    run_dir = out_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config_resolved.json").write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
    datasets, loaders = make_loaders(cfg, paths, cache, cdrs)
    model = CrossContactNetV24(cfg)
    warmstart: dict[str, Any] = {"status": "not_requested"}
    if clean(cfg.init_checkpoint):
        init_path = _resolve(root, cfg.init_checkpoint)
        if not init_path.exists():
            raise FileNotFoundError(f"Missing V2.3 warm-start checkpoint: {init_path}")
        warmstart = {"status": "loaded", **load_v23_warmstart(model, init_path)}
    elif cfg.warmstart_required and not resume:
        raise ValueError("V2.4 warmstart_required=true but init_checkpoint is empty")
    model = model.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    scaler = torch.amp.GradScaler("cuda", enabled=(cfg.use_amp and device.type == "cuda"))
    start_epoch = 1
    best_score = -1e9
    best_path = run_dir / "best_checkpoint.pt"
    history: list[dict[str, Any]] = []
    resume_best_source = ""
    if resume:
        resume_path = Path(resume).resolve()
        checkpoint = torch.load(resume_path, map_location=device, weights_only=False)
        model.load_state_dict(checkpoint["model"])
        optimizer.load_state_dict(checkpoint["optimizer"])
        if "scaler" in checkpoint:
            scaler.load_state_dict(checkpoint["scaler"])
        start_epoch = int(checkpoint.get("epoch", 0)) + 1
        best_score = float(checkpoint.get("best_score", -1e9))
        history = list(checkpoint.get("history", []))
        prior_best, prior_path = restore_resume_best_checkpoint(resume_path, checkpoint, best_path, device)
        best_score = max(best_score, float(prior_best.get("best_score", -1e9)))
        resume_best_source = str(prior_path)

    for epoch in range(start_epoch, cfg.epochs + 1):
        model.train()
        total = 0.0
        steps = 0
        accumulated = 0
        task_totals = {"contact": 0.0, "site": 0.0, "pair_bce": 0.0, "rank_listwise": 0.0, "rank_typed_margin": 0.0}
        site_iter = iter(loaders["site_train"])
        pair_iter = iter(loaders["pair_train"])
        rank_iter = iter(loaders["rank_train"])
        optimizer.zero_grad(set_to_none=True)
        for step_index, contact_batch in enumerate(loaders["contact_train"], start=1):
            try:
                site_batch = next(site_iter)
            except StopIteration:
                site_iter = iter(loaders["site_train"])
                site_batch = next(site_iter)
            try:
                pair_batch = next(pair_iter)
            except StopIteration:
                pair_iter = iter(loaders["pair_train"])
                pair_batch = next(pair_iter)
            try:
                rank_batch = next(rank_iter)
            except StopIteration:
                rank_iter = iter(loaders["rank_train"])
                rank_batch = next(rank_iter)
            amp_enabled = cfg.use_amp and device.type == "cuda"
            loss_parts: list[torch.Tensor] = []
            task = "contact"
            try:
                with torch.amp.autocast(device_type=device.type, enabled=amp_enabled):
                    cv = contact_batch["vhh"].to(device)
                    cc = contact_batch["vhh_cdr"].to(device)
                    ca = contact_batch["antigen"].to(device)
                    chv, cha, _, _ = model.encode(cv, cc, ca)
                    contact_value = cfg.contact_weight * contact_loss(model, chv, cha, contact_batch, cfg, device)
                ensure_finite_loss(task, contact_value)
                scaler.scale(contact_value / max(cfg.grad_accum_steps, 1)).backward()
                loss_parts.append(contact_value.detach())
                task_totals[task] += float(contact_value.detach().cpu())
                del cv, cc, ca, chv, cha, contact_value

                task = "site"
                with torch.amp.autocast(device_type=device.type, enabled=amp_enabled):
                    sv = site_batch["vhh"].to(device)
                    sc = site_batch["vhh_cdr"].to(device)
                    sa = site_batch["antigen"].to(device)
                    para = site_batch["paratope"].to(device)
                    epi = site_batch["epitope"].to(device)
                    shv, sha, _, _ = model.encode(sv, sc, sa)
                    para_logit, epi_logit = model.site_logits(shv, sha)
                    site_value = cfg.site_weight * (bce_masked(para_logit, para) + bce_masked(epi_logit, epi))
                ensure_finite_loss(task, site_value)
                scaler.scale(site_value / max(cfg.grad_accum_steps, 1)).backward()
                loss_parts.append(site_value.detach())
                task_totals[task] += float(site_value.detach().cpu())
                del sv, sc, sa, para, epi, shv, sha, para_logit, epi_logit, site_value

                task = "pair_bce"
                with torch.amp.autocast(device_type=device.type, enabled=amp_enabled):
                    pair_logits = model.pair_logits(
                        pair_batch["vhh"].to(device), pair_batch["vhh_cdr"].to(device), pair_batch["antigen"].to(device)
                    )
                    pair_value = cfg.pair_bce_weight * observed_positive_bce(
                        pair_logits, pair_batch["label"].to(device), pair_batch["bce_mask"].to(device)
                    )
                ensure_finite_loss(task, pair_value)
                scaler.scale(pair_value / max(cfg.grad_accum_steps, 1)).backward()
                loss_parts.append(pair_value.detach())
                task_totals[task] += float(pair_value.detach().cpu())
                del pair_logits, pair_value

                with torch.amp.autocast(device_type=device.type, enabled=amp_enabled):
                    positive_logits = model.pair_logits(
                        rank_batch["pos_vhh"].to(device), rank_batch["pos_cdr"].to(device), rank_batch["pos_antigen"].to(device)
                    )
                    negative_logits = model.pair_logits(
                        rank_batch["neg_vhh"].to(device), rank_batch["neg_cdr"].to(device), rank_batch["neg_antigen"].to(device)
                    )
                    owners = rank_batch["neg_owner"].to(device)
                    weights = rank_batch["neg_weight"].to(device)
                    margins = rank_batch["neg_margin"].to(device)
                    listwise_value = cfg.listwise_weight * listwise_group_ranking_loss(
                        positive_logits, negative_logits, owners, weights, cfg.ranking_temperature
                    )
                    typed_value = cfg.typed_margin_weight * typed_pairwise_margin_loss(
                        positive_logits, negative_logits, owners, margins, weights
                    )
                for task, value in (("rank_listwise", listwise_value), ("rank_typed_margin", typed_value)):
                    ensure_finite_loss(task, value)
                    scaler.scale(value / max(cfg.grad_accum_steps, 1)).backward(retain_graph=(task == "rank_listwise"))
                    loss_parts.append(value.detach())
                    task_totals[task] += float(value.detach().cpu())
                del positive_logits, negative_logits, owners, weights, margins, listwise_value, typed_value
                accumulated += 1
            except (NonFiniteLossError, torch.cuda.OutOfMemoryError) as exc:
                optimizer.zero_grad(set_to_none=True)
                if device.type == "cuda":
                    torch.cuda.empty_cache()
                diagnostic = {
                    "status": "FAILED",
                    "reason": "cuda_oom" if isinstance(exc, torch.cuda.OutOfMemoryError) else "nonfinite_loss",
                    "message": repr(exc),
                    "task": getattr(exc, "task", task),
                    "epoch": epoch,
                    "step": step_index,
                    "batch_ids": {
                        "contact": contact_batch.get("id", []),
                        "site": site_batch.get("id", []),
                        "pair": pair_batch.get("id", []),
                        "ranking_group": rank_batch.get("group", []),
                    },
                    "device": device_metadata(device),
                }
                write_failure_artifacts(run_dir, model, cfg, diagnostic)
                raise
            if accumulated % max(cfg.grad_accum_steps, 1) == 0:
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
            total += float(torch.stack(loss_parts).sum().cpu())
            steps += 1
            if cfg.log_every_steps > 0 and step_index % cfg.log_every_steps == 0:
                print(json.dumps({"event": "train_progress", "epoch": epoch, "step": step_index, "steps_total": len(loaders["contact_train"]), "mean_loss": total / max(steps, 1)}), flush=True)
        if accumulated % max(cfg.grad_accum_steps, 1) != 0:
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad(set_to_none=True)

        val_contact = eval_contact(model, loaders["contact_val"], device, cfg)
        val_site = eval_site(model, loaders["site_val"], device)
        val_pair = eval_pair_proxy(model, loaders["pair_val"], device)
        val_rank = eval_ranking_groups(model, loaders["rank_val"], device)
        record: dict[str, Any] = {
            "epoch": epoch,
            "train_loss": total / max(steps, 1),
            **{f"train_{name}_loss": value / max(steps, 1) for name, value in task_totals.items()},
            **{f"val_{key}": value for key, value in val_contact.items()},
            **{f"val_{key}": value for key, value in val_site.items()},
            **{f"val_{key}": value for key, value in val_pair.items()},
            **{f"val_{key}": value for key, value in val_rank.items()},
        }
        history.append(record)
        selection_score = (
            cfg.selection_contact_weight * float(record.get("val_contact_auprc", 0.0))
            + cfg.selection_ranking_weight * float(record.get("val_ranking_mrr", 0.0))
            + cfg.selection_hard_negative_weight * float(record.get("val_ranking_hard_negative_win_rate", 0.0))
            + cfg.selection_paratope_weight * float(record.get("val_paratope_auprc", 0.0))
        )
        checkpoint = {
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "scaler": scaler.state_dict(),
            "cfg": asdict(cfg),
            "epoch": epoch,
            "best_score": max(best_score, selection_score),
            "best_checkpoint_path": str(best_path.resolve()),
            "run_id": run_id,
            "history": history,
            "warmstart": warmstart,
            "env": device_metadata(device),
            "schema_version": "phase2_v2_4_listwise_ranking_checkpoint_v1",
        }
        torch.save(checkpoint, run_dir / "last_checkpoint.pt")
        if selection_score > best_score:
            best_score = selection_score
            torch.save(checkpoint, best_path)
        print(json.dumps({
            "epoch": epoch,
            "train_loss": record["train_loss"],
            "val_contact_auprc": record.get("val_contact_auprc"),
            "val_ranking_mrr": record.get("val_ranking_mrr"),
            "val_ranking_mrr_delta_vs_random": record.get("val_ranking_mrr_delta_vs_random"),
            "val_ranking_hit_at_1": record.get("val_ranking_hit_at_1"),
            "val_ranking_hard_negative_win_rate": record.get("val_ranking_hard_negative_win_rate"),
        }), flush=True)

    best_checkpoint = torch.load(best_path, map_location=device, weights_only=False)
    model.load_state_dict(best_checkpoint["model"])
    metrics = {
        "dataset_sizes": {key: len(value) for key, value in datasets.items()},
        "dataset_excluded_unresolved_cdr_rows": {key: int(getattr(value, "excluded_unresolved_cdr_rows", 0)) for key, value in datasets.items()},
        "checkpoint": str(best_path),
        "contact_test": eval_contact(model, loaders["contact_test"], device, cfg),
        "site_test": eval_site(model, loaders["site_test"], device),
        "pair_test": eval_pair_proxy(model, loaders["pair_test"], device),
        "ranking_test": eval_ranking_groups(model, loaders["rank_test"], device),
        "label_boundary": "constructed ranking candidates are proxy contrasts, not verified non-binders",
        "calibration": {"status": "NOT_APPLICABLE", "reason": "no verified positive-and-negative probability labels"},
    }
    environment = device_metadata(device) | {
        "best_epoch": int(best_checkpoint.get("epoch", -1)),
        "run_id": run_id,
        "resume_best_source": resume_best_source,
    }
    (run_dir / "metrics_history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    (run_dir / "test_metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    (run_dir / "run_summary.json").write_text(json.dumps({
        "history": history,
        "test_metrics": metrics,
        "env": environment,
        "warmstart": warmstart,
        "strict_inputs": {key: str(value) for key, value in paths.items()},
    }, indent=2, sort_keys=True), encoding="utf-8")
    reports_dir = out_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "phase2_v2_4_metrics.json").write_text((run_dir / "run_summary.json").read_text(), encoding="utf-8")
    canonical = out_root / "checkpoints/phase2_v2_4_best_checkpoint.pt"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_checkpoint, canonical)
    return {"status": "PASS", "run_id": run_id, "best_epoch": environment["best_epoch"], "metrics": str(run_dir / "test_metrics.json"), "checkpoint": str(best_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--root")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--resume", default="")
    parser.add_argument("--init-checkpoint", default=None)
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--dry-validate", action="store_true")
    for name in ("clustered_site_csv", "pair_csv", "ranking_triplets_csv", "ranking_groups_csv", "pvrig_controls_csv", "contact_jsonl", "esm2_cache_manifest", "cdr_mask_csv"):
        parser.add_argument("--" + name.replace("_", "-"), default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    if args.root is not None:
        cfg.root = args.root
    if args.epochs is not None:
        cfg.epochs = args.epochs
    if args.seed is not None:
        cfg.seed = args.seed
    if args.init_checkpoint is not None:
        cfg.init_checkpoint = args.init_checkpoint
    for name in ("clustered_site_csv", "pair_csv", "ranking_triplets_csv", "ranking_groups_csv", "pvrig_controls_csv", "contact_jsonl", "esm2_cache_manifest", "cdr_mask_csv"):
        value = getattr(args, name)
        if value is not None:
            setattr(cfg, name, value)
    if args.dry_validate:
        paths = validate_inputs(cfg)
        print(json.dumps({"status": "VALIDATED", "strict_inputs": {key: str(value) for key, value in paths.items()}}, indent=2, sort_keys=True))
        return
    print(json.dumps(train(cfg, args.run_name, args.resume), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
