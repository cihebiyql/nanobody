from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SRC))

import node1_contact_gradient_calibration_v1_2 as mod  # noqa: E402
import select_contact_loss_gradient_grid_v1 as selector  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observation(lane: str) -> dict[str, object]:
    raw = {"dual": 1.0, "receptor": 0.0, "marginal": 25.0, "ranking": 0.0, "residual": 0.0}
    weights = {**selector.NONCONTACT_WEIGHTS, "marginal": 0.0001}
    if lane == "D_FULL_PAIR":
        raw["pair"] = 20.0
        weights["pair"] = 0.00005
    weighted = {name: abs(weights[name]) * raw[name] for name in raw}
    denominator = sum(weighted.values())
    fractions = {name: value / denominator for name, value in weighted.items()}
    return {
        "schema_version": selector.OBSERVATION_SCHEMA,
        "lane": lane,
        "gradient_batch_index": 0,
        "gradient_batches_in_observation": 1,
        "optimizer_steps_before_observation": 0,
        "candidate_ids_sha256": "a" * 64,
        "candidate_count": 8,
        "teacher_source_counts": {selector.SOURCES[0]: 2, selector.SOURCES[1]: 6},
        "unweighted_gradient_l2_norm": raw,
        "component_weights": weights,
        "weighted_gradient_l2_norm": weighted,
        "weighted_gradient_fraction": fractions,
        "direct_contact_gradient_fraction": fractions["marginal"] + fractions.get("pair", 0.0),
        "open_only": True,
        "v4_f_test32_access_count": 0,
        "prediction_metrics_access_count": 0,
        "outer_fold": 0,
        "inner_fold": 1,
        "training_stage": "first_inner_selection_epoch0_first_batch",
    }


class Fixture:
    def __init__(self, temporary: str) -> None:
        self.root = Path(temporary)
        self.bundle = self.root / "bundle"
        self.runtime = self.root / "runtime"
        self.bundle.mkdir()
        implementation_paths = {
            "trainer": self.bundle / "residue_v2/src/train_nested_residue_surrogate_v2.py",
            "residue_model": self.bundle / "residue_v2/src/residue_model_v2.py",
            "augment_target_script": self.bundle / "residue_v2/src/augment_target_graph_esm2_v2.py",
            "selector": self.bundle / "residue_v2/src/select_contact_loss_gradient_grid_v1.py",
            "preregistration": self.bundle / "residue_v2/PREREGISTRATION_V2.json",
            "base_trainer_v1": self.bundle / "residue_v1/src/train_nested_residue_surrogate.py",
            "base_trainer_v1_5": self.bundle / "residue_v1/src/train_nested_residue_surrogate_v1_5.py",
            "base_residue_model_v1": self.bundle / "residue_v1/src/residue_model.py",
            "build_residue_graph_cache_v2": self.bundle / "residue_v2/src/build_residue_graph_cache_v2.py",
            "domain_balance_v2": self.bundle / "residue_v2/src/domain_balance_v2.py",
        }
        artifacts: dict[str, dict[str, str]] = {}
        for label in sorted(mod.STATIC_LABELS):
            path = implementation_paths.get(label, self.bundle / "inputs" / f"{label}.bin")
            path.parent.mkdir(parents=True, exist_ok=True)
            if label == "preregistration":
                path.write_text(json.dumps({"status": "ORIGINAL_UNCHANGED"}) + "\n")
            else:
                path.write_bytes(f"fixture:{label}".encode())
            artifacts[label] = {"path": str(path), "sha256": sha(path)}
        self.matrix = self.root / "matrix.json"
        payload = {
            "schema_version": mod.MATRIX_SCHEMA,
            "status": mod.MATRIX_STATUS,
            "mode": "OPEN_ONLY_PREPRODUCTION_NOT_FORMAL_OOF",
            "bundle_root": str(self.bundle),
            "runtime_root": str(self.runtime),
            "python": sys.executable,
            "minimum_free_gib": 200,
            "augmentation_gpu": 5,
            "lane_gpu_map": mod.LANE_GPU,
            "outer_fold": 0,
            "maximum_epochs": 1,
            "smoke_mode": True,
            "structure_prefixes": list(mod.STRUCTURE_PREFIXES),
            "trainer_arguments": mod.TRAINER_ARGUMENTS,
            "artifacts": artifacts,
            "launcher_sha256": sha(Path(mod.__file__).resolve()),
            "original_preregistration_sha256": artifacts["preregistration"]["sha256"],
            "sealed_boundary": {
                "v4_f_test32_access_count": 0,
                "prediction_metrics_used_for_selection": False,
                "formal_oof_started": False,
            },
        }
        self.matrix.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        self.context = mod.load_context(self.matrix)
        self.commands: list[tuple[list[str], dict[str, str]]] = []
        self.omit_observation_lane: str | None = None

    @staticmethod
    def gpu_probe(indices):
        return {int(index): {"memory_used_mib": 18, "utilization_percent": 0} for index in indices}

    def runner(self, command, environment, log_path):
        command = list(command)
        self.commands.append((command, dict(environment)))
        if "augment_target_graph_esm2_v2.py" in command[1]:
            output = Path(command[command.index("--output-dir") + 1])
            artifact_dir = output / "by_sha256" / ("b" * 64)
            artifact_dir.mkdir(parents=True)
            artifact = artifact_dir / "target_graphs_esm2_650m_v2.pt"
            artifact.write_bytes(b"augmented")
            receipt = artifact_dir / "target_graphs_esm2_650m_v2.receipt.json"
            a = self.context.artifacts
            receipt.write_text(json.dumps({
                "status": "PASS_TARGET_GRAPHS_ESM2_650M_AUGMENTED",
                "implementation_sha256": a["augment_target_script"].sha256,
                "input_hashes": {
                    "base_target_pt": a["base_target_pt"].sha256,
                    "target_manifest": a["base_target_manifest"].sha256,
                    "base_target_receipt": a["base_target_receipt"].sha256,
                    "model_identity_file": a["esm2_650m_model_identity"].sha256,
                },
                "sealed_boundary": {"candidate_docking_pose_files_opened": 0},
            }))
            (output / "CURRENT.json").write_text(json.dumps({
                "schema_version": "pvrig_v6_target_graphs_esm2_650m_v2",
                "artifact_relative_path": str(artifact.relative_to(output)),
                "receipt_relative_path": str(receipt.relative_to(output)),
                "artifact_sha256": sha(artifact), "receipt_sha256": sha(receipt),
            }))
            return
        if "train_nested_residue_surrogate_v2.py" in command[1]:
            lane = command[command.index("--lane") + 1]
            output = Path(command[command.index("--output-dir") + 1])
            output.mkdir(parents=True)
            payload = {"status": "PASS_OUTER_FOLD_COMPLETE", "lane": lane, "outer_fold": 0}
            if lane != self.omit_observation_lane:
                payload["contact_gradient_calibration_observation"] = observation(lane)
            (output / "RESULT.json").write_text(json.dumps(payload))
            return
        if "select_contact_loss_gradient_grid_v1.py" in command[1]:
            selector.run(selector.parser().parse_args(command[2:]))
            return
        raise AssertionError(command)


class CalibrationLauncherTests(unittest.TestCase):

    def test_cpu_thread_caps_are_locked_for_every_gpu_process(self) -> None:
        expected = {
            "OMP_NUM_THREADS": "8",
            "MKL_NUM_THREADS": "8",
            "OPENBLAS_NUM_THREADS": "8",
            "NUMEXPR_NUM_THREADS": "8",
        }
        for gpu in (1, 2, 3, 4, 5):
            environment = mod.base_environment(gpu)
            self.assertEqual({name: environment[name] for name in expected}, expected)
            self.assertEqual(environment["CUDA_VISIBLE_DEVICES"], str(gpu))

    def test_dry_run_validates_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(temporary)
            result = mod.execute(fixture.context, mode="dry-run")
            self.assertEqual(result["writes"], 0)
            self.assertFalse(fixture.runtime.exists())
            self.assertEqual(set(result["lane_commands"]), set(mod.LANES))

    def test_run_and_resume_content_addressed_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(temporary)
            result = mod.execute(
                fixture.context, mode="run", runner=fixture.runner,
                gpu_probe=fixture.gpu_probe, free_gib=lambda _: 999,
            )
            self.assertEqual(result["status"], mod.TERMINAL_STATUS)
            self.assertTrue(result["first_prestep_observation_per_lane"])
            self.assertEqual(result["v4_f_test32_access_count"], 0)
            self.assertEqual(len(result["lane_result_sha256"]), 4)
            self.assertTrue((fixture.runtime / "calibration/CURRENT.json").is_file())
            gpu_commands = [env.get("CUDA_VISIBLE_DEVICES") for _, env in fixture.commands]
            self.assertEqual(set(gpu_commands), {"", "1", "2", "3", "4", "5"})
            before = len(fixture.commands)
            replay = mod.execute(
                fixture.context, mode="resume", runner=fixture.runner,
                gpu_probe=fixture.gpu_probe, free_gib=lambda _: 999,
            )
            self.assertEqual(replay, result)
            self.assertEqual(len(fixture.commands), before)

    def test_missing_first_prestep_observation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(temporary)
            fixture.omit_observation_lane = "C_PATCH"
            with self.assertRaisesRegex(mod.CalibrationLaunchError, "first_prestep_observation_missing"):
                mod.execute(
                    fixture.context, mode="run", runner=fixture.runner,
                    gpu_probe=fixture.gpu_probe, free_gib=lambda _: 999,
                )

    def test_static_tamper_and_sealed_path_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(temporary)
            fixture.context.artifacts["training_tsv"].path.write_text("tamper")
            with self.assertRaisesRegex(mod.CalibrationLaunchError, "artifact_sha_mismatch"):
                mod.execute(fixture.context, mode="dry-run")
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(temporary)
            payload = json.loads(fixture.matrix.read_text())
            payload["artifacts"]["training_tsv"]["path"] = str(fixture.bundle / "test32/training.tsv")
            fixture.matrix.write_text(json.dumps(payload))
            with self.assertRaisesRegex(mod.CalibrationLaunchError, "sealed_path_forbidden"):
                mod.load_context(fixture.matrix)

    def test_bundle_full_local_import_closure_is_exact_and_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(temporary)
            expected = {
                "base_trainer_v1": "residue_v1/src/train_nested_residue_surrogate.py",
                "base_trainer_v1_5": "residue_v1/src/train_nested_residue_surrogate_v1_5.py",
                "base_residue_model_v1": "residue_v1/src/residue_model.py",
                "build_residue_graph_cache_v2": "residue_v2/src/build_residue_graph_cache_v2.py",
                "domain_balance_v2": "residue_v2/src/domain_balance_v2.py",
            }
            for label, suffix in expected.items():
                self.assertTrue(str(fixture.context.artifacts[label].path).endswith(suffix))
            fixture.context.artifacts["base_trainer_v1"].path.unlink()
            with self.assertRaisesRegex(mod.CalibrationLaunchError, "artifact_missing_or_symlink:base_trainer_v1"):
                mod.execute(fixture.context, mode="dry-run")

    def test_trainer_repo_local_import_graph_is_closed(self) -> None:
        trainer = HERE.parent / "src/train_nested_residue_surrogate_v2.py"
        modules = set()
        for node in ast.walk(ast.parse(trainer.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        expected = {
            "train_nested_residue_surrogate",
            "train_nested_residue_surrogate_v1_5",
            "residue_model",
            "build_residue_graph_cache_v2",
            "domain_balance_v2",
            "residue_model_v2",
        }
        local = {
            name for name in modules
            if (HERE.parent / "src" / f"{name}.py").is_file()
            or (HERE.parent.parent / "residue_v1/src" / f"{name}.py").is_file()
        }
        self.assertEqual(local, expected)
        self.assertTrue({
            "base_trainer_v1", "base_trainer_v1_5", "base_residue_model_v1",
            "build_residue_graph_cache_v2", "domain_balance_v2", "residue_model",
        } <= mod.STATIC_LABELS)

    def test_exact_bundle_layout_imports_trainer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            v2_source = HERE.parent / "src"
            v1_source = HERE.parent.parent / "residue_v1/src"
            for source in (
                v2_source / "train_nested_residue_surrogate_v2.py",
                v2_source / "residue_model_v2.py",
                v2_source / "build_residue_graph_cache_v2.py",
                v2_source / "domain_balance_v2.py",
            ):
                destination = bundle / "residue_v2/src" / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            for source in (
                v1_source / "train_nested_residue_surrogate.py",
                v1_source / "train_nested_residue_surrogate_v1_5.py",
                v1_source / "residue_model.py",
            ):
                destination = bundle / "residue_v1/src" / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            completed = subprocess.run(
                [sys.executable, "-c", "import train_nested_residue_surrogate_v2"],
                cwd=bundle / "residue_v2/src",
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
