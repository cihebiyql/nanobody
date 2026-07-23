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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--publish-root", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    assert sha256(args.manifest) == args.manifest_sha256
    with args.manifest.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(rows) == 16880
    assert {row["seed"] for row in rows} == {"42", "3047"}
    assert {row["conformation"] for row in rows} == {"8x6b", "9e6y"}
    states: Counter[str] = Counter()
    valid_success = technical_na = 0
    invalid_success: list[str] = []
    for row in rows:
        job_id = row["job_id"]
        status_path = args.publish_root / "status/jobs" / f"{job_id}.json"
        result_path = args.publish_root / "results" / job_id / "job_result.json"
        compact_path = args.publish_root / "compressed_queue" / f"{job_id}.tar.gz"
        if not status_path.is_file():
            states["MISSING"] += 1
            continue
        try:
            status = json.loads(status_path.read_text())
        except Exception:
            states["INVALID_STATUS_JSON"] += 1
            continue
        state = str(status.get("status", "UNKNOWN"))
        states[state] += 1
        if state == "SUCCESS":
            try:
                result = json.loads(result_path.read_text())
                ok = result.get("state") == "SUCCESS"
                ok = ok and result.get("job_id") == job_id
                ok = ok and result.get("job_hash") == row["job_hash"]
                ok = ok and (
                    compact_path.is_file() or result.get("offloaded_to_node1") is True
                )
            except Exception:
                ok = False
            if ok:
                valid_success += 1
            elif len(invalid_success) < 20:
                invalid_success.append(job_id)
        elif state in {"FAILED", "FAILED_MAX_ATTEMPTS"} and int(status.get("attempts", 0)) >= 2:
            technical_na += 1
    terminal = valid_success + technical_na
    report = {
        "schema_version": "pvrig.c2_new4220.seed42_3047.technical_audit.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "expected_jobs": 16880,
        "valid_success": valid_success,
        "technical_na": technical_na,
        "terminal_jobs": terminal,
        "pending_jobs": 16880 - terminal,
        "status_states": dict(states),
        "invalid_success_examples": invalid_success,
        "technical_failure_semantics": "NA_not_negative",
        "claim_boundary": "Computational Docking geometry only; not binding, Kd, IC50, purity, expression, or experimental blocking.",
    }
    report["status"] = (
        "COMPLETE_WITH_TECHNICAL_NA"
        if terminal == 16880 and not invalid_success
        else "INCOMPLETE"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(".partial")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    tmp.replace(args.output)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
