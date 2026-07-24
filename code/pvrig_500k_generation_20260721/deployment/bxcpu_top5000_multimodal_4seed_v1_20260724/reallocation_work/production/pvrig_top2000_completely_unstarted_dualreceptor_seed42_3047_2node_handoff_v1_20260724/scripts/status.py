#!/usr/bin/env python3
"""Summarize local or node1 V3 docking progress without modifying job states."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from common import project_root, read_json, read_tsv, write_json


def root() -> Path:
    return Path(os.environ.get("PVRIG_PROJECT_ROOT", project_root())).resolve()


def pid_alive(value: object) -> bool:
    try:
        os.kill(int(value), 0)
        return True
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def summarize() -> dict[str, object]:
    manifest_path = root() / "manifests/docking_jobs.tsv"
    rows = read_tsv(manifest_path) if manifest_path.is_file() else []
    counts: Counter[str] = Counter()
    by_type: dict[str, Counter[str]] = defaultdict(Counter)
    by_conformation: dict[str, Counter[str]] = defaultdict(Counter)
    success_seeds: dict[tuple[str, str], set[str]] = defaultdict(set)
    stale_active: list[str] = []
    for row in rows:
        state = read_json(root() / "status/jobs" / f"{row['job_id']}.json", {})
        status = str(state.get("status") or "PENDING")
        counts[status] += 1
        by_type[row["entity_type"]][status] += 1
        by_conformation[row["conformation"]][status] += 1
        if status in {"QUEUED", "RUNNING"} and not pid_alive(state.get("pid")):
            stale_active.append(row["job_id"])
        if status == "SUCCESS":
            success_seeds[(row["entity_id"], row["conformation"])].add(row["seed"])
    minimum = 2
    pairs_at_least_two = sum(len(seeds) >= minimum for seeds in success_seeds.values())
    expected_pairs = len({row["entity_id"] for row in rows}) * 2 if rows else 0
    controller = read_json(root() / "status/controller.json", {})
    return {
        "manifest": str(manifest_path),
        "total_jobs": len(rows),
        "counts": dict(sorted(counts.items())),
        "by_entity_type": {key: dict(sorted(value.items())) for key, value in sorted(by_type.items())},
        "by_conformation": {key: dict(sorted(value.items())) for key, value in sorted(by_conformation.items())},
        "entity_conformations_with_at_least_2_successful_seeds": pairs_at_least_two,
        "expected_entity_conformations": expected_pairs,
        "stale_active_count": len(stale_active),
        "stale_active_jobs": stale_active[:50],
        "controller": controller,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = summarize()
        write_json(root() / "status/summary.json", payload)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"TOTAL\t{payload['total_jobs']}")
            for key, value in payload["counts"].items():
                print(f"{key}\t{value}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
