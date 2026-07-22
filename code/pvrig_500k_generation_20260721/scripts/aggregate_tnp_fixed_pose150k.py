#!/usr/bin/env python3
"""Merge four exact-ID TNP wave aggregates for the fixed-pose top-150k set."""

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
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def selected_ids(path: Path) -> set[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as handle:
        return {row["candidate_id"] for row in csv.DictReader(handle, delimiter="\t")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--expected", required=True, type=int)
    args = parser.parse_args()

    wave_tables = sorted(args.input_root.glob("wave_*/tnp_aggregate/tnp_all.tsv.gz"))
    if len(wave_tables) != 4:
        raise SystemExit(f"expected 4 wave tables, found {len(wave_tables)}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "tnp_fixed_pose_top150k.tsv.gz"
    fields: list[str] | None = None
    seen: set[str] = set()
    counts: dict[str, int] = {}
    with gzip.open(output, "wt", newline="") as dst:
        writer = None
        for table in wave_tables:
            with gzip.open(table, "rt", newline="") as src:
                reader = csv.DictReader(src, delimiter="\t")
                current = list(reader.fieldnames or [])
                if fields is None:
                    fields = current
                    writer = csv.DictWriter(dst, fieldnames=fields, delimiter="\t", lineterminator="\n")
                    writer.writeheader()
                elif current != fields:
                    raise SystemExit(f"schema mismatch: {table}")
                assert writer is not None
                for row in reader:
                    candidate_id = row["candidate_id"]
                    if candidate_id in seen:
                        raise SystemExit(f"duplicate candidate_id: {candidate_id}")
                    seen.add(candidate_id)
                    counts[row["status"]] = counts.get(row["status"], 0) + 1
                    writer.writerow(row)

    expected_ids = selected_ids(args.selection)
    if len(expected_ids) != args.expected or seen != expected_ids:
        raise SystemExit(
            f"exact-ID mismatch expected_selection={len(expected_ids)} observed={len(seen)}"
        )

    digest = sha256(output)
    receipt = {
        "status": "PASS" if counts.get("PASS", 0) == args.expected else "COMPLETE_WITH_TECHNICAL_NA",
        "records": len(seen),
        "status_counts": counts,
        "waves": 4,
        "id_set_exact_match": True,
        "technical_na_is_not_negative": True,
        "output": str(output.resolve()),
        "sha256": digest,
        "scientific_boundary": "TNP structure developability proxy; not measured expression or purity",
    }
    (args.output_dir / "READY.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "SHA256SUMS").write_text(f"{digest}  {output.name}\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

