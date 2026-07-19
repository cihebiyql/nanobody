import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
SOURCE = ROOT / "deployment" / "prepared" / "node1_smoke_package_v1"
BUILDER = ROOT / "deployment" / "build_gpu1_sequential_authorization_overlay_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("gpu1_overlay_builder", BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_module()


class TestGPU1SequentialOverlay(unittest.TestCase):
    def test_build_and_audit_pending_overlay(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "gpu1_overlay"
            manifest = builder.build_package(SOURCE, output)
            self.assertFalse(manifest["launch_authorized"])
            self.assertFalse(manifest["training_or_prediction_executed"])
            self.assertEqual(manifest["physical_gpu_allowlist"], [1])
            self.assertEqual(manifest["max_cpu_per_process"], 8)
            self.assertFalse((output / "EXPLICIT_OPERATOR_AUTHORIZATION.json").exists())
            audit = builder.audit_package(SOURCE, output)
            self.assertEqual(
                audit["status"],
                "PASS_GPU1_SEQUENTIAL_OVERLAY_AUDIT_PENDING_AUTHORIZATION_NOT_LAUNCHED",
            )
            self.assertEqual(audit["job_count"], 6)

    def test_six_jobs_are_strictly_sequential_gpu1_cpu8_and_commands_null(self):
        source = builder.validate_source(SOURCE)
        plan = builder.build_plan(source["source_plan"])
        jobs = plan["jobs"]
        self.assertEqual(len(jobs), 6)
        for index, job in enumerate(jobs):
            expected_dependencies = [] if index == 0 else [jobs[index - 1]["job_id"]]
            self.assertEqual(job["dependencies"], expected_dependencies)
            self.assertIsNone(job["command"])
            self.assertEqual(job["physical_gpu"], 1)
            self.assertEqual(job["visible_cuda_devices"], [1])
            self.assertEqual(job["max_cpu_per_process"], 8)
            command = job["command_template"]
            self.assertEqual(command[:4], ["/usr/bin/taskset", "-c", "0-7", "/usr/bin/env"])
            self.assertIn("CUDA_VISIBLE_DEVICES=1", command)
            self.assertIn("OMP_NUM_THREADS=8", command)
            self.assertIn("MKL_NUM_THREADS=8", command)
            self.assertIn("OPENBLAS_NUM_THREADS=8", command)
            self.assertIn("NUMEXPR_NUM_THREADS=8", command)
            self.assertIn("TORCH_NUM_THREADS=8", command)
            self.assertIn(builder.NODE1_PYTHON, command)

    def test_source_model_data_and_firewall_hashes_are_exactly_bound(self):
        source = builder.validate_source(SOURCE)
        self.assertEqual(source["hashes"], builder.SOURCE_EXPECTED)
        inputs = source["source_inputs"]
        self.assertTrue(inputs["training_contact_graph_candidate_closure"])
        self.assertEqual(inputs["v4_f_test32_access_count"], 0)
        self.assertEqual(inputs["prediction_metrics_access_count"], 0)
        self.assertEqual(
            inputs["source_local_evidence"]["counts"],
            {"rows": 1269, "parents": 28, "train_rows": 1085, "score_rows": 184},
        )

    def test_launcher_is_fail_closed_on_missing_external_authorization(self):
        source = builder.validate_source(SOURCE)
        plan = builder.build_plan(source["source_plan"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan_path = root / "plan.json"
            overlay_path = root / "overlay.json"
            plan_path.write_text(json.dumps(plan, sort_keys=True) + "\n")
            overlay_path.write_text("{}\n")
            text = builder.launcher_source(
                builder.sha256_file(plan_path),
                builder.sha256_file(overlay_path),
                builder.SOURCE_EXPECTED["PACKAGE_MANIFEST.json"],
                builder.SOURCE_EXPECTED["SHA256SUMS"],
            )
        self.assertIn("explicit_operator_authorization_missing", text)
        self.assertIn(builder.AUTHORIZATION_REMOTE_PATH, text)
        self.assertIn("launch_authorized\") is False", text)
        self.assertNotIn("subprocess.Popen", text)


if __name__ == "__main__":
    unittest.main()
