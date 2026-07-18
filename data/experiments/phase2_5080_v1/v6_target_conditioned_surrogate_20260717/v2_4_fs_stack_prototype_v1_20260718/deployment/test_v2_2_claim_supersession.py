import json
import pathlib
import unittest

from ..trainer import observe_v2_4_multibatch_calibration_v2_2 as wrapper
from ..trainer import train_v2_4_base_split as base
from . import build_prefreeze_manifest_v2_2 as builder
from . import materialize_postcalibration_freeze_v2_2 as materializer
from . import node1_v2_4_outer_development_launcher_v2_2 as launcher
from . import run_open_only_prestep_calibration_v2_2 as runner


HERE = pathlib.Path(__file__).resolve().parent
AUDIT = HERE / "V2_CALIBRATION_CLAIM_BOUNDARY_SUPERSESSION_V2_2.json"


class V22ClaimSupersessionTests(unittest.TestCase):
    def test_exact_claim_is_shared_and_base_claim_is_not_accepted(self) -> None:
        self.assertEqual(wrapper.CLAIM_BOUNDARY, materializer.CLAIM_BOUNDARY)
        self.assertEqual(wrapper.CLAIM_BOUNDARY, launcher.CLAIM_BOUNDARY)
        self.assertNotEqual(wrapper.CLAIM_BOUNDARY, base.CLAIM_BOUNDARY)
        self.assertEqual(wrapper.SUPERSESSION_VERSION, runner.SUPERSESSION_VERSION)
        self.assertEqual(wrapper.SUPERSESSION_VERSION, launcher.SUPERSESSION_VERSION)

    def test_v2_1_observed_weights_and_numeric_gates_are_frozen(self) -> None:
        payload = json.loads(AUDIT.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "SUPERSEDE_V2_1_WITH_V2_2_AFTER_EXACT_CLAIM_BOUNDARY_MISMATCH")
        numeric = payload["frozen_numeric_contract"]
        self.assertEqual(numeric["fixed_grid"], [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 7.5, 10.0])
        self.assertEqual(numeric["target_median_gradient_fraction_band"], [0.05, 0.15])
        self.assertEqual(numeric["maximum_per_batch_gradient_fraction"], 0.3)
        self.assertEqual(numeric["calibration_batch_count"], 8)
        self.assertEqual(numeric["numeric_method_changes"], 0)
        self.assertFalse(numeric["weight_changes_permitted"])
        self.assertEqual(payload["v2_1_observed_evidence"]["selected_contact_weights"], runner.EXPECTED_SELECTED_WEIGHTS)
        self.assertEqual(runner.EXPECTED_SELECTED_WEIGHTS, materializer.EXPECTED_CONTACT_WEIGHTS)

    def test_calibration_command_executes_v2_2_wrapper_not_base_trainer(self) -> None:
        records = [
            {"batch_id": f"B{i:02d}", "batch_offset": i, "candidate_ids_sha256": f"{i:064x}"}
            for i in range(8)
        ]
        manifest = {
            "python": "/python",
            "artifacts": {
                "trainer": {"node1_path": "/base_trainer.py"},
                "calibration_trainer": {"node1_path": "/claim_aligned_wrapper_v2_2.py"},
                "outer_split_0": {"node1_path": "/split.json"},
                "vhh_graph_cache_npz": {"node1_path": "/graphs/cache.npz"},
            },
            "trainer": {
                "artifact_label": "trainer",
                "calibration_artifact_label": "calibration_trainer",
                "argv_template": ["{python}", "{trainer}", "--lane", "{lane}", "--output-dir", "{output_dir}"],
                "frozen_noncalibration_parameters": {
                    "fixed_epochs": 8, "graph_hidden_dim": 128, "dropout": 0.25,
                    "batch_size": 8, "precision": "bf16",
                },
            },
            "calibration_contract": {
                "fixed_grid": [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 7.5, 10.0],
                "pair_to_marginal_ratio": 0.5,
                "target_median_gradient_fraction_band": [0.05, 0.15],
                "maximum_per_batch_gradient_fraction": 0.3,
                "batch_selection": {"batch_records": records},
            },
        }
        command = runner.calibration_command(
            manifest, lane="C_SPLIT_MARGINAL", output_dir=pathlib.Path("/out"),
        )
        self.assertEqual(command[1], "/claim_aligned_wrapper_v2_2.py")
        self.assertNotEqual(command[1], "/base_trainer.py")

    def test_builder_uses_new_immutable_roots(self) -> None:
        self.assertIn("_v2_2_", builder.BUNDLE)
        self.assertIn("_v2_2_", builder.CALIBRATION_RUNTIME)
        self.assertIn("_v2_2_", builder.RUNTIME)
        self.assertEqual(builder.MANIFEST_SCHEMA, launcher.MANIFEST_SCHEMA)


if __name__ == "__main__":
    unittest.main()
