#!/usr/bin/env python3
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("build_phase2_v4_g_unseen96_full_qc_package.py")
SPEC = importlib.util.spec_from_file_location("v4g_package", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class V4GUnseen96PackageTests(unittest.TestCase):
    def build(self, root: Path) -> Path:
        output = root / "package"
        result = MODULE.build_package(
            MODULE.DEFAULT_MANIFEST,
            MODULE.DEFAULT_PREREG,
            MODULE.DEFAULT_FREEZE_RECEIPT,
            output,
        )
        self.assertEqual(result["status"], "PASS")
        return output

    def test_allowed_frozen_sources_close_without_labels(self):
        rows, metadata = MODULE.validate_sources(
            MODULE.DEFAULT_MANIFEST,
            MODULE.DEFAULT_PREREG,
            MODULE.DEFAULT_FREEZE_RECEIPT,
        )
        self.assertEqual(len(rows), 96)
        self.assertEqual(len(metadata["parent_clusters"]), 8)
        self.assertFalse(set(metadata["parent_clusters"]) & set(metadata["reserve2_parent_clusters_excluded"]))

    def test_build_and_validate_receipt_last(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = self.build(Path(tmpdir))
            result = MODULE.validate_package(
                output, MODULE.DEFAULT_MANIFEST, MODULE.DEFAULT_PREREG, MODULE.DEFAULT_FREEZE_RECEIPT
            )
            self.assertEqual(result["candidate_count"], 96)
            self.assertEqual({path.name for path in output.iterdir()}, MODULE.PACKAGE_FILES)
            receipt = output / "PACKAGE_RECEIPT.json"
            self.assertGreaterEqual(
                receipt.stat().st_mtime_ns,
                max(path.stat().st_mtime_ns for path in output.iterdir() if path != receipt),
            )

    def test_replay_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = self.build(root / "a")
            second = self.build(root / "b")
            for name in MODULE.PACKAGE_FILES:
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes(), name)

    def test_payload_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = self.build(Path(tmpdir))
            with (output / "unseen96.fasta").open("ab") as handle:
                handle.write(b"\n")
            with self.assertRaises(RuntimeError):
                MODULE.validate_package(
                    output, MODULE.DEFAULT_MANIFEST, MODULE.DEFAULT_PREREG, MODULE.DEFAULT_FREEZE_RECEIPT
                )

    def test_waiter_requires_ssd_path_switch_and_never_nfs_complete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = self.build(Path(tmpdir))
            launcher = (output / "wait_for_ssd_deepqc_delivery_then_run_node1.sh").read_text()
            self.assertIn("ACTIVE_DEEPQC_DELIVERY_PATH_SWITCH.json", launcher)
            self.assertIn("PASS_SSD_DEEPQC_DELIVERY_PATH_SWITCHED", launcher)
            self.assertNotIn("/data/qlyu/", launcher)
            self.assertNotIn('upstream_state" == COMPLETE', launcher)

    def test_generated_shells_execute_runtime_smoke_with_canonical_bindings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = self.build(Path(tmpdir))
            result = MODULE.validate_shell_contracts(output)
            self.assertEqual(result["runner"]["status"], "PASS_V4_G_RUNNER_SHELL_SMOKE")
            self.assertEqual(result["runner"]["screen"], MODULE.CANONICAL_SCREEN)
            self.assertEqual(result["waiter"]["status"], "PASS_V4_G_WAITER_SHELL_SMOKE")
            self.assertEqual(
                result["waiter"]["recovery_receipt"], MODULE.CANONICAL_RECOVERY_RECEIPT
            )

    def test_rc0_without_full_completion_artifacts_is_terminal_fail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output = self.build(root / "build")
            fixture = Path("/tmp") / f"v4g_false_rc0_fixture_{root.name}"
            try:
                (fixture / "status").mkdir(parents=True, exist_ok=False)
                completed = subprocess.run(
                    [
                        str(output / "run_full_qc_node1.sh"),
                        "--terminal-contract-test",
                        str(fixture),
                        "0",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 86, completed.stderr)
                failed_path = fixture / "status" / "runner.failed.json"
                self.assertTrue(failed_path.is_file())
                failed = json.loads(failed_path.read_text())
                self.assertEqual(failed["status"], "FAIL_V4_G_UNSEEN96_FULL_QC")
                self.assertEqual(failed["original_returncode"], 0)
                self.assertEqual(failed["returncode"], 86)
                self.assertIn("missing_cascade_state", failed["completion_contract_error"])
                self.assertFalse((fixture / "status" / "runner.complete.json").exists())
            finally:
                shutil.rmtree(fixture, ignore_errors=True)

    def test_tampered_manifest_or_reserve_entry_is_rejected_before_build(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "manifest.tsv"
            shutil.copyfile(MODULE.DEFAULT_MANIFEST, manifest)
            manifest.write_text(manifest.read_text().replace("C0404", "C0019", 1))
            with self.assertRaises(RuntimeError):
                MODULE.validate_sources(manifest, MODULE.DEFAULT_PREREG, MODULE.DEFAULT_FREEZE_RECEIPT)


if __name__ == "__main__":
    unittest.main()
