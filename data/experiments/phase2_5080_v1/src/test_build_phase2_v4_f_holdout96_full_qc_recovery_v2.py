#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); assert spec.loader
    spec.loader.exec_module(module)
    return module


B = load("v4f_builder", HERE / "build_phase2_v4_f_holdout96_full_qc_recovery_v2.py")
R = load("v4f_runner", HERE / "run_phase2_v4_f_holdout96_full_qc_recovery_v2_node1.py")


class V4FFullQCRecoveryV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v4f96_fullqc_v2_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def build(self) -> Path:
        output = self.tmp / "package"
        B.build(output, self.tmp / "freeze.json")
        return output

    def test_frozen_sources_exact_96(self):
        rows, hashes = B.validate_sources()
        self.assertEqual(len(rows), 96)
        self.assertEqual(hashes["manifest"], B.EXPECTED["manifest"])
        self.assertEqual({row["model_split"] for row in rows}, {"PROSPECTIVE_V4_F_COMPUTATIONAL_HOLDOUT"})

    def test_build_and_validate_package(self):
        output = self.build()
        result = B.validate_package(output)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["candidate_count"], 96)

    def test_packaged_runner_input_contract_and_zero_work_preflight(self):
        output = self.build()
        rows = R.validate_input_contract(output)
        self.assertEqual(len(rows), 96)
        result = R.preflight(output, verify_runtime=False)
        self.assertEqual(result["status"], "PASS_ZERO_WORK_PREFLIGHT")
        self.assertTrue(all(value == 0 for value in result["label_path_access"].values()))

    def test_source_mutation_fails_closed(self):
        manifest = self.tmp / "manifest.tsv"
        audit = self.tmp / "audit.json"
        receipt = self.tmp / "receipt.json"
        prereg = self.tmp / "prereg.json"
        for source, target in ((B.DEFAULT_MANIFEST, manifest), (B.DEFAULT_AUDIT, audit), (B.DEFAULT_RECEIPT, receipt), (B.DEFAULT_PREREG, prereg)):
            shutil.copyfile(source, target)
        manifest.write_bytes(manifest.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "frozen_source_hash_mismatch"):
            B.validate_sources(manifest, audit, receipt, prereg)

    def test_package_tamper_fails_closed(self):
        output = self.build()
        (output / "inputs/holdout96.fasta").write_text("tamper\n")
        with self.assertRaisesRegex(RuntimeError, "package_hash_mismatch"):
            B.validate_package(output)

    def test_package_extra_file_fails_closed(self):
        output = self.build(); (output / "extra.txt").write_text("x")
        with self.assertRaisesRegex(RuntimeError, "package_file_closure"):
            B.validate_package(output)

    def test_prereg_mutation_fails_runner_contract(self):
        output = self.build()
        (output / B.DEFAULT_PREREG.name).write_bytes((output / B.DEFAULT_PREREG.name).read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "frozen_input_hash_or_type_mismatch:prereg"):
            R.validate_input_contract(output)

    def test_waiter_smoke_and_resource_gate(self):
        output = self.build(); waiter = output / "wait_for_support_v4a720_structures_then_run_full_qc.sh"
        payload = json.loads(subprocess.check_output(["bash", str(waiter), "--smoke-test"], text=True))
        self.assertEqual(payload["maximum_cpu_workers"], 24)
        self.assertEqual(payload["gpu"], 0)
        text = waiter.read_text()
        for token in ("structures.complete.json", "structure_processes_dead", "MAX_LOAD1=8.0", "taskset -c 0-23", "--preflight"):
            self.assertIn(token, text)

    def test_runner_command_has_all_survivors_no_model_input(self):
        command = R.screen_command("full")
        self.assertEqual(command[command.index("--full-qc-limit") + 1], "0")
        self.assertNotIn("--binder-summary", command)
        self.assertEqual(R.RESOURCE_POLICY["maximum_requested_cpu_workers"], 24)
        self.assertEqual(R.RESOURCE_POLICY["gpu_requested"], 0)

    def test_clean_env_disables_cuda_and_nfs(self):
        env = R.clean_env()
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "")
        self.assertNotIn("/data/qlyu", env["PATH"])
        self.assertNotIn("/data/qlyu", env["PYTHONPATH"])

    def test_terminal_closure_publishes_explicit_tnp_unrun_states(self):
        cascade, outputs = self.tmp / "cascade", self.tmp / "outputs"
        cascade.mkdir(); outputs.mkdir()
        rows = B.validate_sources()[0]
        fail_ids = {row["candidate_id"] for row in rows[:6]}
        fast = [{"candidate_id": row["candidate_id"], "hard_fail": "true" if row["candidate_id"] in fail_ids else "false"} for row in rows]
        full = [row for row in fast if row["hard_fail"] == "false"]
        def write(path: Path, data: list[dict[str, str]]):
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["candidate_id", "hard_fail"], delimiter="\t", lineterminator="\n")
                writer.writeheader(); writer.writerows(data)
        write(cascade / "fast_merged.tsv", fast)
        write(cascade / "full_qc_shortlist.tsv", full)
        write(cascade / "full_merged.tsv", full)
        (cascade / "full_qc_excluded_due_cap.tsv").write_text("")
        (cascade / "cascade_state.json").write_text(json.dumps({"stages": {stage: {"status": "complete"} for stage in ("prepare", "fast", "merge_fast", "full", "merge_full")}}))
        for base, count in (("fast_chunks", 8), ("full_chunks", 8)):
            for index in range(count):
                path = cascade / base / f"chunk_{index+1:06d}"; path.mkdir(parents=True); (path / "complete.json").write_text("{}")
        old_cascade, old_outputs = R.CASCADE, R.OUTPUTS
        try:
            R.CASCADE, R.OUTPUTS = cascade, outputs
            summary = R.validate_and_publish_terminal(rows)
        finally:
            R.CASCADE, R.OUTPUTS = old_cascade, old_outputs
        self.assertEqual(summary["tnp_state_counts"], {"DEFERRED_UNRUN": 90, "UPSTREAM_FAST_HARD_FAIL_NA": 6})
        self.assertEqual(summary["tnp_numeric_or_flag_nonblank"], 0)
        with (outputs / "tnp_three_state_unrun_summary.tsv").open(newline="") as handle:
            tnp = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(tnp), 96)
        self.assertTrue(all(not row["tnp_score"] and not row["tnp_flag"] for row in tnp))

    def test_package_contains_no_result_or_label_artifacts(self):
        output = self.build()
        rels = {str(path.relative_to(output)) for path in output.rglob("*") if path.is_file()}
        self.assertFalse(any(name.endswith((".pdb", ".pt", ".npy", ".npz")) for name in rels))
        self.assertFalse(any("full_merged" in name or "prediction" in name or "docking" in name for name in rels))


if __name__ == "__main__": unittest.main(verbosity=2)
