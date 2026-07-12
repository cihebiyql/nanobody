#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import torch

MODULE_PATH = Path(__file__).with_name("train_phase2_v3_g2_generic.py")
SPEC = importlib.util.spec_from_file_location("train_phase2_v3_g2_generic", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class V3G2GenericTest(unittest.TestCase):
    def test_cross_family_targets_never_uses_same_family_when_two_exist(self) -> None:
        frame = pd.DataFrame(
            [
                {"dataset_id": "a", "target_sequence": "AAAA"},
                {"dataset_id": "b", "target_sequence": "BBBB"},
            ]
        )
        swaps = MOD.cross_family_targets(frame)
        self.assertEqual(swaps["a"], ("BBBB", True))
        self.assertEqual(swaps["b"], ("AAAA", True))

    def test_observed_contrasts_require_same_vhh_and_opposite_real_labels(self) -> None:
        frame = pd.DataFrame(
            [
                {"split": "train", "sequence_sha256": "v1", "vhh_sequence": "V", "label": 1, "target_sequence": "A", "target_sequence_sha256": "a", "sample_id": "p"},
                {"split": "train", "sequence_sha256": "v1", "vhh_sequence": "V", "label": 0, "target_sequence": "B", "target_sequence_sha256": "b", "sample_id": "n"},
                {"split": "train", "sequence_sha256": "v2", "vhh_sequence": "W", "label": 1, "target_sequence": "A", "target_sequence_sha256": "a", "sample_id": "only"},
            ]
        )
        contrasts = MOD.build_observed_contrasts(frame, "train")
        self.assertEqual(len(contrasts), 1)
        self.assertEqual(contrasts.iloc[0]["sequence_sha256"], "v1")
        self.assertEqual(contrasts.iloc[0]["positive_target_sequence"], "A")
        self.assertEqual(contrasts.iloc[0]["negative_target_sequence"], "B")

    def test_macro_target_auprc(self) -> None:
        macro, per_target = MOD.macro_target_auprc(
            np.asarray([0, 1, 0, 1]),
            np.asarray([0.1, 0.9, 0.2, 0.8]),
            ["a", "a", "b", "b"],
        )
        self.assertEqual(macro, 1.0)
        self.assertEqual(per_target, {"a": 1.0, "b": 1.0})

    def test_optimizer_groups_cover_each_parameter_once(self) -> None:
        cfg = MOD.v23.Config(d_model=16, esm_dim=8, contact_dim=4, layers=1, cross_layers=1, heads=4, max_vhh_len=20, max_antigen_len=30)
        model = MOD.v23.CrossContactNetV23(cfg)
        groups, names = MOD.optimizer_groups(model, MOD.TrainConfig())
        parameters = [parameter for group in groups for parameter in group["params"]]
        self.assertEqual(len(parameters), len(set(map(id, parameters))))
        self.assertEqual(len(parameters), len(list(model.parameters())))
        self.assertTrue(names["head"])
        self.assertTrue(names["backbone"])

    def test_current_inputs_exist(self) -> None:
        for path in (MOD.DEFAULT_BINDING, MOD.DEFAULT_CACHE, MOD.DEFAULT_CDR, MOD.DEFAULT_DATA_AUDIT, MOD.DEFAULT_CHECKPOINT):
            self.assertTrue(path.exists(), path)


if __name__ == "__main__":
    unittest.main()
