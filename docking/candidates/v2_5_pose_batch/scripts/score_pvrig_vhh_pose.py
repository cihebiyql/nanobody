#!/usr/bin/env python3
"""Score PVRIG VHH docking poses against a PVRL2 reference interface.

Pure standard-library utility: parses PDB ATOM/HETATM records, computes heavy-atom
contacts, hotspot overlap, optional CDR support, and aligned-reference PVRL2
clash/occlusion proxies.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


HEAVY_CONTACT_CUTOFF_A = 4.5
CLASH_CUTOFF_A = 2.5


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
    element: str

    @property
    def residue_id(self) -> str:
        suffix = self.icode.strip()
        return f"{self.chain}:{self.resseq}{suffix}{self.resname}"

    @property
    def residue_key(self) -> Tuple[str, int, str, str]:
        return (self.chain, self.resseq, self.icode.strip(), self.resname)


@dataclass(frozen=True)
class Contact:
    pvrig_residue: str
    vhh_residue: str
    distance_a: float
    pvrig_atom: str
    vhh_atom: str


@dataclass(frozen=True)
class CdrRange:
    label: str
    chain: Optional[str]
    start: int
    end: int


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Score a PVRIG:VHH docking pose for PVRIG contacts, hotspot overlap, "
            "optional CDR support, and PVRL2 occlusion against an aligned 8X6B/9E6Y reference."
        )
    )
    parser.add_argument("--pose-pdb", required=True, help="Docked pose PDB containing PVRIG and VHH chains.")
    parser.add_argument("--reference-pdb", required=True, help="Reference PVRIG:PVRL2 complex PDB, e.g. 8X6B or 9E6Y.")
    parser.add_argument("--pvrig-chain", required=True, help="PVRIG chain ID in the pose PDB.")
    parser.add_argument("--vhh-chain", required=True, help="VHH chain ID in the pose PDB.")
    parser.add_argument("--ref-pvrig-chain", required=True, help="PVRIG chain ID in the reference PDB.")
    parser.add_argument("--ref-pvrl2-chain", required=True, help="PVRL2 chain ID in the reference PDB.")
    parser.add_argument("--hotspots-csv", required=True, help="Hotspot CSV with pdb_*_ref columns such as B:33S or A:31S.")
    parser.add_argument("--out-csv", help="Write one-row summary CSV to this path.")
    parser.add_argument("--out-json", help="Write detailed JSON report to this path.")
    parser.add_argument(
        "--assume-aligned",
        action="store_true",
        help=(
            "Required: assume pose PVRIG coordinates are already aligned to the reference PVRIG. "
            "Kabsch superposition is not implemented in this standard-library scorer yet."
        ),
    )
    parser.add_argument(
        "--contact-cutoff",
        type=float,
        default=HEAVY_CONTACT_CUTOFF_A,
        help=f"Heavy-atom contact/occlusion cutoff in Angstrom (default: {HEAVY_CONTACT_CUTOFF_A}).",
    )
    parser.add_argument(
        "--clash-cutoff",
        type=float,
        default=CLASH_CUTOFF_A,
        help=f"Heavy-atom clash cutoff in Angstrom (default: {CLASH_CUTOFF_A}).",
    )
    parser.add_argument(
        "--cdr-ranges",
        default="",
        help=(
            "Optional CDR residue ranges on the VHH chain. Examples: '26-35,50-65,95-102' "
            "or 'CDR1:26-35,CDR2:50-65,CDR3:95-102' or 'H:CDR1:26-35'."
        ),
    )
    parser.add_argument(
        "--hotspot-ref-column",
        default="",
        help="Optional hotspot CSV column to force, e.g. pdb_8x6b_ref or pdb_9e6y_ref. Auto-detected by chain otherwise.",
    )
    args = parser.parse_args(argv)
    if bool(args.out_csv) == bool(args.out_json):
        parser.error("Provide exactly one of --out-csv or --out-json.")
    if not args.assume_aligned:
        parser.error(
            "--assume-aligned is required because Kabsch PVRIG superposition is not implemented. "
            "Align pose PVRIG to the reference PVRIG first, then rerun."
        )
    if args.contact_cutoff <= 0 or args.clash_cutoff <= 0:
        parser.error("Cutoffs must be positive.")
    return args


def parse_pdb(path: str) -> List[Atom]:
    atoms: List[Atom] = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not (line.startswith("ATOM  ") or line.startswith("HETATM")):
                continue
            try:
                serial = int(line[6:11])
                name = line[12:16].strip()
                resname = line[17:20].strip()
                chain = line[21].strip() or "_"
                resseq = int(line[22:26])
                icode = line[26].strip()
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])
                element = line[76:78].strip() if len(line) >= 78 else ""
            except ValueError:
                continue
            atoms.append(Atom(serial, name, resname, chain, resseq, icode, x, y, z, element))
    return atoms


def is_heavy_atom(atom: Atom) -> bool:
    element = atom.element.upper()
    if element:
        return element not in {"H", "D"}
    return not atom.name.upper().startswith(("H", "D"))


def select_chain(atoms: Iterable[Atom], chain: str) -> List[Atom]:
    return [atom for atom in atoms if atom.chain == chain and is_heavy_atom(atom)]


def distance(a: Atom, b: Atom) -> float:
    dx = a.x - b.x
    dy = a.y - b.y
    dz = a.z - b.z
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def residue_sort_key(residue_id: str) -> Tuple[str, int, str]:
    match = re.match(r"([^:]+):(-?\d+)([A-Za-z]?)(.*)", residue_id)
    if not match:
        return (residue_id, 0, "")
    return (match.group(1), int(match.group(2)), match.group(3))


def residue_label(key: Tuple[str, int, str, str]) -> str:
    chain, resseq, icode, resname = key
    return f"{chain}:{resseq}{icode}{resname}"


def closest_contacts(a_atoms: List[Atom], b_atoms: List[Atom], cutoff: float) -> List[Contact]:
    best: Dict[Tuple[str, str], Contact] = {}
    cutoff2 = cutoff * cutoff
    for atom_a in a_atoms:
        for atom_b in b_atoms:
            dx = atom_a.x - atom_b.x
            dy = atom_a.y - atom_b.y
            dz = atom_a.z - atom_b.z
            dist2 = dx * dx + dy * dy + dz * dz
            if dist2 > cutoff2:
                continue
            dist = math.sqrt(dist2)
            pair_key = (atom_a.residue_id, atom_b.residue_id)
            old = best.get(pair_key)
            if old is None or dist < old.distance_a:
                best[pair_key] = Contact(atom_a.residue_id, atom_b.residue_id, dist, atom_a.name, atom_b.name)
    return sorted(best.values(), key=lambda c: (residue_sort_key(c.pvrig_residue), residue_sort_key(c.vhh_residue)))


def parse_cdr_ranges(spec: str, default_chain: str) -> List[CdrRange]:
    ranges: List[CdrRange] = []
    if not spec.strip():
        return ranges
    for idx, raw_item in enumerate(spec.split(","), start=1):
        item = raw_item.strip()
        if not item:
            continue
        parts = item.split(":")
        chain: Optional[str] = None
        label = f"CDR{idx}"
        range_part = parts[-1]
        if len(parts) == 2:
            if re.fullmatch(r"[A-Za-z0-9_]", parts[0]):
                chain = parts[0]
            else:
                label = parts[0]
        elif len(parts) == 3:
            chain, label, range_part = parts
        match = re.fullmatch(r"(-?\d+)\s*-\s*(-?\d+)", range_part)
        if not match:
            raise ValueError(f"Invalid CDR range '{item}'. Expected start-end or label:start-end.")
        start, end = int(match.group(1)), int(match.group(2))
        if start > end:
            start, end = end, start
        ranges.append(CdrRange(label=label, chain=chain or default_chain, start=start, end=end))
    return ranges


def cdr_support(vhh_contact_residues: Set[str], cdr_ranges: List[CdrRange]) -> Dict[str, object]:
    by_label: Dict[str, List[str]] = defaultdict(list)
    for residue in vhh_contact_residues:
        match = re.match(r"([^:]+):(-?\d+)", residue)
        if not match:
            continue
        chain, resseq = match.group(1), int(match.group(2))
        for cdr in cdr_ranges:
            if cdr.chain == chain and cdr.start <= resseq <= cdr.end:
                by_label[cdr.label].append(residue)
    by_label_sorted = {label: sorted(vals, key=residue_sort_key) for label, vals in sorted(by_label.items())}
    all_cdr_residues = sorted({res for vals in by_label_sorted.values() for res in vals}, key=residue_sort_key)
    return {
        "cdr_contact_residue_count": len(all_cdr_residues),
        "cdr_contact_residues": all_cdr_residues,
        "cdr_contact_residues_by_label": by_label_sorted,
    }


def parse_hotspot_ref(value: str) -> Optional[Tuple[str, int, str]]:
    value = (value or "").strip()
    match = re.fullmatch(r"([^:\s]+):(-?\d+)([A-Za-z]*)", value)
    if not match:
        return None
    chain = match.group(1)
    resseq = int(match.group(2))
    aa = match.group(3)
    return chain, resseq, aa


def load_hotspots(path: str, ref_pvrig_chain: str, forced_column: str = "") -> Tuple[List[Dict[str, str]], str]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return [], forced_column
    columns = rows[0].keys()
    ref_columns = [col for col in columns if col.lower().startswith("pdb_") and col.lower().endswith("_ref")]
    if forced_column:
        if forced_column not in columns:
            raise ValueError(f"Hotspot CSV does not contain forced column '{forced_column}'.")
        chosen = forced_column
    else:
        chosen = ""
        for col in ref_columns:
            if any((parse_hotspot_ref(row.get(col, "")) or (None, None, None))[0] == ref_pvrig_chain for row in rows):
                chosen = col
                break
        if not chosen and ref_columns:
            chosen = ref_columns[0]
    hotspots: List[Dict[str, str]] = []
    for row in rows:
        parsed = parse_hotspot_ref(row.get(chosen, "")) if chosen else None
        if not parsed or parsed[0] != ref_pvrig_chain:
            continue
        chain, resseq, aa = parsed
        hotspot_id = row.get("hotspot_id") or row.get("id") or f"{chain}:{resseq}{aa}"
        hotspots.append(
            {
                "hotspot_id": hotspot_id,
                "chain": chain,
                "resseq": str(resseq),
                "aa": aa,
                "weight": row.get("priority_weight", "1"),
                "source_column": chosen,
            }
        )
    return hotspots, chosen


def hotspot_overlap(contact_pvrig_residues: Set[str], hotspots: List[Dict[str, str]], pose_pvrig_chain: str) -> Dict[str, object]:
    contacted_numbers = set()
    for residue in contact_pvrig_residues:
        match = re.match(r"([^:]+):(-?\d+)", residue)
        if match and match.group(1) == pose_pvrig_chain:
            contacted_numbers.add(int(match.group(2)))
    matched = []
    total_weight = 0.0
    matched_weight = 0.0
    for hotspot in hotspots:
        resseq = int(hotspot["resseq"])
        try:
            weight = float(hotspot.get("weight") or 1.0)
        except ValueError:
            weight = 1.0
        total_weight += weight
        if resseq in contacted_numbers:
            matched_weight += weight
            matched.append({"hotspot_id": hotspot["hotspot_id"], "pose_pvrig_residue_number": resseq, "weight": weight})
    return {
        "hotspot_count": len(hotspots),
        "hotspot_overlap_count": len(matched),
        "hotspot_overlap_fraction": (len(matched) / len(hotspots)) if hotspots else 0.0,
        "hotspot_weight_total": total_weight,
        "hotspot_weight_overlap": matched_weight,
        "hotspot_weight_fraction": (matched_weight / total_weight) if total_weight else 0.0,
        "hotspot_overlaps": matched,
    }


def residue_counts(contacts: List[Contact]) -> Tuple[Set[str], Set[str]]:
    pvrig = {contact.pvrig_residue for contact in contacts}
    vhh = {contact.vhh_residue for contact in contacts}
    return pvrig, vhh


def summarize_occlusion(vhh_atoms: List[Atom], pvrl2_atoms: List[Atom], contact_cutoff: float, clash_cutoff: float) -> Dict[str, object]:
    occlusion_contacts = closest_contacts(pvrl2_atoms, vhh_atoms, contact_cutoff)
    clash_contacts = closest_contacts(pvrl2_atoms, vhh_atoms, clash_cutoff)
    pvrl2_occ, vhh_occ = residue_counts(occlusion_contacts)
    pvrl2_clash, vhh_clash = residue_counts(clash_contacts)
    return {
        "pvrl2_vhh_occluding_contact_count": len(occlusion_contacts),
        "pvrl2_occluded_residue_count": len(pvrl2_occ),
        "vhh_occluding_residue_count": len(vhh_occ),
        "pvrl2_vhh_clash_count": len(clash_contacts),
        "pvrl2_clash_residue_count": len(pvrl2_clash),
        "vhh_clash_residue_count": len(vhh_clash),
        "pvrl2_occluded_residues": sorted(pvrl2_occ, key=residue_sort_key),
        "vhh_occluding_residues": sorted(vhh_occ, key=residue_sort_key),
        "pvrl2_vhh_clashes": [contact.__dict__ for contact in clash_contacts],
    }


def write_csv(path: str, summary: Dict[str, object]) -> None:
    scalar_keys = [
        key
        for key, value in summary.items()
        if isinstance(value, (str, int, float, bool)) or value is None
    ]
    list_as_string = {
        "pvrig_contact_residues": ";".join(summary.get("pvrig_contact_residues", [])),
        "vhh_contact_residues": ";".join(summary.get("vhh_contact_residues", [])),
        "cdr_contact_residues": ";".join(summary.get("cdr_contact_residues", [])),
        "pvrl2_occluded_residues": ";".join(summary.get("pvrl2_occluded_residues", [])),
        "vhh_occluding_residues": ";".join(summary.get("vhh_occluding_residues", [])),
    }
    row = {key: summary[key] for key in scalar_keys}
    row.update(list_as_string)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


def ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        cdr_ranges = parse_cdr_ranges(args.cdr_ranges, args.vhh_chain)
        pose_atoms = parse_pdb(args.pose_pdb)
        ref_atoms = parse_pdb(args.reference_pdb)
        pvrig_atoms = select_chain(pose_atoms, args.pvrig_chain)
        vhh_atoms = select_chain(pose_atoms, args.vhh_chain)
        ref_pvrl2_atoms = select_chain(ref_atoms, args.ref_pvrl2_chain)
        if not pvrig_atoms:
            raise ValueError(f"No heavy atoms found for pose PVRIG chain '{args.pvrig_chain}'.")
        if not vhh_atoms:
            raise ValueError(f"No heavy atoms found for pose VHH chain '{args.vhh_chain}'.")
        if not ref_pvrl2_atoms:
            raise ValueError(f"No heavy atoms found for reference PVRL2 chain '{args.ref_pvrl2_chain}'.")
        contacts = closest_contacts(pvrig_atoms, vhh_atoms, args.contact_cutoff)
        pvrig_contact_residues, vhh_contact_residues = residue_counts(contacts)
        hotspots, hotspot_column = load_hotspots(args.hotspots_csv, args.ref_pvrig_chain, args.hotspot_ref_column)
        hotspot_summary = hotspot_overlap(pvrig_contact_residues, hotspots, args.pvrig_chain)
        cdr_summary = cdr_support(vhh_contact_residues, cdr_ranges)
        occlusion_summary = summarize_occlusion(vhh_atoms, ref_pvrl2_atoms, args.contact_cutoff, args.clash_cutoff)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    summary: Dict[str, object] = {
        "pose_pdb": args.pose_pdb,
        "reference_pdb": args.reference_pdb,
        "pvrig_chain": args.pvrig_chain,
        "vhh_chain": args.vhh_chain,
        "ref_pvrig_chain": args.ref_pvrig_chain,
        "ref_pvrl2_chain": args.ref_pvrl2_chain,
        "assume_aligned": args.assume_aligned,
        "contact_cutoff_a": args.contact_cutoff,
        "clash_cutoff_a": args.clash_cutoff,
        "hotspot_ref_column": hotspot_column,
        "pvrig_vhh_contact_pair_count": len(contacts),
        "pvrig_contact_residue_count": len(pvrig_contact_residues),
        "vhh_contact_residue_count": len(vhh_contact_residues),
        "pvrig_contact_residues": sorted(pvrig_contact_residues, key=residue_sort_key),
        "vhh_contact_residues": sorted(vhh_contact_residues, key=residue_sort_key),
        "pvrig_vhh_contacts": [contact.__dict__ for contact in contacts],
    }
    summary.update(hotspot_summary)
    summary.update(cdr_summary)
    summary.update(occlusion_summary)
    summary["notes"] = [
        "Only ATOM/HETATM heavy atoms are scored; hydrogens/deuteriums are ignored.",
        "Pose and reference must already be in the same PVRIG coordinate frame; Kabsch superposition is a future TODO.",
        "Hotspot overlap assumes pose PVRIG residue numbers match the chosen reference hotspot column.",
    ]

    out_path = args.out_json or args.out_csv
    ensure_parent(out_path)
    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    else:
        write_csv(args.out_csv, summary)
    print(f"Wrote score report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
