import unittest

import torch

from . import observe_v2_4_multibatch_calibration_v2 as calibration


class MultiBatchCalibrationTests(unittest.TestCase):
    def unit_norms(self):
        return [
            {
                "batch_id": f"B{index:02d}", "batch_offset": index,
                "candidate_ids_sha256": f"{index:064x}",
                "scalar_gradient_l2_norm": 9.0 + index,
                "unit_contact_gradient_l2_norm": 1.0,
                "scalar_contact_cosine": 0.0,
                "parameter_groups": {
                    group: {
                        "parameter_tensor_count": 1,
                        "gradient_l2_norm": {"scalar": 1.0, "contact": 0.5},
                        "scalar_contact_cosine": 0.0,
                    }
                    for group in calibration.GRADIENT_GROUPS
                },
            }
            for index in range(8)
        ]

    def test_even_offsets_are_deterministic_complete_and_unique(self):
        observed = calibration.evenly_spaced_complete_batch_offsets(1269, 8, 8)
        self.assertEqual(observed, [0, 22, 44, 67, 89, 112, 134, 157])
        self.assertEqual(len(set(observed)), 8)

    def test_candidate_digest_is_order_sensitive(self):
        left = calibration.canonical_candidate_ids_sha256(["A", "B"])
        right = calibration.canonical_candidate_ids_sha256(["B", "A"])
        self.assertNotEqual(left, right)

    def test_smallest_weight_with_median_and_max_gate_is_selected(self):
        observations, selected = calibration.summarize_grid_observations(
            grid=[0.5, 1.0, 2.0],
            per_batch_unit_norms=self.unit_norms(),
            pair_to_marginal_ratio=0.5,
            median_band=[0.05, 0.15],
            maximum_fraction=0.30,
            lane="D_SPLIT_PAIR",
        )
        self.assertEqual(selected, {"marginal": 1.0, "pair": 0.5})
        self.assertEqual(len(observations), 3)
        self.assertTrue(observations[1]["eligible"])
        self.assertEqual(len(observations[1]["per_batch"]), 8)
        groups = observations[1]["per_batch"][0]["gradient_groups"]
        self.assertEqual(set(groups), set(calibration.GRADIENT_GROUPS))
        self.assertEqual(groups["pair_factors"]["contact_gradient_l2_norm"], 0.5)

    def test_grouped_telemetry_uses_same_gradient_calls_for_all_groups(self):
        shared = torch.nn.Parameter(torch.tensor([1.0]))
        pair = torch.nn.Parameter(torch.tensor([2.0]))
        attention_terminal = torch.nn.Parameter(torch.tensor([3.0]))
        scalar_head = torch.nn.Parameter(torch.tensor([4.0]))
        named = [
            ("head.vhh_graph_encoder.weight", shared),
            ("head.interaction.vhh_left.weight", pair),
            ("head.interaction.contact_terminal", attention_terminal),
            ("head.scalar_head.0.weight", scalar_head),
        ]
        scalar = (
            shared.square().sum() + pair.square().sum()
            + attention_terminal.square().sum() + scalar_head.square().sum()
        )
        contact = (
            2 * shared.square().sum() + 3 * pair.square().sum()
            + 4 * attention_terminal.square().sum() + 5 * scalar_head.square().sum()
        )
        telemetry = calibration.grouped_component_gradient_telemetry(
            {"scalar": scalar, "contact": contact}, named,
        )
        self.assertEqual(set(telemetry["parameter_groups"]), set(calibration.GRADIENT_GROUPS))
        self.assertEqual(
            telemetry["parameter_groups"]["pair_factors"]["parameter_tensor_count"], 1,
        )
        self.assertAlmostEqual(
            telemetry["parameter_groups"]["attention_contact_terminals"]["gradient_l2_norm"]["contact"],
            24.0,
        )
        self.assertAlmostEqual(
            telemetry["parameter_groups"]["scalar_head"]["gradient_l2_norm"]["contact"],
            40.0,
        )

    def test_maximum_gate_can_reject_median_eligible_weight(self):
        norms = self.unit_norms()
        norms[0] = {**norms[0], "unit_contact_gradient_l2_norm": 8.0}
        observations, selected = calibration.summarize_grid_observations(
            grid=[0.75, 1.0, 2.0],
            per_batch_unit_norms=norms,
            pair_to_marginal_ratio=0.5,
            median_band=[0.05, 0.15],
            maximum_fraction=0.45,
            lane="C_SPLIT_MARGINAL",
        )
        self.assertFalse(observations[1]["eligible"])
        self.assertEqual(selected["marginal"], 0.75)

    def test_no_eligible_weight_fails_closed(self):
        with self.assertRaisesRegex(
            calibration.MultiBatchCalibrationError,
            "calibration_no_grid_value_satisfies_multibatch_rule",
        ):
            calibration.summarize_grid_observations(
                grid=[0.01, 0.02],
                per_batch_unit_norms=self.unit_norms(),
                pair_to_marginal_ratio=0.5,
                median_band=[0.05, 0.15],
                maximum_fraction=0.30,
                lane="C_SPLIT_MARGINAL",
            )


if __name__ == "__main__":
    unittest.main()
