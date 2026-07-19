import hashlib
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src/run_sequence_stage0_open_inner_v1.py"
SPEC = importlib.util.spec_from_file_location("stage0", MODULE_PATH)
stage0 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(stage0)


class Stage0Tests(unittest.TestCase):
    def test_forbidden_paths_fail_closed(self):
        for value in ("/tmp/V4_F/a", "/tmp/test32/a", "/tmp/outer_test/a", "/tmp/sealed/a"):
            with self.assertRaises(RuntimeError):
                stage0.reject_forbidden_path(Path(value), "fixture")

    def test_exact_min(self):
        pred = np.asarray([[0.5, 0.4], [0.2, 0.7]])
        np.testing.assert_allclose(stage0.exact_min(pred), [0.4, 0.2])

    def test_region_features_are_finite_and_fixed_width(self):
        values = stage0.region_features("ACDEFGHIKLMNPQRSTVWY")
        self.assertEqual(len(values), 31)
        self.assertTrue(np.isfinite(values).all())
        self.assertAlmostEqual(sum(values[1:21]), 1.0)

    def test_enrichment_perfect_ranking(self):
        truth = np.arange(100, dtype=float)
        rows = stage0.enrichment_table(truth, truth)
        item = next(x for x in rows if x["true_top_fraction"] == 0.10 and x["predicted_budget_fraction"] == 0.10)
        self.assertEqual(item["hits"], 10)
        self.assertAlmostEqual(item["recall"], 1.0)
        self.assertAlmostEqual(item["enrichment_factor"], 10.0)

    def test_parent_hash_is_order_invariant(self):
        self.assertEqual(stage0.stable_parent_hash(["B", "A"]), stage0.stable_parent_hash(["A", "B", "A"]))

    def test_load_json_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.json"
            source.write_text(json.dumps({"ok": True}))
            link = root / "link.json"
            link.symlink_to(source)
            with self.assertRaises(RuntimeError):
                stage0.load_json(link)


if __name__ == "__main__":
    unittest.main()

