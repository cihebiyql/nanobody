#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("deliver_phase2_v4_d_open_teacher_from_node23.py")
SPEC = importlib.util.spec_from_file_location("deliver_phase2_v4_d_open_teacher_from_node23", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable_to_load_delivery_module")
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_valid_outputs(root: Path, *, builder_sha: str = MOD.EXPECTED_BUILDER_SHA256) -> Path:
    outputs = root / "outputs"
    outputs.mkdir(parents=True)
    teacher = outputs / "v4d_open_teacher.tsv"
    fields = ["candidate_id", "model_split", "R_dual_min", "sequence_sha256"]
    with teacher.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for index in range(226):
            writer.writerow(
                {
                    "candidate_id": f"train-{index:03d}",
                    "model_split": "OPEN_TRAIN",
                    "R_dual_min": f"{index / 1000:.6f}",
                    "sequence_sha256": f"{index:064x}",
                }
            )
        for index in range(32):
            writer.writerow(
                {
                    "candidate_id": f"dev-{index:03d}",
                    "model_split": "OPEN_DEVELOPMENT",
                    "R_dual_min": f"{index / 100:.6f}",
                    "sequence_sha256": f"{index + 1000:064x}",
                }
            )

    evaluator = {
        "status": "PASS",
        "unlockable": True,
        "evidence_mode": "production_pose_backed",
        "job_count": MOD.EXPECTED_TOTAL_JOBS,
        "job_manifest_sha256": MOD.EXPECTED_JOB_MANIFEST_SHA256,
        "job_results_sha256": "1" * 64,
        "pose_scores_sha256": "2" * 64,
        "protocol_core_sha256": MOD.EXPECTED_PROTOCOL_CORE_SHA256,
        "protocol_lock_sha256": MOD.EXPECTED_PROTOCOL_LOCK_SHA256,
        "candidates_sha256": MOD.EXPECTED_SPLIT_MANIFEST_SHA256,
        "stability_gate_spec_sha256": MOD.EXPECTED_STABILITY_SPEC_SHA256,
        "gates": {"all_jobs_terminal": {"status": "PASS"}, "minimum_seeds": {"passed": True}},
    }
    evaluator_path = outputs / "EVALUATOR_STABLE.json"
    write_json(evaluator_path, evaluator)
    closure_sha = "3" * 64
    audit = {
        "status": "PASS_V4_D_OPEN_CONTINUOUS_TEACHER_RELEASE",
        "release": "open_train_and_open_development_only",
        "row_count": 258,
        "sealed_data_boundary": {
            "model_split": MOD.SEALED_SPLIT,
            "row_count": MOD.EXPECTED_SEALED_COUNT,
            "raw_job_results_opened": 0,
            "sealed_metrics_used_for_teacher_or_ranking": False,
        },
        "inputs": {
            "split_manifest_sha256": MOD.EXPECTED_SPLIT_MANIFEST_SHA256,
            "job_manifest_sha256": MOD.EXPECTED_JOB_MANIFEST_SHA256,
            "job_results_sha256_for_evaluator_binding_only": evaluator["job_results_sha256"],
            "pose_scores_sha256_for_evaluator_binding_only": evaluator["pose_scores_sha256"],
            "evaluator_sha256": digest(evaluator_path),
            "raw_aggregate_closure": {
                "status": "PASS_RAW_OPEN_RESULTS_MATCH_EVALUATOR_BOUND_AGGREGATES",
                "job_count": MOD.EXPECTED_OPEN_JOB_COUNT,
                "closure_sha256": closure_sha,
            },
        },
        "output": {"sha256": digest(teacher)},
    }
    audit_path = outputs / "v4d_open_teacher.tsv.audit.json"
    write_json(audit_path, audit)
    receipt = {
        "schema_version": "pvrig_v4_d_open_teacher_postprocess_receipt_v2",
        "status": "PASS_OPEN258_TEACHER_READY_TEST32_SEALED",
        "row_count": 258,
        "split_counts": MOD.EXPECTED_OPEN_COUNTS,
        "sealed_test_raw_job_results_opened": 0,
        "sealed_metrics_used_for_teacher_or_ranking": False,
        "full_aggregate_streamed_only_for_open_row_closure": True,
        "raw_aggregate_closure_sha256": closure_sha,
        "teacher_sha256": digest(teacher),
        "teacher_audit_sha256": digest(audit_path),
        "evaluator_sha256": digest(evaluator_path),
        "builder_sha256": builder_sha,
        "job_manifest_sha256": evaluator["job_manifest_sha256"],
        "job_results_sha256": evaluator["job_results_sha256"],
        "pose_scores_sha256": evaluator["pose_scores_sha256"],
    }
    receipt_path = outputs / "open_teacher_postprocess_receipt.json"
    write_json(receipt_path, receipt)
    checksum_paths = [teacher, audit_path, evaluator_path, receipt_path]
    (outputs / "SHA256SUMS").write_text(
        "".join(f"{digest(path)}  outputs/{path.name}\n" for path in checksum_paths),
        encoding="ascii",
    )
    return root


def build_archive(payload_root: Path, archive: Path, *, mode: str = "valid") -> str:
    members = sorted(MOD.EXPECTED_ARCHIVE_MEMBERS)
    with tarfile.open(archive, "w:gz") as bundle:
        for name in members:
            source = payload_root / name
            if mode == "symlink" and name == "outputs/v4d_open_teacher.tsv":
                info = tarfile.TarInfo(name)
                info.type = tarfile.SYMTYPE
                info.linkname = "outputs/EVALUATOR_STABLE.json"
                bundle.addfile(info)
            elif mode == "hardlink" and name == "outputs/v4d_open_teacher.tsv":
                info = tarfile.TarInfo(name)
                info.type = tarfile.LNKTYPE
                info.linkname = "outputs/EVALUATOR_STABLE.json"
                bundle.addfile(info)
            else:
                bundle.add(source, arcname=name, recursive=False)
        if mode == "traversal":
            raw = b"escape"
            info = tarfile.TarInfo("../escape")
            info.size = len(raw)
            bundle.addfile(info, io.BytesIO(raw))
    return digest(archive)


class FakeRemote:
    def __init__(self, archive: Path | None, *, status: str = "COMPLETE", checksum_override: str | None = None) -> None:
        self.archive = archive
        self.status = status
        self.checksum_override = checksum_override
        self.read_paths: list[str] = []
        self.stream_paths: list[str] = []

    def read_file(self, remote_path: Path, *, max_bytes: int) -> bytes:
        self.read_paths.append(str(remote_path))
        if str(remote_path).endswith(MOD.REMOTE_STATUS):
            return json.dumps({"status": self.status, "reason": "test"}).encode()
        if str(remote_path).endswith(MOD.REMOTE_ARCHIVE_SHA):
            if self.archive is None:
                raise MOD.DeliveryError("remote checksum missing")
            checksum = self.checksum_override or digest(self.archive)
            return f"{checksum}  {MOD.REMOTE_ARCHIVE}\n".encode("ascii")
        raise AssertionError(f"unexpected read: {remote_path}")

    def stream_file(self, remote_path: Path, destination: Path, *, max_bytes: int) -> int:
        self.stream_paths.append(str(remote_path))
        if self.archive is None:
            raise MOD.DeliveryError("remote archive missing")
        raw = self.archive.read_bytes()
        if len(raw) > max_bytes:
            raise MOD.DeliveryError("too large")
        destination.write_bytes(raw)
        return len(raw)


def config(root: Path) -> MOD.Config:
    return MOD.Config(
        delivery_root=root,
        ssh_exe=Path("/fake/ssh"),
        remote_host="node23",
        remote_root=MOD.REMOTE_ROOT,
        poll_seconds=0.01,
        production=False,
    )


class OpenTeacherDeliveryTest(unittest.TestCase):
    def test_waits_without_remote_complete_and_opens_no_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            delivery = Path(directory) / "delivery"
            delivery.mkdir()
            remote = FakeRemote(None, status="WAITING_V4D")
            with self.assertRaises(MOD.DeliveryWaiting):
                MOD.one_delivery_attempt(config(delivery), remote, {"script_sha256": "x"})
            self.assertEqual(len(remote.read_paths), 1)
            self.assertFalse((delivery / "current").exists())
            status = json.loads((delivery / "status/delivery_status.json").read_text())
            self.assertEqual(status["status"], "WAITING_REMOTE")
            self.assertFalse(status["test32_labels_read"])

    def test_complete_delivery_is_content_addressed_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = build_valid_outputs(root / "payload")
            archive = root / "bundle.tar.gz"
            archive_sha = build_archive(payload, archive)
            delivery = root / "delivery"
            delivery.mkdir()
            remote = FakeRemote(archive)
            observed = MOD.one_delivery_attempt(config(delivery), remote, {"script_sha256": "x"})
            self.assertEqual(observed, archive_sha)
            self.assertTrue((delivery / "current").is_symlink())
            self.assertEqual(os.readlink(delivery / "current"), f"by_sha256/{archive_sha}")
            self.assertEqual(
                (delivery / "current/outputs/v4d_open_teacher.tsv").resolve(),
                (delivery / f"by_sha256/{archive_sha}/outputs/v4d_open_teacher.tsv").resolve(),
            )
            second = FakeRemote(None, status="FAILED")
            self.assertEqual(
                MOD.one_delivery_attempt(config(delivery), second, {"script_sha256": "x"}),
                archive_sha,
            )
            self.assertEqual(second.read_paths, [])

    def test_remote_complete_without_artifacts_waits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            delivery = Path(directory) / "delivery"
            delivery.mkdir()
            with self.assertRaises(MOD.DeliveryWaiting):
                MOD.one_delivery_attempt(config(delivery), FakeRemote(None), {"script_sha256": "x"})
            status = json.loads((delivery / "status/delivery_status.json").read_text())
            self.assertEqual(status["status"], "WAITING_REMOTE_ARTIFACTS")

    def test_archive_hash_mismatch_never_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = build_valid_outputs(root / "payload")
            archive = root / "bundle.tar.gz"
            build_archive(payload, archive)
            delivery = root / "delivery"
            delivery.mkdir()
            with self.assertRaisesRegex(MOD.DeliveryError, "downloaded_archive_sha256_mismatch"):
                MOD.one_delivery_attempt(
                    config(delivery), FakeRemote(archive, checksum_override="0" * 64), {"script_sha256": "x"}
                )
            self.assertFalse((delivery / "current").exists())

    def test_archive_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "bundle.tar.gz"
            build_archive(build_valid_outputs(root / "payload"), archive, mode="symlink")
            with self.assertRaisesRegex(MOD.DeliveryError, "archive_member_not_regular"):
                MOD.extract_validated_archive(archive, root / "out")

    def test_archive_hardlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "bundle.tar.gz"
            build_archive(build_valid_outputs(root / "payload"), archive, mode="hardlink")
            with self.assertRaisesRegex(MOD.DeliveryError, "archive_member_not_regular"):
                MOD.extract_validated_archive(archive, root / "out")

    def test_archive_traversal_or_extra_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "bundle.tar.gz"
            build_archive(build_valid_outputs(root / "payload"), archive, mode="traversal")
            with self.assertRaisesRegex(MOD.DeliveryError, "archive_member_set_mismatch"):
                MOD.extract_validated_archive(archive, root / "out")
            self.assertFalse((root / "escape").exists())

    def test_payload_checksum_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_valid_outputs(Path(directory) / "payload")
            with (root / "outputs/v4d_open_teacher.tsv").open("a", encoding="utf-8") as handle:
                handle.write("tamper\n")
            with self.assertRaisesRegex(MOD.DeliveryError, "payload_sha256_mismatch"):
                MOD.validate_release_outputs(root)

    def test_wrong_builder_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_valid_outputs(Path(directory) / "payload", builder_sha="0" * 64)
            receipt = root / "outputs/open_teacher_postprocess_receipt.json"
            sums = root / "outputs/SHA256SUMS"
            lines = sums.read_text().splitlines()
            lines[-1] = f"{digest(receipt)}  outputs/{receipt.name}"
            sums.write_text("\n".join(lines) + "\n")
            with self.assertRaisesRegex(MOD.DeliveryError, "receipt_builder_hash_mismatch"):
                MOD.validate_release_outputs(root)

    def test_test32_boundary_violation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_valid_outputs(Path(directory) / "payload")
            receipt_path = root / "outputs/open_teacher_postprocess_receipt.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["sealed_test_raw_job_results_opened"] = 1
            write_json(receipt_path, receipt)
            sums = root / "outputs/SHA256SUMS"
            lines = sums.read_text().splitlines()
            lines[-1] = f"{digest(receipt_path)}  outputs/{receipt_path.name}"
            sums.write_text("\n".join(lines) + "\n")
            with self.assertRaisesRegex(MOD.DeliveryError, "receipt_sealed_results_opened"):
                MOD.validate_release_outputs(root)

    def test_evaluator_nonpass_gate_is_rejected_even_when_receipt_rehashed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_valid_outputs(Path(directory) / "payload")
            evaluator_path = root / "outputs/EVALUATOR_STABLE.json"
            evaluator = json.loads(evaluator_path.read_text())
            evaluator["gates"]["minimum_seeds"] = {"status": "FAIL"}
            write_json(evaluator_path, evaluator)
            audit_path = root / "outputs/v4d_open_teacher.tsv.audit.json"
            audit = json.loads(audit_path.read_text())
            audit["inputs"]["evaluator_sha256"] = digest(evaluator_path)
            write_json(audit_path, audit)
            receipt_path = root / "outputs/open_teacher_postprocess_receipt.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["evaluator_sha256"] = digest(evaluator_path)
            receipt["teacher_audit_sha256"] = digest(audit_path)
            write_json(receipt_path, receipt)
            paths = [
                root / "outputs/v4d_open_teacher.tsv",
                audit_path,
                evaluator_path,
                receipt_path,
            ]
            (root / "outputs/SHA256SUMS").write_text(
                "".join(f"{digest(path)}  outputs/{path.name}\n" for path in paths)
            )
            with self.assertRaisesRegex(MOD.DeliveryError, "evaluator_nonpass_gates"):
                MOD.validate_release_outputs(root)

    def test_different_existing_current_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            delivery = root / "delivery"
            delivery.mkdir()
            payload1 = build_valid_outputs(root / "payload1")
            archive1 = root / "one.tar.gz"
            sha1 = build_archive(payload1, archive1)
            MOD.one_delivery_attempt(config(delivery), FakeRemote(archive1), {"script_sha256": "x"})
            payload2 = build_valid_outputs(root / "payload2")
            teacher2 = payload2 / "outputs/v4d_open_teacher.tsv"
            teacher2.write_text(teacher2.read_text().replace("0.000000", "0.000001", 1))
            # Rebuild all dependent hashes through the test helper after changing content.
            payload2 = build_valid_outputs(root / "payload2_rebuilt")
            archive2 = root / "two.tar.gz"
            sha2 = build_archive(payload2, archive2)
            if sha1 == sha2:
                archive2.write_bytes(archive2.read_bytes() + b"\n")
                sha2 = digest(archive2)
            staging = root / "staging"
            MOD.extract_validated_archive(archive2, staging)
            source = staging / "source"
            source.mkdir()
            (source / "v4d_open_teacher_delivery_v1.tar.gz").write_bytes(archive2.read_bytes())
            (source / "v4d_open_teacher_delivery_v1.tar.gz.sha256").write_text(
                f"{sha2}  {MOD.REMOTE_ARCHIVE}\n"
            )
            validation = MOD.validate_release_outputs(staging)
            with self.assertRaisesRegex(MOD.DeliveryError, "different_existing_current_refused"):
                MOD.publish_release(config(delivery), staging, sha2, validation, {"script_sha256": "x"})
            self.assertEqual(os.readlink(delivery / "current"), f"by_sha256/{sha1}")

    def test_checksum_parser_requires_exact_remote_filename(self) -> None:
        good = f"{'a' * 64}  {MOD.REMOTE_ARCHIVE}\n".encode()
        self.assertEqual(MOD.parse_remote_archive_checksum(good), "a" * 64)
        with self.assertRaises(MOD.DeliveryError):
            MOD.parse_remote_archive_checksum(f"{'a' * 64}  bundle.tar.gz\n".encode())

    def test_no_python_assert_is_used_by_production_delivery_source(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?m)^\s*assert\s")


if __name__ == "__main__":
    unittest.main()
