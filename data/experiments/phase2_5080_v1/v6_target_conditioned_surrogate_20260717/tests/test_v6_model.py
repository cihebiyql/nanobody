#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import torch


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
import v6_model as mod  # noqa: E402


class V6ModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tokenizer = mod.TinyResidueTokenizer()
        backbone = mod.TinyResidueBackbone(len(self.tokenizer), 24)
        config = mod.V6ModelConfig(structure_dim=126, fusion_dim=32, dropout=0.0, uncertainty_head=True, contact_head=True)
        self.model = mod.V6MultitaskModel(backbone, 24, config)

    def batch(self) -> dict[str, torch.Tensor]:
        encoded = self.tokenizer(["ACDEFG", "HIKLMN"], return_special_tokens_mask=True)
        residue_mask = encoded["attention_mask"].bool() & ~encoded["special_tokens_mask"].bool()
        return {**encoded, "residue_mask": residue_mask, "structure_features": torch.randn(2, 126)}

    def test_parent_folds_never_split_parent(self) -> None:
        groups = [f"P{i}" for i in range(9) for _ in range(i % 3 + 1)]
        folds = mod.build_parent_folds(groups, 3, seed=11)
        for fold in folds:
            inside = {groups[index] for index in fold}
            outside = {groups[index] for index in range(len(groups)) if index not in set(fold)}
            self.assertFalse(inside & outside)

    def test_model_outputs_are_bounded_residuals(self) -> None:
        batch = self.batch()
        output = self.model(
            input_ids=batch["input_ids"], attention_mask=batch["attention_mask"],
            residue_mask=batch["residue_mask"], structure_features=batch["structure_features"],
        )
        self.assertEqual(output["prediction"].shape, (2, 3))
        self.assertEqual(output["contact_logits"].shape, batch["input_ids"].shape)
        self.assertTrue(torch.all(output["residual"].abs() <= self.model.config.residual_scale + 1e-7))
        self.assertTrue(torch.allclose(output["prediction"], output["m2_prediction"] + output["residual"]))

    def test_multitask_loss_supports_weight_contact_uncertainty_and_ranking(self) -> None:
        batch = self.batch()
        output = self.model(
            input_ids=batch["input_ids"], attention_mask=batch["attention_mask"],
            residue_mask=batch["residue_mask"], structure_features=batch["structure_features"],
        )
        targets = torch.tensor([[0.5, 0.6, 0.5], [0.6, 0.7, 0.6]])
        contact = torch.zeros_like(output["contact_logits"])
        mask = batch["residue_mask"]
        config = mod.V6LossConfig(contact_weight=0.2, ranking_weight=0.1, uncertainty_weight=0.1)
        loss, parts = mod.compute_multitask_loss(
            output, targets, torch.tensor([1.0, 0.5]), ["P", "P"], config,
            contact_targets=contact, contact_mask=mask,
        )
        self.assertTrue(torch.isfinite(loss))
        self.assertEqual(set(("contact_bce", "ranking", "uncertainty_nll")) - set(parts), set())
        loss.backward()
        self.assertTrue(any(parameter.grad is not None for parameter in self.model.parameters()))

    def test_hf_loader_fails_closed_without_local_path(self) -> None:
        with self.assertRaisesRegex(mod.V6Error, "local_model_path_missing"):
            mod.HuggingFaceResidueBackbone.from_local(Path("/definitely/missing/model"))


if __name__ == "__main__":
    unittest.main()

