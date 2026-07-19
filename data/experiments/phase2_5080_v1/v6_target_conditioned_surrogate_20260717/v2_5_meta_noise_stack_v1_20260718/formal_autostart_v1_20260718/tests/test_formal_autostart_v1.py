#!/usr/bin/env python3

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from watch_input_closure_then_authorize_and_evaluate_v1 import sha256_file


TOKEN = "SYNTHETIC_AUTHORIZATION_TOKEN"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_tsv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("candidate_id\tvalue\nC0\t1\n")


class FullFixture:
    def __init__(self, root: Path):
        self.package = root / "package"; self.output = root / "output"
        self.runtime = root / "runtime"; self.inputs = root / "inputs"
        for path in (self.package, self.runtime, self.inputs): path.mkdir(parents=True)
        names = ["labels", "outer_manifest", "inner_manifest", "coarse_pose_raw36", "existing_c2_outer_oof", "existing_c2_alpha_selection"]
        canonical = {}
        for name in names:
            filename = f"{name}.tsv"; write_tsv(self.inputs / filename)
            canonical[name] = {"filename": filename, "sha256": sha256_file(self.inputs / filename)}
        upstream = {
            "job_graph_sha256": "a" * 64, "package_manifest_sha256": "b" * 64,
            "authorization_overlay_sha256": "c" * 64, "launch_receipt_sha256": "d" * 64,
        }
        self.contract = self.package / "contract.json"
        write_json(self.contract, {
            "status": "FROZEN_DESIGN_UNAUTHORIZED_DO_NOT_EVALUATE",
            "canonical_inputs": canonical, "upstream_v2_4_strict": upstream,
            "authorization": {"required_token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()},
        })
        self.evaluator = self.package / "evaluator.py"; self.evaluator.write_text("# frozen dummy\n")
        self.adapter_freeze = self.package / "adapter_freeze.json"; write_json(self.adapter_freeze, {"status": "frozen"})
        self.manifest = self.package / "manifest.json"
        write_json(self.manifest, {
            "status": "FROZEN_UNAUTHORIZED_INPUT_VALIDATION_ONLY", "execution_authorized": False,
            "formal_evaluator_launch_allowed": False,
            "contract": {"sha256": sha256_file(self.contract)}, "code": {},
        })
        self.intent = self.package / "EXPLICIT_AUTHORIZATION_INTENT_V1.json"
        write_json(self.intent, {
            "status": "EXPLICITLY_AUTHORIZED_PENDING_PASS_INPUT_CLOSURE", "execution_authorized": True,
            "authorization_token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
            "bound_execution_manifest_sha256": sha256_file(self.manifest),
            "bound_execution_adapter_freeze_sha256": sha256_file(self.adapter_freeze),
            "bound_execution_contract_sha256": sha256_file(self.contract),
            "bound_formal_evaluator_sha256": sha256_file(self.evaluator),
            "required_input_closure_status": "PASS_INPUTS_READY_UNAUTHORIZED",
            "required_job_result_closure": 195, "required_allowed_predictor_lane": "D_SPLIT_PAIR",
            "required_forbidden_lane_predictor_read_count": 0, "required_candidates": 1507,
            "required_outer_folds": 5, "required_v4_f_test32_access_count": 0,
            "claim_boundary": "synthetic",
        })
        fold_evidence = {}
        for fold in range(5):
            eroot = self.runtime / "evidence/D_SPLIT_PAIR" / f"outer_{fold}"
            fold_evidence[str(fold)] = {}
            for role, names in {
                "inner": ("inner_oof_base.tsv", "inner_oof_base.validation.json", "inner_oof_provenance.json"),
                "outer": ("outer_test_base.tsv", "outer_test_base.validation.json", "outer_test_provenance.json"),
            }.items():
                for name in names:
                    p = eroot / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(f"{fold}:{role}:{name}\n")
                fold_evidence[str(fold)][role] = {
                    "evidence_sha256": sha256_file(eroot / names[0]),
                    "validation_sha256": sha256_file(eroot / names[1]),
                    "provenance_sha256": sha256_file(eroot / names[2]),
                    "exact_min_violations": 0,
                }
        self.closure = self.package / "INPUT_CLOSURE_RECEIPT.json"
        write_json(self.closure, {
            "status": "PASS_INPUTS_READY_UNAUTHORIZED", "execution_authorized": False,
            "formal_evaluator_launched": False, "performance_evaluation_performed": False,
            "contract_sha256": sha256_file(self.contract), "expected_job_count": 195,
            "closed_job_result_count": 195, "all_lane_graph_result_hash_closure": True,
            "allowed_lane_read": "D_SPLIT_PAIR", "forbidden_lane_predictor_read_count": 0,
            "input_hashes": {name: value["sha256"] for name, value in canonical.items()},
            "upstream_binding_hashes": {
                "job_graph": upstream["job_graph_sha256"], "package_manifest": upstream["package_manifest_sha256"],
                "upstream_authorization_overlay": upstream["authorization_overlay_sha256"],
                "launch_receipt": upstream["launch_receipt_sha256"],
            },
            "c2_outer_oof_closure": {
                "candidate_count": 1507, "candidate_scored_exactly_once": True,
                "exact_min_violations": 0, "v4_f_test32_access_count": 0,
                "outer_fold_counts": {str(i): 1 for i in range(5)},
            },
            "fold_evidence": fold_evidence, "v4_f_test32_access_count": 0,
        })
        self.runner = self.package / "fake_runner.py"
        self.runner.write_text('''#!/usr/bin/env python3
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser()
for name in ("evaluator","expected-evaluator-sha256","execution-manifest","input-closure-receipt","authorization-overlay","contract","input-root","runtime-root","output-dir"):
 p.add_argument("--"+name,required=True)
a=p.parse_args(); out=Path(a.output_dir); out.mkdir(parents=True)
arts={}
for name in ("FORMAL_OUTER_OOF_PREDICTIONS.tsv","FORMAL_METRICS.json","FORMAL_PARAMETERS.json"):
 q=out/name; q.write_text(name+"\\n"); arts[name]=hashlib.sha256(q.read_bytes()).hexdigest()
overlay=hashlib.sha256(Path(a.authorization_overlay).read_bytes()).hexdigest()
(out/"FORMAL_EXECUTION_RECEIPT.json").write_text(json.dumps({"status":"PASS_FORMAL_EVALUATION_COMPLETED","execution_authorized":True,"authorization_overlay_sha256":overlay,"artifacts":arts,"v4_f_test32_access_count":0},sort_keys=True)+"\\n")
''')
        self.freeze = self.package / "IMPLEMENTATION_FREEZE_V1.json"
        write_json(self.freeze, {
            "status": "FROZEN_EXPLICIT_AUTHORIZATION_AUTOSTART_V1",
            "artifact_hashes": {"EXPLICIT_AUTHORIZATION_INTENT_V1.json": sha256_file(self.intent)},
        })


class FormalAutostartTests(unittest.TestCase):
    def test_full_watcher_waits_child_and_writes_pass_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = FullFixture(Path(tmp))
            env = dict(os.environ); env["PVRIG_V2_5_AUTH_TOKEN"] = TOKEN
            result = subprocess.run([
                sys.executable, str(SRC / "watch_input_closure_then_authorize_and_evaluate_v1.py"),
                "--package-root", str(fixture.package), "--freeze", str(fixture.freeze),
                "--expected-freeze-sha256", sha256_file(fixture.freeze),
                "--intent", str(fixture.intent), "--manifest", str(fixture.manifest),
                "--adapter-freeze", str(fixture.adapter_freeze), "--contract", str(fixture.contract),
                "--input-closure", str(fixture.closure), "--runtime-root", str(fixture.runtime),
                "--input-root", str(fixture.inputs), "--evaluator", str(fixture.evaluator),
                "--runner", str(fixture.runner), "--python", sys.executable,
                "--output-root", str(fixture.output), "--poll-seconds", "0", "--max-polls", "1",
            ], env=env, check=False)
            self.assertEqual(result.returncode, 0)
            terminal = json.loads((fixture.output / "TERMINAL.json").read_text())
            self.assertEqual(terminal["status"], "PASS")
            self.assertTrue(terminal["formal_evaluator_terminal"])
            status = json.loads((fixture.output / "WATCHER_STATUS.json").read_text())
            self.assertEqual(status["status"], "PASS_FORMAL_EVALUATOR_CHILD_TERMINAL")
            overlay = json.loads((fixture.output / "authorization/EXPLICIT_AUTHORIZATION_OVERLAY_V1.json").read_text())
            self.assertEqual(overlay["input_closure_receipt_sha256"], sha256_file(fixture.closure))

    def test_v4f_access_fails_closed_before_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = FullFixture(Path(tmp))
            closure = json.loads(fixture.closure.read_text()); closure["v4_f_test32_access_count"] = 1
            write_json(fixture.closure, closure)
            env = dict(os.environ); env["PVRIG_V2_5_AUTH_TOKEN"] = TOKEN
            result = subprocess.run([
                sys.executable, str(SRC / "watch_input_closure_then_authorize_and_evaluate_v1.py"),
                "--package-root", str(fixture.package), "--freeze", str(fixture.freeze),
                "--expected-freeze-sha256", sha256_file(fixture.freeze), "--intent", str(fixture.intent),
                "--manifest", str(fixture.manifest), "--adapter-freeze", str(fixture.adapter_freeze),
                "--contract", str(fixture.contract), "--input-closure", str(fixture.closure),
                "--runtime-root", str(fixture.runtime), "--input-root", str(fixture.inputs),
                "--evaluator", str(fixture.evaluator), "--runner", str(fixture.runner),
                "--python", sys.executable, "--output-root", str(fixture.output),
            ], env=env, check=False)
            self.assertEqual(result.returncode, 1)
            terminal = json.loads((fixture.output / "TERMINAL.json").read_text())
            self.assertEqual(terminal["status"], "FAIL")
            self.assertIn("protected_access_nonzero", terminal["error"])
            self.assertFalse((fixture.output / "formal_output").exists())

    def test_env_wrapper_does_not_require_token_on_command_line(self):
        source = (SRC / "run_frozen_evaluator_from_env_v1.py").read_text()
        self.assertIn('os.environ.pop("PVRIG_V2_5_AUTH_TOKEN"', source)
        launcher = (SRC / "launch_formal_autostart_watcher_v1.py").read_text()
        self.assertNotIn("--authorization-token", launcher)
        watcher = (SRC / "watch_input_closure_then_authorize_and_evaluate_v1.py").read_text()
        self.assertIn("returncode = child.wait()", watcher)
        self.assertIn('"formal_evaluator_terminal": True', watcher)

    def test_launcher_strips_remainder_separator_and_persists_no_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); package = root / "package"; package.mkdir()
            write_json(package / "EXPLICIT_AUTHORIZATION_INTENT_V1.json", {
                "authorization_token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
            })
            freeze = package / "freeze.json"; write_json(freeze, {"status": "frozen"})
            watcher = package / "watcher.py"; watcher.write_text("import sys\n")
            output = root / "output"
            env = dict(os.environ); env["PVRIG_V2_5_AUTH_TOKEN"] = TOKEN
            result = subprocess.run([
                sys.executable, str(SRC / "launch_formal_autostart_watcher_v1.py"),
                "--package-root", str(package), "--freeze", str(freeze),
                "--expected-freeze-sha256", sha256_file(freeze),
                "--watcher", str(watcher), "--expected-watcher-sha256", sha256_file(watcher),
                "--python", sys.executable, "--output-root", str(output),
                "--", "--intent", "dummy",
            ], env=env, check=False)
            self.assertEqual(result.returncode, 0)
            receipt = json.loads((output / "AUTOSTART_DEPLOYMENT_RECEIPT.json").read_text())
            self.assertNotIn("--", receipt["command"])
            self.assertIn("--intent", receipt["command"])
            self.assertFalse(receipt["runtime_token_persisted"])


if __name__ == "__main__":
    unittest.main()
