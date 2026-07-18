import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(value)
    return value


auth = module("auth_v222", HERE.with_name("authorize_v2_2_2_strict_nested_package_v1.py"))
audit_mod = module("audit_auth_v222", HERE.with_name("audit_authorized_v2_2_2_strict_nested_package_v1.py"))
DRY = HERE.parent / "prepared" / "dry_run_v1"


class AuthorizedPackageTests(unittest.TestCase):
    def test_authorized_graph_is_separate_exact_195_job_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "authorized"
            result = auth.build(DRY, root)
            self.assertTrue(result["launch_authorized"])
            self.assertFalse(result["training_or_prediction_executed"])
            self.assertEqual(result["job_graph"]["job_count"], 195)
            report = audit_mod.audit(root)
            self.assertEqual(report["status"], "PASS_AUTHORIZED_PACKAGE_READY_TO_LAUNCH")
            graph = json.loads((root / "node1_bundle" / "plan" / "job_graph.json").read_text())
            gpu = [j for j in graph["jobs"] if j["kind"].startswith("GPU_")]
            self.assertTrue(all(j["command"] for j in gpu))
            self.assertEqual({j["physical_gpu"] for j in gpu}, {2, 4, 5})
            base_ready = json.loads(auth.base.READY.read_text())
            self.assertFalse(base_ready["production_authorized"])


if __name__ == "__main__":
    unittest.main()
