#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[4] / "docking/success_case_validation/process_haddock3_calibration_run.py"
SPEC = importlib.util.spec_from_file_location("process_haddock3_calibration_run", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class ProcessHaddockCalibrationRunTest(unittest.TestCase):
    def test_selected_models_deduplicate_compressed_and_plain_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            selected = Path(tmp) / "6_seletopclusts"
            selected.mkdir()
            for name in (
                "cluster_1_model_1.pdb",
                "cluster_1_model_1.pdb.gz",
                "cluster_2_model_1.pdb.gz",
            ):
                (selected / name).write_text("x", encoding="utf-8")
            models = MOD.selected_model_paths(Path(tmp), 10)
            self.assertEqual([name for name, _ in models], ["cluster_1_model_1", "cluster_2_model_1"])
            self.assertEqual(models[0][1].suffix, ".gz")


if __name__ == "__main__":
    unittest.main()
