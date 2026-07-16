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


SCRIPT = Path(__file__).with_name("monitor_pvrig_submission_release.sh")


def write_table(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_upstream(exp: Path) -> dict[str, Path]:
    shortlist = exp / "prepared/pvrig_geometry_shortlist_v1/shortlist50.tsv"
    shortlist_audit = exp / "prepared/pvrig_geometry_shortlist_v1/geometry_shortlist_audit.json"
    pose_manifest = exp / "prepared/pvrig_top20_pose_review_v1/remote_delivery_v1/current/pose_review_manifest.tsv"
    pose_audit = pose_manifest.parent / "pose_review_audit.json"
    pose_archive = pose_manifest.parent / "pose_review_bundle.tar.gz"
    receipt = exp / "status/pvrig_v4d_deepqc_postprocess_v1/final_receipt.json"
    shortlist_rows = [
        {"candidate_id": f"CAND_{index + 1:03d}", "rank": str(index + 1)}
        for index in range(50)
    ]
    write_table(shortlist, shortlist_rows)
    shortlist_audit.parent.mkdir(parents=True, exist_ok=True)
    shortlist_audit.write_text("{}\n")
    pose_rows = []
    for row in shortlist_rows[:20]:
        for pose_index in range(18):
            pose_rows.append(
                {
                    "candidate_id": row["candidate_id"],
                    "rank": row["rank"],
                    "pose_index": str(pose_index),
                }
            )
    write_table(pose_manifest, pose_rows)
    pose_audit.write_text("{}\n")
    pose_archive.write_bytes(b"archive")
    paths = {
        "shortlist50": shortlist,
        "geometry_shortlist_audit": shortlist_audit,
        "top20_pose_bundle_manifest": pose_manifest,
        "top20_pose_bundle_audit": pose_audit,
        "top20_pose_bundle_archive": pose_archive,
    }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(
            {
                "schema_version": "pvrig_v4d_deepqc_postprocess_receipt_v1",
                "status": "PASS_OPEN258_RANKED_TOP50_TOP20_POSE_BUNDLE_READY",
                "sealed_test_geometry_rows_released": 0,
                "outputs": {
                    name: {"path": str(path.resolve()), "sha256": sha(path)}
                    for name, path in paths.items()
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    paths["receipt"] = receipt
    return paths


def run_once(exp: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    env = dict(
        os.environ,
        PVRIG_EXP_DIR=str(exp),
        PYTHON=sys.executable,
        ONCE="1",
        POLL_SECONDS="1",
        MAX_WAIT_SECONDS="30",
        **extra,
    )
    return subprocess.run(
        [str(SCRIPT)], text=True, capture_output=True, env=env, check=False
    )


def status(exp: Path) -> dict[str, str]:
    path = exp / "status/pvrig_submission_release_v1/status.json"
    return json.loads(path.read_text())


def complete_review_inputs(exp: Path) -> None:
    review = exp / "prepared/pvrig_submission_release_v1/review_inputs"
    with (review / "pose_review_verdicts.template.tsv").open(
        newline="", encoding="utf-8"
    ) as handle:
        verdicts = list(csv.DictReader(handle, delimiter="\t"))
    for row in verdicts:
        row.update(
            {
                "verdict": "ACCEPT_COMPUTATIONAL_PRIORITY",
                "reviewer": "fixture",
                "review_notes": "current context review",
            }
        )
    write_table(review / "pose_review_verdicts.tsv", verdicts)
    with (review / "top10_selection.template.tsv").open(
        newline="", encoding="utf-8"
    ) as handle:
        selections = list(csv.DictReader(handle, delimiter="\t"))[:10]
    for index, row in enumerate(selections, start=1):
        row["portfolio_rank"] = str(index)
        row["selection_reason"] = "fixture selection"
    write_table(review / "top10_selection.tsv", selections)


class SubmissionMonitorTests(unittest.TestCase):
    def test_missing_and_invalid_upstream_never_become_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            exp = Path(temporary)
            result = run_once(exp)
            self.assertEqual(result.returncode, 4)
            self.assertEqual(status(exp)["status"], "WAITING_UPSTREAM")
            receipt = exp / "status/pvrig_v4d_deepqc_postprocess_v1/final_receipt.json"
            receipt.parent.mkdir(parents=True)
            receipt.write_text("not json")
            result = run_once(exp)
            self.assertEqual(result.returncode, 4)
            self.assertEqual(status(exp)["status"], "BLOCKED_UPSTREAM_INVALID_RECEIPT")

    def test_fake_existing_release_is_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            exp = Path(temporary)
            prepare_upstream(exp)
            self.assertEqual(run_once(exp).returncode, 4)
            complete_review_inputs(exp)
            release = exp / "prepared/pvrig_submission_release_v1/release"
            release.mkdir()
            (release / "release_audit.json").write_text("not json")
            (release / "clean_replay_receipt.json").write_text("not json")
            result = run_once(exp)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(status(exp)["status"], "FAILED")

    def test_review_context_change_makes_old_review_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            exp = Path(temporary)
            paths = prepare_upstream(exp)
            self.assertEqual(run_once(exp).returncode, 4)
            complete_review_inputs(exp)
            old_context = json.loads(
                (exp / "prepared/pvrig_submission_release_v1/review_inputs/review_context.json").read_text()
            )["review_context_id"]
            with paths["top20_pose_bundle_manifest"].open("a", encoding="utf-8") as handle:
                handle.write("\n")
            receipt = json.loads(paths["receipt"].read_text())
            receipt["outputs"]["top20_pose_bundle_manifest"]["sha256"] = sha(
                paths["top20_pose_bundle_manifest"]
            )
            paths["receipt"].write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
            result = run_once(exp)
            self.assertEqual(result.returncode, 4)
            self.assertEqual(status(exp)["status"], "WAITING_COMPUTATIONAL_POSE_REVIEW")
            new_context = json.loads(
                (exp / "prepared/pvrig_submission_release_v1/review_inputs/review_context.json").read_text()
            )["review_context_id"]
            self.assertNotEqual(old_context, new_context)

    def test_builder_timeout_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            exp = Path(temporary)
            prepare_upstream(exp)
            self.assertEqual(run_once(exp).returncode, 4)
            complete_review_inputs(exp)
            builder = exp / "slow_builder.py"
            builder.write_text("import time\ntime.sleep(5)\n")
            result = run_once(
                exp,
                BUILDER=str(builder),
                BUILD_TIMEOUT_SECONDS="1",
            )
            self.assertNotEqual(result.returncode, 0)
            payload = status(exp)
            self.assertEqual(payload["status"], "BLOCKED")
            self.assertIn("stage=builder", payload["reason"])


if __name__ == "__main__":
    unittest.main()
