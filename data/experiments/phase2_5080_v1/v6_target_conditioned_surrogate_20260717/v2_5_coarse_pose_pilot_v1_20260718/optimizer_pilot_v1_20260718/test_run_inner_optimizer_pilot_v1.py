import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location("optimizer_pilot", HERE.with_name("run_inner_optimizer_pilot_v1.py"))
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class OptimizerPilotTests(unittest.TestCase):
    def test_rank_ties(self):
        self.assertEqual(module.ranks([3.0, 1.0, 1.0, 2.0]), [4.0, 1.5, 1.5, 3.0])

    def test_metrics_perfect(self):
        rows = [
            {"truth_Rdual": str(value), "neural_Rdual": str(value)}
            for value in (0.1, 0.4, 0.2, 0.3)
        ]
        result = module.metrics(rows, "Rdual")
        self.assertAlmostEqual(result["spearman"], 1.0)
        self.assertAlmostEqual(result["mae"], 0.0)
        self.assertAlmostEqual(result["rmse"], 0.0)

    def test_set_arg_requires_unique_flag(self):
        command = ["python", "x.py", "--fixed-epochs", "8"]
        module.set_arg(command, "--fixed-epochs", 16)
        self.assertEqual(command[-1], "16")
        with self.assertRaisesRegex(module.PilotError, "flag_count"):
            module.set_arg(command, "--missing", 1)

    def test_variant_split_changes_only_epochs(self):
        payload = {
            "split_id": "outer_0_inner_0", "outer_fold": 0,
            "train_parents": ["A"], "score_parents": ["B"], "fixed_epochs": 8,
            "open_only": True, "v4_f_test32_access_count": 0,
            "train_parent_set_sha256": "train", "score_parent_set_sha256": "score",
        }
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.json"
            destination = Path(temporary) / "variant.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            receipt = module.materialize_variant_split(source, destination, 16)
            observed = json.loads(destination.read_text())
            self.assertEqual(receipt["changed_fields"], ["fixed_epochs"])
            self.assertEqual(observed["fixed_epochs"], 16)
            self.assertEqual(observed["train_parents"], ["A"])
            self.assertEqual(observed["score_parents"], ["B"])


if __name__ == "__main__":
    unittest.main()
