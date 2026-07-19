#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
import sys
import unittest
from pathlib import Path

PATH = Path(__file__).with_name("real1507_role_isolated_trainer_v1_4.py")
SPEC = importlib.util.spec_from_file_location("trainer_v14", PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)

class ContactAblationContractTests(unittest.TestCase):
    def test_combined(self):
        self.assertEqual(mod.validate_contact_ablation_weights(1.0, 0.5), "COMBINED")
    def test_marginal_only(self):
        self.assertEqual(mod.validate_contact_ablation_weights(1.0, 0.0), "MARGINAL_ONLY")
    def test_pair_only(self):
        self.assertEqual(mod.validate_contact_ablation_weights(0.0, 0.5), "PAIR_ONLY")
    def test_both_zero_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "contact_ablation_both_zero"):
            mod.validate_contact_ablation_weights(0.0, 0.0)
    def test_negative_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "contact_weight_negative"):
            mod.validate_contact_ablation_weights(-1.0, 0.5)
    def test_contract_declares_modes(self):
        modes = mod.integration_contract()["contact_ablation_modes"]
        self.assertEqual(set(modes), {"COMBINED", "MARGINAL_ONLY", "PAIR_ONLY"})

if __name__ == "__main__":
    unittest.main()
