#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("materialize_phase2_v4_d_dev1_open258_v1_1_offline_review_package.py")
SPEC = importlib.util.spec_from_file_location("materialize_phase2_v4_d_dev1_open258_v1_1_offline_review_package", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable_to_load_materializer")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def make_fixture(root: Path) -> tuple[Path, dict[str, Path]]:
    sources = root / "sources"
    sources.mkdir()
    files: dict[str, Path] = {}
    for key in ("builder", "delivery", "split_manifest", "generic_prior_extract"):
        path = sources / f"{key}.txt"
        path.write_text(f"label-free fixture for {key}\n", encoding="utf-8")
        files[key] = path
    freeze = {
        "schema_version": "fixture",
        "status": MOD.CANDIDATE_STATUS,
        "remote_execution_started": False,
        "remote_execution_authorized": False,
        "test32_raw_job_files_opened": 0,
        "test32_metric_values_read": 0,
        "test32_label_rows_emitted": 0,
        "source_evaluator_status": "FAIL",
        "source_evaluator_unlockable": False,
        "formal_v4_f_unlock_eligible": False,
        "final_submission_authority": False,
        "single_terminal_failure_fallback": {
            "count": 1,
            "raw_success_count": 1547,
            "aggregate_terminal_rows_parsed": 1,
            "aggregate_metric_fields_parsed": 0,
            "pose_scores_exact_job_rows": 0,
            "state": "FAILED_MAX_ATTEMPTS",
        },
        "files": {
            key: {"sha256": digest(path), "size": path.stat().st_size}
            for key, path in files.items()
        },
    }
    freeze_path = root / "freeze.json"
    write_json(freeze_path, freeze)
    return freeze_path, files


class OfflinePackageMaterializerTest(unittest.TestCase):
    def test_valid_candidate_freeze_materializes_content_closed_local_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            freeze, files = make_fixture(root)
            output = root / "package"
            result = MOD.materialize(freeze, output, files=files)
            self.assertEqual(result["status"], MOD.PACKAGE_STATUS)
            self.assertFalse(result["remote_execution_authorized"])
            self.assertEqual(result["test32_metric_values_read"], 0)
            self.assertEqual(result["test32_label_rows_included"], 0)
            self.assertEqual(result["single_terminal_failure_recovery"]["raw_success_count"], 1547)
            self.assertTrue((output / "PACKAGE_RECEIPT.json").is_file())
            checksum_lines = (output / "SHA256SUMS").read_text().splitlines()
            self.assertEqual(len(checksum_lines), len(list(output.iterdir())) - 1)
            for line in checksum_lines:
                value, name = line.split("  ", 1)
                self.assertEqual(value, digest(output / name))

    def test_launch_authorization_or_test32_access_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            freeze_path, files = make_fixture(root)
            baseline = json.loads(freeze_path.read_text())
            for field, value, message in (
                ("remote_execution_authorized", True, "freeze_remote_execution_authorized"),
                ("test32_metric_values_read", 1, "freeze_test32_metric_values_read_nonzero"),
                ("formal_v4_f_unlock_eligible", True, "freeze_formal_v4f_unlock_true"),
                ("final_submission_authority", True, "freeze_final_submission_authority_true"),
            ):
                with self.subTest(field=field):
                    altered = json.loads(json.dumps(baseline))
                    altered[field] = value
                    write_json(freeze_path, altered)
                    with self.assertRaisesRegex(MOD.PackageError, message):
                        MOD.materialize(freeze_path, root / f"package-{field}", files=files)

    def test_hash_drift_fails_closed_and_removes_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            freeze, files = make_fixture(root)
            files["delivery"].write_text("post-freeze drift\n", encoding="utf-8")
            output = root / "package"
            with self.assertRaisesRegex(MOD.PackageError, "freeze_hash_mismatch:delivery"):
                MOD.materialize(freeze, output, files=files)
            self.assertFalse(output.exists())

    def test_symlink_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            freeze, files = make_fixture(root)
            original = files["delivery"]
            target = root / "replacement"
            target.write_bytes(original.read_bytes())
            original.unlink()
            os.symlink(target, original)
            with self.assertRaisesRegex(MOD.PackageError, "not_regular_or_is_symlink:delivery"):
                MOD.materialize(freeze, root / "package", files=files)

    def test_freeze_must_bind_exact_review_file_key_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            freeze_path, files = make_fixture(root)
            payload = json.loads(freeze_path.read_text())
            payload["files"].pop("delivery")
            write_json(freeze_path, payload)
            with self.assertRaisesRegex(MOD.PackageError, "freeze_file_key_set_mismatch"):
                MOD.materialize(freeze_path, root / "package", files=files)

    def test_source_has_no_ssh_execution_or_python_assert(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?m)^\s*assert\s")
        self.assertNotIn("subprocess", source)
        self.assertNotIn("ssh.exe", source)
        self.assertNotIn("EVALUATOR_STABLE.json", source)
        self.assertNotIn("job_result.json", source)


if __name__ == "__main__":
    unittest.main()
