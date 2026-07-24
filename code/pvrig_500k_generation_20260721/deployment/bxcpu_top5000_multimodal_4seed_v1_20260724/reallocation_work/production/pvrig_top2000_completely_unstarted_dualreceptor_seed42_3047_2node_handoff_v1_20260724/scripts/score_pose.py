#!/usr/bin/env python3
"""Score PVRIG VHH poses against normalized PVRIG/PVRL2 references."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from common import is_standard_atom_line, project_root, read_json, write_json

REFERENCE_IDS = ("8x6b", "9e6y")
HOTSPOT_SUMMARY = Path("reports/reference_normalization_summary.json")
CONTACT_CUTOFF = 4.5
CLASH_CUTOFF = 2.5


@dataclass(frozen=True)
class Atom:
    serial: int
    name: str
    resname: str
    chain: str
    resseq: int
    icode: str
    x: float
    y: float
    z: float

    @property
    def residue_id(self) -> str:
        suffix = self.icode.strip()
        return f"{self.chain}:{self.resseq}{suffix}:{self.resname}"

    @property
    def atom_id(self) -> str:
        suffix = self.icode.strip()
        return f"{self.chain}:{self.resseq}{suffix}:{self.resname}:{self.name}:{self.serial}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pose", type=Path, help="Pose PDB or PDB.GZ")
    parser.add_argument("--root", type=Path, default=project_root(), help="Project root")
    parser.add_argument("--reference", choices=REFERENCE_IDS, action="append", help="Reference id to score; default both")
    parser.add_argument("--io-json", type=Path, help="Optional HADDOCK io.json to parse")
    parser.add_argument("--vhh-chain", default="A", help="VHH chain in the docked pose, default A")
    parser.add_argument("--cdr1", default="26-35", help="1-based PDB residue range(s), e.g. 27-33")
    parser.add_argument("--cdr2", default="50-65", help="1-based PDB residue range(s)")
    parser.add_argument("--cdr3", default="95-117", help="1-based PDB residue range(s)")
    parser.add_argument("--out", type=Path, help="Optional JSON output path")
    return parser.parse_args()


def open_text(path: Path) -> Iterable[str]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            yield from handle
    else:
        with path.open(encoding="utf-8", errors="replace") as handle:
            yield from handle


def parse_pdb(path: Path) -> list[Atom]:
    atoms: list[Atom] = []
    for line in open_text(path):
        if not is_standard_atom_line(line):
            continue
        element = line[76:78].strip().upper() if len(line) >= 78 else ""
        if not element:
            element = "".join(ch for ch in line[12:16] if ch.isalpha())[:1].upper()
        if element in {"H", "D"}:
            continue
        try:
            atoms.append(
                Atom(
                    serial=int(line[6:11]),
                    name=line[12:16].strip(),
                    resname=line[17:20].strip().upper(),
                    chain=line[21],
                    resseq=int(line[22:26]),
                    icode=line[26],
                    x=float(line[30:38]),
                    y=float(line[38:46]),
                    z=float(line[46:54]),
                )
            )
        except ValueError as exc:
            raise ValueError(f"invalid PDB atom line in {path}: {line.rstrip()}") from exc
    if not atoms:
        raise ValueError(f"no standard amino-acid ATOM records in {path}")
    return atoms


def ca_by_t_residue(atoms: list[Atom]) -> dict[int, tuple[float, float, float]]:
    return {atom.resseq: (atom.x, atom.y, atom.z) for atom in atoms if atom.chain == "T" and atom.name == "CA"}


def kabsch_transform(
    moving: list[tuple[float, float, float]], fixed: list[tuple[float, float, float]]
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    if len(moving) != len(fixed) or len(moving) < 3:
        raise ValueError("Kabsch overlay requires at least three paired CA atoms")
    moving_array = np.asarray(moving, dtype=float)
    fixed_array = np.asarray(fixed, dtype=float)
    cm = moving_array.mean(axis=0)
    cf = fixed_array.mean(axis=0)
    covariance = (moving_array - cm).T @ (fixed_array - cf)
    u, _singular_values, vt = np.linalg.svd(covariance)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1, :] *= -1
        rotation = vt.T @ u.T
    transformed = (rotation @ (moving_array - cm).T).T + cf
    rmsd = float(np.sqrt(np.mean(np.sum((transformed - fixed_array) ** 2, axis=1))))
    return rotation, cm, cf, rmsd


def apply_transform_point(
    point: tuple[float, float, float],
    rotation: np.ndarray,
    moving_centroid: np.ndarray,
    fixed_centroid: np.ndarray,
) -> tuple[float, float, float]:
    transformed = rotation @ (np.asarray(point, dtype=float) - moving_centroid) + fixed_centroid
    return float(transformed[0]), float(transformed[1]), float(transformed[2])


def transform_atoms(
    atoms: list[Atom], rotation: np.ndarray, moving_centroid: np.ndarray, fixed_centroid: np.ndarray
) -> list[Atom]:
    transformed: list[Atom] = []
    for atom in atoms:
        x, y, z = apply_transform_point((atom.x, atom.y, atom.z), rotation, moving_centroid, fixed_centroid)
        transformed.append(Atom(atom.serial, atom.name, atom.resname, atom.chain, atom.resseq, atom.icode, x, y, z))
    return transformed


def squared_distance(a: Atom, b: Atom) -> float:
    return (a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2


def residues_with_contacts(query: list[Atom], target: list[Atom], cutoff: float) -> tuple[set[str], set[str], set[tuple[str, str]]]:
    cutoff2 = cutoff * cutoff
    query_residues: set[str] = set()
    target_residues: set[str] = set()
    residue_pairs: set[tuple[str, str]] = set()
    target_xyz = np.asarray([(atom.x, atom.y, atom.z) for atom in target], dtype=float)
    for start in range(0, len(query), 256):
        query_chunk = query[start : start + 256]
        query_xyz = np.asarray([(atom.x, atom.y, atom.z) for atom in query_chunk], dtype=float)
        distances2 = np.sum((query_xyz[:, None, :] - target_xyz[None, :, :]) ** 2, axis=2)
        for query_index, target_index in np.argwhere(distances2 <= cutoff2):
            q = query_chunk[int(query_index)]
            t = target[int(target_index)]
            query_residues.add(q.residue_id)
            target_residues.add(t.residue_id)
            residue_pairs.add((q.residue_id, t.residue_id))
    return query_residues, target_residues, residue_pairs


def atom_and_residue_clashes(query: list[Atom], target: list[Atom], cutoff: float) -> dict[str, Any]:
    cutoff2 = cutoff * cutoff
    atom_pairs: list[tuple[str, str]] = []
    residue_pairs: set[tuple[str, str]] = set()
    target_xyz = np.asarray([(atom.x, atom.y, atom.z) for atom in target], dtype=float)
    for start in range(0, len(query), 256):
        query_chunk = query[start : start + 256]
        query_xyz = np.asarray([(atom.x, atom.y, atom.z) for atom in query_chunk], dtype=float)
        distances2 = np.sum((query_xyz[:, None, :] - target_xyz[None, :, :]) ** 2, axis=2)
        for query_index, target_index in np.argwhere(distances2 <= cutoff2):
            q = query_chunk[int(query_index)]
            t = target[int(target_index)]
            atom_pairs.append((q.atom_id, t.atom_id))
            residue_pairs.add((q.residue_id, t.residue_id))
    return {
        "atom_pair_count": len(atom_pairs),
        "residue_pair_count": len(residue_pairs),
        "atom_pairs": [list(pair) for pair in sorted(atom_pairs)],
        "residue_pairs": [list(pair) for pair in sorted(residue_pairs)],
    }


def parse_residue_range(spec: str) -> set[int]:
    values: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part[1:]:
            split_at = part[1:].index("-") + 1
            start, end = int(part[:split_at]), int(part[split_at + 1 :])
            if start > end:
                start, end = end, start
            values.update(range(start, end + 1))
        else:
            values.add(int(part))
    if not values:
        raise ValueError(f"empty residue range: {spec!r}")
    return values


def cdr_region(resseq: int, ranges: dict[str, set[int]]) -> str:
    if resseq in ranges["cdr1"]:
        return "cdr1"
    if resseq in ranges["cdr2"]:
        return "cdr2"
    if resseq in ranges["cdr3"]:
        return "cdr3"
    return "framework"


def residue_number(residue_id: str) -> int:
    middle = residue_id.split(":", 2)[1]
    digits = "".join(ch for ch in middle if ch.isdigit() or ch == "-")
    return int(digits)


def hotspot_overlap(contacted_t_residues: set[str], positions: list[int]) -> dict[str, Any]:
    contacted_positions = {residue_number(item) for item in contacted_t_residues if item.startswith("T:")}
    hits = sorted(pos for pos in positions if pos in contacted_positions)
    return {"count": len(hits), "total": len(positions), "fraction": round(len(hits) / len(positions), 6), "positions": hits}


def parse_haddock_io(path: Path | None, pose_path: Path | None = None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = read_json(path)
    records: list[dict[str, Any]] = []
    if isinstance(payload, dict) and "score" in payload:
        records.append(payload)
    if isinstance(payload, dict):
        for key in ("input", "output"):
            value = payload.get(key)
            if isinstance(value, list):
                records.extend(item for item in value if isinstance(item, dict) and "score" in item)
    pose_names = set()
    if pose_path is not None:
        pose_names = {pose_path.name, pose_path.stem, Path(pose_path.stem).stem}
    selected = None
    for record in records:
        record_names = {str(record.get(key) or "") for key in ("file_name", "full_name", "ori_name")}
        expanded = record_names | {Path(name).stem for name in record_names if name}
        if pose_names & expanded:
            selected = record
            break
    if selected is None and len(records) == 1:
        selected = records[0]
    energies = selected.get("unw_energies") if isinstance(selected, dict) else None
    return {
        "path": str(path),
        "matched_model": None if selected is None else selected.get("file_name", selected.get("full_name")),
        "score": None if selected is None else selected.get("score"),
        "unw_energies.air": energies.get("air") if isinstance(energies, dict) else None,
    }


def score_against_reference(
    pose_atoms: list[Atom],
    reference_atoms: list[Atom],
    reference_id: str,
    hotspots: dict[str, Any],
    vhh_chain: str,
    cdr_ranges: dict[str, set[int]],
) -> dict[str, Any]:
    pose_ca = ca_by_t_residue(pose_atoms)
    ref_ca = ca_by_t_residue(reference_atoms)
    common = sorted(set(pose_ca) & set(ref_ca))
    rotation, moving_centroid, fixed_centroid, rmsd = kabsch_transform(
        [pose_ca[pos] for pos in common], [ref_ca[pos] for pos in common]
    )
    atoms = transform_atoms(pose_atoms, rotation, moving_centroid, fixed_centroid)
    vhh_atoms = [atom for atom in atoms if atom.chain == vhh_chain]
    if not vhh_atoms:
        raise ValueError("pose has no VHH atoms; expected at least one chain other than T/L")
    t_atoms = [atom for atom in atoms if atom.chain == "T"]
    ref_l_atoms = [atom for atom in reference_atoms if atom.chain == "L"]
    _, contacted_t, vhh_t_pairs = residues_with_contacts(vhh_atoms, t_atoms, CONTACT_CUTOFF)
    vhh_l_residues, contacted_l, vhh_l_pairs = residues_with_contacts(vhh_atoms, ref_l_atoms, CONTACT_CUTOFF)

    region_counts = {"cdr1": 0, "cdr2": 0, "cdr3": 0, "framework": 0}
    for vhh_residue, _target_residue in vhh_l_pairs:
        region_counts[cdr_region(residue_number(vhh_residue), cdr_ranges)] += 1
    total_occlusion_pairs = sum(region_counts.values())
    cdr3_fraction = 0.0 if total_occlusion_pairs == 0 else region_counts["cdr3"] / total_occlusion_pairs

    return {
        "reference_id": reference_id,
        "overlay": {
            "common_t_ca_count": len(common),
            "t_ca_rmsd_a": round(rmsd, 6),
            "common_uniprot_positions": common,
        },
        "hotspot_overlap": {
            "full": hotspot_overlap(contacted_t, hotspots["all_uniprot_positions"]),
            "anchor": hotspot_overlap(contacted_t, hotspots["air_anchor_uniprot_positions"]),
            "holdout": hotspot_overlap(contacted_t, hotspots["holdout_uniprot_positions"]),
        },
        "vhh_pvrig_contacts": {
            "cutoff_a": CONTACT_CUTOFF,
            "pvrig_residue_count": len(contacted_t),
            "vhh_pvrig_residue_pair_count": len(vhh_t_pairs),
            "pvrig_residues": sorted(contacted_t, key=lambda item: (residue_number(item), item)),
        },
        "vhh_pvrl2_occlusion": {
            "cutoff_a": CONTACT_CUTOFF,
            "pvrl2_residue_count": len(contacted_l),
            "vhh_residue_count": len(vhh_l_residues),
            "residue_pair_count": len(vhh_l_pairs),
            "by_vhh_region_pair_count": region_counts,
            "cdr3_fraction": round(cdr3_fraction, 6),
            "pvrl2_residues": sorted(contacted_l, key=lambda item: (residue_number(item), item)),
        },
        "clashes_2p5a": {
            **atom_and_residue_clashes(vhh_atoms, t_atoms + ref_l_atoms, CLASH_CUTOFF),
            "vhh_pvrig": atom_and_residue_clashes(vhh_atoms, t_atoms, CLASH_CUTOFF),
            "vhh_pvrl2": atom_and_residue_clashes(vhh_atoms, ref_l_atoms, CLASH_CUTOFF),
        },
    }


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    try:
        summary = read_json(root / HOTSPOT_SUMMARY)
        hotspots = summary["hotspots"]
        pose_atoms = parse_pdb(args.pose)
        cdr_ranges = {
            "cdr1": parse_residue_range(args.cdr1),
            "cdr2": parse_residue_range(args.cdr2),
            "cdr3": parse_residue_range(args.cdr3),
        }
        reference_ids = args.reference or list(REFERENCE_IDS)
        scores = []
        for reference_id in reference_ids:
            reference_path = root / "inputs" / "normalized" / f"{reference_id}_TL_reference.pdb"
            scores.append(
                score_against_reference(
                    pose_atoms,
                    parse_pdb(reference_path),
                    reference_id,
                    hotspots,
                    args.vhh_chain,
                    cdr_ranges,
                )
            )
        payload = {
            "schema_version": 1,
            "pose": str(args.pose),
            "atom_filter": "standard_amino_acid_ATOM_only",
            "vhh_chain": args.vhh_chain,
            "cdr_ranges": {key: sorted(value) for key, value in cdr_ranges.items()},
            "haddock_io": parse_haddock_io(args.io_json, args.pose),
            "scores": scores,
        }
        if args.out:
            write_json(args.out, payload)
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    except Exception as exc:
        print(f"score_pose failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
