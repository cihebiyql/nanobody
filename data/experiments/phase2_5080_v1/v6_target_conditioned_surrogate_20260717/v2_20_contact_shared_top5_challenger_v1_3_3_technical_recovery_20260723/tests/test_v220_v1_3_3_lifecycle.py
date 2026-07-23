from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MATERIALIZER = load("v131_materializer_test", "src/materialize_v220_shared_fold_calibration_v1_3_1.py")
LOAD_ONLY = load("v131_load_only_test", "src/validate_v220_shared_fold_calibration_load_only_v1_3_1.py")
PREFLIGHT = load("v131_preflight_test", "src/build_v220_v1_3_3_preflight_receipt.py")
FINALIZER = load("v131_finalizer_test", "src/finalize_v220_v1_3_3_training_authorization.py")
HELPER = ROOT / "launchers/run_shared_fold_materialization_once_v1_3_1.sh"
TEMPLATE = ROOT / "launchers/run_phase1_core_fold_pair_node1_v1_3_3.template.sh"
PREREG = ROOT / "PREREGISTRATION_PHASE1_TECHNICAL_RECOVERY_V1_3_3.json"
LEGACY_ADAPTER = ROOT / "launchers/run_legacy_102_tests_python311_v1_3_3.sh"
FREEZE_NAME = "IMPLEMENTATION_FREEZE_PHASE1_TECHNICAL_RECOVERY_V1_3_3.json"
FREEZE_SIDECAR_NAME = FREEZE_NAME + ".sha256"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return sha(path)


@contextmanager
def temporary_environment(**updates):
    old = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class AtomicHelperRuntimeTests(unittest.TestCase):
    def run_helper(self, shared: Path, command: list[str]):
        return subprocess.run([str(HELPER), str(shared), "--", *command], text=True, capture_output=True)

    def test_real_runtime_creates_directory_before_redirection_and_exports_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory) / "missing" / "shared_calibration" / "fold_0"
            code = (
                "import json,os; print(json.dumps({'status':'PASS_SMOKE','lock_dir':os.environ.get('V220_V131_EXACT_ONCE_LOCK_DIR'),"
                "'token':os.environ.get('V220_V131_EXACT_ONCE_LOCK_TOKEN'),'helper':os.environ.get('V220_V131_EXACT_ONCE_HELPER_SHA256')}))"
            )
            result = self.run_helper(shared, ["python3", "-c", code])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((shared / "MATERIALIZATION_TERMINAL.json").is_file())
            self.assertTrue((shared / "MATERIALIZATION_STDERR.log").is_file())
            self.assertEqual((shared / "MATERIALIZATION_COMMAND.rc").read_text().strip(), "0")
            lock = json.loads((shared / "EXACT_ONCE_LOCK.json").read_text())
            terminal = json.loads((shared / "MATERIALIZATION_TERMINAL.json").read_text())
            self.assertEqual(terminal["status"], "PASS_SMOKE")
            self.assertEqual(terminal["lock_dir"], str(shared.resolve()))
            self.assertEqual(terminal["token"], lock["token"])
            self.assertEqual(terminal["helper"], sha(HELPER))

    def test_sequential_second_launch_fails_before_second_materializer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); shared = root / "shared_calibration/fold_0"; counter = root / "counter"
            command = ["bash", "-c", 'echo x >> "$1"; printf "{}\\n"', "_", str(counter)]
            first = self.run_helper(shared, command)
            second = self.run_helper(shared, command)
            self.assertEqual(first.returncode, 0)
            self.assertEqual(second.returncode, 73)
            self.assertEqual(counter.read_text().splitlines(), ["x"])

    def test_concurrent_same_fold_has_one_zero_one_73_and_one_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); shared = root / "shared_calibration/fold_1"; counter = root / "counter"
            command = ["bash", "-c", 'echo x >> "$1"; sleep 0.3; printf "{}\\n"', "_", str(counter)]
            argv = [str(HELPER), str(shared), "--", *command]
            one = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            two = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            one.communicate(); two.communicate()
            rcs = [one.returncode, two.returncode]
            self.assertEqual(sorted(rcs), [0, 73])
            self.assertEqual(counter.read_text().splitlines(), ["x"])

    def test_failed_materializer_leaves_lock_and_cannot_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); shared = root / "shared_calibration/fold_2"; counter = root / "counter"
            fail = ["bash", "-c", 'echo x >> "$1"; exit 7', "_", str(counter)]
            self.assertEqual(self.run_helper(shared, fail).returncode, 7)
            self.assertTrue(shared.is_dir())
            self.assertEqual(self.run_helper(shared, fail).returncode, 73)
            self.assertEqual(counter.read_text().splitlines(), ["x"])


class MaterializerLockBindingTests(unittest.TestCase):
    def fixture(self, root: Path, fold: int = 2):
        lock = root / "shared_calibration" / f"fold_{fold}"
        lock.mkdir(parents=True)
        token = "a" * 64
        write_json(lock / "EXACT_ONCE_LOCK.json", {
            "schema_version": "pvrig.v220.v1_3_1.exact_once_lock.v1",
            "helper_sha256": sha(HELPER),
            "token": token,
        })
        args = argparse.Namespace(
            shared_lock_dir=lock,
            shared_calibration_artifact=lock / "CONTACT_WEIGHT_CALIBRATION.json",
            exact_once_helper=HELPER,
            expected_exact_once_helper_sha256=sha(HELPER),
        )
        env = {
            "V220_V131_EXACT_ONCE_LOCK_DIR": str(lock.resolve()),
            "V220_V131_EXACT_ONCE_LOCK_TOKEN": token,
            "V220_V131_EXACT_ONCE_HELPER_SHA256": sha(HELPER),
        }
        return lock, args, env

    def test_valid_helper_lock_binding_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            lock, args, env = self.fixture(Path(directory))
            with temporary_environment(**env):
                observed, helper_sha, receipt = MATERIALIZER.validate_exact_once_lock(args, 2)
            self.assertEqual(observed, lock.resolve())
            self.assertEqual(helper_sha, sha(HELPER))
            self.assertEqual(receipt.name, "EXACT_ONCE_LOCK.json")

    def test_direct_bypass_without_helper_environment_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            _, args, _ = self.fixture(Path(directory))
            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(Exception, "helper_environment_binding"):
                    MATERIALIZER.validate_exact_once_lock(args, 2)

    def test_artifact_outside_lock_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); _, args, env = self.fixture(root)
            outside = root / "other"; outside.mkdir()
            args.shared_calibration_artifact = outside / "CONTACT_WEIGHT_CALIBRATION.json"
            with temporary_environment(**env), self.assertRaisesRegex(Exception, "artifact_parent"):
                MATERIALIZER.validate_exact_once_lock(args, 2)

    def test_fold_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            _, args, env = self.fixture(Path(directory))
            with temporary_environment(**env), self.assertRaisesRegex(Exception, "lock_fold_binding"):
                MATERIALIZER.validate_exact_once_lock(args, 3)

    def test_upstream_sibling_hash_mismatch_fails_before_prepare(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); runner = root / "runner.py"; runner.write_text("x")
            for name in ("calibrate_v220_contact_weight_v1.py", "materialize_v220_paired_initial_state_v1.py", "v220_contact_teacher_store_v1.py"):
                (root / name).write_text(name)
            args = argparse.Namespace(
                upstream_v1_2_runner=runner,
                expected_calibrator_sha256="0" * 64,
                expected_paired_initial_state_sha256=sha(root / "materialize_v220_paired_initial_state_v1.py"),
                expected_contact_teacher_store_sha256=sha(root / "v220_contact_teacher_store_v1.py"),
            )
            with self.assertRaisesRegex(Exception, "upstream_sibling_sha256"):
                MATERIALIZER.validate_upstream_siblings(args)


class LoadOnlyIsolationTests(unittest.TestCase):
    def test_disjoint_paths_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            LOAD_ONLY.require_disjoint_output_paths(root / "forbidden/fold_0", root / "receipts/fold_0.json")

    def test_receipt_inside_training_output_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(Exception, "receipt_inside_training_output"):
                LOAD_ONLY.require_disjoint_output_paths(root / "training", root / "training/receipt.json")

    def test_training_output_inside_receipt_path_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(Exception, "training_output_inside_receipt_path"):
                LOAD_ONLY.require_disjoint_output_paths(root / "receipts/training", root / "receipts")

    def test_load_only_source_has_no_training_call_and_rechecks_after_write(self):
        source = (ROOT / "src/validate_v220_shared_fold_calibration_load_only_v1_3_1.py").read_text()
        self.assertNotIn("run_fold_core(", source)
        self.assertNotIn("build_optimizer(", source)
        self.assertNotIn(".backward(", source)
        self.assertIn("load_only_created_training_output_after_receipt", source)


class FiveFoldPreflightReceiptTests(unittest.TestCase):
    def test_five_fold_synthetic_separate_process_evidence_closes_no_training_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); runtime = root / "runtime"; runtime.mkdir()
            prereg = root / "prereg.json"; prereg.write_bytes(PREREG.read_bytes())
            freeze = root / "freeze.json"
            write_json(freeze, {
                "status": "FROZEN_V1_3_3_IMPLEMENTATION_PENDING_INDEPENDENT_REVIEW_AND_NODE1_PREFLIGHT",
                "training_started": False,
                "implementation_hashes": {"PREREGISTRATION_PHASE1_TECHNICAL_RECOVERY_V1_3_3.json": sha(prereg)},
            })
            legacy = root / "legacy.log"; legacy.write_text("Ran 102 tests in 1.0s\n\nOK\nPASS_LEGACY_102_PYTHON311_COMPATIBLE python=Python 3.11.14\n")
            new = root / "new.log"; new.write_text("Ran 17 tests in 0.1s\n\nOK\n")
            for fold in range(5):
                shared = runtime / "shared_calibration" / f"fold_{fold}"; shared.mkdir(parents=True)
                artifact = {"fold_id": fold, "seed": 43, "calibrator_invocations": 1, "optimizer_created": False, "optimizer_steps": 0, "backward_called": False, "training_started": False, "unique": fold}
                artifact_path = shared / "CONTACT_WEIGHT_CALIBRATION.json"; write_json(artifact_path, artifact); digest = sha(artifact_path)
                write_json(shared / "MATERIALIZATION_TERMINAL.json", {
                    "status": PREFLIGHT.MATERIALIZATION_STATUS, "fold_id": fold, "seed": 43,
                    "shared_calibration_sha256": digest, "calibrator_invocations": 1,
                    "optimizer_created": False, "optimizer_steps": 0, "backward_called": False, "training_started": False,
                })
                (shared / "MATERIALIZATION_COMMAND.rc").write_text("0\n")
                write_json(runtime / "load_only" / f"fold_{fold}.json", {
                    "status": PREFLIGHT.LOAD_ONLY_STATUS, "fold_id": fold, "seed": 43,
                    "loaded_arms": {arm: {"shared_artifact_sha256": digest} for arm in ("C0", "C1")},
                    "same_bytes_for_both_arms": True, "optimizer_created": False, "optimizer_steps": 0,
                    "backward_called": False, "training_started": False, "run_fold_core_called": False,
                    "training_output_created": False,
                })
            args = argparse.Namespace(
                runtime_root=runtime, training_sentinel=runtime / "training_output_forbidden",
                implementation_freeze=freeze, expected_implementation_freeze_sha256=sha(freeze),
                preregistration=prereg, legacy_test_log=legacy, v1_3_3_test_log=new,
                expected_new_tests=17, output_receipt=runtime / "NODE1_V1_3_3_PREFLIGHT_RECEIPT.json",
            )
            payload, digest = PREFLIGHT.build(args)
            self.assertEqual(payload["fold_count"], 5)
            self.assertEqual(payload["calibrator_invocations_total"], 5)
            self.assertFalse(payload["training_started"])
            self.assertEqual(sha(args.output_receipt), digest)


class FinalizationLifecycleTests(unittest.TestCase):
    def fixture(self, root: Path):
        package = root / "package"
        def ignore_production_freeze(directory: str, names: list[str]):
            if Path(directory).resolve() == ROOT.resolve():
                return {name for name in (FREEZE_NAME, FREEZE_SIDECAR_NAME) if name in names}
            return set()

        shutil.copytree(ROOT, package, symlinks=True, ignore=ignore_production_freeze)
        prereg = root / "prereg.json"; prereg.write_bytes(PREREG.read_bytes()); prereg_sha = sha(prereg)
        implementation = {
            path.relative_to(package).as_posix(): sha(path)
            for path in package.rglob("*")
            if path.is_file()
        }
        freeze = package / FREEZE_NAME
        sidecar = freeze.with_suffix(freeze.suffix + ".sha256")
        package_allowlist = sorted(
            [path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_file()]
            + [freeze.relative_to(package).as_posix(), sidecar.relative_to(package).as_posix()]
        )
        write_json(freeze, {"status": FINALIZER.FREEZE_STATUS, "training_authorized": False, "training_started": False, "implementation_hashes": implementation, "package_file_allowlist": sorted(package_allowlist)})
        freeze_sha = sha(freeze)
        sidecar.write_text(f"{freeze_sha}  {freeze.name}\n")
        folds = {str(i): {"calibrator_invocations": 1, "same_bytes_for_both_arms": True, "optimizer_created": False, "optimizer_steps": 0, "backward_called": False, "training_started": False, "run_fold_core_called": False, "training_output_created": False} for i in range(5)}
        preflight = root / "preflight.json"
        write_json(preflight, {
            "status": FINALIZER.PREFLIGHT_STATUS,
            "implementation_freeze": {"sha256": freeze_sha}, "preregistration": {"sha256": prereg_sha},
            "fold_count": 5, "calibrator_invocations_total": 5, "folds": folds,
            "optimizer_created": False, "optimizer_steps": 0, "backward_called": False,
            "training_started": False, "run_fold_core_called": False, "training_output_created": False,
            "training_sentinel_exists": False,
        })
        approval = root / "approval.json"
        write_json(approval, {
            "status": FINALIZER.APPROVAL_STATUS, "approved": True,
            "implementation_freeze_sha256": freeze_sha, "preregistration_sha256": prereg_sha,
            "preflight_receipt_sha256": sha(preflight), "training_template_sha256": sha(TEMPLATE),
        })
        args = argparse.Namespace(
            package_root=package, implementation_freeze=freeze, expected_implementation_freeze_sha256=freeze_sha,
            preregistration=prereg, expected_preregistration_sha256=prereg_sha,
            preflight_receipt=preflight, expected_preflight_receipt_sha256=sha(preflight),
            approval_receipt=approval, expected_approval_receipt_sha256=sha(approval), output_dir=root / "final",
        )
        return args

    def test_unfinalized_template_refuses_before_arguments_or_outputs(self):
        result = subprocess.run(["bash", str(TEMPLATE)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 86)
        self.assertIn("not_finalized", result.stderr)

    def test_cold_atime_update_is_not_misclassified_as_content_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cold.json"
            path.write_text("{}\n")
            stat = path.stat()
            os.utime(path, ns=(1_000_000_000, stat.st_mtime_ns))
            self.assertEqual(FINALIZER.read_regular(path), b"{}\n")
            os.utime(path, ns=(1_000_000_000, stat.st_mtime_ns))
            self.assertEqual(PREFLIGHT.read_regular(path), b"{}\n")

    def test_success_writes_only_launcher_and_false_started_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            result = FINALIZER.finalize(args)
            self.assertTrue(result["training_authorized"])
            self.assertFalse(result["training_started"])
            self.assertEqual(sorted(p.name for p in args.output_dir.iterdir()), ["FINAL_TRAINING_AUTHORIZATION_V1_3_3.json", "run_phase1_core_fold_pair_node1_v1_3_3.sh"])
            launcher = args.output_dir / "run_phase1_core_fold_pair_node1_v1_3_3.sh"
            self.assertNotIn("__V220_", launcher.read_text())
            self.assertNotIn("training_v1_2/C", launcher.read_text())

    def test_wrong_hash_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory)); args.expected_preflight_receipt_sha256 = "0" * 64
            with self.assertRaisesRegex(Exception, "preflight_sha256"):
                FINALIZER.finalize(args)
            self.assertFalse(args.output_dir.exists())

    def test_false_preflight_training_flag_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory)); value = json.loads(args.preflight_receipt.read_text()); value["training_started"] = True
            write_json(args.preflight_receipt, value); args.expected_preflight_receipt_sha256 = sha(args.preflight_receipt)
            approval = json.loads(args.approval_receipt.read_text()); approval["preflight_receipt_sha256"] = args.expected_preflight_receipt_sha256
            write_json(args.approval_receipt, approval); args.expected_approval_receipt_sha256 = sha(args.approval_receipt)
            with self.assertRaisesRegex(Exception, "preflight_training_started"):
                FINALIZER.finalize(args)

    def test_false_approval_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory)); value = json.loads(args.approval_receipt.read_text()); value["approved"] = False
            write_json(args.approval_receipt, value); args.expected_approval_receipt_sha256 = sha(args.approval_receipt)
            with self.assertRaisesRegex(Exception, "approval_false"):
                FINALIZER.finalize(args)


class SourceClosureTests(unittest.TestCase):
    def test_fully_frozen_package_exact_test_launcher_passes(self):
        if os.environ.get("V220_V133_NESTED_FROZEN_TEST") == "1":
            return
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "frozen-package"

            def ignore_production_freeze(source: str, names: list[str]):
                if Path(source).resolve() == ROOT.resolve():
                    return {name for name in (FREEZE_NAME, FREEZE_SIDECAR_NAME) if name in names}
                return set()

            shutil.copytree(ROOT, package, symlinks=True, ignore=ignore_production_freeze)
            implementation = {
                path.relative_to(package).as_posix(): sha(path)
                for path in package.rglob("*")
                if path.is_file()
            }
            freeze = package / FREEZE_NAME
            sidecar = package / FREEZE_SIDECAR_NAME
            allowlist = sorted([*implementation, freeze.name, sidecar.name])
            self.assertEqual(len(allowlist), len(set(allowlist)))
            freeze_sha = write_json(freeze, {
                "status": FINALIZER.FREEZE_STATUS,
                "training_authorized": False,
                "training_started": False,
                "implementation_hashes": implementation,
                "package_file_allowlist": allowlist,
            })
            sidecar.write_text(f"{freeze_sha}  {freeze.name}\n")
            result = subprocess.run(
                ["bash", str(package / "launchers/run_tests_v1_3_3.sh")],
                env={
                    **os.environ,
                    "PYTHON_BIN": sys.executable,
                    "V220_V133_NESTED_FROZEN_TEST": "1",
                },
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Ran 44 tests", result.stdout)
            self.assertRegex(result.stdout, r"(?m)^OK$")

    def test_package_allowlist_rejects_extra_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            freeze = root / "IMPLEMENTATION_FREEZE_PHASE1_TECHNICAL_RECOVERY_V1_3_3.json"
            implementation = root / "expected.txt"
            implementation.write_text("ok\n")
            freeze.write_text("{}\n")
            freeze_sha = sha(freeze)
            sidecar = freeze.with_suffix(freeze.suffix + ".sha256")
            sidecar.write_text(f"{freeze_sha}  {freeze.name}\n")
            allowlist = ["expected.txt", freeze.name, sidecar.name]
            FINALIZER.validate_package_closure(root, freeze, freeze_sha, allowlist, {"expected.txt": sha(implementation)})
            (root / "unexpected.sh").write_text("exit 1\n")
            with self.assertRaisesRegex(Exception, "package_allowlist_drift"):
                FINALIZER.validate_package_closure(root, freeze, freeze_sha, allowlist, {"expected.txt": sha(implementation)})
            (root / "unexpected.sh").unlink()
            (root / "linked").symlink_to(implementation)
            with self.assertRaisesRegex(Exception, "package_symlink"):
                FINALIZER.validate_package_closure(root, freeze, freeze_sha, allowlist, {"expected.txt": sha(implementation)})

    def test_dynamic_runtime_modules_and_helper_are_inside_artifact_bindings(self):
        for relative in (
            "src/materialize_v220_shared_fold_calibration_v1_3_1.py",
            "src/run_v220_contact_shared_fold_v1_3_1.py",
            "src/validate_v220_shared_fold_calibration_load_only_v1_3_1.py",
        ):
            source = (ROOT / relative).read_text()
            self.assertIn('"upstream_calibrator"', source)
            self.assertIn('"upstream_paired_initial_state"', source)
            self.assertIn('"upstream_contact_teacher_store"', source)
            self.assertIn('"exact_once_helper"', source)

    def test_preflight_launcher_has_no_arm_training_runner_and_binds_helper_argv(self):
        source = (ROOT / "launchers/run_phase1_preflight_node1_v1_3_3.sh").read_text()
        self.assertNotIn("run_v220_contact_shared_fold_v1_3_1.py", source)
        self.assertIn('"$HELPER" "$SHARED_DIR" --', source)
        self.assertIn('--shared-lock-dir "$SHARED_DIR"', source)
        self.assertIn('--expected-exact-once-helper-sha256 "$HELPER_SHA"', source)
        self.assertIn("EXPECTED_CALIBRATOR_SHA", source)


class Python311LegacyAdapterTests(unittest.TestCase):
    EXPECTED_RELATIVE = (
        "tests/test_calibrate_v220_contact_weight_v1.py",
        "tests/test_collect_v220_contact_shared_oof_v1.py",
        "tests/test_evaluate_v220_phase1_core_gate_v1.py",
        "tests/test_materialize_v220_paired_initial_state_v1.py",
        "tests/test_materialize_v220_production_initial_state_v1.py",
        "tests/test_materialize_v220_train_contact_teacher_v1.py",
        "tests/test_materialize_v220_train_contact_teacher_v1_1.py",
        "tests/test_materialize_v220_train_contact_teacher_v1_2.py",
        "tests/test_run_v220_contact_shared_fold_v1.py",
        "tests/test_v220_b0_replay_and_evaluator_v1.py",
        "tests/test_v220_contact_teacher_store_v1.py",
        "tests/test_validate_v220_paired_folds_v1.py",
        "tests/test_validate_v220_cross_process_initial_state_v1.py",
    )

    def test_adapter_uses_exact_relative_argv_and_never_discover(self):
        source = LEGACY_ADAPTER.read_text()
        self.assertNotIn("unittest discover", source)
        self.assertIn('"$PYTHON_BIN" -m unittest "${REL_TEST_FILES[@]}" -v', source)
        array = source.split("REL_TEST_FILES=(", 1)[1].split("\n)", 1)[0]
        observed = tuple(line.strip() for line in array.splitlines() if line.strip())
        self.assertEqual(observed, self.EXPECTED_RELATIVE)

    def test_adapter_binds_thirteen_hashes_and_rejects_top_level_drift(self):
        source = LEGACY_ADAPTER.read_text()
        checks = [line for line in source.splitlines() if line.endswith(".py") and "  tests/test_" in line and len(line.split()[0]) == 64]
        self.assertEqual(len(checks), 13)
        self.assertIn("assert observed==expected", source)
        self.assertIn("assert len(relative)==13", source)

    def test_adapter_rejects_wrong_python_version_before_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "legacy/tests").mkdir(parents=True)
            (root / "legacy/src").mkdir()
            fake = root / "fake-python"
            marker = root / "unexpected-test-invocation"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"${1:-}\" == --version ]]; then echo 'Python 3.11.13'; exit 0; fi\n"
                f"touch {marker}\nexit 99\n"
            )
            fake.chmod(0o700)
            result = subprocess.run(
                [str(LEGACY_ADAPTER), str(root / "legacy")],
                env={**os.environ, "PYTHON_BIN": str(fake)},
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 3)
            self.assertIn("python_version_mismatch", result.stderr)
            self.assertFalse(marker.exists())

    def test_builder_rejects_legacy_log_without_exact_python311_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.log"
            path.write_text("Ran 102 tests in 1.0s\n\nOK\n")
            with self.assertRaisesRegex(Exception, "legacy_python311_marker"):
                PREFLIGHT.parse_legacy_test_log(path)

    def test_adapter_does_not_execute_unbound_nested_test(self):
        source = LEGACY_ADAPTER.read_text()
        self.assertNotIn("-s tests", source)
        self.assertNotIn("-p 'test_*.py'", source)
        self.assertIn('"${REL_TEST_FILES[@]}"', source)

    def test_combined_launcher_uses_adapter_with_explicit_legacy_root(self):
        source = (ROOT / "launchers/run_combined_legacy_and_v1_3_3_tests.sh").read_text()
        self.assertIn('run_legacy_102_tests_python311_v1_3_3.sh" "$LEGACY_ROOT"', source)
        self.assertNotIn("run_phase1_core_preflight_tests_v1_2.sh", source)

    def test_preflight_binds_adapter_and_unchanged_v131_core(self):
        source = (ROOT / "launchers/run_phase1_preflight_node1_v1_3_3.sh").read_text()
        self.assertIn("run_legacy_102_tests_python311_v1_3_3.sh", source)
        self.assertIn("expected_freeze_sha=sys.argv[3]", source)
        self.assertIn("expected_allowlist=set(freeze['package_file_allowlist'])", source)
        self.assertIn("f'{expected_freeze_sha}  {freeze_path.name}", source)
        self.assertNotIn("f'{expected}  {freeze_path.name}", source)
        for relative in (
            "run_shared_fold_materialization_once_v1_3_1.sh",
            "materialize_v220_shared_fold_calibration_v1_3_1.py",
            "validate_v220_shared_fold_calibration_load_only_v1_3_1.py",
        ):
            self.assertIn(relative, source)

    def test_training_template_uses_unchanged_v131_core(self):
        source = TEMPLATE.read_text()
        self.assertIn("run_shared_fold_materialization_once_v1_3_1.sh", source)
        self.assertIn("materialize_v220_shared_fold_calibration_v1_3_1.py", source)
        self.assertIn("run_v220_contact_shared_fold_v1_3_1.py", source)
        self.assertIn("V1_3_1_SHARED_CALIBRATION_REPLAY_RECEIPT.json", source)
        self.assertIn("PASS_V220_V1_3_1_ARM_USED_SHARED_CALIBRATION_NO_RECALIBRATION", source)
        self.assertIn("EXPECTED_PAIRED_INITIAL_STATE_SHA", source)
        self.assertIn("EXPECTED_CONTACT_TEACHER_STORE_SHA", source)

    def test_builder_accepts_exact_unchanged_v131_load_only_status(self):
        self.assertEqual(
            PREFLIGHT.LOAD_ONLY_STATUS,
            "PASS_V220_V1_3_1_SHARED_CALIBRATION_SEPARATE_PROCESS_LOAD_ONLY",
        )

    def test_new_test_launcher_uses_relative_paths_not_root_absolute_argv(self):
        source = (ROOT / "launchers/run_tests_v1_3_3.sh").read_text()
        self.assertIn('cd "$ROOT"', source)
        self.assertIn('"$PYTHON_BIN" -m unittest "${REL_TEST_FILES[@]}" -v', source)
        self.assertNotIn('"$ROOT/tests/', source)

    def test_training_template_closes_preflight_internal_bindings_and_authorization(self):
        source = TEMPLATE.read_text()
        self.assertIn("preflight['implementation_freeze']['sha256']==freeze_sha", source)
        self.assertIn("preflight['preregistration']['sha256']==prereg_sha", source)
        self.assertIn("auth['training_authorized'] is True", source)
        self.assertIn('"$HELPER" "$SHARED_DIR" --', source)
        self.assertIn('--shared-lock-dir "$SHARED_DIR"', source)
        self.assertIn("EXPECTED_CALIBRATOR_SHA", source)


if __name__ == "__main__":
    unittest.main()
