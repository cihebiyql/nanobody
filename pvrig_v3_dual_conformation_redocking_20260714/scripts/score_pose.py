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

from common import STANDARD_RESIDUES, is_standard_atom_line, project_root, read_json, write_json

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


def centroid(points: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    n = len(points)
    return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n, sum(p[2] for p in points) / n)


def mat_vec_mul(matrix: list[list[float]], vec: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        matrix[0][0] * vec[0] + matrix[0][1] * vec[1] + matrix[0][2] * vec[2],
        matrix[1][0] * vec[0] + matrix[1][1] * vec[1] + matrix[1][2] * vec[2],
        matrix[2][0] * vec[0] + matrix[2][1] * vec[1] + matrix[2][2] * vec[2],
    )


def kabsch_transform(
    moving: list[tuple[float, float, float]], fixed: list[tuple[float, float, float]]
) -> tuple[list[list[float]], tuple[float, float, float], tuple[float, float, float], float]:
    if len(moving) != len(fixed) or len(moving) < 3:
        raise ValueError("Kabsch overlay requires at least three paired CA atoms")
    cm = centroid(moving)
    cf = centroid(fixed)
    m = [(p[0] - cm[0], p[1] - cm[1], p[2] - cm[2]) for p in moving]
    f = [(p[0] - cf[0], p[1] - cf[1], p[2] - cf[2]) for p in fixed]
    sxx = sum(a[0] * b[0] for a, b in zip(m, f))
    sxy = sum(a[0] * b[1] for a, b in zip(m, f))
    sxz = sum(a[0] * b[2] for a, b in zip(m, f))
    syx = sum(a[1] * b[0] for a, b in zip(m, f))
    syy = sum(a[1] * b[1] for a, b in zip(m, f))
    syz = sum(a[1] * b[2] for a, b in zip(m, f))
    szx = sum(a[2] * b[0] for a, b in zip(m, f))
    szy = sum(a[2] * b[1] for a, b in zip(m, f))
    szz = sum(a[2] * b[2] for a, b in zip(m, f))
    trace = sxx + syy + szz
    k = [
        [trace, syz - szy, szx - sxz, sxy - syx],
        [syz - szy, sxx - syy - szz, sxy + syx, szx + sxz],
        [szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy],
        [sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz],
    ]
    q = [1.0, 0.0, 0.0, 0.0]
    for _ in range(80):
        nq = [sum(k[i][j] * q[j] for j in range(4)) for i in range(4)]
        norm = math.sqrt(sum(v * v for v in nq))
        if norm == 0.0:
            break
        q = [v / norm for v in nq]
    w, x, y, z = q
    rot = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    transformed = [apply_transform_point(p, rot, cm, cf) for p in moving]
    rmsd = math.sqrt(
        sum(
            (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
            for a, b in zip(transformed, fixed)
        )
        / len(fixed)
    )
    return rot, cm, cf, rmsd


def apply_transform_point(
    point: tuple[float, float, float],
    rotation: list[list[float]],
    moving_centroid: tuple[float, float, float],
    fixed_centroid: tuple[float, float, float],
) -> tuple[float, float, float]:
    shifted = (point[0] - moving_centroid[0], point[1] - moving_centroid[1], point[2] - moving_centroid[2])
    rotated = mat_vec_mul(rotation, shifted)
    return (rotated[0] + fixed_centroid[0], rotated[1] + fixed_centroid[1], rotated[2] + fixed_centroid[2])


def transform_atoms(
    atoms: list[Atom], rotation: list[list[float]], moving_centroid: tuple[float, float, float], fixed_centroid: tuple[float, float, float]
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
    for q in query:
        for t in target:
            if squared_distance(q, t) <= cutoff2:
                query_residues.add(q.residue_id)
                target_residues.add(t.residue_id)
                residue_pairs.add((q.residue_id, t.residue_id))
    return query_residues, target_residues, residue_pairs


def atom_and_residue_clashes(query: list[Atom], target: list[Atom], cutoff: float) -> dict[str, Any]:
    cutoff2 = cutoff * cutoff
    atom_pairs: list[tuple[str, str]] = []
    residue_pairs: set[tuple[str, str]] = set()
    for q in query:
        for t in target:
            if squared_distance(q, t) <= cutoff2:
                atom_pairs.append((q.atom_id, t.atom_id))
                residue_pairs.add((q.residue_id, t.residue_id))
    return {
        "atom_pair_count": len(atom_pairs),
        "residue_pair_count": len(residue_pairs),
        "atom_pairs": [list(pair) for pair in sorted(atom_pairs)],
        "residue_pairs": [list(pair) for pair in sorted(residue_pairs)],
    }


def cdr_region(resseq: int) -> str:
    if 26 <= resseq <= 35:
        return "cdr1"
    if 50 <= resseq <= 65:
        return "cdr2"
    if 95 <= resseq <= 117:
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


def parse_haddock_io(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = read_json(path)
    score = payload.get("score")
    unw_air = None
    energies = payload.get("unw_energies")
    if isinstance(energies, dict):
        unw_air = energies.get("air")
    return {"path": str(path), "score": score, "unw_energies.air": unw_air}


def score_against_reference(
    pose_atoms: list[Atom], reference_atoms: list[Atom], reference_id: str, hotspots: dict[str, Any]
) -> dict[str, Any]:
    pose_ca = ca_by_t_residue(pose_atoms)
    ref_ca = ca_by_t_residue(reference_atoms)
    common = sorted(set(pose_ca) & set(ref_ca))
    rotation, moving_centroid, fixed_centroid, rmsd = kabsch_transform(
        [pose_ca[pos] for pos in common], [ref_ca[pos] for pos in common]
    )
    atoms = transform_atoms(pose_atoms, rotation, moving_centroid, fixed_centroid)
    vhh_atoms = [atom for atom in atoms if atom.chain not in {"T", "L"}]
    if not vhh_atoms:
        raise ValueError("pose has no VHH atoms; expected at least one chain other than T/L")
    t_atoms = [atom for atom in atoms if atom.chain == "T"]
    l_atoms = [atom for atom in atoms if atom.chain == "L"]
    ref_l_atoms = [atom for atom in reference_atoms if atom.chain == "L"]
    _, contacted_t, vhh_t_pairs = residues_with_contacts(vhh_atoms, t_atoms, CONTACT_CUTOFF)
    vhh_l_residues, contacted_l, vhh_l_pairs = residues_with_contacts(vhh_atoms, l_atoms or ref_l_atoms, CONTACT_CUTOFF)

    region_counts = {"cdr1": 0, "cdr2": 0, "cdr3": 0, "framework": 0}
    for vhh_residue, _target_residue in vhh_l_pairs:
        region_counts[cdr_region(residue_number(vhh_residue))] += 1
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
        "clashes_2p5a": atom_and_residue_clashes(vhh_atoms, t_atoms + (l_atoms or ref_l_atoms), CLASH_CUTOFF),
    }


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    try:
        summary = read_json(root / HOTSPOT_SUMMARY)
        hotspots = summary["hotspots"]
        pose_atoms = parse_pdb(args.pose)
        reference_ids = args.reference or list(REFERENCE_IDS)
        scores = []
        for reference_id in reference_ids:
            reference_path = root / "inputs" / "normalized" / f"{reference_id}_TL_reference.pdb"
            scores.append(score_against_reference(pose_atoms, parse_pdb(reference_path), reference_id, hotspots))
        payload = {
            "schema_version": 1,
            "pose": str(args.pose),
            "atom_filter": "standard_amino_acid_ATOM_only",
            "haddock_io": parse_haddock_io(args.io_json),
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
