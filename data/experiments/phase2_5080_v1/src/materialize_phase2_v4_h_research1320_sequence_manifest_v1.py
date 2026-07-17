#!/usr/bin/env python3
"""Materialize a label-free V4-H research1320 sequence embedding manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import stat
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "phase2_v4_h_research1320_sequence_manifest_v1"
STATUS = "PASS_V4_H_RESEARCH1320_LABEL_FREE_SEQUENCE_MANIFEST"
EXPECTED_SOURCE_SHA256 = "f02cfeaac9775442bb1748c7bb63413a1077b5df11f9cd7214e983d0e51c0551"
EXPECTED_ROWS = 1320
OUTPUT_FIELDS = ("sequence_sha256", "sequence", "sequence_length", "roles")
STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")
CLAIM_BOUNDARY = (
    "Label-free V4-H sequence inputs for frozen embedding and computational "
    "docking-geometry surrogate comparison; no docking result, pose, geometry "
    "label, binding, affinity, or experimental blocking truth."
)


class MaterializationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MaterializationError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_regular(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise MaterializationError(f"source_missing:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"source_not_regular_or_symlink:{path}")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def materialize(
    source: Path,
    output: Path,
    receipt: Path,
    *,
    expected_source_sha256: str = EXPECTED_SOURCE_SHA256,
    expected_rows: int = EXPECTED_ROWS,
) -> dict[str, Any]:
    require_regular(source)
    require(not output.exists() and not output.is_symlink(), f"output_exists:{output}")
    require(not receipt.exists() and not receipt.is_symlink(), f"receipt_exists:{receipt}")
    require(sha256_file(source) == expected_source_sha256, "source_sha256_mismatch")
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = set(reader.fieldnames or ())
        required = {
            "candidate_id", "sequence", "sequence_sha256", "sequence_length",
            "research_pool_state", "monomer_structure_eligible", "sequence_repaired",
        }
        require(required <= fields, "source_fields_missing")
        source_rows = [dict(row) for row in reader]
    require(len(source_rows) == expected_rows, f"source_row_count_invalid:{len(source_rows)}")
    require(len({row["candidate_id"] for row in source_rows}) == expected_rows, "candidate_ids_not_unique")
    rows: list[dict[str, str]] = []
    for row in source_rows:
        candidate_id = row["candidate_id"]
        sequence = row["sequence"].strip().upper()
        require(sequence and set(sequence) <= STANDARD_AA, f"invalid_sequence:{candidate_id}")
        require(int(row["sequence_length"]) == len(sequence), f"sequence_length_mismatch:{candidate_id}")
        sequence_sha = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        require(sequence_sha == row["sequence_sha256"], f"sequence_sha256_mismatch:{candidate_id}")
        require(row["research_pool_state"] == "RESEARCH_READY", f"candidate_not_research_ready:{candidate_id}")
        require(row["monomer_structure_eligible"] == "true", f"candidate_not_monomer_eligible:{candidate_id}")
        require(row["sequence_repaired"] == "false", f"candidate_sequence_repaired:{candidate_id}")
        rows.append({
            "sequence_sha256": sequence_sha,
            "sequence": sequence,
            "sequence_length": str(len(sequence)),
            "roles": "vhh",
        })
    require(len({row["sequence_sha256"] for row in rows}) == expected_rows, "sequence_hashes_not_unique")
    rows.sort(key=lambda row: row["sequence_sha256"])
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
    writer.writeheader(); writer.writerows(rows)
    atomic_write(output, buffer.getvalue().encode("utf-8"))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "source_sha256": expected_source_sha256,
        "output_sha256": sha256_file(output),
        "row_count": expected_rows,
        "unique_sequence_sha256": expected_rows,
        "roles": {"vhh": expected_rows},
        "V4_H_docking_result_files_opened": 0,
        "V4_H_geometry_labels_accessed": 0,
        "V4_F_test32_rows_accessed": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_write(receipt, (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = materialize(args.source, args.output, args.receipt)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
