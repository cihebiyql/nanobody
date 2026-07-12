#!/usr/bin/env python3
"""Train the cluster-safe residue-level V3-G generic binding prior.

V3-G2 starts from the validated V2.3 contact/site checkpoint, trains on real
binder/non-binder labels, replays structure contact/site supervision, and
measures whether scores change when the antigen family changes. Its output is
a generic binding prior, not PVRIG binding, affinity, or blocking truth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.nn.utils.rnn import pad_sequence
from torch.utils.data import DataLoader, Dataset

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import train_phase2_v2_3 as v23  # noqa: E402

DEFAULT_BINDING = EXP_DIR / "prepared/phase2_v3_g2/binding_cluster_safe_v1.csv"
DEFAULT_CACHE = EXP_DIR / "prepared/phase2_v3_g2/esm2_8m_residue_cache_v1/manifest.csv"
DEFAULT_CDR = EXP_DIR / "prepared/phase2_v3_g2/vhh_cdr_type_masks_v1.csv"
DEFAULT_DATA_AUDIT = EXP_DIR / "prepared/phase2_v3_g2/prepare_audit_v1.json"
DEFAULT_CHECKPOINT = EXP_DIR / "checkpoints/phase2_v2_3_strict_seed67_best_checkpoint.pt"
DEFAULT_SITE = EXP_DIR / "data_splits/zym_site_split_manifest_v2_clustered.csv"
DEFAULT_CONTACT = EXP_DIR / "prepared/structure_contact_maps_v3_clustered.jsonl"
DEFAULT_OUT = EXP_DIR / "runs/phase2_v3_g2_generic"
CLAIM_BOUNDARY = "generic_binding_prior_not_pvrig_binding_affinity_or_blocking_truth"


@dataclass
class TrainConfig:
    binding_csv: str = str(DEFAULT_BINDING)
    cache_manifest: str = str(DEFAULT_CACHE)
    cdr_mask_csv: str = str(DEFAULT_CDR)
    data_audit_json: str = str(DEFAULT_DATA_AUDIT)
    source_checkpoint: str = str(DEFAULT_CHECKPOINT)
    site_csv: str = str(DEFAULT_SITE)
    contact_jsonl: str = str(DEFAULT_CONTACT)
    out_root: str = str(DEFAULT_OUT)
    seed: int = 83
    epochs: int = 4
    batch_size: int = 64
    contrast_batch_size: int = 24
    replay_batch_size: int = 16
    head_learning_rate: float = 2e-4
    backbone_learning_rate: float = 3e-5
    weight_decay: float = 1e-4
    target_swap_weight: float = 0.10
    target_swap_margin: float = 0.10
    observed_contrast_weight: float = 0.25
    observed_contrast_margin: float = 0.15
    observed_contrast_every: int = 4
    replay_weight: float = 0.30
    replay_every: int = 4
    early_stopping_patience: int = 2
    max_train_batches: int = 0
    max_eval_batches: int = 0
    max_cached_shards: int = 0
    use_amp: bool = True
    device: str = "cuda"
    num_workers: int = 0
    log_every_steps: int = 100


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_key(value: str) -> str:
    return hashlib.sha256(f"phase2_v3_g2\t{value}".encode()).hexdigest()


class CompactESM2Cache(v23.ESM2Cache):
    """Keep cached fp16 shards compact instead of expanding every shard."""

    def __init__(self, manifest_path: Path, expected_dim: int, max_cached_shards: int = 0):
        super().__init__(manifest_path, expected_dim)
        self.max_cached_shards = max_cached_shards
        self._shards = OrderedDict()

    def get(self, sequence: str, max_len: int) -> torch.Tensor:
        digest = v23.seq_hash(sequence)
        row = self.rows.get(digest)
        if row is None:
            raise KeyError(f"Missing ESM2 cache row for sequence hash {digest}")
        shard_path = (self.manifest_path.parent / row["shard_path"]).resolve()
        if not shard_path.exists():
            raise FileNotFoundError(f"Missing ESM2 shard for {digest}: {shard_path}")
        if shard_path not in self._shards:
            payload = torch.load(shard_path, map_location="cpu", weights_only=False)
            self._shards[shard_path] = {key: value.detach().contiguous() for key, value in payload.items()}
            if self.max_cached_shards and len(self._shards) > self.max_cached_shards:
                self._shards.popitem(last=False)
        else:
            self._shards.move_to_end(shard_path)
        tensor = self._shards[shard_path][row.get("shard_key") or digest]
        if tensor.ndim != 2 or tensor.shape[1] != self.expected_dim:
            raise ValueError(f"ESM2 embedding for {digest} has invalid shape {tuple(tensor.shape)}")
        cached_len = self.cached_length_for(row)
        if tensor.shape[0] != cached_len:
            raise ValueError(f"ESM2 cached length mismatch for {digest}")
        return tensor[: min(max_len, cached_len)].contiguous()


def read_binding(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {
        "sample_id",
        "dataset_id",
        "target_id",
        "split",
        "cluster_id",
        "vhh_sequence",
        "target_sequence",
        "sequence_sha256",
        "target_sequence_sha256",
        "label",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Binding input is missing {sorted(missing)}")
    if set(frame["split"].astype(str)) != {"train", "dev", "test"}:
        raise ValueError("V3-G2 requires train/dev/test splits")
    if frame["sample_id"].duplicated().any():
        raise ValueError("V3-G2 binding input contains duplicate sample IDs")
    if not set(frame["label"].astype(int).unique()).issubset({0, 1}):
        raise ValueError("V3-G2 requires binary real-assay labels")
    for field in ("sequence_sha256", "cluster_id"):
        split_sets = {
            split: set(frame.loc[frame["split"] == split, field].astype(str))
            for split in ("train", "dev", "test")
        }
        if any(
            split_sets[left] & split_sets[right]
            for left, right in (("train", "dev"), ("train", "test"), ("dev", "test"))
        ):
            raise ValueError(f"Cross-split {field} leakage detected")
    return frame


def cross_family_targets(frame: pd.DataFrame) -> dict[str, tuple[str, bool]]:
    targets = {
        family: sorted(set(group["target_sequence"].astype(str)), key=stable_key)
        for family, group in frame.groupby("dataset_id")
    }
    families = sorted(targets)
    output: dict[str, tuple[str, bool]] = {}
    for index, family in enumerate(families):
        if len(families) < 2:
            output[family] = (targets[family][0], False)
        else:
            other = families[(index + 1) % len(families)]
            output[family] = (targets[other][0], True)
    return output


class RealBindingDataset(Dataset):
    def __init__(
        self,
        frame: pd.DataFrame,
        split: str,
        cfg: v23.Config,
        cache: CompactESM2Cache,
        cdrs: v23.CDRMaskStore,
    ):
        data = frame[frame["split"].astype(str) == split].copy()
        if split != "train":
            data["_order"] = data["sample_id"].astype(str).map(stable_key)
            data = data.sort_values("_order").drop(columns="_order")
        self.frame = data.reset_index(drop=True)
        self.swap_targets = cross_family_targets(frame)
        self.cfg = cfg
        self.cache = cache
        self.cdrs = cdrs
        self.unresolved_cdr_rows = int((~self.frame["vhh_sequence"].astype(str).map(cdrs.has_cdr3)).sum())

    def __len__(self) -> int:
        return len(self.frame)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.frame.loc[index]
        vhh_sequence = str(row["vhh_sequence"])
        target_sequence = str(row["target_sequence"])
        vhh = self.cache.get(vhh_sequence, self.cfg.max_vhh_len)
        cdr = self.cdrs.get(vhh_sequence, self.cfg.max_vhh_len)[: len(vhh)]
        swap_sequence, swap_valid = self.swap_targets[str(row["dataset_id"])]
        return {
            "sample_id": str(row["sample_id"]),
            "dataset_id": str(row["dataset_id"]),
            "target_id": str(row["target_id"]),
            "vhh": vhh,
            "cdr": cdr,
            "antigen": self.cache.get(target_sequence, self.cfg.max_antigen_len),
            "swap_antigen": self.cache.get(swap_sequence, self.cfg.max_antigen_len),
            "swap_valid": swap_valid,
            "label": float(row["label"]),
        }


def binding_collate(batch: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "sample_id": [row["sample_id"] for row in batch],
        "dataset_id": [row["dataset_id"] for row in batch],
        "target_id": [row["target_id"] for row in batch],
        "vhh": pad_sequence([row["vhh"] for row in batch], batch_first=True),
        "cdr": pad_sequence([row["cdr"] for row in batch], batch_first=True, padding_value=v23.PAD_CDR),
        "antigen": pad_sequence([row["antigen"] for row in batch], batch_first=True),
        "swap_antigen": pad_sequence([row["swap_antigen"] for row in batch], batch_first=True),
        "swap_valid": torch.tensor([row["swap_valid"] for row in batch], dtype=torch.bool),
        "label": torch.tensor([row["label"] for row in batch], dtype=torch.float32),
    }


def build_observed_contrasts(frame: pd.DataFrame, split: str, max_per_vhh: int = 4) -> pd.DataFrame:
    data = frame[frame["split"].astype(str) == split]
    label_diversity = data.groupby("sequence_sha256")["label"].nunique()
    eligible = set(label_diversity[label_diversity > 1].index.astype(str))
    data = data[data["sequence_sha256"].astype(str).isin(eligible)]
    rows = []
    for sequence_sha, group in data.groupby("sequence_sha256", sort=False):
        positives = group[group["label"].astype(int) == 1]
        negatives = group[group["label"].astype(int) == 0]
        candidates = [
            (positive, negative)
            for _, positive in positives.iterrows()
            for _, negative in negatives.iterrows()
            if str(positive["target_sequence_sha256"]) != str(negative["target_sequence_sha256"])
        ]
        candidates.sort(key=lambda pair: stable_key(f"{pair[0]['sample_id']}|{pair[1]['sample_id']}"))
        for positive, negative in candidates[:max_per_vhh]:
            rows.append(
                {
                    "contrast_id": f"{positive['sample_id']}__gt__{negative['sample_id']}",
                    "sequence_sha256": str(sequence_sha),
                    "vhh_sequence": str(positive["vhh_sequence"]),
                    "positive_target_sequence": str(positive["target_sequence"]),
                    "negative_target_sequence": str(negative["target_sequence"]),
                }
            )
    return pd.DataFrame(rows)


class ObservedContrastDataset(Dataset):
    def __init__(self, frame: pd.DataFrame, cfg: v23.Config, cache: CompactESM2Cache, cdrs: v23.CDRMaskStore):
        self.frame = frame.reset_index(drop=True)
        self.cfg = cfg
        self.cache = cache
        self.cdrs = cdrs

    def __len__(self) -> int:
        return len(self.frame)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.frame.loc[index]
        sequence = str(row["vhh_sequence"])
        vhh = self.cache.get(sequence, self.cfg.max_vhh_len)
        return {
            "contrast_id": str(row["contrast_id"]),
            "vhh": vhh,
            "cdr": self.cdrs.get(sequence, self.cfg.max_vhh_len)[: len(vhh)],
            "positive_antigen": self.cache.get(str(row["positive_target_sequence"]), self.cfg.max_antigen_len),
            "negative_antigen": self.cache.get(str(row["negative_target_sequence"]), self.cfg.max_antigen_len),
        }


def contrast_collate(batch: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "contrast_id": [row["contrast_id"] for row in batch],
        "vhh": pad_sequence([row["vhh"] for row in batch], batch_first=True),
        "cdr": pad_sequence([row["cdr"] for row in batch], batch_first=True, padding_value=v23.PAD_CDR),
        "positive_antigen": pad_sequence([row["positive_antigen"] for row in batch], batch_first=True),
        "negative_antigen": pad_sequence([row["negative_antigen"] for row in batch], batch_first=True),
    }


def macro_target_auprc(labels: np.ndarray, scores: np.ndarray, targets: Sequence[str]) -> tuple[float, dict[str, float]]:
    target_array = np.asarray(targets)
    values = {}
    for target in sorted(set(targets)):
        mask = target_array == target
        if len(set(labels[mask].tolist())) == 2:
            values[target] = v23.auprc(labels[mask], scores[mask])
    return (float(np.mean(list(values.values()))) if values else 0.0), values


def model_inputs(batch: Mapping[str, Any], device: torch.device) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    dtype = torch.float16 if device.type == "cuda" else torch.float32
    return (
        batch["vhh"].to(device=device, dtype=dtype),
        batch["cdr"].to(device),
        batch["antigen"].to(device=device, dtype=dtype),
    )


def next_or_restart(iterator: Iterator[Any], loader: DataLoader) -> tuple[Any, Iterator[Any]]:
    try:
        return next(iterator), iterator
    except StopIteration:
        iterator = iter(loader)
        return next(iterator), iterator


def evaluate_binding(
    model: v23.CrossContactNetV23,
    loader: DataLoader,
    device: torch.device,
    use_amp: bool,
    max_batches: int,
) -> tuple[dict[str, Any], list[dict[str, object]]]:
    model.eval()
    labels: list[float] = []
    scores: list[float] = []
    swap_scores: list[float] = []
    swap_valid: list[bool] = []
    sample_ids: list[str] = []
    targets: list[str] = []
    datasets: list[str] = []
    with torch.inference_mode():
        for batch_index, batch in enumerate(loader, start=1):
            if max_batches and batch_index > max_batches:
                break
            vhh, cdr, antigen = model_inputs(batch, device)
            dtype = torch.float16 if device.type == "cuda" else torch.float32
            swapped = batch["swap_antigen"].to(device=device, dtype=dtype)
            with torch.amp.autocast(device_type=device.type, enabled=use_amp and device.type == "cuda"):
                logits = model.pair_logits(vhh, cdr, antigen)
                swap_logits = model.pair_logits(vhh, cdr, swapped)
            scores.extend(torch.sigmoid(logits).float().cpu().tolist())
            swap_scores.extend(torch.sigmoid(swap_logits).float().cpu().tolist())
            labels.extend(batch["label"].tolist())
            swap_valid.extend(batch["swap_valid"].tolist())
            sample_ids.extend(batch["sample_id"])
            targets.extend(batch["target_id"])
            datasets.extend(batch["dataset_id"])
    y = np.asarray(labels, dtype=np.int64)
    score = np.asarray(scores, dtype=np.float64)
    swapped = np.asarray(swap_scores, dtype=np.float64)
    valid = np.asarray(swap_valid, dtype=bool)
    positive = (y == 1) & valid
    metrics: dict[str, Any] = v23.binary_metrics(y, score)
    macro, per_target = macro_target_auprc(y, score, targets)
    metrics.update(
        {
            "macro_target_auprc": macro,
            "per_target_auprc": per_target,
            "target_swap_valid_rows": int(valid.sum()),
            "target_swap_mean_abs_delta": float(np.mean(np.abs(score[valid] - swapped[valid]))) if valid.any() else 0.0,
            "positive_true_minus_cross_family_swap": float(np.mean(score[positive] - swapped[positive])) if positive.any() else 0.0,
            "positive_cross_family_swap_win_rate": float(np.mean(score[positive] > swapped[positive])) if positive.any() else 0.0,
        }
    )
    for family in sorted(set(datasets)):
        mask = np.asarray(datasets) == family
        metrics[f"dataset_{family}_auprc"] = v23.auprc(y[mask], score[mask])
    rows = [
        {
            "sample_id": sample_id,
            "dataset_id": dataset,
            "target_id": target,
            "label": int(label),
            "score": float(value),
            "cross_family_swap_score": float(swap_value),
            "cross_family_swap_valid": bool(valid_value),
        }
        for sample_id, dataset, target, label, value, swap_value, valid_value in zip(
            sample_ids, datasets, targets, labels, scores, swap_scores, swap_valid, strict=True
        )
    ]
    return metrics, rows


def evaluate_contrasts(
    model: v23.CrossContactNetV23,
    loader: DataLoader,
    device: torch.device,
    use_amp: bool,
    max_batches: int,
) -> dict[str, float]:
    margins = []
    model.eval()
    dtype = torch.float16 if device.type == "cuda" else torch.float32
    with torch.inference_mode():
        for batch_index, batch in enumerate(loader, start=1):
            if max_batches and batch_index > max_batches:
                break
            vhh = batch["vhh"].to(device=device, dtype=dtype)
            cdr = batch["cdr"].to(device)
            positive = batch["positive_antigen"].to(device=device, dtype=dtype)
            negative = batch["negative_antigen"].to(device=device, dtype=dtype)
            with torch.amp.autocast(device_type=device.type, enabled=use_amp and device.type == "cuda"):
                pos = model.pair_logits(vhh, cdr, positive)
                neg = model.pair_logits(vhh, cdr, negative)
            margins.extend((pos - neg).float().cpu().tolist())
    values = np.asarray(margins, dtype=np.float64)
    return {
        "observed_target_contrast_n": float(len(values)),
        "observed_target_contrast_win_rate": float(np.mean(values > 0)) if len(values) else 0.0,
        "observed_target_contrast_mean_logit_margin": float(np.mean(values)) if len(values) else 0.0,
    }


def optimizer_groups(model: v23.CrossContactNetV23, cfg: TrainConfig) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    head_names = {f"pair.{name}" for name, _ in model.pair.named_parameters()}
    head = []
    backbone = []
    names = {"head": [], "backbone": []}
    for name, parameter in model.named_parameters():
        if name in head_names:
            head.append(parameter)
            names["head"].append(name)
        else:
            backbone.append(parameter)
            names["backbone"].append(name)
    return [
        {"params": head, "lr": cfg.head_learning_rate},
        {"params": backbone, "lr": cfg.backbone_learning_rate},
    ], names


def validate_inputs(cfg: TrainConfig) -> dict[str, Any]:
    paths = {
        "binding": Path(cfg.binding_csv),
        "cache": Path(cfg.cache_manifest),
        "cdr": Path(cfg.cdr_mask_csv),
        "audit": Path(cfg.data_audit_json),
        "checkpoint": Path(cfg.source_checkpoint),
        "site": Path(cfg.site_csv),
        "contact": Path(cfg.contact_jsonl),
    }
    for path in paths.values():
        if not path.exists():
            raise FileNotFoundError(path)
    audit = json.loads(paths["audit"].read_text(encoding="utf-8"))
    if audit.get("status") != "PASS_CLUSTER_SAFE_BINDING_DATA_READY":
        raise ValueError("V3-G2 data audit is not PASS")
    frame = read_binding(paths["binding"])
    cache_manifest = pd.read_csv(paths["cache"], usecols=["sequence_sha256", "shard_path"])
    cache_hashes = set(cache_manifest["sequence_sha256"].astype(str))
    required_cache = set(frame["sequence_sha256"].astype(str)) | set(frame["target_sequence_sha256"].astype(str))
    missing_cache = required_cache - cache_hashes
    if missing_cache:
        raise ValueError(f"V3-G2 residue cache is missing {len(missing_cache)} sequences")
    cdr_hashes = set(pd.read_csv(paths["cdr"], usecols=["sequence_hash"])["sequence_hash"].astype(str))
    missing_cdr = set(frame["sequence_sha256"].astype(str)) - cdr_hashes
    if missing_cdr:
        raise ValueError(f"V3-G2 CDR masks are missing {len(missing_cdr)} VHH sequences")
    return {"paths": paths, "frame": frame, "audit": audit}


def train(cfg: TrainConfig) -> dict[str, Any]:
    validated = validate_inputs(cfg)
    paths: dict[str, Path] = validated["paths"]
    frame: pd.DataFrame = validated["frame"]
    random.seed(cfg.seed)
    np.random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    if cfg.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    device = torch.device(cfg.device)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(cfg.seed)
        torch.set_float32_matmul_precision("high")
        torch.cuda.reset_peak_memory_stats(device)

    source = torch.load(paths["checkpoint"], map_location="cpu", weights_only=False)
    backbone_cfg = v23.Config(**source["cfg"])
    cache = CompactESM2Cache(paths["cache"], backbone_cfg.esm_dim, cfg.max_cached_shards)
    cdrs = v23.CDRMaskStore(paths["cdr"])
    datasets = {
        split: RealBindingDataset(frame, split, backbone_cfg, cache, cdrs)
        for split in ("train", "dev", "test")
    }
    contrast_frames = {split: build_observed_contrasts(frame, split) for split in ("train", "dev", "test")}
    contrast_datasets = {
        split: ObservedContrastDataset(contrast_frames[split], backbone_cfg, cache, cdrs)
        for split in contrast_frames
    }
    generator = torch.Generator().manual_seed(cfg.seed + 10_000)
    loaders = {
        "train": DataLoader(
            datasets["train"], batch_size=cfg.batch_size, shuffle=True, generator=generator,
            collate_fn=binding_collate, num_workers=cfg.num_workers,
        ),
        "dev": DataLoader(datasets["dev"], batch_size=cfg.batch_size, shuffle=False, collate_fn=binding_collate),
        "test": DataLoader(datasets["test"], batch_size=cfg.batch_size, shuffle=False, collate_fn=binding_collate),
    }
    contrast_loaders = {
        split: DataLoader(
            contrast_datasets[split], batch_size=cfg.contrast_batch_size,
            shuffle=(split == "train"), generator=generator if split == "train" else None,
            collate_fn=contrast_collate,
        )
        for split in contrast_datasets
    }
    replay_site = v23.SiteDataset(paths["site"], "train", backbone_cfg, cache, cdrs)
    replay_contact = v23.ContactDataset(paths["contact"], "train", backbone_cfg, cache, cdrs)
    replay_loaders = {
        "site": DataLoader(replay_site, batch_size=cfg.replay_batch_size, shuffle=True, generator=generator, collate_fn=v23.collate_site),
        "contact": DataLoader(replay_contact, batch_size=cfg.replay_batch_size, shuffle=True, generator=generator, collate_fn=v23.collate_contact),
    }

    model = v23.CrossContactNetV23(backbone_cfg)
    model.load_state_dict(source["model"])
    model.to(device)
    parameter_groups, trainable_names = optimizer_groups(model, cfg)
    optimizer = torch.optim.AdamW(parameter_groups, weight_decay=cfg.weight_decay)
    scaler = torch.amp.GradScaler("cuda", enabled=cfg.use_amp and device.type == "cuda")
    train_positive = float(datasets["train"].frame["label"].astype(float).sum())
    train_negative = float(len(datasets["train"]) - train_positive)
    pos_weight = torch.tensor(min(train_negative / max(train_positive, 1.0), 20.0), device=device)

    run_id = time.strftime("phase2_v3_g2_generic_%Y%m%d_%H%M%S") + f"_seed{cfg.seed}"
    run_dir = Path(cfg.out_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "config_resolved.json").write_text(json.dumps(asdict(cfg), indent=2, sort_keys=True) + "\n")

    baseline_dev, _ = evaluate_binding(model, loaders["dev"], device, cfg.use_amp, cfg.max_eval_batches)
    baseline_contrast = evaluate_contrasts(model, contrast_loaders["dev"], device, cfg.use_amp, cfg.max_eval_batches)
    best_score = -float("inf")
    best_epoch = 0
    best_state = None
    history = []
    stale = 0
    dtype = torch.float16 if device.type == "cuda" else torch.float32
    amp_enabled = cfg.use_amp and device.type == "cuda"
    for epoch in range(1, cfg.epochs + 1):
        model.train()
        contrast_iterator = iter(contrast_loaders["train"])
        replay_iterators = {name: iter(loader) for name, loader in replay_loaders.items()}
        losses = []
        task_losses: dict[str, list[float]] = {"bce": [], "target_swap": [], "observed_contrast": [], "replay": []}
        for step, batch in enumerate(loaders["train"], start=1):
            if cfg.max_train_batches and step > cfg.max_train_batches:
                break
            optimizer.zero_grad(set_to_none=True)
            vhh, cdr, antigen = model_inputs(batch, device)
            swap_antigen = batch["swap_antigen"].to(device=device, dtype=dtype)
            labels = batch["label"].to(device)
            valid_swap = batch["swap_valid"].to(device) & (labels > 0.5)
            with torch.amp.autocast(device_type=device.type, enabled=amp_enabled):
                logits = model.pair_logits(vhh, cdr, antigen)
                bce = nn.functional.binary_cross_entropy_with_logits(logits, labels, pos_weight=pos_weight)
                if valid_swap.any():
                    swapped_logits = model.pair_logits(
                        vhh[valid_swap], cdr[valid_swap], swap_antigen[valid_swap]
                    )
                    target_swap = nn.functional.softplus(
                        cfg.target_swap_margin - (logits[valid_swap] - swapped_logits)
                    ).mean()
                else:
                    target_swap = logits.sum() * 0.0
                loss = bce + cfg.target_swap_weight * target_swap

                contrast_loss = logits.sum() * 0.0
                if (
                    len(contrast_datasets["train"])
                    and cfg.observed_contrast_every > 0
                    and step % cfg.observed_contrast_every == 0
                ):
                    contrast, contrast_iterator = next_or_restart(contrast_iterator, contrast_loaders["train"])
                    cv = contrast["vhh"].to(device=device, dtype=dtype)
                    cc = contrast["cdr"].to(device)
                    cp = contrast["positive_antigen"].to(device=device, dtype=dtype)
                    cn = contrast["negative_antigen"].to(device=device, dtype=dtype)
                    pos_logits = model.pair_logits(cv, cc, cp)
                    neg_logits = model.pair_logits(cv, cc, cn)
                    contrast_loss = nn.functional.softplus(
                        cfg.observed_contrast_margin - (pos_logits - neg_logits)
                    ).mean()
                    loss = loss + cfg.observed_contrast_weight * contrast_loss

                replay_loss = logits.sum() * 0.0
                if cfg.replay_every > 0 and step % cfg.replay_every == 0:
                    replay_name = "contact" if (step // cfg.replay_every) % 2 else "site"
                    replay, replay_iterators[replay_name] = next_or_restart(
                        replay_iterators[replay_name], replay_loaders[replay_name]
                    )
                    if replay_name == "contact":
                        rv = replay["vhh"].to(device=device, dtype=dtype)
                        rc = replay["vhh_cdr"].to(device)
                        ra = replay["antigen"].to(device=device, dtype=dtype)
                        rhv, rha, _, _ = model.encode(rv, rc, ra)
                        replay_loss = v23.contact_loss(model, rhv, rha, replay, backbone_cfg, device)
                    else:
                        rv = replay["vhh"].to(device=device, dtype=dtype)
                        rc = replay["vhh_cdr"].to(device)
                        ra = replay["antigen"].to(device=device, dtype=dtype)
                        rhv, rha, _, _ = model.encode(rv, rc, ra)
                        paratope, epitope = model.site_logits(rhv, rha)
                        replay_loss = v23.bce_masked(paratope, replay["paratope"].to(device)) + v23.bce_masked(
                            epitope, replay["epitope"].to(device)
                        )
                    loss = loss + cfg.replay_weight * replay_loss
            if not torch.isfinite(loss):
                raise RuntimeError(f"Non-finite V3-G2 loss at epoch={epoch} step={step}")
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            losses.append(float(loss.detach().cpu()))
            task_losses["bce"].append(float(bce.detach().cpu()))
            task_losses["target_swap"].append(float(target_swap.detach().cpu()))
            task_losses["observed_contrast"].append(float(contrast_loss.detach().cpu()))
            task_losses["replay"].append(float(replay_loss.detach().cpu()))
            if cfg.log_every_steps and step % cfg.log_every_steps == 0:
                print(json.dumps({"epoch": epoch, "step": step, "mean_loss": statistics.mean(losses)}), flush=True)

        dev_metrics, _ = evaluate_binding(model, loaders["dev"], device, cfg.use_amp, cfg.max_eval_batches)
        dev_contrast = evaluate_contrasts(model, contrast_loaders["dev"], device, cfg.use_amp, cfg.max_eval_batches)
        selection = (
            float(dev_metrics["macro_target_auprc"])
            + 0.10 * float(dev_contrast["observed_target_contrast_win_rate"])
            + 0.05 * max(float(dev_metrics["positive_true_minus_cross_family_swap"]), 0.0)
        )
        record = {
            "epoch": epoch,
            "train_loss": statistics.mean(losses),
            "train_task_loss": {name: statistics.mean(values) for name, values in task_losses.items()},
            "dev": dev_metrics,
            "dev_observed_contrast": dev_contrast,
            "selection_score": selection,
        }
        history.append(record)
        print(json.dumps({"event": "epoch_complete", **record}, sort_keys=True), flush=True)
        if selection > best_score + 1e-12:
            best_score = selection
            best_epoch = epoch
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= cfg.early_stopping_patience:
                break
    if best_state is None:
        raise RuntimeError("V3-G2 did not produce a checkpoint")

    model.load_state_dict(best_state)
    dev_metrics, dev_predictions = evaluate_binding(model, loaders["dev"], device, cfg.use_amp, cfg.max_eval_batches)
    test_metrics, test_predictions = evaluate_binding(model, loaders["test"], device, cfg.use_amp, cfg.max_eval_batches)
    dev_contrast = evaluate_contrasts(model, contrast_loaders["dev"], device, cfg.use_amp, cfg.max_eval_batches)
    test_contrast = evaluate_contrasts(model, contrast_loaders["test"], device, cfg.use_amp, cfg.max_eval_batches)
    checkpoint_path = run_dir / "checkpoint.pt"
    torch.save(
        {
            "schema_version": "phase2_v3_g2_generic_checkpoint_v1",
            "model": best_state,
            "backbone_cfg": asdict(backbone_cfg),
            "train_cfg": asdict(cfg),
            "source_checkpoint": str(paths["checkpoint"]),
            "best_epoch": best_epoch,
            "best_selection_score": best_score,
            "claim_boundary": CLAIM_BOUNDARY,
        },
        checkpoint_path,
    )
    pd.DataFrame(dev_predictions).to_csv(run_dir / "dev_predictions.csv", index=False)
    pd.DataFrame(test_predictions).to_csv(run_dir / "test_predictions.csv", index=False)
    summary: dict[str, Any] = {
        "status": "PASS_V3_G2_TRAINING_COMPLETED",
        "schema_version": "phase2_v3_g2_generic_summary_v1",
        "run_dir": str(run_dir),
        "seed": cfg.seed,
        "device": str(device),
        "gpu_name": torch.cuda.get_device_name(device) if device.type == "cuda" else "",
        "cuda_peak_allocated_mib": float(torch.cuda.max_memory_allocated(device)) / 1024**2 if device.type == "cuda" else 0.0,
        "dataset_sizes": {split: len(dataset) for split, dataset in datasets.items()},
        "unresolved_cdr_rows": {split: dataset.unresolved_cdr_rows for split, dataset in datasets.items()},
        "observed_contrast_sizes": {split: len(dataset) for split, dataset in contrast_datasets.items()},
        "trainable_parameter_names": trainable_names,
        "baseline_dev_metrics": baseline_dev,
        "baseline_dev_observed_contrast": baseline_contrast,
        "best_epoch": best_epoch,
        "best_selection_score": best_score,
        "dev_metrics": dev_metrics,
        "dev_observed_contrast": dev_contrast,
        "test_metrics": test_metrics,
        "test_observed_contrast": test_contrast,
        "history": history,
        "artifact_sha256": {
            "binding_csv": sha256_file(paths["binding"]),
            "cache_manifest": sha256_file(paths["cache"]),
            "cdr_mask_csv": sha256_file(paths["cdr"]),
            "data_audit_json": sha256_file(paths["audit"]),
            "source_checkpoint": sha256_file(paths["checkpoint"]),
            "checkpoint": sha256_file(checkpoint_path),
        },
        "formal_readiness": (
            "INTERNAL_CLUSTER_SAFE_RESULT_REQUIRES_MULTI_SEED_AND_EXTERNAL_hTNFa_COMPARISON"
            if not cfg.max_train_batches and not cfg.max_eval_batches
            else "SMOKE_ONLY_TRUNCATED_BATCHES"
        ),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding-csv", default=str(DEFAULT_BINDING))
    parser.add_argument("--cache-manifest", default=str(DEFAULT_CACHE))
    parser.add_argument("--cdr-mask-csv", default=str(DEFAULT_CDR))
    parser.add_argument("--data-audit-json", default=str(DEFAULT_DATA_AUDIT))
    parser.add_argument("--source-checkpoint", default=str(DEFAULT_CHECKPOINT))
    parser.add_argument("--site-csv", default=str(DEFAULT_SITE))
    parser.add_argument("--contact-jsonl", default=str(DEFAULT_CONTACT))
    parser.add_argument("--out-root", default=str(DEFAULT_OUT))
    parser.add_argument("--seed", type=int, default=83)
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--max-train-batches", type=int, default=0)
    parser.add_argument("--max-eval-batches", type=int, default=0)
    parser.add_argument("--max-cached-shards", type=int, default=0)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--dry-validate", action="store_true")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    cfg = TrainConfig(
        binding_csv=args.binding_csv,
        cache_manifest=args.cache_manifest,
        cdr_mask_csv=args.cdr_mask_csv,
        data_audit_json=args.data_audit_json,
        source_checkpoint=args.source_checkpoint,
        site_csv=args.site_csv,
        contact_jsonl=args.contact_jsonl,
        out_root=args.out_root,
        seed=args.seed,
        epochs=args.epochs,
        batch_size=args.batch_size,
        max_train_batches=args.max_train_batches,
        max_eval_batches=args.max_eval_batches,
        max_cached_shards=args.max_cached_shards,
        device=args.device,
    )
    if args.dry_validate:
        validated = validate_inputs(cfg)
        print(
            json.dumps(
                {
                    "status": "PASS_V3_G2_INPUTS_VALIDATED",
                    "rows": len(validated["frame"]),
                    "audit_status": validated["audit"]["status"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    summary = train(cfg)
    print(json.dumps({key: summary[key] for key in ("status", "run_dir", "best_epoch", "formal_readiness")}, indent=2))


if __name__ == "__main__":
    main()
