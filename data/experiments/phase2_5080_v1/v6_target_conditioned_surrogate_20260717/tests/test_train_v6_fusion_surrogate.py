import importlib.util
import pathlib
import unittest

import numpy as np
import torch

MODULE = pathlib.Path(__file__).parents[1] / "src" / "train_v6_fusion_surrogate.py"
spec = importlib.util.spec_from_file_location("v6_train", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


class TestV6Trainer(unittest.TestCase):
    def test_model_shape_and_bound(self):
        model = mod.FusionResidualModel(32, 8, 16, 0.0, 0.12)
        base = torch.full((5, 3), 0.5)
        pred, logvar, top = model(torch.randn(5, 32), torch.randn(5, 8), base)
        self.assertEqual(tuple(pred.shape), (5, 3))
        self.assertEqual(tuple(logvar.shape), (5,))
        self.assertEqual(tuple(top.shape), (5,))
        self.assertTrue(torch.all(torch.abs(pred - base) <= 0.120001))

    def test_ranking_loss_prefers_correct_order(self):
        target = torch.tensor([[0.0, 0.0, 0.8], [0.0, 0.0, 0.5]])
        good = torch.tensor([[0.0, 0.0, 0.7], [0.0, 0.0, 0.4]])
        bad = torch.tensor([[0.0, 0.0, 0.4], [0.0, 0.0, 0.7]])
        self.assertLess(mod.ranking_loss(good, target, ["P", "P"]), mod.ranking_loss(bad, target, ["P", "P"]))

    def test_metrics(self):
        y = np.array([0.1, 0.2, 0.3, 0.4])
        value = mod.metrics(y, y.copy(), ["A", "A", "B", "B"])
        self.assertAlmostEqual(value["spearman"], 1.0)
        self.assertAlmostEqual(value["mae"], 0.0)


if __name__ == "__main__":
    unittest.main()
