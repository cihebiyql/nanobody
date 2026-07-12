#!/usr/bin/env python3
"""Smoke-train a real-label binding head on the frozen V2.3 contact backbone.

This is the first V3-G1 integration gate. It trains only the cross-contact
pair head, keeps residue/contact/site parameters frozen, and reports target
shuffle sensitivity. It is not a formal model and does not make PVRIG claims.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

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
DEFAULT_BINDING = EXP_DIR / "prepared/phase2_v3_g1/binding_smoke_train_dev_v1.csv"
DEFAULT_CACHE = EXP_DIR / "prepared/phase2_v3_g1/esm2_8m_smoke_cache/manifest.csv"
DEFAULT_CDR = EXP_DIR / "prepared/phase2_v3_g1/vhh_cdr_type_masks_smoke_v1.csv"
DEFAULT_CHECKPOINT = EXP_DIR / "checkpoints/phase2_v2_3_strict_seed67_best_checkpoint.pt"
DEFAULT_OUT = EXP_DIR / "runs/phase2_v3_g1_binding_smoke"
CLAIM_BOUNDARY = "generic_binding_head_smoke_not_formal_not_pvrig_binding_or_blocking_truth"


@dataclass
class SmokeConfig:
    binding_csv: str = str(DEFAULT_BINDING)
    cache_manifest: str = str(DEFAULT_CACHE)
    cdr_mask_csv: str = str(DEFAULT_CDR)
    source_checkpoint: str = str(DEFAULT_CHECKPOINT)
    out_root: str = str(DEFAULT_OUT)
    seed: int = 73
    epochs: int = 2
    batch_size: int = 12
    learning_rate: float = 3e-4
    weight_decay: float = 1e-4
    target_dependence_weight: float = 0.10
    target_dependence_margin: float = 0.10
    max_train_batches: int = 0
    max_eval_batches: int = 0
    use_amp: bool = True


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RealBindingDataset(Dataset):
    def __init__(self, path: Path, split: str, cfg: v23.Config, cache: v23.ESM2Cache, cdrs: v23.CDRMaskStore):
        frame = pd.read_csv(path)
        frame = frame[frame["split"].astype(str) == split].copy()
        keep = frame["vhh_sequence"].astype(str).map(cdrs.has_cdr3)
        self.excluded_unresolved_cdr_rows = int((~keep).sum())
        self.frame = frame[keep].reset_index(drop=True)
        self.cfg = cfg
        self.cache = cache
        self.cdrs = cdrs

    def __len__(self) -> int:
        return len(self.frame)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.frame.loc[index]
        vhh_sequence = str(row["vhh_sequence"])
        target_sequence = str(row["target_sequence"])
        vhh = self.cache.get(vhh_sequence, self.cfg.max_vhh_len)
        cdr = self.cdrs.get(vhh_sequence, self.cfg.max_vhh_len)[: len(vhh)]
        antigen = self.cache.get(target_sequence, self.cfg.max_antigen_len)
        return {
            "sample_id": str(row["sample_id"]),
            "target_id": str(row["target_id"]),
            "vhh": vhh,
            "cdr": cdr,
            "antigen": antigen,
            "label": float(row["label"]),
        }


def collate_binding(batch: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "sample_id": [row["sample_id"] for row in batch],
        "target_id": [row["target_id"] for row in batch],
        "vhh": pad_sequence([row["vhh"] for row in batch], batch_first=True),
        "cdr": pad_sequence([row["cdr"] for row in batch], batch_first=True, padding_value=v23.PAD_CDR),
        "antigen": pad_sequence([row["antigen"] for row in batch], batch_first=True),
        "label": torch.tensor([row["label"] for row in batch], dtype=torch.float32),
    }


def freeze_for_binding_head_smoke(model: v23.CrossContactNetV23) -> list[str]:
    for parameter in model.parameters():
        parameter.requires_grad = False
    for parameter in model.pair.parameters():
        parameter.requires_grad = True
    return [name for name, parameter in model.named_parameters() if parameter.requires_grad]


def macro_target_auprc(labels: np.ndarray, scores: np.ndarray, targets: Sequence[str]) -> tuple[float, dict[str, float]]:
    values: dict[str, float] = {}
    target_array = np.asarray(targets)
    for target in sorted(set(targets)):
        mask = target_array == target
        y = labels[mask]
        if len(set(y.tolist())) < 2:
            continue
        values[target] = v23.auprc(y, scores[mask])
    return (float(np.mean(list(values.values()))) if values else 0.0), values


def evaluate(
    model: v23.CrossContactNetV23,
    loader: DataLoader,
    device: torch.device,
    use_amp: bool,
    max_batches: int,
) -> tuple[dict[str, Any], list[dict[str, object]]]:
    model.eval()
    labels: list[float] = []
    scores: list[float] = []
    shuffled_scores: list[float] = []
    target_ids: list[str] = []
    sample_ids: list[str] = []
    with torch.inference_mode():
        for batch_index, batch in enumerate(loader, start=1):
            if max_batches and batch_index > max_batches:
                break
            vhh = batch["vhh"].to(device)
            cdr = batch["cdr"].to(device)
            antigen = batch["antigen"].to(device)
            with torch.amp.autocast(device_type=device.type, enabled=use_amp and device.type == "cuda"):
                logits = model.pair_logits(vhh, cdr, antigen)
                shuffled = model.pair_logits(vhh, cdr, antigen.roll(1, dims=0))
            labels.extend(batch["label"].tolist())
            scores.extend(torch.sigmoid(logits).float().cpu().tolist())
            shuffled_scores.extend(torch.sigmoid(shuffled).float().cpu().tolist())
            target_ids.extend(batch["target_id"])
            sample_ids.extend(batch["sample_id"])
    y = np.asarray(labels, dtype=np.int64)
    score = np.asarray(scores, dtype=np.float64)
    shuffled = np.asarray(shuffled_scores, dtype=np.float64)
    metrics = v23.binary_metrics(y, score)
    macro, per_target = macro_target_auprc(y, score, target_ids)
    positive = y == 1
    metrics.update(
        {
            "macro_target_auprc": macro,
            "per_target_auprc": per_target,
            "target_shuffle_mean_abs_delta": float(np.mean(np.abs(score - shuffled))),
            "positive_true_minus_target_shuffle": float(np.mean(score[positive] - shuffled[positive])) if positive.any() else 0.0,
        }
    )
    rows = [
        {
            "sample_id": sample_id,
            "target_id": target,
            "label": int(label),
            "score": float(value),
            "target_shuffle_score": float(shuffle_value),
        }
        for sample_id, target, label, value, shuffle_value in zip(
            sample_ids, target_ids, labels, scores, shuffled_scores, strict=True
        )
    ]
    return metrics, rows


def train(cfg: SmokeConfig) -> dict[str, Any]:
    random.seed(cfg.seed)
    np.random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.cuda.manual_seed_all(cfg.seed)
        torch.set_float32_matmul_precision("high")

    source = torch.load(cfg.source_checkpoint, map_location="cpu", weights_only=False)
    backbone_cfg = v23.Config(**source["cfg"])
    cache = v23.ESM2Cache(Path(cfg.cache_manifest), backbone_cfg.esm_dim)
    cdrs = v23.CDRMaskStore(Path(cfg.cdr_mask_csv))
    datasets = {
        split: RealBindingDataset(Path(cfg.binding_csv), split, backbone_cfg, cache, cdrs)
        for split in ("train", "dev")
    }
    generator = torch.Generator().manual_seed(cfg.seed)
    loaders = {
        "train": DataLoader(
            datasets["train"],
            batch_size=cfg.batch_size,
            shuffle=True,
            generator=generator,
            collate_fn=collate_binding,
            num_workers=0,
        ),
        "dev": DataLoader(
            datasets["dev"],
            batch_size=cfg.batch_size,
            shuffle=False,
            collate_fn=collate_binding,
            num_workers=0,
        ),
    }
    model = v23.CrossContactNetV23(backbone_cfg)
    model.load_state_dict(source["model"])
    trainable = freeze_for_binding_head_smoke(model)
    model.to(device)
    optimizer = torch.optim.AdamW(
        (parameter for parameter in model.parameters() if parameter.requires_grad),
        lr=cfg.learning_rate,
        weight_decay=cfg.weight_decay,
    )
    scaler = torch.amp.GradScaler("cuda", enabled=cfg.use_amp and device.type == "cuda")

    run_id = time.strftime("phase2_v3_g1_binding_smoke_%Y%m%d_%H%M%S") + f"_seed{cfg.seed}"
    run_dir = Path(cfg.out_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "config_resolved.json").write_text(json.dumps(asdict(cfg), indent=2, sort_keys=True) + "\n")
    baseline_metrics, _ = evaluate(model, loaders["dev"], device, cfg.use_amp, cfg.max_eval_batches)
    history: list[dict[str, Any]] = []
    best_metric = -1.0
    best_state: dict[str, torch.Tensor] | None = None
    for epoch in range(1, cfg.epochs + 1):
        model.eval()
        model.pair.train()
        losses: list[float] = []
        bce_losses: list[float] = []
        dependence_losses: list[float] = []
        for batch_index, batch in enumerate(loaders["train"], start=1):
            if cfg.max_train_batches and batch_index > cfg.max_train_batches:
                break
            vhh = batch["vhh"].to(device)
            cdr = batch["cdr"].to(device)
            antigen = batch["antigen"].to(device)
            labels = batch["label"].to(device)
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast(device_type=device.type, enabled=cfg.use_amp and device.type == "cuda"):
                logits = model.pair_logits(vhh, cdr, antigen)
                positive = labels.sum().clamp_min(1.0)
                negative = (len(labels) - labels.sum()).clamp_min(1.0)
                bce = nn.functional.binary_cross_entropy_with_logits(
                    logits,
                    labels,
                    pos_weight=(negative / positive).clamp(max=10.0),
                )
                shuffled_logits = model.pair_logits(vhh, cdr, antigen.roll(1, dims=0))
                target_ids = batch["target_id"]
                different = torch.tensor(
                    [target_ids[index] != target_ids[index - 1] for index in range(len(target_ids))],
                    dtype=torch.bool,
                    device=device,
                )
                mask = (labels > 0.5) & different
                dependence = (
                    nn.functional.softplus(cfg.target_dependence_margin - (logits[mask] - shuffled_logits[mask])).mean()
                    if mask.any()
                    else logits.sum() * 0.0
                )
                loss = bce + cfg.target_dependence_weight * dependence
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            nn.utils.clip_grad_norm_((parameter for parameter in model.parameters() if parameter.requires_grad), 1.0)
            scaler.step(optimizer)
            scaler.update()
            losses.append(float(loss.detach().cpu()))
            bce_losses.append(float(bce.detach().cpu()))
            dependence_losses.append(float(dependence.detach().cpu()))
        metrics, _ = evaluate(model, loaders["dev"], device, cfg.use_amp, cfg.max_eval_batches)
        record = {
            "epoch": epoch,
            "train_loss": statistics.mean(losses),
            "train_bce": statistics.mean(bce_losses),
            "train_target_dependence": statistics.mean(dependence_losses),
            "dev": metrics,
        }
        history.append(record)
        print(json.dumps(record, sort_keys=True), flush=True)
        if metrics["macro_target_auprc"] > best_metric:
            best_metric = float(metrics["macro_target_auprc"])
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
    if best_state is None:
        raise RuntimeError("No smoke checkpoint produced")
    model.load_state_dict(best_state)
    final_metrics, predictions = evaluate(model, loaders["dev"], device, cfg.use_amp, cfg.max_eval_batches)
    checkpoint_path = run_dir / "checkpoint.pt"
    torch.save(
        {
            "schema_version": "phase2_v3_g1_binding_head_smoke_checkpoint_v1",
            "model": best_state,
            "backbone_cfg": asdict(backbone_cfg),
            "smoke_cfg": asdict(cfg),
            "source_checkpoint": cfg.source_checkpoint,
            "trainable_parameters": trainable,
            "claim_boundary": CLAIM_BOUNDARY,
        },
        checkpoint_path,
    )
    pd.DataFrame(predictions).to_csv(run_dir / "dev_predictions.csv", index=False)
    summary: dict[str, Any] = {
        "status": "PASS_SMOKE_TRAINING_COMPLETED",
        "schema_version": "phase2_v3_g1_binding_head_smoke_summary_v1",
        "run_dir": str(run_dir),
        "device": str(device),
        "gpu_name": torch.cuda.get_device_name(device) if device.type == "cuda" else "",
        "dataset_sizes": {key: len(value) for key, value in datasets.items()},
        "excluded_unresolved_cdr_rows": {
            key: value.excluded_unresolved_cdr_rows for key, value in datasets.items()
        },
        "trainable_parameters": trainable,
        "baseline_dev_metrics": baseline_metrics,
        "final_dev_metrics": final_metrics,
        "history": history,
        "artifact_sha256": {
            "binding_csv": sha256_file(Path(cfg.binding_csv)),
            "cache_manifest": sha256_file(Path(cfg.cache_manifest)),
            "cdr_mask_csv": sha256_file(Path(cfg.cdr_mask_csv)),
            "source_checkpoint": sha256_file(Path(cfg.source_checkpoint)),
            "checkpoint": sha256_file(checkpoint_path),
        },
        "formal_readiness": "NOT_READY_HEAD_ONLY_SMOKE_AND_SOURCE_SPLIT_HAS_EXACT_VHH_OVERLAP",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding-csv", default=str(DEFAULT_BINDING))
    parser.add_argument("--cache-manifest", default=str(DEFAULT_CACHE))
    parser.add_argument("--cdr-mask-csv", default=str(DEFAULT_CDR))
    parser.add_argument("--source-checkpoint", default=str(DEFAULT_CHECKPOINT))
    parser.add_argument("--out-root", default=str(DEFAULT_OUT))
    parser.add_argument("--seed", type=int, default=73)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument("--max-train-batches", type=int, default=0)
    parser.add_argument("--max-eval-batches", type=int, default=0)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    cfg = SmokeConfig(**vars(args))
    summary = train(cfg)
    print(json.dumps({"status": summary["status"], "run_dir": summary["run_dir"]}, sort_keys=True))


if __name__ == "__main__":
    main()
