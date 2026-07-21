#!/usr/bin/env python3
"""Verify and merge bxcpu CPU-generation archives without extracting them."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import tarfile
from collections import Counter, defaultdict
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_hash(path: Path) -> str:
    fields = path.read_text(encoding="utf-8").strip().split()
    if len(fields) < 2:
        raise ValueError(f"invalid checksum file: {path}")
    return fields[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source = args.input_dir.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)

    archives = sorted(source.glob("node_*/cpu_node_*.tar.gz"))
    if len(archives) != 8:
        raise ValueError(f"expected 8 node archives, found {len(archives)}")

    ready_rows = []
    for archive in archives:
        ready = json.loads((archive.parent / "READY.json").read_text(encoding="utf-8"))
        if ready.get("status") != "READY":
            raise ValueError(f"node is not READY: {archive.parent}")
        actual = sha256_file(archive)
        expected = expected_hash(archive.with_suffix(archive.suffix + ".sha256"))
        if actual != expected:
            raise ValueError(f"archive checksum mismatch: {archive}")
        ready_rows.append(ready)

    output_fields: list[str] | None = None
    all_writer = pass_writer = fail_writer = None
    all_handle = gzip.open(output / "all_raw.tsv.gz", "wt", encoding="utf-8", newline="", compresslevel=1)
    pass_handle = gzip.open(output / "fast_qc_pass.tsv.gz", "wt", encoding="utf-8", newline="", compresslevel=1)
    fail_handle = gzip.open(output / "fast_qc_fail.tsv.gz", "wt", encoding="utf-8", newline="", compresslevel=1)
    task_ids: set[str] = set()
    pass_sequences: set[str] = set()
    route_counts: Counter[str] = Counter()
    route_pass_counts: Counter[str] = Counter()
    route_mode_pass_counts: Counter[tuple[str, str]] = Counter()
    route_unique_sequences: dict[str, set[str]] = defaultdict(set)
    route_mode_unique_sequences: dict[tuple[str, str], set[str]] = defaultdict(set)
    raw_count = pass_count = fail_count = 0
    try:
        for archive in archives:
            with tarfile.open(archive, "r:gz") as tar:
                members = sorted(
                    (member for member in tar.getmembers() if member.name.endswith(".raw.tsv")),
                    key=lambda member: member.name,
                )
                if len(members) != 64:
                    raise ValueError(f"expected 64 raw shards in {archive}, found {len(members)}")
                for member in members:
                    binary = tar.extractfile(member)
                    if binary is None:
                        raise ValueError(f"cannot read {member.name} from {archive}")
                    rows = csv.DictReader(io.TextIOWrapper(binary, encoding="utf-8"), delimiter="\t")
                    if rows.fieldnames is None:
                        raise ValueError(f"missing header: {archive}:{member.name}")
                    enriched_fields = list(rows.fieldnames) + ["bxcpu_source_archive", "bxcpu_source_member"]
                    if output_fields is None:
                        output_fields = enriched_fields
                        all_writer = csv.DictWriter(all_handle, fieldnames=output_fields, delimiter="\t")
                        pass_writer = csv.DictWriter(pass_handle, fieldnames=output_fields, delimiter="\t")
                        fail_writer = csv.DictWriter(fail_handle, fieldnames=output_fields, delimiter="\t")
                        all_writer.writeheader(); pass_writer.writeheader(); fail_writer.writeheader()
                    elif enriched_fields != output_fields:
                        raise ValueError(f"field mismatch: {archive}:{member.name}")
                    for row in rows:
                        task_id = row["task_id"]
                        if task_id in task_ids:
                            raise ValueError(f"duplicate task_id: {task_id}")
                        task_ids.add(task_id)
                        row["bxcpu_source_archive"] = archive.name
                        row["bxcpu_source_member"] = member.name
                        assert all_writer is not None and pass_writer is not None and fail_writer is not None
                        all_writer.writerow(row)
                        raw_count += 1
                        route = row["route_id"]
                        route_counts[route] += 1
                        if row["fast_qc_status"] == "PASS":
                            pass_writer.writerow(row)
                            pass_count += 1
                            route_pass_counts[route] += 1
                            mode = row["design_mode"]
                            route_mode_pass_counts[(route, mode)] += 1
                            sequence = row["sequence"]
                            pass_sequences.add(sequence)
                            route_unique_sequences[route].add(sequence)
                            route_mode_unique_sequences[(route, mode)].add(sequence)
                        else:
                            fail_writer.writerow(row)
                            fail_count += 1
    finally:
        all_handle.close(); pass_handle.close(); fail_handle.close()

    expected_raw = sum(int(row["raw_count"]) for row in ready_rows)
    expected_pass = sum(int(row["fast_qc_pass_count"]) for row in ready_rows)
    if raw_count != expected_raw or pass_count != expected_pass:
        raise ValueError(
            f"READY count mismatch raw={raw_count}/{expected_raw}, pass={pass_count}/{expected_pass}"
        )
    receipt = {
        "status": "MERGED_FAST_QC_ONLY_NOT_FINAL_ANARCI",
        "node_count": len(archives),
        "raw_count": raw_count,
        "fast_qc_pass_count": pass_count,
        "fast_qc_fail_count": fail_count,
        "exact_unique_fast_qc_pass_count": len(pass_sequences),
        "duplicate_task_id_count": raw_count - len(task_ids),
        "route_raw_counts": dict(sorted(route_counts.items())),
        "route_fast_qc_pass_counts": dict(sorted(route_pass_counts.items())),
        "route_exact_unique_fast_qc_pass_counts": {
            key: len(value) for key, value in sorted(route_unique_sequences.items())
        },
        "route_mode_fast_qc_pass_counts": {
            f"{route}|{mode}": count
            for (route, mode), count in sorted(route_mode_pass_counts.items())
        },
        "route_mode_exact_unique_fast_qc_pass_counts": {
            f"{route}|{mode}": len(value)
            for (route, mode), value in sorted(route_mode_unique_sequences.items())
        },
        "note": "Fast-QC PASS is not final eligibility; ANARCI/IMGT and global family controls remain required.",
    }
    (output / "MERGE_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
