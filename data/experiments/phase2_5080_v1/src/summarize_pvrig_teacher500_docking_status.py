#!/usr/bin/env python3
"""Summarize the latest per-candidate state of a sharded Teacher500 run."""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Sequence


EXIT_RE = re.compile(r"^HADDOCK_EXIT\s+(\S+)\s+rc=(\d+)\b")
START_RE = re.compile(r"^HADDOCK_START\s+(\S+)\b")


def candidate_shards(root: Path) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for manifest in sorted(root.glob("shard_*/manifests/selected_candidates_manifest.tsv")):
        with manifest.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                candidate_id = row["candidate_id"]
                if candidate_id in mapping:
                    raise ValueError(f"Duplicate candidate_id across shards: {candidate_id}")
                mapping[candidate_id] = manifest.parents[1]
    return mapping


def latest_events(root: Path) -> tuple[set[str], dict[str, int]]:
    started: set[str] = set()
    latest: dict[str, int] = {}
    logs = sorted(
        root.glob("shard_*/logs/run_node1_v2_5_pose_batch.*.log"),
        key=lambda path: (path.name, str(path)),
    )
    for log in logs:
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            match = START_RE.match(line)
            if match:
                started.add(match.group(1))
                continue
            match = EXIT_RE.match(line)
            if match:
                latest[match.group(1)] = int(match.group(2))
    return started, latest


def selected_model_count(shard_root: Path, candidate_id: str) -> int:
    selected = (
        shard_root
        / "haddock3"
        / candidate_id
        / f"run_{candidate_id}_pvrig_hotspot"
        / "6_seletopclusts"
    )
    names = {
        path.name.removesuffix(".pdb.gz").removesuffix(".pdb")
        for path in selected.glob("cluster_*_model_*.pdb*")
    }
    return len(names)


def summarize(root: Path, expected_candidates: int, min_models: int) -> dict[str, int]:
    mapping = candidate_shards(root)
    if len(mapping) != expected_candidates:
        raise ValueError(f"Expected {expected_candidates} manifest candidates, found {len(mapping)}")
    started, latest = latest_events(root)
    unknown = sorted((started | set(latest)) - set(mapping))
    if unknown:
        raise ValueError(f"Runtime logs contain unknown candidates: {unknown[:5]}")

    model_counts = {candidate_id: selected_model_count(shard, candidate_id) for candidate_id, shard in mapping.items()}
    latest_success = sum(latest.get(candidate_id) == 0 for candidate_id in mapping)
    latest_failed = sum(latest.get(candidate_id, 0) != 0 for candidate_id in mapping if candidate_id in latest)
    return {
        "complete": int((root / "docking.complete").is_file()),
        "expected": expected_candidates,
        "unique_started": len(started),
        "latest_success": latest_success,
        "latest_failed": latest_failed,
        "pending": expected_candidates - latest_success - latest_failed,
        "model_ready": sum(count >= min_models for count in model_counts.values()),
        "top_models": sum(model_counts.values()),
    }


def controller_state(root: Path) -> dict[str, int]:
    pid = 0
    try:
        pid = int((root / "controller.pid").read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        pass
    return {"alive": int(pid > 0 and Path(f"/proc/{pid}").exists()), "pid": pid}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--expected-candidates", type=int, default=500)
    parser.add_argument("--min-models", type=int, default=4)
    args = parser.parse_args(argv)
    if args.expected_candidates <= 0 or args.min_models <= 0:
        parser.error("Expected candidates and minimum models must be positive")
    return args


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    status = {**summarize(args.root, args.expected_candidates, args.min_models), **controller_state(args.root)}
    order = (
        "complete", "alive", "pid", "expected", "unique_started", "latest_success",
        "latest_failed", "pending", "model_ready", "top_models",
    )
    print(" ".join(str(status[key]) for key in order))


if __name__ == "__main__":
    main()
