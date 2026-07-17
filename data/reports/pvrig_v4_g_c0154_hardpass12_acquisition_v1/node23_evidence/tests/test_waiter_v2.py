#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
VERIFIER = HERE / "verify_open_teacher_release_v1.py"
WAITER = HERE / "wait_for_v4d_open_teacher_then_run_v2.sh"
if not VERIFIER.is_file():
    VERIFIER = HERE.parent / "scripts/verify_open_teacher_release_v1.py"
if not WAITER.is_file():
    WAITER = HERE.parent / "scripts/wait_for_v4d_open_teacher_then_run_v2.sh"

spec = importlib.util.spec_from_file_location("open_teacher_verifier", VERIFIER)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OpenTeacherReleaseVerifierTests(unittest.TestCase):
    def make_release(self, root: Path) -> None:
        (root / "status").mkdir(parents=True)
        (root / "outputs").mkdir()
        (root / "status/postprocess_status.json").write_text(
            json.dumps({"status": "COMPLETE"}) + "\n"
        )
        builder = root / "prepare_phase2_v4_d_open_teacher.py"
        builder.write_text("# frozen builder\n")
        teacher = root / "outputs/v4d_open_teacher.tsv"
        teacher.write_text("opaque_hash_only\n")
        evaluator = {
            "status": "PASS",
            "unlockable": True,
            "evidence_mode": "production_pose_backed",
            "job_count": 2022,
            "job_manifest_sha256": "1" * 64,
            "job_results_sha256": "2" * 64,
            "pose_scores_sha256": "3" * 64,
            "gates": {name: {"status": "PASS"} for name in module.REQUIRED_EVALUATOR_GATES},
        }
        evaluator_path = root / "outputs/EVALUATOR_STABLE.json"
        evaluator_path.write_text(json.dumps(evaluator) + "\n")
        closure_hash = "4" * 64
        audit = {
            "status": "PASS_V4_D_OPEN_CONTINUOUS_TEACHER_RELEASE",
            "sealed_data_boundary": {
                "raw_job_results_opened": 0,
                "candidate_level_aggregate_rows_retained_or_released": 0,
                "sealed_metrics_used_for_teacher_or_ranking": False,
            },
            "inputs": {"raw_aggregate_closure": {
                "status": "PASS_RAW_OPEN_RESULTS_MATCH_EVALUATOR_BOUND_AGGREGATES",
                "job_count": 1548,
                "closure_sha256": closure_hash,
            }},
        }
        audit_path = root / "outputs/v4d_open_teacher.tsv.audit.json"
        audit_path.write_text(json.dumps(audit) + "\n")
        receipt = {
            "status": "PASS_OPEN258_TEACHER_READY_TEST32_SEALED",
            "row_count": 258,
            "split_counts": {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32},
            "sealed_test_raw_job_results_opened": 0,
            "sealed_metrics_used_for_teacher_or_ranking": False,
            "full_aggregate_streamed_only_for_open_row_closure": True,
            "raw_aggregate_closure_sha256": closure_hash,
            "teacher_sha256": digest(teacher),
            "teacher_audit_sha256": digest(audit_path),
            "evaluator_sha256": digest(evaluator_path),
            "builder_sha256": digest(builder),
            "job_manifest_sha256": evaluator["job_manifest_sha256"],
            "job_results_sha256": evaluator["job_results_sha256"],
            "pose_scores_sha256": evaluator["pose_scores_sha256"],
        }
        receipt_path = root / "outputs/open_teacher_postprocess_receipt.json"
        receipt_path.write_text(json.dumps(receipt) + "\n")
        members = [
            teacher,
            audit_path,
            evaluator_path,
            receipt_path,
        ]
        (root / "outputs/SHA256SUMS").write_text(
            "".join(f"{digest(path)}  outputs/{path.name}\n" for path in members)
        )
        archive = root / "outputs/v4d_open_teacher_delivery_v1.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            for path in members:
                handle.add(path, arcname=f"outputs/{path.name}")
        (root / "outputs/v4d_open_teacher_delivery_v1.tar.gz.sha256").write_text(
            f"{digest(archive)}  outputs/{archive.name}\n"
        )

    def test_valid_release_passes_without_parsing_teacher_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_release(root)
            result = module.assess(root)
            self.assertEqual(result["status"], "READY")
            self.assertTrue(result["test32_sealed"])

    def test_test32_opened_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_release(root)
            receipt_path = root / "outputs/open_teacher_postprocess_receipt.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["sealed_test_raw_job_results_opened"] = 1
            receipt_path.write_text(json.dumps(receipt) + "\n")
            result = module.assess(root)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertFalse(result["test32_sealed"])

    def test_noncomplete_postprocessor_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_release(root)
            (root / "status/postprocess_status.json").write_text(
                json.dumps({"status": "WAITING_V4D"}) + "\n"
            )
            result = module.assess(root)
            self.assertEqual(result["status"], "BLOCKED")

    def test_waiter_has_all_priority_gates(self) -> None:
        source = WAITER.read_text()
        for token in (
            "terminal and closed and no_active and release_ready and load1 <= max_load",
            "PASS_V1_WAITER_STOPPED_BEFORE_ACQUISITION_V2_READY",
            "open_teacher_ready_test32_sealed",
            "WAITER_TRUST_ANCHOR_V2.json",
            "verify_open_teacher_release_v1.py",
        ):
            self.assertIn(token, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
