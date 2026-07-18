#!/usr/bin/env python3
"""Orthogonal attention/contact residue model for the V2.5 stack.

The scalar geometry path uses only the attention branch.  Contact evidence is
produced by a separate low-rank terminal branch and is never read by the scalar
head.  The contact branch can either share encoder gradients or consume
detached encoder states.  R_dual is always the exact minimum of direct R8/R9
predictions at inference.
"""

from __future__ import annotations

import inspect
import math
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal, Mapping

import torch
from torch import Tensor, nn
from torch.nn import functional as F


RECEPTOR_NAMES = ("8x6b", "9e6y")
DIRECT_TARGET_NAMES = ("R_8X6B", "R_9E6Y")
DERIVED_TARGET_NAME = "R_dual_min"
LANE_B = "B_CLEAN_TARGET_ATTENTION"
LANE_E = "E_DECOUPLED_CONTACT"
LANES = (LANE_B, LANE_E)
CLAIM_BOUNDARY = (
    "Sequence and label-free monomer-graph approximation of independent "
    "dual-receptor computational Docking geometry; not binding probability, "
    "affinity, experimental blocking, Docking Gold, or submission evidence."
)


class ResidueV25OrthoError(RuntimeError):
    """Fail-closed V2.5 model/input error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ResidueV25OrthoError(message)


def require_finite(value: Tensor, message: str) -> None:
    require(bool(torch.all(torch.isfinite(value))), message)


@dataclass(frozen=True)
class ResidueV25OrthoConfig:
    backbone_hidden_size: int
    target_node_dim: int
    edge_feature_dim: int = 26
    graph_hidden_dim: int = 128
    aa_embedding_dim: int = 16
    region_embedding_dim: int = 8
    aa_vocab_size: int = 21
    region_vocab_size: int = 5
    vhh_graph_layers: int = 3
    target_graph_layers: int = 2
    interaction_rank: int = 64
    dropout: float = 0.25
    attention_temperature_8x6b: float = 1.0
    attention_temperature_9e6y: float = 1.0
    pool_epsilon: float = 1e-6
    enable_contact_evidence: bool = True
    contact_encoder_gradient: Literal["shared", "detached"] = "detached"

    def validate(self) -> None:
        require(self.backbone_hidden_size > 0 and self.target_node_dim > 0, "input_dimension_invalid")
        require(self.edge_feature_dim > 0 and self.graph_hidden_dim > 0, "graph_dimension_invalid")
        require(self.aa_vocab_size >= 21 and self.region_vocab_size >= 5, "categorical_vocab_invalid")
        require(self.vhh_graph_layers == 3, "vhh_graph_layers_must_equal_3")
        require(self.target_graph_layers == 2, "target_graph_layers_must_equal_2")
        require(self.interaction_rank == 64, "interaction_rank_must_equal_64")
        require(0.0 <= self.dropout < 1.0, "dropout_invalid")
        require(self.attention_temperature_8x6b > 0.0, "attention_temperature_8x6b_invalid")
        require(self.attention_temperature_9e6y > 0.0, "attention_temperature_9e6y_invalid")
        require(self.pool_epsilon > 0.0, "epsilon_invalid")
        require(self.contact_encoder_gradient in {"shared", "detached"}, "contact_encoder_gradient_invalid")

    def attention_temperature(self, receptor: str) -> float:
        require(receptor in RECEPTOR_NAMES, f"receptor_invalid:{receptor}")
        return float(getattr(self, f"attention_temperature_{receptor}"))

    @classmethod
    def for_lane(cls, lane: str, **kwargs: Any) -> "ResidueV25OrthoConfig":
        require(lane in LANES, f"lane_invalid:{lane}")
        configured = cls(**kwargs)
        expected = lane == LANE_E
        if configured.enable_contact_evidence != expected:
            configured = replace(configured, enable_contact_evidence=expected)
        configured.validate()
        return configured


class InvariantMessagePassingLayer(nn.Module):
    def __init__(self, hidden_dim: int, edge_feature_dim: int, dropout: float) -> None:
        super().__init__()
        self.hidden_dim = hidden_dim
        self.edge_feature_dim = edge_feature_dim
        self.node_norm = nn.LayerNorm(hidden_dim)
        self.edge_projection = nn.Sequential(
            nn.LayerNorm(edge_feature_dim), nn.Linear(edge_feature_dim, hidden_dim), nn.GELU(),
        )
        self.message = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim), nn.GELU(), nn.Linear(hidden_dim, hidden_dim),
        )
        self.gate = nn.Sequential(nn.Linear(hidden_dim * 2, hidden_dim), nn.Sigmoid())
        self.update = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.output_norm = nn.LayerNorm(hidden_dim)

    def forward(self, node_states: Tensor, edge_index: Tensor, edge_features: Tensor) -> Tensor:
        require(node_states.ndim == 2 and node_states.shape[1] == self.hidden_dim, "node_states_shape_invalid")
        require(edge_index.ndim == 2 and edge_index.shape[0] == 2, "edge_index_shape_invalid")
        require(edge_features.shape == (edge_index.shape[1], self.edge_feature_dim), "edge_features_shape_invalid")
        require(edge_index.dtype == torch.long, "edge_index_dtype_invalid")
        require(edge_index.device == node_states.device == edge_features.device, "graph_device_mismatch")
        require(edge_index.shape[1] > 0, "graph_has_no_edges")
        require(int(edge_index.min()) >= 0 and int(edge_index.max()) < len(node_states), "edge_index_out_of_bounds")

        source, destination = edge_index
        normalized = self.node_norm(node_states)
        source_edge = torch.cat((normalized[source], self.edge_projection(edge_features)), dim=-1)
        messages = (self.message(source_edge) * self.gate(source_edge)).to(dtype=node_states.dtype)
        aggregate = torch.zeros_like(node_states)
        aggregate.index_add_(0, destination, messages)
        degree = torch.zeros((len(node_states), 1), dtype=node_states.dtype, device=node_states.device)
        degree.index_add_(
            0,
            destination,
            torch.ones((len(destination), 1), dtype=node_states.dtype, device=node_states.device),
        )
        aggregate = aggregate / degree.clamp_min(1.0)
        update = self.update(torch.cat((normalized, aggregate), dim=-1))
        return self.output_norm(node_states + update)


class InvariantGraphEncoder(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int, edge_feature_dim: int, layers: int, dropout: float) -> None:
        super().__init__()
        require(layers > 0, "graph_layers_invalid")
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.edge_feature_dim = edge_feature_dim
        self.input_projection = nn.Sequential(nn.LayerNorm(input_dim), nn.Linear(input_dim, hidden_dim), nn.GELU())
        self.layers = nn.ModuleList(
            InvariantMessagePassingLayer(hidden_dim, edge_feature_dim, dropout) for _ in range(layers)
        )

    def forward(self, node_features: Tensor, edge_index: Tensor, edge_features: Tensor) -> Tensor:
        require(node_features.ndim == 2 and node_features.shape[1] == self.input_dim, "graph_node_features_shape_invalid")
        states = self.input_projection(node_features)
        for layer in self.layers:
            states = layer(states, edge_index, edge_features)
        return states


def _unit_pair_logits(left: Tensor, right: Tensor, terminal: Tensor) -> Tensor:
    left_unit = F.normalize(left.float(), dim=-1, eps=1e-6).to(dtype=left.dtype)
    right_unit = F.normalize(right.float(), dim=-1, eps=1e-6).to(dtype=right.dtype)
    return torch.einsum("blr,tr,r->blt", left_unit, right_unit, terminal.to(dtype=left.dtype))


class OrthogonalAttentionInteraction(nn.Module):
    """Attention-only pair branch used by scalar R8/R9 prediction."""

    materializes_rank4_pair_tensor = False

    def __init__(self, hidden_dim: int, rank: int, dropout: float) -> None:
        super().__init__()
        self.hidden_dim = hidden_dim
        self.rank = rank
        self.vhh_left = nn.Linear(hidden_dim, rank, bias=False)
        self.target_right = nn.Linear(hidden_dim, rank, bias=False)
        self.terminal = nn.Parameter(torch.ones(rank))
        self.vhh_bias = nn.Linear(hidden_dim, 1, bias=False)
        self.target_bias = nn.Linear(hidden_dim, 1, bias=False)
        self.target_value = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.vhh_value = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.vhh_fusion = nn.Sequential(
            nn.LayerNorm(hidden_dim * 2), nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(), nn.Dropout(dropout), nn.Linear(hidden_dim, hidden_dim),
        )
        self.target_fusion = nn.Sequential(
            nn.LayerNorm(hidden_dim * 2), nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(), nn.Dropout(dropout), nn.Linear(hidden_dim, hidden_dim),
        )

    def forward(
        self,
        vhh_states: Tensor,
        residue_mask: Tensor,
        target_states: Tensor,
        *,
        temperature: float,
    ) -> dict[str, Tensor]:
        require(vhh_states.ndim == 3 and vhh_states.shape[-1] == self.hidden_dim, "vhh_states_shape_invalid")
        require(residue_mask.shape == vhh_states.shape[:2], "residue_mask_shape_invalid")
        require(target_states.ndim == 2 and target_states.shape[-1] == self.hidden_dim, "target_states_shape_invalid")
        require(temperature > 0.0 and bool(torch.all(residue_mask.sum(1) > 0)), "attention_input_invalid")

        logits = _unit_pair_logits(
            self.vhh_left(vhh_states), self.target_right(target_states), self.terminal,
        )
        logits = logits + self.vhh_bias(vhh_states) + self.target_bias(target_states).view(1, 1, -1)
        masked_logits = logits.masked_fill(~residue_mask.unsqueeze(-1), -1e4)
        scaled = masked_logits / float(temperature)

        target_given_vhh = torch.softmax(scaled, dim=-1)
        vhh_context = torch.einsum("blt,th->blh", target_given_vhh, self.target_value(target_states))
        conditioned_vhh = vhh_states + self.vhh_fusion(torch.cat((vhh_states, vhh_context), dim=-1))

        vhh_given_target = torch.softmax(scaled, dim=1)
        target_context = torch.einsum("blt,blh->bth", vhh_given_target, self.vhh_value(vhh_states))
        expanded_target = target_states.unsqueeze(0).expand(len(vhh_states), -1, -1)
        conditioned_target = expanded_target + self.target_fusion(
            torch.cat((expanded_target, target_context), dim=-1)
        )
        residue_attention = vhh_given_target.mean(dim=-1) * residue_mask.to(vhh_states.dtype)
        return {
            "attention_logits": masked_logits,
            "conditioned_vhh": conditioned_vhh,
            "conditioned_target": conditioned_target,
            "residue_attention": residue_attention,
        }


class OrthogonalContactInteraction(nn.Module):
    """Contact-only low-rank branch with no path into scalar geometry."""

    materializes_rank4_pair_tensor = False

    def __init__(self, hidden_dim: int, rank: int) -> None:
        super().__init__()
        self.hidden_dim = hidden_dim
        self.rank = rank
        self.vhh_left = nn.Linear(hidden_dim, rank, bias=False)
        self.target_right = nn.Linear(hidden_dim, rank, bias=False)
        self.terminal = nn.Parameter(torch.empty(rank))
        nn.init.normal_(self.terminal, mean=0.0, std=1.0)

    def forward(self, vhh_states: Tensor, residue_mask: Tensor, target_states: Tensor) -> Tensor:
        logits = _unit_pair_logits(
            self.vhh_left(vhh_states), self.target_right(target_states), self.terminal,
        )
        return logits.masked_fill(~residue_mask.unsqueeze(-1), -1e4)


class ReceptorContactBias(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.bias = nn.Parameter(torch.zeros(len(RECEPTOR_NAMES)))

    def forward(self, logits: Tensor, receptor_index: int) -> Tensor:
        require(receptor_index in range(len(RECEPTOR_NAMES)), "receptor_index_invalid")
        return logits + self.bias[receptor_index]


def _masked_mean(values: Tensor, mask: Tensor, dimensions: tuple[int, ...], epsilon: float) -> Tensor:
    weights = mask.to(values.dtype)
    return (values * weights).sum(dim=dimensions) / weights.sum(dim=dimensions).clamp_min(epsilon)


def summarize_pair_probabilities(
    pair_probabilities: Mapping[str, Tensor],
    residue_mask: Tensor,
    region_index: Tensor,
    target_graphs: Mapping[str, Mapping[str, Tensor]],
    *,
    epsilon: float,
) -> Tensor:
    summaries: list[Tensor] = []
    hotspot_masses: list[Tensor] = []
    for receptor in RECEPTOR_NAMES:
        probabilities = pair_probabilities[receptor]
        graph = target_graphs[receptor]
        interface_mask = graph["interface_mask"].to(dtype=torch.bool, device=probabilities.device)
        hotspot_mask = graph["hotspot_mask"].to(dtype=torch.bool, device=probabilities.device)
        require(
            interface_mask.shape == hotspot_mask.shape == (probabilities.shape[2],),
            f"target_mask_shape_invalid:{receptor}",
        )
        pair_mask = residue_mask.unsqueeze(-1).expand_as(probabilities)
        hotspot_pair_mask = pair_mask & hotspot_mask.view(1, 1, -1)
        interface_pair_mask = pair_mask & interface_mask.view(1, 1, -1)
        hotspot_mass = _masked_mean(probabilities, hotspot_pair_mask, (1, 2), epsilon)
        total_mass = (probabilities * pair_mask.to(probabilities.dtype)).sum((1, 2)).clamp_min(epsilon)
        interface_mass = (probabilities * interface_pair_mask.to(probabilities.dtype)).sum((1, 2))
        interface_specificity = interface_mass / total_mass
        cdr_masses = []
        for region in (1, 2, 3):
            region_mask = pair_mask & (region_index == region).unsqueeze(-1)
            cdr_masses.append(_masked_mean(probabilities, region_mask, (1, 2), epsilon))

        # Endpoint-sensitive entropy is always reduced in FP32 for BF16 safety.
        clipped = probabilities.float().clamp(min=epsilon, max=1.0 - epsilon)
        entropy_values = -(clipped * clipped.log() + (1.0 - clipped) * (1.0 - clipped).log())
        entropy = _masked_mean(entropy_values, pair_mask, (1, 2), epsilon)
        summaries.extend((hotspot_mass, interface_specificity, *cdr_masses, entropy))
        hotspot_masses.append(hotspot_mass)
    hotspot_stack = torch.stack(hotspot_masses, dim=-1)
    summaries.append(hotspot_stack.min(dim=-1).values)
    summaries.append((hotspot_stack[:, 0] - hotspot_stack[:, 1]).abs())
    result = torch.stack(summaries, dim=-1)
    require_finite(result, "pair_summary_nonfinite")
    return result


def contact_composite(pair_summary: Tensor) -> Tensor:
    """Frozen label-free two-receptor contact evidence from the 14D summary."""
    require(pair_summary.ndim == 2 and pair_summary.shape[1] == 14, "pair_summary_shape_invalid")
    result = torch.stack(
        (
            0.5 * (pair_summary[:, 0] + pair_summary[:, 1]),
            0.5 * (pair_summary[:, 6] + pair_summary[:, 7]),
        ),
        dim=-1,
    )
    require_finite(result, "contact_composite_nonfinite")
    return result


def stable_softmin(left: Tensor, right: Tensor, tau: float) -> Tensor:
    """Normalised smooth minimum, evaluated in FP32 for BF16 safety."""
    require(left.shape == right.shape, "softmin_shape_invalid")
    require(math.isfinite(tau) and tau > 0.0, "softmin_tau_invalid")
    values = torch.stack((left.float(), right.float()), dim=-1)
    result = -float(tau) * torch.logsumexp(-values / float(tau), dim=-1) + float(tau) * math.log(2.0)
    require_finite(result, "softmin_nonfinite")
    return result


def exact_min_dual(receptor_predictions: Tensor) -> Tensor:
    require(
        receptor_predictions.ndim == 2 and receptor_predictions.shape[1] == 2,
        "receptor_prediction_shape_invalid",
    )
    result = torch.minimum(receptor_predictions[:, 0], receptor_predictions[:, 1])
    require_finite(result, "exact_min_dual_nonfinite")
    return result


class OrthogonalTargetHead(nn.Module):
    """Attention scalar head plus optional, non-feedback contact evidence."""

    def __init__(self, config: ResidueV25OrthoConfig) -> None:
        super().__init__()
        config.validate()
        self.config = config
        hidden = config.graph_hidden_dim
        self.aa_embedding = nn.Embedding(config.aa_vocab_size, config.aa_embedding_dim)
        self.region_embedding = nn.Embedding(config.region_vocab_size, config.region_embedding_dim)
        vhh_input_dim = config.backbone_hidden_size + config.aa_embedding_dim + config.region_embedding_dim + 1
        self.vhh_graph_encoder = InvariantGraphEncoder(
            vhh_input_dim, hidden, config.edge_feature_dim, config.vhh_graph_layers, config.dropout,
        )
        self.target_graph_encoder = InvariantGraphEncoder(
            config.target_node_dim, hidden, config.edge_feature_dim, config.target_graph_layers, config.dropout,
        )
        self.conformer_embedding = nn.Embedding(len(RECEPTOR_NAMES), hidden)
        self.attention_interaction = OrthogonalAttentionInteraction(
            hidden, config.interaction_rank, config.dropout,
        )
        self.condition_fusion = nn.Sequential(
            nn.LayerNorm(hidden * 3), nn.Linear(hidden * 3, hidden), nn.GELU(), nn.Dropout(config.dropout),
        )
        # global + one attention-only routed pool per receptor.
        self.scalar_head = nn.Sequential(
            nn.LayerNorm(hidden * 3), nn.Linear(hidden * 3, hidden), nn.GELU(),
            nn.Dropout(config.dropout), nn.Linear(hidden, len(DIRECT_TARGET_NAMES)),
        )
        if config.enable_contact_evidence:
            self.contact_interaction: OrthogonalContactInteraction | None = OrthogonalContactInteraction(
                hidden, config.interaction_rank,
            )
            self.contact_calibration: ReceptorContactBias | None = ReceptorContactBias()
        else:
            self.contact_interaction = None
            self.contact_calibration = None

    def _encode_targets(
        self,
        target_graphs: Mapping[str, Mapping[str, Tensor]],
        device: torch.device,
    ) -> dict[str, Tensor]:
        require(set(target_graphs) == set(RECEPTOR_NAMES), "target_conformer_set_invalid")
        encoded: dict[str, Tensor] = {}
        for conformer_index, receptor in enumerate(RECEPTOR_NAMES):
            graph = target_graphs[receptor]
            required = {"node_features", "edge_index", "edge_features", "interface_mask", "hotspot_mask"}
            require(required <= set(graph), f"target_graph_fields_missing:{receptor}")
            states = self.target_graph_encoder(
                graph["node_features"].to(device=device),
                graph["edge_index"].to(device=device, dtype=torch.long),
                graph["edge_features"].to(device=device),
            )
            encoded[receptor] = states + self.conformer_embedding.weight[conformer_index].view(1, -1)
        return encoded

    def forward(
        self,
        token_states: Tensor,
        residue_mask: Tensor,
        vhh_aa_index: Tensor,
        vhh_region_index: Tensor,
        vhh_confidence: Tensor,
        vhh_edge_index: Tensor,
        vhh_edge_features: Tensor,
        target_graphs: Mapping[str, Mapping[str, Tensor]],
    ) -> dict[str, Tensor]:
        require(token_states.ndim == 3, "token_states_shape_invalid")
        batch, length, _ = token_states.shape
        require(
            residue_mask.shape == vhh_aa_index.shape == vhh_region_index.shape == (batch, length),
            "vhh_index_shape_invalid",
        )
        if vhh_confidence.ndim == 2:
            vhh_confidence = vhh_confidence.unsqueeze(-1)
        require(vhh_confidence.shape == (batch, length, 1), "vhh_confidence_shape_invalid")
        require(bool(torch.all(residue_mask.sum(1) > 0)), "empty_residue_mask")
        require(vhh_edge_index.dtype == torch.long and vhh_edge_index.ndim == 2, "vhh_edge_index_invalid")
        flat_valid = residue_mask.reshape(-1)
        require(bool(torch.all(flat_valid[vhh_edge_index.reshape(-1)])), "vhh_edge_touches_padding")

        vhh_features = torch.cat(
            (
                token_states,
                self.aa_embedding(vhh_aa_index),
                self.region_embedding(vhh_region_index),
                vhh_confidence.to(token_states.dtype),
            ),
            dim=-1,
        )
        flat_states = self.vhh_graph_encoder(
            vhh_features.reshape(batch * length, -1), vhh_edge_index, vhh_edge_features,
        )
        vhh_states = flat_states.reshape(batch, length, -1)
        encoded_targets = self._encode_targets(target_graphs, token_states.device)

        attention: dict[str, dict[str, Tensor]] = {}
        for receptor in RECEPTOR_NAMES:
            attention[receptor] = self.attention_interaction(
                vhh_states,
                residue_mask,
                encoded_targets[receptor],
                temperature=self.config.attention_temperature(receptor),
            )

        combined_states = self.condition_fusion(
            torch.cat(
                (
                    vhh_states,
                    attention["8x6b"]["conditioned_vhh"],
                    attention["9e6y"]["conditioned_vhh"],
                ),
                dim=-1,
            )
        )
        residue_weights = residue_mask.to(combined_states.dtype).unsqueeze(-1)
        global_pool = (combined_states * residue_weights).sum(1) / residue_weights.sum(1).clamp_min(1.0)
        receptor_pools = []
        for receptor in RECEPTOR_NAMES:
            weights = attention[receptor]["residue_attention"]
            vhh_pool = (combined_states * weights.unsqueeze(-1)).sum(1) / weights.sum(1, keepdim=True).clamp_min(
                self.config.pool_epsilon
            )
            target_feedback = attention[receptor]["conditioned_target"].mean(1)
            receptor_pools.append(vhh_pool + target_feedback)

        # Critical firewall: this concatenation contains no contact logits,
        # probabilities, summaries, or contact-derived pooling weights.
        receptor_predictions = self.scalar_head(
            torch.cat((global_pool, receptor_pools[0], receptor_pools[1]), dim=-1)
        )
        dual = exact_min_dual(receptor_predictions)
        prediction = torch.cat((receptor_predictions, dual.unsqueeze(-1)), dim=-1)
        require_finite(prediction, "prediction_nonfinite")

        result: dict[str, Tensor] = {
            "receptor_predictions": receptor_predictions,
            "exact_min_dual": dual,
            "prediction": prediction,
            "attention_logits_8x6b": attention["8x6b"]["attention_logits"],
            "attention_logits_9e6y": attention["9e6y"]["attention_logits"],
            "vhh_graph_states": vhh_states,
            "target_states_8x6b": encoded_targets["8x6b"],
            "target_states_9e6y": encoded_targets["9e6y"],
        }

        if self.contact_interaction is not None and self.contact_calibration is not None:
            if self.config.contact_encoder_gradient == "detached":
                contact_vhh = vhh_states.detach()
                contact_targets = {name: value.detach() for name, value in encoded_targets.items()}
            else:
                contact_vhh = vhh_states
                contact_targets = encoded_targets
            contact_logits: dict[str, Tensor] = {}
            for receptor_index, receptor in enumerate(RECEPTOR_NAMES):
                raw = self.contact_interaction(contact_vhh, residue_mask, contact_targets[receptor])
                contact_logits[receptor] = self.contact_calibration(raw, receptor_index).masked_fill(
                    ~residue_mask.unsqueeze(-1), -1e4
                )
            marginal_logits = torch.stack(
                [
                    torch.logsumexp(contact_logits[receptor], dim=-1)
                    - math.log(contact_logits[receptor].shape[-1])
                    for receptor in RECEPTOR_NAMES
                ],
                dim=-1,
            )
            marginal_probabilities = torch.sigmoid(marginal_logits) * residue_mask.unsqueeze(-1).to(
                token_states.dtype
            )
            contact_probabilities = {name: torch.sigmoid(value) for name, value in contact_logits.items()}
            pair_summary = summarize_pair_probabilities(
                contact_probabilities,
                residue_mask,
                vhh_region_index,
                target_graphs,
                epsilon=self.config.pool_epsilon,
            )
            result.update(
                {
                    "marginal_contact_logits": marginal_logits,
                    "marginal_contact_probabilities": marginal_probabilities,
                    "contact_logits_8x6b": contact_logits["8x6b"],
                    "contact_logits_9e6y": contact_logits["9e6y"],
                    "contact_probabilities_8x6b": contact_probabilities["8x6b"],
                    "contact_probabilities_9e6y": contact_probabilities["9e6y"],
                    "pair_summary": pair_summary,
                    "contact_composite": contact_composite(pair_summary),
                    "contact_biases": self.contact_calibration.bias,
                }
            )
        return result


def backbone_states(backbone: nn.Module, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
    output = backbone(input_ids=input_ids, attention_mask=attention_mask)
    states = output.get("last_hidden_state") if isinstance(output, Mapping) else getattr(output, "last_hidden_state", None)
    require(isinstance(states, Tensor), "backbone_missing_last_hidden_state")
    require(states.shape[:2] == input_ids.shape, "backbone_state_shape_invalid")
    return states


class OrthogonalResidueSurrogate(nn.Module):
    def __init__(self, backbone: nn.Module, head: OrthogonalTargetHead) -> None:
        super().__init__()
        self.backbone = backbone
        self.head = head
        for parameter in self.backbone.parameters():
            parameter.requires_grad_(False)

    def forward(
        self,
        input_ids: Tensor,
        attention_mask: Tensor,
        residue_mask: Tensor,
        vhh_aa_index: Tensor,
        vhh_region_index: Tensor,
        vhh_confidence: Tensor,
        vhh_edge_index: Tensor,
        vhh_edge_features: Tensor,
        target_graphs: Mapping[str, Mapping[str, Tensor]],
    ) -> dict[str, Tensor]:
        self.backbone.eval()
        with torch.no_grad():
            states = backbone_states(self.backbone, input_ids, attention_mask)
        return self.head(
            states,
            residue_mask,
            vhh_aa_index,
            vhh_region_index,
            vhh_confidence,
            vhh_edge_index,
            vhh_edge_features,
            target_graphs,
        )


def model_contract(config: ResidueV25OrthoConfig, lane: str) -> dict[str, Any]:
    config.validate()
    require(lane in LANES, f"lane_invalid:{lane}")
    require(config.enable_contact_evidence == (lane == LANE_E), "lane_contact_configuration_mismatch")
    target_fields = tuple(inspect.signature(OrthogonalTargetHead.forward).parameters)
    wrapper_fields = tuple(inspect.signature(OrthogonalResidueSurrogate.forward).parameters)
    forbidden = (
        "m2_base", "m2_outputs", "structure", "structure_features", "candidate_id",
        "candidate_ids", "parent_id", "parent_framework_cluster", "campaign_id",
        "docking_pose", "pose_features", "teacher_source",
    )
    for field in forbidden:
        require(field not in target_fields and field not in wrapper_fields, f"forbidden_forward_feature:{field}")
    return {
        "schema_version": "pvrig_v2_5_ortho_contact_pose_stack_model_v1",
        "lane": lane,
        "claim_boundary": CLAIM_BOUNDARY,
        "config": asdict(config),
        "direct_targets": list(DIRECT_TARGET_NAMES),
        "derived_target": {DERIVED_TARGET_NAME: "exact_min(R_8X6B,R_9E6Y)"},
        "scalar_path": "shared_encoders -> attention_only_pair_branch -> attention_routed_pools -> R8/R9",
        "contact_path": (
            "disabled" if lane == LANE_B else
            f"separate_pair_projections_and_terminal; encoder_gradient={config.contact_encoder_gradient}"
        ),
        "contact_feedback_to_scalar": False,
        "attention_contact_pair_projections_shared": False,
        "rank4_pair_tensor_materialized": False,
        "forbidden_neural_inputs": list(forbidden),
    }

