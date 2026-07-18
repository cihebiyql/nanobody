#!/usr/bin/env python3
"""V1.1 production trainer with nested whole-parent selection and resumability."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import shutil
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import numpy as np
import torch
from torch import Tensor, nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import LambdaLR
from torch.utils.data import DataLoader, Sampler

import train_nested_residue_surrogate as v1
from residue_model import (
    CLAIM_BOUNDARY,
    DualContactResidualHead,
    ResidueHeadConfig,
    ResidueLossConfig,
    ResidueSurrogate,
    compute_loss,
    load_trainable_checkpoint_state,
    model_contract,
    require,
    trainable_checkpoint_state,
)


SCHEMA_VERSION = "pvrig_v6_nested_residue_surrogate_v1_1"
INNER_FOLD_COUNT = 5
# Exact namespaces present in the frozen 126-feature monomer table.  The order
# is inherited from the TSV header and itself bound into the run contract.
STRUCTURE_PREFIXES = (
    "ALL__",
    "CDR1_CDR2__", "CDR1_CDR3__", "CDR1_FRAMEWORK__", "CDR1__",
    "CDR2_CDR3__", "CDR2_FRAMEWORK__", "CDR2__",
    "CDR3_FRAMEWORK__", "CDR3__",
    "CDR_ALL__", "FRAMEWORK__",
)
FROZEN_EXTERNAL_SHA256 = {
    "training_tsv": "ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633",
    "contact_targets_tsv_gz": "bd3cb205af606391aa2153f3c2bbc243c9630796228e12b4a561a2a7da7c7f0f",
    "contact_receipt": "de3973e76e48f0be0c8854fe3f8560c42522ec3e42f90ea4861ce8f9b0ed9027",
    "contact_independent_validation": "8dae292b1dd922ff2af7f9f73bdaa662e4fe3f827f30f633df9d3a3ebd603911",
    "esm2_650m_model_safetensors": "a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0",
}


class SafeStopError(RuntimeError):
    """A recoverable, receipt-bearing disk guard stop."""


def sha256_file(path: Path) -> str:
    return v1.sha256_file(path)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    v1.atomic_json(path, payload)


def atomic_torch_save(path: Path, payload: Mapping[str, Any]) -> None:
    v1.atomic_torch_save(path, payload)


def parent_inner_fold(parent: str, outer_fold: int) -> int:
    require(bool(parent) and outer_fold >= 0, "inner_fold_input_invalid")
    digest = hashlib.sha256(f"PVRIG_V6_INNER|outer={outer_fold}|{parent}".encode()).hexdigest()
    return int(digest, 16) % INNER_FOLD_COUNT


def real_structure_feature_names(fields: Sequence[str]) -> list[str]:
    names = [field for field in fields if field.startswith(STRUCTURE_PREFIXES)]
    require(len(names) == 126, f"real_structure_feature_count_invalid:{len(names)}")
    require(len(names) == len(set(names)), "duplicate_structure_feature_name")
    return names


def selection_key(metrics: Mapping[str, float]) -> tuple[float, float, float, float]:
    return (
        float(metrics["spearman"]),
        float(metrics["parent_centered_spearman"]),
        float(metrics["top20_recall"]),
        -float(metrics["mae"]),
    )


def rounded_median_epoch(epoch_counts: Sequence[int]) -> int:
    require(bool(epoch_counts) and all(int(value) >= 1 for value in epoch_counts), "epoch_counts_invalid")
    median = float(statistics.median([int(value) for value in epoch_counts]))
    return max(1, int(math.floor(median + 0.5)))


class ParentAwareBatchSampler(Sampler[list[int]]):
    """Deterministically packs same-parent chunks while preserving every row once."""

    def __init__(self, parents: Sequence[str], *, batch_size: int, per_parent: int, seed: int) -> None:
        require(batch_size >= per_parent >= 1, "parent_sampler_dimensions_invalid")
        self.parents = [str(value) for value in parents]
        require(self.parents and all(self.parents), "parent_sampler_empty")
        self.batch_size = int(batch_size)
        self.per_parent = int(per_parent)
        self.seed = int(seed)
        self._batches = self._build()

    def _build(self) -> list[list[int]]:
        rng = random.Random(self.seed)
        by_parent: dict[str, list[int]] = defaultdict(list)
        for index, parent in enumerate(self.parents):
            by_parent[parent].append(index)
        chunks: list[list[int]] = []
        for parent in sorted(by_parent):
            values = list(by_parent[parent])
            rng.shuffle(values)
            chunks.extend(values[start : start + self.per_parent] for start in range(0, len(values), self.per_parent))
        rng.shuffle(chunks)
        batches: list[list[int]] = []
        current: list[int] = []
        for chunk in chunks:
            if current and len(current) + len(chunk) > self.batch_size:
                batches.append(current)
                current = []
            current.extend(chunk)
        if current:
            batches.append(current)
        require(sorted(index for batch in batches for index in batch) == list(range(len(self.parents))), "parent_sampler_row_closure_failed")
        return batches

    def __iter__(self) -> Iterator[list[int]]:
        return iter([list(batch) for batch in self._batches])

    def __len__(self) -> int:
        return len(self._batches)


def capture_rng_state() -> dict[str, Any]:
    return {
        "python": random.getstate(),
        "numpy": np.random.get_state(),
        "torch_cpu": torch.get_rng_state(),
        "torch_cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None,
    }


def restore_rng_state(state: Mapping[str, Any]) -> None:
    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.set_rng_state(state["torch_cpu"])
    if torch.cuda.is_available() and state.get("torch_cuda") is not None:
        torch.cuda.set_rng_state_all(state["torch_cuda"])


def validate_contact_receipt(receipt_path: Path, contact_path: Path) -> str:
    v1.require_regular(receipt_path, "contact_receipt")
    v1.require_regular(contact_path, "contact_target")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    require(receipt.get("schema_version") == "pvrig_v6_residue_dual_contact_targets_v1_receipt", "contact_receipt_schema_invalid")
    require(receipt.get("status") == "PASS_DUAL_CONTACT_TARGETS_MATERIALIZED", "contact_receipt_status_invalid")
    output = receipt.get("output") or {}
    require(Path(str(output.get("path"))).name == contact_path.name, "contact_receipt_output_name_mismatch")
    actual = sha256_file(contact_path)
    require(output.get("sha256") == actual, "contact_receipt_output_sha256_mismatch")
    return actual


def validate_implementation_freeze(freeze_path: Path, root: Path) -> dict[str, str]:
    v1.require_regular(freeze_path, "implementation_freeze")
    payload = json.loads(freeze_path.read_text(encoding="utf-8"))
    require(payload.get("schema_version") == "pvrig_v6_residue_v1_1_implementation_freeze", "implementation_freeze_schema_invalid")
    require(payload.get("status") == "IMPLEMENTED_CPU_VALIDATED_NOT_REMOTE_TRAINED", "implementation_freeze_status_invalid")
    hashes = dict(payload.get("implementation_sha256") or {})
    require(bool(hashes), "implementation_hashes_empty")
    for relative, expected in hashes.items():
        path = root / relative
        v1.require_regular(path, f"implementation:{relative}")
        require(sha256_file(path) == expected, f"implementation_sha256_mismatch:{relative}")
    return hashes


def parent_center(values: np.ndarray, parents: Sequence[str]) -> np.ndarray:
    centered = np.asarray(values, dtype=np.float64).copy()
    for parent in sorted(set(parents)):
        indices = np.asarray([index for index, value in enumerate(parents) if value == parent], dtype=int)
        centered[indices] -= float(np.mean(centered[indices]))
    return centered


def evaluation_metrics(target: np.ndarray, prediction: np.ndarray, parents: Sequence[str]) -> dict[str, float]:
    require(target.shape == prediction.shape and target.ndim == 1, "evaluation_metric_shape_invalid")
    budget = max(1, math.ceil(0.20 * len(target)))
    truth = set(np.argsort(-target, kind="mergesort")[:budget].tolist())
    predicted = set(np.argsort(-prediction, kind="mergesort")[:budget].tolist())
    return {
        "spearman": v1.spearman(target, prediction),
        "parent_centered_spearman": v1.spearman(parent_center(target, parents), parent_center(prediction, parents)),
        "top20_recall": len(truth & predicted) / len(truth),
        "mae": float(np.mean(np.abs(target - prediction))),
        "rmse": float(np.sqrt(np.mean((target - prediction) ** 2))),
    }


def crossfit_m2(
    indices: Sequence[int],
    arrays: Mapping[str, Any],
    outer_fold: int,
    alpha: float,
) -> tuple[np.ndarray, dict[int, int]]:
    selected = np.asarray(list(indices), dtype=int)
    require(len(selected) > 0, "crossfit_indices_empty")
    assignments = np.asarray([parent_inner_fold(arrays["parents"][index], outer_fold) for index in selected])
    observed = sorted(set(assignments.tolist()))
    require(len(observed) >= 2, f"crossfit_too_few_observed_inner_folds:{observed}")
    prediction = np.full((len(selected), 3), np.nan, dtype=np.float64)
    counts: dict[int, int] = {}
    for inner_fold in observed:
        held_local = np.where(assignments == inner_fold)[0]
        train_local = np.where(assignments != inner_fold)[0]
        require(len(train_local) >= 2, f"crossfit_training_too_small:{inner_fold}")
        train_global = selected[train_local]
        held_global = selected[held_local]
        state = v1.fit_weighted_ridge(
            arrays["structure"][train_global], arrays["targets"][train_global], arrays["weights"][train_global], alpha,
        )
        prediction[held_local] = v1.predict_ridge(state, arrays["structure"][held_global])
        counts[int(inner_fold)] = len(held_local)
    require(bool(np.all(np.isfinite(prediction))), "crossfit_prediction_nonfinite")
    return prediction, counts


def disk_free_bytes(path: Path) -> int:
    probe = path if path.exists() else path.parent
    return int(shutil.disk_usage(probe).free)


def disk_stage_guard(stage_dir: Path, args: argparse.Namespace, phase: str) -> None:
    free = disk_free_bytes(stage_dir)
    if free < args.safe_stop_free_gb * 1024**3:
        atomic_json(stage_dir / "SAFE_STOP.json", {
            "status": "SAFE_STOP_DISK_BELOW_150GB", "phase": phase, "free_bytes": free,
            "threshold_gb": args.safe_stop_free_gb,
        })
        raise SafeStopError("disk_safe_stop_threshold_reached")


def checkpoint_disk_guard(stage_dir: Path, args: argparse.Namespace, phase: str) -> None:
    free = disk_free_bytes(stage_dir)
    if free < args.checkpoint_min_free_gb * 1024**3:
        atomic_json(stage_dir / "SAFE_STOP.json", {
            "status": "SAFE_STOP_CHECKPOINT_GUARD_BELOW_180GB", "phase": phase, "free_bytes": free,
            "threshold_gb": args.checkpoint_min_free_gb,
        })
        raise SafeStopError("checkpoint_disk_guard_threshold_reached")


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(payload), sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def reconcile_metrics_jsonl(path: Path, start_epoch: int) -> None:
    """Keep exactly the metrics committed by the last durable checkpoint."""
    require(start_epoch >= 0, "metrics_start_epoch_invalid")
    if not path.exists():
        require(start_epoch == 0, "checkpoint_exists_without_metrics_jsonl")
        return
    require(path.is_file() and not path.is_symlink(), "metrics_jsonl_invalid")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    committed = [record for record in records if int(record["epoch"]) < start_epoch]
    require([int(record["epoch"]) for record in committed] == list(range(start_epoch)), "metrics_checkpoint_epoch_closure_failed")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.reconcile.tmp")
    temporary.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in committed), encoding="utf-8")
    os.replace(temporary, path)


def seed_everything(seed: int) -> None:
    v1.seed_everything(seed)


def load_backbone(args: argparse.Namespace) -> tuple[nn.Module, Any, int]:
    if args.backbone_kind == "tiny":
        tokenizer = v1.TinyTokenizer()
        backbone = v1.TinyBackbone(len(tokenizer), args.tiny_hidden_size)
        for parameter in backbone.parameters():
            parameter.requires_grad_(False)
        return backbone, tokenizer, args.tiny_hidden_size
    require(args.model_path is not None and args.model_path.is_dir() and not args.model_path.is_symlink(), "local_model_directory_required")
    try:
        from transformers import AutoModel, AutoTokenizer
    except ImportError as error:
        raise RuntimeError("transformers_required") from error
    tokenizer = AutoTokenizer.from_pretrained(str(args.model_path), local_files_only=True, trust_remote_code=args.trust_remote_code)
    backbone = AutoModel.from_pretrained(str(args.model_path), local_files_only=True, trust_remote_code=args.trust_remote_code)
    hidden = getattr(backbone.config, "hidden_size", None) or getattr(backbone.config, "d_model", None) or getattr(backbone.config, "embed_dim", None)
    require(hidden is not None, "backbone_hidden_size_missing")
    for parameter in backbone.parameters():
        parameter.requires_grad_(False)
    if args.backbone_mode == "lora":
        try:
            from peft import LoraConfig, TaskType, get_peft_model
        except ImportError as error:
            raise RuntimeError("peft_required_for_lora") from error
        targets = [value.strip() for value in args.lora_target_modules.split(",") if value.strip()]
        require(bool(targets), "lora_target_modules_empty")
        backbone = get_peft_model(backbone, LoraConfig(
            r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=args.lora_dropout,
            target_modules=targets, bias="none", task_type=TaskType.FEATURE_EXTRACTION,
        ))
        if args.gradient_checkpointing:
            method = getattr(backbone, "gradient_checkpointing_enable", None)
            require(callable(method), "backbone_gradient_checkpointing_unsupported")
            method()
            enable_inputs = getattr(backbone, "enable_input_require_grads", None)
            if callable(enable_inputs):
                enable_inputs()
    elif args.gradient_checkpointing:
        # Frozen backbones run under no_grad, so gradient checkpointing would only add overhead.
        raise RuntimeError("gradient_checkpointing_requires_lora_mode")
    return backbone, tokenizer, int(hidden)


def build_model(args: argparse.Namespace, device: torch.device) -> tuple[ResidueSurrogate, Any, ResidueHeadConfig]:
    backbone, tokenizer, hidden = load_backbone(args)
    head_config = ResidueHeadConfig(
        backbone_hidden_size=hidden, structure_dim=args.structure_dim,
        fusion_dim=args.fusion_dim, dropout=args.dropout,
        residual_scale=args.residual_scale,
        detach_contact_pooling=not args.end_to_end_contact_pooling,
    )
    model = ResidueSurrogate(backbone, DualContactResidualHead(head_config), backbone_mode=args.backbone_mode)
    model.to(device)
    return model, tokenizer, head_config


def optimizer_and_scheduler(
    model: ResidueSurrogate,
    args: argparse.Namespace,
    updates_per_epoch: int,
    epochs: int,
) -> tuple[AdamW, LambdaLR]:
    head = [parameter for name, parameter in model.named_parameters() if name.startswith("head.") and parameter.requires_grad]
    adapter = [parameter for name, parameter in model.named_parameters() if name.startswith("backbone.") and parameter.requires_grad]
    require(bool(head), "head_parameters_empty")
    groups: list[dict[str, Any]] = [{"params": head, "lr": args.head_learning_rate, "group_name": "head"}]
    if args.backbone_mode == "lora":
        require(bool(adapter), "lora_parameters_empty")
        groups.append({"params": adapter, "lr": args.lora_learning_rate, "group_name": "lora"})
    else:
        require(not adapter, "frozen_mode_has_trainable_backbone_parameters")
    optimizer = AdamW(groups, weight_decay=args.weight_decay)
    total = max(1, updates_per_epoch * epochs)
    warmup = min(args.warmup_steps, total - 1)

    def scale(step: int) -> float:
        if step < warmup:
            return (step + 1) / max(1, warmup)
        progress = (step - warmup) / max(1, total - warmup)
        return 0.5 * (1.0 + math.cos(math.pi * min(1.0, progress)))

    return optimizer, LambdaLR(optimizer, scale)


def training_loader(
    rows: Sequence[v1.TrainingRow], indices: Sequence[int], tokenizer: Any,
    bases: Mapping[int, np.ndarray], args: argparse.Namespace, seed: int,
) -> DataLoader[Any]:
    local_parents = [rows[index].parent for index in indices]
    sampler = ParentAwareBatchSampler(local_parents, batch_size=args.batch_size, per_parent=args.per_parent_batch, seed=seed)
    return DataLoader(
        v1.IndexedDataset(indices), batch_sampler=sampler, num_workers=0,
        collate_fn=v1.Collator(rows, tokenizer, bases),
    )


def evaluation_loader(
    rows: Sequence[v1.TrainingRow], indices: Sequence[int], tokenizer: Any,
    bases: Mapping[int, np.ndarray], args: argparse.Namespace,
) -> DataLoader[Any]:
    return DataLoader(
        v1.IndexedDataset(indices), batch_size=args.batch_size, shuffle=False,
        num_workers=0, collate_fn=v1.Collator(rows, tokenizer, bases),
    )


def run_epoch(
    model: ResidueSurrogate,
    loader: DataLoader[Any],
    device: torch.device,
    loss_config: ResidueLossConfig,
    positive_weights: Tensor,
    args: argparse.Namespace,
    optimizer: AdamW | None,
    scheduler: LambdaLR | None,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    training = optimizer is not None
    model.train(training)
    if model.backbone_mode == "frozen":
        model.backbone.eval()
    if training:
        optimizer.zero_grad(set_to_none=True)
    totals: dict[str, float] = {}
    targets, predictions, parents = [], [], []
    records: list[dict[str, Any]] = []
    batch_count = 0
    for batch_index, source in enumerate(loader):
        batch = v1.move(source, device)
        autocast_enabled = args.precision == "bf16" and device.type == "cuda"
        with torch.set_grad_enabled(training), torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=autocast_enabled):
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
            (loss / args.gradient_accumulation).backward()
            should_step = (batch_index + 1) % args.gradient_accumulation == 0 or batch_index + 1 == len(loader)
            if should_step:
                torch.nn.utils.clip_grad_norm_([parameter for parameter in model.parameters() if parameter.requires_grad], args.gradient_clip)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                if scheduler is not None:
                    scheduler.step()
        for name, value in parts.items():
            totals[name] = totals.get(name, 0.0) + float(value.detach().cpu())
        batch_count += 1
        target = batch["targets"][:, 2].detach().float().cpu().numpy()
        prediction = output["prediction"][:, 2].detach().float().cpu().numpy()
        base = batch["m2_base"][:, 2].detach().float().cpu().numpy()
        targets.append(target)
        predictions.append(prediction)
        parents.extend(batch["parents"])
        for index, candidate in enumerate(batch["candidate_ids"]):
            records.append({
                "candidate_id": candidate,
                "parent_framework_cluster": batch["parents"][index],
                "R_dual_min": float(target[index]),
                "m2_prediction": float(base[index]),
                "residue_prediction": float(prediction[index]),
            })
    result = {f"loss_{name}": value / max(1, batch_count) for name, value in totals.items()}
    result.update(evaluation_metrics(np.concatenate(targets), np.concatenate(predictions), parents))
    return result, records


def stage_binding_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def train_selection_stage(
    args: argparse.Namespace,
    rows: Sequence[v1.TrainingRow],
    train_indices: Sequence[int],
    validation_indices: Sequence[int],
    train_bases: Mapping[int, np.ndarray],
    validation_bases: Mapping[int, np.ndarray],
    stage_dir: Path,
    seed: int,
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    binding_hash = stage_binding_hash(binding)
    seed_everything(seed)
    device = torch.device(args.device)
    model, tokenizer, _head_config = build_model(args, device)
    loss_config = ResidueLossConfig(
        dual_weight=args.dual_weight, receptor_weight=args.receptor_weight,
        contact_weight=args.contact_weight, ranking_weight=args.ranking_weight,
        residual_weight=args.residual_weight, huber_delta=args.huber_delta,
        ranking_minimum_delta=args.ranking_minimum_delta,
        ranking_temperature=args.ranking_temperature,
    )
    positive_weights = v1.contact_positive_weights(rows, train_indices)
    train_loader = training_loader(rows, train_indices, tokenizer, train_bases, args, seed)
    validation_loader = evaluation_loader(rows, validation_indices, tokenizer, validation_bases, args)
    updates = math.ceil(len(train_loader) / args.gradient_accumulation)
    optimizer, scheduler = optimizer_and_scheduler(model, args, updates, args.max_epochs)
    start_epoch, best_epoch = 0, -1
    best_key: tuple[float, float, float, float] | None = None
    last_path = stage_dir / "last.pt"
    if args.resume and last_path.is_file():
        checkpoint = torch.load(last_path, map_location="cpu", weights_only=False)
        require(checkpoint["binding_hash"] == binding_hash, "resume_binding_hash_mismatch")
        load_trainable_checkpoint_state(model, checkpoint["trainable_state"])
        optimizer.load_state_dict(checkpoint["optimizer"])
        scheduler.load_state_dict(checkpoint["scheduler"])
        restore_rng_state(checkpoint["rng_state"])
        start_epoch = int(checkpoint["epoch"]) + 1
        best_epoch = int(checkpoint["best_epoch"])
        best_key = tuple(float(value) for value in checkpoint["best_key"])
    metrics_path = stage_dir / "metrics.jsonl"
    reconcile_metrics_jsonl(metrics_path, start_epoch)
    for epoch in range(start_epoch, args.max_epochs):
        disk_stage_guard(stage_dir, args, f"selection_epoch_{epoch}_precompute")
        train_metrics, _ = run_epoch(model, train_loader, device, loss_config, positive_weights, args, optimizer, scheduler)
        validation_metrics, _ = run_epoch(model, validation_loader, device, loss_config, positive_weights, args, None, None)
        key = selection_key(validation_metrics)
        if best_key is None or key > best_key:
            best_key, best_epoch = key, epoch
        record = {"epoch": epoch, "train": train_metrics, "validation": validation_metrics, "selection_key": list(key)}
        append_jsonl(metrics_path, record)
        checkpoint_disk_guard(stage_dir, args, f"selection_epoch_{epoch}_checkpoint")
        atomic_torch_save(last_path, {
            "schema_version": f"{SCHEMA_VERSION}_selection_checkpoint",
            "binding_hash": binding_hash,
            "epoch": epoch,
            "best_epoch": best_epoch,
            "best_key": list(best_key),
            "trainable_state": trainable_checkpoint_state(model),
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict(),
            "rng_state": capture_rng_state(),
        })
    require(best_epoch >= 0 and best_key is not None, "selection_stage_has_no_epoch")
    result = {
        "status": "PASS_INNER_SELECTION_COMPLETE",
        "best_epoch_zero_based": best_epoch,
        "selected_epoch_count": best_epoch + 1,
        "best_key": list(best_key),
        "binding_hash": binding_hash,
    }
    atomic_json(stage_dir / "RESULT.json", result)
    return result


def train_final_stage(
    args: argparse.Namespace,
    rows: Sequence[v1.TrainingRow],
    train_indices: Sequence[int],
    train_bases: Mapping[int, np.ndarray],
    stage_dir: Path,
    seed: int,
    epochs: int,
    binding: Mapping[str, Any],
) -> tuple[ResidueSurrogate, Any, ResidueHeadConfig, ResidueLossConfig]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    binding_hash = stage_binding_hash(binding)
    seed_everything(seed)
    device = torch.device(args.device)
    model, tokenizer, head_config = build_model(args, device)
    loss_config = ResidueLossConfig(
        dual_weight=args.dual_weight, receptor_weight=args.receptor_weight,
        contact_weight=args.contact_weight, ranking_weight=args.ranking_weight,
        residual_weight=args.residual_weight, huber_delta=args.huber_delta,
        ranking_minimum_delta=args.ranking_minimum_delta,
        ranking_temperature=args.ranking_temperature,
    )
    positive_weights = v1.contact_positive_weights(rows, train_indices)
    train_loader = training_loader(rows, train_indices, tokenizer, train_bases, args, seed)
    updates = math.ceil(len(train_loader) / args.gradient_accumulation)
    optimizer, scheduler = optimizer_and_scheduler(model, args, updates, epochs)
    start_epoch = 0
    last_path = stage_dir / "last.pt"
    if args.resume and last_path.is_file():
        checkpoint = torch.load(last_path, map_location="cpu", weights_only=False)
        require(checkpoint["binding_hash"] == binding_hash, "final_resume_binding_hash_mismatch")
        load_trainable_checkpoint_state(model, checkpoint["trainable_state"])
        optimizer.load_state_dict(checkpoint["optimizer"])
        scheduler.load_state_dict(checkpoint["scheduler"])
        restore_rng_state(checkpoint["rng_state"])
        start_epoch = int(checkpoint["epoch"]) + 1
    metrics_path = stage_dir / "metrics.jsonl"
    reconcile_metrics_jsonl(metrics_path, start_epoch)
    for epoch in range(start_epoch, epochs):
        disk_stage_guard(stage_dir, args, f"final_epoch_{epoch}_precompute")
        train_metrics, _ = run_epoch(model, train_loader, device, loss_config, positive_weights, args, optimizer, scheduler)
        append_jsonl(metrics_path, {"epoch": epoch, "train": train_metrics})
        checkpoint_disk_guard(stage_dir, args, f"final_epoch_{epoch}_checkpoint")
        atomic_torch_save(last_path, {
            "schema_version": f"{SCHEMA_VERSION}_final_checkpoint",
            "binding_hash": binding_hash,
            "epoch": epoch,
            "trainable_state": trainable_checkpoint_state(model),
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict(),
            "rng_state": capture_rng_state(),
        })
    return model, tokenizer, head_config, loss_config


def train(args: argparse.Namespace) -> dict[str, Any]:
    require(args.precision in {"fp32", "bf16"}, "precision_invalid")
    require(args.outer_fold in range(5), "outer_fold_invalid")
    require(args.gradient_accumulation >= 1 and args.max_epochs >= 1, "training_dimensions_invalid")
    if args.output_dir.exists():
        require(args.resume and args.output_dir.is_dir() and not args.output_dir.is_symlink(), "existing_output_requires_resume")
        terminal = args.output_dir / "RESULT.json"
        if terminal.is_file():
            return json.loads(terminal.read_text(encoding="utf-8"))
    else:
        args.output_dir.mkdir(parents=True, exist_ok=False)

    training_hash = sha256_file(args.training_tsv)
    contact_hash = validate_contact_receipt(args.contact_receipt, args.contact_tsv_gz)
    if not args.smoke_mode:
        require(training_hash == FROZEN_EXTERNAL_SHA256["training_tsv"], "frozen_training_sha256_mismatch")
        require(contact_hash == FROZEN_EXTERNAL_SHA256["contact_targets_tsv_gz"], "frozen_contact_sha256_mismatch")
        require(sha256_file(args.contact_receipt) == FROZEN_EXTERNAL_SHA256["contact_receipt"], "frozen_contact_receipt_sha256_mismatch")
        require(args.contact_validation is not None, "contact_independent_validation_required")
        v1.require_regular(args.contact_validation, "contact_independent_validation")
        require(sha256_file(args.contact_validation) == FROZEN_EXTERNAL_SHA256["contact_independent_validation"], "contact_independent_validation_sha256_mismatch")
        if args.expected_training_sha256 is not None:
            require(args.expected_training_sha256 == training_hash, "training_sha256_mismatch")
        if args.expected_contact_sha256 is not None:
            require(args.expected_contact_sha256 == contact_hash, "contact_sha256_mismatch")
        require(args.implementation_freeze is not None, "implementation_freeze_required")
        implementation_hashes = validate_implementation_freeze(args.implementation_freeze, Path(__file__).parents[1])
        require(args.model_identity_file is not None and args.expected_model_sha256, "model_identity_binding_required")
        v1.require_regular(args.model_identity_file, "model_identity_file")
        require(args.model_path is not None and args.model_identity_file.resolve().is_relative_to(args.model_path.resolve()), "model_identity_file_outside_model_path")
        actual_model_sha = sha256_file(args.model_identity_file)
        require(actual_model_sha == FROZEN_EXTERNAL_SHA256["esm2_650m_model_safetensors"], "frozen_model_identity_sha256_mismatch")
        require(actual_model_sha == args.expected_model_sha256, "model_identity_sha256_mismatch")
    else:
        implementation_hashes = {}

    rows, feature_names, data_audit = v1.read_training_table(
        args.training_tsv, args.contact_tsv_gz,
        structure_prefixes=args.structure_prefix,
        structure_dim=args.structure_dim,
    )
    if not args.smoke_mode:
        with args.training_tsv.open(encoding="utf-8-sig") as handle:
            fields = next(csv.reader(handle, delimiter="\t"))
        require(feature_names == real_structure_feature_names(fields), "real_structure_feature_schema_mismatch")
        require(args.structure_dim == 126 and tuple(args.structure_prefix) == STRUCTURE_PREFIXES, "production_structure_schema_not_frozen")
    arrays = v1.arrays_from_rows(rows)
    outer_test = [index for index, row in enumerate(rows) if row.outer_fold == args.outer_fold]
    outer_test_set = set(outer_test)
    outer_train = [index for index in range(len(rows)) if index not in outer_test_set]
    require(outer_train and outer_test, "outer_split_empty")
    require({rows[index].parent for index in outer_train}.isdisjoint(rows[index].parent for index in outer_test), "outer_parent_leakage")
    observed_inner = sorted({parent_inner_fold(rows[index].parent, args.outer_fold) for index in outer_train})
    require(len(observed_inner) >= 2, "too_few_observed_inner_folds")

    run_binding = {
        "schema_version": SCHEMA_VERSION,
        "training_sha256": training_hash,
        "contact_sha256": contact_hash,
        "contact_receipt_sha256": sha256_file(args.contact_receipt),
        "contact_independent_validation_sha256": (
            sha256_file(args.contact_validation) if args.contact_validation is not None else "smoke_not_applicable"
        ),
        "frozen_external_sha256": dict(FROZEN_EXTERNAL_SHA256),
        "implementation_hashes": implementation_hashes,
        "outer_fold": args.outer_fold,
        "observed_inner_folds": observed_inner,
        "seed": args.seed,
        "model_path": str(args.model_path) if args.model_path else "tiny",
        "model_identity_sha256": args.expected_model_sha256 if not args.smoke_mode else "tiny_synthetic",
        "backbone_mode": args.backbone_mode,
        "feature_names_sha256": hashlib.sha256("\n".join(feature_names).encode()).hexdigest(),
    }
    binding_hash = stage_binding_hash(run_binding)
    preflight_path = args.output_dir / "PREFLIGHT.json"
    if preflight_path.is_file():
        require(json.loads(preflight_path.read_text())["binding_hash"] == binding_hash, "run_preflight_binding_mismatch")
    else:
        atomic_json(preflight_path, {
            "status": "PASS_PREFLIGHT_TRAINING_NOT_COMPLETE",
            "binding_hash": binding_hash,
            "binding": run_binding,
            "data_audit": data_audit,
            "counts": {"outer_train": len(outer_train), "outer_test": len(outer_test)},
            "claim_boundary": CLAIM_BOUNDARY,
        })

    selected_epoch_counts: list[int] = []
    inner_results: list[dict[str, Any]] = []
    for inner_fold in observed_inner:
        inner_validation = [index for index in outer_train if parent_inner_fold(rows[index].parent, args.outer_fold) == inner_fold]
        inner_train = [index for index in outer_train if parent_inner_fold(rows[index].parent, args.outer_fold) != inner_fold]
        require(inner_train and inner_validation, f"inner_split_empty:{inner_fold}")
        require({rows[index].parent for index in inner_train}.isdisjoint(rows[index].parent for index in inner_validation), f"inner_parent_leakage:{inner_fold}")
        crossfit, crossfit_counts = crossfit_m2(inner_train, arrays, args.outer_fold, args.ridge_alpha)
        train_bases = {index: crossfit[position] for position, index in enumerate(inner_train)}
        m2_state = v1.fit_weighted_ridge(
            arrays["structure"][inner_train], arrays["targets"][inner_train], arrays["weights"][inner_train], args.ridge_alpha,
        )
        validation_prediction = v1.predict_ridge(m2_state, arrays["structure"][inner_validation])
        validation_bases = {index: validation_prediction[position] for position, index in enumerate(inner_validation)}
        stage_binding = {
            **run_binding, "stage": "inner_selection", "inner_fold": inner_fold,
            "inner_train_candidates_sha256": hashlib.sha256("\n".join(sorted(rows[index].candidate_id for index in inner_train)).encode()).hexdigest(),
            "inner_validation_candidates_sha256": hashlib.sha256("\n".join(sorted(rows[index].candidate_id for index in inner_validation)).encode()).hexdigest(),
            "crossfit_counts": crossfit_counts,
        }
        result = train_selection_stage(
            args, rows, inner_train, inner_validation, train_bases, validation_bases,
            args.output_dir / f"inner_fold_{inner_fold}",
            args.seed + args.outer_fold * 10000 + inner_fold * 100,
            stage_binding,
        )
        selected_epoch_counts.append(int(result["selected_epoch_count"]))
        inner_results.append({"inner_fold": inner_fold, **result})

    final_epochs = rounded_median_epoch(selected_epoch_counts)
    final_crossfit, final_crossfit_counts = crossfit_m2(outer_train, arrays, args.outer_fold, args.ridge_alpha)
    final_train_bases = {index: final_crossfit[position] for position, index in enumerate(outer_train)}
    final_binding = {
        **run_binding, "stage": "final_refit", "final_epochs": final_epochs,
        "selected_epoch_counts": selected_epoch_counts,
        "crossfit_counts": final_crossfit_counts,
    }
    model, tokenizer, head_config, loss_config = train_final_stage(
        args, rows, outer_train, final_train_bases, args.output_dir / "final_refit",
        args.seed + args.outer_fold * 10000 + 9000, final_epochs, final_binding,
    )

    # The outer fold is first tokenized/evaluated only after all inner selection and final refit.
    # A durable one-way seal prevents automatic re-evaluation after an interrupted outer pass.
    outer_seal_path = args.output_dir / "OUTER_EVALUATION_SEAL.json"
    if outer_seal_path.exists():
        seal = json.loads(outer_seal_path.read_text(encoding="utf-8"))
        raise RuntimeError(f"outer_evaluation_already_started_without_terminal:{seal.get('status')}")
    atomic_json(outer_seal_path, {
        "schema_version": f"{SCHEMA_VERSION}_outer_evaluation_seal",
        "status": "SEALED_STARTED_NOT_REPEATABLE",
        "binding_hash": binding_hash,
        "outer_fold": args.outer_fold,
        "claim_boundary": CLAIM_BOUNDARY,
    })
    outer_m2_state = v1.fit_weighted_ridge(
        arrays["structure"][outer_train], arrays["targets"][outer_train], arrays["weights"][outer_train], args.ridge_alpha,
    )
    outer_m2_prediction = v1.predict_ridge(outer_m2_state, arrays["structure"][outer_test])
    outer_bases = {index: outer_m2_prediction[position] for position, index in enumerate(outer_test)}
    outer_loader = evaluation_loader(rows, outer_test, tokenizer, outer_bases, args)
    positive_weights = v1.contact_positive_weights(rows, outer_train)
    outer_metrics, records = run_epoch(
        model, outer_loader, torch.device(args.device), loss_config, positive_weights, args, None, None,
    )
    target = np.asarray([rows[index].targets[2] for index in outer_test])
    parents = [rows[index].parent for index in outer_test]
    m2_metrics = evaluation_metrics(target, outer_m2_prediction[:, 2], parents)

    contract = model_contract(head_config, loss_config, args.backbone_mode)
    contract.update({
        "schema_version": SCHEMA_VERSION,
        "binding": run_binding,
        "binding_hash": binding_hash,
        "inner_protocol": "PVRIG_V6_INNER_whole_parent_5_fold",
        "observed_inner_folds": observed_inner,
        "epoch_selection_lexicographic": ["spearman", "parent_centered_spearman", "top20_recall", "negative_mae"],
        "selected_epoch_counts": selected_epoch_counts,
        "final_epoch_count_rounded_median": final_epochs,
        "outer_evaluation_count": 1,
        "feature_names": feature_names,
    })
    atomic_json(args.output_dir / "contract.json", contract)
    np.savez_compressed(
        args.output_dir / "m2_outer_train_fit.npz",
        x_mean=outer_m2_state.x_mean, x_scale=outer_m2_state.x_scale,
        y_mean=outer_m2_state.y_mean, coefficient=outer_m2_state.coefficient,
        alpha=np.asarray([outer_m2_state.alpha]), feature_names=np.asarray(feature_names),
    )
    atomic_torch_save(args.output_dir / "adapter_head_final.pt", {
        "schema_version": f"{SCHEMA_VERSION}_adapter_head_final",
        "binding_hash": binding_hash,
        "trainable_state": trainable_checkpoint_state(model),
        "contract_sha256": sha256_file(args.output_dir / "contract.json"),
        "claim_boundary": CLAIM_BOUNDARY,
    })
    prediction_path = args.output_dir / "outer_test_predictions.tsv"
    with prediction_path.open("w", encoding="utf-8", newline="") as handle:
        fields = ["candidate_id", "parent_framework_cluster", "outer_fold", "R_dual_min", "m2_prediction", "residue_prediction"]
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for record in sorted(records, key=lambda item: item["candidate_id"]):
            writer.writerow({**record, "outer_fold": args.outer_fold})
    result = {
        "schema_version": f"{SCHEMA_VERSION}_result",
        "status": "PASS_OUTER_FOLD_COMPLETE",
        "outer_fold": args.outer_fold,
        "outer_evaluation_count": 1,
        "inner_results": inner_results,
        "selected_epoch_counts": selected_epoch_counts,
        "final_epoch_count": final_epochs,
        "m2_outer_test": m2_metrics,
        "residue_outer_test": outer_metrics,
        "binding_hash": binding_hash,
        "artifacts": {
            name: sha256_file(args.output_dir / name)
            for name in ("contract.json", "m2_outer_train_fit.npz", "adapter_head_final.pt", "outer_test_predictions.tsv")
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_json(args.output_dir / "RESULT.json", result)
    atomic_json(outer_seal_path, {
        "schema_version": f"{SCHEMA_VERSION}_outer_evaluation_seal",
        "status": "SEALED_COMPLETE_ONE_EVALUATION",
        "binding_hash": binding_hash,
        "outer_fold": args.outer_fold,
        "result_sha256": sha256_file(args.output_dir / "RESULT.json"),
        "claim_boundary": CLAIM_BOUNDARY,
    })
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--training-tsv", type=Path, required=True)
    value.add_argument("--contact-tsv-gz", type=Path, required=True)
    value.add_argument("--contact-receipt", type=Path, required=True)
    value.add_argument("--contact-validation", type=Path)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--implementation-freeze", type=Path)
    value.add_argument("--expected-training-sha256")
    value.add_argument("--expected-contact-sha256")
    value.add_argument("--smoke-mode", action="store_true")
    value.add_argument("--resume", action="store_true")
    value.add_argument("--structure-prefix", action="append", default=[])
    value.add_argument("--structure-dim", type=int, default=126)
    value.add_argument("--outer-fold", type=int, required=True)
    value.add_argument("--ridge-alpha", type=float, default=10.0)
    value.add_argument("--backbone-kind", choices=("tiny", "hf"), default="hf")
    value.add_argument("--backbone-mode", choices=("frozen", "lora"), default="frozen")
    value.add_argument("--model-path", type=Path)
    value.add_argument("--model-identity-file", type=Path)
    value.add_argument("--expected-model-sha256")
    value.add_argument("--trust-remote-code", action="store_true")
    value.add_argument("--gradient-checkpointing", action="store_true")
    value.add_argument("--lora-r", type=int, default=8)
    value.add_argument("--lora-alpha", type=int, default=16)
    value.add_argument("--lora-dropout", type=float, default=0.05)
    value.add_argument("--lora-target-modules", default="query,key,value")
    value.add_argument("--tiny-hidden-size", type=int, default=16)
    value.add_argument("--fusion-dim", type=int, default=128)
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
    value.add_argument("--per-parent-batch", type=int, default=2)
    value.add_argument("--gradient-accumulation", type=int, default=2)
    value.add_argument("--head-learning-rate", type=float, default=2e-4)
    value.add_argument("--lora-learning-rate", type=float, default=2e-5)
    value.add_argument("--weight-decay", type=float, default=0.01)
    value.add_argument("--warmup-steps", type=int, default=10)
    value.add_argument("--gradient-clip", type=float, default=1.0)
    value.add_argument("--precision", choices=("fp32", "bf16"), default="bf16")
    value.add_argument("--seed", type=int, default=43)
    value.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    value.add_argument("--safe-stop-free-gb", type=float, default=150.0)
    value.add_argument("--checkpoint-min-free-gb", type=float, default=180.0)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not args.structure_prefix:
        args.structure_prefix = list(STRUCTURE_PREFIXES)
    result = train(args)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
