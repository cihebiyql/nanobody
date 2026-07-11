#!/usr/bin/env python3
"""Extract auditable PVRIG pose geometry features from optional PDB poses.

Rows with missing or failed poses are carried through explicitly with blank
geometry fields. Only supplied PDB ATOM/HETATM records are parsed; this script
never generates, docks, or repairs structures.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = ROOT / "experiments/phase2_5080_v1/data_splits/p3_optional_pose_manifest_v1.csv"
DEFAULT_MAPPING = ROOT / "model_data/pvrig_target_domain_mapping_v1.csv"
DEFAULT_OUTPUT = ROOT / "experiments/phase2_5080_v1/prepared/p3_pose_geometry_features_v1.csv"
CONTACT_CUTOFF_A = 4.5
CLASH_CUTOFF_A = 2.0
OUTPUT_FIELDS = [
    "candidate_id",
    "pose_id",
    "target_baseline",
    "pose_path",
    "vhh_chain",
    "target_chain",
    "pose_status",
    "qc_status",
    "geometry_status",
    "geometry_notes",
    "heavy_atom_interface_contacts_le_4p5A",
    "heavy_atom_clashes_lt_2p0A",
    "minimum_heavy_atom_distance_A",
    "vhh_interface_residues_json",
    "target_interface_residues_json",
    "target_interface_full_positions_json",
    "hotspot_contact_count",
    "hotspot_weighted_contacts",
    "hotspot_positions_json",
    "cdr3_seq",
    "cdr3_contacts",
    "cdr3_interface_residues_json",
    "calibration_role",
    "leakage_role",
]
AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q", "GLU": "E", "GLY": "G",
    "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P", "SER": "S",
    "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V", "SEC": "U", "PYL": "O",
}


@dataclass(frozen=True)
class Atom:
    serial: int
    name: str
    element: str
    resname: str
    chain: str
    resseq: int
    icode: str
    x: float
    y: float
    z: float

    @property
    def residue_key(self) -> tuple[str, int, str, str]:
        return (self.chain, self.resseq, self.icode, self.resname)

    @property
    def residue_label(self) -> str:
        suffix = self.icode.strip()
        return f"{self.chain}:{self.resname}{self.resseq}{suffix}"


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "na", "n/a", "?", "."}:
        return ""
    return text


def parse_pdb_atom_line(line: str) -> Atom | None:
    if not (line.startswith("ATOM  ") or line.startswith("HETATM")):
        return None
    try:
        serial = int(line[6:11])
        name = line[12:16].strip()
        resname = line[17:20].strip().upper()
        chain = line[21].strip() or "_"
        resseq = int(line[22:26])
        icode = line[26].strip()
        x = float(line[30:38])
        y = float(line[38:46])
        z = float(line[46:54])
        element = line[76:78].strip().upper() if len(line) >= 78 else ""
    except ValueError:
        return None
    if not element:
        stripped = "".join(ch for ch in name if ch.isalpha())
        element = stripped[0].upper() if stripped else ""
    if element == "H" or name.upper().startswith("H"):
        return None
    return Atom(serial, name, element, resname, chain, resseq, icode, x, y, z)


def parse_pdb(path: Path) -> list[Atom]:
    atoms: list[Atom] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            atom = parse_pdb_atom_line(line.rstrip("\n"))
            if atom is not None:
                atoms.append(atom)
    return atoms


def load_mapping(path: Path) -> tuple[dict[int, dict[str, str]], dict[int, dict[str, str]]]:
    by_full: dict[int, dict[str, str]] = {}
    by_model: dict[int, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            full = clean(row.get("full_position_1based"))
            model = clean(row.get("model_position_1based"))
            if full.isdigit():
                by_full[int(full)] = row
            if model.isdigit():
                by_model[int(model)] = row
    return by_full, by_model


def target_mapping_for_resseq(resseq: int, by_full: dict[int, dict[str, str]], by_model: dict[int, dict[str, str]], numbering: str) -> dict[str, str] | None:
    if numbering == "full_uniprot_1based":
        return by_full.get(resseq)
    if numbering == "model_domain_1based":
        return by_model.get(resseq)
    return by_full.get(resseq) or by_model.get(resseq)


def distance(a: Atom, b: Atom) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def residue_order(atoms: Iterable[Atom], chain: str) -> list[tuple[str, int, str, str]]:
    seen: dict[tuple[str, int, str, str], None] = {}
    for atom in sorted((a for a in atoms if a.chain == chain), key=lambda a: (a.resseq, a.icode, a.serial)):
        seen.setdefault(atom.residue_key, None)
    return list(seen)


def locate_cdr3_residues(atoms: list[Atom], vhh_chain: str, vhh_seq: str, cdr3_seq: str) -> tuple[set[tuple[str, int, str, str]], str]:
    if not vhh_seq or not cdr3_seq:
        return set(), "missing_vhh_seq_or_cdr3_seq"
    start = vhh_seq.find(cdr3_seq)
    if start < 0 or vhh_seq.find(cdr3_seq, start + 1) >= 0:
        return set(), "cdr3_substring_missing_or_ambiguous"
    ordered = residue_order(atoms, vhh_chain)
    seq_from_pdb = "".join(AA3_TO_1.get(key[3], "X") for key in ordered)
    if len(ordered) < start + len(cdr3_seq):
        return set(), "pdb_vhh_chain_shorter_than_cdr3_span"
    if len(seq_from_pdb) == len(vhh_seq) and seq_from_pdb[start : start + len(cdr3_seq)] != cdr3_seq:
        return set(), "pdb_vhh_chain_sequence_mismatch_at_cdr3_span"
    return set(ordered[start : start + len(cdr3_seq)]), "ok"


def json_list(values: Iterable[object]) -> str:
    return json.dumps(list(values), ensure_ascii=True, separators=(",", ":"))


def blank_geometry(row: dict[str, str], status: str, notes: str) -> dict[str, str]:
    out = {field: "" for field in OUTPUT_FIELDS}
    for field in ("candidate_id", "pose_id", "target_baseline", "pose_path", "vhh_chain", "target_chain", "pose_status", "qc_status", "cdr3_seq", "calibration_role", "leakage_role"):
        out[field] = clean(row.get(field))
    out["geometry_status"] = status
    out["geometry_notes"] = notes
    return out


def extract_row(row: dict[str, str], by_full: dict[int, dict[str, str]], by_model: dict[int, dict[str, str]]) -> dict[str, str]:
    pose_path = clean(row.get("pose_path"))
    if not pose_path:
        return blank_geometry(row, "no_pose", "explicit manifest row has no pose_path; geometry not fabricated")
    path = Path(pose_path)
    if not path.exists():
        return blank_geometry(row, "pose_file_missing", f"pose_path does not exist: {pose_path}")
    atoms = parse_pdb(path)
    if not atoms:
        return blank_geometry(row, "pose_parse_failed", "no heavy ATOM/HETATM records parsed")

    vhh_chain = clean(row.get("vhh_chain")) or "A"
    target_chain = clean(row.get("target_chain")) or "T"
    vhh_atoms = [a for a in atoms if a.chain == vhh_chain]
    target_atoms = [a for a in atoms if a.chain == target_chain]
    if not vhh_atoms or not target_atoms:
        return blank_geometry(row, "chain_missing", f"vhh_atoms={len(vhh_atoms)} target_atoms={len(target_atoms)}")

    numbering = clean(row.get("target_residue_numbering"))
    cdr3_keys, cdr3_note = locate_cdr3_residues(atoms, vhh_chain, clean(row.get("vhh_seq")).upper(), clean(row.get("cdr3_seq")).upper())
    contacts = 0
    clashes = 0
    min_dist = float("inf")
    vhh_residues: set[str] = set()
    target_residues: set[str] = set()
    target_full_positions: set[int] = set()
    hotspot_positions: set[int] = set()
    hotspot_contact_count = 0
    hotspot_weighted_contacts = 0.0
    cdr3_contacts = 0
    cdr3_residues: set[str] = set()

    for va in vhh_atoms:
        for ta in target_atoms:
            d = distance(va, ta)
            if d < min_dist:
                min_dist = d
            if d < CLASH_CUTOFF_A:
                clashes += 1
            if d <= CONTACT_CUTOFF_A:
                contacts += 1
                vhh_residues.add(va.residue_label)
                target_residues.add(ta.residue_label)
                map_row = target_mapping_for_resseq(ta.resseq, by_full, by_model, numbering)
                if map_row:
                    full_pos = int(map_row["full_position_1based"])
                    target_full_positions.add(full_pos)
                    weight = float(clean(map_row.get("target_weight")) or "0")
                    if weight > 0:
                        hotspot_contact_count += 1
                        hotspot_weighted_contacts += weight
                        hotspot_positions.add(full_pos)
                if va.residue_key in cdr3_keys:
                    cdr3_contacts += 1
                    cdr3_residues.add(va.residue_label)

    notes = "ok"
    if cdr3_note != "ok":
        notes = f"geometry_ok;cdr3_contacts_uncomputed:{cdr3_note}"
        cdr3_contacts_value = ""
    else:
        cdr3_contacts_value = str(cdr3_contacts)

    out = {field: "" for field in OUTPUT_FIELDS}
    for field in ("candidate_id", "pose_id", "target_baseline", "pose_path", "vhh_chain", "target_chain", "pose_status", "qc_status", "cdr3_seq", "calibration_role", "leakage_role"):
        out[field] = clean(row.get(field))
    out.update(
        {
            "geometry_status": "ok",
            "geometry_notes": notes,
            "heavy_atom_interface_contacts_le_4p5A": str(contacts),
            "heavy_atom_clashes_lt_2p0A": str(clashes),
            "minimum_heavy_atom_distance_A": f"{min_dist:.3f}" if min_dist < float("inf") else "",
            "vhh_interface_residues_json": json_list(sorted(vhh_residues)),
            "target_interface_residues_json": json_list(sorted(target_residues)),
            "target_interface_full_positions_json": json_list(sorted(target_full_positions)),
            "hotspot_contact_count": str(hotspot_contact_count),
            "hotspot_weighted_contacts": f"{hotspot_weighted_contacts:.3f}",
            "hotspot_positions_json": json_list(sorted(hotspot_positions)),
            "cdr3_contacts": cdr3_contacts_value,
            "cdr3_interface_residues_json": json_list(sorted(cdr3_residues)) if cdr3_note == "ok" else "",
        }
    )
    return out


def extract_features(manifest: Path, mapping: Path, output: Path) -> dict[str, int]:
    by_full, by_model = load_mapping(mapping)
    with manifest.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    out_rows = [extract_row(row, by_full, by_model) for row in rows]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)
    return {
        "manifest_rows": len(rows),
        "output_rows": len(out_rows),
        "ok_rows": sum(1 for row in out_rows if row["geometry_status"] == "ok"),
        "explicit_non_geometry_rows": sum(1 for row in out_rows if row["geometry_status"] != "ok"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = extract_features(args.manifest, args.mapping, args.output)
    print(json.dumps({"status": "PASS", "output": str(args.output), **summary}, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
