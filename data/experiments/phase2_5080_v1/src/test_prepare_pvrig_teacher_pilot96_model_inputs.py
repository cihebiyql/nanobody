#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("prepare_pvrig_teacher_pilot96_model_inputs.py")
SPEC = importlib.util.spec_from_file_location("prepare_pvrig_teacher_pilot96_model_inputs", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class PreparePilot96InputsTest(unittest.TestCase):
    def test_current_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp)
            audit = MOD.run(MOD.DEFAULT_SELECTION, MOD.DEFAULT_TARGET, outdir)
            self.assertEqual(audit["records"], 96)
            self.assertEqual(audit["unique_vhh_sequences"], 96)
            self.assertEqual(audit["parent_framework_clusters"], ["h-NbBCII10"])
            with (outdir / "pvrig_teacher_pilot96_pair_inputs.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual({row["target_id"] for row in rows}, {"PVRIG_structural_ectodomain_proxy_v1"})


if __name__ == "__main__":
    unittest.main()
