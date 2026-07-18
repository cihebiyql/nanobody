#!/usr/bin/env python3
"""Enrich a portable docking input with QC-derived IMGT CDR sequences."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def atomic_json(path: Path, payload: object) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def unique_range(sequence: str, cdr: str, label: str, candidate_id: str) -> tuple[int, int]:
    if not cdr:
        raise RuntimeError(f"cdr_missing:{candidate_id}:{label}")
    start = sequence.find(cdr)
    if start < 0 or sequence.find(cdr, start + 1) >= 0:
        raise RuntimeError(f"cdr_absent_or_nonunique:{candidate_id}:{label}:{cdr}")
    return start, start + len(cdr)


def run(source_root: Path, qc_paths: list[Path], output_root: Path) -> dict[str, object]:
    receipt_path = source_root / "INPUT_RECEIPT.json"
    candidates_path = source_root / "candidates.tsv"
    monomer_manifest = source_root / "monomer_manifest.tsv"
    for path in (receipt_path, candidates_path, monomer_manifest, source_root / "monomers"):
        if not path.exists() or path.is_symlink():
            raise RuntimeError(f"source_artifact_missing_or_symlink:{path}")
    source_receipt = json.loads(receipt_path.read_text())
    if source_receipt.get("status") != "PASS_PORTABLE_RESEARCH_DOCKING_INPUT_READY":
        raise RuntimeError("source_receipt_status_invalid")
    if source_receipt.get("candidate_manifest_sha256") != sha256(candidates_path):
        raise RuntimeError("source_candidate_hash_mismatch")
    if source_receipt.get("monomer_manifest_sha256") != sha256(monomer_manifest):
        raise RuntimeError("source_monomer_manifest_hash_mismatch")

    qc_by_id: dict[str, dict[str, str]] = {}
    qc_hashes: dict[str, str] = {}
    for path in qc_paths:
        fields, rows = read_tsv(path)
        required = {"candidate_id", "sequence", "IMGT_CDR1", "IMGT_CDR2", "IMGT_CDR3"}
        if not required <= set(fields):
            raise RuntimeError(f"qc_fields_missing:{path}:{sorted(required - set(fields))}")
        for row in rows:
            prior = qc_by_id.get(row["candidate_id"])
            if prior is not None and prior != row:
                raise RuntimeError(f"conflicting_qc_row:{row['candidate_id']}")
            qc_by_id[row["candidate_id"]] = row
        qc_hashes[str(path)] = sha256(path)

    fields, candidates = read_tsv(candidates_path)
    for field in ("cdr1_after", "cdr2_after", "cdr3_after", "cdr3_length"):
        if field not in fields:
            fields.append(field)
    enriched = 0
    for row in candidates:
        candidate_id = row["candidate_id"]
        sequence = row["sequence"]
        if not all(row.get(field, "") for field in ("cdr1_after", "cdr2_after", "cdr3_after")):
            qc = qc_by_id.get(candidate_id)
            if qc is None or qc["sequence"] != sequence:
                raise RuntimeError(f"qc_cdr_source_missing_or_sequence_mismatch:{candidate_id}")
            row["cdr1_after"] = qc["IMGT_CDR1"]
            row["cdr2_after"] = qc["IMGT_CDR2"]
            row["cdr3_after"] = qc["IMGT_CDR3"]
            enriched += 1
        ranges = [
            unique_range(sequence, row[f"cdr{index}_after"], f"cdr{index}", candidate_id)
            for index in (1, 2, 3)
        ]
        if not (ranges[0][1] <= ranges[1][0] and ranges[1][1] <= ranges[2][0]):
            raise RuntimeError(f"cdr_order_invalid:{candidate_id}:{ranges}")
        row["cdr3_length"] = str(len(row["cdr3_after"]))

    staging = output_root.with_name(f".{output_root.name}.staging.{os.getpid()}")
    if output_root.exists() or staging.exists():
        raise FileExistsError(output_root if output_root.exists() else staging)
    staging.mkdir(parents=True)
    try:
        write_tsv(staging / "candidates.tsv", candidates, fields)
        shutil.copy2(monomer_manifest, staging / "monomer_manifest.tsv")
        shutil.copytree(source_root / "monomers", staging / "monomers")
        if (source_root / "technical_failures.tsv").is_file():
            shutil.copy2(source_root / "technical_failures.tsv", staging / "technical_failures.tsv")
        receipt = dict(source_receipt)
        receipt.update({
            "schema_version": "phase2_v4_i_round2_combined_docking_input_cdr_enriched_v1",
            "status": "PASS_PORTABLE_RESEARCH_DOCKING_INPUT_READY",
            "candidate_manifest_sha256": sha256(staging / "candidates.tsv"),
            "monomer_manifest_sha256": sha256(staging / "monomer_manifest.tsv"),
            "source_input_receipt_sha256": sha256(receipt_path),
            "qc_cdr_source_hashes": qc_hashes,
            "cdr_enriched_candidate_count": enriched,
            "cdr_verified_candidate_count": len(candidates),
            "published_at_utc": datetime.now(timezone.utc).isoformat(),
        })
        atomic_json(staging / "INPUT_RECEIPT.json", receipt)
        os.replace(staging, output_root)
        return receipt
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--qc-tsv", action="append", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.source_root, args.qc_tsv, args.output_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
