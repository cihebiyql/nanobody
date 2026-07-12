#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np

MODULE_PATH = Path(__file__).with_name("train_phase2_v3_g1_binding_smoke.py")
SPEC = importlib.util.spec_from_file_location("train_phase2_v3_g1_binding_smoke", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class V3G1BindingSmokeTest(unittest.TestCase):
    def test_macro_target_auprc(self) -> None:
        macro, per_target = MOD.macro_target_auprc(
            np.asarray([0, 1, 0, 1]),
            np.asarray([0.1, 0.9, 0.2, 0.8]),
            ["a", "a", "b", "b"],
        )
        self.assertEqual(macro, 1.0)
        self.assertEqual(per_target, {"a": 1.0, "b": 1.0})

    def test_current_inputs_exist(self) -> None:
        for path in (MOD.DEFAULT_BINDING, MOD.DEFAULT_CACHE, MOD.DEFAULT_CDR, MOD.DEFAULT_CHECKPOINT):
            self.assertTrue(path.exists(), path)


if __name__ == "__main__":
    unittest.main()
