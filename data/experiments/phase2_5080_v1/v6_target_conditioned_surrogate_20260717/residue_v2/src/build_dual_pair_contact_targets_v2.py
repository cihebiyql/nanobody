#!/usr/bin/env python3
"""Build canonical sparse dual-source residue-pair teachers for D_FULL_PAIR.

The sparse table contains every non-zero pair.  Omitted cells are exact zeros
over the *observed successful seeds* only; failed technical seeds are never
inserted as zeros.  A separate group audit explicitly records every training
candidate x receptor group, including groups with zero non-zero pairs.
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
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA_VERSION = "pvrig_v6_dual_source_pair_contact_targets_v2"
RECEIPT_SCHEMA = f"{SCHEMA_VERSION}_receipt"
STATUS = "PASS_DUAL_SOURCE_PAIR_CONTACT_TARGETS_V2"
OUTPUT_NAME = "v6_dual_source_pair_contact_targets_v2.tsv.gz"
GROUP_AUDIT_NAME = "v6_dual_source_pair_group_audit_v2.tsv"
RECEIPT_NAME = "RUN_RECEIPT.json"
SHA256SUMS_NAME = "SHA256SUMS"
SOURCES = ("V4D_OPEN_MULTI_SEED", "V4H_STAGE1_SEED917")
V4D, V4H = SOURCES
RECEPTORS = ("8x6b", "9e6y")
PAIR_SEMANTICS = "SPARSE_ABSENCE_IS_EXACT_ZERO"
CLAIM_BOUNDARY = (
    "Sparse residue-pair targets derived from independent dual-receptor computational "
    "Docking contacts; absent pairs are exact zero only over observed successful seeds, "
    "not imputed failed seeds; not binding, affinity, experimental blocking, Docking Gold, "
    "or submission evidence."
)
FORMAL_SOURCE_COUNTS = {V4D: 226, V4H: 1281}
FORMAL_PARENT_COUNTS = {V4D: 20, V4H: 11}
TRAIN_REQUIRED = {
    "candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster", "teacher_source",
}
V4D_REQUIRED = {
    "schema_version", "teacher_state", "candidate_id", "sequence_sha256",
    "parent_framework_cluster", "receptor", "vhh_sequence_index", "vhh_aa",
    "pvrig_uniprot_position", "pvrig_aa", "contact_target_mean",
    "contact_target_variance", "contact_uncertainty_weight", "supporting_seed_count",
    "observed_seed_count", "expected_seed_count", "seed_contact_values",
}
V4H_REQUIRED = {
    "schema_version", "teacher_state", "candidate_id", "sequence_sha256",
    "parent_framework_cluster", "receptor", "seed", "vhh_sequence_index", "vhh_aa",
    "pvrig_uniprot_position", "pvrig_aa", "contact_frequency_pose_weighted",
    "supporting_pose_count", "selected_pose_count",
}
OUTPUT_FIELDS = (
    "schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster",
    "teacher_source", "receptor", "vhh_sequence_index", "vhh_aa",
    "pvrig_node_index", "pvrig_uniprot_position", "pvrig_aa",
    "contact_target", "contact_variance", "contact_uncertainty_weight", "target_mask",
    "supporting_seed_count", "observed_seed_count", "expected_seed_count",
    "pair_table_semantics", "aggregation", "claim_boundary",
)
GROUP_FIELDS = (
    "schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster",
    "teacher_source", "receptor", "sequence_length", "target_node_count",
    "nonzero_pair_rows", "has_nonzero_pair", "observed_seed_count_min",
    "observed_seed_count_max", "observed_seed_count_audit_state", "expected_seed_count", "pair_table_semantics",
    "technical_failed_seed_zero_imputations", "claim_boundary",
)


class PairTargetError(RuntimeError):
    """Fail-closed pair target materialization error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PairTargetError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"input_missing_or_symlink:{path}")
    opener: Any = gzip.open if path.suffix == ".gz" else Path.open
    if path.suffix == ".gz":
        handle = opener(path, "rt", encoding="utf-8-sig", newline="")
    else:
        handle = opener(path, "r", encoding="utf-8-sig", newline="")
    with handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    require(fields and rows, f"empty_input:{path}")
    return fields, rows


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def write_gzip_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    with path.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="", write_through=True) as text:
                writer = csv.DictWriter(text, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow({field: row.get(field, "") for field in fields})
                    count += 1
        raw.flush()
        os.fsync(raw.fileno())
    return count


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
            count += 1
        handle.flush()
        os.fsync(handle.fileno())
    return count


def finite_unit(text: str, label: str) -> float:
    value = float(text)
    require(math.isfinite(value) and 0.0 <= value <= 1.0, f"{label}_invalid:{text}")
    return value


def load_training(
    path: Path,
    *,
    expected_source_counts: Mapping[str, int],
    expected_parent_counts: Mapping[str, int],
) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    fields, rows = read_tsv(path)
    require(TRAIN_REQUIRED <= set(fields), f"training_fields_missing:{sorted(TRAIN_REQUIRED-set(fields))}")
    training: dict[str, dict[str, str]] = {}
    parent_source: dict[str, str] = {}
    source_counts: Counter[str] = Counter()
    for row in rows:
        candidate = row["candidate_id"].strip()
        source = row["teacher_source"].strip()
        require(source in SOURCES, f"training_source_forbidden:{candidate}:{source}")
        require(candidate and candidate not in training, f"training_candidate_duplicate:{candidate}")
        sequence = row["sequence"].strip().upper()
        require(sequence and all(aa in "ACDEFGHIKLMNPQRSTVWY" for aa in sequence), f"training_sequence_invalid:{candidate}")
        require(hashlib.sha256(sequence.encode("ascii")).hexdigest() == row["sequence_sha256"], f"training_sequence_hash:{candidate}")
        parent = row["parent_framework_cluster"].strip()
        require(parent and (parent not in parent_source or parent_source[parent] == source), f"training_parent_cross_source:{parent}")
        parent_source[parent] = source
        source_counts[source] += 1
        training[candidate] = {**row, "sequence": sequence, "teacher_source": source}
    require(dict(source_counts) == dict(expected_source_counts), f"training_source_counts:{dict(source_counts)}")
    parent_counts = Counter(parent_source.values())
    require(dict(parent_counts) == dict(expected_parent_counts), f"training_parent_counts:{dict(parent_counts)}")
    return training, {
        "candidates": len(training),
        "parents": len(parent_source),
        "source_candidates": dict(source_counts),
        "source_parents": dict(parent_counts),
    }


def validate_v4d_receipt(path: Path, pair_path: Path, expected_candidates: int) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), "v4d_receipt_missing_or_symlink")
    payload = json.loads(path.read_text())
    require(payload.get("schema_version") == "pvrig_v6_v4d_open226_multi_seed_contact_teacher_v2_receipt", "v4d_receipt_schema")
    require(payload.get("status") == "COMPLETE_V4D_OPEN226_MULTI_SEED_CONTACT_TEACHER_V2", "v4d_receipt_status")
    counts = payload.get("counts") or {}
    require(int(counts.get("teacher_candidates", -1)) == expected_candidates, "v4d_receipt_candidate_count")
    require(int(counts.get("zero_imputed_failed_seeds", -1)) == 0, "v4d_receipt_failed_seed_zero_imputation")
    require(int(counts.get("pair_rows", -1)) > 0, "v4d_receipt_pair_rows")
    require((payload.get("outputs") or {}).get("pair_sha256") == sha256_file(pair_path), "v4d_receipt_pair_hash")
    sealed = payload.get("sealed_boundary") or {}
    for field in ("sealed_pose_files_opened", "sealed_result_files_opened", "shared_job_results_tsv_opened", "shared_pose_scores_tsv_opened"):
        require(int(sealed.get(field, -1)) == 0, f"v4d_receipt_sealed_boundary:{field}")
    require(int((payload.get("source") or {}).get("source_mutation_operations", -1)) == 0, "v4d_source_mutation")
    return payload


def validate_v4h_receipt(path: Path, pair_path: Path, expected_candidates: int) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), "v4h_receipt_missing_or_symlink")
    payload = json.loads(path.read_text())
    require(payload.get("schema_version") == "pvrig_v6_v4h_stage1_contact_teacher_v1_receipt", "v4h_receipt_schema")
    require(payload.get("status") == "COMPLETE_V4H_STAGE1_CONTACT_TEACHER_EXTRACTION", "v4h_receipt_status")
    require(int(payload.get("valid_candidate_rows", -1)) == expected_candidates, "v4h_receipt_candidate_count")
    require(int(payload.get("technical_incomplete_pose_files_opened", -1)) == 0, "v4h_receipt_incomplete_pose_opened")
    require(int(payload.get("source_mutation_operations", -1)) == 0, "v4h_source_mutation")
    require((payload.get("output_hashes") or {}).get(pair_path.name) == sha256_file(pair_path), "v4h_receipt_pair_hash")
    return payload


def validate_target_receipt(
    path: Path,
    cache_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), "target_receipt_missing_or_symlink")
    payload = json.loads(path.read_text())
    require(payload.get("schema_version") == "pvrig_v6_residue_v2_fixed_target_graphs", "target_receipt_schema")
    require(payload.get("status") == "PASS_FIXED_TARGET_GRAPHS_MATERIALIZED", "target_receipt_status")
    outputs = payload.get("outputs") or {}
    require(outputs.get(cache_path.name) == sha256_file(cache_path), "target_receipt_cache_hash")
    require(outputs.get(manifest_path.name) == sha256_file(manifest_path), "target_receipt_manifest_hash")
    sealed = payload.get("sealed_boundary") or {}
    require(sealed.get("teacher_source_is_model_feature") is False, "target_receipt_source_feature")
    require(int(sealed.get("candidate_docking_pose_files_opened", -1)) == 0, "target_receipt_candidate_pose")
    return payload


def load_target_position_map(
    cache_path: Path,
    manifest_path: Path,
) -> tuple[dict[str, dict[int, tuple[int, str]]], dict[str, int]]:
    fields, manifest_rows = read_tsv(manifest_path)
    require({"receptor", "sequence", "node_count"} <= set(fields), "target_manifest_fields")
    manifest = {row["receptor"].lower(): row for row in manifest_rows}
    require(set(manifest) == set(RECEPTORS), "target_manifest_receptor_closure")
    require(cache_path.is_file() and not cache_path.is_symlink(), "target_cache_missing_or_symlink")
    output: dict[str, dict[int, tuple[int, str]]] = {}
    node_counts: dict[str, int] = {}
    with np.load(cache_path, allow_pickle=False) as archive:
        for receptor in RECEPTORS:
            sequence = manifest[receptor]["sequence"].strip().upper()
            positions = archive[f"{receptor}_uniprot_position"]
            require(len(sequence) == len(positions) == int(manifest[receptor]["node_count"]), f"target_node_count:{receptor}")
            require(bool(np.all(positions > 0)) and len(set(positions.tolist())) == len(positions), f"target_position_mapping:{receptor}")
            output[receptor] = {
                int(position): (index + 1, sequence[index])
                for index, position in enumerate(positions.tolist())
            }
            node_counts[receptor] = len(sequence)
    return output, node_counts


def validate_pair_identity(
    row: Mapping[str, str],
    training: Mapping[str, Mapping[str, str]],
    source: str,
    target_map: Mapping[str, Mapping[int, tuple[int, str]]],
) -> tuple[str, str, int, str, int, int, str]:
    candidate = row["candidate_id"].strip()
    require(candidate in training, f"pair_candidate_not_training:{source}:{candidate}")
    truth = training[candidate]
    require(truth["teacher_source"] == source, f"pair_candidate_wrong_source:{candidate}")
    require(row["sequence_sha256"] == truth["sequence_sha256"], f"pair_sequence_hash:{candidate}")
    require(row["parent_framework_cluster"] == truth["parent_framework_cluster"], f"pair_parent:{candidate}")
    receptor = row["receptor"].strip().lower()
    require(receptor in RECEPTORS, f"pair_receptor:{candidate}:{receptor}")
    vhh_index = int(row["vhh_sequence_index"])
    sequence = truth["sequence"]
    require(1 <= vhh_index <= len(sequence), f"pair_vhh_position:{candidate}:{vhh_index}")
    vhh_aa = row["vhh_aa"].strip().upper()
    require(vhh_aa == sequence[vhh_index - 1], f"pair_vhh_aa:{candidate}:{vhh_index}")
    pvrig_position = int(row["pvrig_uniprot_position"])
    require(pvrig_position in target_map[receptor], f"pair_pvrig_position:{candidate}:{receptor}:{pvrig_position}")
    node_index, pvrig_aa = target_map[receptor][pvrig_position]
    require(row["pvrig_aa"].strip().upper() == pvrig_aa, f"pair_pvrig_aa:{candidate}:{receptor}:{pvrig_position}")
    return candidate, receptor, vhh_index, vhh_aa, node_index, pvrig_position, pvrig_aa


def parse_seed_values(text: str, observed: int) -> list[tuple[int, float]]:
    values: list[tuple[int, float]] = []
    for item in text.split(";"):
        seed_text, separator, value_text = item.partition(":")
        require(bool(separator), f"v4d_seed_value_format:{item}")
        seed, value = int(seed_text), finite_unit(value_text, "v4d_seed_contact")
        require(seed in {917, 1931, 3253}, f"v4d_seed_unexpected:{seed}")
        values.append((seed, value))
    require(len(values) == observed and len({seed for seed, _ in values}) == observed, "v4d_seed_value_count")
    return values


def canonical_rows(
    *,
    training: Mapping[str, Mapping[str, str]],
    v4d_rows: Sequence[Mapping[str, str]],
    v4h_rows: Sequence[Mapping[str, str]],
    target_map: Mapping[str, Mapping[int, tuple[int, str]]],
    group_counts: Counter[tuple[str, str]],
    group_seed_ranges: dict[tuple[str, str], list[int]],
) -> Iterable[dict[str, Any]]:
    seen: set[tuple[str, str, int, int]] = set()
    previous_by_source: dict[str, tuple[str, str, int, int] | None] = {V4D: None, V4H: None}
    # The upstream V4D state is candidate-level: when one receptor is missing a
    # technical repeat, rows for the candidate's other (complete) receptor are
    # also marked PARTIAL.  Bind that state to the complete candidate record,
    # while retaining each pair row's exact observed seed count.
    v4d_candidate_is_partial: dict[str, bool] = {}
    for row in v4d_rows:
        candidate = row["candidate_id"]
        observed, expected = int(row["observed_seed_count"]), int(row["expected_seed_count"])
        require(expected == 3 and 2 <= observed <= expected, f"v4d_seed_counts:{candidate}:{row['receptor']}")
        v4d_candidate_is_partial[candidate] = v4d_candidate_is_partial.get(candidate, False) or observed < expected
    for source, rows in ((V4D, v4d_rows), (V4H, v4h_rows)):
        for row in rows:
            candidate, receptor, vhh_index, vhh_aa, node_index, position, pvrig_aa = validate_pair_identity(
                row, training, source, target_map,
            )
            key = (candidate, receptor, vhh_index, position)
            require(previous_by_source[source] is None or key > previous_by_source[source], f"pair_input_order_or_duplicate:{source}:{key}")
            previous_by_source[source] = key
            require(key not in seen, f"pair_duplicate_cross_source:{key}")
            seen.add(key)
            if source == V4D:
                require(row["schema_version"] == "pvrig_v6_v4d_open226_multi_seed_contact_teacher_v2", "v4d_row_schema")
                target = finite_unit(row["contact_target_mean"], "v4d_target")
                variance = float(row["contact_target_variance"])
                uncertainty = finite_unit(row["contact_uncertainty_weight"], "v4d_uncertainty")
                observed, expected = int(row["observed_seed_count"]), int(row["expected_seed_count"])
                require(expected == 3 and 2 <= observed <= expected, f"v4d_seed_counts:{candidate}:{receptor}")
                expected_state = (
                    "VALID_DUAL_MULTI_SEED_PARTIAL_TECHNICAL_REPEAT"
                    if v4d_candidate_is_partial[candidate]
                    else "VALID_DUAL_MULTI_SEED_CONTACT"
                )
                require(row["teacher_state"] == expected_state, f"v4d_teacher_state:{candidate}:{receptor}")
                seed_values = parse_seed_values(row["seed_contact_values"], observed)
                numeric = np.asarray([value for _, value in seed_values], dtype=np.float64)
                require(math.isfinite(variance) and variance >= 0.0, f"v4d_variance:{candidate}")
                require(abs(float(numeric.mean()) - target) <= 1e-9, f"v4d_seed_mean:{key}")
                require(abs(float(numeric.var(ddof=0)) - variance) <= 1e-9, f"v4d_seed_variance:{key}")
                require(abs(uncertainty - 1.0 / (1.0 + 4.0 * variance)) <= 1e-9, f"v4d_uncertainty_formula:{key}")
                supporting = int(row["supporting_seed_count"])
                require(supporting == int(np.sum(numeric > 0.0)), f"v4d_supporting_seed_count:{key}")
                aggregation = "multi_seed_mean_over_observed_successful_seeds"
            else:
                require(row["schema_version"] == "pvrig_v6_v4h_stage1_contact_teacher_v1", "v4h_row_schema")
                require(row["teacher_state"] == "VALID_DUAL_1_SEED_CONTACT", "v4h_teacher_state")
                require(int(row["seed"]) == 917, "v4h_seed_not_917")
                # The frozen V4H teacher retains valid receptor jobs with 4--8
                # selected poses.  The provided contact frequency already uses
                # that exact per-row denominator; do not invent missing poses.
                selected_pose_count = int(row["selected_pose_count"])
                require(4 <= selected_pose_count <= 8, "v4h_selected_pose_count")
                target = finite_unit(row["contact_frequency_pose_weighted"], "v4h_target")
                variance, uncertainty, observed, expected = 0.0, 1.0, 1, 1
                supporting = int(int(row["supporting_pose_count"]) > 0)
                require(supporting == 1 and target > 0.0, f"v4h_nonzero_sparse_row:{key}")
                aggregation = f"single_seed_pose_weighted_contact_frequency_over_{selected_pose_count}_selected_poses"
            require(target > 0.0, f"sparse_row_must_be_nonzero:{key}")
            group_counts[(candidate, receptor)] += 1
            group_seed_ranges.setdefault((candidate, receptor), []).append(observed)
            yield {
                "schema_version": SCHEMA_VERSION,
                "candidate_id": candidate,
                "sequence_sha256": training[candidate]["sequence_sha256"],
                "parent_framework_cluster": training[candidate]["parent_framework_cluster"],
                "teacher_source": source,
                "receptor": receptor,
                "vhh_sequence_index": vhh_index,
                "vhh_aa": vhh_aa,
                "pvrig_node_index": node_index,
                "pvrig_uniprot_position": position,
                "pvrig_aa": pvrig_aa,
                "contact_target": format(target, ".12g"),
                "contact_variance": format(variance, ".12g"),
                "contact_uncertainty_weight": format(uncertainty, ".12g"),
                "target_mask": 1,
                "supporting_seed_count": supporting,
                "observed_seed_count": observed,
                "expected_seed_count": expected,
                "pair_table_semantics": PAIR_SEMANTICS,
                "aggregation": aggregation,
                "claim_boundary": CLAIM_BOUNDARY,
            }


def group_audit_rows(
    training: Mapping[str, Mapping[str, str]],
    node_counts: Mapping[str, int],
    group_counts: Mapping[tuple[str, str], int],
    group_seed_ranges: Mapping[tuple[str, str], Sequence[int]],
) -> Iterable[dict[str, Any]]:
    for candidate in sorted(training):
        truth = training[candidate]
        expected = 3 if truth["teacher_source"] == V4D else 1
        for receptor in RECEPTORS:
            seeds = list(group_seed_ranges.get((candidate, receptor), []))
            # A zero-nonzero-pair group is still explicit, but this sparse pair
            # table cannot recover its receptor-specific observed seed count.
            # Keep it unavailable rather than inventing or zero-imputing seeds.
            observed_min: int | str = min(seeds) if seeds else ""
            observed_max: int | str = max(seeds) if seeds else ""
            yield {
                "schema_version": f"{SCHEMA_VERSION}_group_audit",
                "candidate_id": candidate,
                "sequence_sha256": truth["sequence_sha256"],
                "parent_framework_cluster": truth["parent_framework_cluster"],
                "teacher_source": truth["teacher_source"],
                "receptor": receptor,
                "sequence_length": len(truth["sequence"]),
                "target_node_count": node_counts[receptor],
                "nonzero_pair_rows": int(group_counts.get((candidate, receptor), 0)),
                "has_nonzero_pair": int(group_counts.get((candidate, receptor), 0) > 0),
                "observed_seed_count_min": observed_min,
                "observed_seed_count_max": observed_max,
                "observed_seed_count_audit_state": "OBSERVED_FROM_NONZERO_PAIR_ROWS" if seeds else "UNAVAILABLE_ZERO_NONZERO_PAIR_GROUP_NO_SEED_IMPUTATION",
                "expected_seed_count": expected,
                "pair_table_semantics": PAIR_SEMANTICS,
                "technical_failed_seed_zero_imputations": 0,
                "claim_boundary": CLAIM_BOUNDARY,
            }


def build_targets(
    *,
    training_tsv: Path,
    v4d_pair_tsv_gz: Path,
    v4d_receipt: Path,
    v4h_pair_tsv_gz: Path,
    v4h_receipt: Path,
    target_cache_npz: Path,
    target_manifest_tsv: Path,
    target_receipt: Path,
    output_dir: Path,
    expected_source_counts: Mapping[str, int] = FORMAL_SOURCE_COUNTS,
    expected_parent_counts: Mapping[str, int] = FORMAL_PARENT_COUNTS,
) -> dict[str, Any]:
    require(set(expected_source_counts) == set(SOURCES) and set(expected_parent_counts) == set(SOURCES), "expected_source_keys")
    require(not output_dir.exists() and not output_dir.is_symlink(), "output_dir_must_not_exist")
    training, training_audit = load_training(
        training_tsv,
        expected_source_counts=expected_source_counts,
        expected_parent_counts=expected_parent_counts,
    )
    v4d_receipt_payload = validate_v4d_receipt(v4d_receipt, v4d_pair_tsv_gz, int(expected_source_counts[V4D]))
    v4h_receipt_payload = validate_v4h_receipt(v4h_receipt, v4h_pair_tsv_gz, int(expected_source_counts[V4H]))
    target_receipt_payload = validate_target_receipt(target_receipt, target_cache_npz, target_manifest_tsv)
    target_map, node_counts = load_target_position_map(target_cache_npz, target_manifest_tsv)
    v4d_fields, v4d_rows = read_tsv(v4d_pair_tsv_gz)
    v4h_fields, v4h_rows = read_tsv(v4h_pair_tsv_gz)
    require(V4D_REQUIRED <= set(v4d_fields), f"v4d_fields_missing:{sorted(V4D_REQUIRED-set(v4d_fields))}")
    require(V4H_REQUIRED <= set(v4h_fields), f"v4h_fields_missing:{sorted(V4H_REQUIRED-set(v4h_fields))}")
    require(len(v4d_rows) == int(v4d_receipt_payload["counts"]["pair_rows"]), "v4d_pair_row_count")
    require(len(v4h_rows) == int(v4h_receipt_payload["pair_rows"]), "v4h_pair_row_count")

    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        group_counts: Counter[tuple[str, str]] = Counter()
        group_seed_ranges: dict[tuple[str, str], list[int]] = {}
        output_path = staging / OUTPUT_NAME
        output_rows = write_gzip_tsv(
            output_path,
            OUTPUT_FIELDS,
            canonical_rows(
                training=training,
                v4d_rows=v4d_rows,
                v4h_rows=v4h_rows,
                target_map=target_map,
                group_counts=group_counts,
                group_seed_ranges=group_seed_ranges,
            ),
        )
        group_path = staging / GROUP_AUDIT_NAME
        group_rows = write_tsv(
            group_path,
            GROUP_FIELDS,
            group_audit_rows(training, node_counts, group_counts, group_seed_ranges),
        )
        require(group_rows == len(training) * len(RECEPTORS), "group_audit_row_count")
        source_pair_rows = {
            V4D: sum(group_counts[group] for group in group_counts if training[group[0]]["teacher_source"] == V4D),
            V4H: sum(group_counts[group] for group in group_counts if training[group[0]]["teacher_source"] == V4H),
        }
        require(source_pair_rows == {V4D: len(v4d_rows), V4H: len(v4h_rows)}, "source_pair_row_closure")
        input_paths = {
            "training_tsv": training_tsv,
            "v4d_pair_tsv_gz": v4d_pair_tsv_gz,
            "v4d_receipt": v4d_receipt,
            "v4h_pair_tsv_gz": v4h_pair_tsv_gz,
            "v4h_receipt": v4h_receipt,
            "target_cache_npz": target_cache_npz,
            "target_manifest_tsv": target_manifest_tsv,
            "target_receipt": target_receipt,
        }
        receipt = {
            "schema_version": RECEIPT_SCHEMA,
            "status": STATUS,
            "claim_boundary": CLAIM_BOUNDARY,
            "pair_table_semantics": PAIR_SEMANTICS,
            "teacher_source_is_model_feature": False,
            "implementation": {
                "path": str(Path(__file__).resolve()),
                "sha256": sha256_file(Path(__file__).resolve()),
            },
            "inputs": {
                name: {"path": str(path.resolve()), "sha256": sha256_file(path)}
                for name, path in input_paths.items()
            },
            "counts": {
                **training_audit,
                "pair_rows": output_rows,
                "source_pair_rows": source_pair_rows,
                "candidate_receptor_groups": group_rows,
                "source_candidate_receptor_groups": {
                    source: int(expected_source_counts[source]) * 2 for source in SOURCES
                },
                "zero_nonzero_pair_groups": group_rows - len(group_counts),
                "technical_failed_seed_zero_imputations": 0,
                "unresolved_target_pair_rows_dropped": 0,
                "v4d_partial_seed_candidates": int(v4d_receipt_payload["counts"]["partial_seed_candidates"]),
            },
            "source_semantics": {
                V4D: "multi-seed mean/variance over observed successful seeds; missing technical seed never zero-imputed",
                V4H: "frozen seed917 pose-weighted pair contact frequency; sparse absence exact zero",
            },
            "sealed_boundary": {
                "allowed_training_sources": list(SOURCES),
                "v4d_sealed_pose_files_opened": int(v4d_receipt_payload["sealed_boundary"]["sealed_pose_files_opened"]),
                "v4d_sealed_result_files_opened": int(v4d_receipt_payload["sealed_boundary"]["sealed_result_files_opened"]),
                "v4h_technical_incomplete_pose_files_opened": int(v4h_receipt_payload["technical_incomplete_pose_files_opened"]),
                "candidate_docking_pose_files_opened_by_this_builder": 0,
                "sealed_split_rows_emitted": 0,
            },
            "target_graph_status": target_receipt_payload["status"],
            "target_mapping_audit": {
                "mapping_key": "receptor_specific_uniprot_position_to_one_based_graph_node_index",
                "target_node_counts": node_counts,
                "unresolved_target_position_policy": "FAIL_CLOSED_NO_DROP",
                "unresolved_target_pair_rows_dropped": 0,
            },
            "outputs": {
                OUTPUT_NAME: sha256_file(output_path),
                GROUP_AUDIT_NAME: sha256_file(group_path),
            },
        }
        atomic_json(staging / RECEIPT_NAME, receipt)
        sums = (OUTPUT_NAME, GROUP_AUDIT_NAME, RECEIPT_NAME)
        (staging / SHA256SUMS_NAME).write_text(
            "".join(f"{sha256_file(staging / name)}  {name}\n" for name in sums),
            encoding="utf-8",
        )
        os.replace(staging, output_dir)
        return receipt
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def parse_counts(values: Sequence[str] | None, defaults: Mapping[str, int]) -> dict[str, int]:
    if not values:
        return dict(defaults)
    parsed: dict[str, int] = {}
    for item in values:
        source, separator, count = item.partition("=")
        require(bool(separator) and source in SOURCES and source not in parsed, f"expected_count_format:{item}")
        parsed[source] = int(count)
    require(set(parsed) == set(SOURCES) and all(value > 0 for value in parsed.values()), "expected_count_closure")
    return parsed


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--training-tsv", type=Path, required=True)
    value.add_argument("--v4d-pair-tsv-gz", type=Path, required=True)
    value.add_argument("--v4d-receipt", type=Path, required=True)
    value.add_argument("--v4h-pair-tsv-gz", type=Path, required=True)
    value.add_argument("--v4h-receipt", type=Path, required=True)
    value.add_argument("--target-cache-npz", type=Path, required=True)
    value.add_argument("--target-manifest-tsv", type=Path, required=True)
    value.add_argument("--target-receipt", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--expected-source-count", action="append")
    value.add_argument("--expected-parent-count", action="append")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    receipt = build_targets(
        training_tsv=args.training_tsv,
        v4d_pair_tsv_gz=args.v4d_pair_tsv_gz,
        v4d_receipt=args.v4d_receipt,
        v4h_pair_tsv_gz=args.v4h_pair_tsv_gz,
        v4h_receipt=args.v4h_receipt,
        target_cache_npz=args.target_cache_npz,
        target_manifest_tsv=args.target_manifest_tsv,
        target_receipt=args.target_receipt,
        output_dir=args.output_dir,
        expected_source_counts=parse_counts(args.expected_source_count, FORMAL_SOURCE_COUNTS),
        expected_parent_counts=parse_counts(args.expected_parent_count, FORMAL_PARENT_COUNTS),
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
