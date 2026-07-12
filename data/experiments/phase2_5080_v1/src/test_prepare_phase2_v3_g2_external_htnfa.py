#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

MODULE_PATH = Path(__file__).with_name("prepare_phase2_v3_g2_external_htnfa.py")
SPEC = importlib.util.spec_from_file_location("prepare_phase2_v3_g2_external_htnfa", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class PrepareExternalHTNFaTest(unittest.TestCase):
    def test_current_formal_ids_match(self) -> None:
        blinded = pd.read_csv(MOD.DEFAULT_BLINDED, usecols=["sample_id", "formal_block"])
        labels = pd.read_csv(MOD.DEFAULT_LABELS, usecols=["sample_id", "formal_block"])
        blinded_ids = set(blinded.loc[blinded.formal_block == "external_hTNFa", "sample_id"].astype(str))
        label_ids = set(labels.loc[labels.formal_block == "external_hTNFa", "sample_id"].astype(str))
        self.assertEqual(blinded_ids, label_ids)
        self.assertEqual(len(blinded_ids), 5571)

    def test_prepare_rejects_development_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            blinded = pd.DataFrame([{"sample_id": "s", "formal_block": "external_hTNFa", "sequence_sha256": "v", "target_sequence_sha256": "t", "vhh_sequence": "V", "target_sequence": "T"}])
            labels = pd.DataFrame([{"sample_id": "s", "formal_block": "external_hTNFa", "label": 1}])
            development = pd.DataFrame([{"sequence_sha256": "v"}])
            blinded.to_csv(root / "b.csv", index=False)
            labels.to_csv(root / "l.csv", index=False)
            development.to_csv(root / "d.csv", index=False)
            with self.assertRaises(ValueError):
                MOD.prepare(root / "b.csv", root / "l.csv", root / "d.csv", root / "out.csv")


if __name__ == "__main__":
    unittest.main()
