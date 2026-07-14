from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("freeze_protocol", ROOT / "scripts/freeze_protocol.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ProtocolFreezeTests(unittest.TestCase):
    def test_core_freeze_fails_when_required_files_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config/protocol_spec.json").write_text(
                json.dumps(
                    {
                        "protocol_id": "test",
                        "candidate_panel": {"expected_count": 128},
                        "controls": {"expected_count": 47},
                    }
                )
            )
            with self.assertRaises(ValueError):
                MODULE.freeze_core(root)

    def test_declared_core_files_are_unique(self) -> None:
        self.assertEqual(len(MODULE.CORE_FILES), len(set(MODULE.CORE_FILES)))

    def test_declared_final_files_are_unique(self) -> None:
        self.assertEqual(len(MODULE.FINAL_FILES), len(set(MODULE.FINAL_FILES)))


if __name__ == "__main__":
    unittest.main()
