import importlib.util
import pathlib
import unittest


HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("materialize_bundle_v2", HERE / "materialize_node1_bundle_v2.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class BundleV2ContractTests(unittest.TestCase):
    def test_v2_names_are_distinct_from_v1(self) -> None:
        self.assertEqual(MODULE.MANIFEST_NAME, "V2_4_NODE1_PREFREEZE_MANIFEST_V2.json")
        self.assertIn("V2_ADAPTIVE", MODULE.PENDING_STATUS)

    def test_imports_v2_launcher(self) -> None:
        self.assertIn("launcher_v2", pathlib.Path(MODULE.deployment.__file__).name)


if __name__ == "__main__":
    unittest.main()
