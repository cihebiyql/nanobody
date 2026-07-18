#!/usr/bin/env python3

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("node1_v2_4_outer_development_launcher_v1.py")
SPEC = importlib.util.spec_from_file_location("launcher", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        self.runtime = self.root / "runtime"
        sequence = "ACDE"
        sequence_sha = hashlib.sha256(sequence.encode()).hexdigest()
        rows = []
        sources = ["V4D_OPEN_MULTI_SEED", "V4H_ADAPTIVE_SEED_RANKING"]
        tiers = ["A", "B", "C", "A", "C"]
        for index in range(5):
            rows.append({
                "candidate_id": f"c{index}", "sequence": sequence, "sequence_sha256": sequence_sha,
                "parent_framework_cluster": f"p{index}", "teacher_source": sources[index > 0],
                "development_reliability_tier": tiers[index], "outer_fold": str(index),
            })
        table = self.bundle / "train.tsv"
        with table.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)
        receipt = self.bundle / "receipt.json"
        receipt.write_text(json.dumps({"status": "PASS_V2_4_SUPERVISED1507_MATERIALIZED", "output": {"sha256": sha(table)}}), encoding="utf-8")
        trainer = self.bundle / "trainer.py"; trainer.write_text("print('x')\n", encoding="utf-8")
        model = self.bundle / "model.py"; model.write_text("MODEL=1\n", encoding="utf-8")
        calibration = self.bundle / "CALIBRATION_RECEIPT.json"
        lane_weights = {lane: {"marginal": 0.001, "pair": 0.0005} for lane in MOD.LANE_GPU}
        calibration.write_text(json.dumps({
            "status": "PASS_OPEN_ONLY_PRESTEP_CONTACT_GRADIENT_CALIBRATION_V2_4",
            "open_only": True, "optimizer_steps_before_observation": 0,
            "outer_metrics_access_count": 0, "prediction_metrics_access_count": 0,
            "v4_f_test32_access_count": 0, "fixed_grid": [0.0001, 0.001],
            "frozen_lane_contact_weights": lane_weights,
            "attention_temperatures": {"8x6b": 1.0, "9e6y": 1.0},
        }), encoding="utf-8")
        artifacts = {}
        split_paths = {}
        for fold in range(5):
            path = self.bundle / f"outer_{fold}.json"; path.write_text("{}\n")
            split_paths[f"outer_split_{fold}"] = path
        for label, path in {"training_tsv": table, "training_receipt": receipt, "trainer": trainer, "model": model, "vhh_graph_cache_npz": model, "calibration_receipt": calibration, **split_paths}.items():
            artifacts[label] = {
                "source_path": str(path), "node1_path": str(path), "sha256": sha(path),
                "size_bytes": path.stat().st_size, "validation_mode": "LOCAL_SOURCE_AND_NODE1",
            }
        self.manifest = self.bundle / "manifest.json"
        payload = {
            "status": "PREFREEZE_DRY_RUN_READY_DO_NOT_START", "production_authorized": False,
            "sealed_evaluation_access_count": 0, "prediction_metrics_access_count": 0,
            "bundle_root": str(self.bundle), "runtime_root": str(self.runtime), "python": "/usr/bin/python3",
            "resources": {"lane_gpu_map": MOD.LANE_GPU, "cpu_threads_per_process": 8, "thread_environment": MOD.THREAD_ENVIRONMENT},
            "execution": {"phase_order": ["OPEN_ONLY_CONTACT_GRADIENT_CALIBRATION", "IMPLEMENTATION_FREEZE", "TINY_SMOKE", "FOUR_LANE_OUTER_DEVELOPMENT"], "outer_folds": list(range(5)), "lanes_concurrent": 4, "folds_sequential_within_lane": True, "tiny_smoke_must_pass_all_lanes": True},
            "expected_training_counts": {"rows": 5, "unique_candidates": 5, "unique_parent_framework_clusters": 5, "teacher_sources": {"V4D_OPEN_MULTI_SEED": 1, "V4H_ADAPTIVE_SEED_RANKING": 4}, "reliability_tiers": {"A": 2, "B": 1, "C": 2}},
            "artifacts": artifacts,
            "trainer": {"artifact_label": "trainer", "argv_template": ["{python}", "{trainer}", "--training-tsv", "{training_tsv}", "--split-manifest", "{split_manifest}", "--graph-cache-dir", "{vhh_graph_dir}", "--lane", "{lane}", "--output-dir", "{output_dir}"], "tiny_smoke_extra_argv": ["--tiny-e2e", "--backbone-kind", "tiny", "--fixed-epochs", "1"], "outer_development_extra_argv": ["--backbone-kind", "hf", "--fixed-epochs", "8"], "lane_outer_extra_argv": {lane: ["--marginal-weight", "0.001", "--pair-weight", "0.0005"] for lane in MOD.LANE_GPU}, "required_result_file": "RESULT.json"},
            "calibration_contract": {"receipt_artifact_label": "calibration_receipt", "calibration_runtime_root": str(self.root / "calibration_runtime"), "calibration_receipt_node1_path": str(calibration), "open_only": True, "optimizer_steps_before_observation": 0, "outer_metrics_access_count": 0, "prediction_metrics_access_count": 0, "fixed_grid": [0.0001, 0.001], "frozen_lane_contact_weights": lane_weights, "attention_temperatures": {"8x6b": 1.0, "9e6y": 1.0}},
        }
        self.manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_dry_run_is_non_mutating_and_closes_4_plus_20_commands(self) -> None:
        result = MOD.dry_run_plan(self.manifest)
        self.assertEqual(result["status"], "PASS_PREFREEZE_DRY_RUN_NO_RUNTIME_MUTATION")
        self.assertEqual(result["tiny_smoke_command_count"], 4)
        self.assertEqual(result["outer_development_command_count"], 20)
        self.assertFalse(result["automatic_smoke_to_outer_transition"])
        self.assertFalse(self.runtime.exists())
        self.assertEqual({row["physical_gpu"] for row in result["tiny_smoke"].values()}, {1, 2, 4, 5})
        self.assertTrue(all("--tiny-e2e" in row["command"] for row in result["tiny_smoke"].values()))
        self.assertTrue(all("--tiny-e2e" not in command for row in result["outer_development"].values() for command in row["commands"]))

    def test_runtime_presence_fails_closed(self) -> None:
        self.runtime.mkdir()
        with self.assertRaisesRegex(MOD.DeploymentError, "runtime_must_be_absent"):
            MOD.dry_run_plan(self.manifest)

    def test_artifact_hash_mismatch_fails_closed(self) -> None:
        payload = json.loads(self.manifest.read_text())
        payload["artifacts"]["model"]["sha256"] = "0" * 64
        self.manifest.write_text(json.dumps(payload))
        with self.assertRaisesRegex(MOD.DeploymentError, "local_source_sha"):
            MOD.dry_run_plan(self.manifest)

    def test_wrong_gpu_map_fails_closed(self) -> None:
        payload = json.loads(self.manifest.read_text())
        payload["resources"]["lane_gpu_map"]["A_VHH_ONLY"] = 0
        self.manifest.write_text(json.dumps(payload))
        with self.assertRaisesRegex(MOD.DeploymentError, "lane_gpu_map"):
            MOD.load_manifest(self.manifest)

    def test_freeze_must_bind_manifest_and_launcher(self) -> None:
        freeze = self.bundle / MOD.FREEZE_NAME
        freeze.write_text(json.dumps({
            "status": MOD.FREEZE_STATUS, "production_training_started": False, "pending": [],
            "manifest_sha256": sha(self.manifest), "launcher_sha256": sha(MODULE_PATH),
            "formal_artifact_sha256": {
                label: record["sha256"]
                for label, record in sorted(json.loads(self.manifest.read_text())["artifacts"].items())
            },
        }))
        result = MOD.validate_freeze(self.manifest, freeze)
        self.assertEqual(result["status"], MOD.FREEZE_STATUS)
        payload = json.loads(freeze.read_text()); payload["manifest_sha256"] = "0" * 64
        freeze.write_text(json.dumps(payload))
        with self.assertRaisesRegex(MOD.DeploymentError, "freeze_manifest_sha"):
            MOD.validate_freeze(self.manifest, freeze)

    def test_execute_without_freeze_is_not_reachable_from_dry_run(self) -> None:
        MOD.dry_run_plan(self.manifest)
        self.assertFalse(self.runtime.exists())

    def test_calibration_receipt_must_be_open_only_and_prestep(self) -> None:
        calibration_path = Path(json.loads(self.manifest.read_text())["artifacts"]["calibration_receipt"]["source_path"])
        payload = json.loads(calibration_path.read_text()); payload["optimizer_steps_before_observation"] = 1
        calibration_path.write_text(json.dumps(payload))
        manifest = json.loads(self.manifest.read_text())
        manifest["artifacts"]["calibration_receipt"]["sha256"] = sha(calibration_path)
        manifest["artifacts"]["calibration_receipt"]["size_bytes"] = calibration_path.stat().st_size
        self.manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(MOD.DeploymentError, "calibration_receipt_not_prestep"):
            MOD.dry_run_plan(self.manifest)

    def test_pending_calibration_has_smoke_plan_but_no_outer_commands(self) -> None:
        manifest = json.loads(self.manifest.read_text())
        manifest["status"] = "PREFREEZE_DRY_RUN_PENDING_CALIBRATION_DO_NOT_START"
        manifest["artifacts"].pop("calibration_receipt")
        manifest["trainer"]["outer_development_extra_argv"] = None
        manifest["trainer"]["lane_outer_extra_argv"] = None
        manifest["calibration_contract"]["binding_status"] = "PENDING_OPEN_ONLY_PRESTEP_CALIBRATION"
        manifest["calibration_contract"]["receipt_artifact_label"] = None
        manifest["calibration_contract"]["frozen_lane_contact_weights"] = None
        self.manifest.write_text(json.dumps(manifest))
        result = MOD.dry_run_plan(self.manifest)
        self.assertEqual(result["status"], "PASS_PREFREEZE_DRY_RUN_BLOCKED_PENDING_CALIBRATION")
        self.assertEqual(result["tiny_smoke_command_count"], 4)
        self.assertEqual(result["outer_development_command_count"], 0)
        self.assertEqual(result["outer_development_planned_job_count"], 20)
        self.assertFalse(self.runtime.exists())


if __name__ == "__main__":
    unittest.main()
