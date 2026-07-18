#!/usr/bin/env python3
"""Label-free coarse rigid-body pose features for VHH/PVRIG monomers.

This module deliberately consumes only a candidate VHH monomer, CDR sequence
annotations, fixed public PVRIG monomers and fixed interface/hotspot masks.  It
does not read candidate docking poses or teacher labels.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np


AA3 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}
CHARGE = {"D": -1.0, "E": -1.0, "K": 1.0, "R": 1.0, "H": 0.1}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class ResidueCloud:
    sequence: str
    residue_numbers: np.ndarray
    ca: np.ndarray
    charges: np.ndarray


def parse_pdb_ca(path: Path, chain: str | None = None) -> ResidueCloud:
    """Parse one CA per standard residue from a PDB file."""
    residues: Dict[Tuple[str, int, str], Tuple[str, np.ndarray]] = {}
    with path.open() as handle:
        for line in handle:
            if not line.startswith("ATOM") or line[12:16].strip() != "CA":
                continue
            atom_chain = line[21].strip() or "_"
            if chain and atom_chain != chain:
                continue
            resname = line[17:20].strip()
            if resname not in AA3:
                continue
            key = (atom_chain, int(line[22:26]), line[26].strip())
            coord = np.array(
                [float(line[30:38]), float(line[38:46]), float(line[46:54])],
                dtype=np.float64,
            )
            residues.setdefault(key, (AA3[resname], coord))
    if not residues:
        raise ValueError(f"no CA atoms parsed: {path}")
    ordered = list(residues.items())
    seq = "".join(value[0] for _, value in ordered)
    nums = np.asarray([key[1] for key, _ in ordered], dtype=np.int64)
    coords = np.stack([value[1] for _, value in ordered])
    charges = np.asarray([CHARGE.get(value[0], 0.0) for _, value in ordered])
    return ResidueCloud(seq, nums, coords, charges)


def _unit(vector: np.ndarray, eps: float = 1e-10) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm < eps:
        raise ValueError("cannot normalize a near-zero vector")
    return vector / norm


def _project(vector: np.ndarray, normal: np.ndarray) -> np.ndarray:
    return vector - float(np.dot(vector, normal)) * normal


def _stable_transverse_axis(
    points: np.ndarray,
    origin: np.ndarray,
    z_axis: np.ndarray,
    anchors: Iterable[np.ndarray],
) -> np.ndarray:
    for anchor in anchors:
        projected = _project(np.asarray(anchor) - origin, z_axis)
        if np.linalg.norm(projected) > 1e-7:
            return _unit(projected)
    centered = points - points.mean(axis=0)
    covariance = centered.T @ centered
    _, vectors = np.linalg.eigh(covariance)
    for index in (2, 1, 0):
        projected = _project(vectors[:, index], z_axis)
        if np.linalg.norm(projected) > 1e-7:
            axis = _unit(projected)
            reference = points[0] - origin
            if np.dot(axis, reference) < 0:
                axis = -axis
            return axis
    raise ValueError("failed to construct a stable transverse axis")


def _find_unique_subsequence(sequence: str, subsequence: str, label: str) -> np.ndarray:
    starts: List[int] = []
    start = sequence.find(subsequence)
    while start >= 0:
        starts.append(start)
        start = sequence.find(subsequence, start + 1)
    if len(starts) != 1:
        raise ValueError(f"{label} must map uniquely; found {len(starts)} occurrences")
    return np.arange(starts[0], starts[0] + len(subsequence), dtype=np.int64)


@dataclass(frozen=True)
class CanonicalVHH:
    coords: np.ndarray
    charges: np.ndarray
    cdr_indices: np.ndarray
    cdr3_indices: np.ndarray
    cdr3_direction: np.ndarray


def canonicalize_vhh(
    cloud: ResidueCloud, cdr1: str, cdr2: str, cdr3: str
) -> CanonicalVHH:
    idx1 = _find_unique_subsequence(cloud.sequence, cdr1, "CDR1")
    idx2 = _find_unique_subsequence(cloud.sequence, cdr2, "CDR2")
    idx3 = _find_unique_subsequence(cloud.sequence, cdr3, "CDR3")
    return canonicalize_vhh_indices(cloud, idx1, idx2, idx3)


def canonicalize_vhh_indices(
    cloud: ResidueCloud, idx1: np.ndarray, idx2: np.ndarray, idx3: np.ndarray
) -> CanonicalVHH:
    for label, indices in (("CDR1", idx1), ("CDR2", idx2), ("CDR3", idx3)):
        indices = np.asarray(indices, dtype=np.int64)
        if len(indices) == 0 or indices.min() < 0 or indices.max() >= len(cloud.sequence):
            raise ValueError(f"{label} indices are invalid for sequence length {len(cloud.sequence)}")
    cdr_idx = np.unique(np.concatenate([idx1, idx2, idx3]))
    framework_idx = np.setdiff1d(np.arange(len(cloud.sequence)), cdr_idx)
    cdr_center = cloud.ca[cdr_idx].mean(axis=0)
    framework_center = cloud.ca[framework_idx].mean(axis=0)
    z_axis = _unit(cdr_center - framework_center)
    cdr3_center = cloud.ca[idx3].mean(axis=0)
    x_axis = _stable_transverse_axis(
        cloud.ca,
        cdr_center,
        z_axis,
        (cdr3_center, cloud.ca[idx3[-1]], cloud.ca[-1]),
    )
    y_axis = _unit(np.cross(z_axis, x_axis))
    x_axis = _unit(np.cross(y_axis, z_axis))
    basis = np.stack([x_axis, y_axis, z_axis], axis=1)
    canonical = (cloud.ca - cdr_center) @ basis
    framework_center_c = canonical[framework_idx].mean(axis=0)
    cdr3_direction = _unit(canonical[idx3].mean(axis=0) - framework_center_c)
    return CanonicalVHH(canonical, cloud.charges.copy(), cdr_idx, idx3, cdr3_direction)


@dataclass(frozen=True)
class CanonicalTarget:
    coords: np.ndarray
    charges: np.ndarray
    interface_indices: np.ndarray
    hotspot_indices: np.ndarray


def canonicalize_target(
    cloud: ResidueCloud, interface_mask: np.ndarray, hotspot_mask: np.ndarray
) -> CanonicalTarget:
    if len(cloud.sequence) != len(interface_mask) or len(cloud.sequence) != len(hotspot_mask):
        raise ValueError("target PDB/mask residue counts do not match")
    interface_idx = np.flatnonzero(interface_mask)
    hotspot_idx = np.flatnonzero(hotspot_mask)
    if len(interface_idx) == 0 or len(hotspot_idx) == 0:
        raise ValueError("target interface/hotspot mask cannot be empty")
    center = cloud.ca.mean(axis=0)
    interface_center = cloud.ca[interface_idx].mean(axis=0)
    z_axis = _unit(interface_center - center)
    hotspot_center = cloud.ca[hotspot_idx].mean(axis=0)
    x_axis = _stable_transverse_axis(
        cloud.ca[interface_idx],
        interface_center,
        z_axis,
        (hotspot_center, cloud.ca[interface_idx[0]], cloud.ca[interface_idx[-1]]),
    )
    y_axis = _unit(np.cross(z_axis, x_axis))
    x_axis = _unit(np.cross(y_axis, z_axis))
    basis = np.stack([x_axis, y_axis, z_axis], axis=1)
    canonical = (cloud.ca - interface_center) @ basis
    return CanonicalTarget(canonical, cloud.charges.copy(), interface_idx, hotspot_idx)


@dataclass(frozen=True)
class PoseParameters:
    pose_id: int
    direction: np.ndarray
    roll_radians: float
    offset: float


def pose_grid() -> List[PoseParameters]:
    """Fixed 300-pose label-free grid: 25 approach axes x 4 rolls x 3 offsets."""
    axes: List[np.ndarray] = []
    for angle_degrees, azimuth_count in ((0.0, 1), (20.0, 6), (40.0, 8), (60.0, 10)):
        theta = math.radians(angle_degrees)
        for index in range(azimuth_count):
            phi = 2.0 * math.pi * index / azimuth_count
            axes.append(
                np.array(
                    [math.sin(theta) * math.cos(phi), math.sin(theta) * math.sin(phi), -math.cos(theta)],
                    dtype=np.float64,
                )
            )
    poses: List[PoseParameters] = []
    pose_id = 0
    for direction in axes:
        for roll in (0.0, 0.5 * math.pi, math.pi, 1.5 * math.pi):
            for offset in (5.0, 6.5, 8.0):
                poses.append(PoseParameters(pose_id, direction, roll, offset))
                pose_id += 1
    return poses


def _orientation_matrix(direction: np.ndarray, roll: float) -> np.ndarray:
    direction = _unit(direction)
    reference = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(reference, direction))) > 0.9:
        reference = np.array([0.0, 1.0, 0.0])
    x0 = _unit(_project(reference, direction))
    y0 = _unit(np.cross(direction, x0))
    x_axis = math.cos(roll) * x0 + math.sin(roll) * y0
    y_axis = -math.sin(roll) * x0 + math.cos(roll) * y0
    return np.stack([x_axis, y_axis, direction], axis=1)


def _pairwise_min_distance(query: np.ndarray, reference: np.ndarray) -> np.ndarray:
    squared = np.sum((query[:, None, :] - reference[None, :, :]) ** 2, axis=2)
    return np.sqrt(np.maximum(squared.min(axis=1), 0.0))


POSE_FIELDS = (
    "composite", "shape", "hotspot", "charge", "clash_fraction",
    "cdr_contact_fraction", "cdr3_orientation",
)


def score_pose(vhh: CanonicalVHH, target: CanonicalTarget, pose: PoseParameters) -> Dict[str, float]:
    rotation = _orientation_matrix(pose.direction, pose.roll_radians)
    translation = np.array([0.0, 0.0, pose.offset])
    positioned = vhh.coords @ rotation.T + translation
    cdr = positioned[vhh.cdr_indices]
    cdr3 = positioned[vhh.cdr3_indices]
    target_interface = target.coords[target.interface_indices]
    target_hotspot = target.coords[target.hotspot_indices]

    all_min = _pairwise_min_distance(positioned, target.coords)
    cdr_interface_min = _pairwise_min_distance(cdr, target_interface)
    hotspot_cdr_min = _pairwise_min_distance(target_hotspot, cdr)
    shape = float(np.mean(np.exp(-((cdr_interface_min - 6.0) / 2.5) ** 2)))
    hotspot = float(np.mean(np.exp(-((hotspot_cdr_min - 5.5) / 3.0) ** 2)))
    clash_fraction = float(np.mean(all_min < 3.25))
    cdr_contact_fraction = float(np.mean(cdr_interface_min < 9.0))

    v_charge_idx = np.flatnonzero(np.abs(vhh.charges) > 0)
    t_charge_idx = np.flatnonzero(np.abs(target.charges) > 0)
    charge = 0.0
    if len(v_charge_idx) and len(t_charge_idx):
        distances = np.linalg.norm(
            positioned[v_charge_idx, None, :] - target.coords[t_charge_idx][None, :, :], axis=2
        )
        kernels = np.exp(-distances / 6.0) * (distances < 14.0)
        products = -vhh.charges[v_charge_idx, None] * target.charges[t_charge_idx][None, :]
        charge = float(np.sum(kernels * products) / math.sqrt(len(v_charge_idx) * len(t_charge_idx)))
        charge = float(np.tanh(charge))

    transformed_cdr3_direction = vhh.cdr3_direction @ rotation.T
    cdr3_orientation = float(np.dot(_unit(transformed_cdr3_direction), np.array([0.0, 0.0, -1.0])))
    composite = (
        0.40 * shape
        + 0.32 * hotspot
        + 0.13 * cdr_contact_fraction
        + 0.10 * ((charge + 1.0) / 2.0)
        + 0.05 * ((cdr3_orientation + 1.0) / 2.0)
        - 0.70 * clash_fraction
    )
    return {
        "pose_id": float(pose.pose_id),
        "composite": float(composite),
        "shape": shape,
        "hotspot": hotspot,
        "charge": charge,
        "clash_fraction": clash_fraction,
        "cdr_contact_fraction": cdr_contact_fraction,
        "cdr3_orientation": cdr3_orientation,
    }


def scan_receptor(vhh: CanonicalVHH, target: CanonicalTarget, poses: Sequence[PoseParameters]) -> List[Dict[str, float]]:
    return [score_pose(vhh, target, pose) for pose in poses]


def _quantile(values: np.ndarray, probability: float) -> float:
    return float(np.quantile(values, probability))


def aggregate_receptor(prefix: str, rows: Sequence[Mapping[str, float]], top_k: int = 20) -> Dict[str, float]:
    composite = np.asarray([row["composite"] for row in rows], dtype=np.float64)
    ordering = np.argsort(composite)[::-1]
    top = ordering[: min(top_k, len(ordering))]
    best = rows[int(ordering[0])]
    acceptable = np.asarray(
        [
            row["shape"] >= 0.22
            and row["hotspot"] >= 0.22
            and row["clash_fraction"] <= 0.08
            and row["composite"] >= 0.22
            for row in rows
        ],
        dtype=bool,
    )
    top_values = composite[top]
    weights = np.exp(top_values - top_values.max())
    weights /= weights.sum()
    entropy = float(-np.sum(weights * np.log(np.clip(weights, 1e-12, None))))
    return {
        f"{prefix}__pose_count": float(len(rows)),
        f"{prefix}__acceptable_count": float(acceptable.sum()),
        f"{prefix}__acceptable_fraction": float(acceptable.mean()),
        f"{prefix}__best_composite": float(best["composite"]),
        f"{prefix}__top20_composite_mean": float(top_values.mean()),
        f"{prefix}__top20_composite_std": float(top_values.std()),
        f"{prefix}__top20_composite_iqr": _quantile(top_values, 0.75) - _quantile(top_values, 0.25),
        f"{prefix}__top20_score_entropy": entropy,
        f"{prefix}__best_shape": float(best["shape"]),
        f"{prefix}__best_hotspot": float(best["hotspot"]),
        f"{prefix}__best_charge": float(best["charge"]),
        f"{prefix}__best_clash_fraction": float(best["clash_fraction"]),
        f"{prefix}__best_cdr_contact_fraction": float(best["cdr_contact_fraction"]),
        f"{prefix}__best_cdr3_orientation": float(best["cdr3_orientation"]),
    }


def aggregate_dual(
    rows8: Sequence[Mapping[str, float]], rows9: Sequence[Mapping[str, float]]
) -> Dict[str, float]:
    c8 = np.asarray([row["composite"] for row in rows8], dtype=np.float64)
    c9 = np.asarray([row["composite"] for row in rows9], dtype=np.float64)
    a8 = np.asarray([
        row["shape"] >= 0.22 and row["hotspot"] >= 0.22 and row["clash_fraction"] <= 0.08 and row["composite"] >= 0.22
        for row in rows8
    ])
    a9 = np.asarray([
        row["shape"] >= 0.22 and row["hotspot"] >= 0.22 and row["clash_fraction"] <= 0.08 and row["composite"] >= 0.22
        for row in rows9
    ])
    common = a8 & a9
    union = a8 | a9
    paired_min = np.minimum(c8, c9)
    top = np.argsort(paired_min)[::-1][:20]
    corr = float(np.corrcoef(c8, c9)[0, 1]) if np.std(c8) > 0 and np.std(c9) > 0 else 0.0
    return {
        "dual__common_acceptable_count": float(common.sum()),
        "dual__common_acceptable_fraction": float(common.mean()),
        "dual__acceptable_jaccard": float(common.sum() / union.sum()) if union.any() else 0.0,
        "dual__best_min_composite": float(paired_min.max()),
        "dual__top20_min_composite_mean": float(paired_min[top].mean()),
        "dual__top20_min_composite_std": float(paired_min[top].std()),
        "dual__best_receptor_gap": float(abs(c8[np.argmax(paired_min)] - c9[np.argmax(paired_min)])),
        "dual__pose_score_correlation": corr,
    }


def feature_vector(
    vhh: CanonicalVHH,
    targets: Mapping[str, CanonicalTarget],
    poses: Sequence[PoseParameters] | None = None,
) -> Tuple[Dict[str, float], Dict[str, List[Dict[str, float]]]]:
    poses = list(poses or pose_grid())
    scans = {name: scan_receptor(vhh, target, poses) for name, target in targets.items()}
    if set(scans) != {"8x6b", "9e6y"}:
        raise ValueError("exactly 8x6b and 9e6y targets are required")
    features: Dict[str, float] = {}
    features.update(aggregate_receptor("8x6b", scans["8x6b"]))
    features.update(aggregate_receptor("9e6y", scans["9e6y"]))
    features.update(aggregate_dual(scans["8x6b"], scans["9e6y"]))
    if len(features) != 36:
        raise AssertionError(f"expected 36 features, got {len(features)}")
    if not np.isfinite(np.asarray(list(features.values()), dtype=float)).all():
        raise ValueError("non-finite coarse pose feature detected")
    return features, scans


def load_targets(target_npz: Path, target_pdb8: Path, target_pdb9: Path) -> Dict[str, CanonicalTarget]:
    cache = np.load(target_npz, allow_pickle=False)
    target8 = canonicalize_target(
        parse_pdb_ca(target_pdb8), cache["8x6b_interface_mask"], cache["8x6b_hotspot_mask"]
    )
    target9 = canonicalize_target(
        parse_pdb_ca(target_pdb9), cache["9e6y_interface_mask"], cache["9e6y_hotspot_mask"]
    )
    return {"8x6b": target8, "9e6y": target9}


def read_manifest(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    required = {"candidate_id", "monomer_pdb", "monomer_sha256"}
    cdr_sequences = {"cdr1", "cdr2", "cdr3"}
    cdr_ranges = {"cdr1_range", "cdr2_range", "cdr3_range"}
    if not rows or not required.issubset(rows[0]) or not (
        cdr_sequences.issubset(rows[0]) or cdr_ranges.issubset(rows[0])
    ):
        raise ValueError("manifest requires monomer closure plus CDR sequences or 1-based inclusive CDR ranges")
    return rows


def _parse_one_based_inclusive_range(text: str, sequence_length: int, label: str) -> np.ndarray:
    parts = text.split("-")
    if len(parts) != 2:
        raise ValueError(f"invalid {label} range: {text}")
    start, end = (int(part) for part in parts)
    if start < 1 or end < start or end > sequence_length:
        raise ValueError(f"out-of-bounds {label} range: {text}")
    return np.arange(start - 1, end, dtype=np.int64)


def canonicalize_vhh_from_manifest(cloud: ResidueCloud, row: Mapping[str, str]) -> CanonicalVHH:
    if all(row.get(field, "") for field in ("cdr1", "cdr2", "cdr3")):
        return canonicalize_vhh(cloud, row["cdr1"], row["cdr2"], row["cdr3"])
    indices = [
        _parse_one_based_inclusive_range(row[f"cdr{number}_range"], len(cloud.sequence), f"CDR{number}")
        for number in (1, 2, 3)
    ]
    return canonicalize_vhh_indices(cloud, *indices)


def run(args: argparse.Namespace) -> None:
    started = time.perf_counter()
    manifest_path = Path(args.candidate_manifest).resolve()
    targets = load_targets(Path(args.target_npz), Path(args.target_pdb8), Path(args.target_pdb9))
    poses = pose_grid()
    output_rows: List[Dict[str, object]] = []
    per_candidate_seconds: List[float] = []
    for row in read_manifest(manifest_path):
        candidate_started = time.perf_counter()
        monomer = Path(row["monomer_pdb"])
        if not monomer.is_absolute():
            monomer = (manifest_path.parent / monomer).resolve()
        if sha256_file(monomer) != row["monomer_sha256"]:
            raise ValueError(f"monomer hash mismatch: {row['candidate_id']}")
        vhh = canonicalize_vhh_from_manifest(parse_pdb_ca(monomer), row)
        features, _ = feature_vector(vhh, targets, poses)
        elapsed = time.perf_counter() - candidate_started
        per_candidate_seconds.append(elapsed)
        output_rows.append(
            {
                "candidate_id": row["candidate_id"],
                "monomer_sha256": row["monomer_sha256"],
                "feature_schema": "pvrig_v2_5_label_free_coarse_pose_36d_v1",
                **features,
            }
        )

    output_path = Path(args.output_tsv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)
    receipt = {
        "schema_version": "pvrig_v2_5_label_free_coarse_pose_pilot_v1",
        "status": "PASS_LABEL_FREE_COARSE_POSE_FEATURES",
        "claim_boundary": "Label-free coarse rigid-body geometry from candidate VHH monomers and fixed public PVRIG structures only; not Docking, binding, affinity, competition, experimental blocking, or Docking Gold.",
        "candidate_count": len(output_rows),
        "feature_count": 36,
        "pose_count_per_receptor": len(poses),
        "runtime_seconds": time.perf_counter() - started,
        "candidate_runtime_seconds_mean": float(np.mean(per_candidate_seconds)),
        "candidate_runtime_seconds_max": float(np.max(per_candidate_seconds)),
        "all_features_finite": True,
        "sealed_boundary": {
            "candidate_docking_pose_files_opened": 0,
            "teacher_label_files_opened": 0,
            "v4_f_files_opened": 0,
        },
        "inputs": {
            "candidate_manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
            "target_npz": {"path": str(Path(args.target_npz).resolve()), "sha256": sha256_file(Path(args.target_npz))},
            "target_pdb8": {"path": str(Path(args.target_pdb8).resolve()), "sha256": sha256_file(Path(args.target_pdb8))},
            "target_pdb9": {"path": str(Path(args.target_pdb9).resolve()), "sha256": sha256_file(Path(args.target_pdb9))},
        },
        "outputs": {str(output_path): sha256_file(output_path)},
    }
    receipt_path = Path(args.receipt_json)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-manifest", required=True)
    parser.add_argument("--target-npz", required=True)
    parser.add_argument("--target-pdb8", required=True)
    parser.add_argument("--target-pdb9", required=True)
    parser.add_argument("--output-tsv", required=True)
    parser.add_argument("--receipt-json", required=True)
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
