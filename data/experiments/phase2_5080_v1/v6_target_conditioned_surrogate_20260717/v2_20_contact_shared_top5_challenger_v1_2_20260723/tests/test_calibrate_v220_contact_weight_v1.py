from __future__ import annotations

import importlib.util
import random
import sys
import unittest
from pathlib import Path

import torch
from torch import nn


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "calibrate_v220_contact_weight_v1.py"
)
SPEC = importlib.util.spec_from_file_location("v220_contact_calibration", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class SyntheticModel(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.shared = nn.Parameter(torch.tensor([0.25, -0.5], dtype=torch.float64))


class SyntheticTrainer:
    def shared_parameters(self, model: SyntheticModel):
        return [("shared", model.shared)]

    def calibration_losses(
        self, model, payload, target_graphs, device, precision
    ):
        scalar = torch.dot(model.shared, payload["scalar"])
        marginal = torch.dot(model.shared, payload["marginal"])
        pair = torch.dot(model.shared, payload["pair"])
        return scalar, marginal, pair


def make_batch(index: int, contact, *, eligible=True, outer_fit=True):
    return {
        "batch_id": f"b{index}",
        "outer_fit": outer_fit,
        "contact_eligible": eligible,
        "payload": {
            "scalar": torch.tensor([1.0, 0.0], dtype=torch.float64),
            "marginal": torch.tensor(contact[0], dtype=torch.float64),
            "pair": torch.tensor(contact[1], dtype=torch.float64),
        },
    }


class ContactCalibrationTests(unittest.TestCase):
    def test_first_eight_eligible_are_selected_without_reordering(self) -> None:
        batches = [make_batch(0, ([80.0, 0.0], [0.0, 0.0]), eligible=False)]
        batches.extend(make_batch(i, ([80.0, 0.0], [0.0, 0.0])) for i in range(1, 11))
        receipt = mod.calibrate_contact_weight(
            SyntheticModel(), SyntheticTrainer(), batches, {}, "cpu", "fp32"
        )
        self.assertEqual(receipt["selected_batch_ids"], [f"b{i}" for i in range(1, 9)])

    def test_pair_coefficient_and_smallest_in_interval_select_000625(self) -> None:
        # g_contact = 0 + 0.5 * [160, 0] = [80, 0]
        batches = [
            make_batch(i, ([0.0, 0.0], [160.0, 0.0])) for i in range(8)
        ]
        receipt = mod.calibrate_contact_weight(
            SyntheticModel(), SyntheticTrainer(), batches, None, "cpu", "fp32"
        )
        self.assertEqual(receipt["selected_contact_weight"], 0.000625)
        self.assertFalse(receipt["fallback_to_closest_target"])
        self.assertEqual(
            receipt["gradient_definition"],
            "g_contact = grad_shared(L_marginal + 0.5 * L_pair)",
        )
        self.assertAlmostEqual(
            receipt["observations"][0]["contact_gradient_l2"], 80.0
        )

    def test_fallback_chooses_closest_to_point_one(self) -> None:
        selected, medians, fallback = mod.choose_contact_weight([10.0] * 8)
        self.assertEqual(selected, 0.0025)
        self.assertTrue(fallback)
        self.assertAlmostEqual(medians["0.0025"], 0.025)

    def test_three_severe_conflicts_fail_prelaunch(self) -> None:
        batches = []
        for i in range(8):
            contact = [-80.0, 0.0] if i < 3 else [80.0, 0.0]
            batches.append(make_batch(i, (contact, [0.0, 0.0])))
        with self.assertRaises(mod.ContactCalibrationPrelaunchError) as context:
            mod.calibrate_contact_weight(
                SyntheticModel(), SyntheticTrainer(), batches, None, "cpu", "fp32"
            )
        self.assertEqual(context.exception.result["severe_conflict_batch_count"], 3)
        self.assertEqual(
            context.exception.result["status"], "FAIL_PRELAUNCH_GRADIENT_CONFLICT"
        )

    def test_exactly_two_severe_conflicts_pass(self) -> None:
        batches = []
        for i in range(8):
            contact = [-80.0, 0.0] if i < 2 else [80.0, 0.0]
            batches.append(make_batch(i, (contact, [0.0, 0.0])))
        receipt = mod.calibrate_contact_weight(
            SyntheticModel(), SyntheticTrainer(), batches, None, "cpu", "bf16"
        )
        self.assertEqual(receipt["severe_conflict_batch_count"], 2)
        self.assertTrue(receipt["status"].startswith("PASS"))

    def test_model_rng_and_grad_state_are_unchanged(self) -> None:
        model = SyntheticModel()
        before_hash = mod.model_state_sha256(model)
        random.seed(701)
        torch.manual_seed(702)
        python_before = random.getstate()
        torch_before = torch.get_rng_state().clone()
        batches = [
            make_batch(i, ([80.0, 0.0], [0.0, 0.0])) for i in range(8)
        ]
        receipt = mod.calibrate_contact_weight(
            model, SyntheticTrainer(), batches, None, "cpu", "fp32"
        )
        self.assertEqual(before_hash, mod.model_state_sha256(model))
        self.assertEqual(python_before, random.getstate())
        self.assertTrue(torch.equal(torch_before, torch.get_rng_state()))
        self.assertIsNone(model.shared.grad)
        self.assertFalse(receipt["optimizer_created"])
        self.assertEqual(receipt["optimizer_steps"], 0)
        self.assertFalse(receipt["training_started"])

    def test_outer_fit_and_fixed_grid_fail_closed(self) -> None:
        batches = [
            make_batch(i, ([80.0, 0.0], [0.0, 0.0]), outer_fit=(i != 2))
            for i in range(8)
        ]
        with self.assertRaises(mod.ContactCalibrationError):
            mod.calibrate_contact_weight(
                SyntheticModel(), SyntheticTrainer(), batches, None, "cpu", "fp32"
            )
        good = [make_batch(i, ([80.0, 0.0], [0.0, 0.0])) for i in range(8)]
        with self.assertRaises(mod.ContactCalibrationError):
            mod.calibrate_contact_weight(
                SyntheticModel(),
                SyntheticTrainer(),
                good,
                None,
                "cpu",
                "fp32",
                grid=(0.1,),
            )

    def test_zero_contact_gradient_fails(self) -> None:
        batches = [make_batch(i, ([0.0, 0.0], [0.0, 0.0])) for i in range(8)]
        with self.assertRaises(mod.ContactCalibrationError):
            mod.calibrate_contact_weight(
                SyntheticModel(), SyntheticTrainer(), batches, None, "cpu", "fp32"
            )


if __name__ == "__main__":
    unittest.main()
