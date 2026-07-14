#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name(
    "calibrate_phase2_v3_p2_v1_2_family_aware.py"
)
SPEC = importlib.util.spec_from_file_location("pvrig_v1_2_family_calibration", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def metric_row(
    candidate_id: str,
    family: str,
    rank: int,
    baseline: str,
    *,
    h_value: float = 0.5,
    total_pairs: int = 10,
    cdr_pairs: int = 5,
) -> dict[str, str]:
    cdr1 = cdr_pairs // 3
    cdr2 = cdr_pairs // 3
    cdr3 = cdr_pairs - cdr1 - cdr2
    row = {
        "schema_version": "test_metrics_v1",
        "protocol_id": MOD.PROTOCOL_ID,
        "formal_eligible": "false",
        "threshold_freeze_eligible": "false",
        "pose_rule_threshold_freeze_eligible": "true",
        "dual_receptor_r_gold_freeze_eligible": "false",
        "source_docking_receptor": "8x6b",
        "baseline_channel_semantics": "posthoc_test",
        "candidate_id": candidate_id,
        "family": family,
        "canonical_rank": str(rank),
        "baseline": baseline,
        "hotspot_weight_fraction": MOD.scalar_text(h_value),
        "total_occluding_residue_pair_count": str(total_pairs),
        "cdr1_occluding_residue_pair_count": str(cdr1),
        "cdr2_occluding_residue_pair_count": str(cdr2),
        "cdr3_occluding_residue_pair_count": str(cdr3),
    }
    row["metrics_row_sha256"] = MOD.row_sha256(row, "metrics_row_sha256")
    return row


def rows_for_cases(
    cases: dict[str, str],
    ranks: int,
    value_by_case: dict[str, tuple[float, int, int]] | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    value_by_case = value_by_case or {}
    for candidate_id, family in cases.items():
        h_value, total_pairs, cdr_pairs = value_by_case.get(
            candidate_id, (0.45 + 0.01 * len(rows), 12 + len(rows), 6)
        )
        for rank in range(1, ranks + 1):
            for baseline in MOD.BASELINES:
                rows.append(
                    metric_row(
                        candidate_id,
                        family,
                        rank,
                        baseline,
                        h_value=min(h_value + rank * 0.01, 0.99),
                        total_pairs=total_pairs + rank,
                        cdr_pairs=min(cdr_pairs, total_pairs + rank),
                    )
                )
    return rows


def positive_metadata(cases: dict[str, str]) -> dict[str, dict[str, str]]:
    return {
        case_id: {"family": family, "role": "positive", "manifest_row_sha256": "a" * 64}
        for case_id, family in cases.items()
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class FamilyCalibrationUnitTests(unittest.TestCase):
    def test_family_then_case_weighting_is_not_case_pooled(self) -> None:
        cases = {"a1": "A", "b1": "B", "b2": "B", "b3": "B"}
        values = {
            "a1": (0.9, 90, 45),
            "b1": (0.1, 10, 5),
            "b2": (0.2, 20, 10),
            "b3": (0.3, 30, 15),
        }
        rows = rows_for_cases(cases, 1, values)
        rules = MOD.derive_rules(rows, positive_metadata(cases), 1)
        # Family B owns half the mass and its three cases split that half.  The
        # step-CDF q50 is therefore B's third value rather than a pooled median.
        self.assertAlmostEqual(rules["thresholds"]["8x6b"]["H"]["U"], 0.31)
        weights = MOD.anchor_metric_values(rows, positive_metadata(cases), 1)
        family_a_weight = sum(
            weight for value, weight in weights["8x6b"]["H"] if value > 0.8
        )
        self.assertAlmostEqual(family_a_weight, 0.5)

    def test_positive_part_hurdle_and_zero_membership(self) -> None:
        threshold = MOD.threshold_from_weighted_values(
            [(0.0, 0.7), (0.2, 0.1), (0.4, 0.2)], 0.2, 0.5
        )
        self.assertGreater(threshold["L"], 0.0)
        self.assertAlmostEqual(threshold["zero_weight"], 0.7)
        self.assertEqual(MOD.membership(0.0, threshold), 0.0)
        self.assertEqual(MOD.membership(threshold["L"] / 2.0, threshold), 0.0)
        with self.assertRaises(MOD.CalibrationError):
            MOD.threshold_from_weighted_values([(0.0, 1.0)], 0.2, 0.5)

    def test_pose_rule_boundaries(self) -> None:
        metric_rules = {
            metric: {"L": 1.0 if metric == "O" else 0.2, "U": 2.0 if metric == "O" else 0.6}
            for metric in MOD.METRICS
        }
        rules = {"thresholds": {baseline: metric_rules for baseline in MOD.BASELINES}}
        cases = [
            ({"H": 0.6, "O": 2.0, "P": 0.2}, "A"),
            ({"H": 0.2, "O": 1.0, "P": 0.0}, "B"),
            ({"H": 0.2, "O": 0.9, "P": 0.0}, "C"),
            ({"H": 0.19, "O": 0.9, "P": 0.9}, "E"),
        ]
        for features, expected in cases:
            with self.subTest(expected=expected):
                observed, score, memberships = MOD.classify_pose(
                    features, rules, "8x6b"
                )
                self.assertEqual(observed, expected)
                self.assertTrue(math.isfinite(score))
                self.assertEqual(set(memberships), set(MOD.METRICS))

    def test_run_support_requires_weight_and_two_poses(self) -> None:
        rows: list[dict[str, str]] = []
        pair_classes = {
            1: ("A", "A"),
            2: ("A", "B"),
            3: ("E", "E"),
            4: ("E", "E"),
        }
        for rank, classes in pair_classes.items():
            for baseline, pose_class in zip(MOD.BASELINES, classes):
                rows.append(
                    {
                        "candidate_id": "case1",
                        "family": "F1",
                        "canonical_rank": str(rank),
                        "baseline": baseline,
                        "pose_class": pose_class,
                        "S_pose_baseline": "0.5",
                    }
                )
        run = MOD.aggregate_run_scores(rows, {"case1": {"family": "F1"}})[0]
        self.assertGreater(float(run["support_weight_at_or_above_4"]), 0.25)
        self.assertEqual(run["support_count_at_or_above_4"], "1")
        self.assertEqual(run["run_tier"], "G2")
        self.assertEqual(run["qualifying_supporting_pose_count"], "2")

    def test_lofo_covers_each_family_and_case(self) -> None:
        cases = {"p1": "F1", "p2": "F2", "p3": "F3"}
        values = {
            "p1": (0.4, 10, 5),
            "p2": (0.6, 20, 10),
            "p3": (0.8, 30, 15),
        }
        rows = rows_for_cases(cases, 2, values)
        output = MOD.build_lofo_rows(rows, positive_metadata(cases), 2)
        self.assertEqual(len(output), 3)
        self.assertEqual({row["held_out_family"] for row in output}, {"F1", "F2", "F3"})
        self.assertTrue(all(row["training_family_count"] == "2" for row in output))
        self.assertTrue(all(len(row["lofo_rules_sha256"]) == 64 for row in output))

    def test_hierarchical_bootstrap_is_deterministic(self) -> None:
        cases = {"p1": "F1", "p2": "F1", "p3": "F2", "p4": "F3"}
        rows = rows_for_cases(cases, 2)
        metadata = positive_metadata(cases)
        first = MOD.hierarchical_bootstrap_rows(
            rows, metadata, 2, seed=20260714, replicates=7
        )
        second = MOD.hierarchical_bootstrap_rows(
            rows, metadata, 2, seed=20260714, replicates=7
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 7 * 2 * 3 * 2)
        self.assertEqual(
            MOD.row_hash_chain(first, "bootstrap_row_sha256"),
            MOD.row_hash_chain(second, "bootstrap_row_sha256"),
        )

    def test_nonfinite_hash_and_duplicate_rows_fail_closed(self) -> None:
        positive = {"p1": {"family": "F1"}}
        mutant = {"m_base": {"family": "F2"}}
        contract = MOD.CalibrationContract(
            case_count=2,
            positive_case_count=1,
            positive_family_count=1,
            mutant_panel_case_count=1,
            mutant_delta_count=0,
            ranks_per_case=1,
            baseline_count=2,
        )
        base_rows = rows_for_cases({"p1": "F1", "m_base": "F2"}, 1)
        fields = list(base_rows[0])
        for scenario in ("nonfinite", "bad_hash", "duplicate"):
            rows = [dict(row) for row in base_rows]
            if scenario == "nonfinite":
                rows[0]["hotspot_weight_fraction"] = "nan"
                rows[0]["metrics_row_sha256"] = MOD.row_sha256(
                    rows[0], "metrics_row_sha256"
                )
            elif scenario == "bad_hash":
                rows[0]["metrics_row_sha256"] = "0" * 64
            else:
                rows[-1] = dict(rows[0])
            with self.subTest(scenario=scenario), self.assertRaises(MOD.CalibrationError):
                MOD.validate_metrics_rows(fields, rows, positive, mutant, contract)


class FamilyCalibrationEndToEndTests(unittest.TestCase):
    def test_small_contract_builds_deterministic_bounded_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            positive_cases = {"p1": "F1", "p2": "F2", "p3": "F3"}
            mutant_cases = {"m_base": "F1", "m1": "F1", "m2": "F1"}
            all_cases = {**positive_cases, **mutant_cases}
            metrics_rows = rows_for_cases(all_cases, 2)
            metrics_csv = root / "metrics.csv"
            write_csv(metrics_csv, metrics_rows)

            positive_manifest = root / "positive.csv"
            positive_rows = [
                {
                    "calibration_name": case_id,
                    "family": family,
                    "validation_role": "known_success",
                }
                for case_id, family in positive_cases.items()
            ]
            write_csv(positive_manifest, positive_rows)
            mutant_manifest = root / "mutants.csv"
            mutant_rows = [
                {
                    "mutant_name": "m_base",
                    "base_molecule": "BASE1",
                    "family": "F1",
                    "control_type": "base_reference",
                    "mutation_class": "unmutated_positive_control",
                    "mutations_1based": "none",
                },
                {
                    "mutant_name": "m1",
                    "base_molecule": "BASE1",
                    "family": "F1",
                    "control_type": "mutant",
                    "mutation_class": "conservative",
                    "mutations_1based": "A1G",
                },
                {
                    "mutant_name": "m2",
                    "base_molecule": "BASE1",
                    "family": "F1",
                    "control_type": "mutant",
                    "mutation_class": "alanine",
                    "mutations_1based": "W2A",
                },
            ]
            write_csv(mutant_manifest, mutant_rows)
            outdir = root / "out"
            report = root / "report.md"
            contract = MOD.CalibrationContract(
                case_count=6,
                positive_case_count=3,
                positive_family_count=3,
                mutant_panel_case_count=3,
                mutant_delta_count=2,
                ranks_per_case=2,
                baseline_count=2,
            )
            config = MOD.CalibrationConfig(
                metrics_csv=metrics_csv,
                upstream_audit=None,
                positive_manifest=positive_manifest,
                mutant_manifest=mutant_manifest,
                outdir=outdir,
                report=report,
                bootstrap_seed=20260714,
                bootstrap_replicates=5,
                contract=contract,
            )
            first = MOD.build_calibration(config)
            first_hashes = {
                path.name: MOD.sha256_file(path)
                for path in [*outdir.iterdir(), report]
            }
            second = MOD.build_calibration(config)
            second_hashes = {
                path.name: MOD.sha256_file(path)
                for path in [*outdir.iterdir(), report]
            }
            self.assertEqual(first_hashes, second_hashes)
            self.assertEqual(first["status"], second["status"])
            self.assertFalse(first["formal_eligible"])
            self.assertFalse(first["dual_receptor_r_gold_freeze_eligible"])
            self.assertFalse(first["training_label_release_eligible"])
            self.assertTrue(first["p2_training_blocked"])
            with (outdir / MOD.MUTANT_DELTAS_NAME).open(
                newline="", encoding="utf-8"
            ) as handle:
                delta_rows = list(csv.DictReader(handle))
            self.assertEqual(len(delta_rows), 2)
            self.assertTrue(
                all(row["binary_negative_label_assigned"] == "false" for row in delta_rows)
            )
            rules = json.loads((outdir / MOD.RULES_NAME).read_text(encoding="utf-8"))
            self.assertEqual(rules["rules_core"]["run_score_name"], "R_calibration_run_8x6b_dock")
            self.assertNotIn("R_gold", rules["rules_core"]["run_score_name"])
            self.assertIn("dual_receptor_r_gold_freeze_eligible=false", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
