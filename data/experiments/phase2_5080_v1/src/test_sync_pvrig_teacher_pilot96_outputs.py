#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("sync_pvrig_teacher_pilot96_outputs.py")
SPEC = importlib.util.spec_from_file_location("sync_pvrig_teacher_pilot96_outputs", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class SyncPilot96Test(unittest.TestCase):
    def test_remote_command_requires_completion_marker(self) -> None:
        command = MOD.remote_archive_command("/remote/root")
        self.assertIn('test -f "$ROOT/docking.complete"', command)
        self.assertIn("6_seletopclusts", command)
        self.assertIn("traceback/consensus.tsv", command)

    def test_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docking.complete").write_text("", encoding="utf-8")
            for index in range(2):
                cid = f"c{index}"
                run = root / f"shard_{index}/haddock3/{cid}/run_{cid}_pvrig_hotspot"
                selected = run / "6_seletopclusts"
                selected.mkdir(parents=True)
                (run / "traceback").mkdir()
                (run / "traceback/consensus.tsv").write_text("Model\n", encoding="utf-8")
                for model in range(3):
                    (selected / f"cluster_{model + 1}_model_1.pdb.gz").write_text("x", encoding="utf-8")
                reports = root / f"shard_{index}/reports/{cid}"
                reports.mkdir(parents=True)
                for suffix in ("sequence_validation", "monomer_geometry_qc", "pvrig_receptor_geometry_qc"):
                    (reports / f"{cid}_{suffix}.json").write_text("{}", encoding="utf-8")
            self.assertEqual(MOD.inventory(root, 2, 3, 2)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
