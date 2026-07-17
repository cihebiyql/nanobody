#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).with_name("run_phase2_v4_h_research_adaptive_docking_node23_v1.py")
SPEC = importlib.util.spec_from_file_location("adaptive_docking", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AdaptiveDockingTests(unittest.TestCase):
    def test_diversity_selection_preserves_parent_coverage(self) -> None:
        rows = []
        for index in range(30):
            rows.append(
                {
                    "candidate_id": f"C{index:02d}",
                    "parent_framework_cluster": f"P{index % 3}",
                    "target_patch_id": f"PATCH{index % 3}",
                    "design_mode": "H3" if index % 2 else "H1H3",
                    "R_dual_min": f"{1 - index / 100:.3f}",
                }
            )
        selected = MODULE.diversity_select(rows, 12)
        self.assertEqual(len(selected), 12)
        self.assertEqual(set(Counter(row["parent_framework_cluster"] for row in selected)), {"P0", "P1", "P2"})
        self.assertEqual(len({row["candidate_id"] for row in selected}), 12)

    def test_diversity_selection_rejects_insufficient_analyzable(self) -> None:
        rows = [
            {
                "candidate_id": "A",
                "parent_framework_cluster": "P0",
                "target_patch_id": "PATCH0",
                "design_mode": "H3",
                "R_dual_min": "",
            }
        ]
        with self.assertRaisesRegex(RuntimeError, "insufficient_analyzable"):
            MODULE.diversity_select(rows, 1)


if __name__ == "__main__":
    unittest.main()
