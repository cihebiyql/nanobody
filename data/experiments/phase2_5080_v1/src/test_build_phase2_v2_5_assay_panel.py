from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_phase2_v2_5_assay_panel import CLAIM_BOUNDARY, build_panel, parse_args


class Phase2V25AssayPanelTests(unittest.TestCase):
    def test_real_inputs_build_eight_complete_unmeasured_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = parse_args(["--csv-out", str(root / "panel.csv"), "--report-out", str(root / "panel.md")])
            panel = build_panel(args)
            self.assertEqual(len(panel), 24)
            self.assertEqual(panel["prospective_group_id"].nunique(), 8)
            self.assertTrue(panel.groupby("prospective_group_id").size().eq(3).all())
            self.assertEqual(panel["sequence_sha256"].nunique(), 24)
            self.assertEqual(set(panel["claim_boundary"]), {CLAIM_BOUNDARY})
            self.assertFalse(panel["current_truth_status"].str.contains("VERIFIED_NONBINDER", case=False).any())
            self.assertEqual(panel.loc[panel["group_type"] == "paired_mutation_effect", "prospective_group_id"].nunique(), 5)
            self.assertEqual(panel.loc[panel["group_type"] == "binder_nonblocker_enrichment", "prospective_group_id"].nunique(), 2)
            self.assertEqual(panel.loc[panel["group_type"] == "verified_nonbinder_confirmation", "prospective_group_id"].nunique(), 1)
            written = pd.read_csv(root / "panel.csv")
            self.assertEqual(len(written), 24)
            report = (root / "panel.md").read_text(encoding="utf-8")
            self.assertIn("DATA_NOT_READY_FOR_TARGET_MODEL", report)
            self.assertIn("not a negative", report)


if __name__ == "__main__":
    unittest.main()
