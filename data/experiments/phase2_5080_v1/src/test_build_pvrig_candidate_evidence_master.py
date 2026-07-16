#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_pvrig_candidate_evidence_master.py")
SPEC = importlib.util.spec_from_file_location("candidate_evidence_master", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class CandidateEvidenceMasterTests(unittest.TestCase):
    def test_parse_design_indices(self) -> None:
        self.assertEqual(
            MOD.parse_design_indices("PVRIG_RFAb_v2_P2_qkg_L_bb007_mpn01"),
            ("PVRIG_RFAb_v2_P2_qkg_L_bb007", "007", "01"),
        )

    def test_default_sources_build_418_unique_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = MOD.parse_args(["--outdir", tmp])
            audit = MOD.run(args)
            self.assertEqual(audit["status"], "PASS_INITIAL_MASTER_V4D_GEOMETRY_PENDING")
            self.assertEqual(audit["row_count"], 418)
            self.assertEqual(audit["cohort_counts"], {"DUAL128_SECONDARY": 128, "FULLQC290_PRIMARY": 290})
            self.assertEqual(audit["dual128"]["support_class_counts"]["ROBUST_A"], 5)
            self.assertEqual(audit["fullqc290"]["v4d_geometry_pending_count"], 290)
            self.assertEqual(audit["fullqc290"]["cdr3_cluster_count"], 282)
            self.assertEqual(audit["fullqc290"]["maximum_cdr3_cluster_size"], 3)


if __name__ == "__main__":
    unittest.main()
