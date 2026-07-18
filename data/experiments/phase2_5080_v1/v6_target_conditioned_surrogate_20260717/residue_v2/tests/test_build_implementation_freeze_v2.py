from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import build_implementation_freeze_v2 as mod  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FreezeFixture:
    def __init__(self, temporary: str, *, pending_pair: bool = False) -> None:
        self.root = Path(temporary)
        self.residue = self.root / "residue_v2"
        self.artifact_root = self.root / "artifacts"
        self.v1_root = self.root / "v1_5"
        self.runtime = {
            "python_executable": "/data1/qlyu/software/envs/pvrig-v6-tc/bin/python",
            "python_version": "3.11.14",
            "torch_version": "2.6.0+cu124",
            "torch_cuda_version": "12.4",
            "cuda_available": True,
            "cuda_device_count": 8,
            "cuda_device_names": ["NVIDIA GeForce RTX 4090"] * 8,
        }
        self.v1_hashes: dict[str, str] = {}
        self.v1_paths: dict[str, str] = {}
        self.contact_hashes: dict[str, str] = {}
        self.transitive_hashes: dict[str, str] = {}
        self.residue.mkdir(parents=True)
        self.artifact_root.mkdir()
        self.v1_root.mkdir()
        for relative in mod.EXPECTED_IMPLEMENTATION_PATHS:
            path = self.residue / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"fixture:{relative}\n", encoding="utf-8")
        (self.residue / "PREREGISTRATION_V2.json").write_text(json.dumps({
            "promotion_gates": mod.EXPECTED_PROMOTION_GATES,
            "sealed_and_excluded": {
                "v4_f_test32_access": True,
                "open_development_hyperparameter_selection": True,
            },
        }, sort_keys=True) + "\n")
        for index, label in enumerate(sorted(mod.EXPECTED_V1_5_IMMUTABLE)):
            path = self.v1_root / f"{label}.bin"
            path.write_bytes(f"immutable:{index}:{label}".encode())
            self.v1_paths[label] = str(path)
            self.v1_hashes[label] = digest(path)

        artifacts: dict[str, dict[str, object]] = {}
        for index, label in enumerate(sorted(mod.EXPECTED_ARTIFACT_LABELS)):
            if label == "augmented_target_graph":
                artifacts[label] = {
                    "path": str(self.root / "runtime/cache/pvrig_graphs/esm2_650m_v2"),
                    "sha256": None,
                    "phase": "post_augmentation_binding",
                    "closure_required": True,
                }
                continue
            if label in mod.EXPECTED_CONTACT_GOVERNANCE_HASHES:
                continue
            transitive_paths = {
                "residue_v1_residue_model": self.root / "bundle/residue_v1/src/residue_model.py",
                "residue_v1_base_trainer": self.root / "bundle/residue_v1/src/train_nested_residue_surrogate.py",
                "residue_v1_v1_5_trainer": self.root / "bundle/residue_v1/src/train_nested_residue_surrogate_v1_5.py",
            }
            path = transitive_paths.get(label, self.artifact_root / f"{label}.bin")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"artifact:{index}:{label}".encode())
            value = mod.PENDING if pending_pair and label in {"pair_contact_tsv_gz", "pair_contact_receipt"} else digest(path)
            artifacts[label] = {"path": str(path), "sha256": value, "phase": "pre_freeze_binding"}
            if label in transitive_paths:
                self.transitive_hashes[label] = value

        governance_root = self.root / "bundle/inputs/contact_loss_amendment_v2_2"
        governance_root.mkdir(parents=True)
        calibration = {"v4_f_test32_access_count": 0, "input_hashes": {lane: "a" * 64 for lane in mod.LANE_GPU_MAP}}
        amendment = {
            "schema_version": "pvrig_v6_residue_v2_contact_loss_amendment_v2_2",
            "status": "FROZEN_BEFORE_ANY_FORMAL_RESIDUE_V2_TRAINING",
            "lane_weights": mod.EXPECTED_TRAINER_ARGUMENTS["lane_contact_weights"],
            "calibration": calibration,
        }
        amendment_path = governance_root / "CONTACT_LOSS_AMENDMENT_V2_2.json"
        amendment_path.write_text(json.dumps(amendment, sort_keys=True) + "\n")
        report = {
            "status": "PASS_OPEN_ONLY_ONE_BATCH_PRESTEP_LANE_SPECIFIC_GRADIENT_CALIBRATION",
            "calibration": calibration,
            "selection_used_prediction_metrics": False,
            "v4_f_test32_access_count": 0,
        }
        report_path = governance_root / "CONTACT_GRADIENT_CALIBRATION_REPORT_V2_2.json"
        report_path.write_text(json.dumps(report, sort_keys=True) + "\n")
        receipt = {
            "schema_version": "pvrig_v6_residue_v2_contact_gradient_calibration_receipt_v2_2",
            "status": report["status"],
            "outputs": {
                report_path.name: digest(report_path),
                amendment_path.name: digest(amendment_path),
            },
        }
        receipt_path = governance_root / "RUN_RECEIPT.json"
        receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
        for label, path in {
            "contact_loss_amendment_v2_2": amendment_path,
            "contact_gradient_calibration_report_v2_2": report_path,
            "contact_gradient_calibration_receipt_v2_2": receipt_path,
        }.items():
            self.contact_hashes[label] = digest(path)
            artifacts[label] = {"path": str(path), "sha256": digest(path), "phase": "pre_freeze_binding"}

        self.matrix_path = self.residue / "RESIDUE_V2_PRODUCTION_MATRIX.json"
        matrix = {
            "schema_version": mod.MATRIX_SCHEMA,
            "status": "PREPRODUCTION_MATRIX",
            "claim_boundary": mod.CLAIM_BOUNDARY,
            "primary_target": "R_dual_min",
            "implementation_allowlist": sorted(mod.EXPECTED_IMPLEMENTATION_PATHS),
            "promotion_gates": mod.EXPECTED_PROMOTION_GATES,
            "technical_supersession": mod.EXPECTED_TECHNICAL_SUPERSESSION,
            "bootstrap": {"repetitions": 1000, "seed": 20260718},
            "v1_5_immutable_sha256": self.v1_hashes,
            "v1_5_immutable_paths": self.v1_paths,
            "node1_deployment": {
                "remote_root": "/data1/qlyu/projects/pvrig_v6_residue_v2_four_lane_oof_v1_20260718",
                "bundle_root": str(self.root / "bundle"),
                "python": "/data1/qlyu/software/envs/pvrig-v6-tc/bin/python",
                "min_free_gib": 200,
                "augmentation_gpu": mod.AUGMENTATION_GPU,
                "lane_gpu_map": mod.LANE_GPU_MAP,
                "forbidden_gpus": list(mod.FORBIDDEN_GPUS),
                "reserved_gpus": list(mod.RESERVED_GPUS),
                "cpu_threads_per_process": 8,
                "trainer_arguments": mod.EXPECTED_TRAINER_ARGUMENTS,
                "runtime_identity": {
                    "python_executable": self.runtime["python_executable"],
                    "python_version": self.runtime["python_version"],
                    "torch_version": self.runtime["torch_version"],
                    "torch_cuda_version": self.runtime["torch_cuda_version"],
                    "cuda_available": True,
                    "cuda_device_count_min": 8,
                    "gpu_name": "NVIDIA GeForce RTX 4090",
                },
                "artifacts": artifacts,
            },
            "lanes": [
                {"lane": lane, "physical_gpu": gpu, "outer_folds": list(mod.FOLDS)}
                for lane, gpu in mod.LANE_GPU_MAP.items()
            ],
            "production_runs": [
                {"lane": lane, "outer_fold": fold, "physical_gpu": gpu}
                for lane, gpu in mod.LANE_GPU_MAP.items() for fold in mod.FOLDS
            ],
            "sealed_test32_exclusion": {
                "status": "SEALED_UNTIL_PREDICTION_FREEZE",
                "path_access_count": 0,
                "training_use_forbidden": True,
                "hyperparameter_use_forbidden": True,
            },
        }
        self.matrix_path.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n")

    def build(self, *, production: bool) -> dict[str, object]:
        with (
            patch.dict(mod.EXPECTED_V1_5_IMMUTABLE, self.v1_hashes, clear=True),
            patch.dict(mod.EXPECTED_CONTACT_GOVERNANCE_HASHES, self.contact_hashes, clear=True),
            patch.dict(mod.EXPECTED_TRANSITIVE_HASHES, self.transitive_hashes, clear=True),
        ):
            return mod.build_payload(
                residue_root=self.residue,
                matrix_path=self.matrix_path,
                production=production,
                observed_runtime=self.runtime,
            )


class ImplementationFreezeV2Tests(unittest.TestCase):
    def test_production_freeze_closes_4x5_and_defers_only_augmented_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = FreezeFixture(temporary)
            payload = fixture.build(production=True)
            self.assertEqual(payload["status"], mod.PRODUCTION_STATUS)
            self.assertEqual(payload["pending"], [])
            self.assertEqual(len(payload["production_runs"]), 20)
            self.assertEqual(payload["contact_loss_governance"]["status"], "PASS_CONTACT_LOSS_AMENDMENT_V2_2_BOUND")
            self.assertEqual(payload["node1_deployment"]["cpu_threads_per_process"], 8)
            self.assertEqual(payload["node1_deployment"]["lane_gpu_map"], mod.LANE_GPU_MAP)
            augmented = payload["formal_artifacts"]["augmented_target_graph"]
            self.assertEqual(augmented["phase"], "post_augmentation_binding")
            self.assertIsNone(augmented["sha256"])
            self.assertTrue(payload["post_augmentation_contract"]["required_before_smoke_or_production"])

    def test_tampered_static_artifact_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = FreezeFixture(temporary)
            path = Path(json.loads(fixture.matrix_path.read_text())["node1_deployment"]["artifacts"]["training_tsv"]["path"])
            path.write_text("tampered\n")
            with self.assertRaisesRegex(mod.FreezeError, "artifact_hash_mismatch:training_tsv"):
                fixture.build(production=True)

    def test_extra_result_affecting_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = FreezeFixture(temporary)
            (fixture.residue / "src/unregistered_model.py").write_text("pass\n")
            with self.assertRaisesRegex(mod.FreezeError, "implementation_files_extra"):
                fixture.build(production=True)

    def test_missing_allowlisted_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = FreezeFixture(temporary)
            (fixture.residue / "src/residue_model_v2.py").unlink()
            with self.assertRaisesRegex(mod.FreezeError, "implementation_files_missing"):
                fixture.build(production=True)

    def test_pending_static_pair_is_allowed_only_preproduction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = FreezeFixture(temporary, pending_pair=True)
            preproduction = fixture.build(production=False)
            self.assertEqual(preproduction["status"], mod.PREPRODUCTION_STATUS)
            self.assertEqual(preproduction["pending"], ["pair_contact_receipt", "pair_contact_tsv_gz"])
            with self.assertRaisesRegex(mod.FreezeError, "production_pending_artifacts_forbidden"):
                fixture.build(production=True)

    def test_symlinked_result_affecting_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = FreezeFixture(temporary)
            path = fixture.residue / "src/residue_model_v2.py"
            target = fixture.root / "model.py"
            target.write_text("pass\n")
            path.unlink()
            path.symlink_to(target)
            with self.assertRaisesRegex(mod.FreezeError, "missing_or_symlink"):
                fixture.build(production=True)

    def test_check_replays_exact_freeze_and_rejects_matrix_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = FreezeFixture(temporary)
            freeze = fixture.residue / "IMPLEMENTATION_FREEZE_V2.json"
            payload = fixture.build(production=True)
            freeze.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            with (
                patch.dict(mod.EXPECTED_V1_5_IMMUTABLE, fixture.v1_hashes, clear=True),
                patch.dict(mod.EXPECTED_CONTACT_GOVERNANCE_HASHES, fixture.contact_hashes, clear=True),
                patch.dict(mod.EXPECTED_TRANSITIVE_HASHES, fixture.transitive_hashes, clear=True),
            ):
                checked = mod.verify_freeze(
                    freeze,
                    residue_root=fixture.residue,
                    matrix_path=fixture.matrix_path,
                    require_production=True,
                    observed_runtime=fixture.runtime,
                )
            self.assertEqual(checked["status"], mod.CHECK_STATUS)
            matrix = json.loads(fixture.matrix_path.read_text())
            matrix["status"] = "TAMPERED_AFTER_FREEZE"
            fixture.matrix_path.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n")
            with (
                patch.dict(mod.EXPECTED_V1_5_IMMUTABLE, fixture.v1_hashes, clear=True),
                patch.dict(mod.EXPECTED_CONTACT_GOVERNANCE_HASHES, fixture.contact_hashes, clear=True),
                patch.dict(mod.EXPECTED_TRANSITIVE_HASHES, fixture.transitive_hashes, clear=True),
            ):
                with self.assertRaisesRegex(mod.FreezeError, "freeze_replay_mismatch"):
                    mod.verify_freeze(
                        freeze,
                        residue_root=fixture.residue,
                        matrix_path=fixture.matrix_path,
                        require_production=True,
                        observed_runtime=fixture.runtime,
                    )


if __name__ == "__main__":
    unittest.main()
