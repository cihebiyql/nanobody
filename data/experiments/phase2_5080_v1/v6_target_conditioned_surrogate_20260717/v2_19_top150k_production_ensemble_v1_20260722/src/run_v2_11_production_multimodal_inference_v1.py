#!/usr/bin/env python3
"""Run frozen V2.11 S0/M2(/C2) models on a label-free production panel.

The adapter deliberately accepts no teacher or Docking geometry columns.  It
joins the compact candidate manifest, the hash-closed pooled ESM2 cache, the
126-dimensional M2 table, and an optional 32-dimensional C2 table by
``candidate_id`` and ``sequence_sha256``.  Every reported dual score is the
exact minimum of the two independently predicted receptor scores.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import pickle
import shutil
import stat
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import torch


SCHEMA_VERSION = "pvrig_v2_19_v2_11_production_multimodal_inference_v1"
MODEL_SCHEMA = "pvrig_v2_11_canonical_multimodal_fusion_v1"
EMBEDDING_SCHEMA = "pvrig_v6_esm_embedding_cache_v1"
STATUS = "PASS_LABEL_FREE_PRODUCTION_MULTIMODAL_INFERENCE"
CLAIM_BOUNDARY = (
    "Production sequence/monomer/coarse-pose surrogate approximation of "
    "independent 8X6B/9E6Y computational Docking geometry only; not binding, "
    "affinity, experimental blocking, Docking Gold, frozen-test, sealed truth, "
    "or submission evidence."
)
MODEL_CLAIM_BOUNDARY = (
    "Open-development approximation of independent 8X6B/9E6Y computational "
    "Docking geometry only; not binding, affinity, experimental blocking, "
    "Docking Gold, frozen-test, sealed truth, or submission evidence."
)
FORBIDDEN_PATH_TOKENS = (
    "test32", "sealed_truth", "frozen_test", "frozen-test", "v4_f",
)
FORBIDDEN_FIELD_TOKENS = (
    "truth", "teacher", "label", "r_8x6b", "r_9e6y", "r_dual",
    "haddock", "docking_score", "geometry_tier", "hotspot_overlap",
    "occlusion", "experimental_block", "binding_truth",
)
AA = frozenset("ACDEFGHIKLMNPQRSTVWY")
HYDROPHOBIC = frozenset("AVILMFWY")
AROMATIC = frozenset("FWY")
POSITIVE = frozenset("KRH")
NEGATIVE = frozenset("DE")
MANIFEST_ALIASES = {
    "parent_framework_cluster": ("parent_framework_cluster", "parent_cluster"),
    "cdr1": ("cdr1", "cdr1_after"),
    "cdr2": ("cdr2", "cdr2_after"),
    "cdr3": ("cdr3", "cdr3_after"),
}
BASE_LANES = (
    "S0_MATCHED_ESM2_650M_PCA_ELASTICNET",
    "M2_STRUCTURE_ALPHA10",
)
C2_LANES = (
    "C2_COARSE_POSE_PCA8",
    "M2_C2_CONVEX",
    "S0_M2_C2_CONVEX",
    "SHALLOW_GBDT_CHALLENGER",
)


class ProductionInferenceError(RuntimeError):
    """Fail-closed production inference error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProductionInferenceError(message)


def reject_path(path: Path, role: str) -> None:
    normalized = str(path.resolve()).lower().replace("-", "_")
    for token in FORBIDDEN_PATH_TOKENS:
        require(token.replace("-", "_") not in normalized,
                f"forbidden_{role}_path:{token}")


def require_regular(path: Path, role: str) -> None:
    reject_path(path, role)
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ProductionInferenceError(f"missing_{role}:{path}") from exc
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


def reject_forbidden_fields(fields: Iterable[str], role: str) -> None:
    for field in fields:
        normalized = field.strip().lower().replace("-", "_")
        for token in FORBIDDEN_FIELD_TOKENS:
            require(token not in normalized,
                    f"forbidden_{role}_field:{field}:{token}")


def load_tsv(path: Path, role: str) -> tuple[list[str], list[dict[str, str]]]:
    require_regular(path, role)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        require(fields and len(fields) == len(set(fields)), f"{role}_header_invalid")
        reject_forbidden_fields(fields, role)
        rows = [dict(row) for row in reader]
    require(rows, f"{role}_empty")
    return fields, rows


def unique_rows(rows: Sequence[dict[str, str]], role: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        candidate = row.get("candidate_id", "").strip()
        require(candidate and candidate not in result,
                f"{role}_duplicate_or_blank_candidate:{candidate}")
        result[candidate] = row
    return result


def resolve_alias(fields: Sequence[str], canonical: str) -> str:
    aliases = MANIFEST_ALIASES[canonical]
    present = [name for name in aliases if name in fields]
    require(len(present) == 1,
            f"manifest_alias_resolution:{canonical}:{','.join(present)}")
    return present[0]


def load_manifest(path: Path) -> tuple[list[dict[str, str]], dict[str, str]]:
    fields, raw_rows = load_tsv(path, "compact_manifest")
    for required in ("candidate_id", "sequence", "sequence_sha256"):
        require(required in fields, f"manifest_missing_field:{required}")
    aliases = {name: resolve_alias(fields, name) for name in MANIFEST_ALIASES}
    rows_by_id = unique_rows(raw_rows, "manifest")
    normalized: list[dict[str, str]] = []
    sequence_hashes: set[str] = set()
    for candidate in sorted(rows_by_id):
        row = rows_by_id[candidate]
        sequence = row["sequence"].strip().upper()
        sequence_sha256 = row["sequence_sha256"].strip().lower()
        require(sequence and set(sequence) <= AA, f"invalid_sequence:{candidate}")
        require(hashlib.sha256(sequence.encode()).hexdigest() == sequence_sha256,
                f"manifest_sequence_sha256:{candidate}")
        require(sequence_sha256 not in sequence_hashes,
                f"duplicate_sequence_sha256:{candidate}")
        sequence_hashes.add(sequence_sha256)
        item = {
            "candidate_id": candidate,
            "sequence": sequence,
            "sequence_sha256": sequence_sha256,
            "parent_framework_cluster": row[aliases["parent_framework_cluster"]].strip(),
            "cdr1": row[aliases["cdr1"]].strip().upper(),
            "cdr2": row[aliases["cdr2"]].strip().upper(),
            "cdr3": row[aliases["cdr3"]].strip().upper(),
        }
        require(item["parent_framework_cluster"], f"blank_parent:{candidate}")
        for cdr in ("cdr1", "cdr2", "cdr3"):
            value = item[cdr]
            require(value and set(value) <= AA and value in sequence,
                    f"invalid_{cdr}:{candidate}")
        normalized.append(item)
    return normalized, aliases


def finite(raw: str, label: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ProductionInferenceError(f"invalid_numeric:{label}:{raw!r}") from exc
    require(math.isfinite(value), f"nonfinite:{label}")
    return value


def load_feature_matrix(
    path: Path,
    role: str,
    feature_names: Sequence[str],
    manifest_rows: Sequence[Mapping[str, str]],
) -> tuple[np.ndarray, dict[str, Any]]:
    fields, rows = load_tsv(path, role)
    require("candidate_id" in fields, f"{role}_candidate_id_missing")
    missing = [name for name in feature_names if name not in fields]
    require(not missing, f"{role}_features_missing:{','.join(missing[:5])}")
    by_id = unique_rows(rows, role)
    expected = {row["candidate_id"] for row in manifest_rows}
    require(set(by_id) == expected,
            f"{role}_candidate_closure:expected={len(expected)}:observed={len(by_id)}")
    matrix: list[list[float]] = []
    for row in manifest_rows:
        candidate = row["candidate_id"]
        feature_row = by_id[candidate]
        if "sequence_sha256" in fields:
            require(feature_row["sequence_sha256"].strip().lower() == row["sequence_sha256"],
                    f"{role}_sequence_sha256:{candidate}")
        if "parent_framework_cluster" in fields:
            require(feature_row["parent_framework_cluster"].strip() == row["parent_framework_cluster"],
                    f"{role}_parent:{candidate}")
        matrix.append([
            finite(feature_row[name], f"{role}:{candidate}:{name}")
            for name in feature_names
        ])
    values = np.asarray(matrix, dtype=np.float64)
    require(values.shape == (len(manifest_rows), len(feature_names)),
            f"{role}_matrix_shape:{values.shape}")
    require(np.isfinite(values).all(), f"{role}_matrix_nonfinite")
    return values, {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "rows": len(rows),
        "features": len(feature_names),
        "candidate_closure_exact": True,
    }


def load_embedding_cache(
    cache_dir: Path,
    manifest_rows: Sequence[Mapping[str, str]],
) -> tuple[np.ndarray, dict[str, Any]]:
    reject_path(cache_dir, "embedding_cache")
    require(cache_dir.is_dir() and not cache_dir.is_symlink(), "embedding_cache_not_directory")
    receipt_path = cache_dir / "embedding_cache_receipt.json"
    require_regular(receipt_path, "embedding_receipt")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionInferenceError("embedding_receipt_invalid_json") from exc
    require(receipt.get("schema_version") == EMBEDDING_SCHEMA, "embedding_schema")
    shard_root = (cache_dir / "shards").resolve()
    expected = {row["candidate_id"]: row["sequence_sha256"] for row in manifest_rows}
    values: dict[str, np.ndarray] = {}
    hashes: dict[str, str] = {}
    width: int | None = None
    shard_audit: list[dict[str, Any]] = []
    shard_records = receipt.get("shards")
    require(isinstance(shard_records, list) and shard_records, "embedding_shards_invalid")
    for item in shard_records:
        require(isinstance(item, dict), "embedding_shard_record_invalid")
        shard = Path(str(item.get("path", "")))
        if not shard.is_absolute():
            shard = cache_dir / shard
        require(shard.parent.resolve() == shard_root, f"embedding_shard_outside_cache:{shard}")
        require_regular(shard, "embedding_shard")
        observed_sha256 = sha256_file(shard)
        require(observed_sha256 == item.get("sha256"), f"embedding_shard_hash:{shard.name}")
        try:
            payload = torch.load(shard, map_location="cpu", weights_only=False)
            matrix = payload["embeddings"].float().numpy()
            identifiers = payload["metadata"]["candidate_ids"]
            sequence_hashes = payload["metadata"]["sequence_sha256"]
        except (KeyError, TypeError, RuntimeError, ValueError) as exc:
            raise ProductionInferenceError(f"embedding_shard_payload:{shard.name}") from exc
        require(matrix.ndim == 2 and matrix.shape[0] == len(identifiers) == len(sequence_hashes),
                f"embedding_shard_shape:{shard.name}")
        require(int(item.get("rows", -1)) == len(identifiers),
                f"embedding_shard_receipt_rows:{shard.name}")
        width = int(matrix.shape[1]) if width is None else width
        require(matrix.shape[1] == width and np.isfinite(matrix).all(),
                f"embedding_shard_width_or_finite:{shard.name}")
        for candidate, sequence_sha256, vector in zip(identifiers, sequence_hashes, matrix):
            candidate = str(candidate)
            require(candidate not in values, f"duplicate_embedding:{candidate}")
            values[candidate] = vector.astype(np.float64)
            hashes[candidate] = str(sequence_sha256).lower()
        shard_audit.append({
            "name": shard.name,
            "sha256": observed_sha256,
            "rows": len(identifiers),
        })
    require(int(receipt.get("rows", -1)) == len(values), "embedding_receipt_rows")
    require(set(values) == set(expected),
            f"embedding_candidate_closure:expected={len(expected)}:observed={len(values)}")
    for candidate, sequence_sha256 in expected.items():
        require(hashes[candidate] == sequence_sha256,
                f"embedding_sequence_sha256:{candidate}")
    matrix = np.stack([values[row["candidate_id"]] for row in manifest_rows])
    return matrix, {
        "path": str(cache_dir.resolve()),
        "receipt_sha256": sha256_file(receipt_path),
        "rows": len(values),
        "width": width,
        "candidate_closure_exact": True,
        "all_shard_hashes_verified": True,
        "shards": shard_audit,
    }


def region_features(sequence: str) -> list[float]:
    n = len(sequence)
    require(n > 0, "empty_region")
    counts = {aa: sequence.count(aa) for aa in sorted(AA)}
    # Preserve the original V2.11 amino-acid feature order.
    aa_order = "ACDEFGHIKLMNPQRSTVWY"
    probs = [counts[aa] / n for aa in aa_order]
    entropy = -sum(value * math.log(value + 1e-12) for value in probs) / math.log(len(aa_order))
    return [
        float(n), *probs,
        sum(counts[aa] for aa in HYDROPHOBIC) / n,
        sum(counts[aa] for aa in AROMATIC) / n,
        sum(counts[aa] for aa in POSITIVE) / n,
        sum(counts[aa] for aa in NEGATIVE) / n,
        (sum(counts[aa] for aa in POSITIVE) - sum(counts[aa] for aa in NEGATIVE)) / n,
        counts["G"] / n, counts["P"] / n, counts["C"] / n,
        entropy, max(counts.values()) / n,
    ]


def physchem(rows: Sequence[Mapping[str, str]]) -> np.ndarray:
    matrix = np.asarray([
        [value for field in ("sequence", "cdr1", "cdr2", "cdr3")
         for value in region_features(row[field])]
        for row in rows
    ], dtype=np.float64)
    require(matrix.shape == (len(rows), 124), f"physchem_shape:{matrix.shape}")
    require(np.isfinite(matrix).all(), "physchem_nonfinite")
    return matrix


def predict_s0(bundle: Mapping[str, Any], embeddings: np.ndarray,
               physicochemical: np.ndarray) -> np.ndarray:
    joined = np.concatenate((bundle["pca"].transform(embeddings), physicochemical), axis=1)
    transformed = bundle["scaler"].transform(joined)
    result = np.column_stack([model.predict(transformed) for model in bundle["models"]])
    require(result.shape == (len(embeddings), 2) and np.isfinite(result).all(),
            "s0_prediction_invalid")
    return np.asarray(result, dtype=np.float64)


def predict_scaled(bundle: Mapping[str, Any], matrix: np.ndarray) -> np.ndarray:
    result = np.asarray(bundle["model"].predict(bundle["scaler"].transform(matrix)),
                        dtype=np.float64)
    require(result.shape == (len(matrix), 2) and np.isfinite(result).all(),
            "scaled_prediction_invalid")
    return result


def transform_pca8(matrix: np.ndarray, state: Mapping[str, Any]) -> np.ndarray:
    retained = np.asarray(state["retained"], dtype=int)
    normalized = (
        matrix[:, retained] - np.asarray(state["mean"])[retained]
    ) / np.asarray(state["scale"])[retained]
    result = normalized @ np.asarray(state["axes"]).T
    require(np.isfinite(result).all(), "c2_transform_nonfinite")
    return result


def predict_c2(bundle: Mapping[str, Any], matrix: np.ndarray) -> np.ndarray:
    return predict_scaled(bundle["ridge"], transform_pca8(matrix, bundle["pca"]))


def predict_convex(model: Mapping[str, Any], bases: Mapping[str, np.ndarray]) -> np.ndarray:
    fallback = str(model["fallback"])
    require(fallback in bases, f"convex_fallback_missing:{fallback}")
    result = bases[fallback].copy()
    for name, weight in zip(model["branches"], model["weights"]):
        require(name in bases, f"convex_branch_missing:{name}")
        result += float(weight) * (bases[name] - bases[fallback])
    require(result.shape == bases[fallback].shape and np.isfinite(result).all(),
            "convex_prediction_invalid")
    return result


def meta_features(bases: Mapping[str, np.ndarray]) -> np.ndarray:
    s0, m2, c2 = (bases[name] for name in ("S0", "M2", "C2"))
    result = np.column_stack([
        s0, m2, c2,
        np.abs(s0[:, 0] - s0[:, 1]),
        np.abs(m2[:, 0] - m2[:, 1]),
        np.abs(c2[:, 0] - c2[:, 1]),
        np.mean(np.abs(s0 - m2), axis=1),
        np.mean(np.abs(s0 - c2), axis=1),
        np.mean(np.abs(m2 - c2), axis=1),
    ])
    require(result.shape == (len(s0), 12) and np.isfinite(result).all(),
            f"meta_feature_shape:{result.shape}")
    return result


def predict_gbdt(models: Sequence[Any], matrix: np.ndarray) -> np.ndarray:
    require(len(models) == 2, "gbdt_model_count")
    result = np.column_stack([model.predict(matrix) for model in models])
    require(result.shape == (len(matrix), 2) and np.isfinite(result).all(),
            "gbdt_prediction_invalid")
    return result


def validate_artifact(path: Path, expected_sha256: str) -> tuple[dict[str, Any], dict[str, Any]]:
    require_regular(path, "model_artifact")
    observed_sha256 = validate_hash(path, expected_sha256, "model_artifact")
    try:
        with path.open("rb") as handle:
            artifact = pickle.load(handle)
    except (AttributeError, EOFError, ImportError, ModuleNotFoundError, pickle.UnpicklingError) as exc:
        raise ProductionInferenceError("model_artifact_unpickle") from exc
    require(isinstance(artifact, dict), "model_artifact_not_mapping")
    require(artifact.get("schema_version") == MODEL_SCHEMA, "model_artifact_schema")
    require(artifact.get("claim_boundary") == MODEL_CLAIM_BOUNDARY,
            "model_artifact_claim_boundary")
    required = {
        "S0", "M2", "C2", "fusion_m2c2", "fusion_all", "gbdt",
        "structure_feature_names", "c2_feature_names",
    }
    require(required <= set(artifact), "model_artifact_keys")
    structure_names = artifact["structure_feature_names"]
    c2_names = artifact["c2_feature_names"]
    require(isinstance(structure_names, list) and len(structure_names) == 126
            and len(set(structure_names)) == 126, "model_artifact_m2_contract")
    require(isinstance(c2_names, list) and len(c2_names) == 32
            and len(set(c2_names)) == 32, "model_artifact_c2_contract")
    reject_forbidden_fields(structure_names, "artifact_m2")
    reject_forbidden_fields(c2_names, "artifact_c2")
    return artifact, {
        "path": str(path.resolve()),
        "sha256": observed_sha256,
        "schema_version": artifact["schema_version"],
        "claim_boundary_verified": True,
        "m2_features": len(structure_names),
        "c2_features": len(c2_names),
    }


def exact_min(prediction: np.ndarray) -> np.ndarray:
    require(prediction.ndim == 2 and prediction.shape[1] == 2,
            "prediction_shape_for_exact_min")
    return np.minimum(prediction[:, 0], prediction[:, 1])


def competition_ranks(candidate_ids: Sequence[str], scores: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = sorted(range(len(scores)), key=lambda index: (-float(scores[index]), candidate_ids[index]))
    ranks = np.empty(len(scores), dtype=np.int64)
    for rank, index in enumerate(order, start=1):
        ranks[index] = rank
    percentiles = 1.0 - (ranks - 1) / max(1, len(scores) - 1)
    return ranks, percentiles


def tsv_bytes(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def atomic_write(path: Path, payload: bytes) -> None:
    require(not path.exists() and not path.is_symlink(), f"output_exists:{path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def run(args: argparse.Namespace) -> dict[str, Any]:
    reject_path(args.output_dir, "output")
    require(not args.output_dir.exists() and not args.output_dir.is_symlink(), "output_exists")
    require((args.c2_features is None) == (args.expected_c2_features_sha256 is None),
            "c2_path_hash_pair_required")

    manifest_rows, aliases = load_manifest(args.compact_manifest)
    manifest_sha256 = validate_hash(
        args.compact_manifest, args.expected_compact_manifest_sha256, "compact_manifest"
    )
    if args.expected_rows is not None:
        require(len(manifest_rows) == args.expected_rows,
                f"manifest_expected_rows:{len(manifest_rows)}")

    artifact, artifact_audit = validate_artifact(
        args.model_artifact, args.expected_model_artifact_sha256
    )
    embeddings, embedding_audit = load_embedding_cache(args.esm2_pooled_cache, manifest_rows)
    m2_matrix, m2_audit = load_feature_matrix(
        args.m2_features, "m2_features", artifact["structure_feature_names"], manifest_rows
    )
    validate_hash(args.m2_features, args.expected_m2_features_sha256, "m2_features")
    physicochemical = physchem(manifest_rows)

    bases: dict[str, np.ndarray] = {
        "S0": predict_s0(artifact["S0"], embeddings, physicochemical),
        "M2": predict_scaled(artifact["M2"], m2_matrix),
    }
    predictions: dict[str, np.ndarray] = {
        BASE_LANES[0]: bases["S0"],
        BASE_LANES[1]: bases["M2"],
    }
    c2_audit: dict[str, Any] = {"status": "NOT_PROVIDED"}
    if args.c2_features is not None:
        c2_matrix, c2_audit = load_feature_matrix(
            args.c2_features, "c2_features", artifact["c2_feature_names"], manifest_rows
        )
        validate_hash(args.c2_features, args.expected_c2_features_sha256, "c2_features")
        bases["C2"] = predict_c2(artifact["C2"], c2_matrix)
        predictions.update({
            C2_LANES[0]: bases["C2"],
            C2_LANES[1]: predict_convex(
                artifact["fusion_m2c2"], {"M2": bases["M2"], "C2": bases["C2"]}
            ),
            C2_LANES[2]: predict_convex(artifact["fusion_all"], bases),
            C2_LANES[3]: predict_gbdt(artifact["gbdt"], meta_features(bases)),
        })
        c2_audit["status"] = "PASS_OPTIONAL_C2_CLOSURE"

    candidate_ids = [row["candidate_id"] for row in manifest_rows]
    lane_ranks: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    exact_min_violation_count = 0
    for lane, prediction in predictions.items():
        dual = exact_min(prediction)
        exact_min_violation_count += int(np.sum(dual != np.minimum(prediction[:, 0], prediction[:, 1])))
        lane_ranks[lane] = competition_ranks(candidate_ids, dual)
    require(exact_min_violation_count == 0, "exact_min_violation")

    output_rows: list[dict[str, Any]] = []
    for index, source in enumerate(manifest_rows):
        row: dict[str, Any] = {
            "candidate_id": source["candidate_id"],
            "sequence_sha256": source["sequence_sha256"],
            "parent_framework_cluster": source["parent_framework_cluster"],
            "claim_boundary": CLAIM_BOUNDARY,
        }
        for lane, prediction in predictions.items():
            ranks, percentiles = lane_ranks[lane]
            row[f"{lane}__R8"] = format(float(prediction[index, 0]), ".12g")
            row[f"{lane}__R9"] = format(float(prediction[index, 1]), ".12g")
            row[f"{lane}__Rdual_exact_min"] = format(
                float(min(prediction[index, 0], prediction[index, 1])), ".12g"
            )
            row[f"{lane}__Rdual_rank"] = int(ranks[index])
            row[f"{lane}__Rdual_rank_percentile"] = format(float(percentiles[index]), ".12g")
        output_rows.append(row)
    fields = list(output_rows[0])

    temporary_dir = args.output_dir.with_name(f".{args.output_dir.name}.{os.getpid()}.tmp")
    require(not temporary_dir.exists() and not temporary_dir.is_symlink(), "temporary_output_exists")
    temporary_dir.mkdir(parents=True)
    try:
        prediction_path = temporary_dir / "PRODUCTION_PREDICTIONS_RANK_READY.tsv"
        atomic_write(prediction_path, tsv_bytes(output_rows, fields))
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "status": STATUS,
            "claim_boundary": CLAIM_BOUNDARY,
            "counts": {
                "rows": len(manifest_rows),
                "parent_framework_clusters": len({r["parent_framework_cluster"] for r in manifest_rows}),
                "prediction_lanes": len(predictions),
                "m2_features": len(artifact["structure_feature_names"]),
                "c2_features": len(artifact["c2_feature_names"]) if args.c2_features else 0,
            },
            "lanes": list(predictions),
            "inputs": {
                "compact_manifest": {
                    "path": str(args.compact_manifest.resolve()),
                    "sha256": manifest_sha256,
                    "aliases": aliases,
                },
                "model_artifact": artifact_audit,
                "esm2_pooled_cache": embedding_audit,
                "m2_features": m2_audit,
                "c2_features": c2_audit,
            },
            "output": {
                "path": str((args.output_dir / prediction_path.name).resolve()),
                "sha256": sha256_file(prediction_path),
                "rows": len(output_rows),
                "fields": fields,
            },
            "invariants": {
                "candidate_set_exact": True,
                "sequence_sha256_join_exact": True,
                "model_artifact_hash_verified_before_unpickle": True,
                "all_input_shard_hashes_verified": True,
                "all_predictions_finite": True,
                "dual_scores_derived_by_exact_min": True,
                "exact_min_violation_count": exact_min_violation_count,
                "truth_columns_present": 0,
                "teacher_label_values_read": 0,
                "candidate_docking_pose_files_opened": 0,
                "frozen_test_access_count": 0,
                "sealed_truth_access_count": 0,
            },
        }
        receipt_path = temporary_dir / "RUN_RECEIPT.json"
        atomic_write(
            receipt_path,
            (json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(),
        )
        sums = {
            path.name: sha256_file(path)
            for path in temporary_dir.iterdir()
            if path.is_file() and path.name != "SHA256SUMS"
        }
        atomic_write(
            temporary_dir / "SHA256SUMS",
            "".join(f"{digest}  {name}\n" for name, digest in sorted(sums.items())).encode(),
        )
        args.output_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary_dir, args.output_dir)
    except BaseException:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise
    return {
        "status": STATUS,
        "rows": len(manifest_rows),
        "lanes": list(predictions),
        "output_dir": str(args.output_dir),
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--compact-manifest", type=Path, required=True)
    value.add_argument("--expected-compact-manifest-sha256", required=True)
    value.add_argument("--esm2-pooled-cache", type=Path, required=True)
    value.add_argument("--m2-features", type=Path, required=True)
    value.add_argument("--expected-m2-features-sha256", required=True)
    value.add_argument("--c2-features", type=Path)
    value.add_argument("--expected-c2-features-sha256")
    value.add_argument("--model-artifact", type=Path, required=True)
    value.add_argument("--expected-model-artifact-sha256", required=True)
    value.add_argument("--expected-rows", type=int)
    value.add_argument("--output-dir", type=Path, required=True)
    return value


def main() -> int:
    result = run(parser().parse_args())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
