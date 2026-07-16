#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_pvrig_pre_shortlist100.py")
SPEC = importlib.util.spec_from_file_location("pre_shortlist100", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class PreShortlist100Tests(unittest.TestCase):
    def test_default_master_builds_frozen_quota_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = MOD.parse_args(["--outdir", tmp])
            audit = MOD.run(args)
            self.assertEqual(audit["status"], "PASS_PRE_SHORTLIST_GEOMETRY_PENDING_NOT_FINAL")
            self.assertEqual(audit["selected_count"], 100)
            self.assertEqual(audit["lane_counts"], {"EXPLOIT": 82, "EXPLORE": 18})
            self.assertLessEqual(audit["maximum_parent_count"], 4)
            self.assertLessEqual(audit["maximum_parent_patch_mode_count"], 2)
            self.assertLessEqual(audit["maximum_cdr3_cluster_count"], 2)
            self.assertTrue(all(25 <= value <= 40 for value in audit["patch_counts"].values()))
            self.assertEqual(set(audit["mode_counts"]), {"H1H3", "H3"})


if __name__ == "__main__":
    unittest.main()
