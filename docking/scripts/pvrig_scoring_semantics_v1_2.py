#!/usr/bin/env python3
"""Shared record-selection contract for versioned PVRIG V1.2 scorers."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


SCORING_SEMANTICS_VERSION = "PVRIG_PVRL2_ATOM_ONLY_V1_2"
CLAIM_BOUNDARY = (
    "V1.2 protein-ATOM-only computational geometry scorer semantics; not a "
    "calibrated Docking Gold label, experimental binding truth, or blocking truth."
)
ZERO_DENOMINATOR_SEMANTICS = (
    "occlusion and residue-pair fractions are 0.0 when their protein-only "
    "denominator is zero"
)


@dataclass(frozen=True)
class Atom:
    record: str
    serial: int
    name: str
    altloc: str
    resname: str
    chain: str
    resseq: int
    icode: str
    x: float
    y: float
    z: float
    occupancy: float | None
    element: str

    @property
    def residue_id(self) -> str:
        return f"{self.chain}:{self.resseq}{self.icode.strip()}{self.resname}"

    @property
    def residue_key(self) -> tuple[str, int, str, str]:
        return (self.chain, self.resseq, self.icode.strip(), self.resname)


def parse_pdb(path: str | Path) -> list[Atom]:
    atoms: list[Atom] = []
    with Path(path).open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            record = line[:6].strip()
            if record not in {"ATOM", "HETATM"} or len(line) < 54:
                continue
            try:
                serial = int(line[6:11])
                name = line[12:16].strip()
                altloc = line[16].strip()
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
            occupancy_text = line[54:60].strip() if len(line) >= 60 else ""
            try:
                occupancy = float(occupancy_text) if occupancy_text else None
            except ValueError:
                occupancy = None
            atoms.append(
                Atom(
                    record=record,
                    serial=serial,
                    name=name,
                    altloc=altloc,
                    resname=resname,
                    chain=chain,
                    resseq=resseq,
                    icode=icode,
                    x=x,
                    y=y,
                    z=z,
                    occupancy=occupancy,
                    element=element,
                )
            )
    return atoms


def is_heavy_atom(atom: Atom) -> bool:
    element = atom.element.upper()
    if element:
        return element not in {"H", "D"}
    return not atom.name.upper().startswith(("H", "D"))


def select_pose_chain(atoms: Iterable[Atom], chain: str) -> list[Atom]:
    """Retain heavy ATOM and HETATM records for PVRIG/VHH pose chains."""
    return [atom for atom in atoms if atom.chain == chain and is_heavy_atom(atom)]


def select_reference_pvrl2_protein(atoms: Iterable[Atom], chain: str) -> list[Atom]:
    """Retain only protein ATOM heavy atoms for reference PVRL2 scoring."""
    return [
        atom
        for atom in atoms
        if atom.chain == chain and atom.record == "ATOM" and is_heavy_atom(atom)
    ]


def _residue_count(atoms: Iterable[Atom]) -> int:
    return len({atom.residue_key for atom in atoms})


def pose_chain_inventory(atoms: Sequence[Atom], chain: str) -> dict[str, Any]:
    chain_atoms = [atom for atom in atoms if atom.chain == chain]
    heavy = [atom for atom in chain_atoms if is_heavy_atom(atom)]
    atom_heavy = [atom for atom in heavy if atom.record == "ATOM"]
    hetatm_heavy = [atom for atom in heavy if atom.record == "HETATM"]
    altlocs = sorted({atom.altloc for atom in heavy if atom.altloc})
    return {
        "chain": chain,
        "selection_rule": "heavy ATOM and HETATM records retained for pose protein chains",
        "parsed_atom_and_hetatm_count": len(chain_atoms),
        "selected_heavy_atom_count": len(heavy),
        "selected_residue_count": _residue_count(heavy),
        "atom_heavy_atom_count": len(atom_heavy),
        "atom_residue_count": _residue_count(atom_heavy),
        "hetatm_heavy_atom_count": len(hetatm_heavy),
        "hetatm_residue_count": _residue_count(hetatm_heavy),
        "excluded_hydrogen_or_deuterium_count": len(chain_atoms) - len(heavy),
        "altloc_heavy_atom_count": sum(bool(atom.altloc) for atom in heavy),
        "altloc_labels": altlocs,
    }


def reference_pvrl2_inventory(atoms: Sequence[Atom], chain: str) -> dict[str, Any]:
    chain_atoms = [atom for atom in atoms if atom.chain == chain]
    heavy = [atom for atom in chain_atoms if is_heavy_atom(atom)]
    protein = [atom for atom in heavy if atom.record == "ATOM"]
    hetatm = [atom for atom in heavy if atom.record == "HETATM"]
    hoh = [atom for atom in hetatm if atom.resname == "HOH"]
    edo = [atom for atom in hetatm if atom.resname == "EDO"]
    other = [atom for atom in hetatm if atom.resname not in {"HOH", "EDO"}]
    altlocs = sorted({atom.altloc for atom in protein if atom.altloc})
    return {
        "chain": chain,
        "selection_rule": "protein ATOM heavy atoms only; all HETATM excluded",
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
        "excluded_hydrogen_or_deuterium_count": len(chain_atoms) - len(heavy),
        "atom_altloc_heavy_atom_count": sum(bool(atom.altloc) for atom in protein),
        "atom_altloc_labels": altlocs,
    }


def semantics_manifest() -> dict[str, Any]:
    return {
        "scoring_semantics_version": SCORING_SEMANTICS_VERSION,
        "reference_pvrl2_selection": "protein ATOM heavy atoms only",
        "pose_pvrig_vhh_selection": "heavy ATOM and HETATM records",
        "hydrogen_policy": "exclude elemental H and D; fall back to atom-name prefix",
        "altloc_policy": "retain all altloc records; residue-pair metrics remain residue-deduplicated",
        "claim_boundary": CLAIM_BOUNDARY,
    }


def flatten_reference_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        "ref_pvrl2_protein_atom_heavy_atom_count": inventory["protein_atom_heavy_atom_count"],
        "ref_pvrl2_protein_atom_residue_count": inventory["protein_atom_residue_count"],
        "ref_pvrl2_selected_protein_heavy_atom_count": inventory["selected_protein_heavy_atom_count"],
        "ref_pvrl2_selected_protein_residue_count": inventory["selected_protein_residue_count"],
        "ref_pvrl2_excluded_hetatm_heavy_atom_count": inventory["excluded_hetatm_heavy_atom_count"],
        "ref_pvrl2_excluded_hetatm_residue_count": inventory["excluded_hetatm_residue_count"],
        "ref_pvrl2_excluded_hoh_heavy_atom_count": inventory["excluded_hoh_heavy_atom_count"],
        "ref_pvrl2_excluded_hoh_residue_count": inventory["excluded_hoh_residue_count"],
        "ref_pvrl2_excluded_edo_heavy_atom_count": inventory["excluded_edo_heavy_atom_count"],
        "ref_pvrl2_excluded_edo_residue_count": inventory["excluded_edo_residue_count"],
        "ref_pvrl2_excluded_other_hetatm_heavy_atom_count": inventory[
            "excluded_other_hetatm_heavy_atom_count"
        ],
        "ref_pvrl2_excluded_other_hetatm_residue_count": inventory[
            "excluded_other_hetatm_residue_count"
        ],
        "ref_pvrl2_atom_altloc_heavy_atom_count": inventory["atom_altloc_heavy_atom_count"],
        "ref_pvrl2_atom_altloc_labels": ";".join(inventory["atom_altloc_labels"]),
    }


def flatten_pose_inventory(prefix: str, inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        f"{prefix}_selected_heavy_atom_count": inventory["selected_heavy_atom_count"],
        f"{prefix}_selected_residue_count": inventory["selected_residue_count"],
        f"{prefix}_atom_heavy_atom_count": inventory["atom_heavy_atom_count"],
        f"{prefix}_atom_residue_count": inventory["atom_residue_count"],
        f"{prefix}_hetatm_heavy_atom_count": inventory["hetatm_heavy_atom_count"],
        f"{prefix}_hetatm_residue_count": inventory["hetatm_residue_count"],
        f"{prefix}_altloc_heavy_atom_count": inventory["altloc_heavy_atom_count"],
        f"{prefix}_altloc_labels": ";".join(inventory["altloc_labels"]),
    }


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
