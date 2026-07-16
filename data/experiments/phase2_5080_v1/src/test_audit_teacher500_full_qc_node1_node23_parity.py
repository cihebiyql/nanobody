#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("audit_teacher500_full_qc_node1_node23_parity.py")
SPEC = importlib.util.spec_from_file_location("teacher500_parity", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class Teacher500ParityTests(unittest.TestCase):
    fields = [
        "candidate_id",
        "sequence",
        "official_validator_pass",
        "ANARCI_status",
        "IMGT_CDR1",
        "IMGT_CDR2",
        "IMGT_CDR3",
        "hard_fail",
        "recommendation",
        "developability_score",
        "expression_purity_risk_score",
        "final_score",
        "cascade_full_rank",
        "rank",
        "intra_team_cluster_id",
        "AbNatiV_VHH_score",
    ]

    def write(self, path: Path, row: dict[str, str]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.fields, delimiter="\t")
            writer.writeheader()
            writer.writerow(row)

    def base_row(self) -> dict[str, str]:
        return {
            "candidate_id": "c1",
            "sequence": "QVQLV",
            "official_validator_pass": "PASS",
            "ANARCI_status": "True",
            "IMGT_CDR1": "A",
            "IMGT_CDR2": "B",
            "IMGT_CDR3": "C",
            "hard_fail": "False",
            "recommendation": "REVIEW",
            "developability_score": "50.0",
            "expression_purity_risk_score": "50.0",
            "final_score": "70.0",
            "cascade_full_rank": "1",
            "rank": "1",
            "intra_team_cluster_id": "DEFERRED_1",
            "AbNatiV_VHH_score": "0.7",
        }

    def test_ignores_operational_fields_and_tolerates_small_abnativ_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node1 = self.base_row()
            node23 = {**node1, "rank": "8", "intra_team_cluster_id": "DEFERRED_8", "AbNatiV_VHH_score": "0.7000001"}
            self.write(root / "node1.tsv", node1)
            self.write(root / "node23.tsv", node23)
            result = MOD.compare_tables(root / "node1.tsv", root / "node23.tsv")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["ignored_operational_difference_counts"]["rank"], 1)
            self.assertEqual(result["tolerated_numeric_difference_counts"]["AbNatiV_VHH_score"], 1)

    def test_rejects_decision_difference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node1 = self.base_row()
            node23 = {**node1, "hard_fail": "True"}
            self.write(root / "node1.tsv", node1)
            self.write(root / "node23.tsv", node23)
            result = MOD.compare_tables(root / "node1.tsv", root / "node23.tsv")
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("decision_field_mismatch:hard_fail", result["reasons"])

    def test_rejects_large_abnativ_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node1 = self.base_row()
            node23 = {**node1, "AbNatiV_VHH_score": "0.71"}
            self.write(root / "node1.tsv", node1)
            self.write(root / "node23.tsv", node23)
            result = MOD.compare_tables(root / "node1.tsv", root / "node23.tsv")
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["non_normalized_difference_counts"]["AbNatiV_VHH_score"], 1)


if __name__ == "__main__":
    unittest.main()
