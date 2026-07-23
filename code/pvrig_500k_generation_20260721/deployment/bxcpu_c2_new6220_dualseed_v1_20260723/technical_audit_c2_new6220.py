#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inspect_package(
    key: str,
    manifest: Path,
    publish_root: Path,
    expected_count: int,
    expected_sha256: str,
) -> dict:
    assert sha256(manifest) == expected_sha256
    with manifest.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(rows) == expected_count
    manifest_by_job = {row["job_id"]: row for row in rows}
    job_ids = list(manifest_by_job)
    assert len(set(job_ids)) == expected_count

    states = Counter()
    valid_success = 0
    technical_na = 0
    invalid_success = []
    missing = []
    for job_id in job_ids:
        manifest_row = manifest_by_job[job_id]
        status_path = publish_root / "status/jobs" / f"{job_id}.json"
        result_path = publish_root / "results" / job_id / "job_result.json"
        compact_path = publish_root / "compressed_queue" / f"{job_id}.tar.gz"
        if not status_path.is_file():
            states["MISSING"] += 1
            if len(missing) < 20:
                missing.append(job_id)
            continue
        try:
            status = json.loads(status_path.read_text())
        except Exception:
            states["INVALID_STATUS_JSON"] += 1
            continue
        state = str(status.get("status", "UNKNOWN"))
        states[state] += 1
        if status.get("job_id") != job_id:
            states["STATUS_JOB_ID_MISMATCH"] += 1
            continue
        if state == "SUCCESS":
            try:
                result = json.loads(result_path.read_text())
                ok = result.get("state") == "SUCCESS"
                ok = ok and result.get("job_id") == job_id
                ok = ok and result.get("job_hash") == manifest_row["job_hash"]
                ok = (
                    ok
                    and result.get("protocol_core_sha256")
                    == manifest_row["protocol_core_sha256"]
                )
                ok = ok and (
                    compact_path.is_file()
                    or result.get("offloaded_to_node1") is True
                )
            except Exception:
                ok = False
            if ok:
                valid_success += 1
            elif len(invalid_success) < 20:
                invalid_success.append(job_id)
        elif state in {"FAILED", "FAILED_MAX_ATTEMPTS"}:
            if status.get("job_id") == job_id and int(status.get("attempts", 0)) >= 2:
                technical_na += 1

    terminal = valid_success + technical_na
    return {
        "package_key": key,
        "manifest": str(manifest),
        "manifest_sha256": expected_sha256,
        "expected_jobs": expected_count,
        "valid_success": valid_success,
        "technical_na": technical_na,
        "terminal_jobs": terminal,
        "pending_jobs": expected_count - terminal,
        "status_states": dict(states),
        "invalid_success_examples": invalid_success,
        "missing_examples": missing,
        "status": (
            "COMPLETE_WITH_TECHNICAL_NA"
            if terminal == expected_count and not invalid_success
            else "INCOMPLETE"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-4220", type=Path, required=True)
    parser.add_argument("--manifest-2000", type=Path, required=True)
    parser.add_argument("--publish-root", type=Path, required=True)
    parser.add_argument("--sha-4220", required=True)
    parser.add_argument("--sha-2000", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    a = inspect_package(
        "c2_new4220",
        args.manifest_4220,
        args.publish_root / "batch_4220",
        16880,
        args.sha_4220,
    )
    b = inspect_package(
        "c2_new2000",
        args.manifest_2000,
        args.publish_root / "batch_2000",
        8000,
        args.sha_2000,
    )
    report = {
        "schema_version": "pvrig.c2_new6220.bxcpu_technical_audit.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "expected_jobs": 24880,
        "valid_success": a["valid_success"] + b["valid_success"],
        "technical_na": a["technical_na"] + b["technical_na"],
        "terminal_jobs": a["terminal_jobs"] + b["terminal_jobs"],
        "pending_jobs": a["pending_jobs"] + b["pending_jobs"],
        "packages": {"c2_new4220": a, "c2_new2000": b},
        "technical_failure_semantics": "NA_not_negative",
        "claim_boundary": (
            "Computational Docking geometry only; not binding, Kd, IC50, "
            "expression, purity, or experimental blocking."
        ),
    }
    report["status"] = (
        "COMPLETE_WITH_TECHNICAL_NA"
        if report["terminal_jobs"] == report["expected_jobs"]
        and a["status"] == b["status"] == "COMPLETE_WITH_TECHNICAL_NA"
        else "INCOMPLETE"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    partial = args.output.with_suffix(args.output.suffix + ".partial")
    partial.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    partial.replace(args.output)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
