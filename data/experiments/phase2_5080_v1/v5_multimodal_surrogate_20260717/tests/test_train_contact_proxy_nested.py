from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).parents[1] / "src/train_contact_proxy_nested.py"
SPEC = importlib.util.spec_from_file_location("train_contact_proxy_nested", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class ContactProxyTests(unittest.TestCase):
    def test_contact_feature_allowlist_has_frozen_101_fields(self) -> None:
        fields = []
        for receptor in ("8x6b", "9e6y"):
            fields.extend(f"{receptor}_{base}" for base in MOD.CONTACT_BASES)
        for summary in ("dual_mean", "dual_min", "dual_abs_gap"):
            fields.extend(f"{summary}_{base}" for base in MOD.CONTACT_BASES)
        fields.append("dual_pvrig_profile_jsd")
        self.assertEqual(len(MOD.contact_feature_names(fields)), 101)

    def test_multi_ridge_returns_finite_multioutput_predictions(self) -> None:
        rng = np.random.default_rng(7)
        x = rng.normal(size=(30, 5))
        coefficient = rng.normal(size=(5, 3))
        y = x @ coefficient
        fitted = MOD.fit_multi_ridge(x, y, 0.1)
        prediction = MOD.predict_multi_ridge(x, fitted)
        self.assertEqual(prediction.shape, y.shape)
        self.assertTrue(np.isfinite(prediction).all())
        self.assertLess(float(np.mean((prediction - y) ** 2)), 0.01)

    def test_random_relu_mapping_is_deterministic(self) -> None:
        rng = np.random.default_rng(11)
        x = rng.normal(size=(20, 7))
        first = MOD.transform_random_relu(x, MOD.fit_random_relu_map(x))
        second = MOD.transform_random_relu(x, MOD.fit_random_relu_map(x))
        np.testing.assert_allclose(first, second)
        self.assertEqual(first.shape[1], 7 + len(MOD.RANDOM_SEEDS) * MOD.UNITS_PER_SEED)

    def test_nested_evaluate_is_parent_group_closed(self) -> None:
        original = (MOD.ALPHAS, MOD.RANDOM_SEEDS, MOD.UNITS_PER_SEED)
        MOD.ALPHAS = (1.0, 10.0)
        MOD.RANDOM_SEEDS = (101,)
        MOD.UNITS_PER_SEED = 8
        try:
            rng = np.random.default_rng(13)
            groups = [f"P{index // 5:02d}" for index in range(50)]
            structure = rng.normal(size=(50, 6))
            physchem = rng.normal(size=(50, 3))
            contact = np.column_stack([
                np.maximum(structure[:, 0] + 0.2 * structure[:, 1], 0.0),
                np.maximum(physchem[:, 0] - structure[:, 2], 0.0),
                structure[:, 3] ** 2,
                physchem[:, 1] ** 2,
            ])
            y = 0.5 * structure[:, 0] + 0.3 * contact[:, 0] - 0.2 * contact[:, 1]
            rows = [
                {
                    "candidate_id": f"C{index:03d}",
                    "sequence_sha256": f"S{index:03d}",
                    "parent_framework_cluster": groups[index],
                }
                for index in range(50)
            ]
            dataset = MOD.v5.Dataset(
                rows=rows,
                structure_x=structure,
                physchem_x=physchem,
                structure_feature_names=[f"f{index}" for index in range(6)],
                y8=y + 0.01,
                y9=y + 0.02,
                ydual=y,
                ygap=np.full(50, 0.01),
                groups=groups,
            )
            predictions, outer_fold, audit, contact_prediction = MOD.nested_evaluate(dataset, contact)
            self.assertEqual(set(predictions), set(MOD.MODELS))
            self.assertTrue(all(np.isfinite(value).all() for value in predictions.values()))
            self.assertTrue(np.isfinite(contact_prediction).all())
            self.assertEqual(set(outer_fold.tolist()), {0, 1, 2, 3, 4})
            for fold in audit:
                held = set(fold["held_parent_clusters"])
                self.assertTrue(held)
        finally:
            MOD.ALPHAS, MOD.RANDOM_SEEDS, MOD.UNITS_PER_SEED = original


if __name__ == "__main__":
    unittest.main()
