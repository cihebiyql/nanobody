#!/usr/bin/env python3
"""Focused trainer primitives for V2.5 orthogonal attention/contact heads.

This module intentionally does not implement deployment, split selection, M2,
coarse-pose stacking, or metric reporting.  It provides the immutable neural
input firewall, lane construction, loss routing, and optimizer grouping needed
by a later strict nested-crossfit launcher.
"""

from __future__ import annotations

import inspect
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from collections.abc import Callable, Iterable
from typing import Any, Mapping, Sequence

import torch
from torch import Tensor, nn
from torch.nn import functional as F
from torch.optim import AdamW


HERE = Path(__file__).resolve()
MODEL_DIR = HERE.parents[1] / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))
from residue_model_v2_5_ortho import (  # noqa: E402
    LANE_B,
    LANE_E,
    LANES,
    OrthogonalResidueSurrogate,
    OrthogonalTargetHead,
    ResidueV25OrthoConfig,
    exact_min_dual,
    stable_softmin,
)


SCHEMA_VERSION = "pvrig_v2_5_ortho_head_trainer_v1"
NEURAL_REQUIRED_BATCH_FIELDS = (
    "input_ids",
    "attention_mask",
    "residue_mask",
    "vhh_aa_index",
    "vhh_region_index",
    "vhh_confidence",
    "vhh_edge_index",
    "vhh_edge_features",
)
FORBIDDEN_NEURAL_INPUT_FIELDS = (
    "m2_base",
    "m2_outputs",
    "structure",
    "structure_features",
    "candidate_id",
    "candidate_ids",
    "parent_id",
    "parent_framework_cluster",
    "campaign_id",
    "docking_pose",
    "docking_pose_features",
    "pose_features",
    "teacher_source",
)


class OrthoTrainerError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OrthoTrainerError(message)


def require_finite(value: Tensor, message: str) -> None:
    require(bool(torch.all(torch.isfinite(value))), message)


class TinyBackbone(nn.Module):
    def __init__(self, vocab_size: int = 32, hidden_size: int = 12) -> None:
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, hidden_size)

    def forward(self, input_ids: Tensor, attention_mask: Tensor) -> Any:
        del attention_mask
        return SimpleNamespace(last_hidden_state=self.embedding(input_ids))


@dataclass(frozen=True)
class OrthoLossConfig:
    receptor_weight: float = 1.0
    dual_weight: float = 0.5
    marginal_weight: float = 0.0
    pair_weight: float = 0.0
    huber_beta: float = 0.03
    softmin_tau: float = 0.02

    def validate(self, lane: str) -> None:
        require(lane in LANES, f"lane_invalid:{lane}")
        for name, value in asdict(self).items():
            require(math.isfinite(float(value)), f"loss_config_nonfinite:{name}")
        require(self.receptor_weight > 0.0 and self.dual_weight >= 0.0, "scalar_weight_invalid")
        require(self.marginal_weight >= 0.0 and self.pair_weight >= 0.0, "contact_weight_invalid")
        require(self.huber_beta > 0.0 and self.softmin_tau > 0.0, "loss_scale_invalid")
        if lane == LANE_B:
            require(
                self.marginal_weight == 0.0 and self.pair_weight == 0.0,
                "clean_attention_lane_contact_loss_forbidden",
            )


@dataclass(frozen=True)
class OptimizerConfig:
    learning_rate: float = 1e-4
    weight_decay: float = 0.02
    contact_learning_rate_multiplier: float = 1.0

    def validate(self) -> None:
        require(self.learning_rate > 0.0 and math.isfinite(self.learning_rate), "learning_rate_invalid")
        require(self.weight_decay >= 0.0 and math.isfinite(self.weight_decay), "weight_decay_invalid")
        require(
            self.contact_learning_rate_multiplier > 0.0
            and math.isfinite(self.contact_learning_rate_multiplier),
            "contact_lr_multiplier_invalid",
        )


def build_model(
    lane: str,
    backbone: nn.Module,
    config: ResidueV25OrthoConfig,
) -> OrthogonalResidueSurrogate:
    require(lane in LANES, f"lane_invalid:{lane}")
    require(config.enable_contact_evidence == (lane == LANE_E), "lane_contact_configuration_mismatch")
    model = OrthogonalResidueSurrogate(backbone, OrthogonalTargetHead(config))
    require(not any(parameter.requires_grad for parameter in model.backbone.parameters()), "backbone_not_frozen")
    return model


def neural_forward_kwargs(
    batch: Mapping[str, Any],
    target_graphs: Mapping[str, Mapping[str, Tensor]],
) -> dict[str, Any]:
    """Build the only permitted neural forward mapping by positive allowlist.

    Training batches may contain identifiers, M2 features, labels, and pose
    metadata for other pipeline components.  This function never reads them.
    """
    missing = [field for field in NEURAL_REQUIRED_BATCH_FIELDS if field not in batch]
    require(not missing, f"neural_batch_fields_missing:{','.join(missing)}")
    result = {field: batch[field] for field in NEURAL_REQUIRED_BATCH_FIELDS}
    result["target_graphs"] = target_graphs
    require(not (set(result) & set(FORBIDDEN_NEURAL_INPUT_FIELDS)), "neural_firewall_internal_error")
    return result


def forward_lane(
    model: OrthogonalResidueSurrogate,
    lane: str,
    batch: Mapping[str, Any],
    target_graphs: Mapping[str, Mapping[str, Tensor]],
) -> dict[str, Tensor]:
    require(lane in LANES, f"lane_invalid:{lane}")
    require(model.head.config.enable_contact_evidence == (lane == LANE_E), "model_lane_mismatch")
    return model(**neural_forward_kwargs(batch, target_graphs))


def _normalised_sample_weights(batch: Mapping[str, Any], count: int, device: torch.device) -> Tensor:
    weights = batch.get("hierarchy_weights")
    if weights is None:
        result = torch.ones(count, device=device, dtype=torch.float32)
    else:
        require(isinstance(weights, Tensor) and weights.shape == (count,), "hierarchy_weight_shape")
        result = weights.to(device=device, dtype=torch.float32)
    require_finite(result, "hierarchy_weight_nonfinite")
    require(bool(torch.all(result > 0.0)), "hierarchy_weight_nonpositive")
    return result / result.sum()


def _weighted_mean(values: Tensor, weights: Tensor) -> Tensor:
    require(values.shape == weights.shape, "weighted_mean_shape")
    return (values * weights.to(values.dtype)).sum() / weights.sum().clamp_min(1e-12)


def balanced_soft_bce_per_candidate(
    logits: Tensor,
    targets: Tensor,
    uncertainty_weights: Tensor,
    mask: Tensor,
    *,
    positive_class_fraction: float = 0.5,
    epsilon: float = 1e-8,
) -> tuple[Tensor, Tensor]:
    """Return candidate-level balanced soft BCE and availability mask."""
    require(logits.shape == targets.shape == uncertainty_weights.shape == mask.shape, "contact_shape")
    require(logits.ndim >= 2 and 0.0 < positive_class_fraction < 1.0, "contact_balance_contract")
    require_finite(logits, "contact_logits_nonfinite")
    require_finite(targets, "contact_targets_nonfinite")
    require_finite(uncertainty_weights, "contact_uncertainty_nonfinite")
    require(bool(torch.all((targets >= 0.0) & (targets <= 1.0))), "contact_target_range")
    require(bool(torch.all(uncertainty_weights >= 0.0)), "contact_uncertainty_negative")

    flat_logits = logits.float().reshape(len(logits), -1)
    flat_targets = targets.float().reshape(len(logits), -1)
    flat_weights = (uncertainty_weights.float() * mask.float()).reshape(len(logits), -1)
    positive_weights = flat_weights * flat_targets
    negative_weights = flat_weights * (1.0 - flat_targets)
    positive_mass = positive_weights.sum(1)
    negative_mass = negative_weights.sum(1)
    has_positive = positive_mass > epsilon
    has_negative = negative_mass > epsilon
    positive_mean = (F.softplus(-flat_logits) * positive_weights).sum(1) / positive_mass.clamp_min(epsilon)
    negative_mean = (F.softplus(flat_logits) * negative_weights).sum(1) / negative_mass.clamp_min(epsilon)
    both = has_positive & has_negative
    result = torch.zeros_like(positive_mean)
    result = torch.where(
        both,
        positive_class_fraction * positive_mean + (1.0 - positive_class_fraction) * negative_mean,
        result,
    )
    result = torch.where(has_positive & ~has_negative, positive_mean, result)
    result = torch.where(has_negative & ~has_positive, negative_mean, result)
    available = has_positive | has_negative
    require_finite(result, "balanced_contact_loss_nonfinite")
    return result, available


def _contact_component(
    losses: Sequence[Tensor],
    available: Sequence[Tensor],
    sample_weights: Tensor,
    tier_weights: Tensor,
    name: str,
) -> Tensor:
    require(len(losses) == len(available) and bool(losses), f"{name}_component_empty")
    stacked = torch.stack(tuple(losses), dim=-1)
    availability = torch.stack(tuple(available), dim=-1)
    receptor_count = availability.sum(1)
    candidate = (stacked * availability.to(stacked.dtype)).sum(1) / receptor_count.clamp_min(1).to(stacked.dtype)
    eligible = receptor_count > 0
    combined_weights = sample_weights * tier_weights.float() * eligible.float()
    require(float(combined_weights.sum()) > 0.0, f"{name}_no_eligible_weight")
    return _weighted_mean(candidate, combined_weights)


def compute_loss(
    output: Mapping[str, Tensor],
    batch: Mapping[str, Any],
    lane: str,
    config: OrthoLossConfig,
) -> tuple[Tensor, dict[str, Tensor]]:
    config.validate(lane)
    targets = batch.get("targets")
    require(isinstance(targets, Tensor) and targets.ndim == 2 and targets.shape[1] == 2, "targets_shape")
    targets = targets.to(device=output["receptor_predictions"].device, dtype=torch.float32)
    predictions = output["receptor_predictions"].float()
    require(predictions.shape == targets.shape, "prediction_target_shape")
    weights = _normalised_sample_weights(batch, len(targets), predictions.device)

    receptor_per_candidate = F.smooth_l1_loss(
        predictions, targets, reduction="none", beta=config.huber_beta,
    ).mean(1)
    predicted_soft_dual = stable_softmin(predictions[:, 0], predictions[:, 1], config.softmin_tau)
    truth_dual = exact_min_dual(targets)
    dual_per_candidate = F.smooth_l1_loss(
        predicted_soft_dual, truth_dual, reduction="none", beta=config.huber_beta,
    )
    receptor_loss = _weighted_mean(receptor_per_candidate, weights)
    dual_loss = _weighted_mean(dual_per_candidate, weights)
    scalar_loss = config.receptor_weight * receptor_loss + config.dual_weight * dual_loss
    parts: dict[str, Tensor] = {
        "receptor": receptor_loss,
        "softmin_dual": dual_loss,
        "scalar": scalar_loss,
        "marginal_contact": torch.zeros((), device=predictions.device),
        "pair_contact": torch.zeros((), device=predictions.device),
    }

    if lane == LANE_E and config.marginal_weight > 0.0:
        required = ("marginal_targets", "marginal_mask", "marginal_uncertainty")
        require(all(isinstance(batch.get(field), Tensor) for field in required), "marginal_targets_missing")
        logits = output["marginal_contact_logits"]
        marginal_targets = batch["marginal_targets"].to(logits.device)
        marginal_mask = batch["marginal_mask"].to(logits.device)
        marginal_uncertainty = batch["marginal_uncertainty"].to(logits.device)
        losses, available = [], []
        for receptor_index in range(2):
            value, present = balanced_soft_bce_per_candidate(
                logits[:, :, receptor_index],
                marginal_targets[:, :, receptor_index],
                marginal_uncertainty[:, :, receptor_index],
                marginal_mask[:, :, receptor_index],
            )
            losses.append(value)
            available.append(present)
        tier = batch.get("marginal_tier_weights", torch.ones(len(targets)))
        require(isinstance(tier, Tensor) and tier.shape == (len(targets),), "marginal_tier_shape")
        parts["marginal_contact"] = _contact_component(
            losses, available, weights, tier.to(predictions.device), "marginal",
        )

    if lane == LANE_E and config.pair_weight > 0.0:
        pair_losses, pair_available = [], []
        for receptor in ("8x6b", "9e6y"):
            target_key = f"pair_targets_{receptor}"
            mask_key = f"pair_mask_{receptor}"
            uncertainty_key = f"pair_uncertainty_{receptor}"
            require(
                all(isinstance(batch.get(field), Tensor) for field in (target_key, mask_key, uncertainty_key)),
                f"pair_targets_missing:{receptor}",
            )
            logits = output[f"contact_logits_{receptor}"]
            value, present = balanced_soft_bce_per_candidate(
                logits,
                batch[target_key].to(logits.device),
                batch[uncertainty_key].to(logits.device),
                batch[mask_key].to(logits.device),
            )
            pair_losses.append(value)
            pair_available.append(present)
        tier = batch.get("pair_tier_weights", torch.ones(len(targets)))
        require(isinstance(tier, Tensor) and tier.shape == (len(targets),), "pair_tier_shape")
        parts["pair_contact"] = _contact_component(
            pair_losses, pair_available, weights, tier.to(predictions.device), "pair",
        )

    contact_loss = (
        config.marginal_weight * parts["marginal_contact"]
        + config.pair_weight * parts["pair_contact"]
    )
    parts["contact"] = contact_loss
    total = scalar_loss + contact_loss
    parts["total"] = total
    require_finite(total, "total_loss_nonfinite")
    return total, parts


def named_parameter_roles(model: OrthogonalResidueSurrogate) -> dict[str, list[tuple[str, nn.Parameter]]]:
    roles: dict[str, list[tuple[str, nn.Parameter]]] = {"shared_encoder": [], "attention_scalar": [], "contact": []}
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad:
            continue
        require(name.startswith("head."), f"trainable_parameter_outside_head:{name}")
        local = name[len("head."):]
        if local.startswith(("aa_embedding", "region_embedding", "vhh_graph_encoder", "target_graph_encoder", "conformer_embedding")):
            roles["shared_encoder"].append((name, parameter))
        elif local.startswith(("attention_interaction", "condition_fusion", "scalar_head")):
            roles["attention_scalar"].append((name, parameter))
        elif local.startswith(("contact_interaction", "contact_calibration")):
            roles["contact"].append((name, parameter))
        else:
            raise OrthoTrainerError(f"unclassified_trainable_parameter:{name}")
    require(roles["shared_encoder"] and roles["attention_scalar"], "required_parameter_role_empty")
    return roles


def build_optimizer(
    model: OrthogonalResidueSurrogate,
    config: OptimizerConfig,
) -> tuple[AdamW, dict[str, Any]]:
    config.validate()
    roles = named_parameter_roles(model)
    groups: list[dict[str, Any]] = [
        {
            "params": [parameter for _name, parameter in roles["shared_encoder"]],
            "lr": config.learning_rate,
            "weight_decay": config.weight_decay,
            "role": "shared_encoder",
        },
        {
            "params": [parameter for _name, parameter in roles["attention_scalar"]],
            "lr": config.learning_rate,
            "weight_decay": config.weight_decay,
            "role": "attention_scalar",
        },
    ]
    if roles["contact"]:
        groups.append(
            {
                "params": [parameter for _name, parameter in roles["contact"]],
                "lr": config.learning_rate * config.contact_learning_rate_multiplier,
                "weight_decay": config.weight_decay,
                "role": "contact",
            }
        )
    optimizer = AdamW(groups)
    audit = {
        role: {
            "parameter_tensors": len(values),
            "parameter_values": sum(parameter.numel() for _name, parameter in values),
            "names": [name for name, _parameter in values],
        }
        for role, values in roles.items()
    }
    all_parameters = [parameter for values in roles.values() for _name, parameter in values]
    require(len({id(parameter) for parameter in all_parameters}) == len(all_parameters), "optimizer_parameter_overlap")
    return optimizer, audit


def move_to_device(value: Any, device: torch.device) -> Any:
    if isinstance(value, Tensor):
        return value.to(device=device)
    if isinstance(value, Mapping):
        return {key: move_to_device(item, device) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(move_to_device(item, device) for item in value)
    if isinstance(value, list):
        return [move_to_device(item, device) for item in value]
    return value


def assert_train_state_finite(model: nn.Module, optimizer: AdamW) -> None:
    for name, parameter in model.named_parameters():
        if parameter.requires_grad:
            require_finite(parameter, f"parameter_nonfinite:{name}")
            if parameter.grad is not None:
                require_finite(parameter.grad, f"gradient_nonfinite:{name}")
    for parameter, state in optimizer.state.items():
        del parameter
        for key, value in state.items():
            if isinstance(value, Tensor):
                require_finite(value, f"optimizer_state_nonfinite:{key}")


def train_fixed_epochs(
    model: OrthogonalResidueSurrogate,
    lane: str,
    batch_factory: Callable[[int], Iterable[Mapping[str, Any]]],
    target_graphs: Mapping[str, Mapping[str, Tensor]],
    loss_config: OrthoLossConfig,
    optimizer_config: OptimizerConfig,
    *,
    fixed_epochs: int,
    device_name: str,
    precision: str = "bf16",
    gradient_clip: float = 1.0,
    gradient_accumulation: int = 1,
) -> dict[str, Any]:
    """Run a fixed-epoch, no-selection training loop.

    The caller owns whole-parent splits and batch construction.  This function
    cannot inspect candidate IDs, M2, structure aggregates, or docking poses;
    only :func:`neural_forward_kwargs` reaches the model.
    """
    require(lane in LANES, f"lane_invalid:{lane}")
    loss_config.validate(lane)
    optimizer_config.validate()
    require(fixed_epochs > 0, "fixed_epochs_invalid")
    require(precision in {"fp32", "bf16"}, "precision_invalid")
    require(math.isfinite(gradient_clip) and gradient_clip > 0.0, "gradient_clip_invalid")
    require(gradient_accumulation > 0, "gradient_accumulation_invalid")

    device = torch.device(device_name)
    model.to(device)
    target_device = move_to_device(target_graphs, device)
    optimizer, optimizer_audit = build_optimizer(model, optimizer_config)
    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    history: list[dict[str, float]] = []
    steps = 0
    for epoch in range(fixed_epochs):
        model.train()
        model.backbone.eval()
        optimizer.zero_grad(set_to_none=True)
        sums: dict[str, float] = {}
        batches = 0
        for raw_batch in batch_factory(epoch):
            batch = move_to_device(raw_batch, device)
            autocast_enabled = precision == "bf16"
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=autocast_enabled):
                output = forward_lane(model, lane, batch, target_device)
                total, parts = compute_loss(output, batch, lane, loss_config)
            (total / gradient_accumulation).backward()
            for name, value in parts.items():
                sums[name] = sums.get(name, 0.0) + float(value.detach().cpu())
            batches += 1
            if batches % gradient_accumulation == 0:
                nn.utils.clip_grad_norm_(trainable, gradient_clip, error_if_nonfinite=True)
                optimizer.step()
                assert_train_state_finite(model, optimizer)
                optimizer.zero_grad(set_to_none=True)
                steps += 1
        require(batches > 0, f"epoch_has_no_batches:{epoch}")
        if batches % gradient_accumulation:
            # Correct the final partial accumulation window so its average has
            # the same scale as a full window.
            correction = gradient_accumulation / (batches % gradient_accumulation)
            for parameter in trainable:
                if parameter.grad is not None:
                    parameter.grad.mul_(correction)
            nn.utils.clip_grad_norm_(trainable, gradient_clip, error_if_nonfinite=True)
            optimizer.step()
            assert_train_state_finite(model, optimizer)
            optimizer.zero_grad(set_to_none=True)
            steps += 1
        history.append({name: value / batches for name, value in sorted(sums.items())})
    return {
        "schema_version": "pvrig_v2_5_ortho_fixed_epoch_training_v1",
        "lane": lane,
        "fixed_epochs": fixed_epochs,
        "selection": "NONE_FIXED_EPOCH_ONLY",
        "optimizer_steps": steps,
        "precision": precision,
        "device": str(device),
        "gradient_accumulation": gradient_accumulation,
        "loss_config": asdict(loss_config),
        "optimizer_config": asdict(optimizer_config),
        "optimizer_parameter_roles": optimizer_audit,
        "epoch_history": history,
        "neural_input_firewall": {
            "allowlist": list(NEURAL_REQUIRED_BATCH_FIELDS) + ["target_graphs"],
            "forbidden": list(FORBIDDEN_NEURAL_INPUT_FIELDS),
        },
    }


def trainer_contract(lane: str, model: OrthogonalResidueSurrogate, loss: OrthoLossConfig) -> dict[str, Any]:
    loss.validate(lane)
    require(model.head.config.enable_contact_evidence == (lane == LANE_E), "model_lane_mismatch")
    wrapper_fields = set(inspect.signature(model.forward).parameters)
    require(not (wrapper_fields & set(FORBIDDEN_NEURAL_INPUT_FIELDS)), "forbidden_model_forward_feature")
    roles = named_parameter_roles(model)
    return {
        "schema_version": SCHEMA_VERSION,
        "lane": lane,
        "neural_forward_allowlist": list(NEURAL_REQUIRED_BATCH_FIELDS) + ["target_graphs"],
        "forbidden_neural_inputs": list(FORBIDDEN_NEURAL_INPUT_FIELDS),
        "scalar_contact_feedback": False,
        "contact_encoder_gradient": model.head.config.contact_encoder_gradient,
        "loss": asdict(loss),
        "direct_targets": ["R_8X6B", "R_9E6Y"],
        "derived_target": "exact_min(R_8X6B,R_9E6Y)",
        "training_dual_auxiliary": f"normalised_softmin_tau={loss.softmin_tau}",
        "parameter_role_counts": {name: len(values) for name, values in roles.items()},
    }
