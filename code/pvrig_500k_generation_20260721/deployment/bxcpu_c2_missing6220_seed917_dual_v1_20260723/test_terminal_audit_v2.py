#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import pathlib
import tempfile
import unittest


HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "technical_status_c2_missing6220_v2", HERE / "technical_status_c2_missing6220_v2.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class TerminalAuditV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.manifest = self.root / "jobs.tsv"
        with self.manifest.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["job_id"], delimiter="\t")
            writer.writeheader()
            writer.writerows([{"job_id": x} for x in ("a", "b", "c")])
        (self.root / "status/jobs").mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_state(self, job: str, state: str) -> None:
        (self.root / "status/jobs" / f"{job}.json").write_text(
            json.dumps({"job_id": job, "status": state})
        )

    def test_failed_is_terminal_technical_na(self) -> None:
        self.write_state("a", "SUCCESS")
        self.write_state("b", "FAILED")
        self.write_state("c", "FAILED_MAX_ATTEMPTS")
        got = MODULE.audit(manifest=self.manifest, publish_root=self.root, expected_count=3)
        self.assertEqual(got["status"], "COMPLETE_WITH_TECHNICAL_NA")
        self.assertEqual((got["success_jobs"], got["technical_na_jobs"]), (1, 2))

    def test_running_missing_bad_json_fail_closed(self) -> None:
        self.write_state("a", "RUNNING")
        (self.root / "status/jobs/b.json").write_text("{")
        got = MODULE.audit(manifest=self.manifest, publish_root=self.root, expected_count=3)
        self.assertEqual(got["status"], "INCOMPLETE")
        self.assertEqual(got["terminal_jobs"], 0)
        self.assertEqual(got["missing_job_ids"], ["c"])
        self.assertEqual(got["bad_json_job_ids"], ["b"])

    def test_duplicate_or_wrong_count_rejected(self) -> None:
        with self.manifest.open("a") as handle:
            handle.write("a\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            MODULE.audit(manifest=self.manifest, publish_root=self.root, expected_count=4)


if __name__ == "__main__":
    unittest.main()
