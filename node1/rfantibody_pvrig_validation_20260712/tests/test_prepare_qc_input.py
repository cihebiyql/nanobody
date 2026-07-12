from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "prepare_qc_input.py"
SPEC = importlib.util.spec_from_file_location("prepare_qc_input", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PrepareQcInputTest(unittest.TestCase):
    def write_tsv(self, path: Path, rows: list[dict[str, str]]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)

    def rows(self) -> list[dict[str, str]]:
        base = {
            "backbone_index": "0",
            "mpnn_index": "0",
            "cdr1": "AAAAAAA",
            "cdr2": "CCCCCC",
            "cdr3": "DDDDD",
            "valid_sequence": "True",
            "exact_known_positive_match": "False",
        }
        return [
            {**base, "candidate_id": "cand_A", "hotspot_set": "A", "sequence": "ACDEFGHIK"},
            {**base, "candidate_id": "cand_B", "hotspot_set": "B", "sequence": "LMNPQRSTV"},
        ]

    def test_emits_candidate_id_only_headers_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tsv"
            fasta = root / "input.fasta"
            audit_path = root / "audit.json"
            self.write_tsv(source, self.rows())

            audit = MODULE.prepare(
                source,
                fasta,
                audit_path,
                expected_count=2,
                expected_set_counts={"A": 1, "B": 1},
            )

            self.assertEqual(fasta.read_text(), ">cand_A\nACDEFGHIK\n>cand_B\nLMNPQRSTV\n")
            self.assertTrue(audit["all_checks_passed"])
            self.assertEqual(json.loads(audit_path.read_text())["unique_exact_sequences"], 2)

    def test_rejects_exact_duplicate_sequence(self) -> None:
        rows = self.rows()
        rows[1]["sequence"] = rows[0]["sequence"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tsv"
            self.write_tsv(source, rows)
            with self.assertRaisesRegex(ValueError, "duplicate exact sequence"):
                MODULE.prepare(
                    source,
                    root / "input.fasta",
                    root / "audit.json",
                    expected_count=2,
                    expected_set_counts={"A": 1, "B": 1},
                )

    def test_rejects_unstable_identifier(self) -> None:
        rows = self.rows()
        rows[0]["candidate_id"] = "cand|A"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tsv"
            self.write_tsv(source, rows)
            with self.assertRaisesRegex(ValueError, "unstable candidate_id"):
                MODULE.prepare(
                    source,
                    root / "input.fasta",
                    root / "audit.json",
                    expected_count=2,
                    expected_set_counts={"A": 1, "B": 1},
                )


if __name__ == "__main__":
    unittest.main()

