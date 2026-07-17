#!/usr/bin/env python3
"""Project the frozen V4-D V1.2 teacher to an OPEN_TRAIN-only primary table.

The source delivery contains OPEN_TRAIN and OPEN_DEVELOPMENT rows.  This
projector uses ``model_split`` only to route excluded rows and never converts,
copies, summarizes, or emits their target values.  Downstream V1.1 model
selection therefore consumes a physically separate 226-row label table.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from collections import Counter
from pathlib import Path


SCHEMA_VERSION = "phase2_v4_d_open_train_primary_v1"
EXPECTED_SOURCE_SHA256 = "89ad82c7cde28d862fecedfff4559e810bab68cf2405aa8f9e4dc5f1bd148068"
EXPECTED_SPLITS = {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32}
OUTPUT_FIELDS = (
    "schema_version",
    "candidate_id",
    "sequence_sha256",
    "model_split",
    "parent_framework_cluster",
    "design_mode",
    "target_patch_id",
    "R_dual_min",
)
CLAIM_BOUNDARY = (
    "OPEN_TRAIN-only development labels for computational docking-geometry "
    "surrogate development; not Docking Gold or experimental blocking truth."
)


class ProjectionError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProjectionError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def project(source: Path, output: Path, receipt: Path, *, enforce_hash: bool = True) -> dict[str, object]:
    require(not output.exists() and not output.is_symlink(), f"output_exists:{output}")
    require(not receipt.exists() and not receipt.is_symlink(), f"receipt_exists:{receipt}")
    source_sha = sha256_file(source)
    if enforce_hash:
        require(source_sha == EXPECTED_SOURCE_SHA256, "source_sha256_mismatch")
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = set(reader.fieldnames or ())
        require(set(OUTPUT_FIELDS[1:]) <= fields, "required_source_fields_missing")
        counts: Counter[str] = Counter()
        rows: list[dict[str, str]] = []
        for raw in reader:
            split = raw["model_split"]
            counts[split] += 1
            if split != "OPEN_TRAIN":
                continue
            value = float(raw["R_dual_min"])
            require(value == value and abs(value) != float("inf"), "nonfinite_open_train_target")
            rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "candidate_id": raw["candidate_id"],
                    "sequence_sha256": raw["sequence_sha256"],
                    "model_split": split,
                    "parent_framework_cluster": raw["parent_framework_cluster"],
                    "design_mode": raw["design_mode"],
                    "target_patch_id": raw["target_patch_id"],
                    "R_dual_min": f"{value:.12g}",
                }
            )
    require(counts == Counter(EXPECTED_SPLITS), f"source_split_counts_invalid:{dict(counts)}")
    require(len(rows) == 226, "open_train_row_count_invalid")
    require(len({row["candidate_id"] for row in rows}) == 226, "candidate_id_not_unique")
    require(len({row["sequence_sha256"] for row in rows}) == 226, "sequence_sha256_not_unique")
    require({row["model_split"] for row in rows} == {"OPEN_TRAIN"}, "output_split_not_closed")
    rows.sort(key=lambda row: row["candidate_id"])
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_FIELDS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(output, buffer.getvalue().encode("utf-8"))
    output_sha = sha256_file(output)
    payload = {
        "schema_version": f"{SCHEMA_VERSION}_receipt",
        "status": "COMPLETE_OPEN_TRAIN_ONLY_PRIMARY_PROJECTION",
        "source_path": str(source.resolve()),
        "source_sha256": source_sha,
        "source_split_counts": dict(sorted(counts.items())),
        "output_path": str(output.resolve()),
        "output_sha256": output_sha,
        "output_rows": len(rows),
        "output_fields": list(OUTPUT_FIELDS),
        "open_development_rows_excluded": counts["OPEN_DEVELOPMENT"],
        "open_development_target_values_converted": 0,
        "open_development_target_values_copied": 0,
        "open_development_target_values_emitted": 0,
        "prospective_test_rows_accessed": 0,
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
    print(json.dumps(project(args.source, args.output, args.receipt), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
