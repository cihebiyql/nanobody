#!/usr/bin/env python3
"""Build leakage-safe primary D0/D1 teachers for PVRIG V2.9.

Inputs:
1. the old 3388-row labelled teacher;
2. the V29 *label-free* candidate/split table;
3. an independently frozen V29 open-only train/development label snapshot.

Frozen-test parent identities are learned only from the label-free candidate
table.  Old labelled rows sharing those parents are removed completely.  The
program never accepts a frozen-test label source and checks a snapshot row's
candidate ID against the open allowlist before parsing any numeric label.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "pvrig_v2_9_primary_d0_d1_teacher_builder_v1"
RECEIPT_SCHEMA = "pvrig_v2_9_primary_d0_d1_teacher_receipt_v1"
SPLIT_SCHEMA = "pvrig_v2_9_whole_parent_split_v1"
CLAIM = (
    "Open-development sequence-to-independent-dual-receptor computational "
    "Docking geometry supervision only; not binding, affinity, experimental "
    "blocking, Docking Gold, frozen-test labels, or formal validation."
)
AA = set("ACDEFGHIKLMNPQRSTVWY")
OUTPUT_COLUMNS = (
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
)
OLD_REQUIRED = set(OUTPUT_COLUMNS)
CANDIDATE_REQUIRED = {
    "candidate_id", "sequence", "sequence_sha256", "cdr1", "cdr2", "cdr3",
    "parent_framework_cluster", "model_split",
}
SNAPSHOT_REQUIRED = {
    "candidate_id", "sample_weight", "R_8X6B", "R_9E6Y", "R_dual_min",
    "teacher_source", "teacher_reliability",
}
OPEN_SPLITS = {"train", "development"}
ALL_SPLITS = OPEN_SPLITS | {"frozen_test"}
FORBIDDEN_LABEL_PATH_TOKENS = (
    "frozen_test", "frozen-test", "sealed", "formal_test", "formal-test",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def stable_set_hash(values: Iterable[str]) -> str:
    return hashlib.sha256(
        ("\n".join(sorted(set(values))) + "\n").encode()
    ).hexdigest()


def verify_input(path: Path, expected_sha256: str, label: str) -> None:
    require(path.is_file() and not path.is_symlink(), f"{label}_not_regular:{path}")
    require(len(expected_sha256) == 64, f"{label}_expected_hash_invalid")
    require(sha256_file(path) == expected_sha256, f"{label}_hash_mismatch")


def reject_frozen_label_path(path: Path) -> None:
    text = str(path).lower()
    for token in FORBIDDEN_LABEL_PATH_TOKENS:
        require(token not in text, f"forbidden_snapshot_path_token:{token}")


def validate_sequence_fields(row: dict[str, str], label: str) -> dict[str, str]:
    candidate_id = row["candidate_id"].strip()
    sequence = row["sequence"].strip().upper()
    require(candidate_id, f"empty_candidate_id:{label}")
    require(sequence and set(sequence) <= AA, f"invalid_sequence:{candidate_id}")
    require(
        hashlib.sha256(sequence.encode("ascii")).hexdigest() == row["sequence_sha256"],
        f"sequence_hash:{candidate_id}",
    )
    result = dict(row)
    result["candidate_id"] = candidate_id
    result["sequence"] = sequence
    result["parent_framework_cluster"] = row["parent_framework_cluster"].strip()
    require(result["parent_framework_cluster"], f"empty_parent:{candidate_id}")
    for key in ("cdr1", "cdr2", "cdr3"):
        region = row[key].strip().upper()
        require(region and region in sequence, f"invalid_{key}:{candidate_id}")
        result[key] = region
    return result


def parse_geometry(row: dict[str, str], candidate_id: str) -> dict[str, str]:
    """Parse geometry only after the caller proves candidate is open."""
    r8 = float(row["R_8X6B"])
    r9 = float(row["R_9E6Y"])
    dual = float(row["R_dual_min"])
    weight = float(row["sample_weight"])
    require(
        all(math.isfinite(value) for value in (r8, r9, dual, weight)),
        f"nonfinite_geometry:{candidate_id}",
    )
    require(weight > 0, f"nonpositive_sample_weight:{candidate_id}")
    require(abs(min(r8, r9) - dual) < 2e-8, f"truth_exact_min:{candidate_id}")
    require(row["teacher_source"].strip(), f"empty_teacher_source:{candidate_id}")
    require(row["teacher_reliability"].strip(), f"empty_teacher_reliability:{candidate_id}")
    return {
        "sample_weight": f"{weight:.9g}",
        "R_8X6B": f"{r8:.9f}",
        "R_9E6Y": f"{r9:.9f}",
        "R_dual_min": f"{dual:.9f}",
        "teacher_source": row["teacher_source"].strip(),
        "teacher_reliability": row["teacher_reliability"].strip(),
    }


def load_v29_candidates(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    parent_splits: dict[str, str] = {}
    sequence_hashes: set[str] = set()
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(CANDIDATE_REQUIRED.issubset(set(reader.fieldnames or [])), "v29_candidate_columns_missing")
        for raw in reader:
            row = validate_sequence_fields(raw, "v29_candidates")
            candidate_id = row["candidate_id"]
            require(candidate_id not in rows, f"duplicate_v29_candidate:{candidate_id}")
            require(row["sequence_sha256"] not in sequence_hashes, f"duplicate_v29_sequence:{candidate_id}")
            split = raw["model_split"].strip()
            require(split in ALL_SPLITS, f"invalid_v29_model_split:{candidate_id}:{split}")
            parent = row["parent_framework_cluster"]
            if parent in parent_splits:
                require(parent_splits[parent] == split, f"v29_parent_split_inconsistent:{parent}")
            parent_splits[parent] = split
            row["model_split"] = split
            rows[candidate_id] = row
            sequence_hashes.add(row["sequence_sha256"])
    require(bool(rows), "empty_v29_candidates")
    require(set(parent_splits.values()) == ALL_SPLITS, "v29_split_coverage_missing")
    return rows, parent_splits


def load_old_teacher(path: Path) -> list[dict[str, str]]:
    rows = []
    ids: set[str] = set()
    sequences: set[str] = set()
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(OLD_REQUIRED.issubset(set(reader.fieldnames or [])), "old_teacher_columns_missing")
        for raw in reader:
            seq = validate_sequence_fields(raw, "old_teacher")
            candidate_id = seq["candidate_id"]
            require(candidate_id not in ids, f"duplicate_old_candidate:{candidate_id}")
            require(seq["sequence_sha256"] not in sequences, f"duplicate_old_sequence:{candidate_id}")
            geometry = parse_geometry(raw, candidate_id)
            rows.append({key: (geometry[key] if key in geometry else seq[key]) for key in OUTPUT_COLUMNS})
            ids.add(candidate_id)
            sequences.add(seq["sequence_sha256"])
    require(bool(rows), "empty_old_teacher")
    return rows


def load_open_snapshot(
    path: Path,
    v29_candidates: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    """Read only an open snapshot; gate candidate before numeric parsing."""
    rows = []
    ids: set[str] = set()
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(SNAPSHOT_REQUIRED.issubset(set(reader.fieldnames or [])), "snapshot_columns_missing")
        for raw in reader:
            candidate_id = raw["candidate_id"].strip()
            require(candidate_id in v29_candidates, f"snapshot_candidate_unknown:{candidate_id}")
            candidate = v29_candidates[candidate_id]
            # This check intentionally precedes parsing any geometry field.
            require(
                candidate["model_split"] in OPEN_SPLITS,
                f"snapshot_contains_nonopen_candidate_before_label_parse:{candidate_id}",
            )
            require(candidate_id not in ids, f"duplicate_snapshot_candidate:{candidate_id}")
            geometry = parse_geometry(raw, candidate_id)
            rows.append({
                "candidate_id": candidate_id,
                "sequence_sha256": candidate["sequence_sha256"],
                "sequence": candidate["sequence"],
                "parent_framework_cluster": candidate["parent_framework_cluster"],
                "cdr1": candidate["cdr1"],
                "cdr2": candidate["cdr2"],
                "cdr3": candidate["cdr3"],
                **geometry,
            })
            ids.add(candidate_id)
    return rows


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    require(bool(rows), f"empty_output:{path.name}")
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def create_split_manifest(
    *,
    data_version: str,
    split_id: str,
    teacher_path: Path,
    rows: list[dict[str, str]],
    parent_splits: dict[str, str],
) -> dict[str, Any]:
    observed = {row["parent_framework_cluster"] for row in rows}
    frozen = {parent for parent, split in parent_splits.items() if split == "frozen_test"}
    development = {
        parent for parent in observed if parent_splits.get(parent) == "development"
    }
    train = observed - development
    require(train.isdisjoint(development | frozen), "manifest_parent_overlap")
    require(development.isdisjoint(frozen), "manifest_dev_frozen_overlap")
    require(observed.isdisjoint(frozen), "manifest_teacher_frozen_overlap")
    train_rows = sum(row["parent_framework_cluster"] in train for row in rows)
    score_rows = len(rows) - train_rows
    return {
        "schema_version": SPLIT_SCHEMA,
        "data_version": data_version,
        "split_id": split_id,
        "open_only": True,
        "frozen_test_access_count": 0,
        "sealed_truth_access_count": 0,
        "training_tsv_sha256": sha256_file(teacher_path),
        "train_parents": sorted(train),
        "score_parents": sorted(development),
        "frozen_test_parents": sorted(frozen),
        "train_parent_set_sha256": stable_set_hash(train),
        "score_parent_set_sha256": stable_set_hash(development),
        "frozen_test_parent_set_sha256": stable_set_hash(frozen),
        "expected_total_rows": len(rows),
        "expected_train_rows": train_rows,
        "expected_score_rows": score_rows,
        "claim_boundary": CLAIM,
    }


def optional_count_gate(expected: int | None, observed: int, label: str) -> None:
    if expected is not None:
        require(expected == observed, f"{label}_mismatch:{observed}")


def materialize(
    *,
    old_teacher_tsv: Path,
    old_teacher_sha256: str,
    v29_candidates_tsv: Path,
    v29_candidates_sha256: str,
    v29_open_snapshot_tsv: Path,
    v29_open_snapshot_sha256: str,
    output_dir: Path,
    split_id_prefix: str,
    expected_d0_rows: int | None = None,
    expected_d0_train_rows: int | None = None,
    expected_d0_dev_rows: int | None = None,
) -> dict[str, Any]:
    verify_input(old_teacher_tsv, old_teacher_sha256, "old_teacher")
    verify_input(v29_candidates_tsv, v29_candidates_sha256, "v29_candidates")
    reject_frozen_label_path(v29_open_snapshot_tsv)
    verify_input(v29_open_snapshot_tsv, v29_open_snapshot_sha256, "v29_open_snapshot")
    require(not output_dir.exists(), "output_dir_exists")

    v29_candidates, parent_splits = load_v29_candidates(v29_candidates_tsv)
    old_rows = load_old_teacher(old_teacher_tsv)
    frozen_parents = {parent for parent, split in parent_splits.items() if split == "frozen_test"}
    d0_rows = [row for row in old_rows if row["parent_framework_cluster"] not in frozen_parents]
    excluded_old = [row for row in old_rows if row["parent_framework_cluster"] in frozen_parents]
    snapshot_rows = load_open_snapshot(v29_open_snapshot_tsv, v29_candidates)
    require(
        not ({row["candidate_id"] for row in d0_rows} & {row["candidate_id"] for row in snapshot_rows}),
        "d0_snapshot_candidate_overlap",
    )
    require(
        not ({row["sequence_sha256"] for row in d0_rows} & {row["sequence_sha256"] for row in snapshot_rows}),
        "d0_snapshot_sequence_overlap",
    )
    d1_rows = d0_rows + snapshot_rows
    d0_rows.sort(key=lambda row: row["candidate_id"])
    d1_rows.sort(key=lambda row: row["candidate_id"])

    d0_train = sum(parent_splits.get(row["parent_framework_cluster"]) != "development" for row in d0_rows)
    d0_dev = len(d0_rows) - d0_train
    optional_count_gate(expected_d0_rows, len(d0_rows), "expected_d0_rows")
    optional_count_gate(expected_d0_train_rows, d0_train, "expected_d0_train_rows")
    optional_count_gate(expected_d0_dev_rows, d0_dev, "expected_d0_dev_rows")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=output_dir.parent))
    try:
        d0_teacher = temp_dir / "primary_D0_teacher.tsv"
        d1_teacher = temp_dir / "primary_D1_teacher.tsv"
        write_tsv(d0_teacher, d0_rows)
        write_tsv(d1_teacher, d1_rows)
        d0_split = create_split_manifest(
            data_version="D0",
            split_id=f"{split_id_prefix}_D0",
            teacher_path=d0_teacher,
            rows=d0_rows,
            parent_splits=parent_splits,
        )
        d1_split = create_split_manifest(
            data_version="D1",
            split_id=f"{split_id_prefix}_D1",
            teacher_path=d1_teacher,
            rows=d1_rows,
            parent_splits=parent_splits,
        )
        (temp_dir / "primary_D0_split_manifest.json").write_text(
            json.dumps(d0_split, indent=2, sort_keys=True) + "\n"
        )
        (temp_dir / "primary_D1_split_manifest.json").write_text(
            json.dumps(d1_split, indent=2, sort_keys=True) + "\n"
        )
        source_counts = Counter(row["teacher_source"] for row in d1_rows)
        receipt: dict[str, Any] = {
            "schema_version": RECEIPT_SCHEMA,
            "status": "PASS_PRIMARY_D0_D1_MATERIALIZED",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "claim_boundary": CLAIM,
            "inputs": {
                "old_teacher_tsv": str(old_teacher_tsv),
                "old_teacher_sha256": old_teacher_sha256,
                "v29_label_free_candidates_tsv": str(v29_candidates_tsv),
                "v29_label_free_candidates_sha256": v29_candidates_sha256,
                "v29_open_snapshot_tsv": str(v29_open_snapshot_tsv),
                "v29_open_snapshot_sha256": v29_open_snapshot_sha256,
            },
            "counts": {
                "old_input_rows": len(old_rows),
                "old_rows_excluded_for_v29_frozen_parents": len(excluded_old),
                "D0_rows": len(d0_rows),
                "D0_train_rows": d0_split["expected_train_rows"],
                "D0_development_rows": d0_split["expected_score_rows"],
                "v29_open_snapshot_rows": len(snapshot_rows),
                "D1_rows": len(d1_rows),
                "D1_train_rows": d1_split["expected_train_rows"],
                "D1_development_rows": d1_split["expected_score_rows"],
                "v29_frozen_parent_count": len(frozen_parents),
                "v29_frozen_label_rows_read": 0,
                "v29_frozen_label_numeric_parse_count": 0,
            },
            "parent_sets": {
                "v29_train_parent_count": sum(value == "train" for value in parent_splits.values()),
                "v29_development_parent_count": sum(value == "development" for value in parent_splits.values()),
                "v29_frozen_test_parent_count": len(frozen_parents),
                "v29_frozen_test_parent_set_sha256": stable_set_hash(frozen_parents),
            },
            "teacher_source_distribution_D1": dict(sorted(source_counts.items())),
            "invariants": {
                "old_frozen_parent_rows_completely_excluded": True,
                "old_only_parents_assigned_train": True,
                "v29_train_development_boundary_preserved": True,
                "v29_frozen_labels_input_absent": True,
                "frozen_candidate_checked_before_numeric_label_parse": True,
                "R_dual_exact_min": True,
                "cross_source_candidate_overlap": False,
                "cross_source_sequence_overlap": False,
            },
        }
        output_hashes = {
            path.name: sha256_file(path)
            for path in sorted(temp_dir.iterdir())
            if path.is_file()
        }
        receipt["output_sha256"] = output_hashes
        (temp_dir / "MATERIALIZATION_RECEIPT.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        )
        all_hashes = {
            path.name: sha256_file(path)
            for path in sorted(temp_dir.iterdir())
            if path.is_file() and path.name != "SHA256SUMS"
        }
        (temp_dir / "SHA256SUMS").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in all_hashes.items())
        )
        os.replace(temp_dir, output_dir)
        return receipt
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-teacher-tsv", type=Path, required=True)
    parser.add_argument("--old-teacher-sha256", required=True)
    parser.add_argument("--v29-candidates-tsv", type=Path, required=True)
    parser.add_argument("--v29-candidates-sha256", required=True)
    parser.add_argument("--v29-open-snapshot-tsv", type=Path, required=True)
    parser.add_argument("--v29-open-snapshot-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--split-id-prefix", required=True)
    parser.add_argument("--expected-d0-rows", type=int)
    parser.add_argument("--expected-d0-train-rows", type=int)
    parser.add_argument("--expected-d0-dev-rows", type=int)
    args = parser.parse_args()
    receipt = materialize(
        old_teacher_tsv=args.old_teacher_tsv,
        old_teacher_sha256=args.old_teacher_sha256,
        v29_candidates_tsv=args.v29_candidates_tsv,
        v29_candidates_sha256=args.v29_candidates_sha256,
        v29_open_snapshot_tsv=args.v29_open_snapshot_tsv,
        v29_open_snapshot_sha256=args.v29_open_snapshot_sha256,
        output_dir=args.output_dir,
        split_id_prefix=args.split_id_prefix,
        expected_d0_rows=args.expected_d0_rows,
        expected_d0_train_rows=args.expected_d0_train_rows,
        expected_d0_dev_rows=args.expected_d0_dev_rows,
    )
    print(json.dumps({
        "status": receipt["status"],
        "D0_rows": receipt["counts"]["D0_rows"],
        "D1_rows": receipt["counts"]["D1_rows"],
        "output_dir": str(args.output_dir),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
