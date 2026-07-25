#!/usr/bin/env python3
"""Materialize physically isolated OPEN_TRAIN labels and sequences for V1.1."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from collections import Counter
from pathlib import Path


SCHEMA_VERSION = "phase2_v4_d_open_train_model_inputs_v1_1"
EXPECTED_SOURCE_SHA256 = "89ad82c7cde28d862fecedfff4559e810bab68cf2405aa8f9e4dc5f1bd148068"
EXPECTED_SPLITS = {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32}
LABEL_FIELDS = (
    "schema_version", "candidate_id", "sequence_sha256", "model_split",
    "parent_framework_cluster", "design_mode", "target_patch_id", "R_dual_min",
)
SEQUENCE_FIELDS = ("sequence_sha256", "sequence", "sequence_length", "roles")
CLAIM_BOUNDARY = (
    "OPEN_TRAIN-only model inputs for development of a computational "
    "docking-geometry surrogate; not Docking Gold or experimental truth."
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


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_table(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]], delimiter: str) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter=delimiter, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(path, buffer.getvalue().encode("utf-8"))


def materialize(
    source: Path,
    label_output: Path,
    sequence_output: Path,
    receipt_output: Path,
    *,
    enforce_hash: bool = True,
) -> dict[str, object]:
    for path in (label_output, sequence_output, receipt_output):
        require(not path.exists() and not path.is_symlink(), f"output_exists:{path}")
    source_sha = sha256_file(source)
    if enforce_hash:
        require(source_sha == EXPECTED_SOURCE_SHA256, "source_sha256_mismatch")
    labels: list[dict[str, str]] = []
    sequences: list[dict[str, str]] = []
    counts: Counter[str] = Counter()
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = set(LABEL_FIELDS[1:]) | {"sequence"}
        require(required <= set(reader.fieldnames or ()), "required_source_fields_missing")
        for raw in reader:
            split = raw["model_split"]
            counts[split] += 1
            if split != "OPEN_TRAIN":
                continue
            sequence = raw["sequence"].strip().upper()
            require(sequence and set(sequence) <= set("ACDEFGHIKLMNPQRSTVWY"), "invalid_open_train_sequence")
            require(hashlib.sha256(sequence.encode("ascii")).hexdigest() == raw["sequence_sha256"], "sequence_hash_mismatch")
            target = float(raw["R_dual_min"])
            require(math.isfinite(target), "nonfinite_open_train_target")
            labels.append({
                "schema_version": SCHEMA_VERSION,
                "candidate_id": raw["candidate_id"],
                "sequence_sha256": raw["sequence_sha256"],
                "model_split": split,
                "parent_framework_cluster": raw["parent_framework_cluster"],
                "design_mode": raw["design_mode"],
                "target_patch_id": raw["target_patch_id"],
                "R_dual_min": f"{target:.12g}",
            })
            sequences.append({
                "sequence_sha256": raw["sequence_sha256"],
                "sequence": sequence,
                "sequence_length": str(len(sequence)),
                "roles": "vhh",
            })
    require(counts == Counter(EXPECTED_SPLITS), f"source_split_counts_invalid:{dict(counts)}")
    require(len(labels) == len(sequences) == 226, "open_train_count_invalid")
    require(len({row["candidate_id"] for row in labels}) == 226, "candidate_id_not_unique")
    require(len({row["sequence_sha256"] for row in labels}) == 226, "sequence_sha_not_unique")
    label_hashes = {row["sequence_sha256"] for row in labels}
    require(label_hashes == {row["sequence_sha256"] for row in sequences}, "label_sequence_closure_failed")
    labels.sort(key=lambda row: row["candidate_id"])
    sequences.sort(key=lambda row: row["sequence_sha256"])
    write_table(label_output, LABEL_FIELDS, labels, "\t")
    write_table(sequence_output, SEQUENCE_FIELDS, sequences, ",")
    payload = {
        "schema_version": f"{SCHEMA_VERSION}_receipt",
        "status": "COMPLETE_PHYSICALLY_ISOLATED_OPEN_TRAIN226_INPUTS",
        "source_sha256": source_sha,
        "source_split_counts": dict(sorted(counts.items())),
        "label_output_sha256": sha256_file(label_output),
        "sequence_output_sha256": sha256_file(sequence_output),
        "rows": 226,
        "parent_framework_clusters": len({row["parent_framework_cluster"] for row in labels}),
        "open_development_rows_excluded": counts["OPEN_DEVELOPMENT"],
        "open_development_target_values_converted": 0,
        "open_development_target_values_copied": 0,
        "open_development_target_values_emitted": 0,
        "V4_F_test32_sequences_accessed": 0,
        "V4_F_test32_labels_accessed": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_write(receipt_output, (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--label-output", type=Path, required=True)
    parser.add_argument("--sequence-output", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = materialize(args.source, args.label_output, args.sequence_output, args.receipt_output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
