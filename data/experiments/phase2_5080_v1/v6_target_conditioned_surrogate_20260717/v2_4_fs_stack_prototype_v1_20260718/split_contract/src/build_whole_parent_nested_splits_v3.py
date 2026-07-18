#!/usr/bin/env python3
"""Build deterministic whole-parent outer/inner manifests for V2.4 base training."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


BUILDER_VERSION = "pvrig_v2_4_whole_parent_nested_split_builder_v3_parent_balanced"
OUTER_SCHEMA_VERSION = "pvrig_v2_4_whole_parent_outer_split_manifest_v3"
INNER_SCHEMA_VERSION = "pvrig_v2_4_whole_parent_inner_split_manifest_v3"
SUMMARY_SCHEMA_VERSION = "pvrig_v2_4_whole_parent_nested_split_summary_v3"
EXPECTED_PARENT_COUNT = 31

REQUIRED_INPUT_COLUMNS = (
    "candidate_id",
    "teacher_source",
    "parent_framework_cluster",
    "outer_fold",
)

OUTER_COLUMNS = (
    "schema_version",
    "split_level",
    "split_purpose",
    "outer_fold",
    "candidate_id",
    "teacher_source",
    "parent_framework_cluster",
    "input_outer_fold",
    "candidate_role",
    "train_parent_set_sha256",
    "score_parent_set_sha256",
    "input_table_sha256",
    "builder_version",
)

INNER_COLUMNS = (
    "schema_version",
    "split_level",
    "split_purpose",
    "outer_fold",
    "inner_fold",
    "inner_seed",
    "candidate_id",
    "teacher_source",
    "parent_framework_cluster",
    "input_outer_fold",
    "candidate_role",
    "train_parent_set_sha256",
    "score_parent_set_sha256",
    "outer_train_parent_set_sha256",
    "outer_score_parent_set_sha256",
    "input_table_sha256",
    "builder_version",
    "inner_assignment_algorithm",
)

INNER_ASSIGNMENT_ALGORITHM = (
    "whole-parent deterministic capacity-constrained LPT; each fold parent capacity "
    "differs by at most one; descending candidate count; sha256(seed,outer,parent) "
    "tie break; min(candidate_load,parent_load,fold) among folds below capacity"
)

_V4F_TOKEN = re.compile(r"(^|[/\\._-])v4[/\\._-]?f($|[/\\._-])", re.IGNORECASE)


class SplitContractError(ValueError):
    """Raised when the input or generated split violates whole-parent closure."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_parent_set_sha256(parents: Iterable[str]) -> str:
    payload = "".join(f"{parent}\n" for parent in sorted(set(parents))).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _fold_sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def _contains_v4f(value: str) -> bool:
    return _V4F_TOKEN.search(value) is not None


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def read_training_table(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if _contains_v4f(str(path.resolve())):
        raise SplitContractError(f"forbidden_v4f_input_path:{path.resolve()}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise SplitContractError(f"missing_input_header:{path}")
        rows = list(reader)
    validate_training_rows(rows, reader.fieldnames)
    return rows, list(reader.fieldnames)


def validate_training_rows(
    rows: Sequence[Mapping[str, str]], fieldnames: Sequence[str]
) -> None:
    missing = [column for column in REQUIRED_INPUT_COLUMNS if column not in fieldnames]
    if missing:
        raise SplitContractError("missing_input_columns:" + ",".join(missing))
    if not rows:
        raise SplitContractError("empty_training_table")

    candidate_ids: set[str] = set()
    parent_outer_fold: dict[str, str] = {}
    parent_source: dict[str, str] = {}
    for row_number, row in enumerate(rows, start=2):
        for column in REQUIRED_INPUT_COLUMNS:
            if str(row.get(column, "")).strip() == "":
                raise SplitContractError(
                    f"blank_input_value:row={row_number}:column={column}"
                )
        candidate = str(row["candidate_id"])
        source = str(row["teacher_source"])
        parent = str(row["parent_framework_cluster"])
        outer_fold = str(row["outer_fold"])
        if candidate in candidate_ids:
            raise SplitContractError(f"duplicate_candidate_id:{candidate}")
        candidate_ids.add(candidate)
        if re.sub(r"[^a-z0-9]", "", source.lower()) == "v4f" or _contains_v4f(source):
            raise SplitContractError(f"forbidden_v4f_source:{candidate}:{source}")
        if _contains_v4f(parent) or _contains_v4f(candidate):
            raise SplitContractError(f"forbidden_v4f_row_value:{candidate}:{parent}")

        previous_fold = parent_outer_fold.setdefault(parent, outer_fold)
        if previous_fold != outer_fold:
            raise SplitContractError(
                f"parent_in_multiple_outer_folds:{parent}:{previous_fold}:{outer_fold}"
            )
        previous_source = parent_source.setdefault(parent, source)
        if previous_source != source:
            raise SplitContractError(
                f"parent_in_multiple_sources:{parent}:{previous_source}:{source}"
            )

    if len(parent_outer_fold) != EXPECTED_PARENT_COUNT:
        raise SplitContractError(
            f"parent_closure_not_31:observed={len(parent_outer_fold)}"
        )
    if len(set(parent_outer_fold.values())) < 2:
        raise SplitContractError("fewer_than_two_outer_folds")


def _inner_priority(seed: int, outer_fold: str, parent: str) -> str:
    payload = f"{seed}\0{outer_fold}\0{parent}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def assign_inner_folds(
    *,
    outer_fold: str,
    parent_candidate_counts: Mapping[str, int],
    inner_fold_count: int,
    inner_seed: int,
) -> dict[str, str]:
    if inner_fold_count < 2:
        raise SplitContractError("inner_fold_count_below_two")
    if len(parent_candidate_counts) < inner_fold_count:
        raise SplitContractError(
            f"too_few_outer_train_parents_for_inner_folds:outer={outer_fold}:"
            f"parents={len(parent_candidate_counts)}:folds={inner_fold_count}"
        )
    ordered_parents = sorted(
        parent_candidate_counts,
        key=lambda parent: (
            -int(parent_candidate_counts[parent]),
            _inner_priority(inner_seed, outer_fold, parent),
            parent,
        ),
    )
    base_capacity = len(parent_candidate_counts) // inner_fold_count
    extra_capacity = len(parent_candidate_counts) % inner_fold_count
    parent_capacity = [
        base_capacity + (1 if index < extra_capacity else 0)
        for index in range(inner_fold_count)
    ]
    candidate_load = [0 for _ in range(inner_fold_count)]
    parent_load = [0 for _ in range(inner_fold_count)]
    assignment: dict[str, str] = {}
    for parent in ordered_parents:
        eligible_folds = [
            index
            for index in range(inner_fold_count)
            if parent_load[index] < parent_capacity[index]
        ]
        if not eligible_folds:
            raise AssertionError("no_inner_fold_below_parent_capacity")
        fold_index = min(
            eligible_folds,
            key=lambda index: (candidate_load[index], parent_load[index], index),
        )
        assignment[parent] = str(fold_index)
        candidate_load[fold_index] += int(parent_candidate_counts[parent])
        parent_load[fold_index] += 1
    if set(assignment) != set(parent_candidate_counts):
        raise AssertionError("inner_parent_assignment_not_closed")
    if set(assignment.values()) != {str(index) for index in range(inner_fold_count)}:
        raise SplitContractError(f"empty_inner_fold:outer={outer_fold}")
    observed_parent_load = Counter(assignment.values())
    if max(observed_parent_load.values()) - min(observed_parent_load.values()) > 1:
        raise SplitContractError(f"inner_parent_count_imbalance:outer={outer_fold}")
    return assignment


def build_manifests(
    rows: Sequence[Mapping[str, str]],
    *,
    input_table_sha256: str,
    inner_fold_count: int,
    inner_seed: int,
    development_outer_fold: str | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    validate_training_rows(rows, REQUIRED_INPUT_COLUMNS)
    if not _is_sha256(input_table_sha256):
        raise SplitContractError(f"invalid_input_table_sha256:{input_table_sha256}")
    parents = sorted({str(row["parent_framework_cluster"]) for row in rows})
    if len(parents) != EXPECTED_PARENT_COUNT:
        raise SplitContractError(f"parent_closure_not_31:observed={len(parents)}")
    folds = sorted({str(row["outer_fold"]) for row in rows}, key=_fold_sort_key)
    if development_outer_fold is not None:
        if str(development_outer_fold) not in folds:
            raise SplitContractError(
                f"unknown_development_outer_fold:{development_outer_fold}"
            )
        selected_folds = [str(development_outer_fold)]
    else:
        selected_folds = folds

    candidate_counts = Counter(str(row["parent_framework_cluster"]) for row in rows)
    rows_sorted = sorted(rows, key=lambda row: str(row["candidate_id"]))
    outer_manifest: list[dict[str, str]] = []
    inner_manifest: list[dict[str, str]] = []
    outer_summaries: dict[str, Any] = {}

    for outer_fold in selected_folds:
        score_parents = {
            str(row["parent_framework_cluster"])
            for row in rows
            if str(row["outer_fold"]) == outer_fold
        }
        train_parents = set(parents) - score_parents
        train_digest = canonical_parent_set_sha256(train_parents)
        score_digest = canonical_parent_set_sha256(score_parents)
        for row in rows_sorted:
            parent = str(row["parent_framework_cluster"])
            outer_manifest.append(
                {
                    "schema_version": OUTER_SCHEMA_VERSION,
                    "split_level": "outer",
                    "split_purpose": "development",
                    "outer_fold": outer_fold,
                    "candidate_id": str(row["candidate_id"]),
                    "teacher_source": str(row["teacher_source"]),
                    "parent_framework_cluster": parent,
                    "input_outer_fold": str(row["outer_fold"]),
                    "candidate_role": "score" if parent in score_parents else "train",
                    "train_parent_set_sha256": train_digest,
                    "score_parent_set_sha256": score_digest,
                    "input_table_sha256": input_table_sha256,
                    "builder_version": BUILDER_VERSION,
                }
            )

        outer_train_counts = {
            parent: int(candidate_counts[parent]) for parent in sorted(train_parents)
        }
        inner_assignment = assign_inner_folds(
            outer_fold=outer_fold,
            parent_candidate_counts=outer_train_counts,
            inner_fold_count=inner_fold_count,
            inner_seed=inner_seed,
        )
        for inner_fold in (str(index) for index in range(inner_fold_count)):
            inner_score_parents = {
                parent for parent, assigned in inner_assignment.items() if assigned == inner_fold
            }
            inner_train_parents = train_parents - inner_score_parents
            inner_train_digest = canonical_parent_set_sha256(inner_train_parents)
            inner_score_digest = canonical_parent_set_sha256(inner_score_parents)
            for row in rows_sorted:
                parent = str(row["parent_framework_cluster"])
                if parent not in train_parents:
                    continue
                inner_manifest.append(
                    {
                        "schema_version": INNER_SCHEMA_VERSION,
                        "split_level": "inner",
                        "split_purpose": "nested_oof_base_feature",
                        "outer_fold": outer_fold,
                        "inner_fold": inner_fold,
                        "inner_seed": str(inner_seed),
                        "candidate_id": str(row["candidate_id"]),
                        "teacher_source": str(row["teacher_source"]),
                        "parent_framework_cluster": parent,
                        "input_outer_fold": str(row["outer_fold"]),
                        "candidate_role": (
                            "score" if parent in inner_score_parents else "train"
                        ),
                        "train_parent_set_sha256": inner_train_digest,
                        "score_parent_set_sha256": inner_score_digest,
                        "outer_train_parent_set_sha256": train_digest,
                        "outer_score_parent_set_sha256": score_digest,
                        "input_table_sha256": input_table_sha256,
                        "builder_version": BUILDER_VERSION,
                        "inner_assignment_algorithm": INNER_ASSIGNMENT_ALGORITHM,
                    }
                )

        outer_summaries[outer_fold] = {
            "outer_train_parent_count": len(train_parents),
            "outer_score_parent_count": len(score_parents),
            "outer_train_candidate_count": sum(candidate_counts[p] for p in train_parents),
            "outer_score_candidate_count": sum(candidate_counts[p] for p in score_parents),
            "outer_train_parent_set_sha256": train_digest,
            "outer_score_parent_set_sha256": score_digest,
            "inner_parent_assignment": dict(sorted(inner_assignment.items())),
            "inner_score_parent_counts": dict(Counter(inner_assignment.values())),
            "inner_parent_count_difference": (
                max(Counter(inner_assignment.values()).values())
                - min(Counter(inner_assignment.values()).values())
            ),
            "inner_score_candidate_counts": {
                inner_fold: sum(
                    candidate_counts[parent]
                    for parent, assigned in inner_assignment.items()
                    if assigned == inner_fold
                )
                for inner_fold in sorted(set(inner_assignment.values()), key=_fold_sort_key)
            },
        }

    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "input_table_sha256": input_table_sha256,
        "input_candidate_count": len(rows),
        "input_parent_count": len(parents),
        "expected_parent_count": EXPECTED_PARENT_COUNT,
        "input_outer_folds": folds,
        "selected_outer_folds": selected_folds,
        "development_outer_fold": development_outer_fold,
        "inner_fold_count": inner_fold_count,
        "inner_seed": inner_seed,
        "inner_assignment_algorithm": INNER_ASSIGNMENT_ALGORITHM,
        "outer_manifest_row_count": len(outer_manifest),
        "inner_manifest_row_count": len(inner_manifest),
        "outer_splits": outer_summaries,
    }
    validate_generated_manifests(
        rows,
        outer_manifest,
        inner_manifest,
        summary,
        input_table_sha256=input_table_sha256,
    )
    summary["validation_status"] = "PASS_WHOLE_PARENT_31_PARENT_CLOSURE"
    return outer_manifest, inner_manifest, summary


def _validate_common_manifest_rows(
    manifest: Sequence[Mapping[str, str]],
    *,
    exact_columns: Sequence[str],
    schema_version: str,
    input_table_sha256: str,
) -> None:
    if not manifest:
        raise SplitContractError("empty_generated_manifest")
    for row_number, row in enumerate(manifest, start=2):
        if tuple(row) != tuple(exact_columns):
            raise SplitContractError(f"generated_column_order_mismatch:row={row_number}")
        if row["schema_version"] != schema_version:
            raise SplitContractError(f"generated_schema_mismatch:row={row_number}")
        if row["candidate_role"] not in {"train", "score"}:
            raise SplitContractError(f"invalid_candidate_role:row={row_number}")
        if row["input_table_sha256"] != input_table_sha256:
            raise SplitContractError(f"input_sha_mismatch:row={row_number}")
        if _contains_v4f(row["teacher_source"]):
            raise SplitContractError(f"forbidden_v4f_manifest_row:row={row_number}")


def validate_generated_manifests(
    input_rows: Sequence[Mapping[str, str]],
    outer_manifest: Sequence[Mapping[str, str]],
    inner_manifest: Sequence[Mapping[str, str]],
    summary: Mapping[str, Any],
    *,
    input_table_sha256: str,
) -> None:
    _validate_common_manifest_rows(
        outer_manifest,
        exact_columns=OUTER_COLUMNS,
        schema_version=OUTER_SCHEMA_VERSION,
        input_table_sha256=input_table_sha256,
    )
    _validate_common_manifest_rows(
        inner_manifest,
        exact_columns=INNER_COLUMNS,
        schema_version=INNER_SCHEMA_VERSION,
        input_table_sha256=input_table_sha256,
    )

    input_candidates = {str(row["candidate_id"]) for row in input_rows}
    input_parents = {str(row["parent_framework_cluster"]) for row in input_rows}
    if len(input_parents) != EXPECTED_PARENT_COUNT:
        raise SplitContractError(f"parent_closure_not_31:observed={len(input_parents)}")
    input_parent_fold = {
        str(row["parent_framework_cluster"]): str(row["outer_fold"])
        for row in input_rows
    }
    selected_outer_folds = [str(value) for value in summary["selected_outer_folds"]]

    outer_by_fold: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in outer_manifest:
        outer_by_fold[str(row["outer_fold"])].append(row)
    if set(outer_by_fold) != set(selected_outer_folds):
        raise SplitContractError("outer_manifest_fold_closure_failure")

    outer_train_parents_by_fold: dict[str, set[str]] = {}
    outer_score_parents_by_fold: dict[str, set[str]] = {}
    for outer_fold, split_rows in outer_by_fold.items():
        candidate_counts = Counter(str(row["candidate_id"]) for row in split_rows)
        if set(candidate_counts) != input_candidates or any(v != 1 for v in candidate_counts.values()):
            raise SplitContractError(f"outer_candidate_closure_failure:outer={outer_fold}")
        train_parents = {
            str(row["parent_framework_cluster"])
            for row in split_rows
            if row["candidate_role"] == "train"
        }
        score_parents = {
            str(row["parent_framework_cluster"])
            for row in split_rows
            if row["candidate_role"] == "score"
        }
        if train_parents & score_parents:
            raise SplitContractError(f"outer_train_score_parent_overlap:outer={outer_fold}")
        if train_parents | score_parents != input_parents:
            raise SplitContractError(f"outer_31_parent_closure_failure:outer={outer_fold}")
        expected_score = {
            parent for parent, assigned_fold in input_parent_fold.items() if assigned_fold == outer_fold
        }
        if score_parents != expected_score:
            raise SplitContractError(f"outer_score_parent_assignment_mismatch:outer={outer_fold}")
        train_digest = canonical_parent_set_sha256(train_parents)
        score_digest = canonical_parent_set_sha256(score_parents)
        if any(row["train_parent_set_sha256"] != train_digest for row in split_rows):
            raise SplitContractError(f"outer_train_parent_digest_mismatch:outer={outer_fold}")
        if any(row["score_parent_set_sha256"] != score_digest for row in split_rows):
            raise SplitContractError(f"outer_score_parent_digest_mismatch:outer={outer_fold}")
        outer_train_parents_by_fold[outer_fold] = train_parents
        outer_score_parents_by_fold[outer_fold] = score_parents

    inner_by_split: dict[tuple[str, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in inner_manifest:
        inner_by_split[(str(row["outer_fold"]), str(row["inner_fold"]))].append(row)
    expected_inner_keys = {
        (outer_fold, str(index))
        for outer_fold in selected_outer_folds
        for index in range(int(summary["inner_fold_count"]))
    }
    if set(inner_by_split) != expected_inner_keys:
        raise SplitContractError("inner_split_key_closure_failure")

    score_occurrences: dict[tuple[str, str], int] = Counter()
    for (outer_fold, inner_fold), split_rows in inner_by_split.items():
        outer_train_parents = outer_train_parents_by_fold[outer_fold]
        outer_score_parents = outer_score_parents_by_fold[outer_fold]
        expected_candidates = {
            str(row["candidate_id"])
            for row in input_rows
            if str(row["parent_framework_cluster"]) in outer_train_parents
        }
        candidate_counts = Counter(str(row["candidate_id"]) for row in split_rows)
        if set(candidate_counts) != expected_candidates or any(v != 1 for v in candidate_counts.values()):
            raise SplitContractError(
                f"inner_candidate_closure_failure:outer={outer_fold}:inner={inner_fold}"
            )
        train_parents = {
            str(row["parent_framework_cluster"])
            for row in split_rows
            if row["candidate_role"] == "train"
        }
        score_parents = {
            str(row["parent_framework_cluster"])
            for row in split_rows
            if row["candidate_role"] == "score"
        }
        if train_parents & score_parents:
            raise SplitContractError(
                f"inner_train_score_parent_overlap:outer={outer_fold}:inner={inner_fold}"
            )
        if train_parents | score_parents != outer_train_parents:
            raise SplitContractError(
                f"inner_outer_train_parent_closure_failure:outer={outer_fold}:inner={inner_fold}"
            )
        if (train_parents | score_parents) & outer_score_parents:
            raise SplitContractError(
                f"outer_score_parent_leaked_into_inner:outer={outer_fold}:inner={inner_fold}"
            )
        train_digest = canonical_parent_set_sha256(train_parents)
        score_digest = canonical_parent_set_sha256(score_parents)
        outer_train_digest = canonical_parent_set_sha256(outer_train_parents)
        outer_score_digest = canonical_parent_set_sha256(outer_score_parents)
        for row in split_rows:
            if row["train_parent_set_sha256"] != train_digest:
                raise SplitContractError("inner_train_parent_digest_mismatch")
            if row["score_parent_set_sha256"] != score_digest:
                raise SplitContractError("inner_score_parent_digest_mismatch")
            if row["outer_train_parent_set_sha256"] != outer_train_digest:
                raise SplitContractError("inner_outer_train_parent_digest_mismatch")
            if row["outer_score_parent_set_sha256"] != outer_score_digest:
                raise SplitContractError("inner_outer_score_parent_digest_mismatch")
        for parent in score_parents:
            score_occurrences[(outer_fold, parent)] += 1

    for outer_fold, train_parents in outer_train_parents_by_fold.items():
        inner_parent_counts = Counter(
            inner_fold
            for (fold, inner_fold), split_rows in inner_by_split.items()
            if fold == outer_fold
            for parent in {
                str(row["parent_framework_cluster"])
                for row in split_rows
                if row["candidate_role"] == "score"
            }
        )
        if max(inner_parent_counts.values()) - min(inner_parent_counts.values()) > 1:
            raise SplitContractError(
                f"inner_parent_count_difference_above_one:outer={outer_fold}"
            )
        for parent in train_parents:
            if score_occurrences[(outer_fold, parent)] != 1:
                raise SplitContractError(
                    f"inner_score_once_failure:outer={outer_fold}:parent={parent}:"
                    f"count={score_occurrences[(outer_fold, parent)]}"
                )


def write_tsv(path: Path, rows: Sequence[Mapping[str, str]], columns: Sequence[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_manifest_tsv(path: Path, expected_columns: Sequence[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != tuple(expected_columns):
            raise SplitContractError(f"materialized_header_mismatch:{path}")
        return list(reader)


def run(args: argparse.Namespace) -> dict[str, Any]:
    input_path = Path(args.input_tsv).resolve()
    output_dir = Path(args.output_dir).resolve()
    if _contains_v4f(str(output_dir)):
        raise SplitContractError(f"forbidden_v4f_output_path:{output_dir}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SplitContractError(f"nonempty_output_directory:{output_dir}")
    rows, _ = read_training_table(input_path)
    input_sha = sha256_file(input_path)
    outer_rows, inner_rows, summary = build_manifests(
        rows,
        input_table_sha256=input_sha,
        inner_fold_count=int(args.inner_fold_count),
        inner_seed=int(args.inner_seed),
        development_outer_fold=(
            None if args.development_outer_fold is None else str(args.development_outer_fold)
        ),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    outer_path = output_dir / "outer_development_manifest.tsv"
    inner_path = output_dir / "inner_nested_oof_manifest.tsv"
    summary_path = output_dir / "split_summary.json"
    write_tsv(outer_path, outer_rows, OUTER_COLUMNS)
    write_tsv(inner_path, inner_rows, INNER_COLUMNS)
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    materialized_outer_rows = read_manifest_tsv(outer_path, OUTER_COLUMNS)
    materialized_inner_rows = read_manifest_tsv(inner_path, INNER_COLUMNS)
    materialized_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    validate_generated_manifests(
        rows,
        materialized_outer_rows,
        materialized_inner_rows,
        materialized_summary,
        input_table_sha256=input_sha,
    )
    receipt = {
        "status": "PASS_WHOLE_PARENT_31_PARENT_CLOSURE",
        "materialized_readback_validation": "PASS",
        "builder_version": BUILDER_VERSION,
        "builder_script": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "input_table": {"path": str(input_path), "sha256": input_sha},
        "outer_development_manifest": {
            "path": str(outer_path),
            "rows": len(outer_rows),
            "sha256": sha256_file(outer_path),
        },
        "inner_nested_oof_manifest": {
            "path": str(inner_path),
            "rows": len(inner_rows),
            "sha256": sha256_file(inner_path),
        },
        "split_summary": {
            "path": str(summary_path),
            "sha256": sha256_file(summary_path),
        },
    }
    receipt_path = output_dir / "receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-tsv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--inner-fold-count", type=int, default=5)
    parser.add_argument("--inner-seed", type=int, required=True)
    parser.add_argument("--development-outer-fold")
    return parser


def main() -> int:
    receipt = run(build_parser().parse_args())
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
