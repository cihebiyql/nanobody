import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


HERE = Path(__file__).resolve()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


builder = load("v222_builder", HERE.with_name("build_v2_2_2_strict_nested_package_v1.py"))
auditor = load("v222_auditor", HERE.with_name("audit_v2_2_2_strict_nested_package_v1.py"))


class V222StrictPackageTests(unittest.TestCase):
    def test_frozen_inputs_and_stage1_reconciliation(self):
        result = builder.validate_inputs()
        self.assertEqual(result["training_candidates"], 1507)
        self.assertEqual(result["teacher_source_counts"], {"V4D_OPEN_MULTI_SEED": 226, "V4H_ADAPTIVE_SEED_RANKING": 1281})
        self.assertEqual(result["stage1_analyzable_candidates"], 1281)
        self.assertEqual(result["stage2_selected_candidates"], 384)
        self.assertTrue(result["v4h_training_exactly_matches_stage1_analyzable"])

    def test_lane_weight_drift_is_rejected(self):
        ready = json.loads(builder.READY.read_text(encoding="utf-8"))
        tampered = deepcopy(ready)
        tampered["trainer"]["lane_outer_extra_argv"]["C_SPLIT_MARGINAL"] = [
            "--marginal-weight", "1.4", "--pair-weight", "0.0"
        ]
        with self.assertRaisesRegex(builder.PackageError, "lane_weight_drift"):
            builder.validate_lane_contract(tampered)

    def test_later_authorized_planner_command_resolves_v222_adaptive_names(self):
        ready = json.loads(builder.READY.read_text(encoding="utf-8"))
        ready["production_authorized"] = True
        planner = builder.import_planner()
        command = planner.substitute_trainer_command(ready, "D_SPLIT_PAIR", "/split.json", "/output")
        self.assertIn(ready["artifacts"]["adaptive_marginal_tsv_gz"]["node1_path"], command)
        self.assertIn(ready["artifacts"]["adaptive_pair_tsv_gz"]["node1_path"], command)
        self.assertEqual(command[command.index("--marginal-weight") + 1], "1.0")
        self.assertEqual(command[command.index("--pair-weight") + 1], "0.5")
        self.assertEqual(command[command.index("--backbone-kind") + 1], "hf")
        self.assertEqual(command[command.index("--device") + 1], "cuda")

    def test_full_build_is_immutable_non_launching_195_job_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "package"
            result = builder.build(root)
            self.assertFalse(result["launch_authorized"])
            self.assertFalse(result["training_or_prediction_executed"])
            self.assertEqual(result["job_count"], 195)
            audit = auditor.audit(root)
            self.assertEqual(audit["status"], "PASS_IMMUTABLE_NON_LAUNCHING_PACKAGE")
            self.assertEqual(audit["gpu_job_count"], 90)
            graph = json.loads((root / "node1_bundle" / "plan" / "job_graph.json").read_text())
            self.assertFalse(graph["execution_authorized"])
            self.assertTrue(all(job.get("command") is None for job in graph["jobs"] if job["kind"].startswith("GPU_")))


if __name__ == "__main__":
    unittest.main()
