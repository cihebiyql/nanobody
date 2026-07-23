from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent
DATA = ROOT.parents[3]
PACKAGE = BASE / "v2_20_contact_shared_top5_challenger_v1_3_5_technical_recovery_20260723"
APPROVAL = DATA / "reports/pvrig_v220_v135_python311_bxcpu_tests_v1_20260723/INDEPENDENT_STAGE_A_APPROVAL_V1_3_5.json"
MONITOR = ROOT / "monitor_and_launch_stage_a_v2.sh"
START = ROOT / "start_node1_stage_a_watcher_v2.sh"
ENTRY = ROOT / "remote_stage_a_entrypoint_v2.sh"
VERIFY = ROOT / "verify_frozen_package_v2.py"
PROBE = ROOT / "probe_node1_stage_a_state_v2.py"
CLASSIFIER = ROOT / "classify_node1_stage_a_state_v2.py"
SESSION_VALIDATOR = ROOT / "validate_node1_stage_a_session_v2.py"
PROVE = ROOT / "prove_remote_stage_a_artifacts_v2.py"
VALIDATOR = ROOT / "validate_node1_stage_a_receipt_v2.py"
SUPERSESSION = ROOT / "V1_WATCHER_REJECTION_AND_V2_SUPERSESSION.json"
FREEZE_SHA = "07c8463689d6baa0da1ebd0c1d4440fc0315c8e8edb4e1b72415434567dc0804"
PREREG_SHA = "574919e65f7079475c17294e297327ce311910ced12656e34640e1fa4a5b9562"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CLASSIFY_MODULE = load_module(CLASSIFIER, "classify_stage_a_v2")
SESSION_MODULE = load_module(SESSION_VALIDATOR, "validate_session_v2")


def receipt_payload() -> dict:
    folds = {}
    for fold in range(5):
        folds[str(fold)] = {
            "materialization_terminal_sha256": hashlib.sha256(f"terminal-{fold}".encode()).hexdigest(),
            "shared_calibration_sha256": hashlib.sha256(f"shared-{fold}".encode()).hexdigest(),
            "load_only_receipt_sha256": hashlib.sha256(f"load-{fold}".encode()).hexdigest(),
            "calibrator_invocations": 1,
            "same_bytes_for_both_arms": True,
            "optimizer_created": False,
            "optimizer_steps": 0,
            "backward_called": False,
            "training_started": False,
            "run_fold_core_called": False,
            "training_output_created": False,
        }
    return {
        "schema_version": "pvrig.v220.v1_3_5_node1_preflight_receipt.v1",
        "status": "PASS_NODE1_V220_V1_3_5_FIVE_FOLD_SHARED_CALIBRATION_LOAD_ONLY_NO_TRAINING",
        "implementation_freeze": {"sha256": FREEZE_SHA},
        "preregistration": {"sha256": PREREG_SHA},
        "tests": {
            "combined_tests_run": 148,
            "legacy": {"tests_run": 102, "ok": True, "python_version": "Python 3.11.14"},
            "v1_3_5": {"tests_run": 46, "ok": True},
        },
        "fold_count": 5,
        "calibrator_invocations_total": 5,
        "optimizer_created": False,
        "optimizer_steps": 0,
        "backward_called": False,
        "training_started": False,
        "run_fold_core_called": False,
        "training_output_created": False,
        "training_sentinel_exists": False,
        "folds": folds,
    }


def write_receipt_triple(root: Path) -> tuple[Path, Path, Path]:
    receipt = root / "NODE1_V1_3_5_PREFLIGHT_RECEIPT.json"
    raw = (json.dumps(receipt_payload(), indent=2, sort_keys=True) + "\n").encode()
    receipt.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    sidecar = root / f"{receipt.name}.sha256"
    sidecar.write_text(f"{digest}  {receipt.name}\n")
    content = root / f"{receipt.stem}.{digest}.json"
    content.write_bytes(raw)
    return receipt, sidecar, content


class WatcherV2Tests(unittest.TestCase):
    def test_shell_syntax(self):
        for path in (MONITOR, START, ENTRY):
            subprocess.run(["bash", "-n", str(path)], check=True)

    def test_exact_local_bindings_and_frozen_package(self):
        self.assertEqual(hashlib.sha256((PACKAGE / "IMPLEMENTATION_FREEZE_PHASE1_TECHNICAL_RECOVERY_V1_3_5.json").read_bytes()).hexdigest(), FREEZE_SHA)
        self.assertEqual(hashlib.sha256(APPROVAL.read_bytes()).hexdigest(), "91fc04f0cbe2441c76318eac20ba0f41b8525eca1a27bd24465a0963613c97c8")
        completed = subprocess.run([
            "python3", str(VERIFY), "--package-root", str(PACKAGE),
            "--expected-freeze-sha256", FREEZE_SHA,
            "--approval", str(APPROVAL),
            "--expected-approval-sha256", "91fc04f0cbe2441c76318eac20ba0f41b8525eca1a27bd24465a0963613c97c8",
            "--expected-preregistration-sha256", PREREG_SHA,
        ], check=True, text=True, capture_output=True)
        self.assertEqual(json.loads(completed.stdout)["status"], "PASS_STAGE_A_LOCAL_OR_REMOTE_IDENTITY_GATE")

    def test_monitor_local_preflight_makes_no_ssh_action(self):
        environment = dict(os.environ)
        environment["WATCHER_LOCAL_PREFLIGHT_ONLY"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        subprocess.run(["bash", str(MONITOR)], check=True, env=environment, timeout=20)
        status = json.loads((ROOT / "runtime/WATCHER_STATUS.json").read_text())
        self.assertEqual(status["status"], "PASS_LOCAL_PREFLIGHT_ONLY")
        self.assertFalse(status["training_authorized"])
        self.assertFalse(status["training_started"])
        self.assertTrue((ROOT / "runtime/FROZEN_PACKAGE.tar").is_file())

    def test_remote_paths_session_and_atomic_adoption_are_fixed(self):
        text = MONITOR.read_text()
        for expected in (
            "/data1/qlyu/projects/pvrig_v2_20_phase1_core_oof_v1_3_5_technical_recovery_watcher_v2_20260723",
            "/data1/qlyu/projects/pvrig_v2_20_phase1_core_oof_v1_3_5_preflight_runtime_v2_20260723",
            "/data1/qlyu/projects/pvrig_v2_20_phase1_core_oof_v1_3_5_stage_a_evidence_v2_20260723",
            'REMOTE_SESSION="v220_v135_stagea_preflight_v2"',
            "ADOPTING_READY_ARCHIVE", "ADOPTING_ATOMIC_STAGE", "RUNNING_NODE1_STAGE_A_PREFLIGHT",
            "mv '$REMOTE_STAGE' '$REMOTE_PACKAGE'", "RECONCILING_AFTER_LAUNCH_CONNECTION_BOUNDARY",
        ):
            self.assertIn(expected, text)

    def test_stage_a_only_no_training_or_scheduler_launch(self):
        monitor = MONITOR.read_text()
        entry = ENTRY.read_text()
        self.assertIn("run_phase1_preflight_node1_v1_3_5.sh", entry)
        for forbidden in (
            "run_phase1_core_fold_pair_node1_v1_3_5.template.sh",
            "finalize_v220_v1_3_5_training_authorization.py",
            "sbatch",
        ):
            self.assertNotIn(forbidden, monitor)
            self.assertNotIn(forbidden, entry)
        self.assertIn('"training_authorized":False', monitor)
        self.assertIn('"training_started":False', monitor)

    def test_start_uses_unique_v2_tmux(self):
        text = START.read_text()
        self.assertIn('SESSION="pvrig-v220-v135-node1-stagea-v2"', text)
        self.assertIn("monitor_and_launch_stage_a_v2.sh", text)
        self.assertIn('tmux new-session -d -s "$SESSION"', text)

    def test_state_machine_recovery_and_fail_closed(self):
        base = {
            "package": "absent", "stage": "absent", "ready_archive": "absent",
            "partial_archive": "absent", "runtime": "absent", "evidence": "absent",
            "rc": "absent", "rc_value": None, "session": False,
        }
        cases = [
            ({}, "CLEAN"),
            ({"ready_archive": "file"}, "ARCHIVE_READY"),
            ({"stage": "directory"}, "STAGED_PACKAGE"),
            ({"package": "directory"}, "READY"),
            ({"package": "directory", "session": True}, "RUNNING"),
            ({"package": "directory", "runtime": "directory", "evidence": "directory", "rc": "file", "rc_value": "0"}, "TERMINAL"),
            ({"package": "directory", "stage": "directory"}, "AMBIGUOUS_FINAL_AND_STAGE"),
            ({"runtime": "directory"}, "AMBIGUOUS_EXECUTION_WITHOUT_PACKAGE"),
            ({"package": "directory", "evidence": "directory"}, "AMBIGUOUS_PARTIAL_EXECUTION_NO_RC"),
            ({"package": "directory", "evidence": "directory", "rc": "file", "rc_value": "0"}, "AMBIGUOUS_SUCCESS_WITHOUT_RUNTIME"),
            ({"package": "symlink"}, "AMBIGUOUS_INVALID_TYPE_PACKAGE"),
        ]
        for delta, expected in cases:
            snapshot = dict(base); snapshot.update(delta)
            self.assertEqual(CLASSIFY_MODULE.classify(snapshot), expected, delta)

    def test_running_session_is_bound_to_exact_entry_command(self):
        entry = "/data1/qlyu/projects/.entry.sh"
        runtime = "/data1/qlyu/projects/runtime"
        package = "/data1/qlyu/projects/package"
        evidence = "/data1/qlyu/projects/evidence"
        freeze_name = "FREEZE.json"
        command = f'"/bin/bash \'{entry}\' \'{runtime}\' \'{package}\' \'{evidence}\' \'{freeze_name}\' \'{FREEZE_SHA}\' \'3\'"'
        self.assertEqual(SESSION_MODULE.validate(
            {"session": True, "session_command": command}, entry, runtime, package,
            evidence, freeze_name, FREEZE_SHA,
        ), 3)
        with self.assertRaises(RuntimeError):
            SESSION_MODULE.validate(
                {"session": True, "session_command": command.replace("package", "other")},
                entry, runtime, package, evidence, freeze_name, FREEZE_SHA,
            )

    def test_valid_receipt_remote_proof_and_local_validator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); runtime = root / "runtime"; evidence = root / "evidence"
            runtime.mkdir(); evidence.mkdir()
            receipt, sidecar, content = write_receipt_triple(runtime)
            (evidence / "PREFLIGHT_LAUNCHER.rc").write_text("0\n")
            (evidence / "PREFLIGHT_LAUNCHER.log").write_text("terminal\n")
            proof = subprocess.run([
                "python3", str(PROVE), "--runtime", str(runtime), "--evidence", str(evidence),
            ], check=True, text=True, capture_output=True)
            self.assertEqual(json.loads(proof.stdout)["status"], "PASS_REMOTE_REGULAR_NONSYMLINK_STAGE_A_ARTIFACTS")
            output = root / "validated.json"
            subprocess.run([
                "python3", str(VALIDATOR), "--receipt", str(receipt), "--sidecar", str(sidecar),
                "--content-copy", str(content), "--expected-freeze-sha256", FREEZE_SHA,
                "--expected-preregistration-sha256", PREREG_SHA, "--output", str(output),
            ], check=True)
            self.assertEqual(json.loads(output.read_text())["status"], "PASS_VALIDATED_NODE1_STAGE_A_RECEIPT_NO_TRAINING")

    def test_receipt_mutations_and_symlinks_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); runtime = root / "runtime"; evidence = root / "evidence"
            runtime.mkdir(); evidence.mkdir()
            receipt, sidecar, content = write_receipt_triple(runtime)
            (evidence / "PREFLIGHT_LAUNCHER.rc").write_text("0\n")
            (evidence / "PREFLIGHT_LAUNCHER.log").write_text("terminal\n")
            sidecar.write_text("0" * 64 + f"  {receipt.name}\n")
            failed = subprocess.run([
                "python3", str(VALIDATOR), "--receipt", str(receipt), "--sidecar", str(sidecar),
                "--content-copy", str(content), "--expected-freeze-sha256", FREEZE_SHA,
                "--expected-preregistration-sha256", PREREG_SHA, "--output", str(root / "bad.json"),
            ], text=True, capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            sidecar.unlink(); sidecar.symlink_to(receipt)
            failed = subprocess.run([
                "python3", str(PROVE), "--runtime", str(runtime), "--evidence", str(evidence),
            ], text=True, capture_output=True)
            self.assertNotEqual(failed.returncode, 0)

    def test_supersession_record_rejects_v1(self):
        value = json.loads(SUPERSESSION.read_text())
        self.assertEqual(value["status"], "REJECT_V1_WATCHER_SUPERSEDED_BY_V2_BEFORE_REMOTE_ACTION")
        self.assertFalse(value["v1_remote_action_started"])
        self.assertFalse(value["training_authorized"])
        self.assertFalse(value["training_started"])
        self.assertEqual(value["v1_monitor_sha256"], "6c93cc4ef8a3edfe917cbd969944df92698c4e21627c73f2e14ce9513d7acb4c")


if __name__ == "__main__":
    unittest.main()
