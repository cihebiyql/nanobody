#!/usr/bin/env python3
"""Freeze the label-free V4-G unseen-parent acquisition and reserve panels."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "phase2_v4_g_active_learning_freeze_v1"
PREREGISTRATION_VERSION = "phase2_v4_g_active_learning_preregistration_v1"
RECEIPT_VERSION = "phase2_v4_g_active_learning_freeze_receipt_v1"
EXPECTED_POOL_SHA256 = "a92da7c939bf008ffaf7f3a305871477f74466d64f3489e9941c34a61a620e07"
EXPECTED_V4D_SHA256 = "c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd"
EXPECTED_V4F_SHA256 = "3f3c504844756703acecf586b2b218f2e2855c3a108ee22656c8f08e7f57e334"
EXPECTED_POOL_ROWS = 7087
EXPECTED_V4D_ROWS = 290
EXPECTED_V4F_ROWS = 96
EXPECTED_POOL_PARENT_CLUSTERS = 40
EXPECTED_REMAINING_PARENT_CLUSTERS = 10
EXPECTED_V4D_OPEN_TRAIN_PARENT_CLUSTERS = 20
ACQUISITION_PARENT_COUNT = 8
RESERVE_PARENT_COUNT = 2
ROWS_PER_STRATUM = 2
PATCHES = ("A_CENTER", "B_LOWER", "C_CROSS")
MODES = ("H3", "H1H3")
SELECTION_SEED = "phase2_v4_g_active_learning_unseen96_20260716"
MODEL_SPLIT = "V4_G_ACTIVE_LEARNING_UNSEEN_ACQUISITION"
CLAIM_BOUNDARY = (
    "Label-free acquisition design for a future fixed-PVRIG computational docking "
    "surrogate; not docking, binding, affinity, competition, Docking Gold, or "
    "experimental blocking evidence."
)
FORBIDDEN_INPUT_FIELDS = {
    "R_8X6B",
    "R_9E6Y",
    "R_dual_mean",
    "R_dual_min",
    "R_dual_gap",
    "target_R_dual_min",
    "docking_score",
    "haddock_score",
    "geometry_target",
    "experimental_binding",
    "experimental_blocking",
}
OUTPUT_FILENAMES = (
    "unseen96_acquisition_manifest.tsv",
    "untouched_reserve2_parents.tsv",
    "phase2_v4_g_active_learning_preregistration.json",
    "unseen96_acquisition_audit.json",
    "v4_g_active_learning_freeze_receipt.json",
)
MANIFEST_FIELDS = (
    "candidate_id",
    "sequence_sha256",
    "sequence",
    "parent_id",
    "parent_framework_cluster",
    "design_method",
    "design_mode",
    "target_patch_id",
    "cdr1",
    "cdr2",
    "cdr3",
    "cdr3_length",
    "model_split",
    "selection_stratum",
    "selection_rank_in_stratum",
    "selection_hash",
    "full_qc_and_docking_policy",
    "claim_boundary",
)
RESERVE_FIELDS = (
    "parent_framework_cluster",
    "parent_ids",
    "selection_role",
    "parent_hash_rank",
    "selection_hash",
    "eligible_candidate_count",
    "eligible_stratum_count",
    "minimum_eligible_rows_per_stratum",
    "untouched_policy",
    "claim_boundary",
)


class ActiveLearningFreezeError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileSnapshot:
    path: Path
    payload: bytes
    sha256: str
    size_bytes: int


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return sha256_bytes(encoded)


def stable_hash(*parts: str) -> str:
    return sha256_bytes("|".join(parts).encode("utf-8"))


def snapshot_file(path: Path) -> FileSnapshot:
    resolved = path.expanduser().resolve()
    payload = resolved.read_bytes()
    return FileSnapshot(resolved, payload, sha256_bytes(payload), len(payload))


def read_snapshot(snapshot: FileSnapshot, delimiter: str) -> tuple[list[dict[str, str]], tuple[str, ...]]:
    text = snapshot.payload.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows = list(reader)
    return rows, tuple(reader.fieldnames or ())


def require_fields(fieldnames: Sequence[str], required: set[str], label: str) -> None:
    missing = sorted(required - set(fieldnames))
    if missing:
        raise ActiveLearningFreezeError(f"{label}_missing_fields:{','.join(missing)}")
    forbidden = sorted(FORBIDDEN_INPUT_FIELDS & set(fieldnames))
    if forbidden:
        raise ActiveLearningFreezeError(f"{label}_contains_forbidden_label_fields:{','.join(forbidden)}")


def normalize_sequence(value: str, label: str) -> str:
    sequence = str(value).strip().upper()
    if not sequence or any(amino_acid not in "ACDEFGHIKLMNPQRSTVWY" for amino_acid in sequence):
        raise ActiveLearningFreezeError(f"invalid_sequence:{label}")
    return sequence


def validate_pool(
    rows: list[dict[str, str]],
    fieldnames: Sequence[str],
    *,
    expected_rows: int,
    expected_parent_clusters: int,
) -> list[dict[str, str]]:
    required = {
        "candidate_id",
        "vhh_sequence",
        "sequence_sha256",
        "parent_id",
        "parent_framework_cluster",
        "design_method",
        "design_mode",
        "target_patch_id",
        "cdr1_after",
        "cdr2_after",
        "cdr3_after",
        "cdr3_length",
        "fast_gate_tier",
        "hard_fail",
    }
    require_fields(fieldnames, required, "candidate_pool")
    if len(rows) != expected_rows:
        raise ActiveLearningFreezeError(f"candidate_pool_row_count:{len(rows)}")
    canonical: list[dict[str, str]] = []
    for source in rows:
        candidate_id = source["candidate_id"].strip()
        sequence = normalize_sequence(source["vhh_sequence"], candidate_id)
        sequence_hash = source["sequence_sha256"].strip().lower()
        if hashlib.sha256(sequence.encode("ascii")).hexdigest() != sequence_hash:
            raise ActiveLearningFreezeError(f"candidate_sequence_hash_mismatch:{candidate_id}")
        if source["fast_gate_tier"] != "FORMAL_ELIGIBLE" or source["hard_fail"].lower() != "false":
            raise ActiveLearningFreezeError(f"candidate_not_formal_eligible:{candidate_id}")
        if source["target_patch_id"] not in PATCHES or source["design_mode"] not in MODES:
            raise ActiveLearningFreezeError(f"candidate_unexpected_stratum:{candidate_id}")
        cdrs = [source[name].strip().upper() for name in ("cdr1_after", "cdr2_after", "cdr3_after")]
        if not all(cdrs):
            raise ActiveLearningFreezeError(f"candidate_blank_cdr:{candidate_id}")
        try:
            cdr3_length = int(source["cdr3_length"])
        except ValueError as exc:
            raise ActiveLearningFreezeError(f"candidate_invalid_cdr3_length:{candidate_id}") from exc
        if cdr3_length != len(cdrs[2]):
            raise ActiveLearningFreezeError(f"candidate_cdr3_length_mismatch:{candidate_id}")
        canonical.append(
            {
                "candidate_id": candidate_id,
                "sequence_sha256": sequence_hash,
                "sequence": sequence,
                "parent_id": source["parent_id"].strip(),
                "parent_framework_cluster": source["parent_framework_cluster"].strip(),
                "design_method": source["design_method"].strip(),
                "design_mode": source["design_mode"].strip(),
                "target_patch_id": source["target_patch_id"].strip(),
                "cdr1": cdrs[0],
                "cdr2": cdrs[1],
                "cdr3": cdrs[2],
                "cdr3_length": str(cdr3_length),
            }
        )
    if len({row["candidate_id"] for row in canonical}) != len(canonical):
        raise ActiveLearningFreezeError("candidate_pool_duplicate_candidate_id")
    if len({row["sequence_sha256"] for row in canonical}) != len(canonical):
        raise ActiveLearningFreezeError("candidate_pool_duplicate_sequence")
    parent_clusters = {row["parent_framework_cluster"] for row in canonical}
    if len(parent_clusters) != expected_parent_clusters:
        raise ActiveLearningFreezeError(
            f"candidate_pool_parent_cluster_count:{len(parent_clusters)}"
        )
    return canonical


def validate_reference(
    rows: list[dict[str, str]],
    fieldnames: Sequence[str],
    pool_by_id: Mapping[str, Mapping[str, str]],
    *,
    label: str,
    expected_rows: int,
) -> list[dict[str, str]]:
    required = {
        "candidate_id",
        "sequence_sha256",
        "sequence",
        "parent_id",
        "parent_framework_cluster",
        "design_method",
        "design_mode",
        "target_patch_id",
        "cdr1",
        "cdr2",
        "cdr3",
        "cdr3_length",
        "model_split",
    }
    require_fields(fieldnames, required, label)
    if len(rows) != expected_rows:
        raise ActiveLearningFreezeError(f"{label}_row_count:{len(rows)}")
    canonical: list[dict[str, str]] = []
    for source in rows:
        candidate_id = source["candidate_id"].strip()
        if candidate_id not in pool_by_id:
            raise ActiveLearningFreezeError(f"{label}_candidate_not_in_pool:{candidate_id}")
        row = {
            "candidate_id": candidate_id,
            "sequence_sha256": source["sequence_sha256"].strip().lower(),
            "sequence": normalize_sequence(source["sequence"], candidate_id),
            "parent_id": source["parent_id"].strip(),
            "parent_framework_cluster": source["parent_framework_cluster"].strip(),
            "design_method": source["design_method"].strip(),
            "design_mode": source["design_mode"].strip(),
            "target_patch_id": source["target_patch_id"].strip(),
            "cdr1": source["cdr1"].strip().upper(),
            "cdr2": source["cdr2"].strip().upper(),
            "cdr3": source["cdr3"].strip().upper(),
            "cdr3_length": str(int(source["cdr3_length"])),
            "model_split": source["model_split"].strip(),
        }
        pool_row = pool_by_id[candidate_id]
        for field in (
            "sequence_sha256",
            "sequence",
            "parent_id",
            "parent_framework_cluster",
            "design_method",
            "design_mode",
            "target_patch_id",
            "cdr1",
            "cdr2",
            "cdr3",
            "cdr3_length",
        ):
            if row[field] != pool_row[field]:
                raise ActiveLearningFreezeError(
                    f"{label}_pool_identity_mismatch:{candidate_id}:{field}"
                )
        canonical.append(row)
    if len({row["candidate_id"] for row in canonical}) != len(canonical):
        raise ActiveLearningFreezeError(f"{label}_duplicate_candidate_id")
    return canonical


OVERLAP_FIELDS = (
    "candidate_id",
    "sequence_sha256",
    "parent_id",
    "parent_framework_cluster",
    "cdr1",
    "cdr2",
    "cdr3",
)


def value_sets(rows: Iterable[Mapping[str, str]]) -> dict[str, set[str]]:
    materialized = list(rows)
    return {field: {str(row[field]) for row in materialized} for field in OVERLAP_FIELDS}


def overlap_counts(
    left: Iterable[Mapping[str, str]], right: Iterable[Mapping[str, str]]
) -> dict[str, int]:
    left_sets = value_sets(left)
    right_sets = value_sets(right)
    return {field: len(left_sets[field] & right_sets[field]) for field in OVERLAP_FIELDS}


def filter_reference_disjoint(
    pool_rows: Iterable[dict[str, str]], reference_rows: Iterable[dict[str, str]]
) -> list[dict[str, str]]:
    references = value_sets(reference_rows)
    return [
        row
        for row in pool_rows
        if all(row[field] not in references[field] for field in OVERLAP_FIELDS)
    ]


def choose_parent_roles(
    pool_rows: list[dict[str, str]],
    v4d_rows: list[dict[str, str]],
    v4f_rows: list[dict[str, str]],
    *,
    expected_remaining_parent_clusters: int,
) -> tuple[list[str], list[str], list[dict[str, str]]]:
    pool_parents = {row["parent_framework_cluster"] for row in pool_rows}
    v4d_parents = {row["parent_framework_cluster"] for row in v4d_rows}
    v4f_parents = {row["parent_framework_cluster"] for row in v4f_rows}
    if v4d_parents & v4f_parents:
        raise ActiveLearningFreezeError("v4d_v4f_parent_cluster_overlap")
    remaining = sorted(pool_parents - v4d_parents - v4f_parents)
    if len(remaining) != expected_remaining_parent_clusters:
        raise ActiveLearningFreezeError(
            f"remaining_parent_cluster_count:{len(remaining)}"
        )
    if len(remaining) != ACQUISITION_PARENT_COUNT + RESERVE_PARENT_COUNT:
        raise ActiveLearningFreezeError("remaining_parent_role_count_mismatch")
    ranked = sorted(
        remaining,
        key=lambda parent: (stable_hash(SELECTION_SEED, "parent", parent), parent),
    )
    ranking = [
        {
            "parent_framework_cluster": parent,
            "parent_hash_rank": str(index + 1),
            "selection_hash": stable_hash(SELECTION_SEED, "parent", parent),
        }
        for index, parent in enumerate(ranked)
    ]
    return ranked[:ACQUISITION_PARENT_COUNT], ranked[ACQUISITION_PARENT_COUNT:], ranking


def select_unseen96(
    eligible_rows: list[dict[str, str]], acquisition_parents: Sequence[str]
) -> list[dict[str, str]]:
    by_stratum: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    parent_set = set(acquisition_parents)
    for row in eligible_rows:
        parent = row["parent_framework_cluster"]
        if parent in parent_set:
            by_stratum[(parent, row["target_patch_id"], row["design_mode"])].append(row)
    output: list[dict[str, str]] = []
    for parent in acquisition_parents:
        for patch in PATCHES:
            for mode in MODES:
                choices = sorted(
                    by_stratum.get((parent, patch, mode), []),
                    key=lambda row: (
                        stable_hash(
                            SELECTION_SEED,
                            "candidate",
                            parent,
                            patch,
                            mode,
                            row["candidate_id"],
                            row["sequence_sha256"],
                        ),
                        row["candidate_id"],
                    ),
                )
                if len(choices) < ROWS_PER_STRATUM:
                    raise ActiveLearningFreezeError(
                        f"insufficient_unseen_stratum:{parent}:{patch}:{mode}:{len(choices)}"
                    )
                for rank, source in enumerate(choices[:ROWS_PER_STRATUM], start=1):
                    selection_hash = stable_hash(
                        SELECTION_SEED,
                        "candidate",
                        parent,
                        patch,
                        mode,
                        source["candidate_id"],
                        source["sequence_sha256"],
                    )
                    output.append(
                        {
                            **{field: source[field] for field in MANIFEST_FIELDS[:12]},
                            "model_split": MODEL_SPLIT,
                            "selection_stratum": f"{parent}|{patch}|{mode}",
                            "selection_rank_in_stratum": str(rank),
                            "selection_hash": selection_hash,
                            "full_qc_and_docking_policy": (
                                "run_full_qc_on_all_96;dock_every_full_qc_hard_pass;"
                                "record_attrition;no_replacement"
                            ),
                            "claim_boundary": CLAIM_BOUNDARY,
                        }
                    )
    return output


def build_reserve_rows(
    eligible_rows: list[dict[str, str]],
    reserve_parents: Sequence[str],
    parent_ranking: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    rank_by_parent = {row["parent_framework_cluster"]: row for row in parent_ranking}
    output: list[dict[str, str]] = []
    for parent in reserve_parents:
        rows = [row for row in eligible_rows if row["parent_framework_cluster"] == parent]
        counts = Counter((row["target_patch_id"], row["design_mode"]) for row in rows)
        if set(counts) != {(patch, mode) for patch in PATCHES for mode in MODES}:
            raise ActiveLearningFreezeError(f"reserve_parent_missing_strata:{parent}")
        parent_ids = sorted({row["parent_id"] for row in rows})
        rank = rank_by_parent[parent]
        output.append(
            {
                "parent_framework_cluster": parent,
                "parent_ids": ";".join(parent_ids),
                "selection_role": "UNTOUCHED_V4_G_RESERVE_PARENT",
                "parent_hash_rank": rank["parent_hash_rank"],
                "selection_hash": rank["selection_hash"],
                "eligible_candidate_count": str(len(rows)),
                "eligible_stratum_count": str(len(counts)),
                "minimum_eligible_rows_per_stratum": str(min(counts.values())),
                "untouched_policy": (
                    "no_model_scoring;no_full_qc;no_docking;no_label_opening_until_a_new_"
                    "prospective_protocol_is_hash_frozen"
                ),
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )
    return output


def validate_selected_panel(
    rows: list[dict[str, str]],
    acquisition_parents: Sequence[str],
    reserve_parents: Sequence[str],
    v4d_rows: list[dict[str, str]],
    v4f_rows: list[dict[str, str]],
) -> dict[str, Any]:
    expected_rows = ACQUISITION_PARENT_COUNT * len(PATCHES) * len(MODES) * ROWS_PER_STRATUM
    if len(rows) != expected_rows:
        raise ActiveLearningFreezeError(f"unseen96_row_count:{len(rows)}")
    if len({row["candidate_id"] for row in rows}) != expected_rows:
        raise ActiveLearningFreezeError("unseen96_candidate_ids_not_unique")
    if len({row["sequence_sha256"] for row in rows}) != expected_rows:
        raise ActiveLearningFreezeError("unseen96_sequences_not_unique")
    selected_parents = {row["parent_framework_cluster"] for row in rows}
    if selected_parents != set(acquisition_parents):
        raise ActiveLearningFreezeError("unseen96_parent_set_mismatch")
    if selected_parents & set(reserve_parents):
        raise ActiveLearningFreezeError("unseen96_reserve_parent_overlap")
    overlaps = {
        "v4d": overlap_counts(rows, v4d_rows),
        "v4f": overlap_counts(rows, v4f_rows),
        "v4d_and_v4f": overlap_counts(rows, [*v4d_rows, *v4f_rows]),
    }
    if any(value for group in overlaps.values() for value in group.values()):
        raise ActiveLearningFreezeError(f"unseen96_reference_overlap:{overlaps}")
    parent_counts = Counter(row["parent_framework_cluster"] for row in rows)
    stratum_counts = Counter(row["selection_stratum"] for row in rows)
    patch_counts = Counter(row["target_patch_id"] for row in rows)
    mode_counts = Counter(row["design_mode"] for row in rows)
    if set(parent_counts.values()) != {12} or len(parent_counts) != ACQUISITION_PARENT_COUNT:
        raise ActiveLearningFreezeError("unseen96_parent_balance_failed")
    if set(stratum_counts.values()) != {ROWS_PER_STRATUM} or len(stratum_counts) != 48:
        raise ActiveLearningFreezeError("unseen96_stratum_balance_failed")
    if patch_counts != Counter({"A_CENTER": 32, "B_LOWER": 32, "C_CROSS": 32}):
        raise ActiveLearningFreezeError("unseen96_patch_balance_failed")
    if mode_counts != Counter({"H3": 48, "H1H3": 48}):
        raise ActiveLearningFreezeError("unseen96_mode_balance_failed")
    return {
        "row_count": len(rows),
        "candidate_ids_unique": True,
        "sequences_unique": True,
        "parent_counts": dict(sorted(parent_counts.items())),
        "patch_counts": dict(sorted(patch_counts.items())),
        "mode_counts": dict(sorted(mode_counts.items())),
        "stratum_count": len(stratum_counts),
        "rows_per_stratum": ROWS_PER_STRATUM,
        "reference_overlap_counts": overlaps,
        "reserve_parent_overlap": 0,
        "docking_or_test_label_files_opened": 0,
        "docking_or_test_label_fields_read": 0,
    }


def tsv_bytes(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> bytes:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue().encode("utf-8")


def json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")


@contextmanager
def publication_lock(output_dir: Path):
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir.parent / f".{output_dir.name}.freeze.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ActiveLearningFreezeError(f"publication_lock_exists:{lock_path}") from exc
    try:
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        os.close(descriptor)
        yield
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        lock_path.unlink(missing_ok=True)


def publish_receipt_last(output_dir: Path, artifacts: Mapping[str, bytes]) -> None:
    if set(artifacts) != set(OUTPUT_FILENAMES):
        raise ActiveLearningFreezeError("publication_artifact_set_mismatch")
    receipt_name = OUTPUT_FILENAMES[-1]
    with publication_lock(output_dir):
        staging = Path(
            tempfile.mkdtemp(prefix=f".{output_dir.name}.stage.", dir=output_dir.parent)
        )
        try:
            for name, payload in artifacts.items():
                path = staging / name
                path.write_bytes(payload)
                if path.read_bytes() != payload:
                    raise ActiveLearningFreezeError(f"staged_artifact_mismatch:{name}")
            output_dir.mkdir(parents=True, exist_ok=True)
            unexpected = sorted(
                path.name
                for path in output_dir.iterdir()
                if path.is_file() and path.name not in OUTPUT_FILENAMES
            )
            if unexpected:
                raise ActiveLearningFreezeError(
                    f"unexpected_existing_output_files:{','.join(unexpected)}"
                )
            final_receipt = output_dir / receipt_name
            final_receipt.unlink(missing_ok=True)
            for name in OUTPUT_FILENAMES[:-1]:
                os.replace(staging / name, output_dir / name)
                if (output_dir / name).read_bytes() != artifacts[name]:
                    raise ActiveLearningFreezeError(f"published_artifact_mismatch:{name}")
            os.replace(staging / receipt_name, final_receipt)
            if final_receipt.read_bytes() != artifacts[receipt_name]:
                raise ActiveLearningFreezeError("published_receipt_mismatch")
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def run(
    pool_path: Path,
    v4d_path: Path,
    v4f_path: Path,
    output_dir: Path,
    *,
    enforce_production_hashes: bool = True,
    expected_pool_rows: int = EXPECTED_POOL_ROWS,
    expected_v4d_rows: int = EXPECTED_V4D_ROWS,
    expected_v4f_rows: int = EXPECTED_V4F_ROWS,
    expected_pool_parent_clusters: int = EXPECTED_POOL_PARENT_CLUSTERS,
    expected_remaining_parent_clusters: int = EXPECTED_REMAINING_PARENT_CLUSTERS,
    expected_open_train_parent_clusters: int = EXPECTED_V4D_OPEN_TRAIN_PARENT_CLUSTERS,
) -> dict[str, Any]:
    snapshots = {
        "candidate_pool": snapshot_file(pool_path),
        "v4d_split": snapshot_file(v4d_path),
        "v4f_holdout": snapshot_file(v4f_path),
    }
    expected_hashes = {
        "candidate_pool": EXPECTED_POOL_SHA256,
        "v4d_split": EXPECTED_V4D_SHA256,
        "v4f_holdout": EXPECTED_V4F_SHA256,
    }
    if enforce_production_hashes:
        for name, expected in expected_hashes.items():
            if snapshots[name].sha256 != expected:
                raise ActiveLearningFreezeError(f"{name}_sha256_mismatch")
    pool_raw, pool_fields = read_snapshot(snapshots["candidate_pool"], ",")
    v4d_raw, v4d_fields = read_snapshot(snapshots["v4d_split"], "\t")
    v4f_raw, v4f_fields = read_snapshot(snapshots["v4f_holdout"], "\t")
    pool_rows = validate_pool(
        pool_raw,
        pool_fields,
        expected_rows=expected_pool_rows,
        expected_parent_clusters=expected_pool_parent_clusters,
    )
    pool_by_id = {row["candidate_id"]: row for row in pool_rows}
    v4d_rows = validate_reference(
        v4d_raw,
        v4d_fields,
        pool_by_id,
        label="v4d_split",
        expected_rows=expected_v4d_rows,
    )
    v4f_rows = validate_reference(
        v4f_raw,
        v4f_fields,
        pool_by_id,
        label="v4f_holdout",
        expected_rows=expected_v4f_rows,
    )
    if any(overlap_counts(v4d_rows, v4f_rows).values()):
        raise ActiveLearningFreezeError("v4d_v4f_identity_overlap")
    open_train_parents = sorted(
        {
            row["parent_framework_cluster"]
            for row in v4d_rows
            if row["model_split"] == "OPEN_TRAIN"
        }
    )
    if len(open_train_parents) != expected_open_train_parent_clusters:
        raise ActiveLearningFreezeError(
            f"v4d_open_train_parent_cluster_count:{len(open_train_parents)}"
        )
    acquisition_parents, reserve_parents, parent_ranking = choose_parent_roles(
        pool_rows,
        v4d_rows,
        v4f_rows,
        expected_remaining_parent_clusters=expected_remaining_parent_clusters,
    )
    eligible_rows = filter_reference_disjoint(pool_rows, [*v4d_rows, *v4f_rows])
    selected_rows = select_unseen96(eligible_rows, acquisition_parents)
    reserve_rows = build_reserve_rows(eligible_rows, reserve_parents, parent_ranking)
    checks = validate_selected_panel(
        selected_rows, acquisition_parents, reserve_parents, v4d_rows, v4f_rows
    )

    configuration = {
        "schema_version": SCHEMA_VERSION,
        "selection_seed": SELECTION_SEED,
        "expected_counts": {
            "candidate_pool": expected_pool_rows,
            "v4d": expected_v4d_rows,
            "v4f": expected_v4f_rows,
            "pool_parent_clusters": expected_pool_parent_clusters,
            "remaining_parent_clusters": expected_remaining_parent_clusters,
            "acquisition_parents": ACQUISITION_PARENT_COUNT,
            "reserve_parents": RESERVE_PARENT_COUNT,
            "unseen_acquisition_rows": 96,
        },
        "patches": list(PATCHES),
        "design_modes": list(MODES),
        "rows_per_unseen_stratum": ROWS_PER_STRATUM,
        "production_hash_enforcement": enforce_production_hashes,
        "selection_uses_docking_or_test_labels": False,
    }
    input_metadata = {
        name: {
            "path": str(snapshot.path),
            "sha256": snapshot.sha256,
            "size_bytes": snapshot.size_bytes,
            "row_count": len(
                {"candidate_pool": pool_rows, "v4d_split": v4d_rows, "v4f_holdout": v4f_rows}[name]
            ),
        }
        for name, snapshot in snapshots.items()
    }
    input_closure = sha256_json(
        {
            name: {"sha256": value["sha256"], "size_bytes": value["size_bytes"]}
            for name, value in input_metadata.items()
        }
    )
    manifest_payload = tsv_bytes(selected_rows, MANIFEST_FIELDS)
    reserve_payload = tsv_bytes(reserve_rows, RESERVE_FIELDS)
    implementation = {
        "path": str(Path(__file__).resolve()),
        "sha256": sha256_file(Path(__file__)),
    }
    preregistration = {
        "schema_version": PREREGISTRATION_VERSION,
        "status": (
            "FROZEN_LABEL_FREE_BEFORE_V4D_OPEN_TEACHER_OR_V4F_DOCKING_LABELS"
            if enforce_production_hashes
            else "TEST_ONLY_FROZEN_LABEL_FREE_ACTIVE_LEARNING_PLAN"
        ),
        "claim_boundary": CLAIM_BOUNDARY,
        "implementation": implementation,
        "configuration": configuration,
        "configuration_sha256": sha256_json(configuration),
        "input_snapshot_content_closure_sha256": input_closure,
        "unseen96": {
            "role": "acquisition_only_not_evaluation",
            "parent_clusters": acquisition_parents,
            "rows": 96,
            "manifest_sha256": sha256_bytes(manifest_payload),
            "selection": "8 hash-ranked unseen parents x 3 patches x 2 modes x 2 candidates",
            "full_qc": "run on all 96 and record attrition without replacement",
            "docking": "dock every Full-QC hard-pass candidate",
        },
        "untouched_reserve2": {
            "parent_clusters": reserve_parents,
            "parent_manifest_sha256": sha256_bytes(reserve_payload),
            "policy": (
                "no model scoring, Full-QC, docking, or label opening until a new "
                "prospective protocol and prediction receipt are frozen"
            ),
        },
        "future_seen200": {
            "status": "PREREGISTERED_NOT_SELECTED_BY_THIS_FREEZE",
            "source_parent_clusters": open_train_parents,
            "rows": 200,
            "rows_per_parent": 10,
            "model_open_gate_pass_quota_per_parent": {
                "top": 4,
                "uncertainty": 3,
                "disagreement": 2,
                "control": 1,
            },
            "model_open_gate_fail_quota_per_parent": {
                "label_free_diverse_replacing_top": 4,
                "uncertainty": 3,
                "disagreement": 2,
                "control": 1,
            },
            "failure_branch_boundary": (
                "A failed open model gate forbids top-score exploitation; only the four top "
                "slots are replaced by label-free diversity. All rows remain acquisition-only."
            ),
            "forbidden_sources": (
                "V4-D prospective-test labels, V4-F labels, reserve2 parents, experimental "
                "binding/blocking labels, and candidate-specific threshold tuning"
            ),
        },
        "label_access": {
            "docking_label_files_opened": 0,
            "v4d_prospective_test_labels_opened": 0,
            "v4f_labels_opened": 0,
            "experimental_labels_opened": 0,
        },
    }
    preregistration["preregistration_payload_sha256"] = sha256_json(preregistration)
    preregistration_payload = json_bytes(preregistration)
    output_dir = output_dir.expanduser().resolve()
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "PASS_LABEL_FREE_UNSEEN96_AND_RESERVE2_FROZEN"
            if enforce_production_hashes
            else "TEST_ONLY_PASS_LABEL_FREE_UNSEEN96_AND_RESERVE2_FROZEN"
        ),
        "execution_mode": "production" if enforce_production_hashes else "test_only",
        "claim_boundary": CLAIM_BOUNDARY,
        "implementation": implementation,
        "configuration": configuration,
        "configuration_sha256": sha256_json(configuration),
        "inputs": input_metadata,
        "input_snapshot_content_closure_sha256": input_closure,
        "parent_selection": {
            "all_remaining_hash_ranking": parent_ranking,
            "acquisition_parents": acquisition_parents,
            "reserve_parents": reserve_parents,
        },
        "checks": checks,
        "outputs": {
            "unseen96_manifest": {
                "path": OUTPUT_FILENAMES[0],
                "sha256": sha256_bytes(manifest_payload),
                "row_count": len(selected_rows),
            },
            "reserve2_parents": {
                "path": OUTPUT_FILENAMES[1],
                "sha256": sha256_bytes(reserve_payload),
                "row_count": len(reserve_rows),
            },
            "preregistration": {
                "path": OUTPUT_FILENAMES[2],
                "sha256": sha256_bytes(preregistration_payload),
            },
        },
        "future_seen200_preregistered": True,
        "future_seen200_selected": False,
        "docking_or_test_label_files_opened": 0,
        "docking_or_test_label_fields_read": 0,
    }
    audit["audit_payload_sha256"] = sha256_json(audit)
    audit_payload = json_bytes(audit)
    receipt = {
        "schema_version": RECEIPT_VERSION,
        "status": (
            "PASS_COMPLETE_HASH_CLOSURE_RECEIPT_PUBLISHED_LAST"
            if enforce_production_hashes
            else "TEST_ONLY_PASS_COMPLETE_HASH_CLOSURE_RECEIPT_PUBLISHED_LAST"
        ),
        "execution_mode": audit["execution_mode"],
        "implementation_sha256": implementation["sha256"],
        "configuration_sha256": audit["configuration_sha256"],
        "input_snapshot_content_closure_sha256": input_closure,
        "inputs": {name: value["sha256"] for name, value in input_metadata.items()},
        "outputs": {
            OUTPUT_FILENAMES[0]: sha256_bytes(manifest_payload),
            OUTPUT_FILENAMES[1]: sha256_bytes(reserve_payload),
            OUTPUT_FILENAMES[2]: sha256_bytes(preregistration_payload),
            OUTPUT_FILENAMES[3]: sha256_bytes(audit_payload),
        },
        "audit_payload_sha256": audit["audit_payload_sha256"],
        "preregistration_payload_sha256": preregistration[
            "preregistration_payload_sha256"
        ],
        "receipt_publication_order": "LAST_AFTER_ALL_BOUND_OUTPUTS_VERIFIED",
        "docking_or_test_label_files_opened": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    receipt_payload = json_bytes(receipt)
    artifacts = {
        OUTPUT_FILENAMES[0]: manifest_payload,
        OUTPUT_FILENAMES[1]: reserve_payload,
        OUTPUT_FILENAMES[2]: preregistration_payload,
        OUTPUT_FILENAMES[3]: audit_payload,
        OUTPUT_FILENAMES[4]: receipt_payload,
    }
    publish_receipt_last(output_dir, artifacts)
    for name, expected_payload in artifacts.items():
        if (output_dir / name).read_bytes() != expected_payload:
            raise ActiveLearningFreezeError(f"final_publication_verification_failed:{name}")
    return audit


def main(argv: Sequence[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate-pool",
        type=Path,
        default=root
        / "prepared/pvrig_teacher_formal_v1_candidates/fast_gate/fast_gate_formal_eligible_v1.csv",
    )
    parser.add_argument(
        "--v4d-split",
        type=Path,
        default=root / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv",
    )
    parser.add_argument(
        "--v4f-holdout",
        type=Path,
        default=root / "data_splits/pvrig_v4_f/prospective_holdout96_manifest.tsv",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=root / "data_splits/pvrig_v4_g"
    )
    args = parser.parse_args(argv)
    audit = run(args.candidate_pool, args.v4d_split, args.v4f_holdout, args.output_dir)
    print(
        json.dumps(
            {
                "status": audit["status"],
                "unseen96_rows": audit["checks"]["row_count"],
                "acquisition_parents": audit["parent_selection"]["acquisition_parents"],
                "reserve_parents": audit["parent_selection"]["reserve_parents"],
                "output_dir": str(args.output_dir.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
