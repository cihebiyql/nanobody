#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_candidate_evidence.py")
SPEC = importlib.util.spec_from_file_location("build_candidate_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CandidateEvidenceTest(unittest.TestCase):
    def test_seed_evidence_keeps_technical_na_out_of_biological_counts(self) -> None:
        rows = []
        for seed in (917, 1931):
            for conformation in ("8x6b", "9e6y"):
                rows.append(
                    {
                        "candidate_id": "A",
                        "job_id": f"A_{seed}_{conformation}",
                        "seed": str(seed),
                        "conformation": conformation,
                        "state": "SUCCESS",
                        "representative_pair_label": "STRICT_A",
                    }
                )
        rows.append(
            {
                "candidate_id": "A",
                "job_id": "A_3253_8x6b",
                "seed": "3253",
                "conformation": "8x6b",
                "state": "TECHNICAL_NA",
                "representative_pair_label": "",
            }
        )
        evidence = MODULE.seed_evidence(rows)["A"]
        self.assertEqual(evidence["job_count"], 5)
        self.assertEqual(evidence["successful_job_count"], 4)
        self.assertEqual(evidence["seed_count"], 3)
        self.assertEqual(evidence["complete_seed_count"], 2)
        self.assertEqual(evidence["strict_seed_passes"], 2)
        self.assertEqual(evidence["strict_seed_fraction"], 1.0)

    def test_supported_ab_is_broad_but_not_strict(self) -> None:
        rows = [
            {
                "candidate_id": "B",
                "job_id": f"B_{conf}",
                "seed": "917",
                "conformation": conf,
                "state": "SUCCESS",
                "representative_pair_label": label,
            }
            for conf, label in (("8x6b", "STRICT_A"), ("9e6y", "SUPPORTED_AB"))
        ]
        evidence = MODULE.seed_evidence(rows)["B"]
        self.assertEqual(evidence["complete_seed_count"], 1)
        self.assertEqual(evidence["strict_seed_passes"], 0)
        self.assertEqual(evidence["broad_seed_passes"], 1)

    def test_any_selected_strict_pose_not_only_representative_pose(self) -> None:
        rows = [
            {
                "candidate_id": "C",
                "job_id": f"C_{conf}",
                "seed": "917",
                "conformation": conf,
                "state": "SUCCESS",
                "representative_pair_label": "SUPPORTED_AB",
                "model_strict_a_fraction": "0.5",
            }
            for conf in ("8x6b", "9e6y")
        ]
        evidence = MODULE.seed_evidence(rows)["C"]
        self.assertEqual(evidence["strict_seed_passes"], 1)
        self.assertEqual(evidence["broad_seed_passes"], 1)

    def test_developability_contract(self) -> None:
        row = {
            "tnp_status": "PASS",
            "tnp_review_tier": "CLEAR",
            "tnp_red_flag_count": "0",
            "abnativ_status": "PASS",
            "AbNatiV VHH Score": "0.80",
            "mean_self_probability": "0.75",
            "expression_purity_risk_proxy_partial": "90",
            "cys_count": "2",
            "nglyc_motif_count": "0",
            "hydrophobic_5_count": "0",
            "max_positive_cdr_identity": "0.70",
            "anarci_qc_status": "PASS",
            "nbb2_status": "SUCCESS",
            "nbb2_pdb_sequence_match": "true",
        }
        self.assertTrue(MODULE.developability_conservative_pass(row))
        self.assertTrue(MODULE.developability_calibrated(row)[0])
        row["max_positive_cdr_identity"] = "0.80"
        self.assertFalse(MODULE.developability_conservative_pass(row))
        self.assertFalse(MODULE.developability_calibrated(row)[0])

    def test_positive_calibrated_single_warnings_do_not_hard_fail(self) -> None:
        row = {
            "tnp_status": "WARN",
            "tnp_review_tier": "REVIEW",
            "tnp_red_flag_count": "1",
            "abnativ_status": "PASS",
            "AbNatiV VHH Score": "0.75",
            "mean_self_probability": "0.67",
            "expression_purity_risk_proxy_partial": "80",
            "cys_count": "4",
            "nglyc_motif_count": "0",
            "hydrophobic_5_count": "1",
            "max_positive_cdr_identity": "0.70",
            "anarci_qc_status": "PASS",
            "nbb2_status": "SUCCESS",
            "nbb2_pdb_sequence_match": "true",
        }
        passed, warning_count, reasons = MODULE.developability_calibrated(row)
        self.assertTrue(passed)
        self.assertGreaterEqual(warning_count, 4)
        self.assertIn("four_cysteines_requires_structural_disulfide_review", reasons)

    def test_multiple_orthogonal_severe_liabilities_hard_fail(self) -> None:
        row = {
            "tnp_status": "PASS",
            "tnp_review_tier": "CLEAR",
            "tnp_red_flag_count": "0",
            "AbNatiV VHH Score": "0.50",
            "mean_self_probability": "0.50",
            "expression_purity_risk_proxy_partial": "90",
            "cys_count": "2",
            "nglyc_motif_count": "0",
            "hydrophobic_5_count": "0",
            "max_positive_cdr_identity": "0.70",
            "anarci_qc_status": "PASS",
            "nbb2_status": "SUCCESS",
            "nbb2_pdb_sequence_match": "true",
        }
        self.assertFalse(MODULE.developability_calibrated(row)[0])

    def test_percentile_ties_share_rank(self) -> None:
        result = MODULE.percentile({"A": 1.0, "B": 1.0, "C": 2.0})
        self.assertEqual(result["A"], result["B"])
        self.assertEqual(result["C"], 1.0)


if __name__ == "__main__":
    unittest.main()
