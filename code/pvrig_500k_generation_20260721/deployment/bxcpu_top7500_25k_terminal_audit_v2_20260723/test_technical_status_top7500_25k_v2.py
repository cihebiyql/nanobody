#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("technical_status_top7500_25k_v2", HERE / "technical_status_top7500_25k_v2.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class TechnicalStatusV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.manifest = self.root / "jobs.tsv"
        with self.manifest.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["job_id"], delimiter="\t")
            writer.writeheader()
            writer.writerows([{"job_id": "a"}, {"job_id": "b"}, {"job_id": "c"}])
        (self.root / "status/jobs").mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_state(self, job_id: str, state: str) -> None:
        (self.root / "status/jobs" / f"{job_id}.json").write_text(json.dumps({"status": state}))

    def test_failed_is_terminal_technical_na(self) -> None:
        self.write_state("a", "SUCCESS")
        self.write_state("b", "FAILED")
        self.write_state("c", "FAILED_MAX_ATTEMPTS")
        result = MODULE.audit(manifest=self.manifest, publish_root=self.root, expected_count=3)
        self.assertEqual(result["status"], "COMPLETE_WITH_TECHNICAL_NA")
        self.assertEqual(result["success_jobs"], 1)
        self.assertEqual(result["technical_na_jobs"], 2)
        self.assertEqual(result["terminal_jobs"], 3)

    def test_missing_is_not_terminal(self) -> None:
        self.write_state("a", "SUCCESS")
        self.write_state("b", "FAILED")
        result = MODULE.audit(manifest=self.manifest, publish_root=self.root, expected_count=3)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["missing_job_ids"], ["c"])

    def test_running_is_not_terminal(self) -> None:
        self.write_state("a", "SUCCESS")
        self.write_state("b", "FAILED")
        self.write_state("c", "RUNNING")
        result = MODULE.audit(manifest=self.manifest, publish_root=self.root, expected_count=3)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["terminal_jobs"], 2)

    def test_wrong_manifest_count_fails_closed(self) -> None:
        for job_id in ("a", "b", "c"):
            self.write_state(job_id, "SUCCESS")
        result = MODULE.audit(manifest=self.manifest, publish_root=self.root, expected_count=4)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertFalse(result["manifest_count_ok"])


if __name__ == "__main__":
    unittest.main()
