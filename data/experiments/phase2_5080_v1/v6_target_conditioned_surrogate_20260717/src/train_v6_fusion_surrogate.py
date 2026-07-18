#!/usr/bin/env python3
"""Train candidate-level V6 sequence/structure residual models with whole-parent OOF."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import random
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset, Sampler

CLAIM = (
    "Development approximation of independent dual-receptor computational Docking "
    "geometry; not binding, affinity, competition, experimental blocking, or Docking Gold."
)
METADATA = {
    "schema_version", "candidate_id", "sequence_sha256", "sequence",
    "parent_framework_cluster", "target_patch_id", "design_mode", "cdr1", "cdr2", "cdr3",
    "teacher_source", "teacher_reliability", "sample_weight", "outer_fold",
    "R_8X6B", "R_9E6Y", "R_dual_min", "teacher_uncertainty",
    "monomer_sha256", "technical_reasons", "claim_boundary",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temp.replace(path)


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def _average_ranks(values: np.ndarray) -> np.ndarray:
    """Return deterministic 1-based average ranks without a SciPy dependency."""
    values = np.asarray(values, dtype=np.float64)
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = 0.5 * ((start + 1) + end)
        start = end
    return ranks


def spearman(values_a: np.ndarray, values_b: np.ndarray) -> float:
    a = _average_ranks(np.asarray(values_a, dtype=np.float64))
    b = _average_ranks(np.asarray(values_b, dtype=np.float64))
    if len(a) < 2 or np.std(a) == 0 or np.std(b) == 0:
        return 0.0
    value = float(np.corrcoef(a, b)[0, 1])
    return value if math.isfinite(value) else 0.0


class Standardizer:
    """Small NumPy standardizer used to keep the production trainer self-contained."""

    def fit(self, values: np.ndarray) -> "Standardizer":
        values = np.asarray(values, dtype=np.float64)
        self.mean_ = values.mean(axis=0)
        self.scale_ = values.std(axis=0)
        self.scale_[self.scale_ < 1e-12] = 1.0
        return self

    def transform(self, values: np.ndarray) -> np.ndarray:
        return (np.asarray(values, dtype=np.float64) - self.mean_) / self.scale_


class WeightedRidge:
    """Weighted ridge with an unpenalized intercept."""

    def __init__(self, alpha: float = 10.0):
        self.alpha = float(alpha)

    def fit(self, values: np.ndarray, target: np.ndarray, sample_weight: np.ndarray) -> "WeightedRidge":
        x = np.asarray(values, dtype=np.float64)
        y = np.asarray(target, dtype=np.float64)
        weight = np.asarray(sample_weight, dtype=np.float64)
        if len(x) != len(y) or len(y) != len(weight):
            raise ValueError("weighted_ridge_row_mismatch")
        design = np.column_stack((np.ones(len(x), dtype=np.float64), x))
        sqrt_weight = np.sqrt(np.clip(weight, 1e-12, None))
        weighted_design = design * sqrt_weight[:, None]
        weighted_target = y * sqrt_weight
        penalty = np.eye(design.shape[1], dtype=np.float64) * self.alpha
        penalty[0, 0] = 0.0
        system = weighted_design.T @ weighted_design + penalty
        rhs = weighted_design.T @ weighted_target
        self.coef_ = np.linalg.solve(system, rhs)
        return self

    def predict(self, values: np.ndarray) -> np.ndarray:
        x = np.asarray(values, dtype=np.float64)
        return self.coef_[0] + x @ self.coef_[1:]


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def load_embedding_map(root: Path) -> tuple[dict[str, torch.Tensor], dict, dict[str, str]]:
    receipt = json.loads((root / "embedding_cache_receipt.json").read_text())
    mapping: dict[str, torch.Tensor] = {}
    sequence_hashes: dict[str, str] = {}
    for item in receipt["shards"]:
        path = Path(item["path"])
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            path = root / "shards" / Path(item["path"]).name
        if not path.exists() or sha256_file(path) != item.get("sha256"):
            raise ValueError(f"embedding_shard_hash_mismatch:{path}")
        payload = torch.load(path, map_location="cpu", weights_only=False)
        values = payload["embeddings"].float()
        identifiers = payload["metadata"]["candidate_ids"]
        hashes = payload["metadata"]["sequence_sha256"]
        if len(identifiers) != len(hashes) or len(hashes) != len(values):
            raise ValueError(f"embedding_shard_metadata_rows:{path}")
        for candidate, sequence_hash, vector in zip(identifiers, hashes, values):
            if candidate in mapping:
                raise ValueError(f"duplicate_embedding:{candidate}")
            mapping[candidate] = vector
            sequence_hashes[candidate] = sequence_hash
    if len(mapping) != int(receipt["rows"]):
        raise ValueError("embedding_row_count_mismatch")
    return mapping, receipt, sequence_hashes


def metrics(y: np.ndarray, pred: np.ndarray, parents: list[str]) -> dict[str, float | int]:
    if len(y) < 3:
        raise ValueError("too_few_metric_rows")
    sp = spearman(y, pred)
    pc_y = y.copy()
    pc_p = pred.copy()
    per_parent = []
    for parent in sorted(set(parents)):
        idx = np.asarray([i for i, value in enumerate(parents) if value == parent])
        pc_y[idx] -= pc_y[idx].mean()
        pc_p[idx] -= pc_p[idx].mean()
        if len(idx) >= 3 and np.std(y[idx]) > 0 and np.std(pred[idx]) > 0:
            per_parent.append(spearman(y[idx], pred[idx]))
    pc = spearman(pc_y, pc_p)
    budget = max(1, math.ceil(0.2 * len(y)))
    truth_threshold = float(np.sort(y)[-budget])
    prediction_threshold = float(np.sort(pred)[-budget])
    truth = set(np.flatnonzero(y >= truth_threshold).tolist())
    chosen = set(np.flatnonzero(pred >= prediction_threshold).tolist())
    pearson = 0.0
    if np.std(y) > 0 and np.std(pred) > 0:
        value = float(np.corrcoef(y, pred)[0, 1])
        pearson = value if math.isfinite(value) else 0.0
    return {
        "spearman": sp,
        "pearson": pearson,
        "mae": float(np.mean(np.abs(y - pred))),
        "parent_centered_spearman": pc,
        "macro_parent_spearman": float(np.mean(per_parent)) if per_parent else 0.0,
        "macro_parent_groups": len(per_parent),
        "top20_recall": len(truth & chosen) / len(truth),
        "top20_truth_rows_tie_inclusive": len(truth),
        "top20_predicted_rows_tie_inclusive": len(chosen),
    }


class CandidateDataset(Dataset):
    def __init__(self, embeddings, structure, targets, weights, base, parents, top_label):
        self.embeddings = torch.as_tensor(embeddings, dtype=torch.float32)
        self.structure = torch.as_tensor(structure, dtype=torch.float32)
        self.targets = torch.as_tensor(targets, dtype=torch.float32)
        self.weights = torch.as_tensor(weights, dtype=torch.float32)
        self.base = torch.as_tensor(base, dtype=torch.float32)
        self.parents = list(parents)
        self.top_label = torch.as_tensor(top_label, dtype=torch.float32)

    def __len__(self):
        return len(self.targets)

    def __getitem__(self, index):
        return (
            self.embeddings[index], self.structure[index], self.targets[index],
            self.weights[index], self.base[index], self.parents[index], self.top_label[index],
        )


class ParentAwareBatchSampler(Sampler[list[int]]):
    """Shuffle parent chunks while preserving enough within-parent pairs per batch."""

    def __init__(self, parents: list[str], batch_size: int, per_parent: int, seed: int):
        self.batch_size = int(batch_size)
        self.per_parent = max(2, min(int(per_parent), self.batch_size))
        self.seed = int(seed)
        self.epoch = 0
        grouped: dict[str, list[int]] = defaultdict(list)
        for index, parent in enumerate(parents):
            grouped[parent].append(index)
        self.grouped = dict(grouped)
        self.row_count = len(parents)

    def __iter__(self):
        generator = random.Random(self.seed + self.epoch)
        self.epoch += 1
        chunks: list[list[int]] = []
        for parent in sorted(self.grouped):
            values = list(self.grouped[parent])
            generator.shuffle(values)
            chunks.extend(values[start:start + self.per_parent] for start in range(0, len(values), self.per_parent))
        generator.shuffle(chunks)
        batch: list[int] = []
        for chunk in chunks:
            if batch and len(batch) + len(chunk) > self.batch_size:
                yield batch
                batch = []
            batch.extend(chunk)
        if batch:
            yield batch

    def __len__(self):
        return math.ceil(self.row_count / self.batch_size)


class FusionResidualModel(nn.Module):
    def __init__(self, embedding_dim: int, structure_dim: int, hidden: int, dropout: float, residual_scale: float):
        super().__init__()
        self.embedding_norm = nn.LayerNorm(embedding_dim)
        self.sequence = nn.Sequential(nn.Linear(embedding_dim, hidden), nn.GELU(), nn.Dropout(dropout))
        self.structure = nn.Sequential(nn.Linear(structure_dim, hidden // 2), nn.GELU(), nn.Dropout(dropout))
        self.fusion = nn.Sequential(
            nn.Linear(hidden + hidden // 2, hidden), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(hidden, hidden // 2), nn.GELU(), nn.Dropout(dropout),
        )
        self.residual = nn.Linear(hidden // 2, 3)
        self.log_variance = nn.Linear(hidden // 2, 1)
        self.top = nn.Linear(hidden // 2, 1)
        self.residual_scale = float(residual_scale)

    def forward(self, embedding, structure, base):
        sequence = self.sequence(self.embedding_norm(embedding))
        structural = self.structure(structure)
        fused = self.fusion(torch.cat((sequence, structural), dim=-1))
        prediction = base + self.residual_scale * torch.tanh(self.residual(fused))
        log_variance = torch.clamp(self.log_variance(fused).squeeze(-1), -6.0, 2.0)
        top_logit = self.top(fused).squeeze(-1)
        return prediction, log_variance, top_logit


def ranking_loss(
    pred: torch.Tensor,
    target: torch.Tensor,
    parents: list[str],
    row_weight: torch.Tensor | None = None,
    min_gap: float = 0.02,
) -> torch.Tensor:
    losses = []
    weights = []
    for i in range(len(parents)):
        for j in range(i + 1, len(parents)):
            if parents[i] != parents[j]:
                continue
            delta = target[i, 2] - target[j, 2]
            if abs(float(delta)) < min_gap:
                continue
            sign = torch.sign(delta)
            losses.append(torch.nn.functional.softplus(-sign * (pred[i, 2] - pred[j, 2])))
            if row_weight is not None:
                weights.append(torch.sqrt(row_weight[i] * row_weight[j]))
    if not losses:
        return pred.sum() * 0.0
    stacked = torch.stack(losses)
    if row_weight is None:
        return stacked.mean()
    pair_weight = torch.stack(weights)
    return (stacked * pair_weight).sum() / pair_weight.sum().clamp_min(1e-12)


def compute_loss(pred, logvar, top_logit, target, weight, top_label, parents, args):
    huber = torch.nn.functional.smooth_l1_loss(pred, target, reduction="none", beta=args.huber_beta)
    per_row = args.dual_weight * huber[:, 2] + args.receptor_weight * (huber[:, 0] + huber[:, 1])
    nll = 0.5 * (torch.exp(-logvar) * (pred[:, 2] - target[:, 2]).square() + logvar)
    top = torch.nn.functional.binary_cross_entropy_with_logits(top_logit, top_label, reduction="none")
    primary = ((per_row + args.nll_weight * nll + args.top_weight * top) * weight).sum() / weight.sum()
    return primary + args.ranking_weight * ranking_loss(pred, target, list(parents), weight)


def checkpoint_guard(output: Path, minimum_checkpoint_gb: int, safe_stop_gb: int) -> None:
    stat = os.statvfs(output)
    free_gb = stat.f_bavail * stat.f_frsize / 1024**3
    if free_gb < safe_stop_gb:
        raise RuntimeError(f"disk_safe_stop:{free_gb:.1f}GB<{safe_stop_gb}GB")
    if free_gb < minimum_checkpoint_gb:
        raise RuntimeError(f"checkpoint_creation_guard:{free_gb:.1f}GB<{minimum_checkpoint_gb}GB")


def fit_baselines(train_x, train_y, train_weight, val_x):
    scaler = Standardizer().fit(train_x)
    train_z = scaler.transform(train_x)
    val_z = scaler.transform(val_x)
    train_pred = np.zeros_like(train_y)
    val_pred = np.zeros((len(val_x), 3), dtype=np.float64)
    models = []
    for target in range(3):
        ridge = WeightedRidge(alpha=10.0).fit(train_z, train_y[:, target], sample_weight=train_weight)
        train_pred[:, target] = ridge.predict(train_z)
        val_pred[:, target] = ridge.predict(val_z)
        models.append(ridge)
    return train_pred, val_pred, scaler, models


def parent_inner_fold(parent: str, outer_fold: int, inner_folds: int) -> int:
    token = f"PVRIG_V6_INNER|outer={outer_fold}|{parent}".encode()
    return int(hashlib.sha256(token).hexdigest(), 16) % inner_folds


def crossfit_baselines(indices: np.ndarray, arrays: dict, outer_fold: int, inner_folds: int) -> tuple[np.ndarray, dict[int, int]]:
    parents = [arrays["parents"][index] for index in indices]
    assignments = np.asarray([parent_inner_fold(parent, outer_fold, inner_folds) for parent in parents])
    counts = {int(value): int((assignments == value).sum()) for value in sorted(set(assignments.tolist()))}
    if len(counts) < 2:
        raise ValueError(f"too_few_inner_folds:{outer_fold}:{counts}")
    predictions = np.full((len(indices), 3), np.nan, dtype=np.float64)
    for inner_fold in counts:
        held_local = assignments == inner_fold
        keep_local = ~held_local
        if held_local.sum() == 0 or keep_local.sum() == 0:
            raise ValueError(f"empty_inner_fold:{outer_fold}:{inner_fold}")
        _, held_prediction, _, _ = fit_baselines(
            arrays["structure"][indices[keep_local]], arrays["targets"][indices[keep_local]],
            arrays["weights"][indices[keep_local]], arrays["structure"][indices[held_local]],
        )
        predictions[held_local] = held_prediction
    if not np.isfinite(predictions).all():
        raise ValueError(f"nonfinite_crossfit_baseline:{outer_fold}")
    return predictions, counts


def make_dataset(indices: np.ndarray, arrays: dict, structure: np.ndarray, base: np.ndarray, threshold: float) -> CandidateDataset:
    return CandidateDataset(
        arrays["embeddings"][indices], structure, arrays["targets"][indices], arrays["weights"][indices], base,
        [arrays["parents"][index] for index in indices],
        (arrays["targets"][indices, 2] >= threshold).astype(np.float32),
    )


def train_loader(dataset: CandidateDataset, args, seed: int) -> DataLoader:
    sampler = ParentAwareBatchSampler(dataset.parents, args.batch_size, args.per_parent_batch, seed)
    return DataLoader(dataset, batch_sampler=sampler)


def predict_model(model: nn.Module, loader: DataLoader, device: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    model.eval()
    predictions = []
    log_variances = []
    top_probabilities = []
    with torch.no_grad():
        for embedding, structure, target, weight, base, parents, top_label in loader:
            prediction, log_variance, top_logit = model(embedding.to(device), structure.to(device), base.to(device))
            predictions.append(prediction.cpu().numpy())
            log_variances.append(log_variance.cpu().numpy())
            top_probabilities.append(torch.sigmoid(top_logit).cpu().numpy())
    return np.concatenate(predictions), np.concatenate(log_variances), np.concatenate(top_probabilities)


def train_epoch(model: nn.Module, loader: DataLoader, optimizer, args) -> float:
    model.train()
    total = 0.0
    batches = 0
    for embedding, structure, target, weight, base, parents, top_label in loader:
        embedding = embedding.to(args.device)
        structure = structure.to(args.device)
        target = target.to(args.device)
        weight = weight.to(args.device)
        base = base.to(args.device)
        top_label = top_label.to(args.device)
        optimizer.zero_grad(set_to_none=True)
        prediction, log_variance, top_logit = model(embedding, structure, base)
        loss = compute_loss(prediction, log_variance, top_logit, target, weight, top_label, parents, args)
        if not torch.isfinite(loss):
            raise RuntimeError("nonfinite_loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)
        optimizer.step()
        total += float(loss.detach())
        batches += 1
    return total / max(1, batches)


def selection_key(metric: dict[str, float | int]) -> tuple[float, float, float, float]:
    return (
        float(metric["spearman"]),
        float(metric["parent_centered_spearman"]),
        float(metric["top20_recall"]),
        -float(metric["mae"]),
    )


def select_epoch_count(
    fold: int,
    outer_indices: np.ndarray,
    arrays: dict,
    args,
    fold_dir: Path,
    config_hash: str,
) -> tuple[int, list[dict]]:
    selection_path = fold_dir / "inner_selection.json"
    if selection_path.exists():
        payload = json.loads(selection_path.read_text())
        if payload.get("config_hash") != config_hash:
            raise ValueError(f"inner_selection_config_mismatch:{fold}")
        return int(payload["selected_epochs"]), list(payload["inner_results"])

    assignments = np.asarray([
        parent_inner_fold(arrays["parents"][index], fold, args.inner_folds) for index in outer_indices
    ])
    results = []
    for inner_fold in sorted(set(assignments.tolist())):
        inner_val_local = assignments == inner_fold
        inner_train_local = ~inner_val_local
        train_indices = outer_indices[inner_train_local]
        val_indices = outer_indices[inner_val_local]
        if len(train_indices) < 20 or len(val_indices) < 3:
            raise ValueError(f"inner_fold_too_small:{fold}:{inner_fold}:{len(train_indices)}:{len(val_indices)}")
        train_base, val_base, _, _ = fit_baselines(
            arrays["structure"][train_indices], arrays["targets"][train_indices], arrays["weights"][train_indices],
            arrays["structure"][val_indices],
        )
        scaler = Standardizer().fit(arrays["structure"][train_indices])
        train_structure = scaler.transform(arrays["structure"][train_indices])
        val_structure = scaler.transform(arrays["structure"][val_indices])
        threshold = float(np.quantile(arrays["targets"][train_indices, 2], 0.8))
        train_set = make_dataset(train_indices, arrays, train_structure, train_base, threshold)
        val_set = make_dataset(val_indices, arrays, val_structure, val_base, threshold)
        loader = train_loader(train_set, args, args.seed + fold * 100 + int(inner_fold))
        val_loader = DataLoader(val_set, batch_size=args.batch_size, shuffle=False)
        set_seed(args.seed + fold * 100 + int(inner_fold))
        model = FusionResidualModel(
            arrays["embeddings"].shape[1], arrays["structure"].shape[1], args.hidden,
            args.dropout, args.residual_scale,
        ).to(args.device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, args.epochs))
        best_epoch = 0
        best_key = (-float("inf"), -float("inf"), -float("inf"), -float("inf"))
        bad_epochs = 0
        history = []
        val_parents = [arrays["parents"][index] for index in val_indices]
        for epoch in range(args.epochs):
            loss = train_epoch(model, loader, optimizer, args)
            scheduler.step()
            prediction, _, _ = predict_model(model, val_loader, args.device)
            metric = metrics(arrays["targets"][val_indices, 2], prediction[:, 2], val_parents)
            event = {"epoch": epoch, "train_loss": loss, "lr": optimizer.param_groups[0]["lr"], **metric}
            history.append(event)
            key = selection_key(metric)
            improved = key[0] > best_key[0] + args.min_delta
            if not improved and abs(key[0] - best_key[0]) <= args.min_delta:
                improved = key[1:] > best_key[1:]
            if improved:
                best_key = key
                best_epoch = epoch
                bad_epochs = 0
            else:
                bad_epochs += 1
            if bad_epochs >= args.patience:
                break
        results.append({
            "inner_fold": int(inner_fold), "train_rows": len(train_indices), "validation_rows": len(val_indices),
            "validation_parents": len(set(val_parents)), "best_epoch_zero_based": best_epoch,
            "best_key": list(best_key), "history": history,
        })
        del model
        if torch.cuda.is_available() and str(args.device).startswith("cuda"):
            torch.cuda.empty_cache()

    epoch_counts = sorted(int(item["best_epoch_zero_based"]) + 1 for item in results)
    selected_epochs = max(1, int(round(float(np.median(epoch_counts)))))
    payload = {
        "schema_version": "pvrig_v6_inner_epoch_selection_v1",
        "status": "PASS_V6_INNER_SELECTION_COMPLETE",
        "outer_fold": fold,
        "inner_assignment": "sha256('PVRIG_V6_INNER|outer=<outer>|' + parent) modulo inner_folds",
        "inner_folds_requested": args.inner_folds,
        "inner_folds_observed": len(results),
        "selected_epochs": selected_epochs,
        "aggregation": "rounded_median_of_inner_best_epoch_counts",
        "selection_key": ["spearman", "parent_centered_spearman", "top20_recall", "negative_mae"],
        "config_hash": config_hash,
        "inner_results": results,
        "claim_boundary": CLAIM,
    }
    atomic_json(selection_path, payload)
    return selected_epochs, results


def baseline_artifact(scaler: Standardizer, models: list[WeightedRidge]) -> dict:
    return {
        "mean": scaler.mean_, "scale": scaler.scale_,
        "ridge_coefficients": [model.coef_ for model in models],
    }


def train_fold(fold: int, arrays: dict, args, config_hash: str) -> tuple[list[dict], dict]:
    held = arrays["folds"] == fold
    keep = ~held
    if held.sum() == 0 or keep.sum() == 0:
        raise ValueError(f"empty_fold:{fold}")
    fold_dir = args.output_dir / f"fold_{fold}"
    fold_dir.mkdir(parents=True, exist_ok=True)
    terminal = fold_dir / "terminal.json"
    prediction_path = fold_dir / "predictions.tsv"
    if terminal.exists():
        payload = json.loads(terminal.read_text())
        if payload.get("config_hash") != config_hash:
            raise ValueError(f"terminal_config_mismatch:{fold}")
        if not prediction_path.exists() or sha256_file(prediction_path) != payload.get("prediction_sha256"):
            raise ValueError(f"terminal_prediction_hash_mismatch:{fold}")
        with prediction_path.open(newline="") as handle:
            return list(csv.DictReader(handle, delimiter="\t")), payload

    outer_indices = np.flatnonzero(keep)
    held_indices = np.flatnonzero(held)
    selected_epochs, inner_results = select_epoch_count(fold, outer_indices, arrays, args, fold_dir, config_hash)

    crossfit_base, inner_counts = crossfit_baselines(outer_indices, arrays, fold, args.inner_folds)
    _, val_base, baseline_scaler, ridge_models = fit_baselines(
        arrays["structure"][outer_indices], arrays["targets"][outer_indices], arrays["weights"][outer_indices],
        arrays["structure"][held_indices],
    )
    structure_scaler = Standardizer().fit(arrays["structure"][outer_indices])
    train_structure = structure_scaler.transform(arrays["structure"][outer_indices])
    val_structure = structure_scaler.transform(arrays["structure"][held_indices])
    threshold = float(np.quantile(arrays["targets"][outer_indices, 2], 0.8))
    train_set = make_dataset(outer_indices, arrays, train_structure, crossfit_base, threshold)
    val_set = make_dataset(held_indices, arrays, val_structure, val_base, threshold)
    loader = train_loader(train_set, args, args.seed + fold * 1000 + 777)
    val_loader = DataLoader(val_set, batch_size=args.batch_size, shuffle=False)

    set_seed(args.seed + fold * 1000 + 777)
    model = FusionResidualModel(
        arrays["embeddings"].shape[1], arrays["structure"].shape[1], args.hidden,
        args.dropout, args.residual_scale,
    ).to(args.device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, selected_epochs))
    last_path = fold_dir / "last.pt"
    best_path = fold_dir / "best.pt"
    start_epoch = 0
    if last_path.exists() and args.resume:
        state = torch.load(last_path, map_location=args.device, weights_only=False)
        if state.get("config_hash") != config_hash or state.get("phase") != "outer_final":
            raise ValueError(f"resume_config_mismatch:{fold}")
        if int(state.get("selected_epochs", -1)) != selected_epochs:
            raise ValueError(f"resume_epoch_contract_mismatch:{fold}")
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        scheduler.load_state_dict(state["scheduler"])
        start_epoch = int(state["epoch"]) + 1
    metrics_path = fold_dir / "final_training_metrics.jsonl"
    for epoch in range(start_epoch, selected_epochs):
        loss = train_epoch(model, loader, optimizer, args)
        scheduler.step()
        with metrics_path.open("a") as handle:
            handle.write(json.dumps({"epoch": epoch, "train_loss": loss, "lr": optimizer.param_groups[0]["lr"]}, sort_keys=True) + "\n")
        checkpoint_guard(fold_dir, args.minimum_checkpoint_free_gb, args.safe_stop_free_gb)
        torch.save({
            "phase": "outer_final", "model": model.state_dict(), "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict(), "epoch": epoch, "selected_epochs": selected_epochs,
            "config_hash": config_hash,
        }, last_path)

    prediction, log_variance, top_probability = predict_model(model, val_loader, args.device)
    deployment = {
        "phase": "outer_final", "model": model.state_dict(), "selected_epochs": selected_epochs,
        "config_hash": config_hash, "training_fingerprint": arrays["training_fingerprint"],
        "feature_names": arrays["feature_names"], "feature_names_sha256": arrays["feature_names_sha256"],
        "embedding_dimension": int(arrays["embeddings"].shape[1]), "top20_threshold": threshold,
        "structure_scaler_mean": structure_scaler.mean_, "structure_scaler_scale": structure_scaler.scale_,
        "m2_baseline": baseline_artifact(baseline_scaler, ridge_models), "claim_boundary": CLAIM,
    }
    checkpoint_guard(fold_dir, args.minimum_checkpoint_free_gb, args.safe_stop_free_gb)
    torch.save(deployment, best_path)
    output_rows = []
    for local, global_index in enumerate(held_indices):
        output_rows.append({
            "candidate_id": arrays["candidate_ids"][global_index],
            "sequence_sha256": arrays["sequence_hashes"][global_index],
            "parent_framework_cluster": arrays["parents"][global_index],
            "teacher_source": arrays["sources"][global_index],
            "outer_fold": fold,
            "R_dual_min": arrays["targets"][global_index, 2],
            "M2_prediction": val_base[local, 2],
            "V6_prediction": prediction[local, 2],
            "V6_R8_prediction": prediction[local, 0],
            "V6_R9_prediction": prediction[local, 1],
            "V6_log_variance": log_variance[local],
            "V6_top20_probability": top_probability[local],
        })
    with prediction_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=list(output_rows[0]))
        writer.writeheader(); writer.writerows(output_rows)
    terminal_payload = {
        "schema_version": "pvrig_v6_fold_terminal_v2", "status": "PASS_V6_FOLD_TERMINAL",
        "fold": fold, "rows": len(output_rows), "config_hash": config_hash,
        "selected_epochs": selected_epochs, "inner_fold_row_counts": inner_counts,
        "inner_selection_sha256": sha256_file(fold_dir / "inner_selection.json"),
        "prediction_sha256": sha256_file(prediction_path), "best_checkpoint_sha256": sha256_file(best_path),
        "last_checkpoint_sha256": sha256_file(last_path), "claim_boundary": CLAIM,
    }
    atomic_json(terminal, terminal_payload)
    return output_rows, terminal_payload

def parent_bootstrap_delta(
    y: np.ndarray,
    m2: np.ndarray,
    v6: np.ndarray,
    parents: list[str],
    repetitions: int,
    seed: int,
) -> dict:
    grouped = {parent: np.flatnonzero(np.asarray(parents) == parent) for parent in sorted(set(parents))}
    names = sorted(grouped)
    generator = np.random.default_rng(seed)
    deltas = []
    for _ in range(repetitions):
        sampled = generator.choice(names, size=len(names), replace=True)
        indices = np.concatenate([grouped[parent] for parent in sampled])
        deltas.append(spearman(y[indices], v6[indices]) - spearman(y[indices], m2[indices]))
    values = np.asarray(deltas, dtype=np.float64)
    return {
        "repetitions": repetitions,
        "seed": seed,
        "median_delta_spearman": float(np.median(values)),
        "ci95_lower": float(np.quantile(values, 0.025)),
        "ci95_upper": float(np.quantile(values, 0.975)),
        "positive_fraction": float(np.mean(values > 0)),
    }


def validate_rows(
    fields: list[str],
    rows: list[dict[str, str]],
    embedding_map: dict[str, torch.Tensor],
    embedding_hashes: dict[str, str],
    args,
) -> tuple[list[dict[str, str]], list[str]]:
    if not rows:
        raise ValueError("empty_training_table")
    identifiers = [row["candidate_id"] for row in rows]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate_training_candidate")
    if args.max_rows:
        if not args.smoke_mode:
            raise ValueError("max_rows_requires_smoke_mode")
        selected = rows[:args.max_rows]
    else:
        selected = rows
    selected_ids = {row["candidate_id"] for row in selected}
    if selected_ids != set(embedding_map):
        missing = sorted(selected_ids - set(embedding_map))[:3]
        extra = sorted(set(embedding_map) - selected_ids)[:3]
        raise ValueError(f"embedding_candidate_closure:missing={missing}:extra={extra}")
    sequence_hashes = []
    parent_fold: dict[str, str] = {}
    sequence_fold: dict[str, str] = {}
    for row in selected:
        candidate = row["candidate_id"]
        actual_hash = hashlib.sha256(row["sequence"].encode()).hexdigest()
        if actual_hash != row["sequence_sha256"] or embedding_hashes[candidate] != actual_hash:
            raise ValueError(f"sequence_hash_closure:{candidate}")
        if row["parent_framework_cluster"] in parent_fold and parent_fold[row["parent_framework_cluster"]] != row["outer_fold"]:
            raise ValueError(f"parent_cross_fold:{row['parent_framework_cluster']}")
        parent_fold[row["parent_framework_cluster"]] = row["outer_fold"]
        if actual_hash in sequence_fold and sequence_fold[actual_hash] != row["outer_fold"]:
            raise ValueError(f"sequence_cross_fold:{actual_hash}")
        sequence_fold[actual_hash] = row["outer_fold"]
        sequence_hashes.append(actual_hash)
    feature_names = [name for name in fields if name not in METADATA]
    if len(feature_names) != 126:
        raise ValueError(f"structure_feature_count:{len(feature_names)}")
    if len(selected) < 20:
        raise ValueError(f"too_few_joined_rows:{len(selected)}")
    folds = {int(row["outer_fold"]) for row in selected}
    if not args.smoke_mode and folds != set(range(5)):
        raise ValueError(f"production_outer_fold_closure:{sorted(folds)}")
    return selected, feature_names


def main(args: argparse.Namespace) -> dict:
    set_seed(args.seed)
    fields, rows = read_table(args.input)
    embedding_map, embedding_receipt, embedding_hashes = load_embedding_map(args.embeddings)
    selected, feature_names = validate_rows(fields, rows, embedding_map, embedding_hashes, args)
    input_sha256 = sha256_file(args.input)
    embedding_receipt_path = args.embeddings / "embedding_cache_receipt.json"
    embedding_receipt_sha256 = sha256_file(embedding_receipt_path)
    if embedding_receipt.get("input_sha256") != input_sha256:
        raise ValueError("embedding_input_hash_mismatch")
    feature_names_sha256 = hashlib.sha256("\n".join(feature_names).encode()).hexdigest()
    split_rows = sorted(
        f"{row['candidate_id']}\t{row['sequence_sha256']}\t{row['parent_framework_cluster']}\t{row['outer_fold']}"
        for row in selected
    )
    split_manifest_sha256 = hashlib.sha256(("\n".join(split_rows) + "\n").encode()).hexdigest()
    fingerprint_payload = {
        "input_sha256": input_sha256,
        "embedding_receipt_sha256": embedding_receipt_sha256,
        "embedding_shards": [item["sha256"] for item in embedding_receipt["shards"]],
        "feature_names_sha256": feature_names_sha256,
        "split_manifest_sha256": split_manifest_sha256,
        "rows": len(selected),
    }
    training_fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True).encode()).hexdigest()
    structure = np.asarray([[float(row[name]) for name in feature_names] for row in selected])
    targets = np.asarray([
        [float(row["R_8X6B"]), float(row["R_9E6Y"]), float(row["R_dual_min"])] for row in selected
    ])
    if not np.isfinite(structure).all() or not np.isfinite(targets).all():
        raise ValueError("nonfinite_training_values")
    arrays = {
        "candidate_ids": [row["candidate_id"] for row in selected],
        "sequence_hashes": [row["sequence_sha256"] for row in selected],
        "parents": [row["parent_framework_cluster"] for row in selected],
        "sources": [row["teacher_source"] for row in selected],
        "folds": np.asarray([int(row["outer_fold"]) for row in selected]),
        "embeddings": np.stack([embedding_map[row["candidate_id"]].numpy() for row in selected]),
        "structure": structure,
        "targets": targets,
        "weights": np.asarray([float(row["sample_weight"]) for row in selected]),
        "feature_names": feature_names,
        "feature_names_sha256": feature_names_sha256,
        "training_fingerprint": training_fingerprint,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = {key: value for key, value in vars(args).items() if key not in {"resume"}}
    config = {key: str(value) if isinstance(value, Path) else value for key, value in config.items()}
    config["model_family"] = "M3_POOLED_ESM_STRUCTURE_RESIDUAL_BASELINE"
    config["training_fingerprint"] = training_fingerprint
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    folds = sorted(set(arrays["folds"].tolist())) if args.fold < 0 else [args.fold]
    all_predictions = []
    terminals = []
    for fold in folds:
        rows_out, terminal = train_fold(fold, arrays, args, config_hash)
        all_predictions.extend(rows_out)
        terminals.append(terminal)
    if args.fold >= 0:
        return {"status": "PASS_V6_SINGLE_FOLD_TERMINAL", "fold": args.fold, "terminal": terminals[0]}
    if len(all_predictions) != len(selected):
        raise ValueError(f"oof_closure:{len(all_predictions)}:{len(selected)}")
    all_predictions.sort(key=lambda row: row["candidate_id"])
    oof_path = args.output_dir / "oof_predictions.tsv"
    with oof_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=list(all_predictions[0]))
        writer.writeheader(); writer.writerows(all_predictions)
    y = np.asarray([float(row["R_dual_min"]) for row in all_predictions])
    m2 = np.asarray([float(row["M2_prediction"]) for row in all_predictions])
    v6 = np.asarray([float(row["V6_prediction"]) for row in all_predictions])
    parents = [row["parent_framework_cluster"] for row in all_predictions]
    sources = [row["teacher_source"] for row in all_predictions]
    m2_metric = metrics(y, m2, parents)
    v6_metric = metrics(y, v6, parents)
    bootstrap = parent_bootstrap_delta(y, m2, v6, parents, args.bootstrap_repetitions, args.seed + 9000)
    source_metrics = {}
    for source in sorted(set(sources)):
        index = np.flatnonzero(np.asarray(sources) == source)
        if len(index) >= 3:
            source_metrics[source] = {
                "rows": len(index),
                "parents": len(set(parents[i] for i in index)),
                "M2": metrics(y[index], m2[index], [parents[i] for i in index]),
                "V6": metrics(y[index], v6[index], [parents[i] for i in index]),
            }
    promotion_checks = {
        "global_spearman_improves": v6_metric["spearman"] > m2_metric["spearman"],
        "parent_centered_non_degradation": v6_metric["parent_centered_spearman"] >= m2_metric["parent_centered_spearman"],
        "top20_recall_non_degradation": v6_metric["top20_recall"] >= m2_metric["top20_recall"],
        "parent_bootstrap_direction_stable": bootstrap["positive_fraction"] >= 0.80 and bootstrap["median_delta_spearman"] > 0,
    }
    promotion = {
        "status": "PASS_V6_PROMOTION_GATE" if all(promotion_checks.values()) else "FAIL_V6_PROMOTION_GATE",
        "checks": promotion_checks,
        "note": "Training terminal means execution complete; promotion is a separate evidence gate.",
    }
    summary = {
        "schema_version": "pvrig_v6_oof_summary_v2",
        "status": "PASS_V6_OOF_COMPLETE",
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model_family": "M3_POOLED_ESM_STRUCTURE_RESIDUAL_BASELINE",
        "rows": len(all_predictions), "parent_clusters": len(set(parents)),
        "input_sha256": input_sha256,
        "embedding_receipt_sha256": embedding_receipt_sha256,
        "feature_names_sha256": feature_names_sha256,
        "split_manifest_sha256": split_manifest_sha256,
        "training_fingerprint": training_fingerprint,
        "config": config, "config_hash": config_hash,
        "M2": m2_metric, "V6": v6_metric,
        "parent_bootstrap_delta": bootstrap,
        "source_stratified": source_metrics,
        "promotion": promotion,
        "oof_prediction_sha256": sha256_file(oof_path), "claim_boundary": CLAIM,
    }
    atomic_json(args.output_dir / "summary.json", summary)
    atomic_json(args.output_dir / "terminal_receipt.json", {
        "schema_version": "pvrig_v6_training_terminal_receipt_v2",
        "status": "PASS_V6_TRAINING_TERMINAL", "summary_sha256": sha256_file(args.output_dir / "summary.json"),
        "promotion_status": promotion["status"], "fold_terminals": terminals, "claim_boundary": CLAIM,
    })
    return summary

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--embeddings", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--seed", type=int, default=43)
    p.add_argument("--fold", type=int, default=-1, help="-1 runs all folds")
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--per-parent-batch", type=int, default=8)
    p.add_argument("--inner-folds", type=int, default=5)
    p.add_argument("--hidden", type=int, default=256)
    p.add_argument("--dropout", type=float, default=0.15)
    p.add_argument("--residual-scale", type=float, default=0.12)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--huber-beta", type=float, default=0.02)
    p.add_argument("--dual-weight", type=float, default=1.0)
    p.add_argument("--receptor-weight", type=float, default=0.35)
    p.add_argument("--nll-weight", type=float, default=0.10)
    p.add_argument("--top-weight", type=float, default=0.10)
    p.add_argument("--ranking-weight", type=float, default=0.10)
    p.add_argument("--grad-clip", type=float, default=1.0)
    p.add_argument("--patience", type=int, default=6)
    p.add_argument("--min-delta", type=float, default=0.001)
    p.add_argument("--minimum-checkpoint-free-gb", type=int, default=180)
    p.add_argument("--safe-stop-free-gb", type=int, default=150)
    p.add_argument("--bootstrap-repetitions", type=int, default=1000)
    p.add_argument("--max-rows", type=int, default=0)
    p.add_argument("--smoke-mode", action="store_true")
    p.add_argument("--resume", action="store_true")
    return p


if __name__ == "__main__":
    print(json.dumps(main(parser().parse_args()), indent=2, sort_keys=True))
