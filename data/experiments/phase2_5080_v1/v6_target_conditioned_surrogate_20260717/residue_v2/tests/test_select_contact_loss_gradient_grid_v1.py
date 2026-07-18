#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import select_contact_loss_gradient_grid_v1 as mod  # noqa: E402


def observation(lane: str, marginal_raw: float, pair_raw: float = 0.0) -> dict[str, object]:
    components = {
        "dual": 1.0,
        "receptor": 0.0,
        "marginal": marginal_raw,
        "ranking": 0.0,
        "residual": 0.0,
    }
    weights = {**mod.NONCONTACT_WEIGHTS, "marginal": 0.0001}
    if lane == "D_FULL_PAIR":
        components["pair"] = pair_raw
        weights["pair"] = 0.00005
    denominator = sum(abs(weights[name]) * components[name] for name in components)
    fractions = {
        name: abs(weights[name]) * components[name] / denominator
        for name in components
    }
    return {
        "schema_version": mod.OBSERVATION_SCHEMA,
        "lane": lane,
        "gradient_batch_index": 0,
        "gradient_batches_in_observation": 1,
        "optimizer_steps_before_observation": 0,
        "candidate_ids_sha256": "a" * 64,
        "candidate_count": 8,
        "teacher_source_counts": {mod.SOURCES[0]: 2, mod.SOURCES[1]: 6},
        "unweighted_gradient_l2_norm": components,
        "component_weights": weights,
        "weighted_gradient_l2_norm": {
            name: abs(weights[name]) * components[name] for name in components
        },
        "weighted_gradient_fraction": fractions,
        "direct_contact_gradient_fraction": fractions["marginal"] + fractions.get("pair", 0.0),
        "open_only": True,
        "v4_f_test32_access_count": 0,
        "prediction_metrics_access_count": 0,
        "outer_fold": 0,
        "inner_fold": 1,
        "training_stage": "first_inner_selection_epoch0_first_batch",
    }


def write_results(root: Path, *, marginal_raw: float, d_pair_raw: float | None = None) -> dict[str, Path]:
    paths = {}
    for lane in mod.LANES:
        path = root / f"{lane}.json"
        path.write_text(json.dumps({
            "schema_version": "synthetic_result",
            "status": "PASS_OUTER_FOLD_COMPLETE",
            "lane": lane,
            # Prediction metrics can coexist in RESULT.json but are never read
            # by the selector.
            "outer": {"GLOBAL": {"spearman": 0.999}},
            "contact_gradient_calibration_observation": observation(
                lane, marginal_raw, d_pair_raw if lane == "D_FULL_PAIR" and d_pair_raw is not None else marginal_raw,
            ),
        }, sort_keys=True))
        paths[lane] = path
    return paths


def args_for(paths: dict[str, Path], output: Path):
    return mod.parser().parse_args([
        *sum((["--lane-result", f"{lane}={paths[lane]}"] for lane in mod.LANES), []),
        "--output-dir", str(output),
    ])


class ContactGradientGridTests(unittest.TestCase):
    def test_selects_smallest_passing_grid_and_emits_amendment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = write_results(root, marginal_raw=25.0, d_pair_raw=20.0)
            output = root / "out"
            result = mod.run(args_for(paths, output))
            self.assertEqual(result["selected_weights"], {
                "marginal_contact_weight": 0.0025,
                "pair_contact_weight": 0.00125,
            })
            amendment = json.loads((output / "CONTACT_LOSS_AMENDMENT_V1.json").read_text())
            self.assertEqual(amendment["calibration"]["selected_grid_index"], 0)
            self.assertFalse(json.loads((output / "CONTACT_GRADIENT_CALIBRATION_REPORT_V1.json").read_text())["selection_used_prediction_metrics"])

    def test_selects_second_grid_when_first_is_below_band(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = write_results(root, marginal_raw=12.0, d_pair_raw=10.0)
            output = root / "out"
            mod.run(args_for(paths, output))
            amendment = json.loads((output / "CONTACT_LOSS_AMENDMENT_V1.json").read_text())
            self.assertEqual(amendment["calibration"]["selected_grid_index"], 1)

    def test_hard_ceiling_or_no_target_band_fails_without_output(self) -> None:
        for raw in (0.01, 1000.0):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                paths = write_results(root, marginal_raw=raw, d_pair_raw=raw)
                output = root / "out"
                with self.assertRaisesRegex(mod.CalibrationError, "no_grid_entry"):
                    mod.run(args_for(paths, output))
                self.assertFalse(output.exists())

    def test_post_optimizer_observation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = write_results(root, marginal_raw=25.0, d_pair_raw=20.0)
            payload = json.loads(paths["A_DOMAIN"].read_text())
            payload["contact_gradient_calibration_observation"]["optimizer_steps_before_observation"] = 1
            paths["A_DOMAIN"].write_text(json.dumps(payload))
            with self.assertRaisesRegex(mod.CalibrationError, "post_optimizer"):
                mod.run(args_for(paths, root / "out"))

    def test_v4f_or_prediction_metric_access_is_rejected(self) -> None:
        for field in ("v4_f_test32_access_count", "prediction_metrics_access_count"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                paths = write_results(root, marginal_raw=25.0, d_pair_raw=20.0)
                payload = json.loads(paths["B_VHH3D"].read_text())
                payload["contact_gradient_calibration_observation"][field] = 1
                paths["B_VHH3D"].write_text(json.dumps(payload))
                with self.assertRaises(mod.CalibrationError):
                    mod.run(args_for(paths, root / "out"))

    def test_missing_lane_or_component_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = write_results(root, marginal_raw=25.0, d_pair_raw=20.0)
            with self.assertRaisesRegex(mod.CalibrationError, "lane_result_closure"):
                mod.parse_lane_results([f"{lane}={path}" for lane, path in paths.items() if lane != "C_PATCH"])
            payload = json.loads(paths["D_FULL_PAIR"].read_text())
            del payload["contact_gradient_calibration_observation"]["unweighted_gradient_l2_norm"]["pair"]
            paths["D_FULL_PAIR"].write_text(json.dumps(payload))
            with self.assertRaisesRegex(mod.CalibrationError, "raw_component_closure"):
                mod.run(args_for(paths, root / "out"))

    def test_output_is_deterministic_for_identical_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = write_results(root, marginal_raw=25.0, d_pair_raw=20.0)
            first = root / "first"
            second = root / "second"
            mod.run(args_for(paths, first))
            mod.run(args_for(paths, second))
            for name in ("CONTACT_LOSS_AMENDMENT_V1.json", "CONTACT_GRADIENT_CALIBRATION_REPORT_V1.json"):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
