#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("freeze_phase2_v4_c_dual128_split.py")
SPEC = importlib.util.spec_from_file_location("freeze_phase2_v4_c_dual128_split", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class FreezeDual128SplitTest(unittest.TestCase):
    @classmethod
    def source(cls) -> Path:
        return MODULE_PATH.parents[1] / "data_splits/pvrig_v4_c/dual128_candidates_source.tsv"

    def test_real_source_freezes_expected_split(self) -> None:
        rows = MOD.freeze_rows(MOD.load_source(self.source()))
        counts = MOD.distribution(rows, "model_split")
        self.assertEqual(counts, MOD.EXPECTED_SPLIT_COUNTS)
        open_families = {
            row["near_cdr3_family_id"]
            for row in rows
            if row["model_split"] == "OPEN_DEVELOPMENT"
        }
        test_families = {
            row["near_cdr3_family_id"]
            for row in rows
            if row["model_split"] == "UNTOUCHED_TEST"
        }
        self.assertFalse(open_families & test_families)
        self.assertEqual(test_families, MOD.FROZEN_HOLDOUT_FAMILIES)

    def test_outputs_are_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first"
            second = Path(temporary) / "second"
            self.assertEqual(MOD.main(["--input", str(self.source()), "--output-dir", str(first)]), 0)
            self.assertEqual(MOD.main(["--input", str(self.source()), "--output-dir", str(second)]), 0)
            self.assertEqual(
                (first / "dual128_split_manifest.tsv").read_bytes(),
                (second / "dual128_split_manifest.tsv").read_bytes(),
            )
            first_audit = json.loads((first / "dual128_split_audit.json").read_text())
            second_audit = json.loads((second / "dual128_split_audit.json").read_text())
            for payload in (first_audit, second_audit):
                payload["manifest"]["path"] = "NORMALIZED"
                payload["source"]["path"] = "NORMALIZED"
            self.assertEqual(first_audit, second_audit)

    def test_tampered_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tampered = Path(temporary) / "source.tsv"
            shutil.copy2(self.source(), tampered)
            with tampered.open("a", encoding="utf-8") as handle:
                handle.write("\n")
            with self.assertRaises(MOD.SplitFreezeError):
                MOD.load_source(tampered)

    def test_manifest_contains_no_new_docking_label(self) -> None:
        rows = MOD.freeze_rows(MOD.load_source(self.source()))
        forbidden = {
            "native_class",
            "cross_class",
            "R_8X6B",
            "R_9E6Y",
            "R_dual_min",
            "hotspot_overlap",
            "total_occlusion",
        }
        self.assertFalse(forbidden & set(rows[0]))


if __name__ == "__main__":
    unittest.main()
