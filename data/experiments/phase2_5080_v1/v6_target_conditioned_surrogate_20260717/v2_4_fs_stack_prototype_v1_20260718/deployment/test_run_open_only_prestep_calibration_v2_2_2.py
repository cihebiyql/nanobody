import importlib.util
import pathlib
import unittest


HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("calibration_v2_2_2", HERE / "run_open_only_prestep_calibration_v2_2_2.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class CalibrationCommandV221Tests(unittest.TestCase):
    def test_calibration_wrapper_is_not_overwritten_by_base_trainer_artifact(self) -> None:
        records = [
            {
                "batch_id": f"B{i:02d}", "batch_offset": i,
                "candidate_ids_sha256": f"{i:064x}",
            }
            for i in range(8)
        ]
        manifest = {
            "python": "/python",
            "artifacts": {
                "trainer": {"node1_path": "/base_trainer.py"},
                "calibration_trainer": {"node1_path": "/multibatch_wrapper.py"},
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
                "fixed_grid": [1.0], "pair_to_marginal_ratio": 0.5,
                "target_median_gradient_fraction_band": [0.05, 0.15],
                "maximum_per_batch_gradient_fraction": 0.3,
                "batch_selection": {"batch_records": records},
            },
        }
        command = MODULE.calibration_command(
            manifest, lane="C_SPLIT_MARGINAL", output_dir=pathlib.Path("/out"),
        )
        self.assertEqual(command[1], "/multibatch_wrapper.py")
        self.assertNotEqual(command[1], "/base_trainer.py")
        self.assertEqual(MODULE.SUPERSESSION_VERSION, "V2.2_CLAIM_BOUNDARY_ALIGNMENT_ONLY")
        self.assertEqual(MODULE.EXPECTED_SELECTED_WEIGHTS["C_SPLIT_MARGINAL"], {"marginal": 1.5, "pair": 0.0})

    def test_pending_manifest_status_matches_v2_2_launcher_contract(self) -> None:
        self.assertEqual(
            MODULE.PENDING_STATUS,
            "PREFREEZE_V2_2_2_ADAPTIVE_MULTI_SEED_CALIBRATION_PENDING_DO_NOT_START",
        )


if __name__ == "__main__":
    unittest.main()
