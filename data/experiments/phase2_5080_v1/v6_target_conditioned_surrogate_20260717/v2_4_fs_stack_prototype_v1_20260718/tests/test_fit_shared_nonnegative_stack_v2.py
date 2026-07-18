#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "fit_shared_nonnegative_stack_v2.py"
SPEC = importlib.util.spec_from_file_location("fit_shared_nonnegative_stack_v2", MODULE_PATH)
assert SPEC and SPEC.loader
stack = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stack
SPEC.loader.exec_module(stack)


def rows(role, n=40):
    output = []
    for index in range(n):
        source = "V4D" if index < n // 2 else "V4H"
        parent = f"{source}_P{index % 5}"
        m8 = 0.05 + 0.9 * ((index * 7) % n) / n
        m9 = 0.05 + 0.9 * ((index * 11 + 3) % n) / n
        n8 = 0.1 + 0.8 * ((index * 13 + 1) % n) / n
        n9 = 0.1 + 0.8 * ((index * 17 + 2) % n) / n
        c8 = 0.15 + 0.7 * ((index * 19 + 4) % n) / n
        c9 = 0.15 + 0.7 * ((index * 23 + 5) % n) / n
        output.append({
            "evidence_role": role, "candidate_id": f"C{index}",
            "teacher_source": source, "parent_framework_cluster": parent,
            "outer_fold": "0", "M2_R8": repr(m8), "M2_R9": repr(m9),
            "neural_R8": repr(n8), "neural_R9": repr(n9),
            "contact_score_R8": repr(c8), "contact_score_R9": repr(c9),
            "R_8X6B": repr(0.2 + 0.5*m8 + 0.3*n8 + 0.2*c8),
            "R_9E6Y": repr(0.25 + 0.5*m9 + 0.3*n9 + 0.2*c9),
        })
    return output


class StackV2Tests(unittest.TestCase):
    def test_five_parameters_nonnegative_shared_slopes(self):
        model, audit = stack.fit_stack_v2(rows(stack.FIT_ROLE))
        self.assertEqual(model.parameter_count, 5)
        self.assertEqual(audit["parameter_count"], 5)
        self.assertTrue(np.all(model.theta()[2:] >= 0.0))

    def test_fixed_scaling_regularization_and_condition_ceiling_are_audited(self):
        _, audit = stack.fit_stack_v2(rows(stack.FIT_ROLE))
        self.assertEqual(audit["fixed_ridge_alpha"], 1e-3)
        self.assertEqual(audit["fixed_condition_number_ceiling"], 1e6)
        self.assertEqual(audit["scaling_contract"], stack.SCALING_CONTRACT)
        self.assertLessEqual(audit["observed_condition_number"], 1e6)
        self.assertEqual(audit["regularized_parameters"], ["beta_M2", "beta_neural", "beta_contact"])

    def test_scaling_is_shared_across_receptors(self):
        model, _ = stack.fit_stack_v2(rows(stack.FIT_ROLE))
        self.assertEqual(model.scaling.means().shape, (3,))
        self.assertEqual(model.scaling.scales().shape, (3,))
        self.assertTrue(np.all(model.scaling.scales() > 0))

    def test_condition_number_ceiling_rejects_collinear_design(self):
        data = rows(stack.FIT_ROLE)
        for row in data:
            row["neural_R8"] = row["M2_R8"]
            row["neural_R9"] = row["M2_R9"]
            row["contact_score_R8"] = row["M2_R8"]
            row["contact_score_R9"] = row["M2_R9"]
        with self.assertRaisesRegex(stack.StackV2Error, "condition_number_above_fixed_ceiling"):
            stack.fit_stack_v2(data)

    def test_constant_feature_rejected_before_fit(self):
        data = rows(stack.FIT_ROLE)
        for row in data:
            row["contact_score_R8"] = "0.5"
            row["contact_score_R9"] = "0.5"
        with self.assertRaisesRegex(stack.StackV2Error, "feature_scale_below_fixed_minimum:contact"):
            stack.fit_stack_v2(data)

    def test_prediction_dual_is_exact_min(self):
        model, _ = stack.fit_stack_v2(rows(stack.FIT_ROLE))
        predictions = stack.predict_stack_v2(model, rows(stack.SCORE_ROLE, n=10))
        for row in predictions:
            observed = np.float64(row["prediction_R_dual_min"])
            expected = np.minimum(np.float64(row["prediction_R8"]), np.float64(row["prediction_R9"]))
            self.assertEqual(observed.tobytes(), expected.tobytes())

    def test_fit_and_score_roles_cannot_be_swapped(self):
        with self.assertRaisesRegex(stack.StackV2Error, "evidence_role_mismatch"):
            stack.fit_stack_v2(rows(stack.SCORE_ROLE))


if __name__ == "__main__":
    unittest.main(verbosity=2)
