#!/usr/bin/env python3
"""Adversarial synthetic-only tests for the V4-D-DEV1 trainer.

No repository Docking result, V4-D teacher, or prospective-test label is read.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name(
    "train_phase2_v4_d_dev1_sequence_surrogate.py"
)
SPEC = importlib.util.spec_from_file_location(
    "train_phase2_v4_d_dev1_sequence_surrogate", MODULE_PATH
)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


class GuardedTargetRow(dict[str, object]):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.target_reads = 0

    def __getitem__(self, key: str) -> object:
        if key == MOD.PRIMARY_TARGET:
            self.target_reads += 1
            raise AssertionError("prospective target was read")
        return super().__getitem__(key)

    def get(self, key: str, default: object = None) -> object:
        if key == MOD.PRIMARY_TARGET:
            self.target_reads += 1
            raise AssertionError("prospective target was read")
        return super().get(key, default)


class TrainV4DDev1SurrogateTest(unittest.TestCase):
    @classmethod
    def synthetic_data(cls) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        layout = (
            (MOD.TRAIN_SPLIT, 20, 226, "T"),
            (MOD.DEVELOPMENT_SPLIT, 3, 32, "D"),
            (MOD.FORBIDDEN_SPLIT, 3, 32, "S"),
        )
        manifests: list[dict[str, object]] = []
        teachers: list[dict[str, object]] = []
        amino_acids = MOD.base.AA_ORDER
        global_index = 0
        for split, cluster_count, row_count, prefix in layout:
            counts = [row_count // cluster_count] * cluster_count
            for index in range(row_count % cluster_count):
                counts[index] += 1
            for cluster_index, count in enumerate(counts):
                cluster = f"{prefix}{cluster_index:02d}"
                for replicate in range(count):
                    candidate_id = f"SYNTHETIC_{split}_{cluster}_{replicate:03d}"
                    cdr3_length = 9 + (global_index % 8)
                    cdr3 = "C" + "".join(
                        amino_acids[(global_index + offset * 3) % len(amino_acids)]
                        for offset in range(cdr3_length - 2)
                    ) + "W"
                    cdr1 = "GFTF" + amino_acids[global_index % len(amino_acids)] + "SY"
                    cdr2 = "IS" + amino_acids[(global_index * 3) % len(amino_acids)] + "GGT"
                    sequence = (
                        "QVQLVESGGGLVQPGGSLRLSCAAS"
                        + cdr1
                        + "MGWYRQAPGKERELVA"
                        + cdr2
                        + "AYKDSVKGRFTISRDFSRSTMYLQMNSLKPEDTAIYYC"
                        + cdr3
                        + "GQGTQVTVSS"
                    )
                    generic_prior = 0.1 + 0.03 * (global_index % 7)
                    target = (
                        0.15
                        + 0.015 * cdr3_length
                        + 0.08 * (cdr3.count("W") + cdr3.count("Y"))
                        + 0.25 * generic_prior
                        + 0.005 * cluster_index
                    )
                    manifest = {
                        "candidate_id": candidate_id,
                        "model_split": split,
                        "parent_framework_cluster": cluster,
                        "sequence_sha256": MOD.base.sequence_sha256(sequence),
                        "sequence": sequence,
                        "design_method": "SYNTHETIC_METHOD",
                        "design_mode": "H3" if global_index % 2 else "H1H3",
                        "target_patch_id": ("A_CENTER", "B_LOWER", "C_BRIDGE")[
                            global_index % 3
                        ],
                        "cdr1": cdr1,
                        "cdr2": cdr2,
                        "cdr3": cdr3,
                    }
                    manifests.append(manifest)
                    if split != MOD.FORBIDDEN_SPLIT:
                        teachers.append(
                            {
                                **manifest,
                                "generic_binding_prior": f"{generic_prior:.9f}",
                                MOD.PRIMARY_TARGET: f"{target:.9f}",
                                "R_8X6B": f"{target + 0.01:.9f}",
                                "R_9E6Y": f"{target - 0.01:.9f}",
                            }
                        )
                    global_index += 1
        return manifests, teachers

    @staticmethod
    def teacher_audit(
        teacher_path: Path, split_path: Path, teachers: list[dict[str, object]]
    ) -> dict[str, object]:
        return {
            "status": MOD.EXPECTED_TEACHER_STATUS,
            "release": MOD.EXPECTED_TEACHER_RELEASE,
            "source_evaluator": {
                "status": "FAIL",
                "unlockable": False,
                "failed_gates": [MOD.EXPECTED_FAILED_GATE],
                "sha256": MOD.EXPECTED_SOURCE_EVALUATOR_SHA256,
            },
            "formal_v4_f_unlock_eligible": False,
            "claim_boundary": MOD.CLAIM_BOUNDARY,
            "non_authority": {
                "formal_completion_or_unlock_receipt_created": False,
                "formal_v4_f_unlock_eligible": False,
            },
            "sealed_data_boundary": {
                "raw_test32_job_files_opened": 0,
                "test32_metric_values_read": 0,
                "test32_label_rows_emitted": 0,
            },
            "inputs": {"split_manifest_sha256": MOD.sha256_file(split_path)},
            "output": {
                "row_count": 258,
                "split_counts": {MOD.TRAIN_SPLIT: 226, MOD.DEVELOPMENT_SPLIT: 32},
                "sha256": MOD.sha256_file(teacher_path),
                "exact_header": list(teachers[0]),
            },
        }

    def test_model_and_seed_contract_is_exact(self) -> None:
        self.assertEqual(
            MOD.MODEL_NAMES,
            (
                "constant",
                "parent_only",
                "metadata_shortcut",
                "cdr3_only",
                "handcrafted_full_sequence",
                "generic_prior_only",
                "frozen_feature_ridge",
            ),
        )
        self.assertEqual(len(MOD.FIXED_GROUP_BOOTSTRAP_SEEDS), 5)
        self.assertEqual(len(set(MOD.FIXED_GROUP_BOOTSTRAP_SEEDS)), 5)
        self.assertEqual(MOD.PRIMARY_TARGET, "R_dual_min")

    def test_prospective_teacher_row_rejected_before_target_read(self) -> None:
        manifests, teachers = self.synthetic_data()
        sealed_manifest = next(
            row for row in manifests if row["model_split"] == MOD.FORBIDDEN_SPLIT
        )
        guarded = GuardedTargetRow(
            {
                **sealed_manifest,
                "generic_binding_prior": "0.5",
                MOD.PRIMARY_TARGET: "DO_NOT_READ",
            }
        )
        replaced = list(teachers)
        replaced[0] = guarded
        split_by_id = MOD.validate_split_manifest(manifests)
        with self.assertRaisesRegex(
            MOD.Dev1SurrogateError,
            "dev1_teacher_contains_prospective_computational_test",
        ):
            MOD.validate_teacher_rows(replaced, split_by_id)
        self.assertEqual(guarded.target_reads, 0)

    def test_teacher_258_and_226_plus_32_closure_is_required(self) -> None:
        manifests, teachers = self.synthetic_data()
        split_by_id = MOD.validate_split_manifest(manifests)
        with self.assertRaisesRegex(
            MOD.Dev1SurrogateError, "dev1_teacher_row_count_mismatch:257"
        ):
            MOD.validate_teacher_rows(teachers[:-1], split_by_id)

        wrong_split = [dict(row) for row in teachers]
        development_index = next(
            index
            for index, row in enumerate(wrong_split)
            if row["model_split"] == MOD.DEVELOPMENT_SPLIT
        )
        wrong_split[development_index]["model_split"] = MOD.TRAIN_SPLIT
        with self.assertRaisesRegex(
            MOD.Dev1SurrogateError, "dev1_teacher_split_count_mismatch"
        ):
            MOD.validate_teacher_rows(wrong_split, split_by_id)

    def test_parent_cluster_overlap_is_rejected_by_label_free_manifest(self) -> None:
        manifests, _teachers = self.synthetic_data()
        train_cluster = next(
            row["parent_framework_cluster"]
            for row in manifests
            if row["model_split"] == MOD.TRAIN_SPLIT
        )
        development_cluster = next(
            row["parent_framework_cluster"]
            for row in manifests
            if row["model_split"] == MOD.DEVELOPMENT_SPLIT
        )
        for row in manifests:
            if row["parent_framework_cluster"] == development_cluster:
                row["parent_framework_cluster"] = train_cluster
        with self.assertRaisesRegex(
            MOD.Dev1SurrogateError, "parent_cluster_split_leakage"
        ):
            MOD.validate_split_manifest(manifests)

    def test_teacher_audit_requires_all_test32_counters_zero(self) -> None:
        manifests, teachers = self.synthetic_data()
        for field in (
            "raw_test32_job_files_opened",
            "test32_metric_values_read",
            "test32_label_rows_emitted",
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                split_path = root / "split.tsv"
                teacher_path = root / "teacher.tsv"
                audit_path = root / "audit.json"
                write_tsv(split_path, manifests)
                write_tsv(teacher_path, teachers)
                audit = self.teacher_audit(teacher_path, split_path, teachers)
                audit["sealed_data_boundary"][field] = 1  # type: ignore[index]
                audit_path.write_text(json.dumps(audit), encoding="utf-8")
                with self.assertRaisesRegex(
                    MOD.Dev1SurrogateError, f"dev1_teacher_nonzero_sealed_counter:{field}"
                ):
                    MOD.validate_teacher_audit(teacher_path, audit_path, split_path)

    def test_teacher_audit_requires_explicit_non_authority(self) -> None:
        manifests, teachers = self.synthetic_data()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            split_path = root / "split.tsv"
            teacher_path = root / "teacher.tsv"
            audit_path = root / "audit.json"
            write_tsv(split_path, manifests)
            write_tsv(teacher_path, teachers)
            mutations = (
                ("top_unlock", lambda audit: audit.__setitem__("formal_v4_f_unlock_eligible", True), "unlock_eligible_not_false"),
                ("receipt", lambda audit: audit["non_authority"].__setitem__("formal_completion_or_unlock_receipt_created", True), "receipt_flag_mismatch"),
                ("nested_unlock", lambda audit: audit["non_authority"].__setitem__("formal_v4_f_unlock_eligible", True), "unlock_flag_mismatch"),
                ("claim", lambda audit: audit.__setitem__("claim_boundary", "development only"), "claim_boundary_missing"),
            )
            for name, mutate, error in mutations:
                with self.subTest(name=name):
                    audit = self.teacher_audit(teacher_path, split_path, teachers)
                    mutate(audit)
                    audit_path.write_text(json.dumps(audit), encoding="utf-8")
                    with self.assertRaisesRegex(MOD.Dev1SurrogateError, error):
                        MOD.validate_teacher_audit(teacher_path, audit_path, split_path)

    def test_failed_source_evaluator_cannot_be_rewritten_as_pass_or_unlockable(self) -> None:
        manifests, teachers = self.synthetic_data()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            split_path = root / "split.tsv"
            teacher_path = root / "teacher.tsv"
            audit_path = root / "audit.json"
            write_tsv(split_path, manifests)
            write_tsv(teacher_path, teachers)
            for field, value, error in (
                ("status", "PASS", "status_not_fail"),
                ("unlockable", True, "unlockable_not_false"),
            ):
                audit = self.teacher_audit(teacher_path, split_path, teachers)
                audit["source_evaluator"][field] = value  # type: ignore[index]
                audit_path.write_text(json.dumps(audit), encoding="utf-8")
                with self.assertRaisesRegex(MOD.Dev1SurrogateError, error):
                    MOD.validate_teacher_audit(teacher_path, audit_path, split_path)

    def test_formal_paths_and_authoritative_statuses_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in (
                "v4_d_dev1_formal",
                "v4_d_dev1_v4_f",
                "v4_d_dev1_unlock",
                "v4_d_dev1_completion",
            ):
                with self.subTest(path=name), self.assertRaisesRegex(
                    MOD.Dev1SurrogateError, "impersonates_authority"
                ):
                    MOD.validate_dev_only_output_path(root / name)
            for status in (
                "PASS_FORMAL_MODEL",
                "DEV_ONLY_FORMAL_PASS",
                "DEV_ONLY_V4_F_UNLOCK",
                "DEV_ONLY_COMPLETION",
            ):
                with self.subTest(status=status), self.assertRaises(
                    MOD.Dev1SurrogateError
                ):
                    MOD.validate_dev_only_status(status)

    def test_output_and_parent_symlinks_are_rejected_before_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "ordinary_destination"
            real.mkdir()
            parent_link = root / "dev1_parent_link"
            parent_link.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(
                MOD.Dev1SurrogateError, "dev1_output_path_symlink_forbidden"
            ):
                MOD.validate_dev_only_output_path(parent_link / "output")

            real_output = root / "ordinary_output"
            real_output.mkdir()
            output_link = root / "dev1_output_link"
            output_link.symlink_to(real_output, target_is_directory=True)
            with self.assertRaisesRegex(
                MOD.Dev1SurrogateError, "dev1_output_path_symlink_forbidden"
            ):
                MOD.validate_dev_only_output_path(output_link)

    def test_synthetic_pipeline_publishes_dev_only_hash_closed_outputs(self) -> None:
        manifests, teachers = self.synthetic_data()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            split_path = root / "split.tsv"
            teacher_path = root / "teacher.tsv"
            audit_path = root / "teacher.audit.json"
            out_dir = root / "pvrig_v4_d_dev1_synthetic"
            prereg_path = (
                MODULE_PATH.parents[1]
                / "audits/phase2_v4_d_dev1_sequence_surrogate_v1_preregistration.json"
            )
            write_tsv(split_path, manifests)
            write_tsv(teacher_path, teachers)
            audit_path.write_text(
                json.dumps(self.teacher_audit(teacher_path, split_path, teachers)),
                encoding="utf-8",
            )
            result = MOD.run_pipeline(
                teacher_path,
                audit_path,
                split_path,
                prereg_path,
                out_dir,
                enforce_production_hashes=False,
            )
            self.assertEqual(result["test32_raw_label_files_opened"], 0)
            self.assertEqual(result["test32_labels_read"], 0)
            self.assertEqual(result["test32_metric_values_read"], 0)
            self.assertFalse(result["formal_completion_or_unlock_receipt"])
            self.assertEqual(set(path.name for path in out_dir.iterdir()), set(MOD.OUTPUT_FILENAMES))
            self.assertFalse(any("formal" in name.lower() for name in MOD.OUTPUT_FILENAMES))
            self.assertFalse(any("unlock" in name.lower() for name in MOD.OUTPUT_FILENAMES))
            self.assertFalse(any("completion" in name.lower() for name in MOD.OUTPUT_FILENAMES))

            config = json.loads((out_dir / MOD.OUTPUT_FILENAMES[0]).read_text())
            artifact = json.loads((out_dir / MOD.OUTPUT_FILENAMES[1]).read_text())
            predictions = MOD.read_tsv(out_dir / MOD.OUTPUT_FILENAMES[2])
            summary = json.loads((out_dir / MOD.OUTPUT_FILENAMES[3]).read_text())
            receipt = json.loads((out_dir / MOD.OUTPUT_FILENAMES[4]).read_text())
            for payload in (config, artifact, summary, receipt):
                MOD.validate_dev_only_status(payload["status"])
                self.assertFalse(payload["deployment_eligible"])
                self.assertFalse(payload["formal_completion_or_unlock_receipt"])
            self.assertEqual(config["seed_count"], 5)
            self.assertEqual(config["fixed_group_bootstrap_seeds"], list(MOD.FIXED_GROUP_BOOTSTRAP_SEEDS))
            self.assertEqual(config["fit_rows"], 226)
            self.assertEqual(config["selection_rows"], 32)
            self.assertEqual(config["selection_rows_used_as_fit_rows"], 0)
            self.assertEqual(config["parent_cluster_isolation_audit"]["overlap_count"], 0)
            self.assertEqual(config["test32"]["raw_label_files_opened"], 0)
            self.assertEqual(config["test32"]["labels_read"], 0)
            self.assertEqual(config["test32"]["metric_values_read"], 0)
            self.assertEqual(artifact["test32_raw_label_files_opened"], 0)
            self.assertEqual(artifact["test32_labels_read"], 0)
            self.assertEqual(artifact["test32_metric_values_read"], 0)
            self.assertEqual(summary["test32"]["raw_label_files_opened"], 0)
            self.assertEqual(summary["test32"]["labels_read"], 0)
            self.assertEqual(summary["test32"]["metric_values_read"], 0)
            self.assertTrue(summary["test32"]["remains_sealed"])
            self.assertEqual(len(predictions), 32)
            self.assertTrue(
                all(row["model_split"] == MOD.DEVELOPMENT_SPLIT for row in predictions)
            )
            self.assertEqual(receipt["status"], MOD.RECEIPT_STATUS)
            self.assertEqual(receipt["test32_raw_label_files_opened"], 0)
            self.assertEqual(receipt["test32_labels_read"], 0)
            self.assertEqual(receipt["test32_metric_values_read"], 0)
            for path, expected_hash in receipt["outputs"].items():
                self.assertEqual(MOD.sha256_file(Path(path)), expected_hash)


if __name__ == "__main__":
    unittest.main()
