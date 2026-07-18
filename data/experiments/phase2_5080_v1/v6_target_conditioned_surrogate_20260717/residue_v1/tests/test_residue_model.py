import importlib.util
import pathlib
import sys
import unittest

import torch
from torch import nn


ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
import residue_model as mod


class FrozenBackbone(nn.Module):
    def __init__(self, hidden=8):
        super().__init__()
        self.embedding = nn.Embedding(16, hidden)

    def forward(self, input_ids, attention_mask):
        del attention_mask
        return type("Output", (), {"last_hidden_state": self.embedding(input_ids)})()


class LoraBackbone(nn.Module):
    def __init__(self, hidden=8):
        super().__init__()
        self.base = nn.Embedding(16, hidden)
        self.base.weight.requires_grad_(False)
        self.lora_A = nn.Linear(hidden, hidden, bias=False)

    def forward(self, input_ids, attention_mask):
        del attention_mask
        states = self.base(input_ids)
        return type("Output", (), {"last_hidden_state": states + self.lora_A(states)})()


class TestResidueModel(unittest.TestCase):
    def make_inputs(self):
        return {
            "input_ids": torch.randint(1, 15, (3, 7)),
            "attention_mask": torch.ones(3, 7, dtype=torch.long),
            "residue_mask": torch.tensor([[0, 1, 1, 1, 1, 1, 0]] * 3, dtype=torch.bool),
            "structure_features": torch.randn(3, 4),
            "m2_base": torch.full((3, 3), 0.5),
        }

    def test_two_channel_forward_and_bounded_residual(self):
        config = mod.ResidueHeadConfig(backbone_hidden_size=8, structure_dim=4, fusion_dim=6, residual_scale=0.1)
        model = mod.ResidueSurrogate(FrozenBackbone(), mod.DualContactResidualHead(config), backbone_mode="frozen")
        output = model(**self.make_inputs())
        self.assertEqual(output["contact_logits"].shape, (3, 7, 2))
        self.assertEqual(output["prediction"].shape, (3, 3))
        self.assertTrue(torch.all(output["residual"].abs() <= 0.100001))
        self.assertTrue(torch.allclose(output["prediction"], output["m2_base"] + output["residual"]))

    def test_checkpoint_contains_only_head_for_frozen_backbone(self):
        config = mod.ResidueHeadConfig(backbone_hidden_size=8, structure_dim=4, fusion_dim=6)
        model = mod.ResidueSurrogate(FrozenBackbone(), mod.DualContactResidualHead(config), backbone_mode="frozen")
        state = mod.trainable_checkpoint_state(model)
        self.assertTrue(state)
        self.assertTrue(all(name.startswith("head.") for name in state))

    def test_lora_checkpoint_contains_adapter_and_head_but_not_base(self):
        config = mod.ResidueHeadConfig(backbone_hidden_size=8, structure_dim=4, fusion_dim=6)
        model = mod.ResidueSurrogate(LoraBackbone(), mod.DualContactResidualHead(config), backbone_mode="lora")
        state = mod.trainable_checkpoint_state(model)
        self.assertIn("backbone.lora_A.weight", state)
        self.assertNotIn("backbone.base.weight", state)
        self.assertTrue(any(name.startswith("head.") for name in state))

    def test_multitask_loss_is_finite_and_backpropagates_to_heads(self):
        config = mod.ResidueHeadConfig(backbone_hidden_size=8, structure_dim=4, fusion_dim=6)
        model = mod.ResidueSurrogate(FrozenBackbone(), mod.DualContactResidualHead(config), backbone_mode="frozen")
        output = model(**self.make_inputs())
        targets = torch.tensor([[0.51, 0.52, 0.51], [0.48, 0.55, 0.48], [0.59, 0.57, 0.57]])
        contact_targets = torch.rand(3, 7, 2)
        contact_mask = torch.ones(3, 7, 2, dtype=torch.bool)
        loss, parts = mod.compute_loss(
            output, targets, torch.ones(3), ["P", "P", "Q"],
            contact_targets, contact_mask, mod.ResidueLossConfig(),
        )
        self.assertTrue(torch.isfinite(loss))
        loss.backward()
        self.assertIsNotNone(model.head.contact_head[-1].weight.grad)
        self.assertIsNotNone(model.head.residual_head[-1].weight.grad)
        self.assertIn("contact_bce", parts)


if __name__ == "__main__":
    unittest.main()

