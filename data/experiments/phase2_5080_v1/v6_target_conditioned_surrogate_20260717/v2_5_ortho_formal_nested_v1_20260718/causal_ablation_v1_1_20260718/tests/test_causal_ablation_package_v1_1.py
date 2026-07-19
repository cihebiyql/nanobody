#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import shutil
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from build_nonlaunching_causal_ablation_package_v1_1 import main as build_main  # noqa: E402
from validate_causal_ablation_package_v1_1 import ValidationError, validate  # noqa: E402
from watch_formal_terminal_then_mark_ablation_ready_v1_1 import run as watch_run  # noqa: E402


class PackageTests(unittest.TestCase):
    def build(self, temp: Path) -> Path:
        output = temp / "package"
        code = build_main(["--source-root", str(ROOT), "--output-root", str(output)])
        self.assertEqual(code, 0)
        return output

    @staticmethod
    def rebind_manifest_file(output: Path, relative: str) -> None:
        path = output / relative
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path = output / "PACKAGE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][relative] = digest
        if relative == "ABLATION_JOB_GRAPH.json":
            manifest["job_graph_sha256"] = digest
        if relative == "CAUSAL_ABLATION_CONTRACT_V1_1.json":
            manifest["contract_sha256"] = digest
        manifest_path.write_text(json.dumps(manifest) + "\n")

    def test_builder_and_validator_close_131_job_nonlaunching_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = self.build(Path(directory))
            result = validate(output, ROOT)
            self.assertEqual(result["status"], "PASS_IMMUTABLE_NONLAUNCHING_CAUSAL_ABLATION_AUDIT")
            self.assertEqual((result["jobs"], result["gpu_jobs"], result["cpu_jobs"]), (131, 85, 46))
            graph = json.loads((output / "ABLATION_JOB_GRAPH.json").read_text())
            self.assertFalse(graph["execution_authorized"])
            self.assertTrue(all("command" not in job for job in graph["jobs"]))
            self.assertEqual(result["matched_prevalence_mask_null_replicates"], 256)
            self.assertEqual(result["contact_shuffle_pre_optimizer_audits"], 40)
            self.assertFalse(result["v1_frozen_package_mutated"])
            mask_jobs = [job for job in graph["jobs"] if job.get("perturbation") == "HOTSPOT_INTERFACE_MASK_SWAP" and job["kind"] == "GPU_INFERENCE_PERTURB"]
            self.assertEqual(len(mask_jobs), 15)
            self.assertTrue(all(job["mask_null_replicates"] == 256 for job in mask_jobs))

    def test_validator_rejects_hash_mutation_and_authorized_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            output = self.build(temp)
            (output / "src" / "causal_perturbations_v1_1.py").write_text("mutated\n")
            with self.assertRaisesRegex(ValidationError, "package_hash"):
                validate(output)

            shutil.rmtree(output)
            output = self.build(temp)
            graph_path = output / "ABLATION_JOB_GRAPH.json"
            graph = json.loads(graph_path.read_text())
            graph["jobs"][0]["execution_authorized"] = True
            graph_path.write_text(json.dumps(graph) + "\n")
            manifest_path = output / "PACKAGE_MANIFEST.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["files"]["ABLATION_JOB_GRAPH.json"] = hashlib.sha256(graph_path.read_bytes()).hexdigest()
            manifest["job_graph_sha256"] = manifest["files"]["ABLATION_JOB_GRAPH.json"]
            manifest_path.write_text(json.dumps(manifest) + "\n")
            with self.assertRaisesRegex(ValidationError, "job_authorized"):
                validate(output)

    def test_validator_rejects_weakened_mask_null_or_donor_power_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            output = self.build(temp)
            graph_path = output / "ABLATION_JOB_GRAPH.json"
            graph = json.loads(graph_path.read_text())
            mask_job = next(job for job in graph["jobs"] if job.get("perturbation") == "HOTSPOT_INTERFACE_MASK_SWAP" and job["kind"] == "GPU_INFERENCE_PERTURB")
            mask_job["mask_null_replicates"] = 32
            graph_path.write_text(json.dumps(graph) + "\n")
            self.rebind_manifest_file(output, "ABLATION_JOB_GRAPH.json")
            with self.assertRaisesRegex(ValidationError, "mask_job_replicates"):
                validate(output)

            shutil.rmtree(output)
            output = self.build(temp)
            graph_path = output / "ABLATION_JOB_GRAPH.json"
            graph = json.loads(graph_path.read_text())
            shuffle_job = next(job for job in graph["jobs"] if "CONTACT_SHUFFLE" in job["kind"] and "RETRAIN" in job["kind"])
            shuffle_job["pre_optimizer_payload_power_audit_required"] = False
            graph_path.write_text(json.dumps(graph) + "\n")
            self.rebind_manifest_file(output, "ABLATION_JOB_GRAPH.json")
            with self.assertRaisesRegex(ValidationError, "shuffle_job_audit"):
                validate(output)

            shutil.rmtree(output)
            output = self.build(temp)
            contract_path = output / "CAUSAL_ABLATION_CONTRACT_V1_1.json"
            contract = json.loads(contract_path.read_text())
            contract["null_controls"]["DONOR_RECIPIENT_CONTACT_PAYLOAD_DISTANCE_POWER_AUDIT_V1_1"]["thresholds"]["supervision_changed_fraction_min"] = 0.0
            contract_path.write_text(json.dumps(contract) + "\n")
            self.rebind_manifest_file(output, "CAUSAL_ABLATION_CONTRACT_V1_1.json")
            with self.assertRaisesRegex(ValidationError, "donor_power_thresholds"):
                validate(output)

    def test_watcher_waits_without_launching(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            output = self.build(temp)
            status = temp / "status.json"
            result = watch_run(Namespace(
                package_root=output,
                runtime_root=temp / "runtime",
                status_path=status,
                poll_seconds=0.001,
                once=True,
            ))
            self.assertEqual(result["status"], "WAITING_FORMAL_V1_3_TERMINAL_NONLAUNCHING")
            self.assertFalse(result["launch_authorized"])
            self.assertFalse(result["training_or_prediction_executed"])

    def test_watcher_marks_ready_but_still_does_not_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            output = self.build(temp)
            runtime = temp / "runtime"
            (runtime / "final").mkdir(parents=True)
            (runtime / "TERMINAL.json").write_text(json.dumps({
                "status": "PASS",
                "completed": 301,
                "returncode": 0,
                "job_graph_sha256": "ea1c4c1eedf189d9542e3e73b0c0368777b4073468fd4e39535b28fd7fa24185",
                "v4_f_test32_access_count": 0,
            }) + "\n")
            (runtime / "final" / "RESULT.json").write_text(json.dumps({
                "status": "PASS_FORMAL_OPEN_OUTER_EVALUATION_COLLECTED",
                "v4_f_test32_access_count": 0,
            }) + "\n")
            result = watch_run(Namespace(
                package_root=output,
                runtime_root=runtime,
                status_path=temp / "ready.json",
                poll_seconds=0.001,
                once=True,
            ))
            self.assertEqual(result["status"], "READY_NONLAUNCHING_EXPLICIT_NEW_AUTHORIZATION_REQUIRED")
            self.assertFalse(result["launch_authorized"])
            self.assertFalse(result["training_or_prediction_executed"])


if __name__ == "__main__":
    unittest.main()
