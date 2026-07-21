#!/usr/bin/env python3
"""Materialize the frozen M2 126D label-free monomer feature schema."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import stat
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Mapping

import numpy as np


SCHEMA_VERSION = "pvrig_v2_11_canonical10644_m2_126d_features_v1"
INPUT_SCHEMA = "pvrig_v2_11_canonical10644_label_free_structure_manifest_v1"
READY_STATUS = "PASS_CANONICAL10644_M2_126D_FEATURES_MATERIALIZED"
CLAIM_BOUNDARY = (
    "126 label-free rigid-invariant descriptors from hash-closed VHH monomer "
    "structures; no Docking pose, scalar geometry label, binding, affinity, or "
    "experimental blocking truth."
)
REGIONS = ("ALL", "FRAMEWORK", "CDR1", "CDR2", "CDR3", "CDR_ALL")
REGION_FEATURES = (
    "residue_count", "confidence_mean", "confidence_std", "confidence_min", "confidence_q10",
    "ca_radius_of_gyration", "ca_pair_distance_q10", "ca_pair_distance_q25",
    "ca_pair_distance_q50", "ca_pair_distance_q75", "ca_pair_distance_q90",
    "ca_pair_distance_max", "ca_path_length", "ca_end_to_end_distance", "ca_tortuosity",
    "nonlocal_ca_contact_density_8A", "shape_eigenvalue_1_fraction",
    "shape_eigenvalue_2_fraction", "shape_eigenvalue_3_fraction",
)
CDR_NAMES = ("CDR1", "CDR2", "CDR3")


class FeatureError(RuntimeError):
    """Fail-closed feature materialization error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FeatureError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise FeatureError(f"missing_file:{label}:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"not_regular_file:{label}:{path}")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists() and not path.is_symlink(), f"output_exists:{path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def parse_range(value: str, label: str) -> set[int]:
    match = re.fullmatch(r"([0-9]+)-([0-9]+)", value)
    require(match is not None, f"invalid_range:{label}:{value}")
    start, stop = (int(item) for item in match.groups())
    require(1 <= start <= stop, f"invalid_range_order:{label}:{value}")
    return set(range(start, stop + 1))


def load_ca_records(path: Path, expected_chain: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    require_regular_file(path, "monomer_pdb")
    records: list[tuple[int, np.ndarray, float]] = []
    seen: set[int] = set()
    with path.open("r", encoding="ascii", errors="strict") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.startswith("ATOM  ") or line[12:16].strip() != "CA":
                continue
            require(len(line) >= 66, f"short_ca_record:{path}:{line_number}")
            chain = line[21:22]
            require(chain == expected_chain, f"unexpected_ca_chain:{path}:{line_number}:{chain}")
            require(line[26:27] == " ", f"insertion_code_not_supported:{path}:{line_number}")
            try:
                residue = int(line[22:26])
                xyz = np.asarray(
                    [float(line[30:38]), float(line[38:46]), float(line[46:54])], dtype=np.float64
                )
                confidence = float(line[60:66])
            except ValueError as exc:
                raise FeatureError(f"invalid_ca_numeric:{path}:{line_number}") from exc
            require(residue not in seen, f"duplicate_ca_residue:{path}:{residue}")
            require(np.isfinite(xyz).all() and math.isfinite(confidence),
                    f"nonfinite_ca_record:{path}:{line_number}")
            seen.add(residue)
            records.append((residue, xyz, confidence))
    require(len(records) >= 80, f"too_few_ca_records:{path}:{len(records)}")
    records.sort(key=lambda item: item[0])
    return (
        np.asarray([item[0] for item in records], dtype=np.int64),
        np.stack([item[1] for item in records]),
        np.asarray([item[2] for item in records], dtype=np.float64),
    )


def pair_distances(coordinates: np.ndarray) -> np.ndarray:
    if len(coordinates) < 2:
        return np.asarray([], dtype=np.float64)
    delta = coordinates[:, None, :] - coordinates[None, :, :]
    distance = np.sqrt(np.sum(delta * delta, axis=2))
    return distance[np.triu_indices(len(coordinates), k=1)]


def region_descriptors(
    residues: np.ndarray, coordinates: np.ndarray, confidence: np.ndarray
) -> dict[str, float]:
    require(len(residues) == len(coordinates) == len(confidence) and len(residues) > 0, "empty_region")
    centered = coordinates - coordinates.mean(axis=0, keepdims=True)
    radius = float(np.sqrt(np.mean(np.sum(centered * centered, axis=1))))
    distances = pair_distances(coordinates)
    require(len(distances) > 0, "region_without_pair_distances")
    quantiles = np.quantile(distances, [0.10, 0.25, 0.50, 0.75, 0.90])
    ordered_coordinates = coordinates[np.argsort(residues)]
    steps = np.linalg.norm(np.diff(ordered_coordinates, axis=0), axis=1)
    path_length = float(steps.sum())
    end_to_end = float(np.linalg.norm(ordered_coordinates[-1] - ordered_coordinates[0]))
    delta = coordinates[:, None, :] - coordinates[None, :, :]
    matrix = np.sqrt(np.sum(delta * delta, axis=2))
    sequence_separation = np.abs(residues[:, None] - residues[None, :])
    eligible = np.triu(sequence_separation > 2, k=1)
    eligible_count = int(eligible.sum())
    contact_density = float(((matrix < 8.0) & eligible).sum() / eligible_count) if eligible_count else 0.0
    covariance = centered.T @ centered / float(len(coordinates))
    eigenvalues = np.maximum(np.linalg.eigvalsh(covariance)[::-1], 0.0)
    eigen_sum = float(eigenvalues.sum())
    fractions = eigenvalues / eigen_sum if eigen_sum > 0 else np.asarray([1.0, 0.0, 0.0])
    values = {
        "residue_count": float(len(residues)),
        "confidence_mean": float(np.mean(confidence)),
        "confidence_std": float(np.std(confidence)),
        "confidence_min": float(np.min(confidence)),
        "confidence_q10": float(np.quantile(confidence, 0.10)),
        "ca_radius_of_gyration": radius,
        "ca_pair_distance_q10": float(quantiles[0]),
        "ca_pair_distance_q25": float(quantiles[1]),
        "ca_pair_distance_q50": float(quantiles[2]),
        "ca_pair_distance_q75": float(quantiles[3]),
        "ca_pair_distance_q90": float(quantiles[4]),
        "ca_pair_distance_max": float(np.max(distances)),
        "ca_path_length": path_length,
        "ca_end_to_end_distance": end_to_end,
        "ca_tortuosity": path_length / max(end_to_end, 1e-6),
        "nonlocal_ca_contact_density_8A": contact_density,
        "shape_eigenvalue_1_fraction": float(fractions[0]),
        "shape_eigenvalue_2_fraction": float(fractions[1]),
        "shape_eigenvalue_3_fraction": float(fractions[2]),
    }
    require(set(values) == set(REGION_FEATURES), "region_feature_contract_mismatch")
    require(all(math.isfinite(value) for value in values.values()), "nonfinite_region_feature")
    return values


def structure_features(path: Path, chain: str, cdr_ranges: Mapping[str, str]) -> dict[str, float]:
    residues, coordinates, confidence = load_ca_records(path, chain)
    residue_set = set(int(value) for value in residues)
    cdr_sets = {name: parse_range(cdr_ranges[name], name) for name in CDR_NAMES}
    for name, expected in cdr_sets.items():
        require(expected <= residue_set, f"missing_cdr_residues:{name}:{sorted(expected - residue_set)}")
        require(len(expected) >= 3, f"cdr_too_short:{name}")
    cdr_all = set().union(*cdr_sets.values())
    framework = residue_set - cdr_all
    require(len(framework) >= 60, f"framework_too_short:{len(framework)}")
    masks = {
        "ALL": np.ones(len(residues), dtype=bool),
        "FRAMEWORK": np.asarray([int(value) in framework for value in residues]),
        "CDR1": np.asarray([int(value) in cdr_sets["CDR1"] for value in residues]),
        "CDR2": np.asarray([int(value) in cdr_sets["CDR2"] for value in residues]),
        "CDR3": np.asarray([int(value) in cdr_sets["CDR3"] for value in residues]),
        "CDR_ALL": np.asarray([int(value) in cdr_all for value in residues]),
    }
    output: dict[str, float] = {}
    for region in REGIONS:
        values = region_descriptors(residues[masks[region]], coordinates[masks[region]], confidence[masks[region]])
        output.update({f"{region}__{name}": value for name, value in values.items()})
    centroids = {name: coordinates[masks[name]].mean(axis=0) for name in (*CDR_NAMES, "FRAMEWORK")}
    for left, right in (("CDR1", "CDR2"), ("CDR1", "CDR3"), ("CDR2", "CDR3")):
        output[f"{left}_{right}__centroid_distance"] = float(np.linalg.norm(centroids[left] - centroids[right]))
    framework_coordinates = coordinates[masks["FRAMEWORK"]]
    for name in CDR_NAMES:
        cdr_coordinates = coordinates[masks[name]]
        distances = np.linalg.norm(cdr_coordinates[:, None, :] - framework_coordinates[None, :, :], axis=2)
        output[f"{name}_FRAMEWORK__centroid_distance"] = float(
            np.linalg.norm(centroids[name] - centroids["FRAMEWORK"])
        )
        output[f"{name}_FRAMEWORK__minimum_ca_distance"] = float(np.min(distances))
        output[f"{name}_FRAMEWORK__median_minimum_ca_distance"] = float(
            np.median(np.min(distances, axis=1))
        )
    require(len(output) == 126, f"feature_count_invalid:{len(output)}")
    require(all(math.isfinite(value) for value in output.values()), "nonfinite_structure_feature")
    return output


def _extract_one(row: dict[str, str]) -> tuple[dict[str, str], dict[str, float]]:
    path = Path(row["monomer_path"])
    require(sha256_file(path) == row["monomer_sha256"], f"pdb_sha256_mismatch:{row['candidate_id']}")
    values = structure_features(
        path,
        row["monomer_chain"],
        {"CDR1": row["cdr1_range"], "CDR2": row["cdr2_range"], "CDR3": row["cdr3_range"]},
    )
    return row, values


def materialize(
    input_manifest: Path,
    expected_manifest_sha256: str,
    output_dir: Path,
    expected_rows: int,
    workers: int,
) -> dict[str, Any]:
    require_regular_file(input_manifest, "structure_manifest")
    require(sha256_file(input_manifest) == expected_manifest_sha256, "structure_manifest_sha256_mismatch")
    with input_manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
    required = {
        "schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster", "model_split",
        "asset_lane", "monomer_path", "monomer_sha256", "monomer_chain", "cdr1_range", "cdr2_range",
        "cdr3_range", "source_manifest_sha256",
    }
    require(required <= set(reader.fieldnames or []), "structure_manifest_columns_missing")
    require(len(rows) == expected_rows, f"structure_manifest_row_count_invalid:{len(rows)}")
    require(all(row["schema_version"] == INPUT_SCHEMA for row in rows), "structure_manifest_schema_invalid")
    require(len({row["candidate_id"] for row in rows}) == expected_rows, "duplicate_candidate_id")
    require(len({row["sequence_sha256"] for row in rows}) == expected_rows, "duplicate_sequence_sha256")
    require(workers >= 1, "workers_must_be_positive")

    if workers == 1:
        extracted = [_extract_one(row) for row in rows]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            extracted = list(pool.map(_extract_one, rows, chunksize=8))
    feature_names = sorted(extracted[0][1])
    require(len(feature_names) == 126, "feature_schema_count_invalid")
    output_rows: list[dict[str, str]] = []
    for row, values in extracted:
        require(sorted(values) == feature_names, f"feature_schema_drift:{row['candidate_id']}")
        output_rows.append({
            "schema_version": SCHEMA_VERSION,
            "candidate_id": row["candidate_id"],
            "sequence_sha256": row["sequence_sha256"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "model_split": row["model_split"],
            "asset_lane": row["asset_lane"],
            "monomer_sha256": row["monomer_sha256"],
            **{name: f"{values[name]:.9g}" for name in feature_names},
            "claim_boundary": CLAIM_BOUNDARY,
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "canonical10644_m2_126d_features_v1.tsv"
    fields = list(output_rows[0])
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(output_rows)
    atomic_write(output, buffer.getvalue().encode("utf-8"))
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "inputs": {"structure_manifest_sha256": expected_manifest_sha256},
        "counts": {
            "rows": len(output_rows),
            "features": len(feature_names),
            "splits": dict(sorted(Counter(row["model_split"] for row in output_rows).items())),
            "asset_lanes": dict(sorted(Counter(row["asset_lane"] for row in output_rows).items())),
        },
        "output": {"path": output.name, "sha256": sha256_file(output)},
        "invariants": {
            "legacy_m2_126d_schema": True,
            "monomer_sha256_recomputed": True,
            "all_numeric_values_finite": True,
            "geometry_label_values_read": 0,
            "candidate_docking_pose_files_opened": 0,
        },
        "feature_names": feature_names,
    }
    receipt_path = output_dir / "canonical10644_m2_126d_features_v1.receipt.json"
    atomic_write(receipt_path, (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": READY_STATUS,
        "rows": len(output_rows),
        "features": len(feature_names),
        "output_sha256": sha256_file(output),
        "receipt_sha256": sha256_file(receipt_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-rows", type=int, default=10644)
    parser.add_argument("--workers", type=int, default=max(1, min(32, os.cpu_count() or 1)))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = materialize(
        args.input_manifest, args.expected_manifest_sha256, args.output_dir, args.expected_rows, args.workers
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
