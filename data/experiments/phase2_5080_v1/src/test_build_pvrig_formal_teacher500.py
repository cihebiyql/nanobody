#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_pvrig_formal_teacher500.py")
SPEC = importlib.util.spec_from_file_location("build_pvrig_formal_teacher500", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class BuildPVRIGFormalTeacher500Test(unittest.TestCase):
    def test_make_case_uses_formal_patch_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "c1/reports"
            work.mkdir(parents=True)
            consensus = work / "c1_8x6b_9e6y_consensus.csv"
            consensus.write_text("model\n", encoding="utf-8")
            case = MOD.make_case(
                {
                    "candidate_id": "c1",
                    "target_patch_id": "A_CENTER",
                    "design_mode": "H3",
                    "vhh_sequence": "QVQL",
                },
                root,
            )
            self.assertEqual(case.family, "RFantibody_A_CENTER_H3")
            self.assertEqual(case.consensus_csv, consensus)

    def test_teacher_manifest_keeps_parent_split(self) -> None:
        row = {"candidate_id": "c1", "formal_split": "test", "vhh_sequence": "QVQL"}
        case = MOD.base.Case("c1", "c1", "family", "QVQL", MOD.DATASET_ROLE, Path("/tmp/c1"), Path("/tmp/c1.csv"))
        output = MOD.teacher_manifest_row(row, case)
        self.assertEqual(output["formal_split"], "test")
        self.assertEqual(output["calibration_only"], "false")
        self.assertEqual(output["leakage_status"], MOD.LEAKAGE_STATUS)


if __name__ == "__main__":
    unittest.main()
