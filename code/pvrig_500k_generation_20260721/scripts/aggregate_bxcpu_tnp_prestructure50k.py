#!/usr/bin/env python3
"""Validate and merge the eight bxcpu TNP result shards."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def selected_ids(path: Path) -> set[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as handle:
        return {row["candidate_id"] for row in csv.DictReader(handle, delimiter="\t")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--expected", type=int, default=50_000)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    shards = sorted(args.input_dir.glob("node_*.tnp.tsv"))
    if len(shards) != 8:
        raise SystemExit(f"expected 8 TNP shards, found {len(shards)}")
    for shard in shards:
        if not shard.with_name(shard.name.replace(".tnp.tsv", ".READY")).exists():
            raise SystemExit(f"missing READY marker for {shard}")

    output = args.output_dir / "tnp_prestructure50000.tsv.gz"
    seen: set[str] = set()
    status_counts: dict[str, int] = {}
    fieldnames: list[str] | None = None
    with gzip.open(output, "wt", newline="") as out_handle:
        writer = None
        for shard in shards:
            with shard.open(newline="") as in_handle:
                reader = csv.DictReader(in_handle, delimiter="\t")
                if fieldnames is None:
                    fieldnames = list(reader.fieldnames or [])
                    writer = csv.DictWriter(
                        out_handle,
                        fieldnames=fieldnames,
                        delimiter="\t",
                        lineterminator="\n",
                    )
                    writer.writeheader()
                elif list(reader.fieldnames or []) != fieldnames:
                    raise SystemExit(f"schema mismatch in {shard}")
                assert writer is not None
                for row in reader:
                    cid = row["candidate_id"]
                    if cid in seen:
                        raise SystemExit(f"duplicate candidate_id: {cid}")
                    seen.add(cid)
                    status = row["status"]
                    status_counts[status] = status_counts.get(status, 0) + 1
                    writer.writerow(row)

    expected_ids = selected_ids(args.selection)
    if len(expected_ids) != args.expected:
        raise SystemExit(f"selection count mismatch: {len(expected_ids)} != {args.expected}")
    if seen != expected_ids:
        raise SystemExit(
            f"TNP ID set mismatch: missing={len(expected_ids-seen)} extra={len(seen-expected_ids)}"
        )

    output_sha = sha256(output)
    receipt = {
        "status": "PASS" if status_counts.get("PASS", 0) == args.expected else "COMPLETE_WITH_TECHNICAL_NA",
        "records": len(seen),
        "status_counts": status_counts,
        "shards": len(shards),
        "output": str(output.resolve()),
        "sha256": output_sha,
        "id_set_exact_match": True,
        "metric_semantics": "TNP structure developability proxy; not measured expression or purity",
    }
    (args.output_dir / "READY.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "SHA256SUMS").write_text(f"{output_sha}  {output.name}\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
