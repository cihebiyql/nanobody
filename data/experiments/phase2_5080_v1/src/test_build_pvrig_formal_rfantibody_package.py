#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_pvrig_formal_rfantibody_package.py")
SPEC = importlib.util.spec_from_file_location("build_pvrig_formal_rfantibody_package", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class BuildFormalRfantibodyPackageTest(unittest.TestCase):
    def test_current_task_shape(self) -> None:
        parents = MOD.read_tsv(MOD.DEFAULT_PARENTS)
        tasks = MOD.build_tasks(parents)
        self.assertEqual(len(tasks), 240)
        self.assertEqual(sum(int(row["expected_raw_records"]) for row in tasks), 8640)
        self.assertEqual(Counter(row["patch_id"] for row in tasks), Counter({patch: 80 for patch in MOD.PATCHES}))
        self.assertEqual(Counter(row["design_mode"] for row in tasks), Counter(H3=120, H1H3=120))
        self.assertEqual(len(MOD.validation_tasks(tasks)), 8)

    def test_package_is_shell_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit = MOD.run(MOD.DEFAULT_PARENTS, MOD.DEFAULT_TARGET, Path(tmp) / "package", False)
            self.assertEqual(audit["status"], "PASS_RFANTIBODY_MULTIPARENT_PACKAGE_READY")
            self.assertEqual(audit["expected_backbones"], 2880)
            self.assertEqual(audit["expected_raw_records"], 8640)


if __name__ == "__main__":
    unittest.main()
