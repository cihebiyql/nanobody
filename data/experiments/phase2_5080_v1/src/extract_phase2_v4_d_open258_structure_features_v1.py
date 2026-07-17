#!/usr/bin/env python3
"""Extract frozen, label-free, rigid-invariant VHH monomer descriptors."""

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
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


SCHEMA_VERSION = "phase2_v4_d_open258_structure_features_v1"
READY_STATUS = "OPEN258_LABEL_FREE_STRUCTURE_FEATURES_READY_TEST32_UNTOUCHED"
INPUT_SCHEMA = "phase2_v4_d_open258_structure_inputs_v1"
EXPECTED_MANIFEST_SHA256 = "893556640293d15a240158d487c8607a4326b55dd7af5ece46aeb4f3890bf03c"
EXPECTED_COUNTS = {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32}
EXPECTED_ROWS = 258
REGIONS = ("ALL", "FRAMEWORK", "CDR1", "CDR2", "CDR3", "CDR_ALL")
REGION_FEATURES = (
    "residue_count",
    "confidence_mean",
    "confidence_std",
    "confidence_min",
    "confidence_q10",
    "ca_radius_of_gyration",
    "ca_pair_distance_q10",
    "ca_pair_distance_q25",
    "ca_pair_distance_q50",
    "ca_pair_distance_q75",
    "ca_pair_distance_q90",
    "ca_pair_distance_max",
    "ca_path_length",
    "ca_end_to_end_distance",
    "ca_tortuosity",
    "nonlocal_ca_contact_density_8A",
    "shape_eigenvalue_1_fraction",
    "shape_eigenvalue_2_fraction",
    "shape_eigenvalue_3_fraction",
)
CDR_NAMES = ("CDR1", "CDR2", "CDR3")
CLAIM_BOUNDARY = (
    "Label-free rigid-invariant descriptors from frozen VHH monomer inputs; no "
    "docked complex, pose score, geometry label, or experimental truth."
)


class FeatureError(RuntimeError):
    """Fail-closed feature extraction error."""


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
    require(stat.S_ISREG(metadata.st_mode), f"not_regular_or_symlink:{label}:{path}")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
                xyz = np.asarray([float(line[30:38]), float(line[38:46]), float(line[46:54])], dtype=np.float64)
                confidence = float(line[60:66])
            except ValueError as exc:
                raise FeatureError(f"invalid_ca_numeric:{path}:{line_number}") from exc
            require(residue not in seen, f"duplicate_ca_residue:{path}:{residue}")
            require(np.isfinite(xyz).all() and math.isfinite(confidence), f"nonfinite_ca_record:{path}:{line_number}")
            seen.add(residue)
            records.append((residue, xyz, confidence))
    require(len(records) >= 80, f"too_few_ca_records:{path}:{len(records)}")
    records.sort(key=lambda item: item[0])
    residues = np.asarray([item[0] for item in records], dtype=np.int64)
    coordinates = np.stack([item[1] for item in records])
    confidence = np.asarray([item[2] for item in records], dtype=np.float64)
    return residues, coordinates, confidence


def pair_distances(coordinates: np.ndarray) -> np.ndarray:
    if len(coordinates) < 2:
        return np.asarray([], dtype=np.float64)
    delta = coordinates[:, None, :] - coordinates[None, :, :]
    distance = np.sqrt(np.sum(delta * delta, axis=2))
    return distance[np.triu_indices(len(coordinates), k=1)]


def region_descriptors(residues: np.ndarray, coordinates: np.ndarray, confidence: np.ndarray) -> dict[str, float]:
    require(len(residues) == len(coordinates) == len(confidence) and len(residues) > 0, "empty_region")
    centered = coordinates - coordinates.mean(axis=0, keepdims=True)
    radius = float(np.sqrt(np.mean(np.sum(centered * centered, axis=1))))
    distances = pair_distances(coordinates)
    require(len(distances) > 0, "region_without_pair_distances")
    quantiles = np.quantile(distances, [0.10, 0.25, 0.50, 0.75, 0.90])
    order = np.argsort(residues)
    ordered_coordinates = coordinates[order]
    steps = np.linalg.norm(np.diff(ordered_coordinates, axis=0), axis=1)
    path_length = float(steps.sum())
    end_to_end = float(np.linalg.norm(ordered_coordinates[-1] - ordered_coordinates[0]))
    tortuosity = path_length / max(end_to_end, 1e-6)
    delta = coordinates[:, None, :] - coordinates[None, :, :]
    matrix = np.sqrt(np.sum(delta * delta, axis=2))
    sequence_separation = np.abs(residues[:, None] - residues[None, :])
    eligible = np.triu(sequence_separation > 2, k=1)
    eligible_count = int(eligible.sum())
    contact_density = float(((matrix < 8.0) & eligible).sum() / eligible_count) if eligible_count else 0.0
    covariance = centered.T @ centered / float(len(coordinates))
    eigenvalues = np.linalg.eigvalsh(covariance)[::-1]
    eigenvalues = np.maximum(eigenvalues, 0.0)
    eigen_sum = float(eigenvalues.sum())
    eigen_fraction = eigenvalues / eigen_sum if eigen_sum > 0 else np.asarray([1.0, 0.0, 0.0])
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
        "ca_tortuosity": float(tortuosity),
        "nonlocal_ca_contact_density_8A": contact_density,
        "shape_eigenvalue_1_fraction": float(eigen_fraction[0]),
        "shape_eigenvalue_2_fraction": float(eigen_fraction[1]),
        "shape_eigenvalue_3_fraction": float(eigen_fraction[2]),
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
        mask = masks[region]
        values = region_descriptors(residues[mask], coordinates[mask], confidence[mask])
        output.update({f"{region}__{name}": value for name, value in values.items()})
    centroids = {name: coordinates[masks[name]].mean(axis=0) for name in (*CDR_NAMES, "FRAMEWORK")}
    for left, right in (("CDR1", "CDR2"), ("CDR1", "CDR3"), ("CDR2", "CDR3")):
        output[f"{left}_{right}__centroid_distance"] = float(np.linalg.norm(centroids[left] - centroids[right]))
    framework_coordinates = coordinates[masks["FRAMEWORK"]]
    for name in CDR_NAMES:
        cdr_coordinates = coordinates[masks[name]]
        distances = np.linalg.norm(cdr_coordinates[:, None, :] - framework_coordinates[None, :, :], axis=2)
        output[f"{name}_FRAMEWORK__centroid_distance"] = float(np.linalg.norm(centroids[name] - centroids["FRAMEWORK"]))
        output[f"{name}_FRAMEWORK__minimum_ca_distance"] = float(np.min(distances))
        output[f"{name}_FRAMEWORK__median_minimum_ca_distance"] = float(np.median(np.min(distances, axis=1)))
    require(len(output) == len(REGIONS) * len(REGION_FEATURES) + 12, f"feature_count_invalid:{len(output)}")
    require(all(math.isfinite(value) for value in output.values()), "nonfinite_structure_feature")
    return output


def extract(input_root: Path, output_dir: Path, expected_manifest_sha256: str = EXPECTED_MANIFEST_SHA256) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_exists:{output_dir}")
    manifest = input_root / "outputs/open258_structure_manifest_v1.tsv"
    audit_path = input_root / "outputs/open258_structure_input_audit_v1.json"
    require_regular_file(manifest, "input_manifest")
    require_regular_file(audit_path, "input_audit")
    require(sha256_file(manifest) == expected_manifest_sha256, "input_manifest_sha256_mismatch")
    input_audit = json.loads(audit_path.read_text(encoding="utf-8"))
    require(input_audit.get("status") == "OPEN258_LABEL_FREE_FROZEN_MONOMERS_READY_TEST32_UNTOUCHED", "input_audit_status_invalid")
    sealed = input_audit.get("sealed_boundary") or {}
    require(sealed.get("sealed_monomer_files_opened") == 0, "input_sealed_monomers_opened")
    require(sealed.get("geometry_label_values_read") == 0, "input_geometry_labels_read")
    with manifest.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        manifest_rows = list(reader)
    require(len(manifest_rows) == EXPECTED_ROWS, f"input_row_count_invalid:{len(manifest_rows)}")
    require(Counter(row["model_split"] for row in manifest_rows) == Counter(EXPECTED_COUNTS), "input_split_counts_invalid")
    feature_rows: list[dict[str, Any]] = []
    feature_names: list[str] | None = None
    for row in manifest_rows:
        require(row["schema_version"] == INPUT_SCHEMA, f"input_schema_invalid:{row['candidate_id']}")
        pdb = input_root / row["bundle_relative_path"]
        require(sha256_file(pdb) == row["monomer_sha256"], f"pdb_sha256_mismatch:{row['candidate_id']}")
        values = structure_features(
            pdb,
            row["monomer_source_chain"],
            {"CDR1": row["cdr1_range"], "CDR2": row["cdr2_range"], "CDR3": row["cdr3_range"]},
        )
        if feature_names is None:
            feature_names = sorted(values)
        require(sorted(values) == feature_names, f"feature_schema_drift:{row['candidate_id']}")
        feature_rows.append({
            "schema_version": SCHEMA_VERSION,
            "candidate_id": row["candidate_id"],
            "sequence_sha256": row["sequence_sha256"],
            "model_split": row["model_split"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "monomer_sha256": row["monomer_sha256"],
            **{name: f"{values[name]:.9g}" for name in feature_names},
            "claim_boundary": CLAIM_BOUNDARY,
        })
    require(feature_names is not None and len(feature_names) == 126, "feature_schema_not_initialized")
    output_dir.mkdir(parents=True)
    output = output_dir / "open258_structure_features_v1.tsv"
    fields = [
        "schema_version", "candidate_id", "sequence_sha256", "model_split",
        "parent_framework_cluster", "monomer_sha256", *feature_names, "claim_boundary",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(feature_rows)
    atomic_write(output, buffer.getvalue().encode("utf-8"))
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "inputs": {
            "structure_manifest_sha256": sha256_file(manifest),
            "structure_input_audit_sha256": sha256_file(audit_path),
            "candidate_count": len(manifest_rows),
        },
        "output": {
            "path": output.name,
            "sha256": sha256_file(output),
            "row_count": len(feature_rows),
            "split_counts": dict(sorted(Counter(row["model_split"] for row in feature_rows).items())),
            "feature_count": len(feature_names),
            "feature_names": feature_names,
            "all_numeric_values_finite": True,
        },
        "sealed_boundary": {
            "prospective_test_rows_emitted": 0,
            "prospective_test_labels_accessed": 0,
            "docking_result_files_opened": 0,
            "pose_files_opened": 0,
            "geometry_label_values_read": 0,
        },
    }
    audit_output = output.with_suffix(output.suffix + ".audit.json")
    atomic_write(audit_output, (json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "feature_table_sha256": sha256_file(output),
        "feature_audit_sha256": sha256_file(audit_output),
        "row_count": EXPECTED_ROWS,
        "feature_count": len(feature_names),
        "geometry_label_values_read": 0,
        "prospective_test_labels_accessed": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    receipt_path = output_dir / "open258_structure_features_v1.receipt.json"
    atomic_write(receipt_path, (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": READY_STATUS,
        "row_count": EXPECTED_ROWS,
        "feature_count": len(feature_names),
        "feature_table_sha256": sha256_file(output),
        "feature_audit_sha256": sha256_file(audit_output),
        "receipt_sha256": sha256_file(receipt_path),
        "geometry_label_values_read": 0,
        "prospective_test_labels_accessed": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", default=EXPECTED_MANIFEST_SHA256)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = extract(args.input_root, args.output_dir, args.expected_manifest_sha256)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
