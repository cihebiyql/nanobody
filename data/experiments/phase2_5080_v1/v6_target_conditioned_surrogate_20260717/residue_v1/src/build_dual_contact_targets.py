#!/usr/bin/env python3
"""Build deterministic two-receptor residue targets from the frozen pair teacher.

The pair table contains one row per observed VHH--PVRIG residue pair.  This
adapter deliberately uses a conservative aggregation: for each VHH residue and
each receptor, the target is the maximum pose-weighted pair frequency over all
PVRIG residues.  It does not sum correlated residue-pair frequencies and never
turns a technical absence into a negative label.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "pvrig_v6_residue_dual_contact_targets_v1"
CLAIM_BOUNDARY = (
    "Residue targets derived from frozen single-seed 8X6B/9E6Y computational "
    "Docking contacts; not binding probability, affinity, experimental blocking, "
    "Docking Gold, or final submission evidence."
)
RECEPTORS = ("8x6b", "9e6y")
OUTPUT_NAME = "v6_dual_residue_contact_targets.tsv.gz"
RECEIPT_NAME = "RUN_RECEIPT.json"
OUTPUT_FIELDS = (
    "schema_version",
    "candidate_id",
    "sequence_sha256",
    "parent_framework_cluster",
    "vhh_sequence_index",
    "vhh_aa",
    "contact_target_8x6b",
    "contact_target_9e6y",
    "target_mask_8x6b",
    "target_mask_9e6y",
    "aggregation",
    "claim_boundary",
)
PAIR_REQUIRED = {
    "teacher_state",
    "candidate_id",
    "sequence_sha256",
    "parent_framework_cluster",
    "receptor",
    "vhh_sequence_index",
    "vhh_aa",
    "pvrig_uniprot_position",
    "contact_frequency_pose_weighted",
}
TRAIN_REQUIRED = {
    "candidate_id",
    "sequence_sha256",
    "sequence",
    "parent_framework_cluster",
}


class ContactTargetError(RuntimeError):
    """Fail-closed target materialization error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContactTargetError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_regular(path: Path, label: str) -> None:
    require(path.is_file(), f"{label}_missing:{path}")
    require(not path.is_symlink(), f"{label}_symlink_forbidden:{path}")


def read_tsv(path: Path, *, compressed: bool) -> tuple[list[str], list[dict[str, str]]]:
    require_regular(path, "input")
    if compressed:
        handle: Any = gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    else:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    with handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return fields, rows


def write_gzip_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
    os.replace(temporary, path)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def build_targets(
    training_tsv: Path,
    pair_tsv_gz: Path,
    output_dir: Path,
    *,
    expected_candidates: int,
    expected_training_sha256: str | None = None,
    expected_pair_sha256: str | None = None,
) -> dict[str, Any]:
    require(expected_candidates > 0, "expected_candidates_must_be_positive")
    require(not output_dir.is_symlink(), "output_dir_symlink_forbidden")
    require(not output_dir.exists(), f"output_dir_already_exists:{output_dir}")
    training_hash = sha256_file(training_tsv)
    pair_hash = sha256_file(pair_tsv_gz)
    if expected_training_sha256 is not None:
        require(training_hash == expected_training_sha256, "training_sha256_mismatch")
    if expected_pair_sha256 is not None:
        require(pair_hash == expected_pair_sha256, "pair_sha256_mismatch")

    train_fields, train_rows = read_tsv(training_tsv, compressed=False)
    require(TRAIN_REQUIRED <= set(train_fields), f"training_fields_missing:{sorted(TRAIN_REQUIRED-set(train_fields))}")
    training: dict[str, dict[str, str]] = {}
    for row in train_rows:
        candidate = row["candidate_id"]
        require(candidate and candidate not in training, f"duplicate_training_candidate:{candidate}")
        sequence = row["sequence"].strip().upper()
        require(sequence and all(aa.isalpha() for aa in sequence), f"invalid_training_sequence:{candidate}")
        require(hashlib.sha256(sequence.encode()).hexdigest() == row["sequence_sha256"], f"training_sequence_hash_mismatch:{candidate}")
        training[candidate] = row

    pair_fields, pair_rows = read_tsv(pair_tsv_gz, compressed=True)
    require(PAIR_REQUIRED <= set(pair_fields), f"pair_fields_missing:{sorted(PAIR_REQUIRED-set(pair_fields))}")
    values: dict[tuple[str, str, int], float] = {}
    candidates: set[str] = set()
    receptor_by_candidate: dict[str, set[str]] = {}
    observed_pairs: set[tuple[str, str, int, int]] = set()
    valid_states: set[str] = set()
    for line_number, row in enumerate(pair_rows, start=2):
        candidate = row["candidate_id"]
        require(candidate in training, f"pair_candidate_not_in_training:{line_number}:{candidate}")
        source = training[candidate]
        require(row["sequence_sha256"] == source["sequence_sha256"], f"pair_sequence_hash_mismatch:{candidate}")
        require(row["parent_framework_cluster"] == source["parent_framework_cluster"], f"pair_parent_mismatch:{candidate}")
        receptor = row["receptor"].strip().lower()
        require(receptor in RECEPTORS, f"invalid_receptor:{line_number}:{receptor}")
        index = int(row["vhh_sequence_index"])
        sequence = source["sequence"].strip().upper()
        require(1 <= index <= len(sequence), f"vhh_index_out_of_range:{candidate}:{index}")
        require(row["vhh_aa"].strip().upper() == sequence[index - 1], f"vhh_aa_mismatch:{candidate}:{index}")
        pvrig_position = int(row["pvrig_uniprot_position"])
        pair_key = (candidate, receptor, index, pvrig_position)
        require(pair_key not in observed_pairs, f"duplicate_residue_pair:{pair_key}")
        observed_pairs.add(pair_key)
        frequency = float(row["contact_frequency_pose_weighted"])
        require(math.isfinite(frequency) and 0.0 <= frequency <= 1.0, f"invalid_contact_frequency:{line_number}")
        key = (candidate, receptor, index)
        values[key] = max(values.get(key, 0.0), frequency)
        candidates.add(candidate)
        receptor_by_candidate.setdefault(candidate, set()).add(receptor)
        valid_states.add(row["teacher_state"])

    require(len(candidates) == expected_candidates, f"teacher_candidate_count_mismatch:{len(candidates)}:{expected_candidates}")
    for candidate in sorted(candidates):
        require(receptor_by_candidate[candidate] == set(RECEPTORS), f"candidate_missing_receptor:{candidate}:{sorted(receptor_by_candidate[candidate])}")

    output_rows: list[dict[str, Any]] = []
    for candidate in sorted(candidates):
        source = training[candidate]
        sequence = source["sequence"].strip().upper()
        for index, aa in enumerate(sequence, start=1):
            output_rows.append({
                "schema_version": SCHEMA_VERSION,
                "candidate_id": candidate,
                "sequence_sha256": source["sequence_sha256"],
                "parent_framework_cluster": source["parent_framework_cluster"],
                "vhh_sequence_index": index,
                "vhh_aa": aa,
                "contact_target_8x6b": format(values.get((candidate, "8x6b", index), 0.0), ".10g"),
                "contact_target_9e6y": format(values.get((candidate, "9e6y", index), 0.0), ".10g"),
                "target_mask_8x6b": 1,
                "target_mask_9e6y": 1,
                "aggregation": "max_over_pvrig_positions",
                "claim_boundary": CLAIM_BOUNDARY,
            })

    output_dir.mkdir(parents=True, exist_ok=False)
    output_path = output_dir / OUTPUT_NAME
    write_gzip_tsv(output_path, OUTPUT_FIELDS, output_rows)
    receipt = {
        "schema_version": f"{SCHEMA_VERSION}_receipt",
        "status": "PASS_DUAL_CONTACT_TARGETS_MATERIALIZED",
        "claim_boundary": CLAIM_BOUNDARY,
        "algorithm": "per_candidate_per_receptor_per_vhh_residue_max_pose_weighted_pair_frequency",
        "inputs": {
            "training_tsv": str(training_tsv.resolve()),
            "training_sha256": training_hash,
            "pair_tsv_gz": str(pair_tsv_gz.resolve()),
            "pair_sha256": pair_hash,
        },
        "counts": {
            "training_candidates": len(training),
            "teacher_candidates": len(candidates),
            "pair_rows": len(pair_rows),
            "target_rows": len(output_rows),
        },
        "teacher_states": sorted(valid_states),
        "output": {
            "path": output_path.name,
            "sha256": sha256_file(output_path),
        },
    }
    atomic_json(output_dir / RECEIPT_NAME, receipt)
    return receipt


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--training-tsv", type=Path, required=True)
    value.add_argument("--pair-tsv-gz", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--expected-candidates", type=int, required=True)
    value.add_argument("--expected-training-sha256")
    value.add_argument("--expected-pair-sha256")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    receipt = build_targets(
        args.training_tsv,
        args.pair_tsv_gz,
        args.output_dir,
        expected_candidates=args.expected_candidates,
        expected_training_sha256=args.expected_training_sha256,
        expected_pair_sha256=args.expected_pair_sha256,
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

