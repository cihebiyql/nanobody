#!/usr/bin/env python3
"""Independent fail-closed verifier for the V2.10 canonical open teacher.

This verifier is intentionally separate from the materialization adapter.  It
accepts only immutable, explicit paths and recomputes the model-input contract
from the TSV bytes.  The production CLI freezes the expected V2.10 counts:

    9,849 train + 795 development = 10,644 open rows
    1 newly quarantined row

It never reads a frozen-test label source.  The only frozen information it
accepts is the parent identifier set carried by the open split manifest.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


AA = frozenset("ACDEFGHIKLMNPQRSTVWY")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SPLIT_SCHEMA = "pvrig_v2_9_whole_parent_split_v1"
REQUIRED_TEACHER_COLUMNS = frozenset({
    "candidate_id",
    "sequence_sha256",
    "sequence",
    "parent_framework_cluster",
    "cdr1",
    "cdr2",
    "cdr3",
    "sample_weight",
    "R_8X6B",
    "R_9E6Y",
    "R_dual_min",
    "teacher_source",
    "teacher_reliability",
})
PRODUCTION_COUNTS = None  # assigned after ExpectedCounts is declared


class VerificationError(RuntimeError):
    """A fail-closed contract violation."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


@dataclass(frozen=True)
class ExpectedCounts:
    train: int
    development: int
    open_total: int
    new_quarantine: int


PRODUCTION_COUNTS = ExpectedCounts(
    train=9849,
    development=795,
    open_total=10644,
    new_quarantine=1,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require_regular(path: Path, label: str) -> None:
    require(path.is_file(), f"missing_{label}:{path}")
    require(not path.is_symlink(), f"symlink_{label}:{path}")


def load_json(path: Path, label: str) -> dict[str, Any]:
    require_regular(path, label)
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid_{label}_json:{path}") from exc
    require(isinstance(value, dict), f"non_object_{label}:{path}")
    return value


def load_tsv(path: Path, label: str) -> tuple[list[dict[str, str]], list[str]]:
    require_regular(path, label)
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        require(bool(fields), f"missing_{label}_header")
        require(len(fields) == len(set(fields)), f"duplicate_{label}_columns")
        return list(reader), fields


def stable_set_hash(values: Iterable[str]) -> str:
    payload = "\n".join(sorted(set(values))) + "\n"
    return hashlib.sha256(payload.encode()).hexdigest()


def recursively_collect_hashes(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and HEX64.fullmatch(key):
                found.add(key)
            found.update(recursively_collect_hashes(item))
    elif isinstance(value, list):
        for item in value:
            found.update(recursively_collect_hashes(item))
    elif isinstance(value, str) and HEX64.fullmatch(value):
        found.add(value)
    return found


def verify_sha256sums(
    sha256sums: Path,
    required_artifacts: Iterable[Path],
) -> dict[str, str]:
    """Verify every manifest entry and require closure over core artifacts."""
    require_regular(sha256sums, "sha256sums")
    root = sha256sums.parent.resolve()
    entries: dict[Path, str] = {}
    for line_number, raw in enumerate(sha256sums.read_text().splitlines(), 1):
        if not raw.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", raw)
        require(match is not None, f"invalid_sha256sums_line:{line_number}")
        expected, relative_text = match.groups()
        relative = Path(relative_text)
        require(not relative.is_absolute(), f"absolute_sha256_path:{relative_text}")
        require(".." not in relative.parts, f"parent_traversal_sha256_path:{relative_text}")
        target = (root / relative).resolve()
        require(target == root or root in target.parents, f"sha256_path_outside_root:{relative_text}")
        require(target not in entries, f"duplicate_sha256_entry:{relative_text}")
        require_regular(target, f"sha256_entry_{line_number}")
        observed = sha256_file(target)
        require(observed == expected, f"sha256_mismatch:{relative_text}")
        entries[target] = observed
    require(bool(entries), "empty_sha256sums")
    for artifact in required_artifacts:
        require(artifact.resolve() in entries, f"artifact_not_hash_bound:{artifact}")
    return {str(path): digest for path, digest in sorted(entries.items(), key=lambda item: str(item[0]))}


def mismatch_limit(length: int) -> int:
    """Maximum mismatches compatible with Hamming identity >= 80%."""
    return int(math.floor(length * 0.20 + 1e-12))


def hamming80_cross_split_examples(
    train_cdr3: Iterable[str], development_cdr3: Iterable[str], limit: int = 10
) -> list[dict[str, Any]]:
    """Find direct Hamming80 edges between train and development.

    A connected CDR3 family can span both splits only if at least one edge in
    its path crosses the split boundary.  Therefore this direct-edge audit is
    equivalent to testing cross-split connected-component leakage, without
    trusting a family identifier supplied by the adapter.
    """
    train_by_length: dict[int, list[str]] = {}
    development_by_length: dict[int, list[str]] = {}
    for sequence in set(train_cdr3):
        train_by_length.setdefault(len(sequence), []).append(sequence)
    for sequence in set(development_cdr3):
        development_by_length.setdefault(len(sequence), []).append(sequence)
    examples: list[dict[str, Any]] = []
    for length in sorted(set(train_by_length) & set(development_by_length)):
        allowed = mismatch_limit(length)
        for left in sorted(train_by_length[length]):
            for right in sorted(development_by_length[length]):
                mismatches = 0
                for a, b in zip(left, right):
                    if a != b:
                        mismatches += 1
                        if mismatches > allowed:
                            break
                if mismatches <= allowed:
                    examples.append({
                        "train_cdr3": left,
                        "development_cdr3": right,
                        "length": length,
                        "mismatches": mismatches,
                    })
                    if len(examples) >= limit:
                        return examples
    return examples


def _finite(raw: str, label: str, candidate_id: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise VerificationError(f"invalid_{label}:{candidate_id}") from exc
    require(math.isfinite(value), f"nonfinite_{label}:{candidate_id}")
    return value


def verify_release(
    *,
    teacher_tsv: Path,
    split_manifest: Path,
    quarantine_tsv: Path,
    receipt_json: Path,
    sha256sums: Path,
    expected: ExpectedCounts = PRODUCTION_COUNTS,
) -> dict[str, Any]:
    for path, label in (
        (teacher_tsv, "teacher"),
        (split_manifest, "split_manifest"),
        (quarantine_tsv, "quarantine"),
        (receipt_json, "receipt"),
        (sha256sums, "sha256sums"),
    ):
        require_regular(path, label)

    teacher_sha = sha256_file(teacher_tsv)
    split_sha = sha256_file(split_manifest)
    quarantine_sha = sha256_file(quarantine_tsv)
    receipt_sha = sha256_file(receipt_json)
    manifest = load_json(split_manifest, "split_manifest")
    receipt = load_json(receipt_json, "receipt")

    require(manifest.get("schema_version") == SPLIT_SCHEMA, "split_schema")
    require(manifest.get("data_version") == "D1", "split_data_version")
    require(manifest.get("open_only") is True, "split_not_open_only")
    require(manifest.get("frozen_test_access_count") == 0, "frozen_truth_access_nonzero")
    require(manifest.get("sealed_truth_access_count", 0) == 0, "sealed_truth_access_nonzero")
    require(manifest.get("training_tsv_sha256") == teacher_sha, "split_teacher_hash_mismatch")

    train_parents = set(manifest.get("train_parents", []))
    development_parents = set(manifest.get("score_parents", []))
    frozen_parents = set(manifest.get("frozen_test_parents", []))
    require(bool(train_parents), "empty_train_parent_set")
    require(bool(development_parents), "empty_development_parent_set")
    require(bool(frozen_parents), "empty_frozen_parent_metadata")
    require(train_parents.isdisjoint(development_parents), "train_development_parent_overlap")
    require(train_parents.isdisjoint(frozen_parents), "train_frozen_parent_overlap")
    require(development_parents.isdisjoint(frozen_parents), "development_frozen_parent_overlap")
    require(manifest.get("train_parent_set_sha256") == stable_set_hash(train_parents), "train_parent_hash")
    require(
        manifest.get("score_parent_set_sha256") == stable_set_hash(development_parents),
        "development_parent_hash",
    )
    require(
        manifest.get("frozen_test_parent_set_sha256") == stable_set_hash(frozen_parents),
        "frozen_parent_hash",
    )

    teacher_rows, teacher_fields = load_tsv(teacher_tsv, "teacher")
    require(REQUIRED_TEACHER_COLUMNS <= set(teacher_fields), "teacher_columns_missing")
    require(len(teacher_rows) == expected.open_total, f"open_row_count:{len(teacher_rows)}")

    candidate_ids: set[str] = set()
    sequence_hashes: set[str] = set()
    observed_train_parents: set[str] = set()
    observed_development_parents: set[str] = set()
    train_cdr3: list[str] = []
    development_cdr3: list[str] = []
    train_count = 0
    development_count = 0
    for row in teacher_rows:
        candidate_id = row["candidate_id"].strip()
        require(bool(candidate_id), "empty_candidate_id")
        require(candidate_id not in candidate_ids, f"duplicate_candidate:{candidate_id}")
        candidate_ids.add(candidate_id)
        sequence = row["sequence"].strip().upper()
        require(sequence == row["sequence"], f"noncanonical_sequence:{candidate_id}")
        require(bool(sequence) and set(sequence) <= AA, f"invalid_sequence:{candidate_id}")
        sequence_sha = row["sequence_sha256"].strip()
        require(HEX64.fullmatch(sequence_sha) is not None, f"invalid_sequence_hash:{candidate_id}")
        require(hashlib.sha256(sequence.encode()).hexdigest() == sequence_sha, f"sequence_hash:{candidate_id}")
        require(sequence_sha not in sequence_hashes, f"duplicate_sequence:{candidate_id}")
        sequence_hashes.add(sequence_sha)
        for cdr_name in ("cdr1", "cdr2", "cdr3"):
            cdr = row[cdr_name].strip().upper()
            require(bool(cdr) and cdr in sequence, f"invalid_{cdr_name}:{candidate_id}")

        weight = _finite(row["sample_weight"], "sample_weight", candidate_id)
        require(weight > 0, f"nonpositive_sample_weight:{candidate_id}")
        r8 = _finite(row["R_8X6B"], "R8", candidate_id)
        r9 = _finite(row["R_9E6Y"], "R9", candidate_id)
        dual = _finite(row["R_dual_min"], "Rdual", candidate_id)
        require(abs(dual - min(r8, r9)) < 2e-8, f"truth_exact_min:{candidate_id}")
        require(bool(row["teacher_source"].strip()), f"empty_teacher_source:{candidate_id}")
        reliability = row["teacher_reliability"].strip().upper()
        require(bool(reliability), f"empty_teacher_reliability:{candidate_id}")
        require(
            not any(token in reliability for token in ("TECHNICAL_NA", "QUARANTINE", "FROZEN")),
            f"forbidden_reliability_state:{candidate_id}:{reliability}",
        )
        if "training_label_status" in row:
            require(
                row["training_label_status"] == "WEAK_LABEL_AVAILABLE",
                f"nonlabel_row_in_teacher:{candidate_id}",
            )

        parent = row["parent_framework_cluster"].strip()
        require(parent not in frozen_parents, f"frozen_parent_in_teacher:{candidate_id}:{parent}")
        cdr3 = row["cdr3"].strip().upper()
        if parent in train_parents:
            train_count += 1
            observed_train_parents.add(parent)
            train_cdr3.append(cdr3)
            expected_split = "train"
        elif parent in development_parents:
            development_count += 1
            observed_development_parents.add(parent)
            development_cdr3.append(cdr3)
            expected_split = "development"
        else:
            raise VerificationError(f"parent_outside_open_split:{candidate_id}:{parent}")
        if "canonical_model_split" in row:
            require(row["canonical_model_split"] == expected_split, f"row_split_mismatch:{candidate_id}")

    require(train_count == expected.train, f"train_row_count:{train_count}")
    require(development_count == expected.development, f"development_row_count:{development_count}")
    require(train_count + development_count == expected.open_total, "open_count_arithmetic")
    require(observed_train_parents == train_parents, "train_parent_closure")
    require(observed_development_parents == development_parents, "development_parent_closure")

    cdr3_leaks = hamming80_cross_split_examples(train_cdr3, development_cdr3)
    require(not cdr3_leaks, f"cdr3_hamming80_cross_split:{cdr3_leaks[0] if cdr3_leaks else ''}")

    quarantine_rows, quarantine_fields = load_tsv(quarantine_tsv, "quarantine")
    require(len(quarantine_rows) == expected.new_quarantine, f"new_quarantine_count:{len(quarantine_rows)}")
    require({"candidate_id", "sequence_sha256"} <= set(quarantine_fields), "quarantine_columns_missing")
    reason_columns = [
        column for column in ("quarantine_reason", "split_exclusion_reason", "reason")
        if column in quarantine_fields
    ]
    require(bool(reason_columns), "quarantine_reason_column_missing")
    quarantine_candidates: set[str] = set()
    quarantine_sequences: set[str] = set()
    for row in quarantine_rows:
        candidate_id = row["candidate_id"].strip()
        sequence_sha = row["sequence_sha256"].strip()
        require(bool(candidate_id), "empty_quarantine_candidate")
        require(HEX64.fullmatch(sequence_sha) is not None, f"invalid_quarantine_sequence_hash:{candidate_id}")
        require(candidate_id not in quarantine_candidates, f"duplicate_quarantine_candidate:{candidate_id}")
        require(sequence_sha not in quarantine_sequences, f"duplicate_quarantine_sequence:{candidate_id}")
        require(candidate_id not in candidate_ids, f"quarantine_candidate_in_teacher:{candidate_id}")
        require(sequence_sha not in sequence_hashes, f"quarantine_sequence_in_teacher:{candidate_id}")
        require(any(row[column].strip() for column in reason_columns), f"empty_quarantine_reason:{candidate_id}")
        quarantine_candidates.add(candidate_id)
        quarantine_sequences.add(sequence_sha)

    manifest_total = manifest.get("expected_total_rows")
    manifest_train = manifest.get("expected_train_rows")
    manifest_development = manifest.get("expected_score_rows")
    require(manifest_total in (None, expected.open_total), "manifest_total_count")
    require(manifest_train in (None, expected.train), "manifest_train_count")
    require(manifest_development in (None, expected.development), "manifest_development_count")

    receipt_hashes = recursively_collect_hashes(receipt)
    for digest, label in (
        (teacher_sha, "teacher"),
        (split_sha, "split_manifest"),
        (quarantine_sha, "quarantine"),
    ):
        require(digest in receipt_hashes, f"receipt_missing_{label}_hash")
    require(
        str(receipt.get("status", "")).startswith(("PASS", "READY")),
        "receipt_not_pass",
    )
    bound_files = verify_sha256sums(
        sha256sums,
        (teacher_tsv, split_manifest, quarantine_tsv, receipt_json),
    )

    return {
        "schema_version": "pvrig_v2_10_independent_open_teacher_verification_v1",
        "status": "PASS_V2_10_CANONICAL_OPEN_TEACHER",
        "counts": {
            "train": train_count,
            "development": development_count,
            "open_total": len(teacher_rows),
            "new_quarantine": len(quarantine_rows),
            "unique_candidates": len(candidate_ids),
            "unique_sequences": len(sequence_hashes),
        },
        "leakage": {
            "parent_cross_split": 0,
            "cdr3_hamming80_cross_split": 0,
            "frozen_parent_rows": 0,
            "quarantine_rows_in_teacher": 0,
            "technical_na_rows": 0,
        },
        "targets": {"Rdual_exact_min_violations": 0, "nonfinite_rows": 0},
        "hashes": {
            "teacher_sha256": teacher_sha,
            "split_manifest_sha256": split_sha,
            "quarantine_sha256": quarantine_sha,
            "receipt_sha256": receipt_sha,
            "sha256sums_sha256": sha256_file(sha256sums),
            "verified_manifest_entries": bound_files,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher-tsv", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--quarantine-tsv", type=Path, required=True)
    parser.add_argument("--receipt-json", type=Path, required=True)
    parser.add_argument("--sha256sums", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = verify_release(
            teacher_tsv=args.teacher_tsv,
            split_manifest=args.split_manifest,
            quarantine_tsv=args.quarantine_tsv,
            receipt_json=args.receipt_json,
            sha256sums=args.sha256sums,
        )
    except VerificationError as exc:
        print(json.dumps({
            "schema_version": "pvrig_v2_10_independent_open_teacher_verification_v1",
            "status": "FAIL_V2_10_CANONICAL_OPEN_TEACHER",
            "error": str(exc),
        }, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
