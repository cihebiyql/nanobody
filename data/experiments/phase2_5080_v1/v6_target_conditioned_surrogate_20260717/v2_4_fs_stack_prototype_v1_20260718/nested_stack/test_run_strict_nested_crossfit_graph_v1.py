import importlib.util
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
SPEC = importlib.util.spec_from_file_location("graph_runner", HERE.with_name("run_strict_nested_crossfit_graph_v1.py"))
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)
PREPARED = HERE.parent / "prepared" / "strict_double_crossfit_dryrun_v3" / "job_graph.json"


class GraphRunnerTests(unittest.TestCase):
    def test_pending_graph_status_does_not_execute(self):
        graph = mod.load_graph(PREPARED)
        report = mod.status(graph)
        self.assertEqual(report["status"], "PASS_GRAPH_STATUS_ONLY_NO_EXECUTION")
        self.assertFalse(report["execution_authorized"])
        self.assertEqual(report["job_count"], 195)
        self.assertEqual(report["job_states"], {"PENDING": 195})

    def test_pending_graph_cannot_execute_even_with_token(self):
        graph = mod.load_graph(PREPARED)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(mod.GraphExecutionError, "graph_not_execution_authorized"):
                mod.execute(graph, mod.AUTHORIZATION, Path(tmp), 2)

    def test_cycle_and_sealed_token_fail_closed(self):
        base = json.loads(PREPARED.read_text())
        base["jobs"][0]["dependencies"] = [base["jobs"][0]["job_id"]]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"; path.write_text(json.dumps(base))
            with self.assertRaisesRegex(mod.GraphExecutionError, "job_graph_cycle"):
                mod.load_graph(path)
        base = json.loads(PREPARED.read_text())
        base["claim_boundary"] += " /pvrig_v4_f/test32"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"; path.write_text(json.dumps(base))
            with self.assertRaisesRegex(mod.GraphExecutionError, "sealed_token_in_graph"):
                mod.load_graph(path)

    def test_authorized_dummy_cpu_dag_executes_in_dependency_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "artifact.txt"; artifact.write_text("frozen\n")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            first, second = root / "first.done", root / "second.done"
            graph = {
                "schema_version": mod.SCHEMA,
                "status": "READY_EXECUTABLE_POSTCALIBRATION_FREEZE",
                "execution_authorized": True,
                "sealed_evaluation_access_count": 0,
                "prediction_metrics_access_count": 0,
                "claim_boundary": "open development only",
                "code_contracts": {"runner": {"node1_path": str(artifact), "sha256": digest}},
                "canonical_inputs": {name: {"node1_path": str(artifact), "sha256": digest}
                    for name in ("training_tsv", "outer_manifest", "inner_manifest", "contact_formula")},
                "split_manifests": {"one": {"node1_path": str(artifact), "sha256": digest}},
                "jobs": [
                    {"job_id": "first", "kind": "CPU_TEST", "dependencies": [],
                     "expected_result": str(first), "command": [sys.executable, "-c", f"from pathlib import Path; Path({str(first)!r}).write_text('1')"]},
                    {"job_id": "second", "kind": "CPU_TEST", "dependencies": ["first"],
                     "expected_result": str(second), "command": [sys.executable, "-c", f"from pathlib import Path; assert Path({str(first)!r}).is_file(); Path({str(second)!r}).write_text('2')"]},
                ],
            }
            graph_path = root / "graph.json"; graph_path.write_text(json.dumps(graph))
            loaded = mod.load_graph(graph_path)
            result = mod.execute(loaded, mod.AUTHORIZATION, root / "logs", 2)
            self.assertEqual(result["completed_job_count"], 2)
            self.assertEqual(result["newly_executed_job_count"], 2)
            self.assertTrue(first.is_file() and second.is_file())


if __name__ == "__main__":
    unittest.main()
