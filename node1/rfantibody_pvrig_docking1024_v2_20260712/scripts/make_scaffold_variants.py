#!/usr/bin/env python3
"""Create VHHified h-NbBCII10 scaffold variants with PyRosetta."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import pyrosetta
from pyrosetta import pose_from_pdb
from pyrosetta.rosetta.core.kinematics import MoveMap
from pyrosetta.rosetta.protocols.minimization_packing import MinMover
from pyrosetta.rosetta.protocols.simple_moves import MutateResidue


AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}

# PDB residues 47, 48, and 50 map to Kabat H44, H45, and H47.
VARIANTS = {
    "qrg": {47: "Q", 48: "R", 50: "G"},
    "ekg": {47: "E", 48: "K", 50: "G"},
    "qkg": {47: "Q", 48: "K", 50: "G"},
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pdb_sequence(path: Path, chain: str = "H") -> str:
    residues: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for line in path.read_text(encoding="ascii", errors="replace").splitlines():
        if not line.startswith("ATOM") or len(line) < 27 or line[21] != chain:
            continue
        key = (line[21], line[22:26], line[26])
        if key in seen:
            continue
        seen.add(key)
        residue = line[17:20].strip()
        if residue not in AA3_TO_1:
            raise ValueError(f"unsupported residue {residue!r} in {path}")
        residues.append(AA3_TO_1[residue])
    return "".join(residues)


def label_lines(path: Path) -> list[str]:
    return [
        line
        for line in path.read_text(encoding="ascii", errors="replace").splitlines()
        if line.startswith("REMARK PDBinfo-LABEL:")
    ]


def restore_labels(path: Path, labels: list[str]) -> None:
    lines = [
        line
        for line in path.read_text(encoding="ascii", errors="replace").splitlines()
        if not line.startswith("REMARK PDBinfo-LABEL:") and line != "END"
    ]
    lines.extend(labels)
    lines.append("END")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    labels = label_lines(args.source)
    if not labels or not all(any(line.endswith(name) for line in labels) for name in ("H1", "H2", "H3")):
        raise ValueError("source scaffold is missing RFantibody CDR labels")

    pyrosetta.init("-mute all -ignore_unrecognized_res true -load_PDB_components false")
    base_pose = pose_from_pdb(str(args.source))
    scorefxn = pyrosetta.get_fa_scorefxn()
    manifest: list[dict[str, object]] = []

    original = args.output_dir / "h-NbBCII10_original.pdb"
    shutil.copy2(args.source, original)
    manifest.append(
        {
            "scaffold_id": "orig",
            "path": str(original),
            "mutations": "none",
            "sequence": pdb_sequence(original),
            "sha256": sha256_file(original),
            "lane": "diagnostic_baseline_only",
        }
    )

    for scaffold_id, mutations in VARIANTS.items():
        pose = base_pose.clone()
        move_map = MoveMap()
        mutation_text: list[str] = []
        for pdb_residue, target_aa in mutations.items():
            pose_index = pose.pdb_info().pdb2pose("H", pdb_residue)
            if pose_index == 0:
                raise ValueError(f"chain H residue {pdb_residue} is missing")
            source_aa = pose.residue(pose_index).name1()
            MutateResidue(pose_index, target_aa).apply(pose)
            move_map.set_chi(pose_index, True)
            mutation_text.append(f"H{pdb_residue}{source_aa}>{target_aa}")
        MinMover(move_map, scorefxn, "lbfgs_armijo_nonmonotone", 0.001, True).apply(pose)
        output = args.output_dir / f"h-NbBCII10_vhh_{scaffold_id}.pdb"
        pose.dump_pdb(str(output))
        restore_labels(output, labels)
        sequence = pdb_sequence(output)
        for pdb_residue, target_aa in mutations.items():
            if sequence[pdb_residue - 1] != target_aa:
                raise ValueError(f"mutation validation failed for {output}: H{pdb_residue}")
        manifest.append(
            {
                "scaffold_id": scaffold_id,
                "path": str(output),
                "mutations": ";".join(mutation_text),
                "sequence": sequence,
                "sha256": sha256_file(output),
                "lane": "primary_vhhified",
            }
        )

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": str(args.source),
                "source_sha256": sha256_file(args.source),
                "pdb_to_kabat_mapping": {"H47": "H44", "H48": "H45", "H50": "H47"},
                "variants": manifest,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(args.manifest.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
