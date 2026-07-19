from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import pathlib
import tempfile
import unittest


HERE = pathlib.Path(__file__).resolve()
PACKAGE = HERE.parents[1]
SOURCE = PACKAGE / "src" / "node1_cuda_smoke_launcher_v1.py"
SPEC = importlib.util.spec_from_file_location("node1_cuda_smoke_launcher_v1", SOURCE)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

V26 = PACKAGE.parent
INTEGRATION_FREEZE = V26 / "real1507_integration_v1_20260718" / "IMPLEMENTATION_FREEZE_V1.json"
RANK_FREEZE = V26 / "rank_calibration_v1_1_20260718" / "IMPLEMENTATION_FREEZE_V1_1.json"


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: pathlib.Path, payload) -> pathlib.Path:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def environment_probe():
    return {
        "python_path": str(mod.FIXED_PYTHON),
        "torch": "2.6.0+cu124",
        "cuda_available": True,
        "cuda_version": "12.4",
        "bf16_supported": True,
    }


def resource_probe():
    return {
        "data1_free_gib": 179.0,
        "gpus": [
            {
                "index": index,
                "name": "NVIDIA GeForce RTX 4090",
                "memory_used_mib": 8,
                "utilization_percent": 0,
                "compute_process_count": 0,
            }
            for index in mod.FIXED_PHYSICAL_GPUS
        ],
    }


def smoke_result():
    return {
        "schema_version": "pvrig_v2_6_node1_cuda_smoke_result_v1",
        "status": "PASS",
        "precision": "bf16",
        "physical_gpu_map": mod.FIXED_GPU_MAP,
        "integration_freeze_sha256": mod.EXPECTED_INTEGRATION_FREEZE_SHA256,
        "rank_freeze_sha256": mod.EXPECTED_RANK_FREEZE_SHA256,
        "rank_core_sha256": mod.EXPECTED_RANK_CORE_SHA256,
        "be_trajectory": {
            "optimizer_steps": 20,
            "maximum_scalar_shared_parameter_delta": 0.0,
            "main_rng_restored_every_step": True,
            "finite_state_every_step": True,
        },
        "gradient_accumulation": {
            "microbatches_per_optimizer_step": 2,
            "optimizer_steps": 20,
            "microbatches_consumed": 40,
            "reduction": "MEAN_ACTUAL_WINDOW_BEFORE_ONE_ROLE_ISOLATED_STEP",
            "global_all_parameter_clip_used": False,
        },
        "f_shared_gated": {
            "optimizer_steps": 20,
            "kappa": 0.25,
            "telemetry_event_count": 20,
            "gradient_budget_violation_count": 0,
            "main_rng_restored_every_step": True,
            "finite_state_every_step": True,
        },
        "exact_min": {
            "independent_rdual_output_trained": False,
            "maximum_abs_error": 0.0,
            "inference_semantics": "exact_min(R_8X6B,R_9E6Y)",
        },
        "firewall": {
            "v4_f_test32_access_count": 0,
            "score_partition_truth_access_count": 0,
            "outer_metrics_access_count": 0,
            "candidate_docking_pose_input_count": 0,
        },
    }


class TestFrozenBindings(unittest.TestCase):
    def test_real_source_freezes_are_exactly_bound(self):
        integration, rank = mod.validate_source_freezes(INTEGRATION_FREEZE, RANK_FREEZE)
        self.assertEqual(sha(INTEGRATION_FREEZE), mod.EXPECTED_INTEGRATION_FREEZE_SHA256)
        self.assertEqual(sha(RANK_FREEZE), mod.EXPECTED_RANK_FREEZE_SHA256)
        self.assertEqual(integration["data_access"]["v4_f_test32_accessed"], 0)
        self.assertEqual(rank["data_access"]["v4_f_or_test32_results_accessed"], 0)

    def test_mutated_integration_freeze_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "integration.json"
            path.write_bytes(INTEGRATION_FREEZE.read_bytes() + b"\n")
            with self.assertRaisesRegex(mod.PreflightError, "integration_freeze_sha256_mismatch"):
                mod.validate_source_freezes(path, RANK_FREEZE)

    def test_mutated_rank_freeze_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "rank.json"
            path.write_bytes(RANK_FREEZE.read_bytes() + b"\n")
            with self.assertRaisesRegex(mod.PreflightError, "rank_freeze_sha256_mismatch"):
                mod.validate_source_freezes(INTEGRATION_FREEZE, path)


class TestLivePreconditions(unittest.TestCase):
    def test_environment_and_idle_resources_pass(self):
        mod.validate_environment_probe(environment_probe())
        mod.validate_resource_probe(resource_probe())

    def test_bf16_false_is_rejected(self):
        probe = environment_probe()
        probe["bf16_supported"] = False
        with self.assertRaisesRegex(mod.PreflightError, "bf16_unsupported"):
            mod.validate_environment_probe(probe)

    def test_low_data1_space_is_rejected(self):
        probe = resource_probe()
        probe["data1_free_gib"] = 99.99
        with self.assertRaisesRegex(mod.PreflightError, "data1_free_space_below_gate"):
            mod.validate_resource_probe(probe)

    def test_busy_gpu_is_rejected(self):
        for field, value, message in (
            ("memory_used_mib", 513, "gpu_memory_busy:1"),
            ("utilization_percent", 6, "gpu_utilization_busy:1"),
            ("compute_process_count", 1, "gpu_compute_process_busy:1"),
        ):
            with self.subTest(field=field):
                probe = resource_probe()
                probe["gpus"][0][field] = value
                with self.assertRaisesRegex(mod.PreflightError, message):
                    mod.validate_resource_probe(probe)

    def test_v25_terminal_requires_exact_pass_closure(self):
        valid = {
            "status": "PASS",
            "returncode": 0,
            "completed": 301,
            "job_graph_sha256": mod.EXPECTED_V25_JOB_GRAPH_SHA256,
            "v4_f_test32_access_count": 0,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = write_json(pathlib.Path(directory) / "TERMINAL.json", valid)
            mod.validate_v25_terminal(path)
            for field, value, message in (
                ("status", "RUNNING", "v25_terminal_not_pass"),
                ("completed", 300, "v25_terminal_job_closure"),
                ("v4_f_test32_access_count", 1, "v25_terminal_v4f_access"),
            ):
                mutation = dict(valid)
                mutation[field] = value
                write_json(path, mutation)
                with self.assertRaisesRegex(mod.PreflightError, message):
                    mod.validate_v25_terminal(path)


class TestSmokeResultContract(unittest.TestCase):
    def validate(self, payload):
        with tempfile.TemporaryDirectory() as directory:
            path = write_json(pathlib.Path(directory) / "SMOKE_RESULT.json", payload)
            return mod.validate_smoke_result(path)

    def test_complete_result_passes(self):
        self.assertEqual(self.validate(smoke_result())["status"], "PASS")

    def test_be_trajectory_mutations_fail(self):
        for field, value, message in (
            ("optimizer_steps", 19, "be_step_count"),
            ("maximum_scalar_shared_parameter_delta", 1.01e-7, "be_trajectory_delta"),
            ("main_rng_restored_every_step", False, "be_rng_not_restored"),
            ("finite_state_every_step", False, "be_nonfinite_state"),
        ):
            payload = smoke_result()
            payload["be_trajectory"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(mod.PreflightError, message):
                self.validate(payload)

    def test_accumulation_mutations_fail(self):
        for field, value, message in (
            ("microbatches_per_optimizer_step", 1, "accumulation_factor"),
            ("microbatches_consumed", 39, "accumulation_microbatch_closure"),
            ("global_all_parameter_clip_used", True, "global_clip_used"),
        ):
            payload = smoke_result()
            payload["gradient_accumulation"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(mod.PreflightError, message):
                self.validate(payload)

    def test_f_gradient_cap_mutations_fail(self):
        for field, value, message in (
            ("kappa", 0.3, "f_kappa"),
            ("telemetry_event_count", 19, "f_telemetry_count"),
            ("gradient_budget_violation_count", 1, "f_gradient_budget_violation"),
        ):
            payload = smoke_result()
            payload["f_shared_gated"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(mod.PreflightError, message):
                self.validate(payload)

    def test_exact_min_and_firewall_mutations_fail(self):
        mutations = [
            (("exact_min", "independent_rdual_output_trained"), True, "independent_rdual_trained"),
            (("exact_min", "maximum_abs_error"), 1e-9, "exact_min_error"),
            (("firewall", "v4_f_test32_access_count"), 1, "result_v4f_access"),
            (("firewall", "score_partition_truth_access_count"), 1, "score_truth_access"),
            (("firewall", "outer_metrics_access_count"), 1, "outer_metrics_access"),
            (("firewall", "candidate_docking_pose_input_count"), 1, "candidate_pose_input_access"),
        ]
        for (section, field), value, message in mutations:
            payload = smoke_result()
            payload[section][field] = value
            with self.subTest(section=section, field=field), self.assertRaisesRegex(mod.PreflightError, message):
                self.validate(payload)


class TestNonlaunchingSurface(unittest.TestCase):
    def test_checked_in_authorization_is_false(self):
        authorization = json.loads((PACKAGE / "AUTHORIZATION_TEMPLATE_NONLAUNCHING.json").read_text())
        self.assertFalse(authorization["execution_authorized"])
        self.assertEqual(authorization["status"], "NONLAUNCHING_TEMPLATE_DO_NOT_EXECUTE")
        self.assertEqual(authorization["driver_freeze_sha256"], "PENDING")

    def test_cli_requires_explicit_execute(self):
        with self.assertRaisesRegex(mod.PreflightError, "explicit_execute_flag_required"):
            mod.main([
                "--package-manifest", "missing",
                "--authorization", "missing",
                "--integration-freeze", "missing",
                "--rank-freeze", "missing",
                "--driver-freeze", "missing",
                "--expected-driver-freeze-sha256", "PENDING",
                "--v25-terminal", "missing",
                "--runtime-root", "/data1/qlyu/projects/x",
            ])

    def test_command_is_exactly_frozen(self):
        command = mod.build_driver_command(
            driver_path=pathlib.Path("/data1/qlyu/projects/package/smoke_driver.py"),
            runtime_root=pathlib.Path("/data1/qlyu/projects/runtime"),
            integration_freeze_path=pathlib.Path("/data1/qlyu/projects/package/integration.json"),
            rank_freeze_path=pathlib.Path("/data1/qlyu/projects/package/rank.json"),
        )
        self.assertEqual(command[0], str(mod.FIXED_PYTHON))
        self.assertEqual(command[command.index("--physical-gpus") + 1], "1,2,4,5")
        self.assertEqual(command[command.index("--precision") + 1], "bf16")
        self.assertEqual(command[command.index("--optimizer-steps") + 1], "20")
        self.assertEqual(command[command.index("--gradient-accumulation") + 1], "2")
        self.assertEqual(command[command.index("--kappa") + 1], "0.25")


if __name__ == "__main__":
    unittest.main()
