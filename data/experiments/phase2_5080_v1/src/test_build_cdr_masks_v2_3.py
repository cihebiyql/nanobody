#!/usr/bin/env python3
"""Regression tests for Phase 2.3 VHH CDR type masks."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_cdr_masks_v2_3 import build_manifest, build_row, exact_annotation_result, heuristic_result, sequence_hash


class CdrMaskBuildTests(unittest.TestCase):
    def test_exact_annotation_uses_validated_substrings(self) -> None:
        seq = "AAAACDR1BBBBCDR2CCCCCDR3DDDD"
        row = {"vhh_seq": seq, "cdr1_seq": "CDR1", "cdr2_seq": "CDR2", "cdr3_seq": "CDR3"}
        result = exact_annotation_result(seq, row, "unit")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "exact_annotation")
        self.assertEqual(result.spans["cdr1"], [4, 8])
        self.assertEqual(result.mask[4:8], [1, 1, 1, 1])
        self.assertEqual(result.mask[12:16], [2, 2, 2, 2])
        self.assertEqual(result.mask[21:24], [3, 3, 3])

    def test_repeated_substring_ambiguity_rejects_exact_annotation_without_span(self) -> None:
        seq = "AAAACDR1BBBBCDR1CCCCCDR3DDDD"
        row = {"vhh_seq": seq, "cdr1_seq": "CDR1", "cdr2_seq": "BBBB", "cdr3_seq": "CDR3"}
        self.assertIsNone(exact_annotation_result(seq, row, "unit"))

    def test_fallback_heuristic_marks_source_and_reason(self) -> None:
        seq = "QVQLVESGGGSVQAGGSLRLSCAASGYTINTDAVAWFRQAPGKGDERVAVIYTGSGNTNYADSVKGRFTISQDNAKNTVYLQMNSLKPEDTALYYCASGYYGASGYDFNNWGQGTQVTVSS"
        result = heuristic_result(seq, "no_valid_exact_local_annotation")
        self.assertEqual(result.status, "heuristic_fallback")
        self.assertEqual(result.source, "motif_heuristic_v2_3")
        self.assertEqual(result.fallback_reason, "no_valid_exact_local_annotation")
        self.assertEqual(result.cdrs["cdr1"], "GYTINTDAVA")
        self.assertEqual(result.cdrs["cdr3"], "ASGYYGASGYDFNN")

    def test_length_invariants_hold_in_full_manifest_row(self) -> None:
        seq = "AAAACDR1BBBBCDR2CCCCCDR3DDDD"
        exact = {seq: exact_annotation_result(seq, {"cdr1_seq": "CDR1", "cdr2_seq": "CDR2", "cdr3_seq": "CDR3"}, "unit")}
        row = build_row(seq, {"site", "pair"}, exact)  # type: ignore[arg-type]
        mask = json.loads(row["cdr_mask_json"])
        spans = json.loads(row["spans_json"])
        self.assertEqual(len(mask), int(row["vhh_len"]))
        self.assertEqual(len(mask), len(seq))
        self.assertEqual(set(mask), {0, 1, 2, 3})
        self.assertEqual(spans["cdr2"], [12, 16])
        self.assertEqual(row["sequence_hash"], sequence_hash(seq))

    def test_build_manifest_writes_one_row_per_unique_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = root / "site.csv"
            pair = root / "pair.csv"
            contact = root / "contact.jsonl"
            index = root / "index.csv"
            candidates = root / "candidates.csv"
            out = root / "out.csv"
            seq = "AAAACDR1BBBBCDR2CCCCCDR3DDDD"
            site.write_text("vhh_seq\n" + seq + "\n", encoding="utf-8")
            pair.write_text("vhh_seq\n" + seq + "\n", encoding="utf-8")
            contact.write_text('{"vhh_seq":"' + seq + '"}\n', encoding="utf-8")
            index.write_text("vhh_seq,cdr1_seq,cdr2_seq,cdr3_seq\n" + seq + ",CDR1,CDR2,CDR3\n", encoding="utf-8")
            candidates.write_text("vhh_seq,cdr1,cdr2,cdr3\n", encoding="utf-8")
            counts = build_manifest(site, pair, contact, index, candidates, out)
            self.assertEqual(counts["rows"], 1)
            self.assertEqual(counts["exact_annotation"], 1)
            text = out.read_text(encoding="utf-8")
            self.assertIn('"[""contact"",""pair"",""site""]"', text)


if __name__ == "__main__":
    unittest.main()
