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
from unittest import mock


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
    reference_inventory = MOD.canonical_json(
        {
            "selection_rule": "protein ATOM heavy atoms only; all HETATM excluded",
            "selected_protein_heavy_atom_count": 10,
            "protein_atom_heavy_atom_count": 10,
            "selected_protein_residue_count": 2,
            "protein_atom_residue_count": 2,
        }
    )
    region_inventory = MOD.canonical_json(
        {
            "selection_rule": "protein ATOM records; all HETATM excluded",
            "selected_protein_heavy_atom_count": 10,
            "protein_atom_heavy_atom_count": 10,
            "selected_protein_residue_count": 2,
            "protein_atom_residue_count": 2,
        }
    )
    canonical_payload_hash = MOD.sha256_json(
        {"candidate_id": candidate_id, "rank": rank, "channel": "canonical"}
    )
    row = {
        "schema_version": "test_metrics_v1",
        "protocol_id": MOD.PROTOCOL_ID,
        "formal_eligible": "false",
        "threshold_freeze_eligible": "false",
        "pose_rule_threshold_freeze_eligible": "true",
        "dual_receptor_r_gold_freeze_eligible": "false",
        "source_docking_receptor": "8x6b",
        "baseline_channel_semantics": MOD.UPSTREAM_BASELINE_SEMANTICS,
        "candidate_id": candidate_id,
        "family": family,
        "canonical_rank": str(rank),
        "baseline": baseline,
        "selector_row_sha256": MOD.sha256_json(
            {"candidate_id": candidate_id, "rank": rank, "selector": True}
        ),
        "aligned_pose_sha256": MOD.sha256_json(
            {"candidate_id": candidate_id, "rank": rank, "baseline": baseline}
        ),
        "reference_relpath": f"reference_{baseline}.pdb",
        "reference_sha256": MOD.sha256_json({"reference": baseline}),
        "pvrig_vhh_contact_pair_count": str(total_pairs + 50),
        "pvrig_contact_residue_count": "12",
        "vhh_contact_residue_count": "9",
        "cdr_contact_residue_count": "5",
        "hotspot_count": "23",
        "hotspot_overlap_count": "10",
        "hotspot_overlap_fraction": MOD.scalar_text(h_value),
        "hotspot_weight_total": "11.2",
        "hotspot_weight_overlap": MOD.scalar_text(h_value * 11.2),
        "hotspot_weight_fraction": MOD.scalar_text(h_value),
        "total_occluding_residue_pair_count": str(total_pairs),
        "cdr1_occluding_residue_pair_count": str(cdr1),
        "cdr2_occluding_residue_pair_count": str(cdr2),
        "cdr3_occluding_residue_pair_count": str(cdr3),
        "reference_pvrl2_record_inventory_json": reference_inventory,
        "region_reference_pvrl2_record_inventory_json": region_inventory,
        "canonical_internal_score_payload_sha256": canonical_payload_hash,
        "baseline_pose_score_payload_sha256": MOD.sha256_json(
            {"candidate_id": candidate_id, "rank": rank, "baseline": baseline, "pose": True}
        ),
        "region_score_payload_sha256": MOD.sha256_json(
            {"candidate_id": candidate_id, "rank": rank, "baseline": baseline, "region": True}
        ),
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


def threshold_payload(lower: float, upper: float, metric: str) -> dict[str, object]:
    transform = "log1p" if metric == "O" else "identity"
    return {
        "L": lower,
        "U": upper,
        "L_raw": lower,
        "U_raw": upper,
        "L_transformed": math.log1p(lower) if metric == "O" else lower,
        "U_transformed": math.log1p(upper) if metric == "O" else upper,
        "transform": transform,
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_contacts(path: Path, metric_rows: list[dict[str, str]]) -> None:
    records: list[dict[str, object]] = []
    for row in metric_rows:
        rank = int(row["canonical_rank"])
        candidate = row["candidate_id"]
        baseline = row["baseline"]
        record: dict[str, object] = {
            "protocol_id": MOD.PROTOCOL_ID,
            "candidate_id": candidate,
            "canonical_rank": rank,
            "baseline": baseline,
            "selector_row_sha256": row["selector_row_sha256"],
            "aligned_pose_sha256": row["aligned_pose_sha256"],
            "canonical_internal_score_payload_sha256": row[
                "canonical_internal_score_payload_sha256"
            ],
            "baseline_pose_score_payload_sha256": row[
                "baseline_pose_score_payload_sha256"
            ],
            "pvrig_vhh_contacts": [
                {
                    "vhh_residue": f"A:{rank}ALA",
                    "pvrig_residue": f"B:{rank + 10}SER",
                }
            ],
            "region_residue_pairs": {
                region: {
                    "occluding_residue_pairs": (
                        [f"A:{rank}ALA--{baseline}:{rank + 20}GLY"]
                        if region == "CDR3"
                        else []
                    )
                }
                for region in ("CDR1", "CDR2", "CDR3", "framework")
            },
        }
        record["contact_record_sha256"] = MOD.row_sha256(
            record, "contact_record_sha256"
        )
        records.append(record)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(MOD.canonical_json(record) + "\n")


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
        self.assertAlmostEqual(rules["thresholds"]["H_canonical"]["U"], 0.31)
        weights = MOD.anchor_metric_values(rows, positive_metadata(cases), 1)
        family_a_weight = sum(
            weight for value, weight in weights["H_canonical"] if value > 0.8
        )
        self.assertAlmostEqual(family_a_weight, 0.5)

    def test_positive_part_hurdle_and_zero_membership(self) -> None:
        threshold = MOD.threshold_from_weighted_values(
            [(0.0, 0.7), (0.2, 0.1), (0.4, 0.2)], 0.2, 0.5, metric="H"
        )
        self.assertGreater(threshold["L"], 0.0)
        self.assertAlmostEqual(threshold["zero_weight"], 0.7)
        self.assertEqual(MOD.membership(0.0, threshold), 0.0)
        self.assertEqual(MOD.membership(threshold["L"] / 2.0, threshold), 0.0)
        with self.assertRaises(MOD.CalibrationError):
            MOD.threshold_from_weighted_values(
                [(0.0, 1.0)], 0.2, 0.5, metric="H"
            )

    def test_pose_rule_boundaries(self) -> None:
        metric_rules = {
            metric: threshold_payload(
                1.0 if metric == "O" else 0.2,
                2.0 if metric == "O" else 0.6,
                metric,
            )
            for metric in MOD.METRICS
        }
        rules = {
            "thresholds": {
                "H_canonical": metric_rules["H"],
                "baseline": {
                    baseline: {metric: metric_rules[metric] for metric in MOD.BASELINE_METRICS}
                    for baseline in MOD.BASELINES
                },
            }
        }
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
            "p1": (0.4, 10, 2),
            "p2": (0.6, 20, 10),
            "p3": (0.8, 30, 24),
        }
        rows = rows_for_cases(cases, 2, values)
        metadata = positive_metadata(cases)
        central_rules = MOD.derive_rules(rows, metadata, 2)
        central_runs = MOD.aggregate_run_scores(
            MOD.score_pose_rows(rows, central_rules), metadata
        )
        output = MOD.build_lofo_rows(rows, metadata, central_runs, 2)
        self.assertEqual(len(output), 3)
        self.assertEqual({row["held_out_family"] for row in output}, {"F1", "F2", "F3"})
        self.assertTrue(all(row["training_family_count"] == "2" for row in output))
        summary = MOD.summarize_lofo(output, metadata)
        self.assertEqual(set(summary["families"]), {"F1", "F2", "F3"})
        self.assertEqual(
            summary["fold_definition_gate_passed"],
            all(row["fold_defined"] == "true" for row in output),
        )

    def test_hierarchical_bootstrap_is_deterministic(self) -> None:
        cases = {"p1": "F1", "p2": "F1", "p3": "F2", "p4": "F3"}
        rows = rows_for_cases(cases, 2)
        metadata = positive_metadata(cases)
        first_thresholds, first_anchors = MOD.hierarchical_bootstrap_rows(
            rows, metadata, 2, seed=20260714, replicates=7
        )
        second_thresholds, second_anchors = MOD.hierarchical_bootstrap_rows(
            rows, metadata, 2, seed=20260714, replicates=7
        )
        self.assertEqual(first_thresholds, second_thresholds)
        self.assertEqual(first_anchors, second_anchors)
        self.assertEqual(len(first_thresholds), 7 * (1 + 2 * 2) * 2)
        self.assertEqual(len(first_anchors), 7 * len(cases))
        self.assertEqual(
            MOD.row_hash_chain(first_thresholds, "bootstrap_row_sha256"),
            MOD.row_hash_chain(second_thresholds, "bootstrap_row_sha256"),
        )

    def test_bootstrap_anchor_probabilities_use_all_replicates_as_denominator(self) -> None:
        positive = {"p1": {"family": "F1"}, "p2": {"family": "F2"}}
        rows: list[dict[str, str]] = []
        for replicate in range(1, 11):
            for candidate_id in positive:
                if candidate_id == "p1":
                    defined = replicate <= 7
                    tier = "G1" if defined else ""
                else:
                    defined = True
                    tier = "G2" if replicate <= 6 else "G5"
                rows.append(
                    {
                        "candidate_id": candidate_id,
                        "family": positive[candidate_id]["family"],
                        "evaluation_defined": str(defined).lower(),
                        "run_tier": tier,
                        "R_calibration_run_8x6b_dock": "0.5" if defined else "",
                        "baseline_gap_rank_weighted_mean": "0.1" if defined else "",
                        "qualifying_support_weight": "0.4" if defined else "",
                    }
                )
        summary = MOD.summarize_bootstrap_anchors(rows, positive, 10)
        self.assertAlmostEqual(
            summary["anchors"]["p1"]["modal_tier_probability"], 0.7
        )
        self.assertAlmostEqual(
            summary["anchors"]["p1"]["g1_g3_retention_probability"], 0.7
        )
        self.assertAlmostEqual(
            summary["anchors"]["p2"]["modal_tier_probability"], 0.6
        )
        self.assertFalse(summary["passed"])
        self.assertFalse(summary["family_retention_gate_passed"])

    def test_lofo_summary_enforces_all_documented_gates(self) -> None:
        family_sizes = {"F1": 3, "F2": 2, "F3": 2, "F4": 2, "F5": 2}
        positive: dict[str, dict[str, str]] = {}
        rows: list[dict[str, str]] = []
        for family, size in family_sizes.items():
            for index in range(size):
                candidate = f"{family}_{index}"
                positive[candidate] = {"family": family}
                rows.append(
                    {
                        "held_out_family": family,
                        "fold_defined": "true",
                        "held_out_G1_G3_retained": "true",
                        "absolute_tier_shift": "1",
                    }
                )
        passing = MOD.summarize_lofo(rows, positive)
        self.assertTrue(passing["passed"])
        failing_rows = [dict(row) for row in rows]
        failing_rows[0]["absolute_tier_shift"] = "3"
        failing = MOD.summarize_lofo(failing_rows, positive)
        self.assertFalse(failing["passed"])
        self.assertFalse(failing["maximum_shift_gate_passed"])

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

    def test_baseline_internal_contact_or_h_drift_fails_closed(self) -> None:
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
        rows = rows_for_cases({"p1": "F1", "m_base": "F2"}, 1)
        drifted = next(
            row
            for row in rows
            if row["candidate_id"] == "p1" and row["baseline"] == "9e6y"
        )
        drifted["hotspot_weight_fraction"] = "0.123"
        drifted["metrics_row_sha256"] = MOD.row_sha256(
            drifted, "metrics_row_sha256"
        )
        with self.assertRaisesRegex(MOD.CalibrationError, "Canonical.*drift"):
            MOD.validate_metrics_rows(
                list(rows[0]), rows, positive, mutant, contract
            )

    def test_strict_equal_cutpoints_are_undefined_without_step_membership(self) -> None:
        diagnostic = MOD.threshold_fit_diagnostic(
            [(0.5, 0.5), (0.5, 0.5)], 0.2, 0.5, metric="H"
        )
        self.assertFalse(diagnostic["defined"])
        self.assertEqual(
            diagnostic["failure_reason"],
            "upper_cutpoint_not_strictly_greater_than_lower",
        )
        with self.assertRaisesRegex(MOD.CalibrationError, "strict U > L"):
            MOD.membership(0.5, diagnostic)

        cases = {"p1": "F1", "p2": "F2"}
        rows = []
        for candidate_id, family in cases.items():
            for rank in (1, 2):
                for baseline in MOD.BASELINES:
                    rows.append(
                        metric_row(
                            candidate_id,
                            family,
                            rank,
                            baseline,
                            h_value=0.5,
                            total_pairs=10,
                            cdr_pairs=5,
                        )
                    )
        thresholds, anchors = MOD.hierarchical_bootstrap_rows(
            rows, positive_metadata(cases), 2, seed=20260714, replicates=3
        )
        h_rows = [
            row
            for row in thresholds
            if row["baseline"] == MOD.CANONICAL_H_CHANNEL
        ]
        self.assertTrue(all(row["metric_defined"] == "false" for row in h_rows))
        self.assertTrue(all(row["replicate_defined"] == "false" for row in thresholds))
        self.assertTrue(all(row["evaluation_defined"] == "false" for row in anchors))
        self.assertEqual(len(thresholds), 3 * 10)
        self.assertEqual(len(anchors), 3 * 2)

    def test_o_cutpoint_units_apply_log1p_exactly_once(self) -> None:
        threshold = MOD.threshold_from_weighted_values(
            [(9.0, 0.2), (99.0, 0.3), (999.0, 0.5)],
            0.2,
            0.5,
            metric="O",
        )
        self.assertEqual(threshold["L_raw"], 9.0)
        self.assertEqual(threshold["U_raw"], 99.0)
        self.assertAlmostEqual(threshold["L_transformed"], math.log1p(9.0))
        self.assertAlmostEqual(threshold["U_transformed"], math.log1p(99.0))
        midpoint_raw = math.exp(
            (math.log1p(9.0) + math.log1p(99.0)) / 2.0
        ) - 1.0
        self.assertAlmostEqual(MOD.membership(midpoint_raw, threshold), 0.5)

    def test_atom_only_inventory_gate_rejects_hetatm_selection(self) -> None:
        rows = rows_for_cases({"p1": "F1", "m_base": "F2"}, 1)
        bad = rows[0]
        inventory = json.loads(bad["reference_pvrl2_record_inventory_json"])
        inventory["selection_rule"] = "protein ATOM and HETATM"
        bad["reference_pvrl2_record_inventory_json"] = MOD.canonical_json(inventory)
        bad["metrics_row_sha256"] = MOD.row_sha256(bad, "metrics_row_sha256")
        contract = MOD.CalibrationContract(
            case_count=2,
            positive_case_count=1,
            positive_family_count=1,
            mutant_panel_case_count=1,
            mutant_delta_count=0,
            ranks_per_case=1,
            baseline_count=2,
        )
        with self.assertRaisesRegex(MOD.CalibrationError, "ATOM-only"):
            MOD.validate_metrics_rows(
                list(rows[0]),
                rows,
                {"p1": {"family": "F1"}},
                {"m_base": {"family": "F2"}},
                contract,
            )

    def test_contacts_generate_canonical_fingerprints_and_mutant_jaccard(self) -> None:
        cases = {"m_base": "F1", "m1": "F1"}
        rows = rows_for_cases(cases, 2)
        with tempfile.TemporaryDirectory() as temporary:
            contacts = Path(temporary) / "contacts.jsonl"
            write_contacts(contacts, rows)
            fingerprints, evidence = MOD.load_contact_fingerprints(contacts, rows, 2)
        self.assertTrue(evidence["validated"])
        assert fingerprints is not None
        pose_rows: list[dict[str, str]] = []
        for candidate_id in cases:
            for rank in (1, 2):
                for baseline in MOD.BASELINES:
                    pose_rows.append(
                        {
                            "candidate_id": candidate_id,
                            "family": "F1",
                            "canonical_rank": str(rank),
                            "baseline": baseline,
                            "pose_class": "B",
                            "S_pose_baseline": "0.5",
                        }
                    )
        runs = MOD.aggregate_run_scores(pose_rows, {})
        mutant_metadata = {
            "m_base": {
                "family": "F1",
                "base_molecule": "BASE",
                "control_type": "base_reference",
                "mutation_class": "base",
                "mutations_1based": "none",
            },
            "m1": {
                "family": "F1",
                "base_molecule": "BASE",
                "control_type": "mutant",
                "mutation_class": "test",
                "mutations_1based": "A1G",
            },
        }
        deltas = MOD.build_mutant_delta_rows(
            runs, mutant_metadata, {"BASE": "m_base"}, fingerprints
        )
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0]["fingerprints_available"], "true")
        self.assertEqual(float(deltas[0]["AG_matched_rank_weighted_jaccard"]), 1.0)
        self.assertRegex(deltas[0]["O8_cluster_transition_tau_0_50"], r"\d+->\d+")

    def test_external_release_manifest_validates_all_current_hash_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            positive = root / "positive.csv"
            mutant = root / "mutant.csv"
            positive.write_text("positive\n", encoding="utf-8")
            mutant.write_text("mutant\n", encoding="utf-8")
            files = [root / f"anchor_{index}.txt" for index in range(11)]
            for index, path in enumerate(files):
                path.write_text(str(index), encoding="utf-8")
            processor = root / "processor.py"
            processor_test = root / "test_processor.py"
            processor.write_text("pass\n", encoding="utf-8")
            processor_test.write_text("pass\n", encoding="utf-8")
            anchors = {
                "positive_manifest": {
                    "path": str(positive),
                    "sha256": MOD.sha256_file(positive),
                },
                "mutant_manifest": {
                    "path": str(mutant),
                    "sha256": MOD.sha256_file(mutant),
                },
            }
            anchors.update(
                {
                    f"extra_{index}": {
                        "path": str(path),
                        "sha256": MOD.sha256_file(path),
                    }
                    for index, path in enumerate(files)
                }
            )
            release = root / "release.json"
            release.write_text(
                json.dumps(
                    {
                        "schema_version": "pvrig_v1_2_top8_processor_release_manifest_v1",
                        "protocol_id": MOD.PROTOCOL_ID,
                        "status": "FROZEN_V1_2_TOP8_PROCESSOR_RELEASE",
                        "processor": {
                            "path": str(processor),
                            "sha256": MOD.sha256_file(processor),
                        },
                        "processor_test": {
                            "path": str(processor_test),
                            "sha256": MOD.sha256_file(processor_test),
                        },
                        "canonical_anchors": anchors,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                MOD, "DEFAULT_PROCESSOR_RELEASE_MANIFEST", release
            ):
                evidence = MOD.validate_processor_release_manifest(
                    release, positive, mutant
                )
            self.assertTrue(evidence["validated"])
            files[0].write_text("drift", encoding="utf-8")
            with mock.patch.object(
                MOD, "DEFAULT_PROCESSOR_RELEASE_MANIFEST", release
            ):
                drift = MOD.validate_processor_release_manifest(
                    release, positive, mutant
                )
            self.assertFalse(drift["validated"])

    def test_output_and_external_report_publish_roll_back_together(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            destination = root / "output"
            staging.mkdir()
            destination.mkdir()
            (staging / "new.txt").write_text("new", encoding="utf-8")
            (destination / "old.txt").write_text("old", encoding="utf-8")
            staging_report = root / "report.staging"
            report = root / "report.md"
            staging_report.write_text("new report", encoding="utf-8")
            report.write_text("old report", encoding="utf-8")
            original_replace = MOD.os.replace

            def fail_report(source: object, target: object) -> None:
                if Path(source) == staging_report and Path(target) == report:
                    raise OSError("injected report publish failure")
                original_replace(source, target)

            with mock.patch.object(MOD.os, "replace", side_effect=fail_report):
                with self.assertRaisesRegex(OSError, "injected"):
                    MOD.publish_outputs_transaction(
                        staging, destination, staging_report, report
                    )
            self.assertEqual((destination / "old.txt").read_text(), "old")
            self.assertEqual(report.read_text(), "old report")

    def test_default_contract_cannot_freeze_without_explicit_acceptance(self) -> None:
        cases = {"p1": "F1", "p2": "F2", "p3": "F3"}
        rows = rows_for_cases(
            cases,
            2,
            {
                "p1": (0.4, 10, 2),
                "p2": (0.6, 20, 10),
                "p3": (0.8, 30, 20),
            },
        )
        rules = MOD.derive_rules(rows, positive_metadata(cases), 2)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = MOD.CalibrationConfig(
                metrics_csv=root / "metrics.csv",
                upstream_audit=root / "audit.json",
                contacts_jsonl=root / "contacts.jsonl",
                processor_release_manifest=root / "release.json",
                positive_manifest=root / "positive.csv",
                mutant_manifest=root / "mutant.csv",
                outdir=root / "out",
                report=root / "report.md",
            )
            acceptance = {
                "all_gates_passed": False,
                "failed_gates": ["bootstrap"],
                "gates": {"bootstrap": {"passed": False}},
            }
            document = MOD.rules_document(
                rules,
                config,
                {"upstream_audit": {"validated": True}},
                acceptance,
            )
        self.assertEqual(
            document["status"], "FAIL_V1_2_FAMILY_CALIBRATION_NOT_FROZEN"
        )
        self.assertFalse(document["pose_rule_threshold_freeze_eligible"])
        self.assertFalse(document["single_8x6b_dock_run_method_freeze_eligible"])


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
                contacts_jsonl=None,
                processor_release_manifest=None,
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
            self.assertEqual(
                first["status"], "FAIL_V1_2_FAMILY_CALIBRATION_NOT_FROZEN"
            )
            self.assertFalse(first["formal_eligible"])
            self.assertFalse(first["pose_rule_threshold_freeze_eligible"])
            self.assertFalse(first["dual_receptor_r_gold_freeze_eligible"])
            self.assertFalse(first["training_label_release_eligible"])
            self.assertTrue(first["p2_training_blocked"])
            self.assertFalse(first["acceptance_summary"]["all_gates_passed"])
            self.assertIn(
                "upstream_provenance",
                first["acceptance_summary"]["failed_gates"],
            )
            with (outdir / MOD.MUTANT_DELTAS_NAME).open(
                newline="", encoding="utf-8"
            ) as handle:
                delta_rows = list(csv.DictReader(handle))
            self.assertEqual(len(delta_rows), 2)
            self.assertTrue(
                all(row["binary_negative_label_assigned"] == "false" for row in delta_rows)
            )
            self.assertTrue(all(row["fingerprints_available"] == "false" for row in delta_rows))
            for field in (
                "delta_F1",
                "delta_F2",
                "delta_F3",
                "delta_F4",
                "delta_N1",
                "delta_N2",
                "delta_N3",
                "delta_N4",
                "delta_tier_strength",
                "delta_baseline_gap",
            ):
                self.assertIn(field, delta_rows[0])
            with (outdir / MOD.ROBUSTNESS_NAME).open(
                newline="", encoding="utf-8"
            ) as handle:
                robustness_rows = list(csv.DictReader(handle))
            self.assertEqual(len(robustness_rows), 54)
            self.assertTrue(all(row["best_row_selected"] == "false" for row in robustness_rows))
            self.assertEqual(
                {row["minimum_supporting_poses"] for row in robustness_rows},
                {"2", "3"},
            )
            with (outdir / MOD.BOOTSTRAP_NAME).open(
                newline="", encoding="utf-8"
            ) as handle:
                threshold_rows = list(csv.DictReader(handle))
            with (outdir / MOD.BOOTSTRAP_ANCHOR_NAME).open(
                newline="", encoding="utf-8"
            ) as handle:
                anchor_rows = list(csv.DictReader(handle))
            self.assertEqual(len(threshold_rows), 5 * 10)
            self.assertEqual(len(anchor_rows), 5 * 3)
            rules = json.loads((outdir / MOD.RULES_NAME).read_text(encoding="utf-8"))
            self.assertEqual(rules["rules_core"]["run_score_name"], "R_calibration_run_8x6b_dock")
            self.assertNotIn("R_gold", rules["rules_core"]["run_score_name"])
            report_text = report.read_text(encoding="utf-8")
            self.assertIn("pose_rule_threshold_freeze_eligible=false", report_text)
            self.assertIn("dual_receptor_r_gold_freeze_eligible=false", report_text)


if __name__ == "__main__":
    unittest.main()
