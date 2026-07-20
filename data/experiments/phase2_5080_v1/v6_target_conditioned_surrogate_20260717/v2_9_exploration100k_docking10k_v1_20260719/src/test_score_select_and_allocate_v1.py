from __future__ import annotations

import importlib.util
import unittest
from collections import Counter
from pathlib import Path

import pandas as pd


PATH = Path(__file__).with_name("score_select_and_allocate_v1.py")
SPEC = importlib.util.spec_from_file_location("selector", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class DynamicParentContractTests(unittest.TestCase):
    @staticmethod
    def panel() -> pd.DataFrame:
        rows = []
        index = 0
        for parent_index in range(65):
            count = 154 if parent_index < 55 else 153
            for local_index in range(count):
                index += 1
                rows.append({
                    "candidate_id": f"C{index:05d}", "parent_framework_cluster": f"P{parent_index:02d}",
                    "proxy_score_decile": local_index % 10 + 1,
                    "acquisition_lane": ["EXPLOITATION_HIGH", "BOUNDARY_MIDDLE", "QC_PASS_LOW_RANDOM_CONTROL", "MODEL_DISAGREEMENT_UNCERTAINTY", "NEW_PARENT_PATCH_METHOD_EXPLORATION"][local_index % 5],
                    "design_method": f"M{local_index % 5}", "target_patch": f"P{local_index % 3}",
                    "design_mode": f"D{local_index % 3}", "proxy_model_disagreement": float(local_index % 17),
                    "proxy_Rdual_exact_min": float(local_index % 101) / 100,
                })
        return pd.DataFrame(rows)

    def test_65_parent_split_and_repeat_allocations_close(self) -> None:
        contract = {
            "random_seed": 20260719,
            "panel": {"parent_count": 65},
            "split": {"seed": "test", "development_fraction": 0.15, "test_fraction": 0.15},
            "docking_allocation": {"seed2_candidate_count": 2000, "seed3_candidate_count": 500},
        }
        panel, split = MODULE.assign_parent_splits(self.panel(), contract)
        self.assertEqual(Counter(split.model_split), Counter({"train": 45, "development": 10, "frozen_test": 10}))
        seed2, seed3 = MODULE.stratified_repeat_selection(panel, contract)
        self.assertEqual(len(seed2), 2000)
        self.assertEqual(len(seed3), 500)
        self.assertLessEqual(seed3, seed2)


if __name__ == "__main__":
    unittest.main()
