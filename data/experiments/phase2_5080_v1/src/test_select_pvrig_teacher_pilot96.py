#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from collections import Counter
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("select_pvrig_teacher_pilot96.py")
SPEC = importlib.util.spec_from_file_location("select_pvrig_teacher_pilot96", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class SelectPilot96Test(unittest.TestCase):
    def test_random_key_is_deterministic(self) -> None:
        self.assertEqual(MOD.random_key("candidate"), MOD.random_key("candidate"))
        self.assertNotEqual(MOD.random_key("candidate"), MOD.random_key("other"))

    def test_selection_balances_hotspots_and_backbones(self) -> None:
        candidates = []
        fast = []
        for hotspot in "ABCD":
            for index in range(250):
                cid = f"PVRIG_RFAb_v1_{hotspot}_bb{index // 5:03d}_mpn{index % 5:02d}"
                candidates.append(
                    {
                        "candidate_id": cid,
                        "source_candidate_id": cid.replace("_v1_", "_v0_"),
                        "sequence": f"SEQ{hotspot}{index}",
                        "sequence_sha256": str(index),
                        "hotspot_set": hotspot,
                        "hotspots_uniprot": "R95,F139,W144",
                        "framework_id": "h-NbBCII10",
                        "parent_framework_cluster": "h-NbBCII10",
                        "backbone_index": str(index // 5),
                        "mpnn_index": str(index % 5),
                        "cdr1": "AAAAA",
                        "cdr2": "BBBBB",
                        "cdr3": "C" * (5 + index % 9),
                        "rfd_mindist": str(index / 20),
                        "rfd_hotspot_distance_bin": "le_8A" if index < 160 else "gt_10A",
                        "source_mpnn_pdb": f"/{cid}.pdb",
                    }
                )
                fast.append(
                    {
                        "candidate_id": cid,
                        "hard_fail": "False",
                        "final_score": str(100 - index / 10),
                        "cascade_fast_rank": str(index + 1),
                        "recommendation": "REVIEW_DEVELOPABILITY",
                        "reason_summary": "not_vhh_like",
                    }
                )
        selected = MOD.select_rows(candidates, fast)
        self.assertEqual(len(selected), 96)
        self.assertEqual(Counter(row["hotspot_set"] for row in selected), Counter({key: 24 for key in "ABCD"}))
        per_backbone = Counter((row["hotspot_set"], row["backbone_index"]) for row in selected)
        self.assertLessEqual(max(per_backbone.values()), 2)


if __name__ == "__main__":
    unittest.main()
