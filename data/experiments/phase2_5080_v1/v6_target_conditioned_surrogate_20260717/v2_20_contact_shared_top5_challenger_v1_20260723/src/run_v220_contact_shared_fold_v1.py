#!/usr/bin/env python3
"""Run one paired V2.20 lane-E outer fold (C0 or C1).

The runner reuses the frozen V2.13 scalar data, graph, target, backbone and
evaluator implementation.  C0 and C1 share this file, the serialized seed-43
initial state, optimizer groups and deterministic scalar batch order.  Their
only causal difference is whether the preregistered calibrated contact weights
are applied (C1) or multiplied by zero (C0).

This file contains no autorun behavior.  Import tests use the dependency-
injected ``run_fold_core``; the CLI prepares production inputs but is not
invoked by this implementation change.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import torch
from torch import Tensor, nn


SCHEMA_VERSION = "pvrig.v220.contact_shared_fold_runner.v1"
LANE = "E_DECOUPLED_CONTACT"
ARMS = ("C0", "C1")
SEED = 43
PREDICTION_NAME = "fold_predictions.tsv"
CHECKPOINT_NAME = "fold_checkpoint.pt"
HISTORY_NAME = "epoch_history.json"
RESULT_NAME = "RESULT.json"
CALIBRATION_NAME = "CONTACT_WEIGHT_CALIBRATION.json"
RUNNING_NAME = "RUNNING.json"
FIXED_LAMBDA_GRID = (0.00015625, 0.0003125, 0.000625, 0.00125, 0.0025)

PRODUCTION_HYPERPARAMETERS = {
    "epochs": 8,
    "batch_size": 8,
    "eval_batch_size": 16,
    "gradient_accumulation": 4,
    "precision": "bf16",
    "learning_rate": 1e-4,
    "weight_decay": 0.02,
    "gradient_clip": 1.0,
    "graph_hidden_dim": 128,
    "dropout": 0.25,
    "receptor_weight": 1.0,
    "dual_weight": 0.5,
    "huber_beta": 0.03,
    "softmin_tau": 0.02,
    "top_weight_strength": 3.0,
    "top_weight_center": 0.85,
    "top_weight_scale": 0.05,
}

CLAIM_BOUNDARY = (
    "Whole-parent OOF approximation of independent dual-receptor computational "
    "Docking geometry using sequence, label-free VHH graph, fixed public PVRIG "
    "graphs and outer-fit-only residue-contact weak supervision; not binding, "
    "affinity, experimental blocking, Docking Gold or submission evidence."
)


class V220FoldError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise V220FoldError(message)


def _load_module(path: Path, name: str) -> Any:
    require(path.is_file() and not path.is_symlink(), f"module_invalid:{path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"module_spec:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sibling_module(filename: str, name: str) -> Any:
    return _load_module(Path(__file__).resolve().parent / filename, name)


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_torch_save(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    try:
        torch.save(payload, temporary)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@dataclass(frozen=True)
class FoldConfig:
    arm: str
    fold_id: int
    output_dir: Path
    initial_state_path: Path
    initial_state_receipt_path: Path
    expected_initial_state_sha256: str
    expected_initial_state_receipt_sha256: str
    device: str = "cuda:0"
    seed: int = SEED
    epochs: int = 8
    batch_size: int = 8
    eval_batch_size: int = 16
    gradient_accumulation: int = 4
    precision: str = "bf16"
    learning_rate: float = 1e-4
    weight_decay: float = 0.02
    gradient_clip: float = 1.0
    graph_hidden_dim: int = 128
    dropout: float = 0.25
    receptor_weight: float = 1.0
    dual_weight: float = 0.5
    huber_beta: float = 0.03
    softmin_tau: float = 0.02
    top_weight_strength: float = 3.0
    top_weight_center: float = 0.85
    top_weight_scale: float = 0.05
    tiny_e2e: bool = False

    def validate(self) -> None:
        require(self.arm in ARMS, f"arm_invalid:{self.arm}")
        require(self.fold_id >= 0, "fold_id_invalid")
        require(self.seed == SEED, "seed_must_equal_43")
        require(self.epochs > 0 and self.batch_size > 0 and self.eval_batch_size > 0, "count_invalid")
        require(self.gradient_accumulation > 0, "gradient_accumulation_invalid")
        require(self.precision in {"fp32", "bf16"}, "precision_invalid")
        require(self.learning_rate > 0 and self.weight_decay >= 0, "optimizer_invalid")
        require(self.gradient_clip > 0, "gradient_clip_invalid")
        if not self.tiny_e2e:
            observed = {
                "epochs": self.epochs,
                "batch_size": self.batch_size,
                "eval_batch_size": self.eval_batch_size,
                "gradient_accumulation": self.gradient_accumulation,
                "precision": self.precision,
                "learning_rate": self.learning_rate,
                "weight_decay": self.weight_decay,
                "gradient_clip": self.gradient_clip,
                "graph_hidden_dim": self.graph_hidden_dim,
                "dropout": self.dropout,
                "receptor_weight": self.receptor_weight,
                "dual_weight": self.dual_weight,
                "huber_beta": self.huber_beta,
                "softmin_tau": self.softmin_tau,
                "top_weight_strength": self.top_weight_strength,
                "top_weight_center": self.top_weight_center,
                "top_weight_scale": self.top_weight_scale,
            }
            expected = {
                key: PRODUCTION_HYPERPARAMETERS[key]
                for key in observed
            }
            require(observed == expected, f"production_hyperparameter_drift:{observed}")
            require(self.precision == "bf16", "production_precision_must_be_bf16")


@dataclass
class FoldInputs:
    base: Any
    trainer: Any
    model: nn.Module
    tokenizer: Any
    rows: Sequence[Any]
    split: Any
    graph_store: Any
    target_graphs: Mapping[str, Mapping[str, Tensor]]
    teacher_store: Any
    model_identity: str
    input_bindings: Mapping[str, Any] | None = None


def _batch_order(
    base: Any, indices: Sequence[int], collator: Any, batch_size: int, seed: int
) -> list[tuple[list[int], Mapping[str, Tensor]]]:
    return list(base.iter_batches(indices, collator, batch_size, shuffle_seed=seed))


def batch_order_sha256(rows: Sequence[Any], batches: Sequence[tuple[Sequence[int], Any]]) -> str:
    order = [[rows[index].candidate_id for index in indices] for indices, _ in batches]
    return _sha256_json(order)


def epoch_batch_order_hashes(
    base: Any,
    rows: Sequence[Any],
    train_indices: Sequence[int],
    collator: Any,
    *,
    epochs: int,
    batch_size: int,
    seed: int,
) -> list[str]:
    return [
        batch_order_sha256(
            rows,
            _batch_order(base, train_indices, collator, batch_size, seed + epoch),
        )
        for epoch in range(epochs)
    ]


def _contact_eligible(batch: Mapping[str, Any]) -> bool:
    keys = (
        "marginal_mask",
        "pair_mask_8x6b",
        "pair_mask_9e6y",
    )
    return any(
        isinstance(batch.get(key), Tensor) and bool(batch[key].any()) for key in keys
    )


class CalibrationTrainerAdapter:
    def __init__(self, base: Any, trainer: Any, scalar_loss: Any) -> None:
        self.base = base
        self.trainer = trainer
        self.scalar_loss = scalar_loss

    def shared_parameters(self, model: nn.Module):
        return self.trainer.named_parameter_roles(model)["shared_encoder"]

    def calibration_losses(
        self,
        model: nn.Module,
        batch: Mapping[str, Any],
        target_graphs: Any,
        device: Any,
        precision: str,
    ):
        device_object = torch.device(device)
        batch_device = self.base.move(batch, device_object)
        targets_device = self.base.move(target_graphs, device_object)
        with torch.autocast(
            device_type=device_object.type,
            dtype=torch.bfloat16,
            enabled=precision == "bf16",
        ):
            output = self.trainer.forward_lane(model, LANE, batch_device, targets_device)
            calibration_config = self.trainer.OrthoLossConfig(
                receptor_weight=self.scalar_loss.receptor_weight,
                dual_weight=self.scalar_loss.dual_weight,
                marginal_weight=1.0,
                pair_weight=1.0,
                huber_beta=self.scalar_loss.huber_beta,
                softmin_tau=self.scalar_loss.softmin_tau,
            )
            _total, parts = self.trainer.compute_loss(
                output, batch_device, LANE, calibration_config
            )
        return parts["scalar"], parts["marginal_contact"], parts["pair_contact"]


def _prepare_calibration_batches(
    config: FoldConfig,
    inputs: FoldInputs,
    collator: Any,
) -> list[dict[str, Any]]:
    scalar_batches = _batch_order(
        inputs.base,
        inputs.split.train_indices,
        collator,
        config.batch_size,
        config.seed,
    )
    prepared = []
    for ordinal, (indices, raw) in enumerate(scalar_batches):
        selected_rows = [inputs.rows[index] for index in indices]
        augmented = inputs.teacher_store.augment_batch(
            raw, selected_rows, raw["residue_mask"]
        )
        prepared.append(
            {
                "batch_id": f"fold{config.fold_id}_epoch0_batch{ordinal:05d}",
                "outer_fit": True,
                "contact_eligible": _contact_eligible(augmented),
                "payload": augmented,
            }
        )
    require(sum(row["contact_eligible"] for row in prepared) >= 8, "fewer_than_8_contact_eligible_batches")
    return prepared


def _optimizer_audit_hash(audit: Mapping[str, Any]) -> str:
    canonical = {
        role: {
            "parameter_tensors": int(values["parameter_tensors"]),
            "parameter_values": int(values["parameter_values"]),
            "names": list(values["names"]),
        }
        for role, values in sorted(audit.items())
    }
    return _sha256_json(canonical)


def _teacher_audit(store: Any) -> dict[str, Any]:
    audit = store.audit if hasattr(store, "audit") else store.audit_report()
    require(isinstance(audit, Mapping), "teacher_audit_invalid")
    report = dict(audit)
    require(
        int(report.get("score_parent_numeric_int_parse_count", 0)) == 0,
        "outer_score_contact_integer_access_nonzero",
    )
    require(
        int(report.get("score_parent_numeric_float_parse_count", 0)) == 0,
        "outer_score_contact_float_access_nonzero",
    )
    return report


def evaluate_lane_e(
    inputs: FoldInputs,
    indices: Sequence[int],
    collator: Any,
    device: torch.device,
    precision: str,
    batch_size: int,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """V2.13 evaluator logic with only the frozen lane changed from B to E."""

    inputs.model.eval()
    target_device = inputs.base.move(inputs.target_graphs, device)
    truth, predicted = [], []
    records: list[dict[str, str]] = []
    exact_min_max_abs_error = 0.0
    with torch.no_grad():
        for batch_indices, raw in inputs.base.iter_batches(
            indices, collator, batch_size, shuffle_seed=None
        ):
            batch = inputs.base.move(raw, device)
            with torch.autocast(
                device_type=device.type,
                dtype=torch.bfloat16,
                enabled=precision == "bf16",
            ):
                output = inputs.trainer.forward_lane(
                    inputs.model, LANE, batch, target_device
                )
            receptor = output["receptor_predictions"].float().cpu().numpy()
            exact = receptor.min(axis=1)
            reported = output["exact_min_dual"].float().cpu().numpy()
            error = float(abs(exact - reported).max())
            require(error <= 1e-7, f"model_exact_min_mismatch:{error}")
            exact_min_max_abs_error = max(exact_min_max_abs_error, error)
            targets = raw["targets"].numpy()
            truth.append(targets)
            predicted.append(receptor)
            for local, index in enumerate(batch_indices):
                row = inputs.rows[index]
                # The collator stores targets as float32 tensors for training,
                # but the paired OOF evaluator is aligned to the authoritative
                # teacher-table decimal values used by the frozen B0 replay.
                # Serializing ``raw["targets"]`` here would introduce a small
                # float32 truth drift and break an otherwise valid paired
                # whole-parent bootstrap against B0.
                authoritative_target = row.targets
                records.append(
                    {
                        "candidate_id": row.candidate_id,
                        "parent_framework_cluster": row.parent,
                        "target_R_8X6B": f"{authoritative_target[0]:.12g}",
                        "target_R_9E6Y": f"{authoritative_target[1]:.12g}",
                        "target_R_dual_min": f"{min(authoritative_target):.12g}",
                        "prediction_R_8X6B": f"{receptor[local,0]:.12g}",
                        "prediction_R_9E6Y": f"{receptor[local,1]:.12g}",
                        "prediction_R_dual_min": f"{exact[local]:.12g}",
                        "exact_min_abs_error": f"{abs(exact[local]-reported[local]):.12g}",
                    }
                )
    import numpy as np

    target_array = np.concatenate(truth)
    prediction_array = np.concatenate(predicted)
    metrics = inputs.base.comprehensive_metrics(
        [inputs.rows[index].candidate_id for index in indices],
        [inputs.rows[index].parent for index in indices],
        target_array,
        prediction_array,
    )
    metrics["exact_min_max_abs_error"] = exact_min_max_abs_error
    metrics["rows"] = len(records)
    return metrics, records


def run_fold_core(
    config: FoldConfig,
    inputs: FoldInputs,
    *,
    paired_module: Any | None = None,
    calibration_module: Any | None = None,
    calibrator: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    config.validate()
    require(not config.output_dir.exists(), f"output_dir_exists:{config.output_dir}")
    require(inputs.model.head.config.enable_contact_evidence is True, "lane_e_contact_modules_disabled")
    require(inputs.model.head.config.contact_encoder_gradient == "shared", "contact_gradient_not_shared")
    require(inputs.split.train_indices and inputs.split.development_indices, "split_empty")
    require(not (set(inputs.split.train_parents) & set(inputs.split.development_parents)), "parent_overlap")

    paired = paired_module or _sibling_module(
        "materialize_v220_paired_initial_state_v1.py", "v220_paired_state_runner"
    )
    calibration = calibration_module or _sibling_module(
        "calibrate_v220_contact_weight_v1.py", "v220_contact_calibration_runner"
    )
    calibrate = calibrator or calibration.calibrate_contact_weight
    inputs.base.seed_everything(config.seed)
    initial_receipt = paired.load_and_verify_initial_state(
        config.initial_state_path,
        inputs.model,
        backbone_identity_sha256=inputs.model_identity,
        receipt_path=config.initial_state_receipt_path,
        expected_checkpoint_sha256=config.expected_initial_state_sha256,
        expected_receipt_sha256=config.expected_initial_state_receipt_sha256,
    )
    # load_and_verify_initial_state already recomputes both the head state and
    # the separately bound frozen-backbone state.  Reuse that verified result
    # rather than hashing the 650M backbone a second time before training.
    initial_hashes = dict(initial_receipt["hashes"])

    truth_percentiles = inputs.base.training_truth_percentiles(
        inputs.rows, inputs.split.train_indices
    )
    weights = {
        index: inputs.rows[index].sample_weight
        * inputs.base.top_weight(
            truth_percentiles[index],
            config.top_weight_strength,
            config.top_weight_center,
            config.top_weight_scale,
        )
        for index in inputs.split.train_indices
    }
    collator = inputs.base.CleanCollator(
        inputs.rows, inputs.tokenizer, inputs.graph_store, weights, truth_percentiles
    )
    probe = collator(inputs.split.train_indices[: min(2, len(inputs.split.train_indices))])
    neural = inputs.trainer.neural_forward_kwargs(probe, inputs.target_graphs)
    require("marginal_targets" not in neural and "pair_targets_8x6b" not in neural, "contact_label_forward_leak")

    config.output_dir.mkdir(parents=True)
    _atomic_json(
        config.output_dir / RUNNING_NAME,
        {
            "schema_version": SCHEMA_VERSION,
            "status": "RUNNING_PAIRED_CONTACT_SHARED_FOLD",
            "arm": config.arm,
            "fold_id": config.fold_id,
            "seed": config.seed,
            "lane": LANE,
        },
    )
    batch_hashes = epoch_batch_order_hashes(
        inputs.base,
        inputs.rows,
        inputs.split.train_indices,
        collator,
        epochs=config.epochs,
        batch_size=config.batch_size,
        seed=config.seed,
    )
    device = torch.device(config.device)
    require(device.type != "cuda" or torch.cuda.is_available(), "cuda_unavailable")
    require(config.precision == "fp32" or device.type == "cuda", "bf16_requires_cuda")
    inputs.model.to(device)

    scalar_loss = inputs.trainer.OrthoLossConfig(
        receptor_weight=config.receptor_weight,
        dual_weight=config.dual_weight,
        marginal_weight=0.0,
        pair_weight=0.0,
        huber_beta=config.huber_beta,
        softmin_tau=config.softmin_tau,
    )
    calibration_batches = _prepare_calibration_batches(config, inputs, collator)
    adapter = CalibrationTrainerAdapter(inputs.base, inputs.trainer, scalar_loss)
    try:
        calibration_receipt = dict(
            calibrate(
                inputs.model,
                adapter,
                calibration_batches,
                inputs.target_graphs,
                device,
                config.precision,
                grid=FIXED_LAMBDA_GRID,
            )
        )
    except Exception as error:
        failure = getattr(error, "result", None)
        if isinstance(failure, Mapping):
            _atomic_json(config.output_dir / CALIBRATION_NAME, dict(failure))
        raise
    require(calibration_receipt.get("optimizer_created") is False, "calibration_optimizer_created")
    require(calibration_receipt.get("training_started") is False, "calibration_started_training")
    selected_lambda = float(calibration_receipt["selected_contact_weight"])
    require(selected_lambda in FIXED_LAMBDA_GRID, "selected_lambda_outside_grid")
    _atomic_json(config.output_dir / CALIBRATION_NAME, calibration_receipt)

    applied_marginal = 0.0 if config.arm == "C0" else selected_lambda
    applied_pair = 0.5 * applied_marginal
    loss_config = inputs.trainer.OrthoLossConfig(
        receptor_weight=config.receptor_weight,
        dual_weight=config.dual_weight,
        marginal_weight=applied_marginal,
        pair_weight=applied_pair,
        huber_beta=config.huber_beta,
        softmin_tau=config.softmin_tau,
    )
    inputs.trainer.trainer_contract(LANE, inputs.model, loss_config)
    optimizer, optimizer_audit = inputs.trainer.build_optimizer(
        inputs.model,
        inputs.trainer.OptimizerConfig(
            learning_rate=config.learning_rate,
            weight_decay=config.weight_decay,
            contact_learning_rate_multiplier=1.0,
        ),
    )
    require(optimizer_audit["contact"]["parameter_values"] > 0, "contact_optimizer_group_empty")
    optimizer_hash = _optimizer_audit_hash(optimizer_audit)
    trainable = [parameter for parameter in inputs.model.parameters() if parameter.requires_grad]
    target_device = inputs.base.move(inputs.target_graphs, device)
    history: list[dict[str, Any]] = []
    optimizer_steps = 0

    for epoch in range(config.epochs):
        inputs.model.train()
        inputs.model.backbone.eval()
        optimizer.zero_grad(set_to_none=True)
        sums: dict[str, float] = defaultdict(float)
        batches = 0
        epoch_batches = _batch_order(
            inputs.base,
            inputs.split.train_indices,
            collator,
            config.batch_size,
            config.seed + epoch,
        )
        require(batch_order_sha256(inputs.rows, epoch_batches) == batch_hashes[epoch], "batch_order_hash_drift")
        for indices, raw in epoch_batches:
            selected_rows = [inputs.rows[index] for index in indices]
            augmented = inputs.teacher_store.augment_batch(
                raw, selected_rows, raw["residue_mask"]
            )
            batch = inputs.base.move(augmented, device)
            with torch.autocast(
                device_type=device.type,
                dtype=torch.bfloat16,
                enabled=config.precision == "bf16",
            ):
                output = inputs.trainer.forward_lane(
                    inputs.model, LANE, batch, target_device
                )
                total, parts = inputs.trainer.compute_loss(
                    output, batch, LANE, loss_config
                )
            (total / config.gradient_accumulation).backward()
            batches += 1
            for name, value in parts.items():
                sums[name] += float(value.detach().cpu())
            if batches % config.gradient_accumulation == 0:
                nn.utils.clip_grad_norm_(
                    trainable, config.gradient_clip, error_if_nonfinite=True
                )
                optimizer.step()
                inputs.trainer.assert_train_state_finite(inputs.model, optimizer)
                optimizer.zero_grad(set_to_none=True)
                optimizer_steps += 1
        require(batches > 0, f"epoch_empty:{epoch}")
        remainder = batches % config.gradient_accumulation
        if remainder:
            correction = config.gradient_accumulation / remainder
            for parameter in trainable:
                if parameter.grad is not None:
                    parameter.grad.mul_(correction)
            nn.utils.clip_grad_norm_(
                trainable, config.gradient_clip, error_if_nonfinite=True
            )
            optimizer.step()
            inputs.trainer.assert_train_state_finite(inputs.model, optimizer)
            optimizer.zero_grad(set_to_none=True)
            optimizer_steps += 1
        history.append(
            {
                "epoch": epoch + 1,
                "batches": batches,
                "batch_order_sha256": batch_hashes[epoch],
                **{name: value / batches for name, value in sorted(sums.items())},
            }
        )
        _atomic_json(
            config.output_dir / HISTORY_NAME,
            {"selection": "NONE_FIXED_EPOCH_ONLY", "epochs": history},
        )

    metrics, records = evaluate_lane_e(
        inputs,
        inputs.split.development_indices,
        collator,
        device,
        config.precision,
        config.eval_batch_size,
    )
    row_by_id = {row.candidate_id: row for row in inputs.rows}
    for record in records:
        row = row_by_id[record["candidate_id"]]
        record["sequence_sha256"] = row.sequence_sha256
        record["fold_id"] = str(config.fold_id)
        record["seed"] = str(config.seed)
        record["arm"] = config.arm
    prediction_path = config.output_dir / PREDICTION_NAME
    inputs.base._write_predictions(prediction_path, records)
    final_hashes = paired.state_hashes(
        inputs.model, inputs.model_identity
    )
    checkpoint_path = config.output_dir / CHECKPOINT_NAME
    _atomic_torch_save(
        checkpoint_path,
        {
            "schema_version": SCHEMA_VERSION,
            "lane": LANE,
            "arm": config.arm,
            "fold_id": config.fold_id,
            "seed": config.seed,
            "head_config": asdict(inputs.model.head.config),
            "head_state_dict": {
                name: value.detach().cpu()
                for name, value in inputs.model.head.state_dict().items()
            },
            "initial_state_hashes": initial_hashes,
            "final_state_hashes": final_hashes,
            "selected_marginal_weight": selected_lambda,
            "applied_marginal_weight": applied_marginal,
            "applied_pair_weight": applied_pair,
            "optimizer_group_sha256": optimizer_hash,
            "epoch_batch_order_sha256": batch_hashes,
        },
    )
    teacher_audit = _teacher_audit(inputs.teacher_store)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": f"PASS_V220_{config.arm}_CONTACT_SHARED_FOLD",
        "lane": LANE,
        "contact_encoder_gradient": "shared",
        "arm": config.arm,
        "fold_id": config.fold_id,
        "seed": config.seed,
        "claim_boundary": CLAIM_BOUNDARY,
        "split": {
            "split_id": str(inputs.split.split_id),
            "train_rows": len(inputs.split.train_indices),
            "score_rows": len(inputs.split.development_indices),
            "train_parents": len(inputs.split.train_parents),
            "score_parents": len(inputs.split.development_parents),
            "whole_parent_overlap": 0,
        },
        "pairing": {
            "initial_state_path": str(config.initial_state_path),
            "serialized_initial_state_scope": initial_receipt[
                "serialized_state_scope"
            ],
            "backbone_binding": initial_receipt["backbone_binding"],
            "initial_state_hashes": initial_hashes,
            "serialized_initial_state_sha256": initial_receipt[
                "serialized_checkpoint_sha256"
            ],
            "optimizer_group_sha256": optimizer_hash,
            "epoch_batch_order_sha256": batch_hashes,
        },
        "contact_weights": {
            "selected_marginal_weight": selected_lambda,
            "selected_pair_weight": 0.5 * selected_lambda,
            "applied_marginal_weight": applied_marginal,
            "applied_pair_weight": applied_pair,
            "c0_records_same_calibration_but_applies_zero": config.arm == "C0",
        },
        "training": {
            "fixed_epochs": config.epochs,
            "batch_size": config.batch_size,
            "eval_batch_size": config.eval_batch_size,
            "gradient_accumulation": config.gradient_accumulation,
            "precision": config.precision,
            "optimizer": "AdamW",
            "optimizer_steps": optimizer_steps,
            "optimizer_parameter_roles": optimizer_audit,
            "loss": asdict(loss_config),
            "pair_rank_weight": 0.0,
            "balanced_top_per_batch": 0,
            "pcgrad": False,
            "checkpoint_selection": "fixed_final_epoch_only",
        },
        "metrics": metrics,
        "teacher_store_audit": teacher_audit,
        "neural_input_firewall": {
            "contact_labels_forwarded": False,
            "outer_score_contact_numeric_reads": 0,
            "candidate_id_forwarded": False,
            "parent_id_forwarded": False,
            "m2_forwarded": False,
            "c2_forwarded": False,
        },
        "exact_min_inference": True,
        "model_identity": inputs.model_identity,
        "input_bindings": dict(inputs.input_bindings or {}),
        "outputs": {
            PREDICTION_NAME: inputs.base.sha256_file(prediction_path),
            CHECKPOINT_NAME: inputs.base.sha256_file(checkpoint_path),
            HISTORY_NAME: inputs.base.sha256_file(config.output_dir / HISTORY_NAME),
            CALIBRATION_NAME: inputs.base.sha256_file(
                config.output_dir / CALIBRATION_NAME
            ),
        },
    }
    _atomic_json(config.output_dir / RESULT_NAME, receipt)
    (config.output_dir / RUNNING_NAME).unlink()
    return receipt


def default_v213_runner_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "v2_13_top5_enrichment_v1_20260722"
        / "src"
        / "run_top5_clean_attention_fold_v1.py"
    )


def prepare_production_inputs(args: argparse.Namespace) -> tuple[FoldConfig, FoldInputs]:
    base = _load_module(args.v213_runner, "v213_clean_attention_for_v220")
    contract = base.load_contract(args.scalar_contract)
    expected = contract["expected_counts"]
    training_path = base._verify_bound_file(contract["training_table"], "training_table")
    split_path = base._verify_bound_file(contract["split_manifest"], "split_manifest")
    target_receipt_path = base._verify_bound_file(
        contract["fixed_target_graph"]["receipt"], "target_graph_receipt"
    )
    target_path = base._verify_bound_file(
        contract["fixed_target_graph"]["torch_artifact"], "target_graph_pt"
    )
    rows = base.load_rows(training_path, int(expected["total"]))
    split = base.load_split(
        split_path, rows, int(expected["train"]), int(expected["score"])
    )
    require(int(contract["task"]["fold_id"]) == args.fold_id, "fold_contract_mismatch")
    graph_store = base.GraphCacheStore(args.graph_cache_dir, rows, require_full_receipt=True)
    target_graphs = base.load_target_graphs(
        target_path, graph_store.edge_feature_dim, target_receipt_path
    )
    target_dim = int(next(iter(target_graphs.values()))["node_features"].shape[1])
    model_module, trainer = base.load_frozen_ortho_modules(contract)
    backbone, tokenizer, hidden, model_identity = base.load_backbone(args)
    model_config = model_module.ResidueV25OrthoConfig.for_lane(
        LANE,
        backbone_hidden_size=hidden,
        target_node_dim=target_dim,
        edge_feature_dim=graph_store.edge_feature_dim,
        graph_hidden_dim=args.graph_hidden_dim,
        dropout=args.dropout,
        enable_contact_evidence=True,
        contact_encoder_gradient="shared",
    )
    model = trainer.build_model(LANE, backbone, model_config)
    teacher_module = _sibling_module(
        "v220_contact_teacher_store_v1.py", "v220_contact_teacher_store_runner"
    )
    allowed_candidates = {
        rows[index].candidate_id: (
            rows[index].sequence_sha256,
            rows[index].parent,
        )
        for index in split.train_indices
    }
    teacher_store = teacher_module.ContactTeacherStore.from_release(
        args.teacher_release, allowed_candidates
    )
    config = FoldConfig(
        arm=args.arm,
        fold_id=args.fold_id,
        output_dir=args.output_dir,
        initial_state_path=args.initial_state,
        initial_state_receipt_path=args.initial_state_receipt,
        expected_initial_state_sha256=args.expected_initial_state_sha256,
        expected_initial_state_receipt_sha256=(
            args.expected_initial_state_receipt_sha256
        ),
        device=args.device,
        seed=args.seed,
        epochs=args.epochs,
        batch_size=args.batch_size,
        eval_batch_size=args.eval_batch_size,
        gradient_accumulation=args.gradient_accumulation,
        precision=args.precision,
        learning_rate=args.learning_rate,
        weight_decay=args.weight_decay,
        gradient_clip=args.gradient_clip,
        graph_hidden_dim=args.graph_hidden_dim,
        dropout=args.dropout,
        receptor_weight=args.receptor_weight,
        dual_weight=args.dual_weight,
        huber_beta=args.huber_beta,
        softmin_tau=args.softmin_tau,
        top_weight_strength=args.top_weight_strength,
        top_weight_center=args.top_weight_center,
        top_weight_scale=args.top_weight_scale,
        tiny_e2e=False,
    )
    bindings = {
        "scalar_contract_sha256": base.sha256_file(args.scalar_contract),
        "training_table_sha256": base.sha256_file(training_path),
        "split_manifest_sha256": base.sha256_file(split_path),
        "target_graph_sha256": base.sha256_file(target_path),
        "target_graph_receipt_sha256": base.sha256_file(target_receipt_path),
        "graph_bundle_sha256": graph_store.input_hashes,
        "teacher_package_receipt_sha256": teacher_store.audit[
            "package_receipt_sha256"
        ],
    }
    return config, FoldInputs(
        base=base,
        trainer=trainer,
        model=model,
        tokenizer=tokenizer,
        rows=rows,
        split=split,
        graph_store=graph_store,
        target_graphs=target_graphs,
        teacher_store=teacher_store,
        model_identity=model_identity,
        input_bindings=bindings,
    )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--scalar-contract", type=Path, required=True)
    value.add_argument("--teacher-release", type=Path, required=True)
    value.add_argument("--graph-cache-dir", type=Path, required=True)
    value.add_argument("--initial-state", type=Path, required=True)
    value.add_argument("--initial-state-receipt", type=Path, required=True)
    value.add_argument("--expected-initial-state-sha256", required=True)
    value.add_argument("--expected-initial-state-receipt-sha256", required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--arm", choices=ARMS, required=True)
    value.add_argument("--fold-id", type=int, required=True)
    value.add_argument("--v213-runner", type=Path, default=default_v213_runner_path())
    value.add_argument("--device", default="cuda:0")
    value.add_argument("--seed", type=int, default=43)
    value.add_argument("--epochs", type=int, default=8)
    value.add_argument("--batch-size", type=int, default=8)
    value.add_argument("--eval-batch-size", type=int, default=16)
    value.add_argument("--gradient-accumulation", type=int, default=4)
    value.add_argument("--precision", choices=("fp32", "bf16"), default="bf16")
    value.add_argument("--learning-rate", type=float, default=1e-4)
    value.add_argument("--weight-decay", type=float, default=0.02)
    value.add_argument("--gradient-clip", type=float, default=1.0)
    value.add_argument("--graph-hidden-dim", type=int, default=128)
    value.add_argument("--dropout", type=float, default=0.25)
    value.add_argument("--receptor-weight", type=float, default=1.0)
    value.add_argument("--dual-weight", type=float, default=0.5)
    value.add_argument("--huber-beta", type=float, default=0.03)
    value.add_argument("--softmin-tau", type=float, default=0.02)
    value.add_argument("--top-weight-strength", type=float, default=3.0)
    value.add_argument("--top-weight-center", type=float, default=0.85)
    value.add_argument("--top-weight-scale", type=float, default=0.05)
    value.add_argument("--backbone-kind", choices=("hf",), default="hf")
    value.add_argument("--backbone-dtype", choices=("bf16",), default="bf16")
    value.add_argument("--model-path", type=Path, required=True)
    value.add_argument("--model-identity-file", type=Path, required=True)
    value.add_argument("--expected-model-sha256", required=True)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    config, inputs = prepare_production_inputs(args)
    result = run_fold_core(config, inputs)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
