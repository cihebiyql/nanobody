#!/usr/bin/env python3
"""Build immutable Rosetta and MD calibration manifests from frozen V3 jobs."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "pvrig_positive_control_calibration_20260724"
POSITIVE = SOURCE / "positive_v3_job_manifest.tsv"
DESTRUCTIVE = SOURCE / "destructive_control_v3_job_manifest.tsv"


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


positive = read_tsv(POSITIVE)
destructive = read_tsv(DESTRUCTIVE)
if len(positive) != 66:
    raise SystemExit(f"expected 66 positive jobs, found {len(positive)}")
if len(destructive) != 84:
    raise SystemExit(f"expected 84 destructive jobs, found {len(destructive)}")
if any(row["state"] != "SUCCESS" for row in positive + destructive):
    raise SystemExit("non-SUCCESS job present")
if any(row["control_class"] != "positive_control" for row in positive):
    raise SystemExit("positive manifest contains wrong control_class")
if any(row["control_class"] != "destructive_alanine" for row in destructive):
    raise SystemExit("destructive manifest contains wrong control_class")

fields = list(positive[0])
combined = positive + destructive
if len({row["job_id"] for row in combined}) != 150:
    raise SystemExit("duplicate job_id in combined panel")
write_tsv(HERE / "ROSETTA_JOB_MANIFEST.tsv", combined, fields)

md_entities = {
    "HR151": (
        "CTRL_PATENT_001_case02_pos_01_PVRIG-151_HR151",
        None,
    ),
    "P20_F99A": (
        "CTRL_PATENT_002_case02_pos_02_PVRIG-20",
        "CTRL_MUTANT_003_mut_03_PVRIG-20_cdr3_arom_F99A",
    ),
}
md_rows: list[dict[str, str]] = []
for pair_id, (positive_entity, negative_entity) in md_entities.items():
    for role, entity in (("positive", positive_entity), ("destructive", negative_entity)):
        if entity is None:
            continue
        matches = [
            row
            for row in combined
            if row["entity_id"] == entity
            and row["conformation"] == "8x6b"
            and row["docking_seed"] == "917"
        ]
        if len(matches) != 1:
            raise SystemExit(f"{pair_id}/{role}: expected one 8x6b seed917 job, found {len(matches)}")
        row = dict(matches[0])
        row["pair_id"] = pair_id
        row["pair_role"] = role
        md_rows.append(row)

md_fields = ["pair_id", "pair_role", *fields]
write_tsv(HERE / "MD_STAGE_A_MANIFEST.tsv", md_rows, md_fields)

receipt = {
    "schema_version": 1,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "source_positive_manifest": str(POSITIVE),
    "source_positive_sha256": sha256(POSITIVE),
    "source_destructive_manifest": str(DESTRUCTIVE),
    "source_destructive_sha256": sha256(DESTRUCTIVE),
    "rosetta_jobs": len(combined),
    "positive_jobs": len(positive),
    "destructive_jobs": len(destructive),
    "md_stage_a_jobs": len(md_rows),
    "chain_contract": {"PVRIG": "T", "VHH": "A", "rosetta_interface": "T_A"},
}
(HERE / "MANIFEST_RECEIPT.json").write_text(
    json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
print(json.dumps(receipt, indent=2, ensure_ascii=False))
