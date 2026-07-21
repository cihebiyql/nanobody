#!/usr/bin/env python3
"""Prepare all unused fast-QC-passing local candidates for ANARCI top-up."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def unused_fast_qc_passes(
    raw: list[dict[str, str]], primary: list[dict[str, str]]
) -> list[dict[str, str]]:
    used = {row["candidate_id"] for row in primary}
    return [
        row
        for row in raw
        if row["fast_qc_status"] == "PASS" and row["candidate_id"] not in used
    ]


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError("no supplemental candidates available")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def write_fasta(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    args = parser.parse_args()
    campaign = args.campaign_dir.resolve()
    rows = unused_fast_qc_passes(
        read_tsv(campaign / "raw" / "local_cpu_routes_raw.tsv"),
        read_tsv(campaign / "qc" / "local_cpu_routes_pre_anarci.tsv"),
    )
    tsv = campaign / "qc" / "local_cpu_routes_supplemental_pre_anarci.tsv"
    fasta = campaign / "qc" / "local_cpu_routes_supplemental_pre_anarci.fasta"
    write_tsv(tsv, rows)
    write_fasta(fasta, rows)
    summary = {
        "status": "READY_FOR_SUPPLEMENTAL_ANARCI",
        "supplemental_candidates": len(rows),
        "by_route": dict(sorted(Counter(row["route_id"] for row in rows).items())),
        "tsv": str(tsv.relative_to(campaign)),
        "fasta": str(fasta.relative_to(campaign)),
    }
    (campaign / "status" / "LOCAL_CPU_ANARCI_TOPUP_READY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
