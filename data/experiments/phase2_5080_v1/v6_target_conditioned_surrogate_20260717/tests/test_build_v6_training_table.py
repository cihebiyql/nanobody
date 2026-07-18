import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).parents[1] / "data" / "build_v6_training_table.py"
spec = importlib.util.spec_from_file_location("v6_data", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


class TestV6DataHelpers(unittest.TestCase):
    def test_parent_fold_is_deterministic(self):
        self.assertEqual(mod.parent_fold("C0009"), mod.parent_fold("C0009"))
        self.assertIn(mod.parent_fold("C0009"), range(5))

    def test_sequence_hash(self):
        self.assertEqual(
            mod.sequence_hash("ACD"),
            "00e66854ddc46722ac3db985136265f4a24bcbbf0b45103d80cfea510e9217bf",
        )

    def test_feature_columns_excludes_metadata(self):
        row = {
            "schema_version": "x", "candidate_id": "c", "sequence_sha256": "s",
            "parent_framework_cluster": "p", "monomer_sha256": "m",
            "ALL__x": "1", "claim_boundary": "q",
        }
        self.assertEqual(mod.feature_columns(row), ["ALL__x"])


if __name__ == "__main__":
    unittest.main()
