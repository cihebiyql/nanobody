#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd

MODULE_PATH = Path(__file__).with_name("prepare_phase2_v3_g1_data.py")
SPEC = importlib.util.spec_from_file_location("prepare_phase2_v3_g1_data", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class PrepareV3G1DataTest(unittest.TestCase):
    def test_balanced_deterministic_selection(self) -> None:
        rows = []
        for split in ("train", "dev"):
            for target in ("t1", "t2"):
                for label in (0, 1):
                    for index in range(10):
                        rows.append(
                            {
                                "sample_id": f"{split}-{target}-{label}-{index}",
                                "dataset_id": "d",
                                "split": split,
                                "target_id": target,
                                "vhh_sequence": f"V{split}{target}{label}{index}",
                                "target_sequence": target,
                                "sequence_sha256": f"v-{split}-{target}-{label}-{index}",
                                "target_sequence_sha256": f"a-{target}",
                                "label": label,
                            }
                        )
        frame = pd.DataFrame(rows)
        first = MOD.select_smoke(frame, 8)
        second = MOD.select_smoke(frame, 8)
        self.assertEqual(first["sample_id"].tolist(), second["sample_id"].tolist())
        counts = first.groupby(["split", "target_id", "label"]).size().tolist()
        self.assertEqual(set(counts), {4})

    def test_current_binding_source_has_expected_splits(self) -> None:
        frame = pd.read_csv(MOD.DEFAULT_BINDING, usecols=["split"])
        self.assertEqual(set(frame["split"].astype(str)), {"train", "dev"})


if __name__ == "__main__":
    unittest.main()
