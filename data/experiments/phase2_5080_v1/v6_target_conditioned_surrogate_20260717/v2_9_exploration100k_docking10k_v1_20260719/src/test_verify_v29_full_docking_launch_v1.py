#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("verify_v29_full_docking_launch_v1.py")
SPEC = importlib.util.spec_from_file_location("verify_launch", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class VerifyLaunchTest(unittest.TestCase):
    def make_fixture(self, root: Path) -> None:
        frozen = [
            {"job_id": f"allocated{i}", "candidate_id": f"candidate{i}", "receptor": "8x6b", "seed": "917"}
            for i in range(25000)
        ]
        executable = frozen[:4]
        jobs = [
            {"job_id": f"materialized{i}", "entity_id": row["candidate_id"], "conformation": row["receptor"], "seed": row["seed"]}
            for i, row in enumerate(executable)
        ]
        write_tsv(root / "inputs/docking_allocation25000_frozen_all.tsv", frozen)
        write_tsv(root / "inputs/docking_allocation25000.tsv", executable)
        write_tsv(root / "manifests/docking_jobs.tsv", jobs)
        write_tsv(root / "manifests/node1_jobs.tsv", jobs[::2])
        write_tsv(root / "manifests/node23_jobs.tsv", jobs[1::2])
        write_json(root / "PROTOCOL_CORE_LOCK.json", {"status": "LOCKED"})
        write_json(root / "reports/reference_normalization_summary.json", {"status": "PASS"})
        write_json(root / "status/STAGED.json", {
            "status": "PASS_FULL_DOCKING_STAGED", "executable_job_count": 4,
            "node1_job_count": 2, "node23_job_count": 2,
        })
        write_json(root / "status/LAUNCHED.json", {
            "status": "RUNNING_FULL_DOCKING", "executable_job_count": 4,
            "node1_pid": 11, "node23_pid": 12,
        })
        write_json(root / "PROTOCOL_LOCK.json", {
            "status": "LOCKED", "protocol_lock_sha256": "fixture",
            "core_lock_sha256": sha256(root / "PROTOCOL_CORE_LOCK.json"),
            "job_manifest_sha256": sha256(root / "manifests/docking_jobs.tsv"),
            "node1_jobs_sha256": sha256(root / "manifests/node1_jobs.tsv"),
            "node23_jobs_sha256": sha256(root / "manifests/node23_jobs.tsv"),
            "reference_normalization_summary_sha256": sha256(root / "reports/reference_normalization_summary.json"),
        })

    def test_closed_shards_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_fixture(root)
            receipt = MODULE.validate(root, require_first_status=False, skip_pid_check=True)
            self.assertEqual(receipt["status"], "PASS_FULL_DOCKING_LAUNCH_ACCEPTANCE")
            self.assertEqual(receipt["frozen_allocation_count"], 25000)
            self.assertTrue((root / "status/LAUNCH_ACCEPTANCE.json").is_file())

    def test_overlapping_shards_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_fixture(root)
            write_tsv(root / "manifests/node23_jobs.tsv", [{"job_id": "materialized0"}, {"job_id": "materialized1"}])
            lock = json.loads((root / "PROTOCOL_LOCK.json").read_text())
            lock["node23_jobs_sha256"] = sha256(root / "manifests/node23_jobs.tsv")
            write_json(root / "PROTOCOL_LOCK.json", lock)
            with self.assertRaisesRegex(RuntimeError, "node_shards_overlap"):
                MODULE.validate(root, require_first_status=False, skip_pid_check=True)


if __name__ == "__main__":
    unittest.main()
