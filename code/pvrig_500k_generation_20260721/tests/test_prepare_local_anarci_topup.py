from pathlib import Path
import importlib.util
import unittest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "prepare_local_anarci_topup.py"
SPEC = importlib.util.spec_from_file_location("prepare_local_anarci_topup", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PrepareLocalAnarciTopupTest(unittest.TestCase):
    def test_selects_only_unused_fast_qc_passes(self):
        raw = [
            {"candidate_id": "used", "fast_qc_status": "PASS"},
            {"candidate_id": "spare", "fast_qc_status": "PASS"},
            {"candidate_id": "failed", "fast_qc_status": "FAIL"},
        ]
        self.assertEqual(
            MODULE.unused_fast_qc_passes(raw, [{"candidate_id": "used"}]),
            [{"candidate_id": "spare", "fast_qc_status": "PASS"}],
        )


if __name__ == "__main__":
    unittest.main()
