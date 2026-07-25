#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("select_top200.py")


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


class SelectTop200Test(unittest.TestCase):
    def test_selects_exactly_200_with_all_channels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = []
            qc = []
            for index in range(250):
                candidate_id = f"C{index:04d}"
                tier = (
                    "CORE_A"
                    if index < 150
                    else "DISAGREEMENT_C"
                    if index < 210
                    else "RESERVE_D"
                )
                evidence.append(
                    {
                        "candidate_id": candidate_id,
                        "sequence": "A" * (100 + index),
                        "route": "old_top7500" if index % 2 else "c2_four_seed",
                        "parent_cluster": f"P{index % 5}",
                        "cdr3": "G" * (5 + index),
                        "candidate_tier": tier,
                        "g3_docking_hardpass": "true",
                        "developability_hardpass": "true",
                        "rescreen_competition_proxy": f"{1 - index / 1000:.6f}",
                    }
                )
                qc.append(
                    {
                        "candidate_id": candidate_id,
                        "official_validator_pass": "PASS",
                        "pass_similarity_filter": "PASS",
                        "hard_fail": "False",
                        "production_final_score": f"{100 - index / 10:.6f}",
                    }
                )
            evidence_path = root / "evidence.tsv"
            qc_path = root / "qc.tsv"
            out = root / "out"
            write_tsv(evidence_path, evidence)
            write_tsv(qc_path, qc)
            process = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--evidence",
                    str(evidence_path),
                    "--full-qc",
                    str(qc_path),
                    "--out",
                    str(out),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            with (out / "top200_pre_static.tsv").open(newline="") as handle:
                selected = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(selected), 200)
            receipt = json.loads((out / "TOP200_RECEIPT.json").read_text())
            self.assertEqual(receipt["count"], 200)
            self.assertEqual(receipt["status"], "PASS_TOP200_FROZEN")
            self.assertIn("CORE_EXPLOITATION", receipt["channel_counts"])
            self.assertLessEqual(max(receipt["parent_counts"].values()), 60)
            self.assertLessEqual(max(receipt["route_counts"].values()), 140)
            self.assertEqual(receipt["exact_cdr3_duplicate_count"], 0)
            self.assertLess(receipt["max_direct_pairwise_cdr3_identity"], 0.80)
            self.assertTrue(
                receipt["single_linkage_cdr3_clusters_reporting_only"]
            )


if __name__ == "__main__":
    unittest.main()
