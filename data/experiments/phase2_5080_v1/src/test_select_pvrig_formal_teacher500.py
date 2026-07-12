#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

MODULE_PATH = Path(__file__).with_name("select_pvrig_formal_teacher500.py")
SPEC = importlib.util.spec_from_file_location("select_pvrig_formal_teacher500", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class SelectPVRIGFormalTeacher500Test(unittest.TestCase):
    def synthetic_frame(self) -> pd.DataFrame:
        rows = []
        split_parents = {"train": 28, "dev": 6, "test": 6}
        counter = 0
        for split, parent_count in split_parents.items():
            for parent in range(parent_count):
                parent_id = f"{split}_p{parent:02d}"
                for patch in ("A", "B", "C"):
                    for mode in ("H3", "H1H3"):
                        for replicate in range(4):
                            counter += 1
                            sequence = "Q" * 90 + f"{parent:02d}{patch}{mode}{replicate}"
                            rows.append(
                                {
                                    "candidate_id": f"c{counter:05d}",
                                    "vhh_sequence": sequence,
                                    "sequence_sha256": f"sha{counter:05d}",
                                    "parent_id": parent_id,
                                    "formal_split": split,
                                    "target_patch_id": patch,
                                    "design_mode": mode,
                                    "cdr3_after": f"CAR{patch}{replicate}{parent}",
                                    "fast_gate_tier": "FORMAL_ELIGIBLE",
                                    "generic_binding_prior": ((counter * 17) % 997) / 997,
                                    "model_uncertainty": ((counter * 31) % 991) / 991,
                                    "model_disagreement": ((counter * 43) % 983) / 983,
                                    "cheap_qc_score": 0.5 + ((counter * 7) % 499) / 998,
                                }
                            )
        return pd.DataFrame(rows)

    def test_quota_and_caps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scores.csv"
            self.synthetic_frame().to_csv(path, index=False)
            frame = MOD.prepare_frame(path)
            selected = MOD.select_panel(frame)
            self.assertEqual(len(selected), 500)
            self.assertEqual(selected["formal_split"].value_counts().to_dict(), MOD.SPLIT_QUOTAS)
            self.assertLessEqual(int(selected["parent_id"].value_counts().max()), MOD.PARENT_CAP)
            strata = selected.groupby(["parent_id", "target_patch_id", "design_mode"]).size()
            self.assertLessEqual(int(strata.max()), MOD.STRATUM_CAP)
            expected_layers = {name: sum(values.values()) for name, values in MOD.LAYER_SPLIT_QUOTAS.items()}
            self.assertEqual(selected["teacher_selection_layer"].value_counts().to_dict(), expected_layers)

    def test_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scores.csv"
            self.synthetic_frame().to_csv(path, index=False)
            frame = MOD.prepare_frame(path)
            first = MOD.select_panel(frame)["candidate_id"].tolist()
            second = MOD.select_panel(frame)["candidate_id"].tolist()
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
