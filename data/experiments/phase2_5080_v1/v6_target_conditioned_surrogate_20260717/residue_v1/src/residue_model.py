#!/usr/bin/env python3
"""Two-channel residue-contact pooling head for the V6 docking surrogate."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import torch
from torch import Tensor, nn
from torch.nn import functional as F


TARGET_NAMES = ("R_8X6B", "R_9E6Y", "R_dual_min")
RECEPTOR_NAMES = ("8x6b", "9e6y")
CLAIM_BOUNDARY = (
    "Sequence approximation of independent dual-receptor computational Docking "
    "geometry; not binding probability, affinity, experimental competition, "
    "blocking, Docking Gold, or final submission evidence."
)


class ResidueModelError(RuntimeError):
    """Fail-closed model or checkpoint error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ResidueModelError(message)


@dataclass(frozen=True)
class ResidueHeadConfig:
    backbone_hidden_size: int
    structure_dim: int = 126
    fusion_dim: int = 128
    dropout: float = 0.10
    residual_scale: float = 0.12
    detach_contact_pooling: bool = True
    pool_epsilon: float = 1e-5


@dataclass(frozen=True)
class ResidueLossConfig:
    dual_weight: float = 1.0
    receptor_weight: float = 0.35
    contact_weight: float = 0.25
    ranking_weight: float = 0.10
    residual_weight: float = 0.05
    huber_delta: float = 0.03
    ranking_minimum_delta: float = 0.005
    ranking_temperature: float = 0.02


class DualContactResidualHead(nn.Module):
    """Predict residue contacts and a bounded residual over an explicit M2 base.

    The M2 prediction is an input, never an internal learned branch.  This makes
    the cross-fitting provenance auditable and prevents the residue model from
    silently fitting each training row through an in-sample structure head.
    """

    def __init__(self, config: ResidueHeadConfig) -> None:
        super().__init__()
        require(config.backbone_hidden_size > 0, "backbone_hidden_size_invalid")
        require(config.structure_dim > 0 and config.fusion_dim > 0, "head_dimensions_invalid")
        require(0.0 < config.residual_scale <= 1.0, "residual_scale_invalid")
        self.config = config
        hidden = config.backbone_hidden_size
        fusion = config.fusion_dim
        self.contact_head = nn.Sequential(
            nn.LayerNorm(hidden),
            nn.Linear(hidden, fusion),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(fusion, len(RECEPTOR_NAMES)),
        )
        self.residue_projection = nn.Sequential(
            nn.LayerNorm(hidden),
            nn.Linear(hidden, fusion),
            nn.GELU(),
        )
        self.structure_projection = nn.Sequential(
            nn.LayerNorm(config.structure_dim),
            nn.Linear(config.structure_dim, fusion),
            nn.GELU(),
        )
        # global + two receptor-weighted pools + structure + explicit M2 base
        combined = fusion * 4 + len(TARGET_NAMES)
        self.residual_head = nn.Sequential(
            nn.LayerNorm(combined),
            nn.Linear(combined, fusion),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(fusion, len(TARGET_NAMES)),
        )

    def forward(
        self,
        token_states: Tensor,
        residue_mask: Tensor,
        structure_features: Tensor,
        m2_base: Tensor,
    ) -> dict[str, Tensor]:
        require(token_states.ndim == 3, "token_states_shape_invalid")
        require(residue_mask.shape == token_states.shape[:2], "residue_mask_shape_invalid")
        require(structure_features.shape == (len(token_states), self.config.structure_dim), "structure_shape_invalid")
        require(m2_base.shape == (len(token_states), len(TARGET_NAMES)), "m2_base_shape_invalid")
        require(bool(torch.all(residue_mask.sum(dim=1) > 0)), "empty_residue_mask")

        contact_logits = self.contact_head(token_states)
        projected = self.residue_projection(token_states)
        mask = residue_mask.to(dtype=projected.dtype).unsqueeze(-1)
        global_pool = (projected * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1.0)
        probabilities = torch.sigmoid(contact_logits)
        pooling_weights = probabilities.detach() if self.config.detach_contact_pooling else probabilities
        receptor_pools: list[Tensor] = []
        for channel in range(len(RECEPTOR_NAMES)):
            weights = pooling_weights[:, :, channel].to(projected.dtype) * residue_mask.to(projected.dtype)
            denominator = weights.sum(dim=1, keepdim=True).clamp_min(self.config.pool_epsilon)
            receptor_pools.append((projected * weights.unsqueeze(-1)).sum(dim=1) / denominator)
        structure = self.structure_projection(structure_features)
        fused = torch.cat((global_pool, receptor_pools[0], receptor_pools[1], structure, m2_base), dim=-1)
        raw_residual = self.residual_head(fused)
        residual = self.config.residual_scale * torch.tanh(raw_residual)
        prediction = m2_base + residual
        return {
            "prediction": prediction,
            "m2_base": m2_base,
            "residual": residual,
            "contact_logits": contact_logits,
            "contact_probabilities": probabilities,
        }


class ResidueSurrogate(nn.Module):
    """Backbone wrapper whose checkpoints intentionally omit base PLM weights."""

    def __init__(self, backbone: nn.Module, head: DualContactResidualHead, *, backbone_mode: str) -> None:
        super().__init__()
        require(backbone_mode in {"frozen", "lora"}, "invalid_backbone_mode")
        self.backbone = backbone
        self.head = head
        self.backbone_mode = backbone_mode
        if backbone_mode == "frozen":
            for parameter in self.backbone.parameters():
                parameter.requires_grad_(False)
        else:
            trainable = [name for name, parameter in self.backbone.named_parameters() if parameter.requires_grad]
            require(trainable, "lora_mode_has_no_trainable_adapter_parameters")
            require(all(is_adapter_parameter(name) for name in trainable), f"lora_mode_exposes_base_parameters:{trainable[:3]}")

    def forward(
        self,
        input_ids: Tensor,
        attention_mask: Tensor,
        residue_mask: Tensor,
        structure_features: Tensor,
        m2_base: Tensor,
    ) -> dict[str, Tensor]:
        if self.backbone_mode == "frozen":
            self.backbone.eval()
            with torch.no_grad():
                token_states = backbone_states(self.backbone, input_ids, attention_mask)
        else:
            token_states = backbone_states(self.backbone, input_ids, attention_mask)
        require(token_states.shape[:2] == input_ids.shape, "backbone_token_alignment_invalid")
        return self.head(token_states, residue_mask, structure_features, m2_base)


def backbone_states(backbone: nn.Module, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
    output = backbone(input_ids=input_ids, attention_mask=attention_mask)
    if isinstance(output, Tensor):
        states = output
    else:
        states = getattr(output, "last_hidden_state", None)
        if states is None:
            hidden = getattr(output, "hidden_states", None)
            require(hidden is not None and len(hidden) > 0, "backbone_missing_residue_states")
            states = hidden[-1]
    require(isinstance(states, Tensor) and states.ndim == 3, "backbone_state_shape_invalid")
    return states


def is_adapter_parameter(name: str) -> bool:
    lowered = name.lower()
    return "lora_" in lowered or ".adapter" in lowered or lowered.startswith("adapter")


def trainable_checkpoint_state(model: ResidueSurrogate) -> dict[str, Tensor]:
    """Return only head and adapter tensors; never serialize base PLM weights."""
    state = model.state_dict()
    allowed: dict[str, Tensor] = {}
    expected: set[str] = set()
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad:
            continue
        if name.startswith("head.") or (name.startswith("backbone.") and is_adapter_parameter(name)):
            expected.add(name)
        else:
            raise ResidueModelError(f"unexpected_trainable_parameter:{name}")
    for name in sorted(expected):
        require(name in state, f"trainable_state_missing:{name}")
        allowed[name] = state[name].detach().cpu()
    require(allowed, "empty_trainable_checkpoint")
    require(not any(name.startswith("backbone.") and not is_adapter_parameter(name) for name in allowed), "base_backbone_weight_in_checkpoint")
    return allowed


def load_trainable_checkpoint_state(model: ResidueSurrogate, state: Mapping[str, Tensor]) -> None:
    expected = set(trainable_checkpoint_state(model))
    observed = set(state)
    require(observed == expected, f"checkpoint_key_mismatch:missing={sorted(expected-observed)}:extra={sorted(observed-expected)}")
    current = model.state_dict()
    for name, value in state.items():
        require(current[name].shape == value.shape, f"checkpoint_shape_mismatch:{name}")
        current[name] = value
    model.load_state_dict(current, strict=True)


def weighted_mean(values: Tensor, weights: Tensor) -> Tensor:
    require(values.ndim == weights.ndim == 1 and values.shape == weights.shape, "weighted_mean_shape_invalid")
    return (values * weights).sum() / weights.sum().clamp_min(torch.finfo(values.dtype).eps)


def within_parent_ranking_loss(
    prediction: Tensor,
    target: Tensor,
    parents: Sequence[str],
    weights: Tensor,
    *,
    minimum_delta: float,
    temperature: float,
) -> Tensor:
    require(len(prediction) == len(target) == len(weights) == len(parents), "ranking_shape_invalid")
    losses: list[Tensor] = []
    pair_weights: list[Tensor] = []
    for left in range(len(prediction)):
        for right in range(left + 1, len(prediction)):
            if str(parents[left]) != str(parents[right]):
                continue
            delta = target[left] - target[right]
            if abs(float(delta.detach().cpu())) < minimum_delta:
                continue
            sign = torch.sign(delta)
            losses.append(F.softplus(-sign * (prediction[left] - prediction[right]) / temperature))
            pair_weights.append(torch.sqrt(weights[left] * weights[right]))
    if not losses:
        return prediction.sum() * 0.0
    return weighted_mean(torch.stack(losses), torch.stack(pair_weights))


def dual_contact_loss(
    logits: Tensor,
    targets: Tensor,
    mask: Tensor,
    sample_weights: Tensor,
    positive_weights: Tensor | None = None,
) -> Tensor:
    require(logits.shape == targets.shape == mask.shape and logits.ndim == 3 and logits.shape[-1] == 2, "contact_tensor_shape_invalid")
    valid = mask.to(dtype=logits.dtype)
    if positive_weights is None:
        positive_weights = torch.ones(2, device=logits.device, dtype=logits.dtype)
    require(positive_weights.shape == (2,) and bool(torch.all(positive_weights > 0)), "positive_weight_shape_invalid")
    per_token = F.binary_cross_entropy_with_logits(
        logits,
        targets,
        reduction="none",
        pos_weight=positive_weights.view(1, 1, 2),
    )
    counts = valid.sum(dim=(1, 2))
    available = counts > 0
    if not bool(torch.any(available)):
        return logits.sum() * 0.0
    per_candidate = (per_token * valid).sum(dim=(1, 2)) / counts.clamp_min(1.0)
    return weighted_mean(per_candidate[available], sample_weights[available])


def compute_loss(
    output: Mapping[str, Tensor],
    targets: Tensor,
    sample_weights: Tensor,
    parents: Sequence[str],
    contact_targets: Tensor,
    contact_mask: Tensor,
    config: ResidueLossConfig,
    *,
    contact_positive_weights: Tensor | None = None,
) -> tuple[Tensor, dict[str, Tensor]]:
    prediction = output["prediction"]
    require(prediction.shape == targets.shape and prediction.shape[1] == 3, "prediction_target_shape_invalid")
    require(sample_weights.shape == (len(targets),) and bool(torch.all(sample_weights > 0)), "sample_weight_invalid")
    huber = F.huber_loss(prediction, targets, delta=config.huber_delta, reduction="none")
    dual = weighted_mean(huber[:, 2], sample_weights)
    receptor = 0.5 * (weighted_mean(huber[:, 0], sample_weights) + weighted_mean(huber[:, 1], sample_weights))
    residual = weighted_mean(output["residual"].square().mean(dim=1), sample_weights)
    contact = dual_contact_loss(output["contact_logits"], contact_targets, contact_mask, sample_weights, contact_positive_weights)
    ranking = within_parent_ranking_loss(
        prediction[:, 2], targets[:, 2], parents, sample_weights,
        minimum_delta=config.ranking_minimum_delta,
        temperature=config.ranking_temperature,
    )
    total = (
        config.dual_weight * dual
        + config.receptor_weight * receptor
        + config.contact_weight * contact
        + config.ranking_weight * ranking
        + config.residual_weight * residual
    )
    return total, {
        "total": total,
        "dual_huber": dual,
        "receptor_huber": receptor,
        "contact_bce": contact,
        "ranking": ranking,
        "residual_penalty": residual,
    }


def model_contract(head: ResidueHeadConfig, loss: ResidueLossConfig, backbone_mode: str) -> dict[str, Any]:
    return {
        "schema_version": "pvrig_v6_residue_model_v1",
        "head": asdict(head),
        "loss": asdict(loss),
        "backbone_mode": backbone_mode,
        "targets": list(TARGET_NAMES),
        "contact_channels": list(RECEPTOR_NAMES),
        "claim_boundary": CLAIM_BOUNDARY,
        "checkpoint_policy": "adapter_and_head_only_no_base_plm_weights",
    }

