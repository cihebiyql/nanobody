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
                logs = run.parent / "logs"
                logs.mkdir()
                selected_cores = 4 if index == 0 else 8
                (logs / f"{cid}_haddock3_run.log").write_text(
                    "Selected 2 cores to process 2 jobs\n"
                    f"Selected {selected_cores} cores to process 40 jobs\n",
                    encoding="utf-8",
                )
                reports = root / f"shard_{index}/reports/{cid}"
                reports.mkdir(parents=True)
                for suffix in ("sequence_validation", "monomer_geometry_qc", "pvrig_receptor_geometry_qc"):
                    (reports / f"{cid}_{suffix}.json").write_text("{}", encoding="utf-8")
            audit = MOD.inventory(root, 2, 3, 2)
            self.assertEqual(audit["status"], "PASS")
            self.assertEqual(audit["runtime_haddock_log_files"], 2)
            self.assertEqual(audit["runtime_max_selected_core_counts"], {4: 1, 8: 1})

    def test_runtime_core_evidence_uses_log_max_not_postrun_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "shard_0/haddock3/c0/logs/c0_haddock3_run.log"
            log.parent.mkdir(parents=True)
            log.write_text(
                "Selected 2 cores to process 2 jobs\n"
                "Selected 4 cores to process 40 jobs\n",
                encoding="utf-8",
            )
            config = root / "shard_0/haddock3/c0/c0_pvrig_hotspot.cfg"
            config.write_text("ncores = 8\n", encoding="utf-8")
            evidence = MOD.runtime_core_evidence(root)
            self.assertEqual(evidence["runtime_max_selected_core_counts"], {4: 1})


if __name__ == "__main__":
    unittest.main()
