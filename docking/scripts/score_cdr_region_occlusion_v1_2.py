#!/usr/bin/env python3
"""Quantify VHH-region occlusion using V1.2 protein-ATOM-only PVRL2 semantics."""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pvrig_scoring_semantics_v1_2 import (
    Atom,
    CLAIM_BOUNDARY,
    SCORING_SEMANTICS_VERSION,
    ZERO_DENOMINATOR_SEMANTICS,
    flatten_pose_inventory,
    flatten_reference_inventory,
    semantics_manifest,
    write_json,
)


SCHEMA_VERSION = "cdr_region_occlusion_score_v1_2"
REGION_ORDER = ("CDR3", "CDR1", "CDR2", "framework")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pose-pdb", required=True)
    parser.add_argument("--reference-pdb", required=True)
    parser.add_argument("--vhh-chain", required=True)
    parser.add_argument("--ref-pvrl2-chain", required=True)
    parser.add_argument("--cdr1", default="26-35")
    parser.add_argument("--cdr2", default="53-59")
    parser.add_argument("--cdr3", default="98-116")
    parser.add_argument("--contact-cutoff", type=float, default=4.5)
    parser.add_argument("--clash-cutoff", type=float, default=2.5)
    parser.add_argument("--out-json")
    parser.add_argument("--out-csv")
    args = parser.parse_args(argv)
    if bool(args.out_json) == bool(args.out_csv):
        parser.error("Provide exactly one of --out-json or --out-csv.")
    if (
        not math.isfinite(args.contact_cutoff)
        or not math.isfinite(args.clash_cutoff)
        or args.contact_cutoff <= 0
        or args.clash_cutoff <= 0
    ):
        parser.error("Cutoffs must be positive finite numbers.")
    return args


def parse_range(spec: str) -> set[int]:
    values: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError(f"Invalid descending residue range {part!r}")
            values.update(range(start, end + 1))
        else:
            values.add(int(part))
    if not values:
        raise ValueError(f"Empty residue range {spec!r}")
    return values


def atom_element(line: str) -> str:
    element = line[76:78].strip() if len(line) >= 78 else ""
    if element:
        return element.upper()
    return "".join(char for char in line[12:16].strip() if char.isalpha())[:1].upper()


def parse_region_pdb(path: Path) -> list[Atom]:
    """Preserve the V1.1 region scorer's coordinate fallback while recording record type."""
    atoms: list[Atom] = []
    for line in path.read_text(errors="replace").splitlines():
        record = line[:6].strip()
        if record not in {"ATOM", "HETATM"} or len(line) < 54:
            continue
        try:
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
        except ValueError:
            parts = line.split()
            if len(parts) < 9:
                continue
            try:
                x, y, z = float(parts[6]), float(parts[7]), float(parts[8])
            except ValueError:
                continue
        try:
            serial = int(line[6:11])
            resseq = int(line[22:26])
        except ValueError:
            continue
        occupancy_text = line[54:60].strip() if len(line) >= 60 else ""
        try:
            occupancy = float(occupancy_text) if occupancy_text else None
        except ValueError:
            occupancy = None
        atoms.append(
            Atom(
                record=record,
                serial=serial,
                name=line[12:16].strip(),
                altloc=line[16].strip(),
                resname=line[17:20].strip(),
                chain=line[21].strip() or "_",
                resseq=resseq,
                icode=line[26].strip(),
                x=x,
                y=y,
                z=z,
                occupancy=occupancy,
                element=atom_element(line),
            )
        )
    return atoms


def region_v1_1_heavy_atom(atom: Atom) -> bool:
    """Preserve V1.1 region-scorer behavior: exclude H, but not D."""
    return atom.element.upper() != "H"


def select_region_pose_chain(atoms: Sequence[Atom], chain: str) -> list[Atom]:
    return [
        atom for atom in atoms if atom.chain == chain and region_v1_1_heavy_atom(atom)
    ]


def select_region_reference_pvrl2_protein(
    atoms: Sequence[Atom], chain: str
) -> list[Atom]:
    return [
        atom
        for atom in atoms
        if atom.chain == chain
        and atom.record == "ATOM"
        and region_v1_1_heavy_atom(atom)
    ]


def _residue_count(atoms: Sequence[Atom]) -> int:
    return len({atom.residue_key for atom in atoms})


def region_pose_inventory(atoms: Sequence[Atom], chain: str) -> dict[str, Any]:
    chain_atoms = [atom for atom in atoms if atom.chain == chain]
    selected = [atom for atom in chain_atoms if region_v1_1_heavy_atom(atom)]
    atom_records = [atom for atom in selected if atom.record == "ATOM"]
    hetatm_records = [atom for atom in selected if atom.record == "HETATM"]
    return {
        "chain": chain,
        "selection_rule": "V1.1-compatible H-only exclusion; heavy ATOM and HETATM pose records retained",
        "parsed_atom_and_hetatm_count": len(chain_atoms),
        "selected_heavy_atom_count": len(selected),
        "selected_residue_count": _residue_count(selected),
        "atom_heavy_atom_count": len(atom_records),
        "atom_residue_count": _residue_count(atom_records),
        "hetatm_heavy_atom_count": len(hetatm_records),
        "hetatm_residue_count": _residue_count(hetatm_records),
        "excluded_hydrogen_count": len(chain_atoms) - len(selected),
        "altloc_heavy_atom_count": sum(bool(atom.altloc) for atom in selected),
        "altloc_labels": sorted({atom.altloc for atom in selected if atom.altloc}),
    }


def region_reference_inventory(atoms: Sequence[Atom], chain: str) -> dict[str, Any]:
    chain_atoms = [atom for atom in atoms if atom.chain == chain]
    selected_by_h_policy = [
        atom for atom in chain_atoms if region_v1_1_heavy_atom(atom)
    ]
    protein = [atom for atom in selected_by_h_policy if atom.record == "ATOM"]
    hetatm = [atom for atom in selected_by_h_policy if atom.record == "HETATM"]
    hoh = [atom for atom in hetatm if atom.resname == "HOH"]
    edo = [atom for atom in hetatm if atom.resname == "EDO"]
    other = [atom for atom in hetatm if atom.resname not in {"HOH", "EDO"}]
    return {
        "chain": chain,
        "selection_rule": "protein ATOM records with V1.1-compatible H-only exclusion; all HETATM excluded",
        "parsed_atom_and_hetatm_count": len(chain_atoms),
        "protein_atom_heavy_atom_count": len(protein),
        "protein_atom_residue_count": _residue_count(protein),
        "selected_protein_heavy_atom_count": len(protein),
        "selected_protein_residue_count": _residue_count(protein),
        "excluded_hetatm_heavy_atom_count": len(hetatm),
        "excluded_hetatm_residue_count": _residue_count(hetatm),
        "excluded_hoh_heavy_atom_count": len(hoh),
        "excluded_hoh_residue_count": _residue_count(hoh),
        "excluded_edo_heavy_atom_count": len(edo),
        "excluded_edo_residue_count": _residue_count(edo),
        "excluded_other_hetatm_heavy_atom_count": len(other),
        "excluded_other_hetatm_residue_count": _residue_count(other),
        "excluded_hydrogen_count": len(chain_atoms) - len(selected_by_h_policy),
        "atom_altloc_heavy_atom_count": sum(bool(atom.altloc) for atom in protein),
        "atom_altloc_labels": sorted({atom.altloc for atom in protein if atom.altloc}),
    }


def dist2(left: Atom, right: Atom) -> float:
    return (
        (left.x - right.x) ** 2
        + (left.y - right.y) ** 2
        + (left.z - right.z) ** 2
    )


def region_name(
    resseq: int,
    cdr1: set[int],
    cdr2: set[int],
    cdr3: set[int],
) -> str:
    if resseq in cdr3:
        return "CDR3"
    if resseq in cdr1:
        return "CDR1"
    if resseq in cdr2:
        return "CDR2"
    return "framework"


def summarize_contacts(
    vhh_atoms: list[Atom],
    pvrl2_atoms: list[Atom],
    cutoff: float,
    clash_cutoff: float,
    cdr1: set[int],
    cdr2: set[int],
    cdr3: set[int],
) -> tuple[dict[str, dict[str, Any]], int, int, int, int]:
    cutoff2 = cutoff * cutoff
    clash2 = clash_cutoff * clash_cutoff
    stats: dict[str, dict[str, Any]] = {
        region: {
            "occluding_atom_contact_count": 0,
            "occluding_residue_pair_count": 0,
            "clash_atom_contact_count": 0,
            "clash_residue_pair_count": 0,
            "vhh_residues": set(),
            "pvrl2_residues": set(),
            "occluding_residue_pairs": set(),
            "clash_residue_pairs": set(),
            "min_distance_a": None,
        }
        for region in REGION_ORDER
    }
    total_atom_contacts = 0
    total_atom_clashes = 0
    all_pairs: set[tuple[str, str]] = set()
    all_clash_pairs: set[tuple[str, str]] = set()
    for vhh_atom in vhh_atoms:
        region = region_name(vhh_atom.resseq, cdr1, cdr2, cdr3)
        for pvrl2_atom in pvrl2_atoms:
            distance_squared = dist2(vhh_atom, pvrl2_atom)
            if distance_squared > cutoff2:
                continue
            distance = math.sqrt(distance_squared)
            pair = (vhh_atom.residue_id, pvrl2_atom.residue_id)
            total_atom_contacts += 1
            stats[region]["occluding_atom_contact_count"] += 1
            stats[region]["vhh_residues"].add(vhh_atom.residue_id)
            stats[region]["pvrl2_residues"].add(pvrl2_atom.residue_id)
            stats[region]["occluding_residue_pairs"].add(pair)
            all_pairs.add(pair)
            minimum = stats[region]["min_distance_a"]
            if minimum is None or distance < minimum:
                stats[region]["min_distance_a"] = distance
            if distance_squared <= clash2:
                total_atom_clashes += 1
                stats[region]["clash_atom_contact_count"] += 1
                stats[region]["clash_residue_pairs"].add(pair)
                all_clash_pairs.add(pair)

    for region in REGION_ORDER:
        item = stats[region]
        item["occluding_residue_pair_count"] = len(item["occluding_residue_pairs"])
        item["clash_residue_pair_count"] = len(item["clash_residue_pairs"])
        item["vhh_residue_count"] = len(item["vhh_residues"])
        item["pvrl2_residue_count"] = len(item["pvrl2_residues"])
        item["occluding_residue_pairs"] = [
            f"{left}--{right}" for left, right in sorted(item["occluding_residue_pairs"])
        ]
        item["clash_residue_pairs"] = [
            f"{left}--{right}" for left, right in sorted(item["clash_residue_pairs"])
        ]
        item["vhh_residues"] = sorted(item["vhh_residues"])
        item["pvrl2_residues"] = sorted(item["pvrl2_residues"])
        item["occlusion_fraction_of_total"] = (
            item["occluding_atom_contact_count"] / total_atom_contacts
            if total_atom_contacts
            else 0.0
        )
        item["occluding_residue_pair_fraction_of_total"] = (
            item["occluding_residue_pair_count"] / len(all_pairs) if all_pairs else 0.0
        )
        item["clash_fraction_of_total"] = (
            item["clash_atom_contact_count"] / total_atom_clashes
            if total_atom_clashes
            else 0.0
        )
        item["clash_residue_pair_fraction_of_total"] = (
            item["clash_residue_pair_count"] / len(all_clash_pairs)
            if all_clash_pairs
            else 0.0
        )
    return (
        stats,
        total_atom_contacts,
        total_atom_clashes,
        len(all_pairs),
        len(all_clash_pairs),
    )


def write_csv(
    path: Path,
    report: dict[str, Any],
    flattened_inventory: dict[str, Any],
) -> None:
    fields = [
        "schema_version",
        "scoring_semantics_version",
        "claim_boundary",
        "reference_pvrl2_selection",
        *flattened_inventory,
        "pose_pdb",
        "reference_pdb",
        "vhh_chain",
        "ref_pvrl2_chain",
        "contact_cutoff_a",
        "clash_cutoff_a",
        "region",
        "occluding_atom_contact_count",
        "occlusion_fraction_of_total",
        "occluding_residue_pair_count",
        "occluding_residue_pair_fraction_of_total",
        "clash_atom_contact_count",
        "clash_fraction_of_total",
        "clash_residue_pair_count",
        "clash_residue_pair_fraction_of_total",
        "vhh_residue_count",
        "pvrl2_residue_count",
        "min_distance_a",
        "vhh_residues",
        "pvrl2_residues",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for region in REGION_ORDER:
            item = report["regions"][region]
            writer.writerow(
                {
                    "schema_version": report["schema_version"],
                    "scoring_semantics_version": report["scoring_semantics_version"],
                    "claim_boundary": report["claim_boundary"],
                    "reference_pvrl2_selection": report["reference_pvrl2_selection"],
                    **flattened_inventory,
                    "pose_pdb": report["pose_pdb"],
                    "reference_pdb": report["reference_pdb"],
                    "vhh_chain": report["vhh_chain"],
                    "ref_pvrl2_chain": report["ref_pvrl2_chain"],
                    "contact_cutoff_a": report["contact_cutoff_a"],
                    "clash_cutoff_a": report["clash_cutoff_a"],
                    "region": region,
                    "occluding_atom_contact_count": item["occluding_atom_contact_count"],
                    "occlusion_fraction_of_total": item["occlusion_fraction_of_total"],
                    "occluding_residue_pair_count": item["occluding_residue_pair_count"],
                    "occluding_residue_pair_fraction_of_total": item[
                        "occluding_residue_pair_fraction_of_total"
                    ],
                    "clash_atom_contact_count": item["clash_atom_contact_count"],
                    "clash_fraction_of_total": item["clash_fraction_of_total"],
                    "clash_residue_pair_count": item["clash_residue_pair_count"],
                    "clash_residue_pair_fraction_of_total": item[
                        "clash_residue_pair_fraction_of_total"
                    ],
                    "vhh_residue_count": item["vhh_residue_count"],
                    "pvrl2_residue_count": item["pvrl2_residue_count"],
                    "min_distance_a": item["min_distance_a"],
                    "vhh_residues": ";".join(item["vhh_residues"]),
                    "pvrl2_residues": ";".join(item["pvrl2_residues"]),
                }
            )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        cdr1 = parse_range(args.cdr1)
        cdr2 = parse_range(args.cdr2)
        cdr3 = parse_range(args.cdr3)
        pose_path = Path(args.pose_pdb)
        reference_path = Path(args.reference_pdb)
        pose_atoms = parse_region_pdb(pose_path)
        reference_atoms = parse_region_pdb(reference_path)
        vhh_atoms = select_region_pose_chain(pose_atoms, args.vhh_chain)
        pvrl2_atoms = select_region_reference_pvrl2_protein(
            reference_atoms, args.ref_pvrl2_chain
        )
        if not vhh_atoms:
            raise ValueError(f"No VHH heavy atoms for chain {args.vhh_chain!r}")
        if not pvrl2_atoms:
            raise ValueError(
                f"No reference PVRL2 protein ATOM heavy atoms for chain {args.ref_pvrl2_chain!r}"
            )
        stats, total_occ, total_clash, total_pairs, total_clash_pairs = summarize_contacts(
            vhh_atoms,
            pvrl2_atoms,
            args.contact_cutoff,
            args.clash_cutoff,
            cdr1,
            cdr2,
            cdr3,
        )
        vhh_inventory = region_pose_inventory(pose_atoms, args.vhh_chain)
        ref_inventory = region_reference_inventory(
            reference_atoms, args.ref_pvrl2_chain
        )
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    flattened_inventory = {
        **flatten_pose_inventory("pose_vhh", vhh_inventory),
        **flatten_reference_inventory(ref_inventory),
    }
    scorer_manifest = semantics_manifest()
    scorer_manifest["hydrogen_policy"] = (
        "preserve V1.1 region-scorer behavior: exclude element H only; D records remain"
    )
    scorer_manifest["parser_compatibility"] = (
        "preserve V1.1 fixed-column parsing with whitespace coordinate fallback"
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "scoring_semantics_version": SCORING_SEMANTICS_VERSION,
        "claim_boundary": CLAIM_BOUNDARY,
        "reference_pvrl2_selection": (
            "protein ATOM records only with V1.1-compatible H-only exclusion"
        ),
        "pose_vhh_selection": (
            "ATOM and HETATM records with V1.1-compatible H-only exclusion"
        ),
        "inventory_hydrogen_policy": "element H excluded; D retained to preserve V1.1 region semantics",
        "zero_denominator_semantics": ZERO_DENOMINATOR_SEMANTICS,
        "pose_pdb": str(pose_path),
        "reference_pdb": str(reference_path),
        "vhh_chain": args.vhh_chain,
        "ref_pvrl2_chain": args.ref_pvrl2_chain,
        "contact_cutoff_a": args.contact_cutoff,
        "clash_cutoff_a": args.clash_cutoff,
        "cdr_ranges": {"CDR1": args.cdr1, "CDR2": args.cdr2, "CDR3": args.cdr3},
        **flattened_inventory,
        "total_occluding_atom_contact_count": total_occ,
        "total_clash_atom_contact_count": total_clash,
        "total_occluding_residue_pair_count": total_pairs,
        "total_clash_residue_pair_count": total_clash_pairs,
        "regions": stats,
        "record_inventory": {
            "pose": {"vhh_chain": vhh_inventory},
            "reference_pvrl2_chain": ref_inventory,
        },
        "scorer_manifest": scorer_manifest,
        "notes": [
            "Reference PVRL2 contacts use protein ATOM heavy atoms only.",
            "Pose VHH retains legal heavy ATOM and HETATM records.",
            "All altloc records are retained; residue-pair metrics remain deduplicated.",
            "The V1.1 region scorer's H-only and coordinate-fallback parser behavior is preserved.",
            "No classifier threshold is applied or changed by this scorer.",
        ],
    }
    if args.out_json:
        write_json(args.out_json, report)
    else:
        write_csv(Path(args.out_csv), report, flattened_inventory)
    print(
        json.dumps(
            {
                "scoring_semantics_version": SCORING_SEMANTICS_VERSION,
                "pose_pdb": str(pose_path),
                "total_occluding_atom_contact_count": total_occ,
                "total_occluding_residue_pair_count": total_pairs,
                "excluded_reference_hetatm_heavy_atom_count": ref_inventory[
                    "excluded_hetatm_heavy_atom_count"
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
