#!/usr/bin/env python3
"""Materialize the hash-closed canonical10644 open multimodal training table."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import stat
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import torch


SCHEMA_VERSION = "pvrig_v2_11_canonical10644_multimodal_materialization_v1"
READY_STATUS = "PASS_CANONICAL10644_OPEN_MULTIMODAL_MATERIALIZED"
M2_SCHEMA = "pvrig_v2_11_canonical10644_m2_126d_features_v1"
M2_STATUS = "PASS_CANONICAL10644_M2_126D_FEATURES_MATERIALIZED"
C2_SCHEMA = "pvrig_v2_11_canonical10644_coarse_pose_36d_closure_v1"
C2_STATUS = "PASS_CANONICAL10644_COARSE_POSE_36D_SHARD_CLOSURE"
C2_FEATURE_SCHEMA = "pvrig_v2_5_label_free_coarse_pose_36d_v1"
EMBEDDING_SCHEMA = "pvrig_v6_esm_embedding_cache_v1"
CLAIM_BOUNDARY = (
    "Open-development approximation of independent 8X6B/9E6Y computational "
    "Docking geometry only; not binding, affinity, experimental blocking, "
    "Docking Gold, frozen-test, sealed truth, or submission evidence."
)
FORBIDDEN_PATH_TOKENS = ("test32", "sealed_truth", "frozen_test", "frozen-test", "v4_f")
TEACHER_FIELDS = (
    "candidate_id", "sequence_sha256", "sequence", "parent_framework_cluster",
    "cdr1", "cdr2", "cdr3", "sample_weight", "R_8X6B", "R_9E6Y",
    "R_dual_min", "teacher_source", "teacher_reliability",
)
M2_METADATA = {
    "schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster",
    "model_split", "asset_lane", "monomer_sha256", "claim_boundary",
}
C2_METADATA = ("candidate_id", "monomer_sha256", "feature_schema")
C2_RECEPTOR_SUFFIXES = (
    "pose_count", "acceptable_count", "acceptable_fraction", "best_composite",
    "top20_composite_mean", "top20_composite_std", "top20_composite_iqr",
    "top20_score_entropy", "best_shape", "best_hotspot", "best_charge",
    "best_clash_fraction", "best_cdr_contact_fraction", "best_cdr3_orientation",
)
C2_DUAL_FIELDS = (
    "dual__common_acceptable_count", "dual__common_acceptable_fraction",
    "dual__acceptable_jaccard", "dual__best_min_composite",
    "dual__top20_min_composite_mean", "dual__top20_min_composite_std",
    "dual__best_receptor_gap", "dual__pose_score_correlation",
)
C2_FEATURE_FIELDS = tuple(
    f"{target}__{suffix}"
    for target in ("8x6b", "9e6y")
    for suffix in C2_RECEPTOR_SUFFIXES
) + C2_DUAL_FIELDS
C2_EXCLUSIONS = {
    "8x6b__pose_count", "9e6y__pose_count",
    "8x6b__top20_score_entropy", "9e6y__top20_score_entropy",
}


class MaterializationError(RuntimeError):
    """Fail-closed canonical10644 materialization error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MaterializationError(message)


def reject_path(path: Path, role: str) -> None:
    normalized = str(path.resolve()).lower().replace("-", "_")
    for token in FORBIDDEN_PATH_TOKENS:
        require(token.replace("-", "_") not in normalized, f"forbidden_{role}_path:{token}")


def require_regular(path: Path, role: str) -> None:
    reject_path(path, role)
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise MaterializationError(f"missing_file:{role}:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"{role}_not_regular:{path}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_hash(path: Path, expected: str, role: str) -> str:
    require(len(expected) == 64, f"{role}_expected_sha256_invalid")
    observed = sha256_file(path)
    require(observed == expected, f"{role}_sha256_mismatch:{observed}")
    return observed


def stable_parent_hash(parents: Iterable[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(set(parents))) + "\n").encode("utf-8")).hexdigest()


def load_tsv(
    path: Path,
    role: str,
    required_fields: Iterable[str] = (),
    exact_fields: Iterable[str] | None = None,
) -> tuple[list[str], list[dict[str, str]]]:
    require_regular(path, role)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        require(fields and len(fields) == len(set(fields)), f"{role}_header_invalid")
        if exact_fields is not None:
            require(fields == list(exact_fields), f"{role}_header_mismatch")
        missing = sorted(set(required_fields) - set(fields))
        require(not missing, f"{role}_fields_missing:{','.join(missing)}")
        rows = [dict(row) for row in reader]
    require(rows, f"{role}_empty")
    return fields, rows


def unique_by(rows: list[dict[str, str]], key: str, role: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row.get(key, "").strip()
        require(value and value not in result, f"{role}_duplicate_or_blank:{value}")
        result[value] = row
    return result


def finite(raw: str, label: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise MaterializationError(f"invalid_numeric:{label}:{raw!r}") from exc
    require(math.isfinite(value), f"nonfinite:{label}")
    return value


def load_json(path: Path, role: str) -> dict[str, Any]:
    require_regular(path, role)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MaterializationError(f"{role}_invalid_json") from exc
    require(isinstance(value, dict), f"{role}_not_object")
    return value


def validate_parent_list(split: dict[str, Any], key: str) -> set[str]:
    raw = split.get(key)
    require(isinstance(raw, list) and raw, f"{key}_invalid")
    require(all(isinstance(value, str) and value.strip() for value in raw), f"{key}_blank")
    require(len(raw) == len(set(raw)), f"{key}_duplicate")
    return set(raw)


def receipt_output_matches(recorded: Any, expected: Path, receipt_path: Path) -> bool:
    if not isinstance(recorded, str) or not recorded:
        return False
    candidate = Path(recorded)
    if not candidate.is_absolute():
        candidate = receipt_path.parent / candidate
    return candidate.resolve() == expected.resolve()


def validate_m2_receipt(
    path: Path,
    expected_sha256: str,
    m2_path: Path,
    m2_sha256: str,
    feature_names: list[str],
    expected_rows: int,
    expected_splits: dict[str, int],
) -> dict[str, Any]:
    receipt = load_json(path, "m2_receipt")
    validate_hash(path, expected_sha256, "m2_receipt")
    require(receipt.get("schema_version") == M2_SCHEMA, "m2_receipt_schema")
    require(receipt.get("status") == M2_STATUS, "m2_receipt_status")
    counts = receipt.get("counts", {})
    require(counts.get("rows") == expected_rows, "m2_receipt_rows")
    require(counts.get("features") == len(feature_names), "m2_receipt_features")
    require(counts.get("splits") == expected_splits, "m2_receipt_splits")
    require(receipt.get("feature_names") == feature_names, "m2_receipt_feature_names")
    output = receipt.get("output", {})
    require(receipt_output_matches(output.get("path"), m2_path, path), "m2_receipt_output_path")
    require(output.get("sha256") == m2_sha256, "m2_receipt_output_sha256")
    invariants = receipt.get("invariants", {})
    require(invariants.get("legacy_m2_126d_schema") is True, "m2_receipt_schema_invariant")
    require(invariants.get("monomer_sha256_recomputed") is True, "m2_receipt_monomer_invariant")
    require(invariants.get("all_numeric_values_finite") is True, "m2_receipt_finite_invariant")
    require(invariants.get("geometry_label_values_read") == 0, "m2_geometry_label_access")
    require(invariants.get("candidate_docking_pose_files_opened") == 0, "m2_docking_pose_access")
    return {"sha256": expected_sha256, "output_sha256": m2_sha256}


def validate_c2_receipt(
    path: Path,
    expected_sha256: str,
    c2_path: Path,
    c2_sha256: str,
    expected_rows: int,
    expected_splits: dict[str, int],
) -> dict[str, Any]:
    receipt = load_json(path, "coarse_pose_receipt")
    validate_hash(path, expected_sha256, "coarse_pose_receipt")
    require(receipt.get("schema_version") == C2_SCHEMA, "coarse_receipt_schema")
    require(receipt.get("status") == C2_STATUS, "coarse_receipt_status")
    counts = receipt.get("counts", {})
    require(counts.get("candidates") == expected_rows, "coarse_receipt_rows")
    require(counts.get("features") == len(C2_FEATURE_FIELDS), "coarse_receipt_features")
    require(counts.get("splits") == expected_splits, "coarse_receipt_splits")
    output = receipt.get("output", {})
    require(receipt_output_matches(output.get("path"), c2_path, path), "coarse_receipt_output_path")
    require(output.get("sha256") == c2_sha256, "coarse_receipt_output_sha256")
    invariants = receipt.get("invariants", {})
    for key in (
        "candidate_set_exact", "frozen_structure_manifest_order_preserved",
        "all_features_finite", "monomer_sha256_join_exact",
        "all_shard_and_target_hashes_verified",
    ):
        require(invariants.get(key) is True, f"coarse_receipt_invariant:{key}")
    require(invariants.get("candidate_docking_pose_files_opened") == 0, "coarse_docking_pose_access")
    require(invariants.get("teacher_label_files_opened") == 0, "coarse_teacher_label_access")
    return {"sha256": expected_sha256, "output_sha256": c2_sha256}


def validate_cache(
    cache_dir: Path,
    expected_receipt_sha256: str,
    expected_sha_by_id: dict[str, str],
) -> dict[str, Any]:
    reject_path(cache_dir, "embedding_cache")
    receipt_path = cache_dir / "embedding_cache_receipt.json"
    receipt = load_json(receipt_path, "embedding_cache_receipt")
    receipt_sha256 = validate_hash(
        receipt_path, expected_receipt_sha256, "embedding_cache_receipt"
    )
    require(receipt.get("schema_version") == EMBEDDING_SCHEMA, "embedding_schema")
    shard_records = receipt.get("shards")
    require(isinstance(shard_records, list) and shard_records, "embedding_shards_invalid")
    seen: dict[str, str] = {}
    width: int | None = None
    shard_audit: list[dict[str, Any]] = []
    for item in shard_records:
        require(isinstance(item, dict), "embedding_shard_record_invalid")
        shard = Path(str(item.get("path", "")))
        if not shard.is_absolute():
            shard = cache_dir / shard
        require(shard.parent.resolve() == (cache_dir / "shards").resolve(), "embedding_shard_outside_cache")
        require_regular(shard, "embedding_shard")
        shard_sha256 = sha256_file(shard)
        require(shard_sha256 == item.get("sha256"), f"embedding_shard_hash:{shard.name}")
        try:
            payload = torch.load(shard, map_location="cpu", weights_only=False)
            identifiers = payload["metadata"]["candidate_ids"]
            sequence_hashes = payload["metadata"]["sequence_sha256"]
            values = payload["embeddings"].float().numpy()
        except (KeyError, TypeError, RuntimeError, ValueError) as exc:
            raise MaterializationError(f"embedding_shard_payload:{shard.name}") from exc
        require(values.ndim == 2, f"embedding_shard_rank:{shard.name}")
        require(values.shape[0] == len(identifiers) == len(sequence_hashes), f"embedding_shard_shape:{shard.name}")
        if width is None:
            width = int(values.shape[1])
            require(width > 0, "embedding_width_zero")
        require(values.shape[1] == width and np.isfinite(values).all(), "embedding_width_or_finite")
        for candidate, sequence_sha256 in zip(identifiers, sequence_hashes):
            candidate = str(candidate)
            sequence_sha256 = str(sequence_sha256)
            require(candidate and candidate not in seen, f"duplicate_embedding:{candidate}")
            seen[candidate] = sequence_sha256
        shard_audit.append({"path": shard.name, "sha256": shard_sha256, "rows": len(identifiers)})
    require(receipt.get("rows") == len(seen), "embedding_receipt_rows")
    require(set(expected_sha_by_id) <= set(seen), "embedding_candidate_missing")
    for candidate, sequence_sha256 in expected_sha_by_id.items():
        require(seen[candidate] == sequence_sha256, f"embedding_sequence_mismatch:{candidate}")
    return {
        "receipt_sha256": receipt_sha256,
        "cache_rows": len(seen),
        "embedding_width": width,
        "matched_rows": len(expected_sha_by_id),
        "all_shard_hashes_verified": True,
        "shards": shard_audit,
    }


def atomic_write(path: Path, payload: bytes) -> None:
    require(not path.exists() and not path.is_symlink(), f"output_exists:{path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def tsv_bytes(rows: list[dict[str, Any]], fields: list[str]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def materialize(args: argparse.Namespace) -> dict[str, Any]:
    output_dir: Path = args.output_dir
    reject_path(output_dir, "output")
    require(not output_dir.exists() and not output_dir.is_symlink(), "output_exists")
    require(args.expected_rows == args.expected_train_rows + args.expected_development_rows,
            "expected_split_rows_do_not_sum")
    require(args.expected_structure_features == 126, "m2_feature_contract_must_be_126")
    require(args.expected_coarse_features == 36, "coarse_feature_contract_must_be_36")
    require(args.expected_coarse_model_features == 32, "coarse_model_feature_contract_must_be_32")

    input_paths = {
        "teacher": args.teacher,
        "split_manifest": args.split_manifest,
        "m2_features": args.m2_features,
        "m2_receipt": args.m2_receipt,
        "coarse_pose": args.coarse_pose,
        "coarse_pose_receipt": args.coarse_pose_receipt,
    }
    expected_hashes = {
        "teacher": args.expected_teacher_sha256,
        "split_manifest": args.expected_split_sha256,
        "m2_features": args.expected_m2_features_sha256,
        "m2_receipt": args.expected_m2_receipt_sha256,
        "coarse_pose": args.expected_coarse_pose_sha256,
        "coarse_pose_receipt": args.expected_coarse_pose_receipt_sha256,
    }
    hashes: dict[str, str] = {}
    for role, path in input_paths.items():
        require_regular(path, role)
        hashes[role] = validate_hash(path, expected_hashes[role], role)

    teacher_fields, teacher_rows = load_tsv(
        args.teacher, "teacher", exact_fields=TEACHER_FIELDS
    )
    require(teacher_fields == list(TEACHER_FIELDS), "teacher_schema_invalid")
    require(len(teacher_rows) == args.expected_rows, f"teacher_rows:{len(teacher_rows)}")
    teacher = unique_by(teacher_rows, "candidate_id", "teacher")
    sequence_hashes: set[str] = set()
    for row in teacher_rows:
        candidate = row["candidate_id"]
        observed_sequence_sha256 = hashlib.sha256(row["sequence"].encode("utf-8")).hexdigest()
        require(observed_sequence_sha256 == row["sequence_sha256"], f"teacher_sequence_sha256:{candidate}")
        require(row["sequence_sha256"] not in sequence_hashes, f"duplicate_teacher_sequence:{candidate}")
        sequence_hashes.add(row["sequence_sha256"])

    split = load_json(args.split_manifest, "split_manifest")
    require(split.get("schema_version") == "pvrig_v2_9_whole_parent_split_v1", "split_schema")
    require(split.get("open_only") is True, "split_not_open_only")
    require(split.get("training_tsv_sha256") == hashes["teacher"], "split_teacher_hash")
    require(split.get("expected_total_rows") == args.expected_rows, "split_expected_total_rows")
    require(split.get("expected_train_rows") == args.expected_train_rows, "split_expected_train_rows")
    require(split.get("expected_score_rows") == args.expected_development_rows, "split_expected_score_rows")
    require(split.get("frozen_test_access_count") == 0, "frozen_access_nonzero")
    require(split.get("sealed_truth_access_count") == 0, "sealed_access_nonzero")
    train_parents = validate_parent_list(split, "train_parents")
    development_parents = validate_parent_list(split, "score_parents")
    frozen_parents = validate_parent_list(split, "frozen_test_parents")
    require(train_parents.isdisjoint(development_parents), "train_development_parent_overlap")
    require((train_parents | development_parents).isdisjoint(frozen_parents), "open_frozen_parent_overlap")
    require(stable_parent_hash(train_parents) == split.get("train_parent_set_sha256"), "train_parent_hash")
    require(stable_parent_hash(development_parents) == split.get("score_parent_set_sha256"), "development_parent_hash")
    require(stable_parent_hash(frozen_parents) == split.get("frozen_test_parent_set_sha256"), "frozen_parent_hash")
    teacher_parents = {row["parent_framework_cluster"] for row in teacher_rows}
    require(teacher_parents == train_parents | development_parents, "teacher_parent_set_not_exact")

    m2_fields, m2_rows = load_tsv(args.m2_features, "m2_features", required_fields=M2_METADATA)
    require(len(m2_rows) == args.expected_rows, f"m2_rows:{len(m2_rows)}")
    require(set(M2_METADATA) <= set(m2_fields), "m2_metadata_missing")
    m2_feature_names = [field for field in m2_fields if field not in M2_METADATA]
    require(len(m2_feature_names) == args.expected_structure_features, "m2_feature_count")
    require(len(m2_feature_names) == len(set(m2_feature_names)), "m2_duplicate_feature_name")
    m2 = unique_by(m2_rows, "candidate_id", "m2")
    expected_splits = {"development": args.expected_development_rows, "train": args.expected_train_rows}
    validate_m2_receipt(
        args.m2_receipt, hashes["m2_receipt"], args.m2_features, hashes["m2_features"],
        m2_feature_names, args.expected_rows, expected_splits,
    )

    c2_fields, c2_rows = load_tsv(
        args.coarse_pose,
        "coarse_pose",
        exact_fields=(*C2_METADATA, *C2_FEATURE_FIELDS),
    )
    require(c2_fields == [*C2_METADATA, *C2_FEATURE_FIELDS], "coarse_feature_schema")
    require(len(c2_rows) == args.expected_rows, f"coarse_rows:{len(c2_rows)}")
    require(len(C2_FEATURE_FIELDS) == args.expected_coarse_features, "coarse_feature_count")
    c2_model_features = [name for name in C2_FEATURE_FIELDS if name not in C2_EXCLUSIONS]
    require(len(c2_model_features) == args.expected_coarse_model_features, "coarse_model_feature_count")
    coarse = unique_by(c2_rows, "candidate_id", "coarse_pose")
    validate_c2_receipt(
        args.coarse_pose_receipt, hashes["coarse_pose_receipt"], args.coarse_pose,
        hashes["coarse_pose"], args.expected_rows, expected_splits,
    )

    expected_ids = set(teacher)
    require(set(m2) == expected_ids, "m2_candidate_set_not_exact")
    require(set(coarse) == expected_ids, "coarse_candidate_set_not_exact")
    output_rows: list[dict[str, Any]] = []
    split_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    reliability_counts: Counter[str] = Counter()
    train_observed: set[str] = set()
    development_observed: set[str] = set()
    exact_min_violations = 0
    for candidate in sorted(expected_ids):
        teacher_row = teacher[candidate]
        m2_row = m2[candidate]
        coarse_row = coarse[candidate]
        require(m2_row["schema_version"] == M2_SCHEMA, f"m2_schema:{candidate}")
        require(m2_row["sequence_sha256"] == teacher_row["sequence_sha256"], f"teacher_m2_sequence:{candidate}")
        require(m2_row["parent_framework_cluster"] == teacher_row["parent_framework_cluster"],
                f"teacher_m2_parent:{candidate}")
        require(m2_row["monomer_sha256"] == coarse_row["monomer_sha256"],
                f"m2_coarse_monomer:{candidate}")
        require(coarse_row["feature_schema"] == C2_FEATURE_SCHEMA, f"coarse_schema:{candidate}")
        parent = teacher_row["parent_framework_cluster"]
        if parent in train_parents:
            model_split = "train"
            train_observed.add(parent)
        else:
            require(parent in development_parents, f"teacher_parent_outside_open:{candidate}")
            model_split = "development"
            development_observed.add(parent)
        require(m2_row["model_split"] == model_split, f"m2_split:{candidate}")
        r8 = finite(teacher_row["R_8X6B"], f"R8:{candidate}")
        r9 = finite(teacher_row["R_9E6Y"], f"R9:{candidate}")
        dual = finite(teacher_row["R_dual_min"], f"Rdual:{candidate}")
        if abs(dual - min(r8, r9)) >= 2e-8:
            exact_min_violations += 1
            raise MaterializationError(f"exact_min:{candidate}")
        output: dict[str, Any] = {name: teacher_row[name] for name in TEACHER_FIELDS}
        output["model_split"] = model_split
        output["asset_lane"] = m2_row["asset_lane"]
        output["monomer_sha256"] = m2_row["monomer_sha256"]
        for name in m2_feature_names:
            output[name] = f"{finite(m2_row[name], f'm2:{candidate}:{name}'):.17g}"
        for name in C2_FEATURE_FIELDS:
            output[f"C2__{name}"] = f"{finite(coarse_row[name], f'c2:{candidate}:{name}'):.17g}"
        output_rows.append(output)
        split_counts[model_split] += 1
        source_counts[teacher_row["teacher_source"]] += 1
        reliability_counts[teacher_row["teacher_reliability"]] += 1

    require(split_counts == Counter(expected_splits), f"split_counts:{dict(split_counts)}")
    require(train_observed == train_parents, "materialized_train_parent_set_not_exact")
    require(development_observed == development_parents, "materialized_development_parent_set_not_exact")
    require(train_observed.isdisjoint(development_observed), "materialized_parent_overlap")
    cache_audit = validate_cache(
        args.esm2_650m_cache,
        args.expected_esm2_cache_receipt_sha256,
        {candidate: teacher[candidate]["sequence_sha256"] for candidate in sorted(expected_ids)},
    )

    output_dir.mkdir(parents=True)
    table_path = output_dir / "canonical10644_multimodal_open_v1.tsv"
    output_fields = [
        *TEACHER_FIELDS, "model_split", "asset_lane", "monomer_sha256",
        *m2_feature_names, *[f"C2__{name}" for name in C2_FEATURE_FIELDS],
    ]
    atomic_write(table_path, tsv_bytes(output_rows, output_fields))
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "counts": {
            "rows": len(output_rows),
            "splits": dict(sorted(split_counts.items())),
            "parents": {
                "train": len(train_observed),
                "development": len(development_observed),
                "frozen_test": len(frozen_parents),
            },
            "teacher_sources": dict(sorted(source_counts.items())),
            "teacher_reliability": dict(sorted(reliability_counts.items())),
        },
        "parent_closure": {
            "train_parents": sorted(train_observed),
            "development_parents": sorted(development_observed),
            "train_parent_set_sha256": stable_parent_hash(train_observed),
            "development_parent_set_sha256": stable_parent_hash(development_observed),
            "frozen_test_parent_set_sha256": stable_parent_hash(frozen_parents),
        },
        "features": {
            "m2_feature_names": m2_feature_names,
            "m2_feature_count": len(m2_feature_names),
            "coarse_feature_names": list(C2_FEATURE_FIELDS),
            "coarse_feature_count": len(C2_FEATURE_FIELDS),
            "coarse_model_feature_names": c2_model_features,
            "coarse_model_feature_count": len(c2_model_features),
        },
        "inputs": {
            role: {"path": str(input_paths[role].resolve()), "sha256": hashes[role]}
            for role in input_paths
        },
        "embedding_cache": cache_audit,
        "output": {"path": table_path.name, "sha256": sha256_file(table_path)},
        "invariants": {
            "candidate_set_exact_across_teacher_m2_c2": True,
            "sequence_sha256_recomputed_and_exact": True,
            "teacher_m2_sequence_sha256_join_exact": True,
            "m2_c2_monomer_sha256_join_exact": True,
            "whole_parent_split_exact": True,
            "parent_set_hashes_verified": True,
            "teacher_exact_min_violations": exact_min_violations,
            "all_numeric_values_finite": True,
            "all_input_and_upstream_receipt_hashes_verified": True,
            "frozen_test_access_count": 0,
            "sealed_truth_access_count": 0,
        },
    }
    receipt_path = output_dir / "canonical10644_multimodal_materialization_v1.receipt.json"
    atomic_write(
        receipt_path,
        (json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"),
    )
    sums = {
        table_path.name: sha256_file(table_path),
        receipt_path.name: sha256_file(receipt_path),
    }
    atomic_write(
        output_dir / "SHA256SUMS",
        "".join(f"{digest}  {name}\n" for name, digest in sorted(sums.items())).encode("ascii"),
    )
    return {
        "status": READY_STATUS,
        "rows": len(output_rows),
        "train_rows": split_counts["train"],
        "development_rows": split_counts["development"],
        "output_sha256": sha256_file(table_path),
        "receipt_sha256": sha256_file(receipt_path),
        "output_dir": str(output_dir),
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--teacher", type=Path, required=True)
    value.add_argument("--split-manifest", type=Path, required=True)
    value.add_argument("--m2-features", type=Path, required=True)
    value.add_argument("--m2-receipt", type=Path, required=True)
    value.add_argument("--coarse-pose", type=Path, required=True)
    value.add_argument("--coarse-pose-receipt", type=Path, required=True)
    value.add_argument("--esm2-650m-cache", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--expected-teacher-sha256", required=True)
    value.add_argument("--expected-split-sha256", required=True)
    value.add_argument("--expected-m2-features-sha256", required=True)
    value.add_argument("--expected-m2-receipt-sha256", required=True)
    value.add_argument("--expected-coarse-pose-sha256", required=True)
    value.add_argument("--expected-coarse-pose-receipt-sha256", required=True)
    value.add_argument("--expected-esm2-cache-receipt-sha256", required=True)
    value.add_argument("--expected-rows", type=int, default=10644)
    value.add_argument("--expected-train-rows", type=int, default=9849)
    value.add_argument("--expected-development-rows", type=int, default=795)
    value.add_argument("--expected-structure-features", type=int, default=126)
    value.add_argument("--expected-coarse-features", type=int, default=36)
    value.add_argument("--expected-coarse-model-features", type=int, default=32)
    return value


def main() -> int:
    result = materialize(parser().parse_args())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
