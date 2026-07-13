#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import torch

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import train_phase2_v2_3 as v23
from phase2_v3_p1_model import (
    PVRIGModelConfig,
    PVRIGV3P1Model,
    generic_replay_consistency_loss,
    ordinal_cumulative_loss,
    teacher_auxiliary_losses,
    within_campaign_rank_loss,
)


class ExplodingPairHead(torch.nn.Module):
    def forward(self, *args: object, **kwargs: object) -> torch.Tensor:
        raise AssertionError("The forbidden V2.3 pair head was called")


class V3P1ModelTest(unittest.TestCase):
    def setUp(self) -> None:
        torch.manual_seed(7)
        backbone_cfg = v23.Config(
            d_model=8,
            esm_dim=6,
            contact_dim=4,
            layers=1,
            cross_layers=1,
            heads=2,
            dropout=0.0,
            max_vhh_len=16,
            max_antigen_len=16,
        )
        backbone = v23.CrossContactNetV23(backbone_cfg)
        backbone.pair = ExplodingPairHead()
        self.model = PVRIGV3P1Model(
            backbone,
            PVRIGModelConfig(
                contact_dim=4,
                pooled_dim=5,
                hidden_dim=12,
                geometry_dim=8,
                structure_dim=8,
                structure_projection_dim=4,
                dropout=0.0,
            ),
            torch.tensor([1.0, 0.0, 0.5, 0.0]),
            torch.randn(4, 8),
            torch.randn(4, 8),
        ).eval()
        self.vhh = torch.randn(3, 5, 6)
        self.cdr = torch.tensor([[0, 1, 2, 3, 0]] * 3)
        self.antigen = torch.randn(3, 4, 6)
        self.prior = torch.tensor([0.2, 0.5, 0.8])

    def forward(self, **kwargs: object) -> dict[str, torch.Tensor]:
        return self.model(self.vhh, self.cdr, self.antigen, self.prior, **kwargs)

    def test_ordered_probabilities_and_forbidden_pair_head(self) -> None:
        outputs = self.forward()
        cumulative = outputs["cumulative_probabilities"]
        self.assertTrue(torch.all(cumulative[:, :-1] >= cumulative[:, 1:]))
        self.assertTrue(torch.all(outputs["tier_probabilities"] >= 0))
        self.assertTrue(torch.allclose(outputs["tier_probabilities"].sum(1), torch.ones(3), atol=1e-6))
        self.assertTrue(all(not parameter.requires_grad for parameter in self.model.backbone.parameters()))

    def test_dual_structure_channels_and_controls_change_outputs(self) -> None:
        full = self.forward()["predicted_relevance"]
        zeros = torch.zeros(4, 8)
        no_structure = self.forward(structure_8x6b=zeros, structure_9e6y=zeros)["predicted_relevance"]
        only_8x6b = self.forward(structure_9e6y=zeros)["predicted_relevance"]
        only_9e6y = self.forward(structure_8x6b=zeros)["predicted_relevance"]
        self.assertFalse(torch.allclose(full, no_structure))
        self.assertFalse(torch.allclose(only_8x6b, only_9e6y))

        shuffled_a = self.forward(control_type="hotspot_shuffle", control_seed=83)["predicted_relevance"]
        shuffled_b = self.forward(control_type="hotspot_shuffle", control_seed=83)["predicted_relevance"]
        self.assertTrue(torch.equal(shuffled_a, shuffled_b))
        permuted = self.forward(control_type="target_permutation", control_seed=83)["predicted_relevance"]
        self.assertFalse(torch.allclose(full, permuted))

    def test_target_ablation_does_not_use_antigen_content_or_prior(self) -> None:
        first = self.forward(control_type="antigen_ablation")["predicted_relevance"]
        other_antigen = torch.randn_like(self.antigen) * 10
        second = self.model(
            self.vhh,
            self.cdr,
            other_antigen,
            1.0 - self.prior,
            control_type="antigen_ablation",
        )["predicted_relevance"]
        self.assertTrue(torch.allclose(first, second, atol=1e-6))
        vhh_only = self.forward(control_type="vhh_only")
        self.assertTrue(torch.equal(vhh_only["generic_binding_prior"], torch.full((3,), 0.5)))

    def test_multitask_losses_backpropagate_only_into_adapters(self) -> None:
        self.model.train()
        outputs = self.forward()
        relevance = torch.tensor([0, 2, 4])
        ordinal = ordinal_cumulative_loss(outputs["cumulative_logits"], relevance)
        targets = torch.sigmoid(outputs["base_contact_logits"]).detach()
        auxiliaries = teacher_auxiliary_losses(
            outputs,
            targets,
            torch.sigmoid(outputs["base_paratope_logits"]).detach(),
            torch.sigmoid(outputs["base_epitope_logits"]).detach(),
        )
        rank = within_campaign_rank_loss(
            outputs["predicted_relevance"], relevance, torch.tensor([0, 0, 0])
        )
        replay = generic_replay_consistency_loss(outputs)
        loss = ordinal + sum(auxiliaries.values()) + rank + replay
        loss.backward()
        self.assertTrue(any(parameter.grad is not None for name, parameter in self.model.named_parameters() if not name.startswith("backbone.")))
        self.assertTrue(all(parameter.grad is None for parameter in self.model.backbone.parameters()))


if __name__ == "__main__":
    unittest.main()
