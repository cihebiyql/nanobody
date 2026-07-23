#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INPUTS = ROOT / "inputs"
OUTPUT = ROOT / "dispatch_shards"
PACKAGES = {
    "c2_new4220": INPUTS / "c2_new4220_docking_jobs.tsv",
    "c2_new2000": INPUTS / "c2_new2000_docking_jobs.tsv",
}
EXPECTED = {"c2_new4220": 16880, "c2_new2000": 8000}
SHARDS = 8


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    writers = []
    handles = []
    shard_counts = [Counter() for _ in range(SHARDS)]
    all_job_ids: set[str] = set()
    try:
        for index in range(SHARDS):
            handle = (OUTPUT / f"shard_{index:02d}.tsv").open("w", newline="")
            handles.append(handle)
            writer = csv.DictWriter(
                handle,
                fieldnames=["package_key", "job_id"],
                delimiter="\t",
                lineterminator="\n",
            )
            writer.writeheader()
            writers.append(writer)

        for package_key, manifest in PACKAGES.items():
            with manifest.open(newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            assert len(rows) == EXPECTED[package_key]
            ids = [row["job_id"] for row in rows]
            assert len(set(ids)) == len(ids)
            assert not (all_job_ids & set(ids))
            all_job_ids.update(ids)
            for index, job_id in enumerate(ids):
                shard = index % SHARDS
                writers[shard].writerow(
                    {"package_key": package_key, "job_id": job_id}
                )
                shard_counts[shard][package_key] += 1
    finally:
        for handle in handles:
            handle.close()

    assert len(all_job_ids) == 24880
    for counts in shard_counts:
        assert counts == Counter({"c2_new4220": 2110, "c2_new2000": 1000})

    receipt = {
        "schema_version": "pvrig.c2_new6220.bxcpu_dispatch.v1",
        "status": "READY_8_BALANCED_SHARDS",
        "packages": EXPECTED,
        "total_jobs": 24880,
        "shard_count": SHARDS,
        "jobs_per_shard": 3110,
        "jobs_per_shard_by_package": {
            "c2_new4220": 2110,
            "c2_new2000": 1000,
        },
        "input_manifest_sha256": {
            key: sha256(path) for key, path in PACKAGES.items()
        },
        "shard_sha256": {
            path.name: sha256(path) for path in sorted(OUTPUT.glob("shard_*.tsv"))
        },
        "job_ids_disjoint": True,
    }
    (OUTPUT / "DISPATCH_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
