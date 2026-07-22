#!/usr/bin/env python3
"""Union deterministic incompatibilities with observed NBB2/TNP technical failures."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path


def op(path: Path, mode: str):
    return gzip.open(path, mode, newline="") if path.suffix == ".gz" else path.open(mode, newline="")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_metric(paths: list[Path], expected_status: str) -> tuple[dict[str, str], dict[str, str]]:
    statuses: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for path in paths:
        with op(path, "rt") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            required = {"candidate_id", "status", "failure_reason"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise SystemExit(f"{path}: metric fields missing {sorted(missing)}")
            for row in reader:
                candidate_id = row["candidate_id"]
                if candidate_id in statuses:
                    raise SystemExit(f"duplicate metric candidate_id: {candidate_id}")
                statuses[candidate_id] = row["status"]
                if row["status"] != expected_status:
                    reasons[candidate_id] = row.get("failure_reason", "")
    return statuses, reasons


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, action="append", required=True)
    parser.add_argument("--base-invalid", type=Path, required=True)
    parser.add_argument("--nbb2", type=Path, action="append", required=True)
    parser.add_argument("--tnp", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected", type=int, default=700000)
    args = parser.parse_args()

    candidates: dict[str, dict[str, str]] = {}
    for path in args.candidates:
        with op(path, "rt") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            required = {"candidate_id", "route_id", "sequence"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise SystemExit(f"{path}: candidate fields missing {sorted(missing)}")
            for row in reader:
                candidate_id = row["candidate_id"]
                if candidate_id in candidates:
                    raise SystemExit(f"duplicate candidate_id: {candidate_id}")
                candidates[candidate_id] = row
    if len(candidates) != args.expected:
        raise SystemExit(f"candidate records {len(candidates)} != {args.expected}")

    base_ids: set[str] = set()
    with op(args.base_invalid, "rt") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            candidate_id = row["candidate_id"]
            if candidate_id in base_ids:
                raise SystemExit(f"duplicate base-invalid candidate_id: {candidate_id}")
            base_ids.add(candidate_id)
    if not base_ids <= set(candidates):
        raise SystemExit(f"base-invalid IDs outside candidate set: {len(base_ids-set(candidates))}")

    nbb2_status, nbb2_reasons = load_metric(args.nbb2, "SUCCESS")
    tnp_status, tnp_reasons = load_metric(args.tnp, "PASS")
    candidate_ids = set(candidates)
    if set(nbb2_status) != candidate_ids:
        raise SystemExit(
            f"NBB2 ID closure mismatch missing={len(candidate_ids-set(nbb2_status))} "
            f"extra={len(set(nbb2_status)-candidate_ids)}"
        )
    if set(tnp_status) != candidate_ids:
        raise SystemExit(
            f"TNP ID closure mismatch missing={len(candidate_ids-set(tnp_status))} "
            f"extra={len(set(tnp_status)-candidate_ids)}"
        )

    nbb2_fail = {candidate_id for candidate_id, status in nbb2_status.items() if status != "SUCCESS"}
    tnp_fail = {candidate_id for candidate_id, status in tnp_status.items() if status != "PASS"}
    invalid_ids = base_ids | nbb2_fail | tnp_fail
    fields = [
        "candidate_id", "route_id", "parent_cluster", "base_incompatible",
        "nbb2_status", "nbb2_failure_reason", "tnp_status", "tnp_failure_reason",
        "technical_failure_sources",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    route_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    with gzip.open(args.output, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for candidate_id in sorted(invalid_ids):
            sources = []
            if candidate_id in base_ids:
                sources.append("CALIBRATED_NBB2_INCOMPATIBLE")
            if candidate_id in nbb2_fail:
                sources.append("OBSERVED_NBB2_TECHNICAL_NA")
            if candidate_id in tnp_fail:
                sources.append("OBSERVED_TNP_TECHNICAL_NA")
            for source in sources:
                source_counts[source] += 1
            route = candidates[candidate_id]["route_id"]
            route_counts[route] += 1
            writer.writerow({
                "candidate_id": candidate_id,
                "route_id": route,
                "parent_cluster": candidates[candidate_id].get("parent_cluster", ""),
                "base_incompatible": str(candidate_id in base_ids).lower(),
                "nbb2_status": nbb2_status[candidate_id],
                "nbb2_failure_reason": nbb2_reasons.get(candidate_id, ""),
                "tnp_status": tnp_status[candidate_id],
                "tnp_failure_reason": tnp_reasons.get(candidate_id, ""),
                "technical_failure_sources": ";".join(sources),
            })

    payload = {
        "status": "READY_FOR_ROUTE_MATCHED_REPLACEMENT",
        "candidate_records": args.expected,
        "base_incompatible_records": len(base_ids),
        "observed_nbb2_failure_records": len(nbb2_fail),
        "observed_tnp_failure_records": len(tnp_fail),
        "invalid_union_records": len(invalid_ids),
        "invalid_route_counts": dict(sorted(route_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "technical_na_is_not_biological_negative": True,
        "output": str(args.output.resolve()),
        "output_sha256": sha(args.output),
    }
    args.receipt.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
