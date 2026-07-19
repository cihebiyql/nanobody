from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


builder = load("v26_inner_pilot_builder_test", SRC / "build_nonlaunching_inner_pilot_package_v1.py")
collector = load("v26_inner_pilot_collector_test", SRC / "collect_inner_pilot_metrics_v1.py")
scheduler = load("v26_inner_pilot_scheduler_test", SRC / "run_resolved_inner_pilot_job_graph_v1.py")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PackageTests(unittest.TestCase):
    def external_payload(self):
        base = "/data1/mock"
        suffixes = (
            "/plan/trainer_splits/outer_0_inner_0.json",
            "/inputs/split_training/outer_0_inner_0.tsv",
            "/inputs/split_contacts/outer_0_inner_0.marginal.tsv.gz",
            "/inputs/split_contacts/outer_0_inner_0.pair.tsv.gz",
            "/inputs/split_graphs/outer_0_inner_0/graph_cache_receipt_v2.json",
            "/inputs/split_graphs/outer_0_inner_0/graph_cache_v2.npz",
            "/inputs/split_graphs/outer_0_inner_0/graph_manifest_v2.tsv",
            "/inputs/base_target_graphs/target_graphs_v2.pt",
            "/inputs/contact_score_formula_v1.json",
            "/src/train_v2_4_base_split.py",
            "/model.safetensors",
        )
        return {"files": [{"path": base + suffix, "sha256": f"{index:064x}"} for index, suffix in enumerate(suffixes, 1)]}

    def test_job_graph_exact_matrix(self):
        graph = builder.build_job_graph("/data1/pkg", "/data1/runtime")
        gpu = [job for job in graph["jobs"] if job["kind"] == "GPU_INNER_PILOT"]
        self.assertEqual(len(gpu), 8)
        self.assertEqual([job["physical_gpu"] for job in gpu], [1, 2, 4, 5, 1, 2, 4, 5])
        self.assertEqual([job["logical_device"] for job in gpu], ["cuda:0", "cuda:1", "cuda:2", "cuda:3"] * 2)
        self.assertTrue(all(job["command"] is None for job in graph["jobs"]))
        self.assertFalse(graph["launchable"])

    def test_external_allowlist_exact_and_rejects_other_outer(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "external.json"
            path.write_text(json.dumps(self.external_payload()))
            selected = builder.select_external_bindings(path)
            self.assertEqual(len(selected), 11)
            payload = self.external_payload()
            payload["files"].append({"path": "/data1/mock/plan/trainer_splits/outer_4.json", "sha256": "f" * 64})
            path.write_text(json.dumps(payload))
            selected = builder.select_external_bindings(path)
            self.assertEqual(len(selected), 11)

    def test_build_then_static_validate(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            external = temporary / "external.json"
            external.write_text(json.dumps(self.external_payload()))
            package = temporary / "package"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SRC / "build_nonlaunching_inner_pilot_package_v1.py"),
                    "--source-root",
                    str(ROOT),
                    "--output-root",
                    str(package),
                    "--v2-5-external-bindings",
                    str(external),
                    "--node-package-root",
                    "/data1/qlyu/projects/pvrig_v2_6_inner_pilot_package_v1_20260719",
                    "--node-runtime-root",
                    "/data1/qlyu/projects/pvrig_v2_6_inner_pilot_runtime_v1_20260719",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            audited = subprocess.run(
                [sys.executable, str(SRC / "validate_inner_pilot_package_v1.py"), "--package-root", str(package)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(audited.returncode, 0, audited.stderr)
            self.assertIn("PASS_IMMUTABLE_NONLAUNCHING_SKELETON_AUDIT", audited.stdout)

    def test_static_hash_mutation_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            external = temporary / "external.json"
            external.write_text(json.dumps(self.external_payload()))
            package = temporary / "package"
            subprocess.run(
                [sys.executable, str(SRC / "build_nonlaunching_inner_pilot_package_v1.py"), "--source-root", str(ROOT), "--output-root", str(package), "--v2-5-external-bindings", str(external), "--node-package-root", "/data1/pkg", "--node-runtime-root", "/data1/run"],
                check=True,
                capture_output=True,
            )
            target = package / "node1_bundle" / "plan" / "PILOT_JOB_GRAPH_TEMPLATE.json"
            target.write_text(target.read_text() + " ")
            audited = subprocess.run(
                [sys.executable, str(SRC / "validate_inner_pilot_package_v1.py"), "--package-root", str(package)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(audited.returncode, 0)

    def test_scheduler_rejects_unresolved_graph(self):
        graph = builder.build_job_graph("/data1/pkg", "/data1/run")
        with self.assertRaises(scheduler.ContractError):
            scheduler.validate_graph(graph, {})

    def test_scheduler_requires_v11(self):
        graph = builder.build_job_graph("/data1/pkg", "/data1/run")
        graph["status"] = "FROZEN_RESOLVED_PENDING_AUTHORIZATION"
        graph["launchable"] = True
        for job in graph["jobs"]:
            job["command"] = ["python", "driver.py", "--outer_0_inner_0", "--device", job.get("logical_device", "cpu")]
        overlay = {
            "status": "EXPLICITLY_AUTHORIZED_V1_1_INNER_PILOT",
            "execution_authorized": True,
            "integration_schema_version": "pvrig_v2_6_real1507_role_isolated_trainer_v1",
            "integration_v1_forbidden": True,
            "outer0_inner0_training_partition_sha256": "a" * 64,
            "outer0_inner0_rank_label_sha256": "b" * 64,
            "outer_test_truth_access_count": 0,
            "outer_metrics_access_count": 0,
            "v4_f_test32_access_count": 0,
        }
        with self.assertRaises(scheduler.ContractError):
            scheduler.validate_graph(graph, overlay)

    def test_scheduler_accepts_only_resolved_v11_shape(self):
        graph = builder.build_job_graph("/data1/pkg", "/data1/run")
        graph["status"] = "FROZEN_RESOLVED_PENDING_AUTHORIZATION"
        graph["launchable"] = True
        for job in graph["jobs"]:
            job["command"] = ["python", "driver.py", "--outer_0_inner_0", "--device", job.get("logical_device", "cpu")]
        overlay = {
            "status": "EXPLICITLY_AUTHORIZED_V1_1_INNER_PILOT",
            "execution_authorized": True,
            "integration_schema_version": "pvrig_v2_6_real1507_role_isolated_trainer_v1_1",
            "integration_v1_forbidden": True,
            "outer0_inner0_training_partition_sha256": "a" * 64,
            "outer0_inner0_rank_label_sha256": "b" * 64,
            "bound_regular_files": [
                {"logical_name": name, "path": f"/data1/{name}", "sha256": "c" * 64}
                for name in ("integration_v1_1", "integration_v1_1_freeze", "cuda_driver_v1_1", "cuda_driver_v1_1_freeze")
            ],
            "outer_test_truth_access_count": 0,
            "outer_metrics_access_count": 0,
            "v4_f_test32_access_count": 0,
        }
        jobs = scheduler.validate_graph(graph, overlay)
        self.assertEqual(len(jobs), 9)


class CollectorTests(unittest.TestCase):
    def write_tsv(self, path: Path, rows, fields):
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def make_job(self, root: Path, variant: str, seed: int, predictions):
        job = root / "gpu_jobs" / variant / f"seed_{seed}"
        job.mkdir(parents=True)
        training = {
            "outer_test_truth_access_count": 0,
            "outer_metrics_access_count": 0,
            "v4_f_test32_access_count": 0,
        }
        (job / "TRAINING_RECEIPT.json").write_text(json.dumps(training))
        (job / "STEP_EVIDENCE.jsonl").write_text(json.dumps({"finite_state": True, "v4_f_test32_access_count": 0}) + "\n")
        (job / "neural_head.pt").write_bytes(b"checkpoint")
        self.write_tsv(
            job / "score_predictions_no_metrics.tsv",
            predictions,
            ["candidate_id", "neural_R8", "neural_R9", "neural_Rdual"],
        )
        artifacts = {}
        for key, name in {
            "training_receipt": "TRAINING_RECEIPT.json",
            "step_evidence": "STEP_EVIDENCE.jsonl",
            "checkpoint": "neural_head.pt",
            "predictions": "score_predictions_no_metrics.tsv",
        }.items():
            artifacts[key] = {"path": name, "sha256": sha(job / name)}
        artifacts["step_evidence"]["rows"] = 1
        artifacts["predictions"]["rows"] = len(predictions)
        result = {
            "status": "PASS_INNER_PILOT_TRAINING",
            "job_id": f"outer0.inner0.{variant}.seed{seed}",
            "variant": variant,
            "seed": seed,
            "outer_fold": 0,
            "inner_fold": 0,
            "optimizer_steps": 1,
            "exact_min_violation_count": 0,
            "outer_test_truth_access_count": 0,
            "outer_metrics_access_count": 0,
            "v4_f_test32_access_count": 0,
            "artifacts": artifacts,
        }
        (job / "RESULT.json").write_text(json.dumps(result))

    def fixture(self, temporary: Path):
        training = temporary / "training.tsv"
        rows = [
            {"candidate_id": "train1", "parent_framework_cluster": "T", "R_8X6B": "0.2", "R_9E6Y": "0.3", "R_dual_min": "0.2"},
            {"candidate_id": "a", "parent_framework_cluster": "P1", "R_8X6B": "0.5", "R_9E6Y": "0.4", "R_dual_min": "0.4"},
            {"candidate_id": "b", "parent_framework_cluster": "P1", "R_8X6B": "0.4", "R_9E6Y": "0.3", "R_dual_min": "0.3"},
            {"candidate_id": "c", "parent_framework_cluster": "P2", "R_8X6B": "0.7", "R_9E6Y": "0.6", "R_dual_min": "0.6"},
            {"candidate_id": "d", "parent_framework_cluster": "P2", "R_8X6B": "0.6", "R_9E6Y": "0.5", "R_dual_min": "0.5"},
        ]
        self.write_tsv(training, rows, list(rows[0]))
        split = temporary / "split.json"
        split.write_text(json.dumps({"open_only": True, "split_id": "outer_0_inner_0", "outer_fold": 0, "train_parents": ["T"], "score_parents": ["P1", "P2"], "v4_f_test32_access_count": 0}))
        runtime = temporary / "runtime"
        predictions = [
            {"candidate_id": row["candidate_id"], "neural_R8": str(float(row["R_8X6B"]) + 0.01), "neural_R9": str(float(row["R_9E6Y"]) + 0.01), "neural_Rdual": str(float(row["R_dual_min"]) + 0.01)}
            for row in rows[1:]
        ]
        for variant, seeds in collector.VARIANT_SEEDS.items():
            for seed in seeds:
                self.make_job(runtime, variant, seed, predictions)
        return training, split, runtime

    def test_collector_full_closure(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            training, split, runtime = self.fixture(temporary)
            output = temporary / "metrics"
            completed = subprocess.run(
                [sys.executable, str(SRC / "collect_inner_pilot_metrics_v1.py"), "--job-id", "outer0.inner0.collect_open_inner_metrics", "--runtime-root", str(runtime), "--training-tsv", str(training), "--expected-training-tsv-sha256", sha(training), "--split-manifest", str(split), "--expected-split-manifest-sha256", sha(split), "--output-dir", str(output)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads((output / "RESULT.json").read_text())
            self.assertEqual(result["status"], "PASS_OPEN_INNER_ONLY_PILOT_METRICS")
            self.assertEqual(result["inner_score_rows"], 4)
            self.assertEqual(result["outer_test_truth_access_count"], 0)

    def test_collector_rejects_checkpoint_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            training, split, runtime = self.fixture(temporary)
            target = runtime / "gpu_jobs" / "F0_SHARED_GATED_NO_RANK" / "seed_43" / "neural_head.pt"
            target.write_bytes(b"mutated")
            output = temporary / "metrics"
            completed = subprocess.run(
                [sys.executable, str(SRC / "collect_inner_pilot_metrics_v1.py"), "--job-id", "outer0.inner0.collect_open_inner_metrics", "--runtime-root", str(runtime), "--training-tsv", str(training), "--expected-training-tsv-sha256", sha(training), "--split-manifest", str(split), "--expected-split-manifest-sha256", sha(split), "--output-dir", str(output)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(completed.returncode, 0)

    def test_collector_rejects_exact_min_violation(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            _training, _split, runtime = self.fixture(temporary)
            path = runtime / "gpu_jobs" / "F0_SHARED_GATED_NO_RANK" / "seed_43" / "score_predictions_no_metrics.tsv"
            rows = collector.read_tsv(path)
            rows[0]["neural_Rdual"] = "0.9"
            self.write_tsv(path, rows, list(rows[0]))
            result_path = path.parent / "RESULT.json"
            result = json.loads(result_path.read_text())
            result["artifacts"]["predictions"]["sha256"] = sha(path)
            result_path.write_text(json.dumps(result))
            prediction_rows, _result = collector.validate_job(path.parent, "F0_SHARED_GATED_NO_RANK", 43)
            truth = {
                row["candidate_id"]: {"parent": "P", "R8": 0.0, "R9": 0.0, "Rdual": 0.0}
                for row in prediction_rows
            }
            with self.assertRaises(collector.ContractError):
                collector.aggregate_predictions(
                    "F0_SHARED_GATED_NO_RANK",
                    [(43, prediction_rows), (97, prediction_rows), (193, prediction_rows)],
                    truth,
                )


if __name__ == "__main__":
    unittest.main()
