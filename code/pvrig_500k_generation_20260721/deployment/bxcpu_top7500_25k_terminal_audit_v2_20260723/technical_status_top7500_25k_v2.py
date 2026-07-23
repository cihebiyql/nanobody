#!/usr/bin/env python3
"""Fail-closed terminal status audit for the frozen Top7500 25k campaign.

This is deliberately a versioned audit-only replacement.  It does not mutate
or resubmit any Docking job from the frozen v1 campaign.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import pathlib
from datetime import datetime, timezone


TERMINAL_SUCCESS = {"SUCCESS"}
TERMINAL_TECHNICAL_NA = {"FAILED", "FAILED_MAX_ATTEMPTS"}
TERMINAL_STATES = TERMINAL_SUCCESS | TERMINAL_TECHNICAL_NA


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_expected_jobs(manifest: pathlib.Path) -> list[str]:
    with manifest.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows or "job_id" not in rows[0]:
        raise ValueError("manifest_missing_job_id_or_empty")
    jobs = [row["job_id"] for row in rows]
    if any(not job for job in jobs):
        raise ValueError("manifest_contains_empty_job_id")
    if len(jobs) != len(set(jobs)):
        raise ValueError("manifest_contains_duplicate_job_id")
    return jobs


def audit(
    *, manifest: pathlib.Path, publish_root: pathlib.Path, expected_count: int
) -> dict[str, object]:
    expected = load_expected_jobs(manifest)
    counts: collections.Counter[str] = collections.Counter()
    bad_json_jobs: list[str] = []
    missing_jobs: list[str] = []
    for job_id in expected:
        status_path = publish_root / "status" / "jobs" / f"{job_id}.json"
        if not status_path.is_file():
            counts["MISSING"] += 1
            missing_jobs.append(job_id)
            continue
        try:
            payload = json.loads(status_path.read_text())
            state = payload.get("status", "UNKNOWN")
            if not isinstance(state, str):
                state = "INVALID_STATUS_TYPE"
        except Exception:
            state = "INVALID_JSON"
            bad_json_jobs.append(job_id)
        counts[state] += 1

    success = sum(counts[state] for state in TERMINAL_SUCCESS)
    technical_na = sum(counts[state] for state in TERMINAL_TECHNICAL_NA)
    terminal = success + technical_na
    manifest_count_ok = len(expected) == expected_count
    all_terminal = terminal == expected_count
    status = "COMPLETE_WITH_TECHNICAL_NA" if manifest_count_ok and all_terminal else "INCOMPLETE"
    return {
        "schema_version": "pvrig_top7500_25k_technical_status_v2",
        "status": status,
        "expected_jobs": len(expected),
        "required_expected_jobs": expected_count,
        "terminal_jobs": terminal,
        "success_jobs": success,
        "technical_na_jobs": technical_na,
        "state_counts": dict(sorted(counts.items())),
        "manifest_sha256": sha256_file(manifest),
        "manifest_count_ok": manifest_count_ok,
        "all_expected_jobs_terminal": all_terminal,
        "bad_json_job_ids": bad_json_jobs,
        "missing_job_ids": missing_jobs,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_boundary": (
            "Technical completion of the frozen old priority/S0-selected 25k Docking campaign only; "
            "FAILED states are technical NA, never biological negatives; this campaign is not an "
            "overall prospective evaluation of the later C2-refined Top7500 panel."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    parser.add_argument("--publish-root", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--expected-count", type=int, default=25_000)
    args = parser.parse_args()
    payload = audit(
        manifest=args.manifest,
        publish_root=args.publish_root,
        expected_count=args.expected_count,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
