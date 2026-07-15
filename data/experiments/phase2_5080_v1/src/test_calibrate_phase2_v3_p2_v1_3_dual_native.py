from __future__ import annotations

import csv
import contextlib
import io
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
        self.positive_manifest = calibration.DEFAULT_POSITIVE_MANIFEST
        self.mutant_manifest = calibration.DEFAULT_MUTANT_MANIFEST
        self.case_manifest = calibration.DEFAULT_CASE_MANIFEST
        self.run_manifest = calibration.DEFAULT_RUN_MANIFEST
        self.protocol_manifest = calibration.DEFAULT_PROTOCOL_MANIFEST
        self.execution_release = calibration.DEFAULT_EXECUTION_RELEASE
        self.references = calibration.DEFAULT_REFERENCES
        self.selector_csv = root / "selector.csv"
        self.selector_audit = root / "selector_audit.json"
        self.metrics_csv = root / "native_metrics.csv"
        self.processor_audit = root / "processor_audit.json"
        self.processor_qualification = root / "processor_qualification.json"
        self.preregistration = calibration.DEFAULT_PREREGISTRATION
        self.positive_cases = calibration.load_positive_manifest(self.positive_manifest)
        self.mutant_cases, self.base_by_molecule = calibration.load_mutant_manifest(
            self.mutant_manifest
        )
        _case_fields, case_rows = calibration.read_csv_strict(self.case_manifest)
        _run_fields, run_rows = calibration.read_csv_strict(self.run_manifest)
        _protocol_fields, protocol_rows = calibration.read_csv_strict(
            self.protocol_manifest
        )
        self.frozen_cases = {row["case_id"]: row for row in case_rows}
        self.frozen_runs = {
            (row["case_id"], row["receptor_id"]): row for row in run_rows
        }
        self.protocols = {row["receptor_id"]: row for row in protocol_rows}
        self.selector_rows: list[dict[str, str]] = []
        self.metrics_rows: list[dict[str, str]] = []
        self._build_selector()
        self._build_metrics()
        self._build_processor_audit()
        calibration.write_json(
            self.processor_qualification,
            {
                "schema_version": calibration.PROCESSOR_QUALIFICATION_SCHEMA,
                "status": calibration.PROCESSOR_QUALIFICATION_STATUS,
                "protocol_id": calibration.PROTOCOL_ID,
                "calibration_input_eligible": True,
                "formal_eligible": False,
                "docking_gold_release_eligible": False,
                "training_label_release_eligible": False,
                "p2_training_ready": False,
                "native_only": True,
                "qualified_input": {
                    "processor_audit_sha256": calibration.sha256_file(
                        self.processor_audit
                    ),
                    "continuous_metrics_sha256": calibration.sha256_file(
                        self.metrics_csv
                    ),
                    "continuous_metrics_row_hash_chain": calibration.newline_hash_chain(
                        self.metrics_rows, "metrics_row_sha256"
                    ),
                    "selector_csv_sha256": calibration.sha256_file(
                        self.selector_csv
                    ),
                    "selector_audit_sha256": calibration.sha256_file(
                        self.selector_audit
                    ),
                    "selector_publication_release_id": "synthetic-selector-release",
                    "preregistration_sha256": calibration.PREREGISTRATION_SHA256,
                    "execution_release_sha256": calibration.EXECUTION_RELEASE_SHA256,
                    "positive_manifest_sha256": calibration.POSITIVE_MANIFEST_SHA256,
                    "mutant_manifest_sha256": calibration.MUTANT_MANIFEST_SHA256,
                    "case_manifest_sha256": calibration.CASE_MANIFEST_SHA256,
                    "run_manifest_sha256": calibration.RUN_MANIFEST_SHA256,
                    "protocol_manifest_sha256": calibration.PROTOCOL_MANIFEST_SHA256,
                    "reference_sha256": dict(calibration.REFERENCE_SHA256),
                    "processor_sha256": calibration.sha256_file(
                        calibration.DEFAULT_PROCESSOR_IMPLEMENTATION
                    ),
                    "processor_test_sha256": calibration.sha256_file(
                        calibration.DEFAULT_PROCESSOR_TEST
                    ),
                    "validator_sha256": calibration.sha256_file(
                        calibration.DEFAULT_PROCESSOR_QUALIFICATION_VALIDATOR
                    ),
                    "validator_test_sha256": calibration.sha256_file(
                        calibration.DEFAULT_PROCESSOR_QUALIFICATION_TEST
                    ),
                },
                "determinism": {
                    "independent_publication_count": 2,
                    "full_inventory_equal": True,
                    "core_output_hashes_equal": True,
                    "content_addressed_release_id_equal": True,
                    "release_id": "native-synthetic-pending-release",
                    "primary_inventory_sha256": "1" * 64,
                    "rebuild_inventory_sha256": "1" * 64,
                    "primary_processor_audit_sha256": calibration.sha256_file(
                        self.processor_audit
                    ),
                    "rebuild_processor_audit_sha256": "2" * 64,
                },
                "source_pending_releases": {
                    "primary": {
                        "audit_path": "synthetic/primary/audit.json",
                        "audit_sha256": calibration.sha256_file(self.processor_audit),
                        "release_id": "native-synthetic-pending-release",
                    },
                    "rebuild": {
                        "audit_path": "synthetic/rebuild/audit.json",
                        "audit_sha256": "2" * 64,
                        "release_id": "native-synthetic-pending-release",
                    },
                },
                "publication": {
                    "release_id": "synthetic-qualification-release",
                    "release_relpath": "releases/synthetic-qualification-release",
                    "current_pointer_relpath": "current",
                    "immutable_versioned_release": True,
                    "atomic_current_symlink_replacement": True,
                },
            },
        )

    def _write_rows(
        self, path: Path, fields: list[str], rows: list[dict[str, str]]
    ) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def _build_selector(self) -> None:
        fields = sorted(calibration.SELECTOR_REQUIRED_FIELDS - {"selection_row_sha256"})
        fields.append("selection_row_sha256")
        rows: list[dict[str, str]] = []
        for case_id in sorted(self.frozen_cases):
            case = self.frozen_cases[case_id]
            for receptor in calibration.RECEPTORS:
                run = self.frozen_runs[(case_id, receptor)]
                for rank in range(1, 9):
                    row = {
                        "schema_version": "phase2_v3_p2_v1_3_dual47_emref_top8_selection_v3",
                        "protocol_id": "DG_A_PVRIG_V1_3_DUAL47_COMPLETION15",
                        "source_protocol": "HADDOCK3_4_EMREF_IO_SCORE_ORDER_V1",
                        "source_stage": "4_emref",
                        "run_id": run["run_id"],
                        "case_id": case_id,
                        "candidate_id": case_id,
                        "family": case["family"],
                        "sequence_sha256": case["sequence_sha256"],
                        "generation_receptor": receptor,
                        "receptor_id": receptor,
                        "native_rank": str(rank),
                        "canonical_rank": str(rank),
                        "receptor_sha256": self.protocols[receptor]["receptor_sha256"],
                        "run_manifest_sha256": calibration.RUN_MANIFEST_SHA256,
                        "run_manifest_row_sha256": run["run_manifest_row_sha256"],
                        "execution_release_manifest_sha256": calibration.EXECUTION_RELEASE_SHA256,
                        "publication_release_id": "synthetic-selector-release",
                        "formal_eligible": "false",
                        "training_label_release_eligible": "false",
                        "docking_gold_release_eligible": "false",
                        "p2_training_ready": "false",
                    }
                    row["selection_row_sha256"] = calibration.row_sha256(
                        row, "selection_row_sha256"
                    )
                    rows.append(row)
        self._write_rows(self.selector_csv, fields, rows)
        self.selector_rows = rows
        selector_chain = calibration.newline_hash_chain(rows, "selection_row_sha256")
        calibration.write_json(
            self.selector_audit,
            {
                "schema_version": "phase2_v3_p2_v1_3_dual47_emref_top8_recovery_audit_v3",
                "status": "PASS_V1_3_DUAL47_EMREF_TOP8_RECOVERED",
                "protocol_id": "DG_A_PVRIG_V1_3_DUAL47_COMPLETION15",
                "source_protocol": "HADDOCK3_4_EMREF_IO_SCORE_ORDER_V1",
                "k": 8,
                "selection_backfill": False,
                "scoring_performed": False,
                "remote_local_hash_chain_equal": True,
                "formal_eligible": False,
                "training_label_release_eligible": False,
                "docking_gold_release_eligible": False,
                "p2_training_ready": False,
                "counts": {
                    "manifest_runs": 94,
                    "selected_runs": 94,
                    "selected_poses": 752,
                    "cases": 47,
                    "reuse_runs": 64,
                    "new_runs": 30,
                },
                "output_csv": {
                    "sha256": calibration.sha256_file(self.selector_csv),
                    "rows": 752,
                    "selection_row_hash_chain": selector_chain,
                },
                "publication": {
                    "release_id": "synthetic-selector-release",
                    "promotion": "single atomic current symlink replacement",
                    "rollback_safe": True,
                },
                "inputs": {
                    "execution_release_manifest": {
                        "sha256": calibration.EXECUTION_RELEASE_SHA256
                    }
                },
            },
        )

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
            case_id: row["family"] for case_id, row in self.frozen_cases.items()
        }
        selector_by_key = {
            (row["candidate_id"], row["generation_receptor"], int(row["native_rank"])): row
            for row in self.selector_rows
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
                        "primary_native_metric_eligible": "false",
                        "native_only": "true",
                        "candidate_id": case_id,
                        "family": family_by_case[case_id],
                        "run_id": self.frozen_runs[(case_id, receptor)]["run_id"],
                        "generation_receptor": receptor,
                        "native_rank": str(rank),
                        "selector_row_sha256": selector_by_key[
                            (case_id, receptor, rank)
                        ]["selection_row_sha256"],
                        "aligned_pose_sha256": calibration.sha256_json(
                            ["pose", case_id, receptor, rank]
                        ),
                        "reference_relpath": self.references[receptor]
                        .relative_to(calibration.WORKSPACE_ROOT.parent)
                        .as_posix(),
                        "reference_sha256": calibration.REFERENCE_SHA256[receptor],
                        "native_hotspot_ref_column": calibration.NATIVE_HOTSPOT_COLUMN[receptor],
                        "internal_contact_channel": f"raw_4_emref_pose_{receptor.lower()}_native_numbering",
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
            "status": calibration.PROCESSOR_PENDING_STATUS,
            "protocol_id": calibration.PROTOCOL_ID,
            "formal_eligible": False,
            "training_label_release_eligible": False,
            "docking_gold_release_eligible": False,
            "primary_native_metric_eligible": False,
            "native_only": True,
            "thresholds_applied": False,
            "discrete_geometry_outputs_emitted": False,
            "cross_reference_rows_emitted": False,
            "cross_receptor_rank_pairing_performed": False,
            "dual_candidate_score_outputs_emitted": False,
            "p2_training_ready": False,
            "development_release_state": {
                "status": "NOT_EVALUATED_BY_PROCESSOR_BUILDER",
                "independent_qualification_required": True,
                "validated": False,
            },
            "publication_contract": {
                "immutable_versioned_release": True,
                "atomic_current_symlink_replacement": True,
                "rollback_safe": True,
                "release_id": "native-synthetic",
                "release_relpath": "releases/native-synthetic",
                "current_pointer_relpath": "current",
            },
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
            "selector_contract": {
                "selector_csv_sha256": calibration.sha256_file(self.selector_csv),
                "publication_release_id": "synthetic-selector-release",
                "selector_audit_validated": True,
                "selection_row_hash_chain": calibration.newline_hash_chain(
                    self.selector_rows, "selection_row_sha256"
                ),
            },
            "native_processing_contract": {
                "raw_native_H_scored_once_per_pose": True,
                "native_PVRL2_reference_only": True,
                "rank_pairing_across_receptors": False,
                "9E6Y_direct_native_numbering": True,
                "canonical_hotspot_reconciliation_validated": True,
                "reference_PVRL2_protein_ATOM_only": True,
                "all_reference_HETATM_excluded": True,
            },
            "input_sha256": {
                "selector_csv": calibration.sha256_file(self.selector_csv),
                "selector_audit": calibration.sha256_file(self.selector_audit),
                "selector_publication_release_id": "synthetic-selector-release",
                "execution_release_manifest": calibration.EXECUTION_RELEASE_SHA256,
                "run_manifest": calibration.RUN_MANIFEST_SHA256,
                "preregistration": calibration.PREREGISTRATION_SHA256,
                "positive_manifest": calibration.POSITIVE_MANIFEST_SHA256,
                "mutant_manifest": calibration.MUTANT_MANIFEST_SHA256,
                "reference_8x6b": calibration.REFERENCE_SHA256["8X6B"],
                "reference_9e6y": calibration.REFERENCE_SHA256["9E6Y"],
            },
            "expected_contract": {
                "positive_cases": 11,
                "mutant_cases": 36,
                "case_count": 47,
                "run_count": 94,
                "pose_count": 752,
                "poses_per_run": 8,
            },
        }
        payload["output_sha256"]["continuous_metrics"]["row_hash_chain"] = (
            calibration.newline_hash_chain(self.metrics_rows, "metrics_row_sha256")
        )
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
            {
                (
                    row["candidate_id"],
                    row["generation_receptor"],
                    int(row["native_rank"]),
                ): row
                for row in self.fixture.selector_rows
            },
            self.fixture.references,
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
        self.assertNotIn("cross_reference_used", calibration.POSE_SCORE_FIELDS)
        self.assertTrue(all(row["input_native_only"] == "true" for row in pose_rows))
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

    def test_default_publication_wiring_and_stale_root_preflight(self) -> None:
        args = calibration.parse_args([])
        self.assertEqual(args.metrics_csv, calibration.DEFAULT_PROCESSING_DIR / "current" / calibration.DEFAULT_METRICS_CSV.name)
        self.assertEqual(args.processor_audit, calibration.DEFAULT_PROCESSING_DIR / "current" / calibration.DEFAULT_PROCESSOR_AUDIT.name)
        self.assertEqual(
            args.processor_qualification,
            calibration.DEFAULT_PROCESSOR_QUALIFICATION_ROOT
            / "current"
            / calibration.DEFAULT_PROCESSOR_QUALIFICATION.name,
        )
        self.assertEqual(args.selector_csv.parent.name, "current")
        self.assertEqual(args.selector_audit.parent.name, "current")
        wiring = calibration.validate_publication_input_wiring(
            metrics_csv=args.metrics_csv,
            processor_audit=args.processor_audit,
            processor_qualification=args.processor_qualification,
            selector_csv=args.selector_csv,
            selector_audit=args.selector_audit,
        )
        self.assertEqual(set(wiring), {
            "continuous_metrics", "processor_audit", "processor_qualification",
            "selector_csv", "selector_audit",
        })
        stale_metrics = calibration.DEFAULT_PROCESSING_DIR / calibration.DEFAULT_METRICS_CSV.name
        with self.assertRaisesRegex(calibration.CalibrationError, "Stale root-level"):
            calibration.validate_publication_input_wiring(
                metrics_csv=stale_metrics,
                processor_audit=args.processor_audit,
                processor_qualification=args.processor_qualification,
                selector_csv=args.selector_csv,
                selector_audit=args.selector_audit,
            )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = calibration.main(["--metrics-csv", str(stale_metrics)])
        self.assertEqual(exit_code, 2)
        self.assertIn("PREFLIGHT", output.getvalue())

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
                fields,
                bad_hash,
                positive,
                mutants,
                calibration.CalibrationContract(),
                {
                    (row["candidate_id"], row["generation_receptor"], int(row["native_rank"])): row
                    for row in self.fixture.selector_rows
                },
                self.fixture.references,
            )
        bad_schema = [dict(row) for row in rows]
        bad_schema[0]["schema_version"] = "wrong"
        bad_schema[0]["metrics_row_sha256"] = calibration.row_sha256(
            bad_schema[0], "metrics_row_sha256"
        )
        with self.assertRaisesRegex(calibration.CalibrationError, "schema"):
            calibration.validate_metrics_rows(
                fields,
                bad_schema,
                positive,
                mutants,
                calibration.CalibrationContract(),
                {
                    (row["candidate_id"], row["generation_receptor"], int(row["native_rank"])): row
                    for row in self.fixture.selector_rows
                },
                self.fixture.references,
            )

        bad_audit = self.root / "bad_processor_audit.json"
        payload = json.loads(self.fixture.processor_audit.read_text(encoding="utf-8"))
        payload["output_sha256"]["continuous_metrics"]["sha256"] = "0" * 64
        calibration.write_json(bad_audit, payload)
        with self.assertRaisesRegex(calibration.CalibrationError, "Processor audit closure"):
            calibration.validate_processor_audit(
                bad_audit,
                self.fixture.metrics_csv,
                rows,
                self._config(self.root / "unused", 2),
                {
                    "selector_csv": {
                        "sha256": calibration.sha256_file(self.fixture.selector_csv),
                        "row_hash_chain": calibration.newline_hash_chain(
                            self.fixture.selector_rows, "selection_row_sha256"
                        ),
                    },
                    "selector_audit": {
                        "sha256": calibration.sha256_file(self.fixture.selector_audit)
                    },
                    "publication_release_id": "synthetic-selector-release",
                },
                {"sha256": calibration.PREREGISTRATION_SHA256},
            )

        bad_prereg = self.root / "bad_prereg.json"
        shutil.copy2(self.fixture.preregistration, bad_prereg)
        prereg_payload = json.loads(bad_prereg.read_text(encoding="utf-8"))
        prereg_payload["bootstrap"]["replicates"] = 1999
        calibration.write_json(bad_prereg, prereg_payload)
        with self.assertRaisesRegex(calibration.CalibrationError, "SHA256 mismatch"):
            calibration.validate_preregistration(bad_prereg)

    def _config(self, outdir: Path, replicates: int) -> calibration.CalibrationConfig:
        return calibration.CalibrationConfig(
            metrics_csv=self.fixture.metrics_csv,
            processor_audit=self.fixture.processor_audit,
            processor_qualification=self.fixture.processor_qualification,
            selector_csv=self.fixture.selector_csv,
            selector_audit=self.fixture.selector_audit,
            execution_release=self.fixture.execution_release,
            case_manifest=self.fixture.case_manifest,
            run_manifest=self.fixture.run_manifest,
            protocol_manifest=self.fixture.protocol_manifest,
            references=self.fixture.references,
            preregistration=self.fixture.preregistration,
            positive_manifest=self.fixture.positive_manifest,
            mutant_manifest=self.fixture.mutant_manifest,
            outdir=outdir,
            report=outdir / "current" / calibration.REPORT_NAME,
            bootstrap_seed=calibration.BOOTSTRAP_SEED,
            bootstrap_replicates=replicates,
        )

    def test_full_synthetic_build_emits_counts_and_unconditional_vetoes(self) -> None:
        outdir = self.root / "build" / "calibration"
        audit = calibration.build_calibration(
            self._config(outdir, 2)
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
            calibration.CALCULATED_STATUS,
        )
        self.assertFalse(audit["development_smoke_eligible"])
        self.assertTrue((outdir / "current" / calibration.REPORT_NAME).is_file())
        self.assertTrue((outdir / "current" / calibration.AUDIT_NAME).is_file())
        self.assertTrue((outdir / "current" / calibration.RELEASE_INPUT_NAME).is_file())
        rules = json.loads(
            (outdir / "current" / calibration.RULES_NAME).read_text(encoding="utf-8")
        )
        release_input = json.loads(
            (outdir / "current" / calibration.RELEASE_INPUT_NAME).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(rules["status"], calibration.CALCULATED_STATUS)
        self.assertEqual(release_input["status"], calibration.RELEASE_INPUT_STATUS)
        self.assertFalse(release_input["development_smoke_eligible"])
        self.assertTrue(release_input["external_validator_required"])
        self.assertNotIn(
            "PASS_V1_3_DUAL_RECEPTOR_DEVELOPMENT_METHOD",
            json.dumps(audit, sort_keys=True),
        )

    def test_selector_p2_training_boundary_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selector_csv = root / "selector.csv"
            selector_audit = root / "selector_audit.json"
            shutil.copyfile(self.fixture.selector_csv, selector_csv)
            shutil.copyfile(self.fixture.selector_audit, selector_audit)

            fields, rows = calibration.read_csv_strict(selector_csv)
            rows[0]["p2_training_ready"] = "true"
            rows[0]["selection_row_sha256"] = calibration.row_sha256(
                rows[0], "selection_row_sha256"
            )
            self.fixture._write_rows(selector_csv, fields, rows)

            audit = json.loads(selector_audit.read_text(encoding="utf-8"))
            audit["output_csv"]["sha256"] = calibration.sha256_file(selector_csv)
            audit["output_csv"]["selection_row_hash_chain"] = (
                calibration.newline_hash_chain(rows, "selection_row_sha256")
            )
            calibration.write_json(selector_audit, audit)

            with self.assertRaisesRegex(
                calibration.CalibrationError, "Selector native identity mismatch"
            ):
                calibration.validate_selector_publication(
                    selector_csv,
                    selector_audit,
                    self.fixture.frozen_cases,
                    self.fixture.frozen_runs,
                    self.fixture.protocols,
                )

    def test_full_B2000_two_builds_are_byte_deterministic(self) -> None:
        outdir_a = self.root / "determinism" / "build_a"
        outdir_b = self.root / "determinism" / "build_b"
        first = calibration.build_calibration(
            self._config(outdir_a, calibration.BOOTSTRAP_REPLICATES)
        )
        first_release = (outdir_a / "current").resolve()
        first_files = {
            path.relative_to(first_release).as_posix(): path.read_bytes()
            for path in first_release.rglob("*")
            if path.is_file()
        }
        second = calibration.build_calibration(
            self._config(outdir_b, calibration.BOOTSTRAP_REPLICATES)
        )
        second_release = (outdir_b / "current").resolve()
        second_files = {
            path.relative_to(second_release).as_posix(): path.read_bytes()
            for path in second_release.rglob("*")
            if path.is_file()
        }
        self.assertEqual(first, second)
        self.assertNotEqual(first_release, second_release)
        self.assertEqual(first_release.name, second_release.name)
        self.assertEqual(first_files, second_files)
        self.assertEqual(first["status"], calibration.CALCULATED_STATUS)
        self.assertFalse(first["development_smoke_eligible"])
        self.assertEqual(first["bootstrap"]["summary"]["threshold_row_count"], 20000)
        self.assertEqual(
            first["bootstrap"]["summary"]["receptor_anchor_evaluation_row_count"],
            44000,
        )
        self.assertEqual(
            first["bootstrap"]["summary"]["dual_anchor_evaluation_row_count"],
            22000,
        )

    def test_versioned_publication_failure_rolls_back_current(self) -> None:
        outdir = self.root / "rollback" / "calibration"
        calibration.build_calibration(self._config(outdir, 2))
        previous = (outdir / "current").resolve()
        previous_inventory = calibration.directory_inventory(previous)

        def fail_promotion(_release: Path, _current: Path) -> None:
            raise RuntimeError("injected pointer failure")

        with self.assertRaisesRegex(RuntimeError, "injected pointer failure"):
            calibration.build_calibration(
                self._config(outdir, 3), pointer_promoter=fail_promotion
            )
        self.assertTrue((outdir / "current").is_symlink())
        self.assertEqual((outdir / "current").resolve(), previous)
        self.assertEqual(calibration.directory_inventory(previous), previous_inventory)
        self.assertEqual(
            sorted(path.name for path in (outdir / "releases").iterdir()),
            [previous.name],
        )


if __name__ == "__main__":
    unittest.main()
