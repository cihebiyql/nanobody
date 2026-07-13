#!/usr/bin/env python3
"""Score a PVRIG:VHH pose with V1.2 protein-ATOM-only PVRL2 semantics."""
from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from pvrig_scoring_semantics_v1_2 import (
    Atom,
    CLAIM_BOUNDARY,
    SCORING_SEMANTICS_VERSION,
    flatten_reference_inventory,
    parse_pdb,
    pose_chain_inventory,
    reference_pvrl2_inventory,
    select_pose_chain,
    select_reference_pvrl2_protein,
    semantics_manifest,
    write_json,
)


HEAVY_CONTACT_CUTOFF_A = 4.5
CLASH_CUTOFF_A = 2.5
SCHEMA_VERSION = "pvrig_vhh_pose_score_v1_2"


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pose-pdb", required=True)
    parser.add_argument("--reference-pdb", required=True)
    parser.add_argument("--pvrig-chain", required=True)
    parser.add_argument("--vhh-chain", required=True)
    parser.add_argument("--ref-pvrig-chain", required=True)
    parser.add_argument("--ref-pvrl2-chain", required=True)
    parser.add_argument("--hotspots-csv", required=True)
    parser.add_argument("--out-csv")
    parser.add_argument("--out-json")
    parser.add_argument(
        "--assume-aligned",
        action="store_true",
        help="Required: the pose PVRIG must already be aligned to the reference PVRIG.",
    )
    parser.add_argument("--contact-cutoff", type=float, default=HEAVY_CONTACT_CUTOFF_A)
    parser.add_argument("--clash-cutoff", type=float, default=CLASH_CUTOFF_A)
    parser.add_argument("--cdr-ranges", default="")
    parser.add_argument("--hotspot-ref-column", default="")
    args = parser.parse_args(argv)
    if bool(args.out_csv) == bool(args.out_json):
        parser.error("Provide exactly one of --out-csv or --out-json.")
    if not args.assume_aligned:
        parser.error("--assume-aligned is required; this scorer does not perform superposition.")
    if (
        not math.isfinite(args.contact_cutoff)
        or not math.isfinite(args.clash_cutoff)
        or args.contact_cutoff <= 0
        or args.clash_cutoff <= 0
    ):
        parser.error("Cutoffs must be positive finite numbers.")
    return args


def residue_sort_key(residue_id: str) -> tuple[str, int, str]:
    match = re.match(r"([^:]+):(-?\d+)([A-Za-z]?)(.*)", residue_id)
    if not match:
        return (residue_id, 0, "")
    return (match.group(1), int(match.group(2)), match.group(3))


def closest_contacts(a_atoms: list[Atom], b_atoms: list[Atom], cutoff: float) -> list[Contact]:
    best: dict[tuple[str, str], Contact] = {}
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
                best[pair_key] = Contact(
                    atom_a.residue_id,
                    atom_b.residue_id,
                    dist,
                    atom_a.name,
                    atom_b.name,
                )
    return sorted(
        best.values(),
        key=lambda contact: (
            residue_sort_key(contact.pvrig_residue),
            residue_sort_key(contact.vhh_residue),
        ),
    )


def parse_cdr_ranges(spec: str, default_chain: str) -> list[CdrRange]:
    ranges: list[CdrRange] = []
    if not spec.strip():
        return ranges
    for index, raw_item in enumerate(spec.split(","), start=1):
        item = raw_item.strip()
        if not item:
            continue
        parts = item.split(":")
        chain: Optional[str] = None
        label = f"CDR{index}"
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
            raise ValueError(f"Invalid CDR range {item!r}")
        start, end = int(match.group(1)), int(match.group(2))
        if start > end:
            start, end = end, start
        ranges.append(CdrRange(label, chain or default_chain, start, end))
    return ranges


def cdr_support(vhh_contact_residues: set[str], cdr_ranges: list[CdrRange]) -> dict[str, Any]:
    by_label: dict[str, list[str]] = defaultdict(list)
    for residue in vhh_contact_residues:
        match = re.match(r"([^:]+):(-?\d+)", residue)
        if not match:
            continue
        chain, resseq = match.group(1), int(match.group(2))
        for cdr in cdr_ranges:
            if cdr.chain == chain and cdr.start <= resseq <= cdr.end:
                by_label[cdr.label].append(residue)
    by_label_sorted = {
        label: sorted(values, key=residue_sort_key)
        for label, values in sorted(by_label.items())
    }
    all_cdr = sorted(
        {residue for values in by_label_sorted.values() for residue in values},
        key=residue_sort_key,
    )
    return {
        "cdr_contact_residue_count": len(all_cdr),
        "cdr_contact_residues": all_cdr,
        "cdr_contact_residues_by_label": by_label_sorted,
    }


def parse_hotspot_ref(value: str) -> Optional[tuple[str, int, str]]:
    match = re.fullmatch(r"([^:\s]+):(-?\d+)([A-Za-z]*)", (value or "").strip())
    if not match:
        return None
    return match.group(1), int(match.group(2)), match.group(3)


def load_hotspots(
    path: str,
    ref_pvrig_chain: str,
    forced_column: str = "",
) -> tuple[list[dict[str, str]], str]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return [], forced_column
    columns = rows[0].keys()
    ref_columns = [
        column
        for column in columns
        if column.lower().startswith("pdb_") and column.lower().endswith("_ref")
    ]
    if forced_column:
        if forced_column not in columns:
            raise ValueError(f"Hotspot CSV lacks forced column {forced_column!r}")
        chosen = forced_column
    else:
        chosen = ""
        for column in ref_columns:
            if any(
                (parse_hotspot_ref(row.get(column, "")) or (None, None, None))[0]
                == ref_pvrig_chain
                for row in rows
            ):
                chosen = column
                break
        if not chosen and ref_columns:
            chosen = ref_columns[0]
    hotspots: list[dict[str, str]] = []
    for row in rows:
        parsed = parse_hotspot_ref(row.get(chosen, "")) if chosen else None
        if not parsed or parsed[0] != ref_pvrig_chain:
            continue
        chain, resseq, amino_acid = parsed
        hotspots.append(
            {
                "hotspot_id": row.get("hotspot_id") or row.get("id") or f"{chain}:{resseq}{amino_acid}",
                "chain": chain,
                "resseq": str(resseq),
                "aa": amino_acid,
                "weight": row.get("priority_weight", "1"),
                "source_column": chosen,
            }
        )
    return hotspots, chosen


def hotspot_overlap(
    contact_pvrig_residues: set[str],
    hotspots: list[dict[str, str]],
    pose_pvrig_chain: str,
) -> dict[str, Any]:
    contacted_numbers = set()
    for residue in contact_pvrig_residues:
        match = re.match(r"([^:]+):(-?\d+)", residue)
        if match and match.group(1) == pose_pvrig_chain:
            contacted_numbers.add(int(match.group(2)))
    matched: list[dict[str, Any]] = []
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
            matched.append(
                {
                    "hotspot_id": hotspot["hotspot_id"],
                    "pose_pvrig_residue_number": resseq,
                    "weight": weight,
                }
            )
    return {
        "hotspot_count": len(hotspots),
        "hotspot_overlap_count": len(matched),
        "hotspot_overlap_fraction": len(matched) / len(hotspots) if hotspots else 0.0,
        "hotspot_weight_total": total_weight,
        "hotspot_weight_overlap": matched_weight,
        "hotspot_weight_fraction": matched_weight / total_weight if total_weight else 0.0,
        "hotspot_overlaps": matched,
    }


def residue_counts(contacts: Iterable[Contact]) -> tuple[set[str], set[str]]:
    contact_list = list(contacts)
    return (
        {contact.pvrig_residue for contact in contact_list},
        {contact.vhh_residue for contact in contact_list},
    )


def summarize_occlusion(
    vhh_atoms: list[Atom],
    pvrl2_atoms: list[Atom],
    contact_cutoff: float,
    clash_cutoff: float,
) -> dict[str, Any]:
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


def write_csv(path: str, summary: dict[str, Any]) -> None:
    scalar_keys = [
        key
        for key, value in summary.items()
        if isinstance(value, (str, int, float, bool)) or value is None
    ]
    lists = {
        "pvrig_contact_residues": ";".join(summary.get("pvrig_contact_residues", [])),
        "vhh_contact_residues": ";".join(summary.get("vhh_contact_residues", [])),
        "cdr_contact_residues": ";".join(summary.get("cdr_contact_residues", [])),
        "pvrl2_occluded_residues": ";".join(summary.get("pvrl2_occluded_residues", [])),
        "vhh_occluding_residues": ";".join(summary.get("vhh_occluding_residues", [])),
    }
    row = {key: summary[key] for key in scalar_keys}
    row.update(lists)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row), lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        cdr_ranges = parse_cdr_ranges(args.cdr_ranges, args.vhh_chain)
        pose_atoms = parse_pdb(args.pose_pdb)
        reference_atoms = parse_pdb(args.reference_pdb)
        pvrig_atoms = select_pose_chain(pose_atoms, args.pvrig_chain)
        vhh_atoms = select_pose_chain(pose_atoms, args.vhh_chain)
        ref_pvrl2_atoms = select_reference_pvrl2_protein(
            reference_atoms, args.ref_pvrl2_chain
        )
        if not pvrig_atoms:
            raise ValueError(f"No pose PVRIG heavy atoms for chain {args.pvrig_chain!r}")
        if not vhh_atoms:
            raise ValueError(f"No pose VHH heavy atoms for chain {args.vhh_chain!r}")
        if not ref_pvrl2_atoms:
            raise ValueError(
                f"No reference PVRL2 protein ATOM heavy atoms for chain {args.ref_pvrl2_chain!r}"
            )
        contacts = closest_contacts(pvrig_atoms, vhh_atoms, args.contact_cutoff)
        pvrig_contact_residues, vhh_contact_residues = residue_counts(contacts)
        hotspots, hotspot_column = load_hotspots(
            args.hotspots_csv, args.ref_pvrig_chain, args.hotspot_ref_column
        )
        hotspot_summary = hotspot_overlap(
            pvrig_contact_residues, hotspots, args.pvrig_chain
        )
        cdr_summary = cdr_support(vhh_contact_residues, cdr_ranges)
        occlusion_summary = summarize_occlusion(
            vhh_atoms,
            ref_pvrl2_atoms,
            args.contact_cutoff,
            args.clash_cutoff,
        )
        pvrig_inventory = pose_chain_inventory(pose_atoms, args.pvrig_chain)
        vhh_inventory = pose_chain_inventory(pose_atoms, args.vhh_chain)
        ref_inventory = reference_pvrl2_inventory(
            reference_atoms, args.ref_pvrl2_chain
        )
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "scoring_semantics_version": SCORING_SEMANTICS_VERSION,
        "claim_boundary": CLAIM_BOUNDARY,
        "reference_pvrl2_selection": "protein ATOM heavy atoms only",
        "pose_pvrig_vhh_selection": "heavy ATOM and HETATM records",
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
        **flatten_reference_inventory(ref_inventory),
        "pvrig_vhh_contact_pair_count": len(contacts),
        "pvrig_contact_residue_count": len(pvrig_contact_residues),
        "vhh_contact_residue_count": len(vhh_contact_residues),
        "pvrig_contact_residues": sorted(
            pvrig_contact_residues, key=residue_sort_key
        ),
        "vhh_contact_residues": sorted(vhh_contact_residues, key=residue_sort_key),
        "pvrig_vhh_contacts": [contact.__dict__ for contact in contacts],
    }
    summary.update(hotspot_summary)
    summary.update(cdr_summary)
    summary.update(occlusion_summary)
    summary["record_inventory"] = {
        "pose": {
            "pvrig_chain": pvrig_inventory,
            "vhh_chain": vhh_inventory,
        },
        "reference_pvrl2_chain": ref_inventory,
    }
    summary["scorer_manifest"] = semantics_manifest()
    summary["notes"] = [
        "Reference PVRL2 occlusion uses protein ATOM heavy atoms only.",
        "Pose PVRIG and VHH retain legal heavy ATOM and HETATM records.",
        "All altloc records are retained; residue-pair metrics remain deduplicated.",
        "No classifier threshold is applied or changed by this scorer.",
    ]

    output_path = args.out_json or args.out_csv
    if args.out_json:
        write_json(args.out_json, summary)
    else:
        write_csv(args.out_csv, summary)
    print(f"Wrote V1.2 score report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
