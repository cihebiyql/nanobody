import importlib.util
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location("recovery", HERE.with_name("recover_authorized_v2_2_2_split_training_v1_1.py"))
recovery = importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def test_filtered_training_views_close_frozen_split_parents(self):
        source = HERE.parent / "prepared" / "authorized_v1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "recovery"
            result = recovery.build(source, root)
            self.assertEqual(result["split_training_input_count"], 30)
            self.assertFalse(result["recovery_contract"]["trainer_changed"])
            self.assertFalse(result["recovery_contract"]["split_membership_changed"])
            audit = recovery.audit(root)
            self.assertEqual(audit["status"], "PASS_AUTHORIZED_V1_1_RECOVERY_READY_TO_LAUNCH")
            self.assertEqual(audit["job_count"], 195)


if __name__ == "__main__":
    unittest.main()
