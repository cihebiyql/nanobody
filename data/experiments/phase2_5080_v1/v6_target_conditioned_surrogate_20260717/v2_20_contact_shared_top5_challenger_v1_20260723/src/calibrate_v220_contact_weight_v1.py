#!/usr/bin/env python3
"""Calibrate V2.20 shared-contact loss weight before optimizer creation.

The calibration consumes the first eight contact-eligible batches in frozen
outer-fit order and measures gradients only on the ordered shared encoder
parameters.  It never calls backward(), creates an optimizer, or updates model
state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import statistics
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import torch
from torch import nn


SCHEMA_VERSION = "pvrig.v220.contact_weight_calibration.v1"
CONTACT_BATCH_COUNT = 8
PAIR_LOSS_COEFFICIENT = 0.5
LAMBDA_GRID = (0.00015625, 0.0003125, 0.000625, 0.00125, 0.0025)
TARGET_RATIO_INTERVAL = (0.05, 0.15)
TARGET_RATIO = 0.10
SEVERE_CONFLICT_COSINE = -0.5
MAX_SEVERE_CONFLICT_BATCHES = 2


class ContactCalibrationError(RuntimeError):
    """Raised for an invalid or unsafe calibration input."""


class ContactCalibrationPrelaunchError(ContactCalibrationError):
    """Raised when the preregistered gradient-conflict gate fails."""

    def __init__(self, message: str, result: Mapping[str, Any]):
        super().__init__(message)
        self.result = dict(result)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContactCalibrationError(message)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _tensor_bytes(tensor: torch.Tensor) -> bytes:
    cpu = tensor.detach().cpu().contiguous()
    if cpu.numel() == 0:
        return b""
    return cpu.view(torch.uint8).numpy().tobytes(order="C")


def model_state_sha256(model: nn.Module) -> str:
    records = []
    for name, tensor in sorted(model.state_dict().items()):
        records.append(
            {
                "name": name,
                "dtype": str(tensor.dtype),
                "shape": list(tensor.shape),
                "tensor_sha256": hashlib.sha256(_tensor_bytes(tensor)).hexdigest(),
            }
        )
    return hashlib.sha256(_canonical_json_bytes(records)).hexdigest()


@dataclass(frozen=True)
class CalibrationBatch:
    batch_id: str
    payload: Any
    outer_fit: bool = True
    contact_eligible: bool = True


def select_first_contact_eligible_batches(
    batches: Sequence[CalibrationBatch], expected: int = CONTACT_BATCH_COUNT
) -> list[CalibrationBatch]:
    _require(expected == CONTACT_BATCH_COUNT, "V2.20 requires exactly 8 batches")
    selected: list[CalibrationBatch] = []
    observed_ids: set[str] = set()
    for batch in batches:
        _require(batch.outer_fit, f"non-outer-fit batch encountered: {batch.batch_id}")
        _require(batch.batch_id not in observed_ids, f"duplicate batch id: {batch.batch_id}")
        observed_ids.add(batch.batch_id)
        if batch.contact_eligible:
            selected.append(batch)
            if len(selected) == expected:
                break
    _require(
        len(selected) == expected,
        f"need {expected} contact-eligible outer-fit batches, found {len(selected)}",
    )
    return selected


def validate_shared_parameters(
    model: nn.Module, shared_parameters: Sequence[tuple[str, nn.Parameter]]
) -> list[tuple[str, nn.Parameter]]:
    ordered = list(shared_parameters)
    _require(ordered, "shared parameter list is empty")
    named = dict(model.named_parameters())
    seen: set[str] = set()
    for name, parameter in ordered:
        _require(name in named, f"unknown shared parameter: {name}")
        _require(named[name] is parameter, f"shared parameter object mismatch: {name}")
        _require(parameter.requires_grad, f"shared parameter is frozen: {name}")
        _require(name not in seen, f"duplicate shared parameter: {name}")
        _require(parameter.grad is None, f"pre-existing gradient on {name}")
        seen.add(name)
    return ordered


def shared_parameter_order_sha256(
    parameters: Sequence[tuple[str, nn.Parameter]],
) -> str:
    records = [
        {
            "name": name,
            "dtype": str(parameter.dtype),
            "shape": list(parameter.shape),
        }
        for name, parameter in parameters
    ]
    return hashlib.sha256(_canonical_json_bytes(records)).hexdigest()


def _flatten_gradients(
    gradients: Sequence[torch.Tensor | None],
    parameters: Sequence[nn.Parameter],
    label: str,
) -> torch.Tensor:
    pieces = []
    nonzero_path = False
    for gradient, parameter in zip(gradients, parameters):
        if gradient is None:
            piece = torch.zeros(parameter.numel(), dtype=torch.float64)
        else:
            _require(
                torch.isfinite(gradient).all().item(), f"non-finite {label} gradient"
            )
            piece = gradient.detach().reshape(-1).to(device="cpu", dtype=torch.float64)
            nonzero_path = nonzero_path or bool(torch.count_nonzero(piece).item())
        pieces.append(piece)
    _require(nonzero_path, f"zero/unused {label} gradient on shared parameters")
    return torch.cat(pieces)


def _validate_loss(loss: torch.Tensor, label: str) -> None:
    _require(torch.is_tensor(loss), f"{label} loss is not a tensor")
    _require(loss.numel() == 1, f"{label} loss must be scalar")
    _require(bool(torch.isfinite(loss.detach()).item()), f"non-finite {label} loss")
    _require(loss.requires_grad, f"{label} loss has no gradient path")


def choose_contact_weight(
    base_ratios: Sequence[float],
) -> tuple[float, dict[str, float], bool]:
    _require(len(base_ratios) == CONTACT_BATCH_COUNT, "need 8 base ratios")
    _require(
        all(math.isfinite(value) and value > 0.0 for value in base_ratios),
        "base ratios must be finite and positive",
    )
    medians = {
        format(weight, ".8g"): float(
            statistics.median(weight * value for value in base_ratios)
        )
        for weight in LAMBDA_GRID
    }
    low, high = TARGET_RATIO_INTERVAL
    in_interval = [
        weight
        for weight in LAMBDA_GRID
        if low <= medians[format(weight, ".8g")] <= high
    ]
    if in_interval:
        return min(in_interval), medians, False
    selected = min(
        LAMBDA_GRID,
        key=lambda weight: (
            abs(medians[format(weight, ".8g")] - TARGET_RATIO),
            weight,
        ),
    )
    return selected, medians, True


def _capture_rng_state() -> dict[str, Any]:
    state: dict[str, Any] = {
        "python": random.getstate(),
        "torch_cpu": torch.get_rng_state().clone(),
    }
    if torch.cuda.is_available():
        state["torch_cuda"] = [item.clone() for item in torch.cuda.get_rng_state_all()]
    try:
        import numpy as np

        state["numpy"] = np.random.get_state()
    except ImportError:
        pass
    return state


def _restore_rng_state(state: Mapping[str, Any]) -> None:
    random.setstate(state["python"])
    torch.set_rng_state(state["torch_cpu"])
    if "torch_cuda" in state:
        torch.cuda.set_rng_state_all(state["torch_cuda"])
    if "numpy" in state:
        import numpy as np

        np.random.set_state(state["numpy"])


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _calibrate_contact_weight_core(
    *,
    model: nn.Module,
    batches: Sequence[CalibrationBatch],
    shared_parameters: Sequence[tuple[str, nn.Parameter]],
    loss_fn: Callable[
        [nn.Module, Any], tuple[torch.Tensor, torch.Tensor, torch.Tensor]
    ],
    receipt_path: Path | None = None,
    fail_on_conflict: bool = True,
    grid: Sequence[float] = LAMBDA_GRID,
) -> dict[str, Any]:
    """Measure scalar/contact gradient geometry without updating the model."""

    _require(tuple(grid) == LAMBDA_GRID, "V2.20 lambda grid is frozen")
    selected = select_first_contact_eligible_batches(batches)
    ordered_shared = validate_shared_parameters(model, shared_parameters)
    parameter_names = [name for name, _ in ordered_shared]
    parameters = [parameter for _, parameter in ordered_shared]
    before_state_hash = model_state_sha256(model)
    rng_state = _capture_rng_state()
    training_flags = {module: module.training for module in model.modules()}
    observations: list[dict[str, Any]] = []

    try:
        model.eval()
        for batch in selected:
            scalar_loss, marginal_loss, pair_loss = loss_fn(model, batch.payload)
            _validate_loss(scalar_loss, "scalar")
            _validate_loss(marginal_loss, "marginal contact")
            _validate_loss(pair_loss, "pair contact")
            contact_loss = marginal_loss + PAIR_LOSS_COEFFICIENT * pair_loss
            scalar_gradients = torch.autograd.grad(
                scalar_loss,
                parameters,
                retain_graph=True,
                create_graph=False,
                allow_unused=True,
            )
            contact_gradients = torch.autograd.grad(
                contact_loss,
                parameters,
                retain_graph=False,
                create_graph=False,
                allow_unused=True,
            )
            scalar_vector = _flatten_gradients(
                scalar_gradients, parameters, "scalar"
            )
            contact_vector = _flatten_gradients(
                contact_gradients, parameters, "contact composite"
            )
            scalar_norm = float(torch.linalg.vector_norm(scalar_vector).item())
            contact_norm = float(torch.linalg.vector_norm(contact_vector).item())
            _require(scalar_norm > 0.0, "zero scalar gradient norm")
            _require(contact_norm > 0.0, "zero contact gradient norm")
            cosine = float(
                torch.dot(scalar_vector, contact_vector).item()
                / (scalar_norm * contact_norm)
            )
            base_ratio = contact_norm / scalar_norm
            observations.append(
                {
                    "batch_id": batch.batch_id,
                    "scalar_gradient_l2": scalar_norm,
                    "contact_gradient_l2": contact_norm,
                    "unscaled_contact_to_scalar_ratio": base_ratio,
                    "gradient_cosine": cosine,
                    "candidate_scaled_ratios": {
                        format(weight, ".8g"): weight * base_ratio
                        for weight in LAMBDA_GRID
                    },
                }
            )
    finally:
        for module, training in training_flags.items():
            module.training = training
        _restore_rng_state(rng_state)

    after_state_hash = model_state_sha256(model)
    _require(before_state_hash == after_state_hash, "calibration mutated model state")
    for name, parameter in ordered_shared:
        _require(parameter.grad is None, f"calibration populated .grad for {name}")

    base_ratios = [row["unscaled_contact_to_scalar_ratio"] for row in observations]
    selected_weight, grid_medians, fallback_used = choose_contact_weight(base_ratios)
    severe_conflicts = sum(
        row["gradient_cosine"] < SEVERE_CONFLICT_COSINE for row in observations
    )
    passed = severe_conflicts <= MAX_SEVERE_CONFLICT_BATCHES
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "PASS_CONTACT_WEIGHT_CALIBRATED_NO_OPTIMIZER"
            if passed
            else "FAIL_PRELAUNCH_GRADIENT_CONFLICT"
        ),
        "gradient_definition": "g_contact = grad_shared(L_marginal + 0.5 * L_pair)",
        "scalar_gradient_definition": "g_scalar = grad_shared(L_scalar)",
        "batch_selection": "first_8_contact_eligible_batches_in_frozen_outer_fit_order",
        "selected_batch_ids": [batch.batch_id for batch in selected],
        "contact_batch_count": CONTACT_BATCH_COUNT,
        "shared_parameter_names": parameter_names,
        "shared_parameter_order_sha256": shared_parameter_order_sha256(
            ordered_shared
        ),
        "model_state_sha256_before": before_state_hash,
        "model_state_sha256_after": after_state_hash,
        "lambda_grid": list(LAMBDA_GRID),
        "target_median_ratio_interval": list(TARGET_RATIO_INTERVAL),
        "target_median_ratio": TARGET_RATIO,
        "grid_median_scaled_ratios": grid_medians,
        "selected_contact_weight": selected_weight,
        "fallback_to_closest_target": fallback_used,
        "severe_conflict_cosine_threshold": SEVERE_CONFLICT_COSINE,
        "maximum_severe_conflict_batches": MAX_SEVERE_CONFLICT_BATCHES,
        "severe_conflict_batch_count": severe_conflicts,
        "observations": observations,
        "optimizer_created": False,
        "optimizer_steps": 0,
        "training_started": False,
    }
    if receipt_path is not None:
        _atomic_json(Path(receipt_path), result)
    if not passed and fail_on_conflict:
        raise ContactCalibrationPrelaunchError(
            f"{severe_conflicts} batches have cosine < {SEVERE_CONFLICT_COSINE}",
            result,
        )
    return result


def _coerce_calibration_batch(item: Any, index: int) -> CalibrationBatch:
    if isinstance(item, CalibrationBatch):
        return item
    if isinstance(item, Mapping):
        return CalibrationBatch(
            batch_id=str(item.get("batch_id", f"batch_{index:04d}")),
            payload=item.get("payload", item),
            outer_fit=bool(item.get("outer_fit", True)),
            contact_eligible=bool(item.get("contact_eligible", True)),
        )
    return CalibrationBatch(
        batch_id=str(getattr(item, "batch_id", f"batch_{index:04d}")),
        payload=getattr(item, "payload", item),
        outer_fit=bool(getattr(item, "outer_fit", True)),
        contact_eligible=bool(getattr(item, "contact_eligible", True)),
    )


def calibrate_contact_weight(
    model: nn.Module,
    trainer: Any,
    batches: Sequence[Any],
    target_graphs: Any,
    device: Any,
    precision: Any,
    grid: Sequence[float] = LAMBDA_GRID,
) -> dict[str, Any]:
    """Runner-facing calibration API.

    The runner supplies path-independent batches and a trainer adapter exposing:

    ``shared_parameters(model) -> [(name, parameter), ...]`` and
    ``calibration_losses(model, batch, target_graphs, device, precision) ->
    (L_scalar, L_marginal, L_pair)``.
    """

    _require(tuple(grid) == LAMBDA_GRID, "V2.20 lambda grid is frozen")
    _require(
        hasattr(trainer, "shared_parameters")
        and callable(trainer.shared_parameters),
        "trainer must expose shared_parameters(model)",
    )
    _require(
        hasattr(trainer, "calibration_losses")
        and callable(trainer.calibration_losses),
        "trainer must expose calibration_losses(...) method",
    )
    converted = [_coerce_calibration_batch(item, i) for i, item in enumerate(batches)]
    shared = trainer.shared_parameters(model)

    def loss_adapter(current_model: nn.Module, payload: Any):
        losses = trainer.calibration_losses(
            current_model, payload, target_graphs, device, precision
        )
        if isinstance(losses, Mapping):
            return (
                losses["scalar_loss"],
                losses["marginal_loss"],
                losses["pair_loss"],
            )
        _require(len(losses) == 3, "calibration_losses must return three losses")
        return tuple(losses)

    receipt = _calibrate_contact_weight_core(
        model=model,
        batches=converted,
        shared_parameters=shared,
        loss_fn=loss_adapter,
        fail_on_conflict=True,
        grid=grid,
    )
    receipt["runner_context"] = {
        "device": str(device),
        "precision": str(precision),
        "target_graphs_provided": target_graphs is not None,
    }
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-contract", action="store_true")
    args = parser.parse_args()
    if not args.print_contract:
        parser.error(
            "Import calibrate_contact_weight with the real lane-E model and "
            "outer-fit batch stream; this command never starts training."
        )
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "contact_batch_count": CONTACT_BATCH_COUNT,
                "pair_loss_coefficient": PAIR_LOSS_COEFFICIENT,
                "lambda_grid": LAMBDA_GRID,
                "target_ratio_interval": TARGET_RATIO_INTERVAL,
                "severe_conflict_gate": {
                    "cosine_lt": SEVERE_CONFLICT_COSINE,
                    "fail_if_count_gt": MAX_SEVERE_CONFLICT_BATCHES,
                },
                "training_started": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
