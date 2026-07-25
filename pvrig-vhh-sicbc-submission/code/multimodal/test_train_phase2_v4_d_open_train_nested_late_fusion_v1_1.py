import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).with_name("train_phase2_v4_d_open_train_nested_late_fusion_v1_1.py")
SPEC = importlib.util.spec_from_file_location("trainer", MODULE_PATH)
trainer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = trainer
SPEC.loader.exec_module(trainer)


class NestedTrainerTests(unittest.TestCase):
    def make_data(self):
        rng = np.random.default_rng(17)
        groups = [f"G{group:02d}" for group in range(9) for _ in range(6)]
        n = len(groups)
        latent = rng.normal(size=n)
        structure = np.column_stack((latent + rng.normal(scale=0.05, size=n), rng.normal(size=(n, 3))))
        sequence = rng.normal(size=(n, 7))
        sequence[:, 0] = 0.25 * latent + rng.normal(scale=0.8, size=n)
        y = 0.55 + 0.08 * latent + rng.normal(scale=0.01, size=n)
        return sequence, structure, y, groups

    def test_group_folds_have_no_parent_overlap(self):
        _sequence, _structure, _y, groups = self.make_data()
        folds = trainer.build_group_folds(groups, 3)
        for held in folds:
            held_set = set(held.tolist())
            self.assertFalse(
                {groups[index] for index in held_set}
                & {groups[index] for index in range(len(groups)) if index not in held_set}
            )

    def test_nested_oof_is_complete_finite_and_structure_informative(self):
        sequence, structure, y, groups = self.make_data()
        result = trainer.nested_oof(
            sequence, structure, y, groups,
            alphas=(0.1, 1.0, 10.0), weights=(0.0, 0.5, 1.0), gammas=(0.0, 0.5, 1.0),
            outer_folds=3, inner_folds=3, sub_inner_folds=3,
        )
        self.assertEqual(set(result.predictions), set(trainer.MODELS))
        self.assertTrue(all(np.isfinite(value).all() for value in result.predictions.values()))
        self.assertEqual(set(result.outer_fold.tolist()), {0, 1, 2})
        m1 = trainer.metrics(y, result.predictions["M1_sequence_only"])["spearman"]
        m2 = trainer.metrics(y, result.predictions["M2_structure_only"])["spearman"]
        self.assertGreater(m2, m1)

    def test_residual_meta_removes_inner_validation_before_sub_inner_targets(self):
        sequence, structure, y, groups = self.make_data()
        components = trainer.prepare_residual_meta_components(
            sequence, structure, y, groups, (0.1, 1.0), 3, 3
        )
        self.assertEqual(len(components), 3)
        self.assertEqual(sorted(index for item in components for index in item.held.tolist()), list(range(len(y))))
        for item in components:
            self.assertEqual(len(item.residual_target), int(item.keep.sum()))
            self.assertTrue(np.isfinite(item.residual_target).all())

    def test_group_bootstrap_is_deterministic(self):
        sequence, structure, y, groups = self.make_data()
        a = structure[:, 0]
        b = sequence[:, 0]
        first = trainer.paired_group_bootstrap_delta(y, a, b, groups, replicates=50, seed=3)
        second = trainer.paired_group_bootstrap_delta(y, a, b, groups, replicates=50, seed=3)
        self.assertEqual(first, second)
        self.assertEqual(first["resampling_unit"], "parent_framework_cluster")

    def test_refuses_too_few_groups(self):
        with self.assertRaisesRegex(trainer.TrainingError, "too_few_groups"):
            trainer.build_group_folds(["A", "A", "B", "B"], 3)


if __name__ == "__main__":
    unittest.main()
