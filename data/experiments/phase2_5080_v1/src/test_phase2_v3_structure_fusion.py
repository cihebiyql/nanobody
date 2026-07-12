#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fuse_pvrig_v3_structure_evidence import fuse  # noqa: E402


class Phase2V3StructureFusionTests(unittest.TestCase):
    def test_geometry_tier_precedes_binding_score_and_missing_stays_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pd.DataFrame(
                [
                    {"candidate_id": "a", "sequence_sha256": "sa", "screening_lane": "PROSPECTIVE_SCREENING", "deployment_score": 0.1},
                    {"candidate_id": "b", "sequence_sha256": "sb", "screening_lane": "PROSPECTIVE_SCREENING", "deployment_score": 0.9},
                ]
            ).to_csv(root / "scores.csv", index=False)
            pd.DataFrame(
                [
                    {"assay_sample_id": "blind_a", "candidate_id": "a", "sequence_sha256": "sa"},
                    {"assay_sample_id": "blind_b", "candidate_id": "b", "sequence_sha256": "sb"},
                ]
            ).to_csv(root / "key.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "candidate_id": "blind_a",
                        "final_blocker_label": "FINAL_POSITIVE_HIGH",
                        "docking_evidence_status": "IMPORTED",
                        "hotspot_overlap_count": 14,
                        "total_vhh_pvrl2_residue_pair_occlusion": 700,
                        "cdr3_pvrl2_residue_pair_occlusion": 100,
                        "cdr3_occlusion_fraction": 0.2,
                        "final_rank": 1,
                    }
                ]
            ).to_csv(root / "geometry.tsv", sep="\t", index=False)
            summary = fuse(root / "scores.csv", root / "key.csv", root / "geometry.tsv", root / "out.csv")
            result = pd.read_csv(root / "out.csv")
            self.assertEqual(result.iloc[0]["candidate_id"], "a")
            self.assertEqual(result.iloc[1]["structure_evidence_status"], "NOT_AVAILABLE")
            self.assertEqual(summary["with_geometry_count"], 1)


if __name__ == "__main__":
    unittest.main()
