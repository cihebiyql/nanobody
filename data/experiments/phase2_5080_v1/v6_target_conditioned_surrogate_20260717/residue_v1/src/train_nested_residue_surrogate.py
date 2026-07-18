#!/usr/bin/env python3
"""Nested whole-parent training for the V6 residue-level docking surrogate.

For each frozen outer fold, model/epoch selection is performed only inside the
outer-training parents.  The final residue model is then refit on every outer-
training parent and evaluated exactly once on the held outer fold.  Every
scalar-training row receives an out-of-inner-fold M2 prediction; held-out rows
receive an M2 prediction fit on the corresponding training side.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import random
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import numpy as np
import torch
from torch import Tensor, nn
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset, Subset

from residue_model import (
    CLAIM_BOUNDARY,
    ResidueHeadConfig,
    ResidueLossConfig,
    DualContactResidualHead,
    ResidueModelError,
    ResidueSurrogate,
    compute_loss,
    model_contract,
    require,
    trainable_checkpoint_state,
)


SCHEMA_VERSION = "pvrig_v6_nested_residue_surrogate_v1"
REQUIRED_FIELDS = {
    "candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster",
    "outer_fold", "R_8X6B", "R_9E6Y", "R_dual_min",
}
CONTACT_REQUIRED = {
    "candidate_id", "sequence_sha256", "parent_framework_cluster",
    "vhh_sequence_index", "vhh_aa", "contact_target_8x6b",
    "contact_target_9e6y", "target_mask_8x6b", "target_mask_9e6y",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def atomic_torch_save(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    torch.save(dict(payload), temporary)
    os.replace(temporary, path)


def require_regular(path: Path, label: str) -> None:
    require(path.is_file(), f"{label}_missing:{path}")
    require(not path.is_symlink(), f"{label}_symlink_forbidden:{path}")


def disk_guard(path: Path, minimum_free_gb: float) -> int:
    probe = path if path.exists() else path.parent
    free = int(shutil.disk_usage(probe).free)
    require(free >= minimum_free_gb * 1024**3, f"disk_guard_failed:free={free}:minimum_gb={minimum_free_gb}")
    return free


def parent_inner_fold(parent: str, outer_fold: int, inner_folds: int) -> int:
    require(parent and outer_fold >= 0 and inner_folds >= 2, "inner_fold_input_invalid")
    digest = hashlib.sha256(f"PVRIG_V6_RESIDUE_INNER|outer={outer_fold}|{parent}".encode()).hexdigest()
    return int(digest, 16) % inner_folds


@dataclass(frozen=True)
class TrainingRow:
    candidate_id: str
    sequence: str
    sequence_sha256: str
    parent: str
    outer_fold: int
    targets: tuple[float, float, float]
    weight: float
    structure: tuple[float, ...]
    contact_targets: tuple[tuple[float, float], ...] | None
    contact_mask: tuple[tuple[bool, bool], ...] | None


def read_training_table(
    training_tsv: Path,
    contact_tsv_gz: Path,
    *,
    structure_prefixes: Sequence[str],
    structure_dim: int,
) -> tuple[list[TrainingRow], list[str], dict[str, Any]]:
    require_regular(training_tsv, "training_tsv")
    require_regular(contact_tsv_gz, "contact_tsv_gz")
    with training_tsv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        raw_rows = [dict(row) for row in reader]
    require(REQUIRED_FIELDS <= set(fields), f"training_fields_missing:{sorted(REQUIRED_FIELDS-set(fields))}")
    feature_names = [field for field in fields if any(field.startswith(prefix) for prefix in structure_prefixes)]
    require(len(feature_names) == structure_dim, f"structure_feature_count_invalid:{len(feature_names)}:{structure_dim}")

    raw_by_id: dict[str, dict[str, str]] = {}
    parent_folds: dict[str, set[int]] = {}
    for row in raw_rows:
        candidate = row["candidate_id"]
        require(candidate and candidate not in raw_by_id, f"duplicate_training_candidate:{candidate}")
        sequence = row["sequence"].strip().upper()
        require(sequence and hashlib.sha256(sequence.encode()).hexdigest() == row["sequence_sha256"], f"training_sequence_hash_mismatch:{candidate}")
        outer_fold = int(row["outer_fold"])
        require(outer_fold >= 0, f"outer_fold_invalid:{candidate}")
        parent_folds.setdefault(row["parent_framework_cluster"], set()).add(outer_fold)
        raw_by_id[candidate] = row
    require(all(len(folds) == 1 for folds in parent_folds.values()), "outer_fold_parent_leakage")

    contact_rows: dict[str, dict[int, tuple[float, float, bool, bool]]] = {}
    contact_metadata: dict[str, tuple[str, str]] = {}
    with gzip.open(contact_tsv_gz, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        contact_fields = list(reader.fieldnames or [])
        require(CONTACT_REQUIRED <= set(contact_fields), f"contact_fields_missing:{sorted(CONTACT_REQUIRED-set(contact_fields))}")
        for line_number, row in enumerate(reader, start=2):
            candidate = row["candidate_id"]
            require(candidate in raw_by_id, f"contact_candidate_not_in_training:{line_number}:{candidate}")
            source = raw_by_id[candidate]
            require(row["sequence_sha256"] == source["sequence_sha256"], f"contact_sequence_hash_mismatch:{candidate}")
            require(row["parent_framework_cluster"] == source["parent_framework_cluster"], f"contact_parent_mismatch:{candidate}")
            index = int(row["vhh_sequence_index"])
            sequence = source["sequence"].strip().upper()
            require(1 <= index <= len(sequence) and row["vhh_aa"] == sequence[index - 1], f"contact_residue_mismatch:{candidate}:{index}")
            target = (float(row["contact_target_8x6b"]), float(row["contact_target_9e6y"]))
            mask = (bool(int(row["target_mask_8x6b"])), bool(int(row["target_mask_9e6y"])))
            require(all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in target), f"contact_target_invalid:{candidate}:{index}")
            require(index not in contact_rows.setdefault(candidate, {}), f"duplicate_contact_residue:{candidate}:{index}")
            contact_rows[candidate][index] = (target[0], target[1], mask[0], mask[1])
            contact_metadata[candidate] = (row["sequence_sha256"], row["parent_framework_cluster"])

    rows: list[TrainingRow] = []
    for candidate, source in raw_by_id.items():
        sequence = source["sequence"].strip().upper()
        target_values = tuple(float(source[name]) for name in ("R_8X6B", "R_9E6Y", "R_dual_min"))
        require(all(math.isfinite(value) for value in target_values), f"nonfinite_target:{candidate}")
        require(abs(min(target_values[0], target_values[1]) - target_values[2]) <= 1e-6, f"dual_min_contract_failed:{candidate}")
        structure = tuple(float(source[name]) for name in feature_names)
        require(all(math.isfinite(value) for value in structure), f"nonfinite_structure:{candidate}")
        weight = float(source.get("sample_weight") or 1.0)
        require(math.isfinite(weight) and weight > 0, f"sample_weight_invalid:{candidate}")
        if candidate in contact_rows:
            observed = contact_rows[candidate]
            require(sorted(observed) == list(range(1, len(sequence) + 1)), f"contact_residue_closure_failed:{candidate}")
            contact_targets = tuple((observed[index][0], observed[index][1]) for index in range(1, len(sequence) + 1))
            contact_mask = tuple((observed[index][2], observed[index][3]) for index in range(1, len(sequence) + 1))
        else:
            contact_targets = None
            contact_mask = None
        rows.append(TrainingRow(
            candidate, sequence, source["sequence_sha256"], source["parent_framework_cluster"],
            int(source["outer_fold"]), target_values, weight, structure, contact_targets, contact_mask,
        ))
    require(rows and contact_rows, "empty_training_or_contact_table")
    audit = {
        "training_candidates": len(rows),
        "contact_candidates": len(contact_rows),
        "parents": len(parent_folds),
        "outer_folds": sorted({row.outer_fold for row in rows}),
        "structure_features": len(feature_names),
    }
    return rows, feature_names, audit


@dataclass(frozen=True)
class RidgeState:
    x_mean: np.ndarray
    x_scale: np.ndarray
    y_mean: np.ndarray
    coefficient: np.ndarray
    alpha: float


def fit_weighted_ridge(x: np.ndarray, y: np.ndarray, weights: np.ndarray, alpha: float) -> RidgeState:
    require(x.ndim == 2 and y.shape == (len(x), 3) and weights.shape == (len(x),), "ridge_shape_invalid")
    require(len(x) >= 2 and alpha > 0 and np.all(weights > 0), "ridge_input_invalid")
    normalized = weights / weights.sum()
    x_mean = np.sum(x * normalized[:, None], axis=0)
    variance = np.sum((x - x_mean) ** 2 * normalized[:, None], axis=0)
    x_scale = np.sqrt(variance)
    x_scale[x_scale < 1e-8] = 1.0
    y_mean = np.sum(y * normalized[:, None], axis=0)
    xs = (x - x_mean) / x_scale
    yc = y - y_mean
    root = np.sqrt(weights)[:, None]
    gram = (xs * root).T @ (xs * root)
    rhs = (xs * root).T @ (yc * root)
    coefficient = np.linalg.solve(gram + alpha * np.eye(x.shape[1]), rhs)
    return RidgeState(x_mean, x_scale, y_mean, coefficient, float(alpha))


def predict_ridge(state: RidgeState, x: np.ndarray) -> np.ndarray:
    require(x.ndim == 2 and x.shape[1] == len(state.x_mean), "ridge_prediction_shape_invalid")
    return (x - state.x_mean) / state.x_scale @ state.coefficient + state.y_mean


def arrays_from_rows(rows: Sequence[TrainingRow]) -> dict[str, Any]:
    return {
        "parents": [row.parent for row in rows],
        "structure": np.asarray([row.structure for row in rows], dtype=np.float64),
        "targets": np.asarray([row.targets for row in rows], dtype=np.float64),
        "weights": np.asarray([row.weight for row in rows], dtype=np.float64),
    }


def crossfit_m2(
    indices: Sequence[int],
    arrays: Mapping[str, Any],
    outer_fold: int,
    inner_folds: int,
    alpha: float,
) -> tuple[np.ndarray, dict[int, int]]:
    selected = np.asarray(list(indices), dtype=int)
    require(len(selected) > 0, "crossfit_indices_empty")
    assignments = np.asarray([parent_inner_fold(arrays["parents"][index], outer_fold, inner_folds) for index in selected])
    observed = sorted(set(assignments.tolist()))
    require(len(observed) >= 2, f"crossfit_too_few_inner_folds:{observed}")
    prediction = np.full((len(selected), 3), np.nan, dtype=np.float64)
    counts: dict[int, int] = {}
    for fold in observed:
        held_local = np.where(assignments == fold)[0]
        train_local = np.where(assignments != fold)[0]
        require(len(held_local) > 0 and len(train_local) >= 2, f"crossfit_fold_invalid:{fold}")
        train_global = selected[train_local]
        held_global = selected[held_local]
        state = fit_weighted_ridge(
            arrays["structure"][train_global], arrays["targets"][train_global], arrays["weights"][train_global], alpha,
        )
        prediction[held_local] = predict_ridge(state, arrays["structure"][held_global])
        counts[int(fold)] = len(held_local)
    require(bool(np.all(np.isfinite(prediction))), "crossfit_prediction_nonfinite")
    return prediction, counts


class TinyTokenizer:
    pad_token_id = 0

    def __init__(self) -> None:
        alphabet = "ACDEFGHIKLMNPQRSTVWYX"
        self.vocabulary = {aa: index + 3 for index, aa in enumerate(alphabet)}

    def __len__(self) -> int:
        return len(self.vocabulary) + 3

    def __call__(self, sequences: Sequence[str], **_: Any) -> dict[str, Tensor]:
        encoded = [[1] + [self.vocabulary.get(aa, self.vocabulary["X"]) for aa in sequence] + [2] for sequence in sequences]
        width = max(map(len, encoded))
        input_ids, attention, special = [], [], []
        for values in encoded:
            padding = width - len(values)
            input_ids.append(values + [0] * padding)
            attention.append([1] * len(values) + [0] * padding)
            special.append([1] + [0] * (len(values) - 2) + [1] + [1] * padding)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention, dtype=torch.long),
            "special_tokens_mask": torch.tensor(special, dtype=torch.long),
        }


class TinyBackbone(nn.Module):
    def __init__(self, vocabulary_size: int, hidden_size: int) -> None:
        super().__init__()
        self.config = SimpleNamespace(hidden_size=hidden_size)
        self.embedding = nn.Embedding(vocabulary_size, hidden_size, padding_idx=0)
        self.encoder = nn.GRU(hidden_size, hidden_size // 2, batch_first=True, bidirectional=True)

    def forward(self, input_ids: Tensor, attention_mask: Tensor) -> Any:
        del attention_mask
        states, _ = self.encoder(self.embedding(input_ids))
        return SimpleNamespace(last_hidden_state=states)


def load_backbone(args: argparse.Namespace) -> tuple[nn.Module, Any, int, str]:
    if args.backbone_kind == "tiny":
        tokenizer = TinyTokenizer()
        model = TinyBackbone(len(tokenizer), args.tiny_hidden_size)
        for parameter in model.parameters():
            parameter.requires_grad_(False)
        return model, tokenizer, args.tiny_hidden_size, "tiny_synthetic"
    require(args.model_path is not None and args.model_path.is_dir() and not args.model_path.is_symlink(), "local_model_directory_required")
    require(args.model_identity_file is not None, "model_identity_file_required")
    require_regular(args.model_identity_file, "model_identity_file")
    actual_model_hash = sha256_file(args.model_identity_file)
    require(args.expected_model_sha256 and actual_model_hash == args.expected_model_sha256, "model_identity_sha256_mismatch")
    try:
        from transformers import AutoModel, AutoTokenizer
    except ImportError as error:
        raise ResidueModelError("transformers_required") from error
    tokenizer = AutoTokenizer.from_pretrained(str(args.model_path), local_files_only=True, trust_remote_code=args.trust_remote_code)
    model = AutoModel.from_pretrained(str(args.model_path), local_files_only=True, trust_remote_code=args.trust_remote_code)
    hidden = getattr(model.config, "hidden_size", None) or getattr(model.config, "d_model", None) or getattr(model.config, "embed_dim", None)
    require(hidden is not None, "backbone_hidden_size_missing")
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    if args.backbone_mode == "lora":
        try:
            from peft import LoraConfig, TaskType, get_peft_model
        except ImportError as error:
            raise ResidueModelError("peft_required_for_lora") from error
        targets = [item.strip() for item in args.lora_target_modules.split(",") if item.strip()]
        require(targets, "lora_target_modules_empty")
        model = get_peft_model(model, LoraConfig(
            r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=args.lora_dropout,
            target_modules=targets, bias="none", task_type=TaskType.FEATURE_EXTRACTION,
        ))
    return model, tokenizer, int(hidden), actual_model_hash


class IndexedDataset(Dataset[int]):
    def __init__(self, indices: Sequence[int]) -> None:
        self.indices = list(indices)

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, index: int) -> int:
        return self.indices[index]


class Collator:
    def __init__(self, rows: Sequence[TrainingRow], tokenizer: Any, base_by_index: Mapping[int, np.ndarray]) -> None:
        self.rows = rows
        self.tokenizer = tokenizer
        self.base = base_by_index

    def __call__(self, indices: Sequence[int]) -> dict[str, Any]:
        rows = [self.rows[index] for index in indices]
        encoded = self.tokenizer(
            [row.sequence for row in rows], padding=True, truncation=False,
            return_tensors="pt", return_special_tokens_mask=True,
        )
        require("special_tokens_mask" in encoded, "tokenizer_special_mask_missing")
        residue_mask = encoded["attention_mask"].bool() & ~encoded["special_tokens_mask"].bool()
        contact_targets = torch.zeros((*encoded["input_ids"].shape, 2), dtype=torch.float32)
        contact_mask = torch.zeros_like(contact_targets, dtype=torch.bool)
        for batch_index, row in enumerate(rows):
            positions = residue_mask[batch_index].nonzero(as_tuple=False).flatten()
            require(len(positions) == len(row.sequence), f"token_residue_alignment_failed:{row.candidate_id}")
            if row.contact_targets is not None and row.contact_mask is not None:
                contact_targets[batch_index, positions] = torch.tensor(row.contact_targets, dtype=torch.float32)
                contact_mask[batch_index, positions] = torch.tensor(row.contact_mask, dtype=torch.bool)
        return {
            "indices": list(indices),
            "candidate_ids": [row.candidate_id for row in rows],
            "parents": [row.parent for row in rows],
            "input_ids": encoded["input_ids"],
            "attention_mask": encoded["attention_mask"],
            "residue_mask": residue_mask,
            "structure": torch.tensor([row.structure for row in rows], dtype=torch.float32),
            "m2_base": torch.tensor(np.stack([self.base[index] for index in indices]), dtype=torch.float32),
            "targets": torch.tensor([row.targets for row in rows], dtype=torch.float32),
            "weights": torch.tensor([row.weight for row in rows], dtype=torch.float32),
            "contact_targets": contact_targets,
            "contact_mask": contact_mask,
        }


def rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = 0.5 * (start + end - 1)
        start = end
    return ranks


def spearman(target: np.ndarray, prediction: np.ndarray) -> float:
    if len(target) < 2 or np.std(target) < 1e-12 or np.std(prediction) < 1e-12:
        return 0.0
    return float(np.corrcoef(rankdata(target), rankdata(prediction))[0, 1])


def metrics(target: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    return {
        "spearman": spearman(target, prediction),
        "mae": float(np.mean(np.abs(target - prediction))),
        "rmse": float(np.sqrt(np.mean((target - prediction) ** 2))),
    }


def contact_positive_weights(rows: Sequence[TrainingRow], indices: Sequence[int]) -> Tensor:
    positive = np.zeros(2, dtype=np.float64)
    negative = np.zeros(2, dtype=np.float64)
    for index in indices:
        row = rows[index]
        if row.contact_targets is None or row.contact_mask is None:
            continue
        targets = np.asarray(row.contact_targets)
        masks = np.asarray(row.contact_mask, dtype=bool)
        for channel in range(2):
            selected = targets[:, channel][masks[:, channel]]
            positive[channel] += float(np.sum(selected))
            negative[channel] += float(np.sum(1.0 - selected))
    require(bool(np.all(positive > 0)), "contact_channel_has_no_positive_mass")
    return torch.tensor(np.clip(negative / positive, 1.0, 20.0), dtype=torch.float32)


def loader(
    rows: Sequence[TrainingRow], indices: Sequence[int], tokenizer: Any,
    base_by_index: Mapping[int, np.ndarray], batch_size: int, shuffle: bool, seed: int,
) -> DataLoader[Any]:
    return DataLoader(
        IndexedDataset(indices), batch_size=batch_size, shuffle=shuffle,
        generator=torch.Generator().manual_seed(seed), num_workers=0,
        collate_fn=Collator(rows, tokenizer, base_by_index),
    )


def move(batch: Mapping[str, Any], device: torch.device) -> dict[str, Any]:
    return {key: (value.to(device) if isinstance(value, Tensor) else value) for key, value in batch.items()}


def run_epoch(
    model: ResidueSurrogate,
    data: DataLoader[Any],
    device: torch.device,
    loss_config: ResidueLossConfig,
    positive_weights: Tensor,
    optimizer: AdamW | None,
    gradient_clip: float,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    training = optimizer is not None
    model.train(training)
    if model.backbone_mode == "frozen":
        model.backbone.eval()
    totals: dict[str, float] = {}
    count = 0
    target_values, prediction_values = [], []
    records: list[dict[str, Any]] = []
    for source in data:
        batch = move(source, device)
        with torch.set_grad_enabled(training):
            output = model(
                batch["input_ids"], batch["attention_mask"], batch["residue_mask"],
                batch["structure"], batch["m2_base"],
            )
            loss, parts = compute_loss(
                output, batch["targets"], batch["weights"], batch["parents"],
                batch["contact_targets"], batch["contact_mask"], loss_config,
                contact_positive_weights=positive_weights.to(device),
            )
        if training:
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_([parameter for parameter in model.parameters() if parameter.requires_grad], gradient_clip)
            optimizer.step()
        for name, value in parts.items():
            totals[name] = totals.get(name, 0.0) + float(value.detach().cpu())
        count += 1
        prediction = output["prediction"].detach().float().cpu().numpy()
        target = batch["targets"].detach().float().cpu().numpy()
        base = batch["m2_base"].detach().float().cpu().numpy()
        target_values.append(target[:, 2])
        prediction_values.append(prediction[:, 2])
        for item, candidate in enumerate(batch["candidate_ids"]):
            records.append({
                "candidate_id": candidate,
                "parent_framework_cluster": batch["parents"][item],
                "R_dual_min": float(target[item, 2]),
                "m2_prediction": float(base[item, 2]),
                "residue_prediction": float(prediction[item, 2]),
            })
    result = {f"loss_{name}": value / max(count, 1) for name, value in totals.items()}
    result.update(metrics(np.concatenate(target_values), np.concatenate(prediction_values)))
    return result, records


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def build_model(args: argparse.Namespace, device: torch.device) -> tuple[ResidueSurrogate, Any, str, ResidueHeadConfig]:
    backbone, tokenizer, hidden, model_identity = load_backbone(args)
    head_config = ResidueHeadConfig(
        backbone_hidden_size=hidden, structure_dim=args.structure_dim,
        fusion_dim=args.fusion_dim, dropout=args.dropout,
        residual_scale=args.residual_scale,
        detach_contact_pooling=not args.end_to_end_contact_pooling,
    )
    model = ResidueSurrogate(backbone, DualContactResidualHead(head_config), backbone_mode=args.backbone_mode)
    model.to(device)
    return model, tokenizer, model_identity, head_config


def train_stage(
    args: argparse.Namespace,
    rows: Sequence[TrainingRow],
    train_indices: Sequence[int],
    validation_indices: Sequence[int],
    train_base: Mapping[int, np.ndarray],
    validation_base: Mapping[int, np.ndarray],
    epochs: int,
    device: torch.device,
    seed: int,
) -> tuple[int, dict[str, Any], str, ResidueHeadConfig]:
    seed_everything(seed)
    model, tokenizer, model_identity, head_config = build_model(args, device)
    loss_config = ResidueLossConfig(
        dual_weight=args.dual_weight, receptor_weight=args.receptor_weight,
        contact_weight=args.contact_weight, ranking_weight=args.ranking_weight,
        residual_weight=args.residual_weight, huber_delta=args.huber_delta,
        ranking_minimum_delta=args.ranking_minimum_delta,
        ranking_temperature=args.ranking_temperature,
    )
    positive_weights = contact_positive_weights(rows, train_indices)
    train_loader = loader(rows, train_indices, tokenizer, train_base, args.batch_size, True, seed)
    validation_loader = loader(rows, validation_indices, tokenizer, validation_base, args.batch_size, False, seed)
    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    require(trainable, "no_trainable_parameters")
    optimizer = AdamW(trainable, lr=args.learning_rate, weight_decay=args.weight_decay)
    best_epoch = 0
    best_key = (-float("inf"), -float("inf"))
    history = []
    for epoch in range(epochs):
        train_metrics, _ = run_epoch(model, train_loader, device, loss_config, positive_weights, optimizer, args.gradient_clip)
        validation_metrics, _ = run_epoch(model, validation_loader, device, loss_config, positive_weights, None, args.gradient_clip)
        history.append({"epoch": epoch, "train": train_metrics, "validation": validation_metrics})
        key = (validation_metrics["spearman"], -validation_metrics["mae"])
        if key > best_key:
            best_key = key
            best_epoch = epoch
    return best_epoch, {
        "history": history,
        "best_epoch": best_epoch,
        "best_validation": history[best_epoch]["validation"],
        "loss_config": asdict(loss_config),
    }, model_identity, head_config


def final_refit(
    args: argparse.Namespace,
    rows: Sequence[TrainingRow],
    train_indices: Sequence[int],
    test_indices: Sequence[int],
    train_base: Mapping[int, np.ndarray],
    test_base: Mapping[int, np.ndarray],
    epochs: int,
    device: torch.device,
    seed: int,
) -> tuple[ResidueSurrogate, dict[str, Any], list[dict[str, Any]], str, ResidueHeadConfig, ResidueLossConfig]:
    seed_everything(seed)
    model, tokenizer, model_identity, head_config = build_model(args, device)
    loss_config = ResidueLossConfig(
        dual_weight=args.dual_weight, receptor_weight=args.receptor_weight,
        contact_weight=args.contact_weight, ranking_weight=args.ranking_weight,
        residual_weight=args.residual_weight, huber_delta=args.huber_delta,
        ranking_minimum_delta=args.ranking_minimum_delta,
        ranking_temperature=args.ranking_temperature,
    )
    positive_weights = contact_positive_weights(rows, train_indices)
    train_loader = loader(rows, train_indices, tokenizer, train_base, args.batch_size, True, seed)
    test_loader = loader(rows, test_indices, tokenizer, test_base, args.batch_size, False, seed)
    optimizer = AdamW([parameter for parameter in model.parameters() if parameter.requires_grad], lr=args.learning_rate, weight_decay=args.weight_decay)
    history = []
    for epoch in range(epochs):
        train_metrics, _ = run_epoch(model, train_loader, device, loss_config, positive_weights, optimizer, args.gradient_clip)
        history.append({"epoch": epoch, "train": train_metrics})
    test_metrics, records = run_epoch(model, test_loader, device, loss_config, positive_weights, None, args.gradient_clip)
    m2_target = np.asarray([rows[index].targets[2] for index in test_indices])
    m2_prediction = np.asarray([test_base[index][2] for index in test_indices])
    result = {
        "training_history": history,
        "outer_test": test_metrics,
        "m2_outer_test": metrics(m2_target, m2_prediction),
    }
    return model, result, records, model_identity, head_config, loss_config


def run_outer_fold(
    args: argparse.Namespace,
    rows: Sequence[TrainingRow],
    feature_names: Sequence[str],
    outer_fold: int,
    output_dir: Path,
    input_hashes: Mapping[str, str],
) -> dict[str, Any]:
    all_indices = list(range(len(rows)))
    outer_test = [index for index, row in enumerate(rows) if row.outer_fold == outer_fold]
    outer_train = [index for index in all_indices if index not in set(outer_test)]
    require(outer_test and outer_train, f"outer_fold_empty:{outer_fold}")
    require({rows[index].parent for index in outer_train}.isdisjoint(rows[index].parent for index in outer_test), "outer_parent_leakage")
    assignments = {index: parent_inner_fold(rows[index].parent, outer_fold, args.inner_folds) for index in outer_train}
    inner_validation = [index for index in outer_train if assignments[index] == args.inner_validation_fold]
    inner_train = [index for index in outer_train if assignments[index] != args.inner_validation_fold]
    require(inner_validation and inner_train, f"inner_validation_fold_empty:{outer_fold}:{args.inner_validation_fold}")
    require({rows[index].parent for index in inner_train}.isdisjoint(rows[index].parent for index in inner_validation), "inner_parent_leakage")

    disk_guard(output_dir.parent, args.minimum_free_gb)
    output_dir.mkdir(parents=False, exist_ok=False)
    atomic_json(output_dir / "PREFLIGHT.json", {
        "schema_version": f"{SCHEMA_VERSION}_preflight",
        "status": "PASS_PREFLIGHT_TRAINING_NOT_COMPLETE",
        "outer_fold": outer_fold,
        "input_hashes": dict(input_hashes),
        "counts": {
            "outer_train": len(outer_train), "outer_test": len(outer_test),
            "inner_train": len(inner_train), "inner_validation": len(inner_validation),
        },
        "parent_closure": {
            "outer_train_parents": len({rows[index].parent for index in outer_train}),
            "outer_test_parents": len({rows[index].parent for index in outer_test}),
            "inner_train_parents": len({rows[index].parent for index in inner_train}),
            "inner_validation_parents": len({rows[index].parent for index in inner_validation}),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    })

    arrays = arrays_from_rows(rows)
    selection_crossfit, selection_counts = crossfit_m2(inner_train, arrays, outer_fold, args.inner_folds, args.ridge_alpha)
    selection_train_base = {index: selection_crossfit[position] for position, index in enumerate(inner_train)}
    selection_state = fit_weighted_ridge(
        arrays["structure"][inner_train], arrays["targets"][inner_train], arrays["weights"][inner_train], args.ridge_alpha,
    )
    selection_validation_prediction = predict_ridge(selection_state, arrays["structure"][inner_validation])
    selection_validation_base = {index: selection_validation_prediction[position] for position, index in enumerate(inner_validation)}

    device = torch.device(args.device)
    require(device.type != "cuda" or torch.cuda.is_available(), "cuda_requested_but_unavailable")
    best_epoch, selection_result, model_identity, head_config = train_stage(
        args, rows, inner_train, inner_validation, selection_train_base,
        selection_validation_base, args.max_epochs, device, args.seed + outer_fold * 1000,
    )
    atomic_json(output_dir / "INNER_SELECTION.json", selection_result)

    final_crossfit, final_counts = crossfit_m2(outer_train, arrays, outer_fold, args.inner_folds, args.ridge_alpha)
    final_train_base = {index: final_crossfit[position] for position, index in enumerate(outer_train)}
    final_m2_state = fit_weighted_ridge(
        arrays["structure"][outer_train], arrays["targets"][outer_train], arrays["weights"][outer_train], args.ridge_alpha,
    )
    outer_prediction = predict_ridge(final_m2_state, arrays["structure"][outer_test])
    outer_base = {index: outer_prediction[position] for position, index in enumerate(outer_test)}
    model, final_result, records, final_identity, final_head, loss_config = final_refit(
        args, rows, outer_train, outer_test, final_train_base, outer_base,
        best_epoch + 1, device, args.seed + outer_fold * 1000 + 500,
    )
    require(model_identity == final_identity and head_config == final_head, "selection_final_model_identity_mismatch")

    disk_guard(output_dir, args.minimum_free_gb)
    contract = model_contract(final_head, loss_config, args.backbone_mode)
    contract.update({
        "schema_version": SCHEMA_VERSION,
        "outer_fold": outer_fold,
        "inner_folds": args.inner_folds,
        "inner_validation_fold": args.inner_validation_fold,
        "ridge_alpha": args.ridge_alpha,
        "selected_epoch_zero_based": best_epoch,
        "final_refit_epochs": best_epoch + 1,
        "input_hashes": dict(input_hashes),
        "model_identity": final_identity,
        "feature_names": list(feature_names),
        "counts": {
            "outer_train": len(outer_train), "outer_test": len(outer_test),
            "inner_train": len(inner_train), "inner_validation": len(inner_validation),
        },
        "inner_crossfit_counts_selection": selection_counts,
        "inner_crossfit_counts_final": final_counts,
    })
    atomic_json(output_dir / "contract.json", contract)
    m2_path = output_dir / "m2_outer_train_fit.npz"
    np.savez_compressed(
        m2_path,
        x_mean=final_m2_state.x_mean, x_scale=final_m2_state.x_scale,
        y_mean=final_m2_state.y_mean, coefficient=final_m2_state.coefficient,
        alpha=np.asarray([final_m2_state.alpha]), feature_names=np.asarray(feature_names),
    )
    checkpoint = {
        "schema_version": "pvrig_v6_residue_adapter_head_checkpoint_v1",
        "outer_fold": outer_fold,
        "trainable_state": trainable_checkpoint_state(model),
        "contract_sha256": sha256_file(output_dir / "contract.json"),
        "m2_sha256": sha256_file(m2_path),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_torch_save(output_dir / "adapter_head.pt", checkpoint)
    with (output_dir / "outer_test_predictions.tsv").open("w", encoding="utf-8", newline="") as handle:
        fields = ["candidate_id", "parent_framework_cluster", "R_dual_min", "m2_prediction", "residue_prediction"]
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(records, key=lambda row: row["candidate_id"]))
    result = {
        "schema_version": f"{SCHEMA_VERSION}_outer_result",
        "status": "PASS_OUTER_FOLD_COMPLETE",
        "outer_fold": outer_fold,
        "selection": selection_result,
        "final": final_result,
        "artifacts": {
            name: sha256_file(output_dir / name)
            for name in ("contract.json", "m2_outer_train_fit.npz", "adapter_head.pt", "outer_test_predictions.tsv")
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_json(output_dir / "RESULT.json", result)
    return result


def train(args: argparse.Namespace) -> dict[str, Any]:
    require(args.backbone_mode in {"frozen", "lora"}, "invalid_backbone_mode")
    require(args.max_epochs >= 1 and args.batch_size >= 1 and args.inner_folds >= 2, "training_dimensions_invalid")
    require(0 <= args.inner_validation_fold < args.inner_folds, "inner_validation_fold_invalid")
    require(not args.output_dir.exists() and not args.output_dir.is_symlink(), "output_dir_must_not_exist")
    training_hash = sha256_file(args.training_tsv)
    contact_hash = sha256_file(args.contact_tsv_gz)
    if not args.smoke_mode:
        require(args.expected_training_sha256 == training_hash, "training_sha256_mismatch")
        require(args.expected_contact_sha256 == contact_hash, "contact_sha256_mismatch")
    disk_guard(args.output_dir.parent, args.minimum_free_gb)
    rows, feature_names, data_audit = read_training_table(
        args.training_tsv, args.contact_tsv_gz,
        structure_prefixes=args.structure_prefix,
        structure_dim=args.structure_dim,
    )
    available_folds = sorted({row.outer_fold for row in rows})
    selected_folds = available_folds if args.outer_fold == "all" else [int(args.outer_fold)]
    require(set(selected_folds) <= set(available_folds), "requested_outer_fold_unavailable")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    input_hashes = {"training_tsv": training_hash, "contact_tsv_gz": contact_hash}
    results = []
    for outer_fold in selected_folds:
        fold_dir = args.output_dir / f"outer_fold_{outer_fold}"
        try:
            results.append(run_outer_fold(
                args, rows, feature_names, outer_fold, fold_dir, input_hashes,
            ))
        except Exception as error:
            fold_dir.mkdir(parents=False, exist_ok=True)
            atomic_json(fold_dir / "FAILURE.json", {
                "schema_version": f"{SCHEMA_VERSION}_failure",
                "status": "FAIL_OUTER_FOLD_INCOMPLETE",
                "outer_fold": outer_fold,
                "error_type": type(error).__name__,
                "error": str(error),
                "claim_boundary": CLAIM_BOUNDARY,
            })
            raise
    summary = {
        "schema_version": f"{SCHEMA_VERSION}_run_summary",
        "status": "PASS_NESTED_RESIDUE_TRAINING_COMPLETE",
        "outer_folds": selected_folds,
        "data_audit": data_audit,
        "input_hashes": input_hashes,
        "results": [
            {
                "outer_fold": result["outer_fold"],
                "m2_outer_test": result["final"]["m2_outer_test"],
                "residue_outer_test": result["final"]["outer_test"],
            }
            for result in results
        ],
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_json(args.output_dir / "RUN_SUMMARY.json", summary)
    return summary


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--training-tsv", type=Path, required=True)
    value.add_argument("--contact-tsv-gz", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--expected-training-sha256")
    value.add_argument("--expected-contact-sha256")
    value.add_argument("--smoke-mode", action="store_true")
    value.add_argument("--structure-prefix", action="append", default=[])
    value.add_argument("--structure-dim", type=int, default=126)
    value.add_argument("--outer-fold", default="all")
    value.add_argument("--inner-folds", type=int, default=3)
    value.add_argument("--inner-validation-fold", type=int, default=0)
    value.add_argument("--ridge-alpha", type=float, default=10.0)
    value.add_argument("--backbone-kind", choices=("tiny", "hf"), default="hf")
    value.add_argument("--backbone-mode", choices=("frozen", "lora"), default="frozen")
    value.add_argument("--model-path", type=Path)
    value.add_argument("--model-identity-file", type=Path)
    value.add_argument("--expected-model-sha256")
    value.add_argument("--trust-remote-code", action="store_true")
    value.add_argument("--lora-r", type=int, default=8)
    value.add_argument("--lora-alpha", type=int, default=16)
    value.add_argument("--lora-dropout", type=float, default=0.05)
    value.add_argument("--lora-target-modules", default="query,key,value")
    value.add_argument("--tiny-hidden-size", type=int, default=16)
    value.add_argument("--fusion-dim", type=int, default=64)
    value.add_argument("--dropout", type=float, default=0.10)
    value.add_argument("--residual-scale", type=float, default=0.12)
    value.add_argument("--end-to-end-contact-pooling", action="store_true")
    value.add_argument("--dual-weight", type=float, default=1.0)
    value.add_argument("--receptor-weight", type=float, default=0.35)
    value.add_argument("--contact-weight", type=float, default=0.25)
    value.add_argument("--ranking-weight", type=float, default=0.10)
    value.add_argument("--residual-weight", type=float, default=0.05)
    value.add_argument("--huber-delta", type=float, default=0.03)
    value.add_argument("--ranking-minimum-delta", type=float, default=0.005)
    value.add_argument("--ranking-temperature", type=float, default=0.02)
    value.add_argument("--max-epochs", type=int, default=12)
    value.add_argument("--batch-size", type=int, default=8)
    value.add_argument("--learning-rate", type=float, default=2e-4)
    value.add_argument("--weight-decay", type=float, default=0.01)
    value.add_argument("--gradient-clip", type=float, default=1.0)
    value.add_argument("--seed", type=int, default=43)
    value.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    value.add_argument("--minimum-free-gb", type=float, default=180.0)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not args.structure_prefix:
        args.structure_prefix = ["ALL__", "CDR1__", "CDR2__", "CDR3__"]
    result = train(args)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
