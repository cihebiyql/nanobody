#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import select_contact_loss_gradient_grid_v1 as v1  # noqa: E402
import select_contact_loss_gradient_grid_v2 as mod  # noqa: E402


RAW = {
    # Reconstructs the real V1 first-grid fractions to sufficient precision:
    # A=.0240, B=.0606, C=.1892, D=.2541.
    "A_DOMAIN": {"dual": 1.0, "receptor": 0.0, "marginal": 9.836, "ranking": 0.0, "residual": 0.0},
    "B_VHH3D": {"dual": 1.0, "receptor": 0.0, "marginal": 25.80, "ranking": 0.0, "residual": 0.0},
    "C_PATCH": {"dual": 1.0, "receptor": 0.0, "marginal": 93.35, "ranking": 0.0, "residual": 0.0},
    "D_FULL_PAIR": {"dual": 1.0, "receptor": 0.0, "marginal": 90.6, "ranking": 0.0, "residual": 0.0, "pair": 90.6},
}


def observations():
    return {
        lane: {
            "unweighted_gradient_l2_norm": dict(raw),
            "candidate_ids_sha256": "a" * 64,
            "teacher_source_counts": {v1.SOURCES[0]: 2, v1.SOURCES[1]: 6},
        }
        for lane, raw in RAW.items()
    }


def full_observation(lane: str) -> dict[str, object]:
    raw = RAW[lane]
    weights = {**v1.NONCONTACT_WEIGHTS, "marginal": 0.0025}
    if lane == "D_FULL_PAIR":
        weights["pair"] = 0.00125
    weighted = {name: weights[name] * value for name, value in raw.items()}
    denominator = sum(weighted.values())
    fractions = {name: value / denominator for name, value in weighted.items()}
    return {
        "schema_version": v1.OBSERVATION_SCHEMA,
        "lane": lane,
        "gradient_batch_index": 0,
        "gradient_batches_in_observation": 1,
        "optimizer_steps_before_observation": 0,
        "candidate_ids_sha256": "a" * 64,
        "candidate_count": 8,
        "teacher_source_counts": {v1.SOURCES[0]: 2, v1.SOURCES[1]: 6},
        "unweighted_gradient_l2_norm": raw,
        "component_weights": weights,
        "weighted_gradient_l2_norm": weighted,
        "weighted_gradient_fraction": fractions,
        "direct_contact_gradient_fraction": fractions["marginal"] + fractions.get("pair", 0.0),
        "open_only": True,
        "v4_f_test32_access_count": 0,
        "prediction_metrics_access_count": 0,
        "outer_fold": 0,
        "inner_fold": 0,
        "training_stage": "first_inner_selection_epoch0_first_batch",
    }


def write_results(root: Path) -> dict[str, Path]:
    result = {}
    for lane in v1.LANES:
        path = root / f"{lane}.json"
        path.write_text(json.dumps({
            "lane": lane,
            "outer": {"GLOBAL": {"spearman": 1.0}},
            "contact_gradient_calibration_observation": full_observation(lane),
        }, sort_keys=True))
        result[lane] = path
    return result


def args_for(paths: dict[str, Path], output: Path):
    values = []
    for lane in v1.LANES:
        values.extend(("--lane-result", f"{lane}={paths[lane]}"))
    values.extend(("--output-dir", str(output)))
    return mod.parser().parse_args(values)


class LaneSpecificGradientGridTests(unittest.TestCase):
    def test_expected_lane_specific_weights_are_selected(self) -> None:
        amendment, report = mod.build_calibration(observations(), {lane: "b" * 64 for lane in v1.LANES})
        self.assertEqual(amendment["lane_weights"], {
            "A_DOMAIN": {"marginal_contact_weight": 0.01, "pair_contact_weight": 0.005},
            "B_VHH3D": {"marginal_contact_weight": 0.0025, "pair_contact_weight": 0.00125},
            "C_PATCH": {"marginal_contact_weight": 0.000625, "pair_contact_weight": 0.0003125},
            "D_FULL_PAIR": {"marginal_contact_weight": 0.000625, "pair_contact_weight": 0.0003125},
        })
        self.assertEqual(amendment["calibration"]["lane_selected_grid_index"], {
            "A_DOMAIN": 5, "B_VHH3D": 3, "C_PATCH": 1, "D_FULL_PAIR": 1,
        })
        self.assertFalse(report["selection_used_prediction_metrics"])

    def test_grid_is_fixed_geometric_and_pair_is_half(self) -> None:
        amendment, _ = mod.build_calibration(observations(), {lane: "c" * 64 for lane in v1.LANES})
        self.assertEqual([row["marginal_contact_weight"] for row in amendment["calibration"]["grid"]], list(mod.GRID))
        self.assertTrue(all(row["pair_contact_weight"] == row["marginal_contact_weight"] / 2.0 for row in amendment["calibration"]["grid"]))

    def test_lane_without_passing_grid_fails_closed(self) -> None:
        values = observations()
        values["A_DOMAIN"]["unweighted_gradient_l2_norm"]["marginal"] = 0.00001
        with self.assertRaisesRegex(v1.CalibrationError, "A_DOMAIN"):
            mod.build_calibration(values, {lane: "d" * 64 for lane in v1.LANES})

    def test_run_binds_all_four_result_hashes_and_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = write_results(root)
            first, second = root / "first", root / "second"
            mod.run(args_for(paths, first))
            mod.run(args_for(paths, second))
            for name in ("CONTACT_LOSS_AMENDMENT_V2_2.json", "CONTACT_GRADIENT_CALIBRATION_REPORT_V2_2.json"):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
            amendment = json.loads((first / "CONTACT_LOSS_AMENDMENT_V2_2.json").read_text())
            self.assertEqual(amendment["calibration"]["input_hashes"], {
                lane: v1.sha256_file(paths[lane]) for lane in v1.LANES
            })

    def test_v1_observation_gates_still_reject_optimizer_or_v4f_access(self) -> None:
        for field in ("optimizer_steps_before_observation", "v4_f_test32_access_count"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                paths = write_results(root)
                payload = json.loads(paths["A_DOMAIN"].read_text())
                payload["contact_gradient_calibration_observation"][field] = 1
                paths["A_DOMAIN"].write_text(json.dumps(payload))
                with self.assertRaises(v1.CalibrationError):
                    mod.run(args_for(paths, root / "out"))
                self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main()
