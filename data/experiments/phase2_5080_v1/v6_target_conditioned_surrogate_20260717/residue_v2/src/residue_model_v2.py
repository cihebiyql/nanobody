#!/usr/bin/env python3
"""Rigid-invariant VHH/PVRIG residue-graph model for Residue V2.

The model consumes frozen sequence states, label-free monomer graph features,
and two fixed PVRIG conformer graphs.  It never accepts ``teacher_source`` or
candidate Docking coordinates as model features.  Predictions are an explicit
cross-fit M2 baseline plus a bounded 0.02 residual.
"""

from __future__ import annotations

import inspect
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

import torch
from torch import Tensor, nn


TARGET_NAMES = ("R_8X6B", "R_9E6Y", "R_dual_min")
RECEPTOR_NAMES = ("8x6b", "9e6y")
CLAIM_BOUNDARY = (
    "Sequence and label-free monomer structure approximation of independent "
    "dual-receptor computational Docking geometry; not binding probability, "
    "affinity, experimental blocking, Docking Gold, or submission evidence."
)


class ResidueV2ModelError(RuntimeError):
    """Fail-closed model/input error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ResidueV2ModelError(message)


@dataclass(frozen=True)
class ResidueV2Config:
    backbone_hidden_size: int
    target_node_dim: int
    structure_dim: int = 126
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
    residual_scale: float = 0.02
    pool_epsilon: float = 1e-6

    def validate(self) -> None:
        require(self.backbone_hidden_size > 0, "backbone_hidden_size_invalid")
        require(self.target_node_dim > 0 and self.structure_dim > 0, "input_dimension_invalid")
        require(self.edge_feature_dim > 0 and self.graph_hidden_dim > 0, "graph_dimension_invalid")
        require(self.aa_vocab_size >= 21 and self.region_vocab_size >= 5, "categorical_vocab_invalid")
        require(self.vhh_graph_layers == 3, "vhh_graph_layers_must_equal_preregistered_3")
        require(self.target_graph_layers == 2, "target_graph_layers_must_equal_preregistered_2")
        require(self.interaction_rank == 64, "interaction_rank_must_equal_preregistered_64")
        require(abs(self.residual_scale - 0.02) < 1e-12, "residual_scale_must_equal_preregistered_0_02")
        require(0.0 <= self.dropout < 1.0, "dropout_invalid")
        require(self.pool_epsilon > 0.0, "pool_epsilon_invalid")


class InvariantMessagePassingLayer(nn.Module):
    """Message passing over precomputed invariant edge features."""

    def __init__(self, hidden_dim: int, edge_feature_dim: int, dropout: float) -> None:
        super().__init__()
        self.hidden_dim = hidden_dim
        self.edge_feature_dim = edge_feature_dim
        self.node_norm = nn.LayerNorm(hidden_dim)
        self.edge_projection = nn.Sequential(
            nn.LayerNorm(edge_feature_dim),
            nn.Linear(edge_feature_dim, hidden_dim),
            nn.GELU(),
        )
        self.message = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.gate = nn.Sequential(nn.Linear(hidden_dim * 2, hidden_dim), nn.Sigmoid())
        self.update = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
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
        edge_state = self.edge_projection(edge_features)
        source_edge = torch.cat((normalized[source], edge_state), dim=-1)
        messages = self.message(source_edge) * self.gate(source_edge)
        # Under autocast the message path can be bf16 while the residual node
        # state remains fp32. index_add_ requires an exact dtype match.
        messages = messages.to(dtype=node_states.dtype)
        aggregate = torch.zeros_like(node_states)
        aggregate.index_add_(0, destination, messages)
        degree = torch.zeros((len(node_states), 1), dtype=node_states.dtype, device=node_states.device)
        degree.index_add_(0, destination, torch.ones((len(destination), 1), dtype=node_states.dtype, device=node_states.device))
        aggregate = aggregate / degree.clamp_min(1.0)
        update = self.update(torch.cat((normalized, aggregate), dim=-1))
        return self.output_norm(node_states + update)


class InvariantGraphEncoder(nn.Module):
    """Project node features then apply a fixed number of invariant MPNN layers."""

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


class LowRankBiaffineInteraction(nn.Module):
    """Rank-64 bidirectional cross interaction and pair-contact logits."""

    def __init__(self, hidden_dim: int, rank: int, dropout: float) -> None:
        super().__init__()
        self.hidden_dim = hidden_dim
        self.rank = rank
        self.vhh_left = nn.Linear(hidden_dim, rank, bias=False)
        self.target_right = nn.Linear(hidden_dim, rank, bias=False)
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

    def forward(self, vhh_states: Tensor, residue_mask: Tensor, target_states: Tensor) -> tuple[Tensor, Tensor, Tensor]:
        require(vhh_states.ndim == 3 and vhh_states.shape[-1] == self.hidden_dim, "vhh_states_shape_invalid")
        require(residue_mask.shape == vhh_states.shape[:2], "residue_mask_shape_invalid")
        require(target_states.ndim == 2 and target_states.shape[-1] == self.hidden_dim and len(target_states) > 0, "target_states_shape_invalid")
        left = self.vhh_left(vhh_states)
        right = self.target_right(target_states)
        pair_logits = torch.einsum("blr,tr->blt", left, right) / math.sqrt(self.rank)
        pair_logits = pair_logits + self.vhh_bias(vhh_states) + self.target_bias(target_states).view(1, 1, -1)
        pair_logits = pair_logits.masked_fill(~residue_mask.unsqueeze(-1), -1e4)
        vhh_attention = torch.softmax(pair_logits, dim=-1)
        vhh_context = torch.einsum("blt,th->blh", vhh_attention, self.target_value(target_states))
        conditioned_vhh = vhh_states + self.vhh_fusion(torch.cat((vhh_states, vhh_context), dim=-1))
        target_logits = pair_logits.masked_fill(~residue_mask.unsqueeze(-1), -1e4)
        target_attention = torch.softmax(target_logits, dim=1)
        target_context = torch.einsum("blt,blh->bth", target_attention, self.vhh_value(vhh_states))
        expanded_target = target_states.unsqueeze(0).expand(len(vhh_states), -1, -1)
        conditioned_target = expanded_target + self.target_fusion(torch.cat((expanded_target, target_context), dim=-1))
        return pair_logits, conditioned_vhh, conditioned_target


def _masked_mean(values: Tensor, mask: Tensor, dimensions: tuple[int, ...], epsilon: float) -> Tensor:
    weights = mask.to(values.dtype)
    numerator = (values * weights).sum(dim=dimensions)
    denominator = weights.sum(dim=dimensions).clamp_min(epsilon)
    return numerator / denominator


def summarize_pair_probabilities(
    pair_probabilities: Mapping[str, Tensor],
    residue_mask: Tensor,
    region_index: Tensor,
    target_graphs: Mapping[str, Mapping[str, Tensor]],
    *,
    epsilon: float,
) -> Tensor:
    """Return preregistered contact summaries without using source identity."""

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
        cdr_masses: list[Tensor] = []
        for region in (1, 2, 3):
            region_mask = pair_mask & (region_index == region).unsqueeze(-1)
            cdr_masses.append(_masked_mean(probabilities, region_mask, (1, 2), epsilon))
        clipped = probabilities.clamp(min=epsilon, max=1.0 - epsilon)
        binary_entropy = -(clipped * clipped.log() + (1.0 - clipped) * (1.0 - clipped).log())
        entropy = _masked_mean(binary_entropy, pair_mask, (1, 2), epsilon)
        summaries.extend((hotspot_mass, interface_specificity, *cdr_masses, entropy))
        hotspot_masses.append(hotspot_mass)
    hotspot_stack = torch.stack(hotspot_masses, dim=-1)
    summaries.append(hotspot_stack.min(dim=-1).values)
    summaries.append((hotspot_stack[:, 0] - hotspot_stack[:, 1]).abs())
    return torch.stack(summaries, dim=-1)


class TargetConditionedResidueV2Head(nn.Module):
    """Three-layer VHH graph, shared two-layer target graph, and pair head."""

    def __init__(self, config: ResidueV2Config) -> None:
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
        # This single module is called for both conformers: weights are shared.
        self.target_graph_encoder = InvariantGraphEncoder(
            config.target_node_dim, hidden, config.edge_feature_dim, config.target_graph_layers, config.dropout,
        )
        self.conformer_embedding = nn.Embedding(len(RECEPTOR_NAMES), hidden)
        self.interaction = LowRankBiaffineInteraction(hidden, config.interaction_rank, config.dropout)
        self.condition_fusion = nn.Sequential(
            nn.LayerNorm(hidden * 3), nn.Linear(hidden * 3, hidden), nn.GELU(), nn.Dropout(config.dropout),
        )
        self.structure_projection = nn.Sequential(
            nn.LayerNorm(config.structure_dim), nn.Linear(config.structure_dim, hidden), nn.GELU(),
        )
        # 6 per conformer plus dual minimum and conformer gap.
        self.pair_summary_dim = 14
        self.pair_summary_projection = nn.Sequential(
            nn.LayerNorm(self.pair_summary_dim), nn.Linear(self.pair_summary_dim, hidden), nn.GELU(),
        )
        # global + two receptor pools + structure + pair summary + explicit M2.
        self.residual_head = nn.Sequential(
            nn.LayerNorm(hidden * 5 + len(TARGET_NAMES)),
            nn.Linear(hidden * 5 + len(TARGET_NAMES), hidden), nn.GELU(),
            nn.Dropout(config.dropout), nn.Linear(hidden, len(TARGET_NAMES)),
        )

    def _encode_targets(self, target_graphs: Mapping[str, Mapping[str, Tensor]], device: torch.device) -> dict[str, Tensor]:
        require(set(target_graphs) == set(RECEPTOR_NAMES), "target_conformer_set_invalid")
        encoded: dict[str, Tensor] = {}
        for conformer_index, receptor in enumerate(RECEPTOR_NAMES):
            graph = target_graphs[receptor]
            required = {"node_features", "edge_index", "edge_features", "interface_mask", "hotspot_mask"}
            require(required <= set(graph), f"target_graph_fields_missing:{receptor}:{sorted(required - set(graph))}")
            node_features = graph["node_features"].to(device=device)
            edge_index = graph["edge_index"].to(device=device, dtype=torch.long)
            edge_features = graph["edge_features"].to(device=device)
            states = self.target_graph_encoder(node_features, edge_index, edge_features)
            states = states + self.conformer_embedding.weight[conformer_index].view(1, -1)
            encoded[receptor] = states
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
        structure_features: Tensor,
        m2_base: Tensor,
    ) -> dict[str, Tensor]:
        require(token_states.ndim == 3, "token_states_shape_invalid")
        batch, length, _ = token_states.shape
        require(residue_mask.shape == vhh_aa_index.shape == vhh_region_index.shape == (batch, length), "vhh_node_index_shape_invalid")
        if vhh_confidence.ndim == 2:
            vhh_confidence = vhh_confidence.unsqueeze(-1)
        require(vhh_confidence.shape == (batch, length, 1), "vhh_confidence_shape_invalid")
        require(structure_features.shape == (batch, self.config.structure_dim), "structure_features_shape_invalid")
        require(m2_base.shape == (batch, len(TARGET_NAMES)), "m2_base_shape_invalid")
        require(bool(torch.all(residue_mask.sum(dim=1) > 0)), "empty_residue_mask")
        require(vhh_edge_index.device == token_states.device and vhh_edge_features.device == token_states.device, "vhh_graph_device_mismatch")
        require(vhh_edge_index.dtype == torch.long, "vhh_edge_index_dtype_invalid")
        require(vhh_edge_index.ndim == 2 and vhh_edge_index.shape[0] == 2, "vhh_edge_index_shape_invalid")
        flat_valid = residue_mask.reshape(-1)
        require(vhh_edge_index.shape[1] > 0, "vhh_graph_has_no_edges")
        require(int(vhh_edge_index.min()) >= 0 and int(vhh_edge_index.max()) < batch * length, "vhh_edge_index_out_of_bounds")
        require(bool(torch.all(flat_valid[vhh_edge_index.reshape(-1)])), "vhh_edge_touches_padding")
        require(bool(torch.all((vhh_aa_index[residue_mask] >= 0) & (vhh_aa_index[residue_mask] < self.config.aa_vocab_size))), "vhh_aa_index_invalid")
        require(bool(torch.all((vhh_region_index[residue_mask] >= 0) & (vhh_region_index[residue_mask] < self.config.region_vocab_size))), "vhh_region_index_invalid")

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
        pair_logits: dict[str, Tensor] = {}
        conditioned: dict[str, Tensor] = {}
        conditioned_targets: dict[str, Tensor] = {}
        for receptor in RECEPTOR_NAMES:
            logits, vhh_conditioned, target_conditioned = self.interaction(
                vhh_states, residue_mask, encoded_targets[receptor],
            )
            pair_logits[receptor] = logits
            conditioned[receptor] = vhh_conditioned
            conditioned_targets[receptor] = target_conditioned
        combined_states = self.condition_fusion(
            torch.cat((vhh_states, conditioned["8x6b"], conditioned["9e6y"]), dim=-1)
        )
        mask = residue_mask.to(combined_states.dtype).unsqueeze(-1)
        global_pool = (combined_states * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1.0)
        marginal_logits = torch.stack(
            [torch.logsumexp(pair_logits[receptor], dim=-1) - math.log(pair_logits[receptor].shape[-1]) for receptor in RECEPTOR_NAMES],
            dim=-1,
        )
        marginal_probabilities = torch.sigmoid(marginal_logits) * residue_mask.unsqueeze(-1).to(token_states.dtype)
        receptor_pools: list[Tensor] = []
        for channel, receptor in enumerate(RECEPTOR_NAMES):
            weights = marginal_probabilities[:, :, channel]
            vhh_pool = (
                (combined_states * weights.unsqueeze(-1)).sum(dim=1)
                / weights.sum(dim=1, keepdim=True).clamp_min(self.config.pool_epsilon)
            )
            # The target-to-VHH attention direction must affect the prediction,
            # not merely be emitted as a diagnostic tensor.
            target_feedback = conditioned_targets[receptor].mean(dim=1)
            receptor_pools.append(vhh_pool + target_feedback)
        pair_probabilities = {receptor: torch.sigmoid(pair_logits[receptor]) for receptor in RECEPTOR_NAMES}
        pair_summary = summarize_pair_probabilities(
            pair_probabilities, residue_mask, vhh_region_index, target_graphs, epsilon=self.config.pool_epsilon,
        )
        structure = self.structure_projection(structure_features)
        pair_summary_state = self.pair_summary_projection(pair_summary)
        fused = torch.cat((global_pool, receptor_pools[0], receptor_pools[1], structure, pair_summary_state, m2_base), dim=-1)
        raw_residual = self.residual_head(fused)
        residual = self.config.residual_scale * torch.tanh(raw_residual)
        prediction = m2_base + residual
        return {
            "prediction": prediction,
            "m2_base": m2_base,
            "residual": residual,
            "marginal_contact_logits": marginal_logits,
            "marginal_contact_probabilities": marginal_probabilities,
            "pair_logits_8x6b": pair_logits["8x6b"],
            "pair_logits_9e6y": pair_logits["9e6y"],
            "pair_probabilities_8x6b": pair_probabilities["8x6b"],
            "pair_probabilities_9e6y": pair_probabilities["9e6y"],
            "pair_summary": pair_summary,
            "vhh_graph_states": vhh_states,
            "target_states_8x6b": encoded_targets["8x6b"],
            "target_states_9e6y": encoded_targets["9e6y"],
            "conditioned_target_states_8x6b": conditioned_targets["8x6b"],
            "conditioned_target_states_9e6y": conditioned_targets["9e6y"],
        }


class ResidueV2Surrogate(nn.Module):
    """Frozen-backbone wrapper; the first Residue V2 round forbids LoRA."""

    def __init__(self, backbone: nn.Module, head: TargetConditionedResidueV2Head) -> None:
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
        structure_features: Tensor,
        m2_base: Tensor,
    ) -> dict[str, Tensor]:
        self.backbone.eval()
        with torch.no_grad():
            token_states = backbone_states(self.backbone, input_ids, attention_mask)
        return self.head(
            token_states, residue_mask, vhh_aa_index, vhh_region_index, vhh_confidence,
            vhh_edge_index, vhh_edge_features, target_graphs, structure_features, m2_base,
        )


def backbone_states(backbone: nn.Module, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
    output = backbone(input_ids=input_ids, attention_mask=attention_mask)
    if isinstance(output, Mapping):
        states = output.get("last_hidden_state")
    else:
        states = getattr(output, "last_hidden_state", None)
    require(isinstance(states, Tensor), "backbone_missing_last_hidden_state")
    require(states.shape[:2] == input_ids.shape, "backbone_state_shape_invalid")
    return states


def trainable_checkpoint_state(model: ResidueV2Surrogate) -> dict[str, Tensor]:
    state: dict[str, Tensor] = {}
    for name, parameter in model.named_parameters():
        if parameter.requires_grad:
            require(name.startswith("head."), f"frozen_backbone_parameter_exposed:{name}")
            state[name] = parameter.detach().cpu().clone()
    require(state, "empty_trainable_checkpoint")
    return state


def model_contract(config: ResidueV2Config) -> dict[str, Any]:
    config.validate()
    forward_fields = tuple(inspect.signature(TargetConditionedResidueV2Head.forward).parameters)
    require("teacher_source" not in forward_fields, "teacher_source_feature_forbidden")
    return {
        "schema_version": "pvrig_v6_target_conditioned_residue_model_v2",
        "claim_boundary": CLAIM_BOUNDARY,
        "config": asdict(config),
        "vhh_graph": "3-layer invariant MPNN",
        "target_graph": "shared 2-layer invariant MPNN for 8X6B and 9E6Y",
        "interaction": "rank64 bidirectional cross/biaffine pair logits",
        "prediction": "M2 + 0.02*tanh(residual)",
        "forbidden_features": ["teacher_source", "candidate_docking_pose", "raw_absolute_coordinates"],
    }
