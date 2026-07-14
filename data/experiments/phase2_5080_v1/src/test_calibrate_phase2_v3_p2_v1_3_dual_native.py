from __future__ import annotations

import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from experiments.phase2_5080_v1.src import (
    calibrate_phase2_v3_p2_v1_3_dual_native as calibration,
)


class V13SyntheticFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.positive_manifest = root / "positive_manifest.csv"
        self.mutant_manifest = root / "mutant_manifest.csv"
        self.metrics_csv = root / "native_metrics.csv"
        self.processor_audit = root / "processor_audit.json"
        self.preregistration = calibration.DEFAULT_PREREGISTRATION
        self.positive_cases: dict[str, dict[str, str]] = {}
        self.mutant_cases: dict[str, dict[str, str]] = {}
        self.base_by_molecule: dict[str, str] = {}
        self.metrics_rows: list[dict[str, str]] = []
        self._build_manifests()
        self._build_metrics()
        self._build_processor_audit()

    def _write_rows(
        self, path: Path, fields: list[str], rows: list[dict[str, str]]
    ) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def _build_manifests(self) -> None:
        positive_families = ["151", "151", "151", "20", "20", "30", "30", "38", "39", "39", "39"]
        positive_rows: list[dict[str, str]] = []
        for index, family in enumerate(positive_families, start=1):
            case_id = f"positive_{index:02d}"
            positive_rows.append(
                {
                    "calibration_name": case_id,
                    "family": family,
                    "validation_role": "synthetic_positive_anchor",
                }
            )
            self.positive_cases[case_id] = {"family": family}
        self._write_rows(
            self.positive_manifest,
            ["calibration_name", "family", "validation_role"],
            positive_rows,
        )

        mutant_rows: list[dict[str, str]] = []
        mutation_counts = [5, 4, 4, 4, 4, 4, 4]
        control_families = ["20", "30", "38", "39", "151", "20", "39"]
        for group, (mutation_count, family) in enumerate(
            zip(mutation_counts, control_families)
        ):
            molecule = f"molecule_{group}"
            base_id = f"control_{group}_base"
            base_row = {
                "mutant_name": base_id,
                "base_molecule": molecule,
                "family": family,
                "control_type": "base_reference",
                "mutation_class": "unmutated_positive_control",
                "mutations_1based": "none",
            }
            mutant_rows.append(base_row)
            self.mutant_cases[base_id] = dict(base_row)
            self.base_by_molecule[molecule] = base_id
            for mutation in range(mutation_count):
                case_id = f"control_{group}_mut_{mutation}"
                row = {
                    "mutant_name": case_id,
                    "base_molecule": molecule,
                    "family": family,
                    "control_type": "mutant",
                    "mutation_class": "synthetic_perturbation",
                    "mutations_1based": f"A{mutation + 1}G",
                }
                mutant_rows.append(row)
                self.mutant_cases[case_id] = dict(row)
        self._write_rows(
            self.mutant_manifest,
            [
                "mutant_name", "base_molecule", "family", "control_type",
                "mutation_class", "mutations_1based",
            ],
            mutant_rows,
        )
        if len(mutant_rows) != 36:
            raise AssertionError("Synthetic control manifest did not close 36 rows")

    def _build_metrics(self) -> None:
        inventory = calibration.canonical_json(
            {
                "selection_rule": "protein ATOM heavy atoms only; all HETATM excluded",
                "selected_protein_heavy_atom_count": 100,
                "protein_atom_heavy_atom_count": 100,
                "selected_protein_residue_count": 20,
                "protein_atom_residue_count": 20,
            }
        )
        family_by_case = {
            **{case_id: row["family"] for case_id, row in self.positive_cases.items()},
            **{case_id: row["family"] for case_id, row in self.mutant_cases.items()},
        }
        fields = sorted(calibration.REQUIRED_METRICS_FIELDS - {"metrics_row_sha256"})
        fields.append("metrics_row_sha256")
        rows: list[dict[str, str]] = []
        for case_index, case_id in enumerate(sorted(family_by_case)):
            is_positive = case_id in self.positive_cases
            for receptor_index, receptor in enumerate(calibration.RECEPTORS):
                for rank in range(1, 9):
                    signal_index = case_index if is_positive else case_index % 13
                    h_value = (
                        0.18
                        + 0.025 * (signal_index % 11)
                        + 0.018 * rank
                        + 0.025 * receptor_index
                    )
                    total = 18 + 3 * (signal_index % 12) + 4 * rank + 7 * receptor_index
                    cdr_fraction = 0.16 + 0.018 * ((signal_index + rank + receptor_index) % 9)
                    cdr_total = max(1, min(total, round(total * cdr_fraction)))
                    cdr1 = cdr_total // 3
                    cdr2 = cdr_total // 3
                    cdr3 = cdr_total - cdr1 - cdr2
                    record = {
                        "schema_version": calibration.METRICS_SCHEMA_VERSION,
                        "protocol_id": calibration.PROTOCOL_ID,
                        "formal_eligible": "false",
                        "training_label_release_eligible": "false",
                        "docking_gold_release_eligible": "false",
                        "primary_native_metric_eligible": "true",
                        "candidate_id": case_id,
                        "family": family_by_case[case_id],
                        "run_id": f"run_{case_id}_{receptor}",
                        "generation_receptor": receptor,
                        "native_rank": str(rank),
                        "selector_row_sha256": calibration.sha256_json(
                            ["selector", case_id, receptor, rank]
                        ),
                        "aligned_pose_sha256": calibration.sha256_json(
                            ["pose", case_id, receptor, rank]
                        ),
                        "reference_sha256": calibration.sha256_json(
                            ["reference", receptor]
                        ),
                        "hotspot_weight_fraction": format(min(h_value, 0.95), ".17g"),
                        "total_occluding_residue_pair_count": str(total),
                        "cdr1_occluding_residue_pair_count": str(cdr1),
                        "cdr2_occluding_residue_pair_count": str(cdr2),
                        "cdr3_occluding_residue_pair_count": str(cdr3),
                        "reference_pvrl2_record_inventory_json": inventory,
                    }
                    record["metrics_row_sha256"] = calibration.row_sha256(
                        record, "metrics_row_sha256"
                    )
                    rows.append(record)
        self._write_rows(self.metrics_csv, fields, rows)
        self.metrics_rows = rows
        if len(rows) != 752:
            raise AssertionError("Synthetic native metric table did not close 752 rows")

    def _build_processor_audit(self) -> None:
        payload = {
            "schema_version": calibration.PROCESSOR_AUDIT_SCHEMA_VERSION,
            "status": calibration.PROCESSOR_PASS_STATUS,
            "protocol_id": calibration.PROTOCOL_ID,
            "formal_eligible": False,
            "training_label_release_eligible": False,
            "docking_gold_release_eligible": False,
            "primary_native_metric_eligible": True,
            "observed_contract": {
                "case_count": 47,
                "run_count": 94,
                "materialization_rows": 752,
                "metric_rows": 752,
                "contact_records": 752,
                "aligned_pose_files": 752,
                "rows_by_generation_receptor": {"8X6B": 376, "9E6Y": 376},
            },
            "output_sha256": {
                "continuous_metrics": {
                    "relpath": self.metrics_csv.as_posix(),
                    "sha256": calibration.sha256_file(self.metrics_csv),
                    "rows": 752,
                    "row_hash_chain": calibration.row_hash_chain(
                        self.metrics_rows, "metrics_row_sha256"
                    ),
                }
            },
        }
        calibration.write_json(self.processor_audit, payload)

    def load_inputs(self):
        fields, rows = calibration.read_csv_strict(self.metrics_csv)
        positive = calibration.load_positive_manifest(self.positive_manifest)
        mutants, bases = calibration.load_mutant_manifest(self.mutant_manifest)
        return fields, rows, positive, mutants, bases


class TestV13NativeDualCalibration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.fixture = V13SyntheticFixture(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_central_counts_mapping_and_no_cross_receptor_rank_pairing(self) -> None:
        fields, rows, positive, mutants, _bases = self.fixture.load_inputs()
        observed = calibration.validate_metrics_rows(
            fields,
            rows,
            positive,
            mutants,
            calibration.CalibrationContract(),
        )
        rules = calibration.derive_rules(rows, positive, 8)
        weighted_values = calibration.anchor_metric_values(rows, positive, 8)
        pose_rows = calibration.score_pose_rows(rows, rules)
        run_rows = calibration.aggregate_native_runs(pose_rows, positive)
        dual_rows = calibration.aggregate_dual_candidates(run_rows)
        self.assertEqual(observed["rows_by_generation_receptor"], {"8X6B": 376, "9E6Y": 376})
        self.assertEqual(len(pose_rows), 752)
        self.assertEqual(len(run_rows), 94)
        self.assertEqual(len(dual_rows), 47)
        self.assertEqual(rules["primary_channel_count"], 5)
        self.assertAlmostEqual(sum(weight for _value, weight in weighted_values["pooled_H"]), 1.0)
        for receptor in calibration.RECEPTORS:
            for metric in ("O", "P"):
                self.assertAlmostEqual(
                    sum(
                        weight
                        for _value, weight in weighted_values["receptor"][receptor][metric]
                    ),
                    1.0,
                )
        self.assertEqual(calibration.CLASS_RELEVANCE, {"A": 4, "B": 2, "C": 1, "E": 0})
        self.assertTrue(all(row["cross_reference_used"] == "false" for row in pose_rows))
        self.assertTrue(all(row["cross_receptor_rank_pairing"] == "false" for row in run_rows))
        self.assertTrue(all(row["cross_receptor_rank_pairing"] == "false" for row in dual_rows))
        self.assertTrue(all(row["candidate_level_join_only"] == "true" for row in dual_rows))
        self.assertNotIn("R_gold", calibration.DUAL_SCORE_FIELDS)
        expected_map = {
            ("A", "A"): "G1",
            ("A", "B"): "G2",
            ("B", "A"): "G2",
            ("B", "B"): "G3",
            ("A", "C"): "G4",
            ("C", "A"): "G4",
            ("B", "C"): "G4",
            ("C", "B"): "G4",
            ("C", "C"): "G4",
        }
        for pair, tier in expected_map.items():
            self.assertEqual(calibration.dual_tier(*pair), tier)
        for other in calibration.POSE_CLASSES:
            self.assertEqual(calibration.dual_tier("E", other), "G5")
            self.assertEqual(calibration.dual_tier(other, "E"), "G5")

        by_case = {row["candidate_id"]: row for row in dual_rows}
        selected = by_case[sorted(by_case)[0]]
        native_runs = {
            row["generation_receptor"]: row
            for row in run_rows
            if row["candidate_id"] == selected["candidate_id"]
        }
        self.assertAlmostEqual(
            float(selected["R_dual_dev"]),
            (float(native_runs["8X6B"]["R_native"]) + float(native_runs["9E6Y"]["R_native"])) / 2,
        )

    def test_full_B2000_bootstrap_exact_counts_and_small_B_determinism(self) -> None:
        _fields, rows, positive, _mutants, _bases = self.fixture.load_inputs()
        thresholds, receptor_rows, dual_rows = calibration.hierarchical_bootstrap_rows(
            rows, positive, 8, seed=calibration.BOOTSTRAP_SEED, replicates=2000
        )
        self.assertEqual(len(thresholds), 20000)
        self.assertEqual(len(receptor_rows), 44000)
        self.assertEqual(len(dual_rows), 22000)
        self.assertEqual(
            {row["channel"] for row in thresholds},
            {
                "canonical_pooled_H", "8X6B_native_O", "8X6B_native_P",
                "9E6Y_native_O", "9E6Y_native_P",
            },
        )
        first = calibration.hierarchical_bootstrap_rows(
            rows, positive, 8, seed=1234, replicates=3
        )
        second = calibration.hierarchical_bootstrap_rows(
            rows, positive, 8, seed=1234, replicates=3
        )
        hash_fields = (
            "bootstrap_threshold_row_sha256",
            "bootstrap_receptor_row_sha256",
            "bootstrap_dual_row_sha256",
        )
        for left, right, hash_field in zip(first, second, hash_fields):
            self.assertEqual(
                calibration.row_hash_chain(left, hash_field),
                calibration.row_hash_chain(right, hash_field),
            )

    def test_hash_and_schema_fail_closed(self) -> None:
        fields, rows, positive, mutants, _bases = self.fixture.load_inputs()
        bad_hash = [dict(row) for row in rows]
        bad_hash[0]["hotspot_weight_fraction"] = "0.123"
        with self.assertRaisesRegex(calibration.CalibrationError, "metrics_row_sha256"):
            calibration.validate_metrics_rows(
                fields, bad_hash, positive, mutants, calibration.CalibrationContract()
            )
        bad_schema = [dict(row) for row in rows]
        bad_schema[0]["schema_version"] = "wrong"
        bad_schema[0]["metrics_row_sha256"] = calibration.row_sha256(
            bad_schema[0], "metrics_row_sha256"
        )
        with self.assertRaisesRegex(calibration.CalibrationError, "schema"):
            calibration.validate_metrics_rows(
                fields, bad_schema, positive, mutants, calibration.CalibrationContract()
            )

        bad_audit = self.root / "bad_processor_audit.json"
        payload = json.loads(self.fixture.processor_audit.read_text(encoding="utf-8"))
        payload["output_sha256"]["continuous_metrics"]["sha256"] = "0" * 64
        calibration.write_json(bad_audit, payload)
        with self.assertRaisesRegex(calibration.CalibrationError, "Processor audit closure"):
            calibration.validate_processor_audit(
                bad_audit, self.fixture.metrics_csv, rows
            )

        bad_prereg = self.root / "bad_prereg.json"
        shutil.copy2(self.fixture.preregistration, bad_prereg)
        prereg_payload = json.loads(bad_prereg.read_text(encoding="utf-8"))
        prereg_payload["bootstrap"]["replicates"] = 1999
        calibration.write_json(bad_prereg, prereg_payload)
        with self.assertRaisesRegex(calibration.CalibrationError, "SHA256 mismatch"):
            calibration.validate_preregistration(bad_prereg)

    def test_full_synthetic_build_emits_counts_and_unconditional_vetoes(self) -> None:
        outdir = self.root / "build" / "calibration"
        report = self.root / "build" / "report.md"
        audit = calibration.build_calibration(
            calibration.CalibrationConfig(
                metrics_csv=self.fixture.metrics_csv,
                processor_audit=self.fixture.processor_audit,
                preregistration=self.fixture.preregistration,
                positive_manifest=self.fixture.positive_manifest,
                mutant_manifest=self.fixture.mutant_manifest,
                outdir=outdir,
                report=report,
                bootstrap_seed=calibration.BOOTSTRAP_SEED,
                bootstrap_replicates=2,
            )
        )
        self.assertEqual(audit["central_outputs"]["pose_rows"], 752)
        self.assertEqual(audit["central_outputs"]["native_run_rows"], 94)
        self.assertEqual(audit["central_outputs"]["dual_candidate_rows"], 47)
        self.assertEqual(audit["lofo"]["anchor_row_count"], 11)
        self.assertEqual(audit["mutant_sensitivity"]["paired_delta_count"], 29)
        self.assertEqual(audit["robustness_grid"]["rows"], 54)
        bootstrap = audit["bootstrap"]["summary"]
        self.assertEqual(bootstrap["threshold_row_count"], 20)
        self.assertEqual(bootstrap["receptor_anchor_evaluation_row_count"], 44)
        self.assertEqual(bootstrap["dual_anchor_evaluation_row_count"], 22)
        self.assertFalse(audit["formal_eligible"])
        self.assertFalse(audit["docking_gold_release_eligible"])
        self.assertFalse(audit["training_label_release_eligible"])
        self.assertFalse(audit["p2_training_ready"])
        self.assertTrue(audit["development_method_evaluation_eligible"])
        self.assertEqual(audit["training_state"], "P2_TRAINING_BLOCKED")
        self.assertEqual(
            audit["status"],
            "FAIL_V1_3_DUAL_RECEPTOR_DEVELOPMENT_METHOD_NOT_FROZEN",
        )
        self.assertTrue(report.is_file())
        self.assertTrue((outdir / calibration.AUDIT_NAME).is_file())


if __name__ == "__main__":
    unittest.main()
