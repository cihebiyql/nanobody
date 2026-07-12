from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "recover_mpnn_scores.py"
SPEC = importlib.util.spec_from_file_location("recover_mpnn_scores", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RecoverMpnnScoresTest(unittest.TestCase):
    def test_recovers_scores_and_lower_score_rank(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "set_A.log"
            log.write_text(
                "Attempting pose: /tmp/design_7.pdb\n"
                "sequence_optimize: [('ACDE', 1.2), ('FGHI', 0.8)]\n",
                encoding="utf-8",
            )
            final_tsv = root / "final.tsv"
            fields = [
                "candidate_id",
                "hotspot_set",
                "backbone_index",
                "mpnn_index",
                "sequence",
                "cdr1",
                "cdr2",
                "cdr3",
                "rfd_mindist",
                "rfd_averagemin",
                "mpnn_pdb",
            ]
            with final_tsv.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
                writer.writeheader()
                writer.writerow(
                    {
                        "candidate_id": "cand_1",
                        "hotspot_set": "A",
                        "backbone_index": "7",
                        "mpnn_index": "1",
                        "sequence": "FGHI",
                    }
                )

            summary = MODULE.recover(
                final_tsv,
                {"A": log},
                root / "out",
                expected_per_set=2,
                expected_final=1,
            )

            self.assertEqual(summary["raw_score_records"], 2)
            with (root / "out" / "mpnn_scores_selected.tsv").open() as handle:
                row = next(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(row["mpnn_rank_within_backbone"], "1")
            self.assertEqual(row["mpnn_nll_score"], "0.8")

    def test_rejects_sequence_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "set_A.log"
            log.write_text(
                "Attempting pose: /tmp/design_0.pdb\nsequence_optimize: [('ACDE', 1.0)]\n",
                encoding="utf-8",
            )
            final_tsv = root / "final.tsv"
            with final_tsv.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["candidate_id", "hotspot_set", "backbone_index", "mpnn_index", "sequence"],
                    delimiter="\t",
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "candidate_id": "cand",
                        "hotspot_set": "A",
                        "backbone_index": "0",
                        "mpnn_index": "0",
                        "sequence": "FGHI",
                    }
                )
            with self.assertRaisesRegex(ValueError, "sequence mismatch"):
                MODULE.recover(
                    final_tsv,
                    {"A": log},
                    root / "out",
                    expected_per_set=1,
                    expected_final=1,
                )


if __name__ == "__main__":
    unittest.main()

