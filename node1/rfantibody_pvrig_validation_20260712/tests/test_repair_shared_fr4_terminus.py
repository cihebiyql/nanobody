from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "repair_shared_fr4_terminus.py"
SPEC = importlib.util.spec_from_file_location("repair_shared_fr4_terminus", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RepairSharedFr4TerminusTest(unittest.TestCase):
    def run_repair(self, text: str):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        source = root / "source.fasta"
        source.write_text(text, encoding="ascii")
        output = root / "restored.fasta"
        mapping = root / "mapping.tsv"
        audit = root / "audit.json"
        result = MODULE.repair(source, output, mapping, audit)
        return temporary, output, mapping, result

    def test_appends_terminal_serine_and_preserves_order(self) -> None:
        temporary, output, mapping, result = self.run_repair(
            ">a\nAAAWGQGTLVTVS\n>b\nCCCWGQGTLVTVS\n"
        )
        with temporary:
            self.assertEqual(
                output.read_text(),
                ">a\nAAAWGQGTLVTVSS\n>b\nCCCWGQGTLVTVSS\n",
            )
            with mapping.open() as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual([row["candidate_id"] for row in rows], ["a", "b"])
            self.assertEqual({row["action"] for row in rows}, {"APPEND_TERMINAL_S"})
            self.assertEqual(result["unique_output_sequences"], 2)

    def test_is_idempotent_for_complete_suffix(self) -> None:
        temporary, output, mapping, _ = self.run_repair(">a\nAAAWGQGTLVTVSS\n")
        with temporary:
            with mapping.open() as handle:
                row = next(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(row["action"], "ALREADY_COMPLETE")
            self.assertEqual(output.read_text(), ">a\nAAAWGQGTLVTVSS\n")

    def test_rejects_unknown_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.fasta"
            source.write_text(">a\nACDEFG\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "FR4 suffix"):
                MODULE.repair(source, root / "out.fasta", root / "map.tsv", root / "audit.json")


if __name__ == "__main__":
    unittest.main()
