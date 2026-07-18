import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).parents[1] / "src" / "cache_v6_esm_embeddings.py"
spec = importlib.util.spec_from_file_location("v6_cache", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


class TestCacheHelpers(unittest.TestCase):
    def test_cdr_bounds(self):
        self.assertEqual(mod.cdr_bounds("AAACCCGGG", "CCC", "x"), (3, 6))

    def test_cdr_missing_fails(self):
        with self.assertRaises(ValueError):
            mod.cdr_bounds("AAAA", "CCC", "x")

    def test_cdr_ambiguous_fails(self):
        with self.assertRaises(ValueError):
            mod.cdr_bounds("AACCAAACC", "AA", "x")


if __name__ == "__main__":
    unittest.main()
