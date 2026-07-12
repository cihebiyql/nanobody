#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_pvrig_formal_parent40_structure_package.py")
SPEC = importlib.util.spec_from_file_location("build_pvrig_formal_parent40_structure_package", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class BuildParent40StructurePackageTest(unittest.TestCase):
    def test_current_package_builds_four_equal_shards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "package"
            audit = MOD.run(MOD.DEFAULT_MANIFEST, root, False)
            self.assertEqual(audit["status"], "PASS_PARENT40_STRUCTURE_PACKAGE_READY")
            self.assertEqual(audit["shard_counts"], {f"shard_{index}": 10 for index in range(4)})
            self.assertTrue((root / "run_parent40_controller.sh").exists())
            self.assertEqual(len(list(root.glob("shard_*/manifests/parents.tsv"))), 4)


if __name__ == "__main__":
    unittest.main()
