#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_pvrig_teacher_pilot96_package.py")
SPEC = importlib.util.spec_from_file_location("build_pvrig_teacher_pilot96_package", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class Pilot96PackageTest(unittest.TestCase):
    def test_cdr_range(self) -> None:
        self.assertEqual(MOD.cdr_range("AAACCCGGG", "CCC"), (4, 6))
        with self.assertRaises(ValueError):
            MOD.cdr_range("AAACCCAAA", "AAA")

    def test_runner_patch_adds_wait_and_resume(self) -> None:
        source = (MOD.DEFAULT_TEMPLATE / "scripts/run_node1_v2_5_pose_batch.sh").read_text(encoding="utf-8")
        patched = MOD.patch_runner(source)
        self.assertIn('--expected-residue-count "${#seq}"', patched)
        self.assertNotIn("--expected-residue-count 130", patched)
        self.assertIn("LOAD_GATE_WAIT", patched)
        self.assertIn("HADDOCK_SKIP_COMPLETE", patched)

    def test_current_selection_has_96_rows(self) -> None:
        rows = MOD.read_tsv(MOD.DEFAULT_SELECTION)
        self.assertEqual(len(rows), 96)
        self.assertEqual(len({row["candidate_id"] for row in rows}), 96)


if __name__ == "__main__":
    unittest.main()
