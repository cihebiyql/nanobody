from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path

from . import build_prefreeze_manifest_v2_2_2 as builder
from . import materialize_node1_bundle_v2_2_2 as bundle
from . import materialize_postcalibration_freeze_v2_2_2 as postcal
from . import node1_v2_4_outer_development_launcher_v2_2_2 as launcher
from . import run_open_only_prestep_calibration_v2_2_2 as runner


class V222CanonicalClosureTests(unittest.TestCase):
    def test_manifest_schema_and_pending_status_close_across_entrypoints(self) -> None:
        self.assertEqual(builder.MANIFEST_SCHEMA, launcher.MANIFEST_SCHEMA)
        self.assertEqual(builder.MANIFEST_SCHEMA, postcal.MANIFEST_SCHEMA)
        self.assertEqual(builder.MANIFEST_STATUS, runner.PENDING_STATUS)
        self.assertEqual(builder.MANIFEST_STATUS, bundle.PENDING_STATUS)
        self.assertEqual(builder.MANIFEST_STATUS, postcal.PENDING_STATUS)
        self.assertEqual(builder.BUNDLE_REVISION, launcher.BUNDLE_REVISION)
        self.assertEqual(builder.BUNDLE_REVISION, postcal.BUNDLE_REVISION)
        self.assertEqual(launcher.FREEZE_SCHEMA, postcal.FREEZE_SCHEMA)
        self.assertEqual(builder.TRAINER_RESULT_CLAIM_BOUNDARY, launcher.TRAINER_RESULT_CLAIM_BOUNDARY)
        self.assertEqual(builder.TRAINER_RESULT_CLAIM_BOUNDARY, postcal.TRAINER_RESULT_CLAIM_BOUNDARY)

    def test_calibration_receipt_schema_and_status_close(self) -> None:
        self.assertEqual(runner.CALIBRATION_SCHEMA, launcher.CALIBRATION_SCHEMA)
        self.assertEqual(runner.CALIBRATION_SCHEMA, postcal.CALIBRATION_SCHEMA)
        self.assertEqual(runner.CALIBRATION_STATUS, launcher.CALIBRATION_STATUS)
        self.assertEqual(runner.CALIBRATION_STATUS, postcal.CALIBRATION_STATUS)

    def test_bundle_receipt_requires_both_claims_and_revision(self) -> None:
        manifest = {
            "claim_boundary": launcher.CLAIM_BOUNDARY,
            "trainer_result_claim_boundary": launcher.TRAINER_RESULT_CLAIM_BOUNDARY,
        }
        baseline = {
            **manifest,
            "bundle_revision": launcher.BUNDLE_REVISION,
        }
        bundle.validate_bundle_receipt(baseline, manifest)
        for field, error in (
            ("claim_boundary", "bundle_receipt_claim_boundary"),
            ("trainer_result_claim_boundary", "bundle_receipt_trainer_result_claim_boundary"),
            ("bundle_revision", "bundle_receipt_bundle_revision"),
        ):
            with self.subTest(field=field):
                tampered = dict(baseline)
                tampered[field] = "tampered"
                with self.assertRaisesRegex(bundle.deployment.DeploymentError, error):
                    bundle.validate_bundle_receipt(tampered, manifest)

    def test_v2_2_2_canonical_filenames_close(self) -> None:
        self.assertEqual(bundle.MANIFEST_NAME, "V2_4_NODE1_PREFREEZE_MANIFEST_V2_2_2.json")
        self.assertEqual(launcher.FREEZE_NAME, "IMPLEMENTATION_FREEZE_V2_4_ADAPTIVE_V2_2_2.json")
        source = inspect.getsource(postcal.materialize)
        self.assertIn("V2_4_NODE1_PREFREEZE_MANIFEST_V2_2_2.json", source)
        self.assertIn("V2_4_NODE1_READY_MANIFEST_V2_2_2.json", source)
        self.assertIn("IMPLEMENTATION_FREEZE_V2_4_ADAPTIVE_V2_2_2.json", source)
        self.assertNotIn('bundle_root / "V2_4_NODE1_PREFREEZE_MANIFEST_V2_2.json"', source)

    def test_runner_has_no_stale_v2_pending_status_literal(self) -> None:
        source = inspect.getsource(runner)
        self.assertNotIn("PREFREEZE_V2_ADAPTIVE_MULTI_SEED_CALIBRATION_PENDING_DO_NOT_START", source)
        self.assertEqual(source.count("manifest[\"status\"] == PENDING_STATUS"), 2)

    def test_launcher_validates_base_trainer_result_claim_exactly(self) -> None:
        source = inspect.getsource(launcher._run_one)
        self.assertIn('result.get("claim_boundary") == manifest["trainer_result_claim_boundary"]', source)

    def test_ready_smoke_commands_use_all_four_frozen_lane_weights(self) -> None:
        lane_weights = {
            "A_VHH_ONLY": ["--marginal-weight", "0.0", "--pair-weight", "0.0"],
            "B_TARGET_NO_CONTACT": ["--marginal-weight", "0.0", "--pair-weight", "0.0"],
            "C_SPLIT_MARGINAL": ["--marginal-weight", "1.5", "--pair-weight", "0.0"],
            "D_SPLIT_PAIR": ["--marginal-weight", "1.0", "--pair-weight", "0.5"],
        }
        manifest = {
            "python": "/python",
            "artifacts": {
                "trainer": {"node1_path": "/trainer.py"},
                "outer_split_0": {"node1_path": "/split.json"},
                "vhh_graph_cache_npz": {"node1_path": "/graphs/graph_cache.npz"},
            },
            "trainer": {
                "artifact_label": "trainer",
                "argv_template": [
                    "{python}", "{trainer}", "--lane", "{lane}", "--output-dir", "{output_dir}",
                    "--split-manifest", "{split_manifest}", "--graph-cache-dir", "{vhh_graph_dir}",
                ],
                "tiny_smoke_extra_argv": ["--tiny-e2e"],
                "outer_development_extra_argv": ["--fixed-epochs", "8"],
                "lane_outer_extra_argv": lane_weights,
            },
        }
        for lane, expected in lane_weights.items():
            with self.subTest(lane=lane):
                command = launcher.substitute_command(
                    manifest, lane=lane, outer_fold=0, output_dir=Path("/runtime") / lane, smoke=True,
                )
                self.assertEqual(command[-4:], expected)

    def test_pending_smoke_plan_remains_weightless_before_calibration(self) -> None:
        manifest = {
            "python": "/python",
            "artifacts": {
                "trainer": {"node1_path": "/trainer.py"},
                "outer_split_0": {"node1_path": "/split.json"},
                "vhh_graph_cache_npz": {"node1_path": "/graphs/graph_cache.npz"},
            },
            "trainer": {
                "artifact_label": "trainer",
                "argv_template": ["{python}", "{trainer}", "--lane", "{lane}"],
                "tiny_smoke_extra_argv": ["--tiny-e2e"],
                "outer_development_extra_argv": None,
                "lane_outer_extra_argv": None,
            },
        }
        command = launcher.substitute_command(
            manifest, lane="C_SPLIT_MARGINAL", outer_fold=0, output_dir=Path("/runtime/C"), smoke=True,
        )
        self.assertEqual(command[-1], "--tiny-e2e")
        self.assertNotIn("--marginal-weight", command)

    def test_smoke_receipt_requires_both_claims_and_bundle_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "manifest.json"
            freeze = root / "freeze.json"
            runtime = root / "runtime"
            status = runtime / "status"
            status.mkdir(parents=True)
            manifest.write_text("{}\n", encoding="utf-8")
            freeze.write_text("{}\n", encoding="utf-8")
            receipt_path = status / "SMOKE_RECEIPT.json"
            baseline = {
                "status": "PASS_V2_4_ADAPTIVE_V2_2_2_TINY_SMOKE_ALL_FOUR_LANES_STOP_BEFORE_OUTER",
                "manifest_sha256": launcher.sha256_file(manifest),
                "implementation_freeze_sha256": launcher.sha256_file(freeze),
                "outer_development_started": False,
                "tiny_smoke": {lane: {} for lane in launcher.LANE_GPU},
                "claim_boundary": launcher.CLAIM_BOUNDARY,
                "trainer_result_claim_boundary": launcher.TRAINER_RESULT_CLAIM_BOUNDARY,
                "bundle_revision": launcher.BUNDLE_REVISION,
            }
            receipt_path.write_text(json.dumps(baseline), encoding="utf-8")
            self.assertEqual(
                launcher.validate_smoke_receipt(manifest, freeze, runtime)["bundle_revision"],
                launcher.BUNDLE_REVISION,
            )
            for field, error in (
                ("claim_boundary", "smoke_claim_boundary"),
                ("trainer_result_claim_boundary", "smoke_trainer_result_claim_boundary"),
                ("bundle_revision", "smoke_bundle_revision"),
            ):
                with self.subTest(field=field):
                    tampered = dict(baseline)
                    tampered[field] = "tampered"
                    receipt_path.write_text(json.dumps(tampered), encoding="utf-8")
                    with self.assertRaisesRegex(launcher.DeploymentError, error):
                        launcher.validate_smoke_receipt(manifest, freeze, runtime)


if __name__ == "__main__":
    unittest.main()
