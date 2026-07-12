#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("process_pvrig_teacher_pilot96.py")
SPEC = importlib.util.spec_from_file_location("process_pvrig_teacher_pilot96", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def write_csv(path: Path, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["model"])
        writer.writeheader()
        for index in range(rows):
            writer.writerow({"model": f"m{index}"})


class ProcessPilot96Test(unittest.TestCase):
    def test_cdr_range(self) -> None:
        self.assertEqual(MOD.cdr_range("AAABBBCCC", "BBB"), "4-6")
        with self.assertRaises(ValueError):
            MOD.cdr_range("AAAAAA", "AAA")

    def test_find_run_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = root / "shard_2/haddock3/c1/run_c1_pvrig_hotspot"
            expected.mkdir(parents=True)
            self.assertEqual(MOD.find_run_dir(root, "c1"), expected)
            selected = expected / "6_seletopclusts"
            selected.mkdir()
            (selected / "cluster_1_model_1.pdb.gz").write_text("x", encoding="utf-8")
            self.assertEqual(MOD.selected_model_count(expected), 1)

    def test_completion_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            cid = "c1"
            for name in (
                f"{cid}_8x6b_9e6y_consensus.csv",
                f"{cid}_8x6b_blocker_classification.csv",
                f"{cid}_9e6y_blocker_classification.csv",
            ):
                write_csv(workdir / "reports" / name, 2)
            for label in ("8x6b", "9e6y"):
                folder = workdir / f"haddock3/top_models_aligned_to_{label}"
                folder.mkdir(parents=True)
                for index in range(2):
                    (folder / f"m{index}_aligned_to_{label}.pdb").write_text("END\n", encoding="utf-8")
            self.assertTrue(MOD.completion_evidence(workdir, cid, 2)["complete"])


if __name__ == "__main__":
    unittest.main()
