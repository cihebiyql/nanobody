import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[1]
TRAINER = ROOT / "src" / "train_nested_residue_surrogate_v1_4.py"
COLLECTOR = ROOT / "src" / "collect_residue_oof_v1_4.py"
GOVERNANCE = ROOT.parent / "PREREGISTRATION_V1_1_IMPLEMENTATION_AMENDMENT.json"
FREEZE = ROOT / "IMPLEMENTATION_FREEZE_V1_4.json"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


trainer = load("residue_trainer_v1_4", TRAINER)
collector = load("residue_collector_v1_4_for_trainer_test", COLLECTOR)


class TestV14CollectorMatrixClosure(unittest.TestCase):
    def test_real_v14_freeze_closes_for_trainer(self):
        hashes = trainer.validate_implementation_freeze(FREEZE, ROOT, GOVERNANCE)
        self.assertEqual(hashes["src/train_nested_residue_surrogate_v1_4.py"], trainer.sha256_file(TRAINER))

    def test_trainer_and_collector_freeze_the_same_matrix(self):
        self.assertEqual(trainer.COLLECTOR_MATRIX, collector.COLLECTOR_MATRIX)
        self.assertEqual(trainer.COLLECTOR_MATRIX_SHA256, collector.COLLECTOR_MATRIX_SHA256)
        payload = {
            "collector_matrix": dict(trainer.COLLECTOR_MATRIX),
            "collector_matrix_sha256": trainer.COLLECTOR_MATRIX_SHA256,
        }
        trainer.validate_collector_matrix_binding(payload)

    def test_trainer_rejects_nonfrozen_repetition_seed_and_hash(self):
        mutations = (
            ("bootstrap_repetitions", 2000, "freeze_collector_matrix_mismatch"),
            ("bootstrap_seed", 20260719, "freeze_collector_matrix_mismatch"),
        )
        for field, value, expected in mutations:
            with self.subTest(field=field):
                payload = {
                    "collector_matrix": dict(trainer.COLLECTOR_MATRIX),
                    "collector_matrix_sha256": trainer.COLLECTOR_MATRIX_SHA256,
                }
                payload["collector_matrix"][field] = value
                with self.assertRaisesRegex(Exception, expected):
                    trainer.validate_collector_matrix_binding(payload)
        payload = {
            "collector_matrix": dict(trainer.COLLECTOR_MATRIX),
            "collector_matrix_sha256": "0" * 64,
        }
        with self.assertRaisesRegex(Exception, "freeze_collector_matrix_sha256_mismatch"):
            trainer.validate_collector_matrix_binding(payload)


if __name__ == "__main__":
    unittest.main()
