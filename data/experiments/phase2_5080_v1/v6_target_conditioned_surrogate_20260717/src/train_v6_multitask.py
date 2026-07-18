#!/usr/bin/env python3
"""Train V6 from a frozen combined TSV using whole-parent validation."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch
from torch import Tensor
from torch.optim import AdamW
from torch.optim.lr_scheduler import LambdaLR
from torch.utils.data import DataLoader, Dataset, Subset

from v6_model import (
    TARGET_NAMES,
    HuggingFaceResidueBackbone,
    TinyResidueBackbone,
    TinyResidueTokenizer,
    V6Error,
    V6LossConfig,
    V6ModelConfig,
    V6MultitaskModel,
    build_parent_folds,
    compute_multitask_loss,
    model_contract,
    require,
)


REQUIRED_FIELDS = {
    "candidate_id",
    "sequence",
    "parent_framework_cluster",
    *TARGET_NAMES,
}


@dataclass(frozen=True)
class TrainingRow:
    candidate_id: str
    sequence: str
    parent: str
    targets: tuple[float, float, float]
    sample_weight: float
    structure: tuple[float, ...]
    contact: tuple[float, ...] | None = None
    fold_id: int | None = None


class RowDataset(Dataset[TrainingRow]):
    def __init__(self, rows: Sequence[TrainingRow]) -> None:
        self.rows = list(rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> TrainingRow:
        return self.rows[index]


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"training_tsv_missing_or_symlink:{path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    require(REQUIRED_FIELDS <= set(fields), f"training_fields_missing:{sorted(REQUIRED_FIELDS-set(fields))}")
    return fields, rows


def read_structure_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"structure_tsv_missing_or_symlink:{path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    require("candidate_id" in fields, "structure_candidate_id_missing")
    return fields, rows


def load_contact_jsonl(path: Path | None) -> dict[str, tuple[float, ...]]:
    if path is None:
        return {}
    require(path.is_file() and not path.is_symlink(), f"contact_jsonl_missing_or_symlink:{path}")
    result: dict[str, tuple[float, ...]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            candidate = str(payload["candidate_id"])
            require(candidate not in result, f"duplicate_contact_candidate:{candidate}")
            values = tuple(float(value) for value in payload["contact_targets"])
            require(values and all(math.isfinite(value) and 0 <= value <= 1 for value in values), f"invalid_contact_values:{line_number}")
            result[candidate] = values
    return result


def load_rows(
    path: Path,
    *,
    structure_prefix: str,
    structure_dim: int,
    structure_tsv: Sequence[Path] | None = None,
    contact_jsonl: Path | None = None,
) -> tuple[list[TrainingRow], list[str]]:
    fields, raw = read_tsv(path)
    structure_by_id: dict[str, dict[str, str]] = {}
    structure_paths = list(structure_tsv or [])
    if not structure_paths:
        structure_fields = fields
        feature_names = [field for field in structure_fields if field.startswith(structure_prefix)]
    else:
        metadata = {
            "schema_version", "candidate_id", "sequence_sha256", "model_split",
            "parent_framework_cluster", "target_patch_id", "design_mode",
            "monomer_sha256", "claim_boundary",
        }
        feature_names = []
        for structure_path in structure_paths:
            structure_fields, structure_rows = read_structure_tsv(structure_path)
            current_names = [field for field in structure_fields if field.startswith(structure_prefix)]
            if not current_names:
                current_names = [field for field in structure_fields if field not in metadata]
            require(len(current_names) == structure_dim, f"structure_feature_count_invalid:{structure_path}:{len(current_names)}")
            if feature_names:
                require(current_names == feature_names, f"structure_feature_schema_mismatch:{structure_path}")
            else:
                feature_names = current_names
            for structure_row in structure_rows:
                candidate = structure_row["candidate_id"]
                require(candidate not in structure_by_id, f"duplicate_structure_candidate:{candidate}")
                structure_by_id[candidate] = structure_row
    require(len(feature_names) == structure_dim, f"structure_feature_count_invalid:{len(feature_names)}")
    contacts = load_contact_jsonl(contact_jsonl)
    rows: list[TrainingRow] = []
    seen: set[str] = set()
    for source in raw:
        candidate = source["candidate_id"]
        require(candidate not in seen, f"duplicate_candidate:{candidate}")
        seen.add(candidate)
        sequence = source["sequence"].strip().upper()
        require(sequence and all(aa.isalpha() for aa in sequence), f"invalid_sequence:{candidate}")
        targets = tuple(float(source[name]) for name in TARGET_NAMES)
        require(all(math.isfinite(value) for value in targets), f"nonfinite_target:{candidate}")
        require(abs(min(targets[0], targets[1]) - targets[2]) <= 1e-6, f"dual_min_contract_failed:{candidate}")
        weight = float(source.get("sample_weight") or source.get("reliability_weight") or 1.0)
        structure_source = source if not structure_paths else structure_by_id.get(candidate)
        require(structure_source is not None, f"structure_candidate_missing:{candidate}")
        if "sequence_sha256" in source and "sequence_sha256" in structure_source:
            require(source["sequence_sha256"] == structure_source["sequence_sha256"], f"structure_sequence_mismatch:{candidate}")
        if "parent_framework_cluster" in structure_source:
            require(source["parent_framework_cluster"] == structure_source["parent_framework_cluster"], f"structure_parent_mismatch:{candidate}")
        structure = tuple(float(structure_source[name]) for name in feature_names)
        require(weight > 0 and math.isfinite(weight), f"invalid_sample_weight:{candidate}")
        require(all(math.isfinite(value) for value in structure), f"nonfinite_structure:{candidate}")
        contact = contacts.get(candidate)
        if contact is not None:
            require(len(contact) == len(sequence), f"contact_sequence_length_mismatch:{candidate}")
        fold_text = source.get("fold_id", "").strip()
        fold_id = int(fold_text) if fold_text else None
        rows.append(TrainingRow(candidate, sequence, source["parent_framework_cluster"], targets, weight, structure, contact, fold_id))
    require(rows, "training_table_empty")
    require(not contacts.keys() - seen, "contact_candidates_not_in_training_table")
    return rows, feature_names


def frozen_parent_folds(rows: Sequence[TrainingRow], fold_count: int) -> list[list[int]] | None:
    if all(row.fold_id is None for row in rows):
        return None
    require(all(row.fold_id is not None for row in rows), "partial_frozen_fold_assignment")
    require({int(row.fold_id) for row in rows} == set(range(fold_count)), "frozen_fold_ids_invalid")
    by_parent: dict[str, set[int]] = {}
    folds: list[list[int]] = [[] for _ in range(fold_count)]
    for index, row in enumerate(rows):
        fold = int(row.fold_id)
        folds[fold].append(index)
        by_parent.setdefault(row.parent, set()).add(fold)
    require(all(len(values) == 1 for values in by_parent.values()), "frozen_fold_parent_leakage")
    require(all(folds), "frozen_fold_empty")
    return folds


class ResidueCollator:
    def __init__(self, tokenizer: Any, *, max_length: int | None = None) -> None:
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __call__(self, rows: Sequence[TrainingRow]) -> dict[str, Any]:
        sequences = [row.sequence for row in rows]
        encoded = self.tokenizer(
            sequences,
            padding=True,
            truncation=self.max_length is not None,
            max_length=self.max_length,
            return_tensors="pt",
            return_special_tokens_mask=True,
        )
        require("special_tokens_mask" in encoded, "tokenizer_must_return_special_tokens_mask")
        residue_mask = encoded["attention_mask"].bool() & ~encoded["special_tokens_mask"].bool()
        for index, sequence in enumerate(sequences):
            require(int(residue_mask[index].sum()) == len(sequence), f"token_residue_alignment_failed:{rows[index].candidate_id}")
        contact_targets = torch.zeros_like(encoded["input_ids"], dtype=torch.float32)
        contact_mask = torch.zeros_like(encoded["input_ids"], dtype=torch.bool)
        for index, row in enumerate(rows):
            if row.contact is None:
                continue
            positions = residue_mask[index].nonzero(as_tuple=False).flatten()
            contact_targets[index, positions] = torch.tensor(row.contact, dtype=torch.float32)
            contact_mask[index, positions] = True
        return {
            "candidate_ids": [row.candidate_id for row in rows],
            "parent_ids": [row.parent for row in rows],
            "input_ids": encoded["input_ids"],
            "attention_mask": encoded["attention_mask"],
            "residue_mask": residue_mask,
            "structure_features": torch.tensor([row.structure for row in rows], dtype=torch.float32),
            "targets": torch.tensor([row.targets for row in rows], dtype=torch.float32),
            "sample_weight": torch.tensor([row.sample_weight for row in rows], dtype=torch.float32),
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


def spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) < 2 or np.std(y_true) < 1e-12 or np.std(y_pred) < 1e-12:
        return 0.0
    return float(np.corrcoef(rankdata(y_true), rankdata(y_pred))[0, 1])


def parent_center(values: np.ndarray, groups: Sequence[str]) -> np.ndarray:
    centered = values.copy()
    for group in sorted(set(groups)):
        indices = np.asarray([index for index, value in enumerate(groups) if value == group])
        centered[indices] -= float(np.mean(centered[indices]))
    return centered


def evaluation_metrics(target: np.ndarray, prediction: np.ndarray, groups: Sequence[str]) -> dict[str, float]:
    require(target.shape == prediction.shape and target.ndim == 1, "metric_shape_invalid")
    budget = max(1, math.ceil(0.20 * len(target)))
    truth = set(np.argsort(-target, kind="mergesort")[:budget].tolist())
    predicted = set(np.argsort(-prediction, kind="mergesort")[:budget].tolist())
    return {
        "spearman": spearman(target, prediction),
        "parent_centered_spearman": spearman(parent_center(target, groups), parent_center(prediction, groups)),
        "mae": float(np.mean(np.abs(target - prediction))),
        "top20_recall": len(truth.intersection(predicted)) / len(truth),
    }


def move_batch(batch: Mapping[str, Any], device: torch.device) -> dict[str, Any]:
    return {key: (value.to(device) if isinstance(value, Tensor) else value) for key, value in batch.items()}


def cosine_scheduler(optimizer: AdamW, warmup_steps: int, total_steps: int) -> LambdaLR:
    require(total_steps > 0 and 0 <= warmup_steps < total_steps, "invalid_scheduler_steps")

    def scale(step: int) -> float:
        if step < warmup_steps:
            return float(step + 1) / max(1, warmup_steps)
        progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
        return 0.5 * (1.0 + math.cos(math.pi * min(progress, 1.0)))

    return LambdaLR(optimizer, scale)


def atomic_torch_save(payload: Mapping[str, Any], path: Path) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    torch.save(dict(payload), temporary)
    os.replace(temporary, path)


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(payload), sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def run_epoch(
    model: V6MultitaskModel,
    loader: DataLoader[Any],
    loss_config: V6LossConfig,
    device: torch.device,
    *,
    optimizer: AdamW | None,
    scheduler: LambdaLR | None,
    precision: str,
    gradient_clip: float,
    gradient_accumulation: int,
) -> dict[str, Any]:
    training = optimizer is not None
    model.train(training)
    totals: dict[str, float] = {}
    predictions, targets, groups = [], [], []
    if training:
        optimizer.zero_grad(set_to_none=True)
    for batch_index, source in enumerate(loader):
        batch = move_batch(source, device)
        enabled = precision == "bf16"
        with torch.set_grad_enabled(training), torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=enabled):
            output = model(
                input_ids=batch["input_ids"],
                attention_mask=batch["attention_mask"],
                residue_mask=batch["residue_mask"],
                structure_features=batch["structure_features"],
            )
            loss, parts = compute_multitask_loss(
                output,
                batch["targets"],
                batch["sample_weight"],
                batch["parent_ids"],
                loss_config,
                contact_targets=batch["contact_targets"],
                contact_mask=batch["contact_mask"],
            )
            scaled_loss = loss / gradient_accumulation
        if training:
            scaled_loss.backward()
            should_step = (batch_index + 1) % gradient_accumulation == 0 or batch_index + 1 == len(loader)
            if should_step:
                torch.nn.utils.clip_grad_norm_(model.parameters(), gradient_clip)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                if scheduler is not None:
                    scheduler.step()
        for name, value in parts.items():
            totals[name] = totals.get(name, 0.0) + float(value.detach().cpu())
        predictions.append(output["prediction"][:, 2].detach().float().cpu().numpy())
        targets.append(batch["targets"][:, 2].detach().float().cpu().numpy())
        groups.extend(batch["parent_ids"])
    count = max(1, len(loader))
    result: dict[str, Any] = {f"loss_{name}": value / count for name, value in totals.items()}
    result.update(evaluation_metrics(np.concatenate(targets), np.concatenate(predictions), groups))
    return result


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def load_backbone(args: argparse.Namespace) -> tuple[torch.nn.Module, int, Any]:
    if args.backbone_kind == "tiny":
        tokenizer = TinyResidueTokenizer()
        backbone = TinyResidueBackbone(len(tokenizer), args.tiny_hidden_size)
        return backbone, backbone.hidden_size, tokenizer
    require(args.model_path is not None, "model_path_required_for_hf_backbone")
    lora = None
    if args.lora:
        lora = {
            "r": args.lora_r,
            "alpha": args.lora_alpha,
            "dropout": args.lora_dropout,
            "target_modules": [value for value in args.lora_target_modules.split(",") if value],
        }
    backbone, tokenizer = HuggingFaceResidueBackbone.from_local(
        args.model_path,
        gradient_checkpointing=args.gradient_checkpointing,
        trust_remote_code=args.trust_remote_code,
        lora=lora,
        load_dtype=args.load_dtype,
    )
    if args.freeze_backbone:
        for parameter in backbone.parameters():
            parameter.requires_grad_(False)
    return backbone, backbone.hidden_size, tokenizer


def train(args: argparse.Namespace) -> dict[str, Any]:
    require(args.precision in {"fp32", "bf16"}, "invalid_precision")
    require(args.epochs >= 1 and args.batch_size >= 1 and args.gradient_accumulation >= 1, "invalid_training_dimensions")
    require(not args.output_dir.is_symlink(), "output_dir_symlink_forbidden")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    require(args.resume is not None or not (args.output_dir / "metrics.jsonl").exists(), "existing_run_requires_resume")
    seed_everything(args.seed)
    rows, feature_names = load_rows(
        args.train_tsv,
        structure_prefix=args.structure_prefix,
        structure_dim=args.structure_dim,
        structure_tsv=args.structure_tsv,
        contact_jsonl=args.contact_jsonl,
    )
    folds = frozen_parent_folds(rows, args.fold_count) or build_parent_folds([row.parent for row in rows], args.fold_count, args.split_seed)
    require(0 <= args.validation_fold < len(folds), "validation_fold_out_of_range")
    validation_indices = folds[args.validation_fold]
    validation_set = set(validation_indices)
    train_indices = [index for index in range(len(rows)) if index not in validation_set]
    require(set(rows[index].parent for index in train_indices).isdisjoint(rows[index].parent for index in validation_indices), "parent_split_leakage")

    backbone, hidden_size, tokenizer = load_backbone(args)
    model_config = V6ModelConfig(
        structure_dim=args.structure_dim,
        fusion_dim=args.fusion_dim,
        dropout=args.dropout,
        residual_scale=args.residual_scale,
        uncertainty_head=args.uncertainty_weight > 0,
        contact_head=args.contact_weight > 0,
        freeze_m2=args.freeze_m2,
    )
    loss_config = V6LossConfig(
        dual_weight=args.dual_weight,
        receptor_weight=args.receptor_weight,
        contact_weight=args.contact_weight,
        ranking_weight=args.ranking_weight,
        uncertainty_weight=args.uncertainty_weight,
        residual_weight=args.residual_weight,
        huber_delta=args.huber_delta,
        ranking_margin=args.ranking_margin,
        ranking_temperature=args.ranking_temperature,
    )
    model = V6MultitaskModel(backbone, hidden_size, model_config)
    if args.m2_checkpoint is not None:
        payload = torch.load(args.m2_checkpoint, map_location="cpu", weights_only=False)
        state = payload.get("m2_head", payload)
        if "model" in payload:
            state = {
                key.removeprefix("m2_head."): value
                for key, value in payload["model"].items()
                if key.startswith("m2_head.")
            }
        require(set(state) == {"weight", "bias"}, "m2_checkpoint_state_invalid")
        model.load_m2_state(state, freeze=args.freeze_m2)
    elif args.freeze_m2:
        raise V6Error("freeze_m2_requires_m2_checkpoint")
    device = torch.device(args.device)
    require(device.type != "cuda" or torch.cuda.is_available(), "cuda_requested_but_unavailable")
    model.to(device)
    collator = ResidueCollator(tokenizer, max_length=args.max_length)
    generator = torch.Generator().manual_seed(args.seed)
    train_loader = DataLoader(
        Subset(RowDataset(rows), train_indices),
        batch_size=args.batch_size,
        shuffle=True,
        generator=generator,
        num_workers=0,
        collate_fn=collator,
    )
    validation_loader = DataLoader(
        Subset(RowDataset(rows), validation_indices),
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=0,
        collate_fn=collator,
    )
    backbone_parameters = [parameter for parameter in model.backbone.parameters() if parameter.requires_grad]
    backbone_ids = {id(parameter) for parameter in backbone_parameters}
    head_parameters = [parameter for parameter in model.parameters() if parameter.requires_grad and id(parameter) not in backbone_ids]
    parameter_groups = []
    if backbone_parameters:
        parameter_groups.append({"params": backbone_parameters, "lr": args.backbone_learning_rate or args.learning_rate})
    if head_parameters:
        parameter_groups.append({"params": head_parameters, "lr": args.learning_rate})
    require(bool(parameter_groups), "no_trainable_parameters")
    optimizer = AdamW(parameter_groups, lr=args.learning_rate, weight_decay=args.weight_decay)
    steps_per_epoch = math.ceil(len(train_loader) / args.gradient_accumulation)
    total_steps = max(1, steps_per_epoch * args.epochs)
    scheduler = cosine_scheduler(optimizer, min(args.warmup_steps, total_steps - 1), total_steps)
    start_epoch, best_spearman, stale = 0, -float("inf"), 0
    if args.resume is not None:
        checkpoint = torch.load(args.resume, map_location="cpu", weights_only=False)
        model.load_state_dict(checkpoint["model"], strict=True)
        optimizer.load_state_dict(checkpoint["optimizer"])
        scheduler.load_state_dict(checkpoint["scheduler"])
        start_epoch = int(checkpoint["epoch"]) + 1
        best_spearman = float(checkpoint["best_spearman"])
        stale = int(checkpoint.get("stale", 0))

    contract = model_contract(model, loss_config)
    contract.update({
        "feature_names": feature_names,
        "row_count": len(rows),
        "train_count": len(train_indices),
        "validation_count": len(validation_indices),
        "validation_fold": args.validation_fold,
        "fold_count": args.fold_count,
        "seed": args.seed,
        "split_seed": args.split_seed,
        "backbone_kind": args.backbone_kind,
        "model_path": str(args.model_path) if args.model_path else None,
        "structure_tsv": [str(path) for path in (args.structure_tsv or [])],
    })
    (args.output_dir / "contract.json").write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    metrics_path = args.output_dir / "metrics.jsonl"
    last_validation: dict[str, Any] = {}
    for epoch in range(start_epoch, args.epochs):
        train_metrics = run_epoch(
            model, train_loader, loss_config, device,
            optimizer=optimizer, scheduler=scheduler, precision=args.precision,
            gradient_clip=args.gradient_clip, gradient_accumulation=args.gradient_accumulation,
        )
        validation_metrics = run_epoch(
            model, validation_loader, loss_config, device,
            optimizer=None, scheduler=None, precision=args.precision,
            gradient_clip=args.gradient_clip, gradient_accumulation=1,
        )
        last_validation = validation_metrics
        record = {"epoch": epoch, "train": train_metrics, "validation": validation_metrics, "lr": optimizer.param_groups[0]["lr"]}
        append_jsonl(metrics_path, record)
        improved = validation_metrics["spearman"] > best_spearman
        if improved:
            best_spearman = validation_metrics["spearman"]
            stale = 0
        else:
            stale += 1
        checkpoint = {
            "epoch": epoch,
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict(),
            "best_spearman": best_spearman,
            "stale": stale,
            "contract": contract,
        }
        atomic_torch_save(checkpoint, args.output_dir / "last.pt")
        if improved:
            atomic_torch_save(checkpoint, args.output_dir / "best.pt")
        if stale >= args.early_stopping_patience:
            break
    result = {
        "status": "COMPLETE",
        "best_validation_spearman": best_spearman,
        "last_validation": last_validation,
        "output_dir": str(args.output_dir),
    }
    (args.output_dir / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--train-tsv", type=Path, required=True)
    value.add_argument("--structure-tsv", type=Path, action="append", help="Repeat for disjoint structure feature shards.")
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--contact-jsonl", type=Path)
    value.add_argument("--structure-prefix", default="structure_")
    value.add_argument("--structure-dim", type=int, default=126)
    value.add_argument("--backbone-kind", choices=("tiny", "esm2", "esmc", "hf"), default="esm2")
    value.add_argument("--model-path", type=Path)
    value.add_argument("--trust-remote-code", action="store_true")
    value.add_argument("--load-dtype", choices=("auto", "float32", "bfloat16"), default="auto")
    value.add_argument("--freeze-backbone", action="store_true")
    value.add_argument("--gradient-checkpointing", action="store_true")
    value.add_argument("--lora", action="store_true")
    value.add_argument("--lora-r", type=int, default=8)
    value.add_argument("--lora-alpha", type=int, default=16)
    value.add_argument("--lora-dropout", type=float, default=0.05)
    value.add_argument("--lora-target-modules", default="query,key,value")
    value.add_argument("--tiny-hidden-size", type=int, default=32)
    value.add_argument("--fusion-dim", type=int, default=128)
    value.add_argument("--dropout", type=float, default=0.10)
    value.add_argument("--residual-scale", type=float, default=0.15)
    value.add_argument("--freeze-m2", action="store_true")
    value.add_argument("--m2-checkpoint", type=Path)
    value.add_argument("--dual-weight", type=float, default=1.0)
    value.add_argument("--receptor-weight", type=float, default=0.35)
    value.add_argument("--contact-weight", type=float, default=0.0)
    value.add_argument("--ranking-weight", type=float, default=0.0)
    value.add_argument("--uncertainty-weight", type=float, default=0.0)
    value.add_argument("--residual-weight", type=float, default=0.10)
    value.add_argument("--huber-delta", type=float, default=0.03)
    value.add_argument("--ranking-margin", type=float, default=0.005)
    value.add_argument("--ranking-temperature", type=float, default=0.02)
    value.add_argument("--fold-count", type=int, default=5)
    value.add_argument("--validation-fold", type=int, default=0)
    value.add_argument("--split-seed", type=int, default=20260717)
    value.add_argument("--seed", type=int, default=43)
    value.add_argument("--epochs", type=int, default=20)
    value.add_argument("--batch-size", type=int, default=8)
    value.add_argument("--gradient-accumulation", type=int, default=1)
    value.add_argument("--learning-rate", type=float, default=2e-4)
    value.add_argument("--backbone-learning-rate", type=float)
    value.add_argument("--weight-decay", type=float, default=0.01)
    value.add_argument("--warmup-steps", type=int, default=10)
    value.add_argument("--gradient-clip", type=float, default=1.0)
    value.add_argument("--early-stopping-patience", type=int, default=5)
    value.add_argument("--precision", choices=("fp32", "bf16"), default="fp32")
    value.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    value.add_argument("--max-length", type=int)
    value.add_argument("--resume", type=Path)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    result = train(args)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
