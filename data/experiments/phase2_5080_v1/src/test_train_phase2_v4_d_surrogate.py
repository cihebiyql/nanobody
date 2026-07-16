#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).with_name("train_phase2_v4_d_surrogate.py")
SPEC = importlib.util.spec_from_file_location("train_phase2_v4_d_surrogate", MODULE_PATH)
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
            raise AssertionError("sealed target was read")
        return super().__getitem__(key)


class TrainV4DSurrogateTest(unittest.TestCase):
    @classmethod
    def synthetic_data(cls) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        layout = (
            (MOD.TRAIN_SPLIT, 20, 226, "T"),
            (MOD.DEVELOPMENT_SPLIT, 3, 32, "D"),
            (MOD.SEALED_SPLIT, 3, 32, "S"),
        )
        manifests: list[dict[str, object]] = []
        teachers: list[dict[str, object]] = []
        amino_acids = MOD.AA_ORDER
        global_index = 0
        for split, cluster_count, row_count, prefix in layout:
            counts = [row_count // cluster_count] * cluster_count
            for index in range(row_count % cluster_count):
                counts[index] += 1
            for cluster_index, count in enumerate(counts):
                cluster = f"{prefix}{cluster_index:02d}"
                for replicate in range(count):
                    candidate_id = f"{split}_{cluster}_{replicate:03d}"
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
                        "sequence_sha256": MOD.sequence_sha256(sequence),
                        "sequence": sequence,
                        "design_method": "RFantibody_RFdiffusion_ProteinMPNN",
                        "design_mode": "H3" if global_index % 2 else "H1H3",
                        "target_patch_id": ("A_CENTER", "B_LOWER", "C_BRIDGE")[
                            global_index % 3
                        ],
                        "cdr1": cdr1,
                        "cdr2": cdr2,
                        "cdr3": cdr3,
                    }
                    manifests.append(manifest)
                    if split != MOD.SEALED_SPLIT:
                        teachers.append(
                            {
                                **manifest,
                                "generic_binding_prior": f"{generic_prior:.9f}",
                                MOD.PRIMARY_TARGET: f"{target:.9f}",
                            }
                        )
                    global_index += 1
        return manifests, teachers

    def test_metrics_have_expected_values_and_bounds(self) -> None:
        target = np.asarray([0.1, 0.2, 0.3, 0.4])
        self.assertAlmostEqual(MOD.spearman(target, target), 1.0)
        self.assertAlmostEqual(MOD.ndcg(target, target), 1.0)
        self.assertAlmostEqual(MOD.top_quartile_recall(target, target), 1.0)
        self.assertEqual(MOD.spearman(target, np.ones_like(target)), 0.0)
        metric = MOD.regression_metrics(target, target[::-1])
        self.assertGreaterEqual(metric["ndcg"], 0.0)
        self.assertLessEqual(metric["ndcg"], 1.0)
        self.assertGreaterEqual(metric["top_quartile_recall_at_25pct_budget"], 0.0)
        self.assertLessEqual(metric["top_quartile_recall_at_25pct_budget"], 1.0)

    def test_split_parent_cluster_leakage_is_rejected(self) -> None:
        manifests, _teachers = self.synthetic_data()
        development_cluster = next(
            row["parent_framework_cluster"]
            for row in manifests
            if row["model_split"] == MOD.DEVELOPMENT_SPLIT
        )
        train_cluster = next(
            row["parent_framework_cluster"]
            for row in manifests
            if row["model_split"] == MOD.TRAIN_SPLIT
        )
        for row in manifests:
            if row["parent_framework_cluster"] == development_cluster:
                row["parent_framework_cluster"] = train_cluster
        with self.assertRaisesRegex(MOD.SurrogateError, "parent_cluster_split_leakage"):
            MOD.validate_split_manifest(manifests)

    def test_missing_teacher_feature_is_rejected(self) -> None:
        manifests, teachers = self.synthetic_data()
        split_by_id = MOD.validate_split_manifest(manifests)
        teachers[0].pop("sequence")
        with self.assertRaisesRegex(MOD.SurrogateError, "missing_fields:teacher:sequence"):
            MOD.validate_teacher_rows(teachers, split_by_id)

    def test_teacher_features_must_close_against_frozen_manifest(self) -> None:
        mutations = {
            "sequence": "ACDEFGHIKLMNPQRSTVWY",
            "sequence_sha256": "0" * 64,
            "cdr1": "ACDEFG",
            "cdr2": "HIKLM",
            "cdr3": "NPQRSTVW",
            "design_method": "WRONG_METHOD",
            "design_mode": "WRONG_MODE",
            "target_patch_id": "WRONG_PATCH",
        }
        for field, replacement in mutations.items():
            with self.subTest(field=field):
                manifests, teachers = self.synthetic_data()
                split_by_id = MOD.validate_split_manifest(manifests)
                teachers[0][field] = replacement
                if field == "sequence":
                    teachers[0]["sequence_sha256"] = MOD.sequence_sha256(replacement)
                with self.assertRaisesRegex(MOD.SurrogateError, "mismatch"):
                    MOD.validate_teacher_rows(teachers, split_by_id)

    def test_manifest_sequence_hash_must_match_manifest_sequence(self) -> None:
        manifests, _teachers = self.synthetic_data()
        manifests[0]["sequence_sha256"] = "0" * 64
        with self.assertRaisesRegex(MOD.SurrogateError, "manifest_sequence_sha256_mismatch"):
            MOD.validate_split_manifest(manifests)

    def test_sealed_target_is_never_accessed(self) -> None:
        manifests, teachers = self.synthetic_data()
        split_by_id = MOD.validate_split_manifest(manifests)
        sealed_manifest = next(
            row for row in manifests if row["model_split"] == MOD.SEALED_SPLIT
        )
        guarded = GuardedTargetRow(
            {
                **sealed_manifest,
                MOD.PRIMARY_TARGET: "THIS_MUST_NOT_BE_READ",
            }
        )
        replaced = list(teachers)
        replaced[0] = guarded
        with self.assertRaisesRegex(MOD.SurrogateError, "teacher_contains_non_open_candidate"):
            MOD.validate_teacher_rows(replaced, split_by_id)
        self.assertEqual(guarded.target_reads, 0)

    def test_group_bootstrap_keeps_parent_rows_together(self) -> None:
        manifests, teachers = self.synthetic_data()
        train_rows, _development_rows = MOD.validate_teacher_rows(
            teachers, MOD.validate_split_manifest(manifests)
        )
        sampled = MOD.group_bootstrap_indices(train_rows, 123)
        original_counts = MOD.Counter(row["parent_framework_cluster"] for row in train_rows)
        sampled_counts = MOD.Counter(
            train_rows[int(index)]["parent_framework_cluster"] for index in sampled
        )
        for group, count in sampled_counts.items():
            self.assertEqual(count % original_counts[group], 0)

    def test_selective_risk_fails_closed_for_zero_or_tied_uncertainty(self) -> None:
        groups = [f"P{index // 8}" for index in range(24)]
        target = np.zeros(24)
        prediction = np.asarray(([0.1] * 6 + [1.0] * 2) * 3)
        zero_uncertainty = np.zeros(24)
        zero_result = MOD.selective_risk(
            target, prediction, zero_uncertainty, groups
        )
        self.assertFalse(zero_result["gate_pass"])
        self.assertFalse(
            zero_result["uncertainty_diagnostics"]["informative_pass"]
        )

        tied_uncertainty = np.asarray(([0.0] * 4 + [1.0] * 4) * 3)
        tied_result = MOD.selective_risk(
            target, prediction, tied_uncertainty, groups
        )
        self.assertFalse(tied_result["gate_pass"])
        self.assertFalse(tied_result["all_parent_uncertainties_informative"])

    def test_parent_aware_selective_risk_can_pass_informative_uncertainty(self) -> None:
        groups = [f"P{index // 8}" for index in range(24)]
        target = np.zeros(24)
        per_parent_errors = [0.1, 0.11, 0.12, 0.2, 0.3, 0.5, 0.8, 1.2]
        prediction = np.asarray(per_parent_errors * 3)
        uncertainty = np.asarray(list(range(8)) * 3, dtype=np.float64)
        result = MOD.selective_risk(target, prediction, uncertainty, groups)
        self.assertTrue(result["uncertainty_diagnostics"]["informative_pass"])
        self.assertTrue(result["all_parent_uncertainties_informative"])
        self.assertTrue(result["gate_pass"])

    def test_relative_improvement_cannot_rescue_negative_absolute_performance(self) -> None:
        candidate = {
            "ensemble_metrics": {
                "spearman": -0.6,
                "top_quartile_recall_at_25pct_budget": 0.5,
            },
            "parent_macro_ensemble_metrics": {
                "macro": {
                    "spearman": -0.5,
                    "top_quartile_recall_at_25pct_budget": 0.5,
                }
            },
        }
        shortcut = {"ensemble_metrics": {"spearman": -0.8}}
        result = MOD.evaluate_open_performance_gates(candidate, shortcut)
        self.assertTrue(result["gates"]["relative_spearman_delta"]["passed"])
        self.assertFalse(result["gates"]["absolute_spearman"]["passed"])
        self.assertFalse(result["gates"]["parent_macro_spearman"]["passed"])
        self.assertFalse(result["all_passed"])

    def test_frozen_candidate_is_deterministic(self) -> None:
        manifests, teachers = self.synthetic_data()
        train_rows, development_rows = MOD.validate_teacher_rows(
            teachers, MOD.validate_split_manifest(manifests)
        )
        kwargs = {
            "model_name": "frozen_feature_ridge",
            "train_rows": train_rows,
            "development_rows": development_rows,
            "target": MOD.PRIMARY_TARGET,
            "alphas": (0.1, 1.0),
            "ensemble_seeds": (11, 12, 13),
            "frozen_feature_width": 24,
        }
        first = MOD.train_one_model(**kwargs)
        second = MOD.train_one_model(**kwargs)
        np.testing.assert_array_equal(first["ensemble_prediction"], second["ensemble_prediction"])
        np.testing.assert_array_equal(first["ensemble_uncertainty"], second["ensemble_uncertainty"])
        self.assertEqual(first["selected_alpha"], second["selected_alpha"])
        self.assertEqual(first["ensemble_metrics"], second["ensemble_metrics"])
        self.assertFalse(first["ensemble_metric_distribution"]["is_confidence_interval"])
        self.assertIn("not a confidence interval", first["ensemble_metric_distribution"]["interpretation"])

    def test_pipeline_writes_frozen_hash_bound_artifacts(self) -> None:
        manifests, teachers = self.synthetic_data()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            split_path = root / "split.tsv"
            teacher_path = root / "teacher.tsv"
            audit_path = root / "teacher.tsv.audit.json"
            out_dir = root / "out"
            write_tsv(split_path, manifests)
            write_tsv(teacher_path, teachers)
            audit = {
                "status": "PASS_V4_D_OPEN_CONTINUOUS_TEACHER_RELEASE",
                "release": "open_train_and_open_development_only",
                "inputs": {"split_manifest_sha256": MOD.sha256_file(split_path)},
                "sealed_data_boundary": {
                    "raw_job_results_opened": 0,
                    "sealed_metrics_used_for_teacher_or_ranking": False,
                },
                "output": {"sha256": MOD.sha256_file(teacher_path)},
            }
            audit_path.write_text(json.dumps(audit), encoding="utf-8")
            result = MOD.run_pipeline(
                teacher_path,
                audit_path,
                split_path,
                out_dir,
                alphas=(0.1, 1.0),
                ensemble_seeds=(11, 12, 13),
                frozen_feature_width=24,
                enforce_production_split_hash=False,
            )
            self.assertFalse(result["prospective_test_labels_read"])
            expected = (
                "frozen_open_model_config.json",
                "frozen_open_model_artifact.json",
                "open_development_predictions.tsv",
                "open_development_summary.json",
                "frozen_open_artifact_sha256_receipt.json",
            )
            self.assertTrue(all((out_dir / name).is_file() for name in expected))
            summary = json.loads((out_dir / "open_development_summary.json").read_text())
            config = json.loads((out_dir / "frozen_open_model_config.json").read_text())
            self.assertEqual(config["runtime_provenance"]["numpy_version"], np.__version__)
            self.assertTrue(config["runtime_provenance"]["python_version"])
            self.assertEqual(summary["fit"]["rows"], 226)
            self.assertEqual(summary["selection"]["rows"], 32)
            self.assertFalse(summary["prospective_test"]["labels_read"])
            self.assertEqual(summary["prospective_test"]["label_files_opened"], 0)
            self.assertEqual(set(summary["models"]), set(MOD.MODEL_NAMES))
            self.assertEqual(
                summary["serialized_artifact_prediction_roundtrip"]["status"],
                "PASS_SERIALIZED_ARTIFACT_PREDICTION_ROUNDTRIP",
            )
            for model in summary["models"].values():
                distribution = model["bootstrap_seed_metric_distribution"]
                self.assertFalse(distribution["is_confidence_interval"])
                self.assertIn("not a confidence interval", distribution["interpretation"])
            receipt = json.loads(
                (out_dir / "frozen_open_artifact_sha256_receipt.json").read_text()
            )
            self.assertEqual(receipt["status"], "PASS_FROZEN_OPEN_ARTIFACT_HASH_CLOSURE")
            self.assertFalse(
                receipt["publication"]["stale_receipt_removed_before_replacement"]
            )
            self.assertTrue(receipt["publication"]["receipt_published_last"])
            for path, expected_hash in receipt["outputs"].items():
                self.assertEqual(MOD.sha256_file(Path(path)), expected_hash)
            predictions = MOD.read_tsv(out_dir / "open_development_predictions.tsv")
            self.assertEqual(len(predictions), 32)
            self.assertTrue(all(row["model_split"] == MOD.DEVELOPMENT_SPLIT for row in predictions))

            _train_rows, development_rows = MOD.validate_teacher_rows(
                teachers, MOD.validate_split_manifest(manifests)
            )
            artifact = MOD.load_model_artifact(
                out_dir / "frozen_open_model_artifact.json",
                expected_config_sha256=MOD.sha256_file(
                    out_dir / "frozen_open_model_config.json"
                ),
            )
            selected = summary["selected_candidate_model"]
            replay_prediction, replay_uncertainty = MOD.predict_serialized_model(
                artifact, selected, development_rows
            )
            np.testing.assert_array_equal(
                np.round(replay_prediction, 9),
                np.asarray([float(row["selected_prediction"]) for row in predictions]),
            )
            np.testing.assert_array_equal(
                np.round(replay_uncertainty, 9),
                np.asarray([float(row["selected_uncertainty"]) for row in predictions]),
            )

            # A malformed stale receipt is removed before a complete staged replacement.
            (out_dir / "frozen_open_artifact_sha256_receipt.json").write_text(
                '{"status":"STALE"}\n', encoding="utf-8"
            )
            MOD.run_pipeline(
                teacher_path,
                audit_path,
                split_path,
                out_dir,
                alphas=(0.1, 1.0),
                ensemble_seeds=(11, 12, 13),
                frozen_feature_width=24,
                enforce_production_split_hash=False,
            )
            replacement_receipt = json.loads(
                (out_dir / "frozen_open_artifact_sha256_receipt.json").read_text()
            )
            self.assertEqual(
                replacement_receipt["status"],
                "PASS_FROZEN_OPEN_ARTIFACT_HASH_CLOSURE",
            )
            self.assertTrue(
                replacement_receipt["publication"][
                    "stale_receipt_removed_before_replacement"
                ]
            )
            self.assertFalse(list(root.glob(".out.stage.*")))

    def test_publication_rejects_unexpected_existing_output_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out_dir = Path(temporary) / "out"
            out_dir.mkdir()
            (out_dir / "unrelated.txt").write_text("do not overwrite", encoding="utf-8")
            with self.assertRaisesRegex(
                MOD.SurrogateError, "unexpected_existing_output_files"
            ):
                MOD.validate_existing_output_directory(out_dir)

    def test_teacher_audit_rejects_any_sealed_raw_result_access(self) -> None:
        manifests, teachers = self.synthetic_data()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            split_path = root / "split.tsv"
            teacher_path = root / "teacher.tsv"
            audit_path = root / "audit.json"
            write_tsv(split_path, manifests)
            write_tsv(teacher_path, teachers)
            audit_path.write_text(
                json.dumps(
                    {
                        "status": "PASS_V4_D_OPEN_CONTINUOUS_TEACHER_RELEASE",
                        "release": "open_train_and_open_development_only",
                        "inputs": {"split_manifest_sha256": MOD.sha256_file(split_path)},
                        "sealed_data_boundary": {
                            "raw_job_results_opened": 1,
                            "sealed_metrics_used_for_teacher_or_ranking": False,
                        },
                        "output": {"sha256": MOD.sha256_file(teacher_path)},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                MOD.SurrogateError, "teacher_audit_reports_sealed_raw_results_opened"
            ):
                MOD.validate_teacher_audit(teacher_path, audit_path, split_path)


if __name__ == "__main__":
    unittest.main()
