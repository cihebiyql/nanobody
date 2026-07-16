#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("monitor_phase2_v4_d_readonly.py")
SPEC = importlib.util.spec_from_file_location("monitor_phase2_v4_d_readonly", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


NOW = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def set_mtime(path: Path, timestamp: float) -> None:
    os.utime(path, (timestamp, timestamp))


def job(
    job_id: str,
    entity_id: str,
    entity_type: str,
    conformation: str,
    seed: int,
) -> dict[str, str]:
    return {
        "job_id": job_id,
        "priority": str(seed),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "conformation": conformation,
        "seed": str(seed),
    }


def state(
    status: str,
    *,
    attempts: int,
    updated_at: str,
    completed_at: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status,
        "stage": "complete" if status == "SUCCESS" else "haddock",
        "attempts": attempts,
        "updated_at": updated_at,
    }
    if completed_at:
        payload["completed_at"] = completed_at
    return payload


def result(row: dict[str, str], completed_at: str) -> dict[str, object]:
    return {
        "job_id": row["job_id"],
        "entity_id": row["entity_id"],
        "entity_type": row["entity_type"],
        "dock_conformation": row["conformation"],
        "seed": int(row["seed"]),
        "state": "SUCCESS",
        "selected_model_count": 4,
        "completed_at": completed_at,
    }


def snapshot_tree(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class ReadOnlyV4DMonitorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "v4d"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build_running_fixture(self) -> list[dict[str, str]]:
        rows = [
            job("train-8x-1", "candidate-a", "candidate", "8x6b", 1),
            job("train-8x-2", "candidate-a", "candidate", "8x6b", 2),
            job("train-9e-1", "candidate-a", "candidate", "9e6y", 1),
            job("train-9e-2", "candidate-a", "candidate", "9e6y", 2),
            job("control-8x-1", "control-a", "control", "8x6b", 1),
            job("control-8x-2", "control-a", "control", "8x6b", 2),
        ]
        write_tsv(self.root / "manifests/docking_jobs.tsv", rows)
        write_tsv(
            self.root / "inputs/fullqc290_split_manifest.tsv",
            [{"candidate_id": "candidate-a", "model_split": "OPEN_TRAIN"}],
        )
        states = {
            "train-8x-1": state(
                "SUCCESS", attempts=1, updated_at="2026-07-16T11:30:00+00:00",
                completed_at="2026-07-16T11:30:00+00:00",
            ),
            "train-8x-2": state(
                "SUCCESS", attempts=2, updated_at="2026-07-16T11:45:00+00:00",
                completed_at="2026-07-16T11:45:00+00:00",
            ),
            "train-9e-1": state(
                "RUNNING", attempts=1, updated_at="2026-07-16T10:00:00+00:00",
            ),
            "control-8x-1": state(
                "SUCCESS", attempts=1, updated_at="2026-07-16T11:15:00+00:00",
                completed_at="2026-07-16T11:15:00+00:00",
            ),
            "control-8x-2": state(
                "SUCCESS", attempts=1, updated_at="2026-07-16T11:50:00+00:00",
                completed_at="2026-07-16T11:50:00+00:00",
            ),
        }
        by_id = {row["job_id"]: row for row in rows}
        for job_id, payload in states.items():
            path = self.root / "status/jobs" / f"{job_id}.json"
            write_json(path, payload)
            set_mtime(path, NOW.timestamp() - 30)
            if payload["status"] == "SUCCESS":
                result_path = self.root / "results" / job_id / "job_result.json"
                write_json(result_path, result(by_id[job_id], str(payload["completed_at"])))
                set_mtime(result_path, NOW.timestamp() - 20)
        controller = self.root / "status/controller.json"
        write_json(
            controller,
            {
                "status": "RUNNING",
                "controller_pid": 12345,
                "selected_job_count": len(rows),
                "max_parallel": 12,
                "parallel_limit": 12,
            },
        )
        set_mtime(controller, NOW.timestamp() - 10)
        summary = self.root / "status/summary.json"
        write_json(summary, {"total_jobs": 6, "counts": {"PENDING": 6}})
        set_mtime(summary, NOW.timestamp() - 4000)
        return rows

    def build_complete_fixture(self) -> list[dict[str, str]]:
        rows = [
            job("done-1", "candidate-done", "candidate", "8x6b", 1),
            job("done-2", "candidate-done", "candidate", "8x6b", 2),
        ]
        write_tsv(self.root / "manifests/docking_jobs.tsv", rows)
        for index, row in enumerate(rows):
            completed = f"2026-07-16T11:{40 + index:02d}:00+00:00"
            state_path = self.root / "status/jobs" / f"{row['job_id']}.json"
            write_json(
                state_path,
                state("SUCCESS", attempts=1, updated_at=completed, completed_at=completed),
            )
            result_path = self.root / "results" / row["job_id"] / "job_result.json"
            write_json(result_path, result(row, completed))
            set_mtime(state_path, NOW.timestamp() - 30)
            set_mtime(result_path, NOW.timestamp() - 20)
        controller = self.root / "status/controller.json"
        write_json(
            controller,
            {"status": "COMPLETE", "controller_pid": 12345, "selected_job_count": 2},
        )
        set_mtime(controller, NOW.timestamp() - 10)
        summary = self.root / "status/summary.json"
        write_json(summary, {"total_jobs": 2, "counts": {"SUCCESS": 2}})
        set_mtime(summary, NOW.timestamp() - 5)
        return rows

    def test_running_snapshot_reports_grouped_progress_stale_attempts_and_eta(self) -> None:
        self.build_running_fixture()

        payload = MOD.summarize(self.root, now=NOW, stale_seconds=3600)

        self.assertEqual(payload["total_jobs"], 6)
        self.assertEqual(payload["status_counts"], {"PENDING": 1, "RUNNING": 1, "SUCCESS": 4})
        self.assertEqual(payload["by_entity_type"]["candidate"], {"PENDING": 1, "RUNNING": 1, "SUCCESS": 2})
        self.assertEqual(payload["by_conformation"]["8x6b"], {"SUCCESS": 4})
        self.assertEqual(payload["by_model_split"]["OPEN_TRAIN"], {"PENDING": 1, "RUNNING": 1, "SUCCESS": 2})
        self.assertEqual(payload["by_model_split"]["CONTROL"], {"SUCCESS": 2})
        self.assertEqual(payload["seed_coverage"]["entity_conformations_at_least_threshold"], 2)
        self.assertEqual(payload["seed_coverage"]["expected_entity_conformations"], 3)
        self.assertEqual(payload["stale"]["stale_active_count"], 1)
        self.assertEqual(payload["stale"]["stale_active_jobs"][0]["job_id"], "train-9e-1")
        self.assertEqual(payload["attempts"]["total_attempts"], 6)
        self.assertEqual(payload["attempts"]["retried_jobs"], 1)
        self.assertEqual(payload["attempts"]["max_attempts_observed"], 2)
        self.assertEqual(payload["throughput"]["completed_in_window"], 4)
        self.assertEqual(payload["throughput"]["jobs_per_hour"], 4.0)
        self.assertEqual(payload["throughput"]["eta_seconds"], 1800.0)
        self.assertTrue(payload["summary_staleness"]["stale"])
        self.assertIn("status_counts_mismatch", payload["summary_staleness"]["reasons"])
        self.assertEqual(payload["controller_health"]["health"], "DEGRADED_STALE_ACTIVE")
        self.assertEqual(payload["controller_health"]["pid_liveness"], "NOT_CHECKED_CROSS_HOST_SAFE")
        self.assertEqual(payload["result_evidence"]["valid_success_results"], 4)
        self.assertEqual(payload["result_evidence"]["success_states_without_valid_result"], [])

    def test_complete_snapshot_without_split_has_healthy_controller_and_fresh_summary(self) -> None:
        self.build_complete_fixture()

        payload = MOD.summarize(self.root, now=NOW)

        self.assertIsNone(payload["by_model_split"])
        self.assertIsNone(payload["seed_coverage"]["by_model_split"])
        self.assertEqual(payload["status_counts"], {"SUCCESS": 2})
        self.assertEqual(payload["controller_health"]["health"], "HEALTHY_COMPLETE")
        self.assertFalse(payload["summary_staleness"]["stale"])
        self.assertEqual(payload["throughput"]["remaining_nonterminal_jobs"], 0)
        self.assertEqual(payload["throughput"]["eta_seconds"], 0.0)

    def test_cli_output_is_outside_root_and_does_not_mutate_monitored_tree(self) -> None:
        self.build_complete_fixture()
        before = snapshot_tree(self.root)
        output = self.base / "sidecar-output.json"
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            return_code = MOD.main(
                [
                    str(self.root),
                    "--now", "2026-07-16T12:00:00+00:00",
                    "--output", str(output),
                ]
            )

        self.assertEqual(return_code, 0)
        self.assertEqual(snapshot_tree(self.root), before)
        self.assertEqual(json.loads(stdout.getvalue()), json.loads(output.read_text(encoding="utf-8")))
        with self.assertRaisesRegex(MOD.MonitorError, "outside the monitored project root"):
            MOD.write_output(self.root / "status/forbidden.json", {"x": 1}, self.root)
        self.assertFalse((self.root / "status/forbidden.json").exists())

    def test_malformed_result_and_orphan_files_are_reported_without_becoming_success_evidence(self) -> None:
        rows = [job("bad-result", "candidate-bad", "candidate", "8x6b", 1)]
        write_tsv(self.root / "manifests/docking_jobs.tsv", rows)
        write_json(
            self.root / "status/jobs/bad-result.json",
            state(
                "SUCCESS", attempts=1, updated_at="2026-07-16T11:30:00+00:00",
                completed_at="2026-07-16T11:30:00+00:00",
            ),
        )
        malformed = self.root / "results/bad-result/job_result.json"
        malformed.parent.mkdir(parents=True)
        malformed.write_text("not-json", encoding="utf-8")
        write_json(self.root / "results/orphan/job_result.json", {"state": "SUCCESS"})

        payload = MOD.summarize(self.root, now=NOW)

        self.assertEqual(payload["result_evidence"]["valid_success_results"], 0)
        self.assertIn("bad-result", payload["result_evidence"]["malformed_results"])
        self.assertEqual(payload["result_evidence"]["success_states_without_valid_result"], ["bad-result"])
        self.assertEqual(len(payload["result_evidence"]["orphan_result_files"]), 1)


if __name__ == "__main__":
    unittest.main()
