#!/usr/bin/env python3
"""Validate finite values and rotation invariance on a completed smoke panel."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from coarse_pose_features_v1 import (
    ResidueCloud, canonicalize_target, canonicalize_vhh, canonicalize_vhh_from_manifest,
    feature_vector, load_targets, parse_pdb_ca,
    pose_grid, read_manifest, sha256_file,
)


def rotation(axis, angle):
    axis = np.asarray(axis, dtype=float)
    axis /= np.linalg.norm(axis)
    x, y, z = axis
    c, s, q = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    return np.array([
        [c + x*x*q, x*y*q-z*s, x*z*q+y*s],
        [y*x*q+z*s, c+y*y*q, y*z*q-x*s],
        [z*x*q-y*s, z*y*q+x*s, c+z*z*q],
    ])


def main(args):
    feature_path = Path(args.feature_tsv).resolve()
    with feature_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    numeric_fields = [field for field in rows[0] if "__" in field]
    values = np.asarray([[float(row[field]) for field in numeric_fields] for row in rows])
    if values.shape[1] != 36 or not np.isfinite(values).all():
        raise ValueError("feature dimension/finite validation failed")

    targets = load_targets(Path(args.target_npz), Path(args.target_pdb8), Path(args.target_pdb9))
    manifest_path = Path(args.candidate_manifest).resolve()
    checks = []
    transform = rotation([1.2, -0.7, 2.1], 0.83)
    for row in read_manifest(manifest_path)[: args.rotation_candidates]:
        monomer = Path(row["monomer_pdb"])
        if not monomer.is_absolute():
            monomer = (manifest_path.parent / monomer).resolve()
        cloud = parse_pdb_ca(monomer)
        base = canonicalize_vhh_from_manifest(cloud, row)
        base_features, _ = feature_vector(base, targets, pose_grid())
        moved_cloud = ResidueCloud(
            cloud.sequence,
            cloud.residue_numbers,
            cloud.ca @ transform.T + np.array([7.3, -4.1, 2.6]),
            cloud.charges,
        )
        moved = canonicalize_vhh_from_manifest(moved_cloud, row)
        moved_features, _ = feature_vector(moved, targets, pose_grid())
        maximum_error = max(abs(base_features[key] - moved_features[key]) for key in base_features)
        checks.append({"candidate_id": row["candidate_id"], "max_abs_feature_error": maximum_error})
    max_error = max(check["max_abs_feature_error"] for check in checks)
    cache = np.load(args.target_npz, allow_pickle=False)
    target_transform = rotation([-0.4, 1.7, 0.9], -1.13)
    rotated_targets = {}
    for receptor, pdb_path in (("8x6b", args.target_pdb8), ("9e6y", args.target_pdb9)):
        cloud = parse_pdb_ca(Path(pdb_path))
        moved_cloud = ResidueCloud(
            cloud.sequence,
            cloud.residue_numbers,
            cloud.ca @ target_transform.T + np.array([-3.2, 6.8, 4.4]),
            cloud.charges,
        )
        rotated_targets[receptor] = canonicalize_target(
            moved_cloud, cache[f"{receptor}_interface_mask"], cache[f"{receptor}_hotspot_mask"]
        )
    first = read_manifest(manifest_path)[0]
    first_monomer = Path(first["monomer_pdb"])
    if not first_monomer.is_absolute():
        first_monomer = (manifest_path.parent / first_monomer).resolve()
    first_vhh = canonicalize_vhh_from_manifest(parse_pdb_ca(first_monomer), first)
    fixed_features, _ = feature_vector(first_vhh, targets, pose_grid())
    rotated_target_features, _ = feature_vector(first_vhh, rotated_targets, pose_grid())
    target_rotation_error = max(
        abs(fixed_features[key] - rotated_target_features[key]) for key in fixed_features
    )
    max_error = max(max_error, target_rotation_error)
    status = "PASS_COARSE_POSE_SMOKE_VALIDATION" if max_error <= args.rotation_tolerance else "FAIL"
    receipt = {
        "schema_version": "pvrig_v2_5_coarse_pose_smoke_validation_v1",
        "status": status,
        "candidate_count": len(rows),
        "feature_count": len(numeric_fields),
        "all_features_finite": bool(np.isfinite(values).all()),
        "rotation_tolerance": args.rotation_tolerance,
        "rotation_invariance_max_abs_error": max_error,
        "fixed_target_rotation_max_abs_error": target_rotation_error,
        "rotation_checks": checks,
        "feature_tsv": {"path": str(feature_path), "sha256": sha256_file(feature_path)},
        "claim_boundary": "Validation of label-free coarse rigid-body features only; no claim of binding, affinity, experimental blocking, or Docking equivalence.",
    }
    out = Path(args.output_json)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    if status != "PASS_COARSE_POSE_SMOKE_VALIDATION":
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature-tsv", required=True)
    parser.add_argument("--candidate-manifest", required=True)
    parser.add_argument("--target-npz", required=True)
    parser.add_argument("--target-pdb8", required=True)
    parser.add_argument("--target-pdb9", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--rotation-candidates", type=int, default=3)
    parser.add_argument("--rotation-tolerance", type=float, default=1e-8)
    main(parser.parse_args())
