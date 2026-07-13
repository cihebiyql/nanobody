#!/usr/bin/env python3
"""Formal V3-P sequence-to-geometry model built on the frozen V2.3 backbone.

The V2.3 pair head is intentionally outside this model's execution path.  A
frozen, externally supplied mean-pooled generic binding prior is the only pair
level binding feature consumed by V3-P.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import torch
from torch import nn


TIER_NAMES = ("G1", "G2", "G3", "G4", "G5")
TIER_TO_RELEVANCE = {"G1": 4, "G2": 3, "G3": 2, "G4": 1, "G5": 0}
RELEVANCE_TO_TIER = {value: key for key, value in TIER_TO_RELEVANCE.items()}


@dataclass(frozen=True)
class PVRIGModelConfig:
    contact_dim: int = 64
    pooled_dim: int = 48
    hidden_dim: int = 128
    geometry_dim: int = 8
    structure_dim: int = 8
    structure_projection_dim: int = 16
    dropout: float = 0.1
    contact_residual_scale: float = 0.1
    site_residual_scale: float = 0.1


def _masked_mean(values: torch.Tensor, mask: torch.Tensor, dimensions: tuple[int, ...]) -> torch.Tensor:
    weights = mask.to(values.dtype)
    return (values * weights).sum(dimensions) / weights.sum(dimensions).clamp_min(1.0)


def cumulative_to_tier_probabilities(cumulative: torch.Tensor) -> torch.Tensor:
    """Convert P(relevance > k), k=0..3, into ordered G1..G5 probabilities."""
    if cumulative.ndim != 2 or cumulative.shape[1] != 4:
        raise ValueError(f"Expected cumulative probabilities with shape (batch, 4), got {tuple(cumulative.shape)}")
    g5 = 1.0 - cumulative[:, 0]
    g4 = cumulative[:, 0] - cumulative[:, 1]
    g3 = cumulative[:, 1] - cumulative[:, 2]
    g2 = cumulative[:, 2] - cumulative[:, 3]
    g1 = cumulative[:, 3]
    return torch.stack((g1, g2, g3, g4, g5), dim=1)


class PVRIGV3P1Model(nn.Module):
    """Trainable PVRIG adapters over frozen V2.3 residue representations."""

    def __init__(
        self,
        backbone: nn.Module,
        config: PVRIGModelConfig,
        hotspot_weights: torch.Tensor,
        structure_8x6b: torch.Tensor | None = None,
        structure_9e6y: torch.Tensor | None = None,
    ) -> None:
        super().__init__()
        if hotspot_weights.ndim != 1:
            raise ValueError("hotspot_weights must be one-dimensional")
        self.backbone = backbone
        self.config = config
        for parameter in self.backbone.parameters():
            parameter.requires_grad = False
        self.backbone.eval()

        d_model = int(backbone.cfg.d_model)
        self.contact_q = nn.Linear(d_model, config.contact_dim)
        self.contact_k = nn.Linear(d_model, config.contact_dim)
        self.contact_bias_v = nn.Linear(d_model, 1)
        self.contact_bias_a = nn.Linear(d_model, 1)
        self.contact_scale = nn.Parameter(torch.tensor(float(config.contact_residual_scale)))
        self.paratope_residual = nn.Linear(d_model, 1)
        self.epitope_residual = nn.Linear(d_model, 1)
        self.site_scale = nn.Parameter(torch.tensor(float(config.site_residual_scale)))
        self.structure_8x6b_projection = nn.Sequential(
            nn.Linear(config.structure_dim, config.structure_projection_dim, bias=False), nn.GELU()
        )
        self.structure_9e6y_projection = nn.Sequential(
            nn.Linear(config.structure_dim, config.structure_projection_dim, bias=False), nn.GELU()
        )
        self.structure_fusion = nn.Linear(config.structure_projection_dim * 2, d_model, bias=False)

        self.vhh_pool = nn.Sequential(nn.Linear(d_model, config.pooled_dim), nn.GELU())
        self.antigen_pool = nn.Sequential(nn.Linear(d_model, config.pooled_dim), nn.GELU())
        # Fifteen contact/site statistics plus prior and prior-logit features.
        feature_dim = config.pooled_dim * 2 + 17
        self.shared = nn.Sequential(
            nn.LayerNorm(feature_dim),
            nn.Linear(feature_dim, config.hidden_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim, config.hidden_dim),
            nn.GELU(),
        )
        self.tier_score = nn.Linear(config.hidden_dim, 1)
        self.geometry = nn.Linear(config.hidden_dim, config.geometry_dim)

        # Ordered cutpoints guarantee P(y>0) >= ... >= P(y>3).
        self.cutpoint_base = nn.Parameter(torch.tensor(-1.5))
        inverse_softplus_one = math.log(math.expm1(1.0))
        self.cutpoint_gaps_raw = nn.Parameter(torch.full((3,), inverse_softplus_one))
        self.register_buffer("default_hotspot_weights", hotspot_weights.detach().float().clone())
        default_shape = (len(hotspot_weights), config.structure_dim)
        structure_8x6b = torch.zeros(default_shape) if structure_8x6b is None else structure_8x6b
        structure_9e6y = torch.zeros(default_shape) if structure_9e6y is None else structure_9e6y
        if tuple(structure_8x6b.shape) != default_shape or tuple(structure_9e6y.shape) != default_shape:
            raise ValueError(f"Conformer features must both have shape {default_shape}")
        self.register_buffer("default_structure_8x6b", structure_8x6b.detach().float().clone())
        self.register_buffer("default_structure_9e6y", structure_9e6y.detach().float().clone())

    def train(self, mode: bool = True) -> "PVRIGV3P1Model":
        super().train(mode)
        # Frozen dropout/layernorm behavior must not change between train/eval.
        self.backbone.eval()
        return self

    def ordered_cutpoints(self) -> torch.Tensor:
        gaps = nn.functional.softplus(self.cutpoint_gaps_raw) + 1e-4
        return torch.cat((self.cutpoint_base.reshape(1), self.cutpoint_base + torch.cumsum(gaps, dim=0)))

    def _resolve_hotspots(
        self,
        antigen_length: int,
        batch_size: int,
        device: torch.device,
        hotspot_weights: torch.Tensor | None,
    ) -> torch.Tensor:
        source = self.default_hotspot_weights if hotspot_weights is None else hotspot_weights
        source = source.to(device=device, dtype=torch.float32)
        if source.ndim == 1:
            source = source.unsqueeze(0).expand(batch_size, -1)
        if source.ndim != 2 or source.shape[0] != batch_size:
            raise ValueError("hotspot_weights must have shape (antigen_length,) or (batch, antigen_length)")
        if source.shape[1] < antigen_length:
            source = nn.functional.pad(source, (0, antigen_length - source.shape[1]))
        return source[:, :antigen_length]

    def _resolve_structure(
        self,
        source: torch.Tensor,
        antigen_length: int,
        batch_size: int,
        device: torch.device,
    ) -> torch.Tensor:
        source = source.to(device=device, dtype=torch.float32)
        if source.ndim == 2:
            source = source.unsqueeze(0).expand(batch_size, -1, -1)
        if source.ndim != 3 or source.shape[0] != batch_size or source.shape[2] != self.config.structure_dim:
            raise ValueError("Structure features must have shape (length, dim) or (batch, length, dim)")
        if source.shape[1] < antigen_length:
            source = nn.functional.pad(source, (0, 0, 0, antigen_length - source.shape[1]))
        return source[:, :antigen_length]

    @staticmethod
    def _control_permutation(length: int, seed: int, device: torch.device) -> torch.Tensor:
        generator = torch.Generator(device="cpu").manual_seed(int(seed))
        return torch.randperm(length, generator=generator).to(device)

    def _encode_vhh_only(self, vhh: torch.Tensor, cdr: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        v_mask = vhh.abs().sum(-1).eq(0)
        positions = torch.arange(vhh.shape[1], device=vhh.device).unsqueeze(0).expand(vhh.shape[0], -1)
        positions = positions.clamp(max=self.backbone.cfg.max_vhh_len - 1)
        hidden = self.backbone.esm_project(vhh) + self.backbone.cdr_type(cdr.clamp(0, 3)) + self.backbone.v_pos(positions)
        return self.backbone.v_enc(hidden, src_key_padding_mask=v_mask), v_mask

    def forward(
        self,
        vhh: torch.Tensor,
        cdr: torch.Tensor,
        antigen: torch.Tensor,
        generic_binding_prior: torch.Tensor,
        hotspot_weights: torch.Tensor | None = None,
        structure_8x6b: torch.Tensor | None = None,
        structure_9e6y: torch.Tensor | None = None,
        control_type: str = "full",
        control_seed: int = 0,
    ) -> dict[str, torch.Tensor]:
        allowed_controls = {"full", "hotspot_shuffle", "antigen_ablation", "target_permutation", "vhh_only"}
        if control_type not in allowed_controls:
            raise ValueError(f"Unsupported inference control: {control_type}")
        prior = generic_binding_prior.float().reshape(-1)
        if len(prior) != vhh.shape[0] or not torch.isfinite(prior).all():
            raise ValueError("generic_binding_prior must contain one finite scalar per candidate")
        if bool(((prior < 0.0) | (prior > 1.0)).any()):
            raise ValueError("generic_binding_prior must be a probability in [0, 1]")

        structure_8x6b = self.default_structure_8x6b if structure_8x6b is None else structure_8x6b
        structure_9e6y = self.default_structure_9e6y if structure_9e6y is None else structure_9e6y
        raw_hotspots = self.default_hotspot_weights if hotspot_weights is None else hotspot_weights
        antigen_input = antigen
        if control_type == "target_permutation":
            permutation = self._control_permutation(antigen.shape[1], control_seed, antigen.device)
            antigen_input = antigen[:, permutation]
            raw_hotspots = raw_hotspots[..., permutation]
            structure_8x6b = structure_8x6b[..., permutation, :] if structure_8x6b.ndim == 3 else structure_8x6b[permutation]
            structure_9e6y = structure_9e6y[..., permutation, :] if structure_9e6y.ndim == 3 else structure_9e6y[permutation]
        elif control_type == "hotspot_shuffle":
            permutation = self._control_permutation(antigen.shape[1], control_seed, antigen.device)
            raw_hotspots = raw_hotspots[..., permutation]

        self.backbone.eval()
        with torch.no_grad():
            if control_type == "vhh_only":
                hv, v_mask = self._encode_vhh_only(vhh, cdr)
                ha = torch.zeros((vhh.shape[0], antigen.shape[1], hv.shape[2]), device=hv.device, dtype=hv.dtype)
                a_mask = antigen.abs().sum(-1).eq(0)
                base_contact = torch.zeros((vhh.shape[0], vhh.shape[1], antigen.shape[1]), device=hv.device, dtype=hv.dtype)
                base_paratope = self.backbone.para(hv).squeeze(-1).detach()
                base_epitope = torch.zeros((vhh.shape[0], antigen.shape[1]), device=hv.device, dtype=hv.dtype)
            else:
                hv, ha, v_mask, a_mask = self.backbone.encode(vhh, cdr, antigen_input)
                base_contact = self.backbone.contact_logits(hv, ha).detach()
                base_paratope, base_epitope = self.backbone.site_logits(hv, ha)
                base_paratope = base_paratope.detach()
                base_epitope = base_epitope.detach()

        structures_8x6b = self._resolve_structure(structure_8x6b, ha.shape[1], ha.shape[0], ha.device)
        structures_9e6y = self._resolve_structure(structure_9e6y, ha.shape[1], ha.shape[0], ha.device)
        hotspots = self._resolve_hotspots(ha.shape[1], ha.shape[0], ha.device, raw_hotspots)
        if control_type in {"antigen_ablation", "vhh_only"}:
            ha = torch.zeros_like(ha)
            structures_8x6b = torch.zeros_like(structures_8x6b)
            structures_9e6y = torch.zeros_like(structures_9e6y)
            hotspots = torch.zeros_like(hotspots)
            base_contact = torch.zeros_like(base_contact)
            base_epitope = torch.zeros_like(base_epitope)
        structure_8x6b_encoded = self.structure_8x6b_projection(structures_8x6b)
        structure_9e6y_encoded = self.structure_9e6y_projection(structures_9e6y)
        ha = ha + self.structure_fusion(torch.cat((structure_8x6b_encoded, structure_9e6y_encoded), dim=-1))

        adapter = torch.bmm(self.contact_q(hv), self.contact_k(ha).transpose(1, 2))
        adapter = adapter / math.sqrt(float(self.contact_q.out_features))
        adapter = adapter + self.contact_bias_v(hv) + self.contact_bias_a(ha).transpose(1, 2)
        contact_logits = base_contact + self.contact_scale * adapter
        paratope_logits = base_paratope + self.site_scale * self.paratope_residual(hv).squeeze(-1)
        epitope_logits = base_epitope + self.site_scale * self.epitope_residual(ha).squeeze(-1)

        valid_contact = (~v_mask).unsqueeze(2) & (~a_mask).unsqueeze(1)
        contact_prob = torch.sigmoid(contact_logits).masked_fill(~valid_contact, 0.0)
        paratope_prob = torch.sigmoid(paratope_logits).masked_fill(v_mask, 0.0)
        epitope_prob = torch.sigmoid(epitope_logits).masked_fill(a_mask, 0.0)
        interface = hotspots.gt(0).unsqueeze(1) & valid_contact
        noninterface = hotspots.eq(0).unsqueeze(1) & valid_contact
        weighted_hotspot = hotspots.unsqueeze(1) * valid_contact

        hotspot_mean = _masked_mean(contact_prob, interface, (1, 2))
        noninterface_mean = _masked_mean(contact_prob, noninterface, (1, 2))
        hotspot_mass = (contact_prob * weighted_hotspot).sum((1, 2)) / weighted_hotspot.sum((1, 2)).clamp_min(1.0)
        flattened = contact_prob.masked_fill(~valid_contact, -1.0).flatten(1)
        top = torch.topk(flattened, k=min(20, flattened.shape[1]), dim=1).values.clamp_min(0.0)
        top1 = top[:, 0]
        top5 = top[:, : min(5, top.shape[1])].mean(1)
        top20 = top.mean(1)
        cdr_contact: list[torch.Tensor] = []
        cdr_paratope: list[torch.Tensor] = []
        for cdr_type in (1, 2, 3):
            cdr_mask = (cdr == cdr_type) & (~v_mask)
            cdr_contact.append(_masked_mean(contact_prob, cdr_mask.unsqueeze(2) & interface, (1, 2)))
            cdr_paratope.append(_masked_mean(paratope_prob, cdr_mask, (1,)))
        eps = 1e-6
        bernoulli_entropy = -(
            contact_prob.clamp(eps, 1 - eps) * contact_prob.clamp(eps, 1 - eps).log()
            + (1 - contact_prob).clamp(eps, 1 - eps) * (1 - contact_prob).clamp(eps, 1 - eps).log()
        )
        contact_entropy = _masked_mean(bernoulli_entropy, valid_contact, (1, 2))
        interface_epitope = _masked_mean(epitope_prob, hotspots.gt(0) & (~a_mask), (1,))

        v_valid = (~v_mask).to(hv.dtype).unsqueeze(-1)
        a_valid = (~a_mask).to(ha.dtype).unsqueeze(-1)
        v_pool = (hv * v_valid).sum(1) / v_valid.sum(1).clamp_min(1.0)
        a_pool = (ha * a_valid).sum(1) / a_valid.sum(1).clamp_min(1.0)
        prior_clamped = prior.to(hv.device).clamp(1e-5, 1 - 1e-5)
        prior_logit = torch.logit(prior_clamped)
        engineered = torch.stack(
            (
                hotspot_mean,
                noninterface_mean,
                hotspot_mass,
                hotspot_mean - noninterface_mean,
                top1,
                top5,
                top20,
                *cdr_contact,
                *cdr_paratope,
                contact_entropy,
                interface_epitope,
                prior_clamped,
                prior_logit,
            ),
            dim=1,
        )
        features = torch.cat((self.vhh_pool(v_pool), self.antigen_pool(a_pool), engineered), dim=1)
        hidden = self.shared(features)
        relevance_score = self.tier_score(hidden).squeeze(-1)
        cumulative_logits = relevance_score.unsqueeze(1) - self.ordered_cutpoints().unsqueeze(0)
        cumulative_probabilities = torch.sigmoid(cumulative_logits)
        tier_probabilities = cumulative_to_tier_probabilities(cumulative_probabilities)

        return {
            "cumulative_logits": cumulative_logits,
            "cumulative_probabilities": cumulative_probabilities,
            "tier_probabilities": tier_probabilities,
            "predicted_relevance": cumulative_probabilities.sum(1),
            "geometry": self.geometry(hidden),
            "contact_logits": contact_logits,
            "paratope_logits": paratope_logits,
            "epitope_logits": epitope_logits,
            "base_contact_logits": base_contact,
            "base_paratope_logits": base_paratope,
            "base_epitope_logits": base_epitope,
            "valid_contact_mask": valid_contact,
            "vhh_padding_mask": v_mask,
            "antigen_padding_mask": a_mask,
            "generic_binding_prior": prior.to(hv.device),
            "structure_8x6b_encoded": structure_8x6b_encoded,
            "structure_9e6y_encoded": structure_9e6y_encoded,
        }

    def trainable_state_dict(self) -> dict[str, torch.Tensor]:
        return {
            name: value.detach().cpu().clone()
            for name, value in self.state_dict().items()
            if not name.startswith("backbone.")
        }

    def load_trainable_state_dict(self, state: dict[str, torch.Tensor]) -> None:
        missing, unexpected = self.load_state_dict(state, strict=False)
        missing = [name for name in missing if name.startswith("backbone.")]
        if unexpected or len(missing) != len(self.backbone.state_dict()):
            raise ValueError(f"Invalid V3-P trainable state: missing={missing[:3]} unexpected={unexpected[:3]}")


def ordinal_targets(relevance: torch.Tensor) -> torch.Tensor:
    if relevance.ndim != 1:
        raise ValueError("relevance must be one-dimensional")
    return (relevance.unsqueeze(1) > torch.arange(4, device=relevance.device).unsqueeze(0)).float()


def ordinal_cumulative_loss(cumulative_logits: torch.Tensor, relevance: torch.Tensor) -> torch.Tensor:
    return nn.functional.binary_cross_entropy_with_logits(cumulative_logits, ordinal_targets(relevance))


def within_campaign_rank_loss(
    scores: torch.Tensor,
    relevance: torch.Tensor,
    campaign_codes: torch.Tensor,
    margin: float = 0.2,
) -> torch.Tensor:
    """Pairwise ordinal loss, restricted to comparable candidates in a campaign."""
    losses: list[torch.Tensor] = []
    for campaign in torch.unique(campaign_codes):
        mask = campaign_codes == campaign
        local_scores = scores[mask]
        local_relevance = relevance[mask]
        better = local_relevance[:, None] > local_relevance[None, :]
        if better.any():
            differences = local_scores[:, None] - local_scores[None, :]
            losses.append(nn.functional.softplus(margin - differences[better]).mean())
    return torch.stack(losses).mean() if losses else scores.sum() * 0.0


def _soft_label_bce(logits: torch.Tensor, targets: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    if not mask.any():
        return logits.sum() * 0.0
    return nn.functional.binary_cross_entropy_with_logits(logits[mask], targets[mask])


def teacher_auxiliary_losses(
    outputs: dict[str, torch.Tensor],
    contact_targets: torch.Tensor,
    paratope_targets: torch.Tensor,
    epitope_targets: torch.Tensor,
) -> dict[str, torch.Tensor]:
    contact_mask = outputs["valid_contact_mask"]
    vhh_mask = ~outputs["vhh_padding_mask"]
    antigen_mask = ~outputs["antigen_padding_mask"]
    return {
        "contact": _soft_label_bce(outputs["contact_logits"], contact_targets, contact_mask),
        "paratope": _soft_label_bce(outputs["paratope_logits"], paratope_targets, vhh_mask),
        "epitope": _soft_label_bce(outputs["epitope_logits"], epitope_targets, antigen_mask),
    }


def generic_replay_consistency_loss(outputs: dict[str, torch.Tensor]) -> torch.Tensor:
    """Keep adapters close to frozen generic contact/site predictions on replay data."""
    contact_target = torch.sigmoid(outputs["base_contact_logits"]).detach()
    paratope_target = torch.sigmoid(outputs["base_paratope_logits"]).detach()
    epitope_target = torch.sigmoid(outputs["base_epitope_logits"]).detach()
    losses = teacher_auxiliary_losses(outputs, contact_target, paratope_target, epitope_target)
    return (losses["contact"] + losses["paratope"] + losses["epitope"]) / 3.0


def assert_backbone_frozen(model: PVRIGV3P1Model) -> None:
    trainable = [name for name, parameter in model.backbone.named_parameters() if parameter.requires_grad]
    if trainable:
        raise AssertionError(f"V2.3 backbone unexpectedly trainable: {trainable[:5]}")


def checkpoint_model_metadata(model: PVRIGV3P1Model) -> dict[str, Any]:
    return {
        "model_config": model.config.__dict__,
        "tier_names_probability_order": list(TIER_NAMES),
        "relevance_mapping": TIER_TO_RELEVANCE,
        "generic_binding_feature": "frozen_meanpool_v3_full_scalar_only",
        "forbidden_pair_heads": ["v2_3_pair_head", "v3_g2_failed_pair_head"],
        "frozen_backbone": True,
    }
