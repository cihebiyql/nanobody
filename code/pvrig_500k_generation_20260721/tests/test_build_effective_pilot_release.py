from pathlib import Path
import importlib.util
import unittest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "build_effective_pilot_release.py"
SPEC = importlib.util.spec_from_file_location("build_effective_pilot_release", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class EffectiveReleaseTest(unittest.TestCase):
    def test_cdr3_family_uses_transitive_hamming80_components(self):
        values = ["AAAAAAAAAA", "AAAAAAAATA", "AAAAAAATTA", "CCCCCCCCCC"]
        mapping = MODULE.cdr3_families(values)
        self.assertEqual(mapping[values[0]], mapping[values[1]])
        self.assertEqual(mapping[values[1]], mapping[values[2]])
        self.assertNotEqual(mapping[values[0]], mapping[values[3]])

    def test_normalize_requires_parent_and_cdr3(self):
        with self.assertRaises(ValueError):
            MODULE.normalize("route", {"candidate_id": "x", "sequence": "AAAA"})


if __name__ == "__main__":
    unittest.main()
