#!/usr/bin/env python3
"""Feature-separated V2.4 residue model prototype.

This module intentionally contains no M2 prediction or 126-dimensional
aggregate structure-feature input.  It predicts the two receptor scores
directly and derives the dual score by an exact minimum.
"""

from __future__ import annotations

import inspect
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

import torch
from torch import Tensor, nn
from torch.nn import functional as F


RECEPTOR_NAMES = ("8x6b", "9e6y")
DIRECT_TARGET_NAMES = ("R_8X6B", "R_9E6Y")
DERIVED_TARGET_NAME = "R_dual_min"
CLAIM_BOUNDARY = (
    "Sequence and label-free monomer-graph approximation of independent "
    "dual-receptor computational Docking geometry; not binding probability, "
    "affinity, experimental blocking, Docking Gold, or submission evidence."
)


class ResidueV24ModelError(RuntimeError):
    """Fail-closed model or input contract error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ResidueV24ModelError(message)


def require_finite(value: Tensor, message: str) -> None:
    require(bool(torch.all(torch.isfinite(value))), message)


@dataclass(frozen=True)
class ResidueV24Config:
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

    def attention_temperature(self, receptor: str) -> float:
        require(receptor in RECEPTOR_NAMES, f"receptor_invalid:{receptor}")
        return float(getattr(self, f"attention_temperature_{receptor}"))


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


class SplitLowRankPairInteraction(nn.Module):
    """Implicit rank-64 pair representation with independent terminal heads.

    The two scalar projections are evaluated with weighted einsums.  No
    ``B x L x T x rank`` tensor is materialized.
    """

    materializes_rank4_pair_tensor = False

    def __init__(self, hidden_dim: int, rank: int, dropout: float) -> None:
        super().__init__()
        self.hidden_dim = hidden_dim
        self.rank = rank
        self.vhh_left = nn.Linear(hidden_dim, rank, bias=False)
        self.target_right = nn.Linear(hidden_dim, rank, bias=False)

        self.attention_terminal = nn.Parameter(torch.ones(rank))
        self.contact_terminal = nn.Parameter(torch.empty(rank))
        # Unit-normalised left/right factors make terminal norm the single,
        # identifiable per-head gain. std=1 gives O(1/sqrt(rank)) initial logits.
        nn.init.normal_(self.contact_terminal, mean=0.0, std=1.0)
        self.attention_vhh_bias = nn.Linear(hidden_dim, 1, bias=False)
        self.attention_target_bias = nn.Linear(hidden_dim, 1, bias=False)

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

    def _terminal_logits(
        self,
        left: Tensor,
        right: Tensor,
        terminal: Tensor,
        vhh_bias: nn.Linear | None,
        target_bias: nn.Linear | None,
        vhh_states: Tensor,
        target_states: Tensor,
    ) -> Tensor:
        # Unit-normalised left/right factors remove their arbitrary scale.
        # Terminal direction and norm remain trainable; terminal norm is now the
        # single identifiable per-head gain. Contact receives no local bias
        # because receptor-specific bias is the sole contact intercept.
        left_unit = F.normalize(left.float(), dim=-1, eps=1e-6).to(dtype=left.dtype)
        right_unit = F.normalize(right.float(), dim=-1, eps=1e-6).to(dtype=right.dtype)
        logits = torch.einsum("blr,tr,r->blt", left_unit, right_unit, terminal.to(dtype=left.dtype))
        if vhh_bias is not None:
            logits = logits + vhh_bias(vhh_states)
        if target_bias is not None:
            logits = logits + target_bias(target_states).view(1, 1, -1)
        return logits

    def forward(
        self,
        vhh_states: Tensor,
        residue_mask: Tensor,
        target_states: Tensor,
        *,
        attention_temperature: float,
    ) -> dict[str, Tensor]:
        require(vhh_states.ndim == 3 and vhh_states.shape[-1] == self.hidden_dim, "vhh_states_shape_invalid")
        require(residue_mask.shape == vhh_states.shape[:2], "residue_mask_shape_invalid")
        require(target_states.ndim == 2 and target_states.shape[-1] == self.hidden_dim, "target_states_shape_invalid")
        require(len(target_states) > 0 and attention_temperature > 0.0, "target_or_temperature_invalid")
        require(bool(torch.all(residue_mask.sum(dim=1) > 0)), "empty_residue_mask")

        left = self.vhh_left(vhh_states)
        right = self.target_right(target_states)
        attention_logits = self._terminal_logits(
            left, right, self.attention_terminal,
            self.attention_vhh_bias, self.attention_target_bias,
            vhh_states, target_states,
        )
        contact_logits = self._terminal_logits(
            left, right, self.contact_terminal,
            None, None,
            vhh_states, target_states,
        )

        masked_attention = attention_logits.masked_fill(~residue_mask.unsqueeze(-1), -1e4)
        scaled_attention = masked_attention / attention_temperature
        vhh_attention = torch.softmax(scaled_attention, dim=-1)
        vhh_context = torch.einsum("blt,th->blh", vhh_attention, self.target_value(target_states))
        conditioned_vhh = vhh_states + self.vhh_fusion(torch.cat((vhh_states, vhh_context), dim=-1))

        target_attention = torch.softmax(scaled_attention, dim=1)
        target_context = torch.einsum("blt,blh->bth", target_attention, self.vhh_value(vhh_states))
        expanded_target = target_states.unsqueeze(0).expand(len(vhh_states), -1, -1)
        conditioned_target = expanded_target + self.target_fusion(
            torch.cat((expanded_target, target_context), dim=-1)
        )
        contact_logits = contact_logits.masked_fill(~residue_mask.unsqueeze(-1), -1e4)
        return {
            "attention_logits": masked_attention,
            "contact_raw_logits": contact_logits,
            "conditioned_vhh": conditioned_vhh,
            "conditioned_target": conditioned_target,
        }


class ReceptorContactBias(nn.Module):
    """Identifiable receptor calibration with a fixed non-trainable scale of one."""

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
        require(interface_mask.shape == hotspot_mask.shape == (probabilities.shape[2],), f"target_mask_shape_invalid:{receptor}")
        pair_mask = residue_mask.unsqueeze(-1).expand_as(probabilities)
        hotspot_pair_mask = pair_mask & hotspot_mask.view(1, 1, -1)
        interface_pair_mask = pair_mask & interface_mask.view(1, 1, -1)
        hotspot_mass = _masked_mean(probabilities, hotspot_pair_mask, (1, 2), epsilon)
        total_mass = (probabilities * pair_mask.to(probabilities.dtype)).sum(dim=(1, 2)).clamp_min(epsilon)
        interface_mass = (probabilities * interface_pair_mask.to(probabilities.dtype)).sum(dim=(1, 2))
        interface_specificity = interface_mass / total_mass
        cdr_masses = []
        for region in (1, 2, 3):
            region_mask = pair_mask & (region_index == region).unsqueeze(-1)
            cdr_masses.append(_masked_mean(probabilities, region_mask, (1, 2), epsilon))

        # Preserve the V2.3 technical-numerics repair: BF16 cannot represent
        # 1-1e-6, so endpoint-sensitive entropy is reduced in FP32.
        clipped = probabilities.float().clamp(min=epsilon, max=1.0 - epsilon)
        binary_entropy = -(clipped * clipped.log() + (1.0 - clipped) * (1.0 - clipped).log())
        entropy = _masked_mean(binary_entropy, pair_mask, (1, 2), epsilon)
        summaries.extend((hotspot_mass, interface_specificity, *cdr_masses, entropy))
        hotspot_masses.append(hotspot_mass)
    hotspot_stack = torch.stack(hotspot_masses, dim=-1)
    summaries.append(hotspot_stack.min(dim=-1).values)
    summaries.append((hotspot_stack[:, 0] - hotspot_stack[:, 1]).abs())
    result = torch.stack(summaries, dim=-1)
    require_finite(result, "pair_summary_nonfinite")
    return result


def stable_softmin(left: Tensor, right: Tensor, tau: float) -> Tensor:
    """Unnormalised smooth minimum, evaluated in FP32 for BF16 safety."""
    require(left.shape == right.shape, "softmin_shape_invalid")
    require(math.isfinite(tau) and tau > 0.0, "softmin_tau_invalid")
    values = torch.stack((left.float(), right.float()), dim=-1)
    result = -float(tau) * torch.logsumexp(-values / float(tau), dim=-1)
    require_finite(result, "softmin_nonfinite")
    return result


def exact_min_dual(receptor_predictions: Tensor) -> Tensor:
    require(receptor_predictions.ndim == 2 and receptor_predictions.shape[1] == 2, "receptor_prediction_shape_invalid")
    result = torch.minimum(receptor_predictions[:, 0], receptor_predictions[:, 1])
    require_finite(result, "exact_min_dual_nonfinite")
    return result


class FeatureSeparatedTargetHead(nn.Module):
    """M2-free target-conditioned head with split attention/contact terminals."""

    def __init__(self, config: ResidueV24Config) -> None:
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
        self.interaction = SplitLowRankPairInteraction(hidden, config.interaction_rank, config.dropout)
        self.contact_calibration = ReceptorContactBias()
        self.condition_fusion = nn.Sequential(
            nn.LayerNorm(hidden * 3), nn.Linear(hidden * 3, hidden), nn.GELU(), nn.Dropout(config.dropout),
        )
        self.pair_summary_dim = 14
        self.pair_summary_projection = nn.Sequential(
            nn.LayerNorm(self.pair_summary_dim), nn.Linear(self.pair_summary_dim, hidden), nn.GELU(),
        )
        # global + one routed pool per receptor + contact summary.
        self.scalar_head = nn.Sequential(
            nn.LayerNorm(hidden * 4), nn.Linear(hidden * 4, hidden), nn.GELU(),
            nn.Dropout(config.dropout), nn.Linear(hidden, len(DIRECT_TARGET_NAMES)),
        )

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
        require(residue_mask.shape == vhh_aa_index.shape == vhh_region_index.shape == (batch, length), "vhh_index_shape_invalid")
        if vhh_confidence.ndim == 2:
            vhh_confidence = vhh_confidence.unsqueeze(-1)
        require(vhh_confidence.shape == (batch, length, 1), "vhh_confidence_shape_invalid")
        require(bool(torch.all(residue_mask.sum(dim=1) > 0)), "empty_residue_mask")
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

        interactions: dict[str, dict[str, Tensor]] = {}
        contact_logits: dict[str, Tensor] = {}
        for receptor_index, receptor in enumerate(RECEPTOR_NAMES):
            interaction = self.interaction(
                vhh_states,
                residue_mask,
                encoded_targets[receptor],
                attention_temperature=self.config.attention_temperature(receptor),
            )
            interactions[receptor] = interaction
            contact_logits[receptor] = self.contact_calibration(
                interaction["contact_raw_logits"], receptor_index,
            ).masked_fill(~residue_mask.unsqueeze(-1), -1e4)

        combined_states = self.condition_fusion(
            torch.cat(
                (
                    vhh_states,
                    interactions["8x6b"]["conditioned_vhh"],
                    interactions["9e6y"]["conditioned_vhh"],
                ),
                dim=-1,
            )
        )
        residue_weights = residue_mask.to(combined_states.dtype).unsqueeze(-1)
        global_pool = (combined_states * residue_weights).sum(1) / residue_weights.sum(1).clamp_min(1.0)

        marginal_logits = torch.stack(
            [
                torch.logsumexp(contact_logits[receptor], dim=-1)
                - math.log(contact_logits[receptor].shape[-1])
                for receptor in RECEPTOR_NAMES
            ],
            dim=-1,
        )
        marginal_probabilities = torch.sigmoid(marginal_logits) * residue_mask.unsqueeze(-1).to(token_states.dtype)
        receptor_pools = []
        for channel, receptor in enumerate(RECEPTOR_NAMES):
            weights = marginal_probabilities[:, :, channel]
            vhh_pool = (combined_states * weights.unsqueeze(-1)).sum(1) / weights.sum(1, keepdim=True).clamp_min(
                self.config.pool_epsilon
            )
            target_feedback = interactions[receptor]["conditioned_target"].mean(1)
            receptor_pools.append(vhh_pool + target_feedback)

        contact_probabilities = {name: torch.sigmoid(value) for name, value in contact_logits.items()}
        pair_summary = summarize_pair_probabilities(
            contact_probabilities,
            residue_mask,
            vhh_region_index,
            target_graphs,
            epsilon=self.config.pool_epsilon,
        )
        pair_summary_state = self.pair_summary_projection(pair_summary)
        receptor_predictions = self.scalar_head(
            torch.cat((global_pool, receptor_pools[0], receptor_pools[1], pair_summary_state), dim=-1)
        )
        dual = exact_min_dual(receptor_predictions)
        prediction = torch.cat((receptor_predictions, dual.unsqueeze(-1)), dim=-1)
        require_finite(prediction, "prediction_nonfinite")

        return {
            "receptor_predictions": receptor_predictions,
            "exact_min_dual": dual,
            "prediction": prediction,
            "marginal_contact_logits": marginal_logits,
            "marginal_contact_probabilities": marginal_probabilities,
            "attention_logits_8x6b": interactions["8x6b"]["attention_logits"],
            "attention_logits_9e6y": interactions["9e6y"]["attention_logits"],
            "contact_logits_8x6b": contact_logits["8x6b"],
            "contact_logits_9e6y": contact_logits["9e6y"],
            "contact_probabilities_8x6b": contact_probabilities["8x6b"],
            "contact_probabilities_9e6y": contact_probabilities["9e6y"],
            "pair_summary": pair_summary,
            "vhh_graph_states": vhh_states,
            "target_states_8x6b": encoded_targets["8x6b"],
            "target_states_9e6y": encoded_targets["9e6y"],
            "contact_biases": self.contact_calibration.bias,
        }


def backbone_states(backbone: nn.Module, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
    output = backbone(input_ids=input_ids, attention_mask=attention_mask)
    states = output.get("last_hidden_state") if isinstance(output, Mapping) else getattr(output, "last_hidden_state", None)
    require(isinstance(states, Tensor), "backbone_missing_last_hidden_state")
    require(states.shape[:2] == input_ids.shape, "backbone_state_shape_invalid")
    return states


class FeatureSeparatedResidueSurrogate(nn.Module):
    def __init__(self, backbone: nn.Module, head: FeatureSeparatedTargetHead) -> None:
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


class M2FreeVHHOnlyHead(nn.Module):
    """Capacity-matched VHH-only baseline without target, M2, or 126D inputs."""

    def __init__(self, config: ResidueV24Config) -> None:
        super().__init__()
        config.validate()
        self.config = config
        hidden = config.graph_hidden_dim
        self.aa_embedding = nn.Embedding(config.aa_vocab_size, config.aa_embedding_dim)
        self.region_embedding = nn.Embedding(config.region_vocab_size, config.region_embedding_dim)
        input_dim = config.backbone_hidden_size + config.aa_embedding_dim + config.region_embedding_dim + 1
        self.vhh_graph_encoder = InvariantGraphEncoder(
            input_dim, hidden, config.edge_feature_dim, config.vhh_graph_layers, config.dropout,
        )
        self.receptor_pool_logits = nn.Linear(hidden, len(RECEPTOR_NAMES))
        self.scalar_head = nn.Sequential(
            nn.LayerNorm(hidden * 3), nn.Linear(hidden * 3, hidden), nn.GELU(),
            nn.Dropout(config.dropout), nn.Linear(hidden, len(DIRECT_TARGET_NAMES)),
        )

    def forward(
        self,
        token_states: Tensor,
        residue_mask: Tensor,
        vhh_aa_index: Tensor,
        vhh_region_index: Tensor,
        vhh_confidence: Tensor,
        vhh_edge_index: Tensor,
        vhh_edge_features: Tensor,
    ) -> dict[str, Tensor]:
        batch, length, _ = token_states.shape
        if vhh_confidence.ndim == 2:
            vhh_confidence = vhh_confidence.unsqueeze(-1)
        features = torch.cat(
            (
                token_states,
                self.aa_embedding(vhh_aa_index),
                self.region_embedding(vhh_region_index),
                vhh_confidence.to(token_states.dtype),
            ),
            dim=-1,
        )
        states = self.vhh_graph_encoder(
            features.reshape(batch * length, -1), vhh_edge_index, vhh_edge_features,
        ).reshape(batch, length, -1)
        mask = residue_mask.to(states.dtype).unsqueeze(-1)
        global_pool = (states * mask).sum(1) / mask.sum(1).clamp_min(1.0)
        logits = self.receptor_pool_logits(states)
        probabilities = torch.sigmoid(logits) * residue_mask.unsqueeze(-1).to(states.dtype)
        pools = []
        for channel in range(len(RECEPTOR_NAMES)):
            weights = probabilities[:, :, channel]
            pools.append(
                (states * weights.unsqueeze(-1)).sum(1)
                / weights.sum(1, keepdim=True).clamp_min(self.config.pool_epsilon)
            )
        receptor_predictions = self.scalar_head(torch.cat((global_pool, pools[0], pools[1]), dim=-1))
        dual = exact_min_dual(receptor_predictions)
        prediction = torch.cat((receptor_predictions, dual.unsqueeze(-1)), dim=-1)
        require_finite(prediction, "vhh_only_prediction_nonfinite")
        return {
            "receptor_predictions": receptor_predictions,
            "exact_min_dual": dual,
            "prediction": prediction,
            "marginal_contact_logits": logits,
            "marginal_contact_probabilities": probabilities,
        }


class M2FreeVHHOnlySurrogate(nn.Module):
    def __init__(self, backbone: nn.Module, head: M2FreeVHHOnlyHead) -> None:
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
        )


def model_contract(config: ResidueV24Config) -> dict[str, Any]:
    config.validate()
    target_fields = tuple(inspect.signature(FeatureSeparatedTargetHead.forward).parameters)
    wrapper_fields = tuple(inspect.signature(FeatureSeparatedResidueSurrogate.forward).parameters)
    for forbidden in ("m2_base", "structure_features", "structure", "teacher_source"):
        require(forbidden not in target_fields and forbidden not in wrapper_fields, f"forbidden_forward_feature:{forbidden}")
    return {
        "schema_version": "pvrig_v6_feature_separated_residue_model_v2_4_prototype",
        "claim_boundary": CLAIM_BOUNDARY,
        "config": asdict(config),
        "direct_targets": list(DIRECT_TARGET_NAMES),
        "derived_target": {DERIVED_TARGET_NAME: "exact_min(R_8X6B,R_9E6Y)"},
        "interaction": "implicit_rank64_shared_pair_factors_split_attention_contact_terminals",
        "low_rank_identifiability": "unit_normalized_left_right_with_terminal_norm_as_per_head_gain",
        "contact_calibration": "fixed_scale_1_plus_receptor_specific_bias",
        "rank4_pair_tensor_materialized": False,
        "forbidden_neural_inputs": [
            "M2 outputs", "126D M2 aggregate vector", "teacher_source", "candidate_docking_pose",
        ],
    }
