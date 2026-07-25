#!/usr/bin/env python3
"""Convert a validated single-chain VHH PDB into RFantibody HLT format."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence


def parse_range(value: str) -> tuple[int, int]:
    parts = value.split("-", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid residue range: {value}")
    start, end = (int(part) for part in parts)
    if start <= 0 or end < start:
        raise ValueError(f"Invalid residue range: {value}")
    return start, end


def atom_residue_key(line: str) -> tuple[str, str]:
    return line[22:26], line[26:27]


def build_hlt(
    input_pdb: Path,
    output_pdb: Path,
    input_chain: str,
    expected_residues: int,
    cdr_ranges: dict[str, tuple[int, int]],
    audit_path: Path | None = None,
) -> dict[str, object]:
    atoms = [
        line
        for line in input_pdb.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.startswith("ATOM") and len(line) >= 27 and line[21:22] == input_chain
    ]
    if not atoms:
        raise ValueError(f"No ATOM records found for chain {input_chain}")
    residue_order: list[tuple[str, str]] = []
    for line in atoms:
        key = atom_residue_key(line)
        if not residue_order or residue_order[-1] != key:
            residue_order.append(key)
    if len(residue_order) != expected_residues:
        raise ValueError(f"Expected {expected_residues} residues, found {len(residue_order)}")
    for name, (start, end) in cdr_ranges.items():
        if end > expected_residues:
            raise ValueError(f"{name} range exceeds residue count: {start}-{end} > {expected_residues}")
    ordered_ranges = [cdr_ranges[name] for name in ("H1", "H2", "H3")]
    if not (ordered_ranges[0][1] < ordered_ranges[1][0] and ordered_ranges[1][1] < ordered_ranges[2][0]):
        raise ValueError(f"CDR ranges overlap or are out of order: {cdr_ranges}")

    residue_to_index = {key: index for index, key in enumerate(residue_order, start=1)}
    output_lines: list[str] = []
    for line in atoms:
        index = residue_to_index[atom_residue_key(line)]
        padded = line.ljust(80)
        output_lines.append(f"{padded[:21]}H{index:4d} {padded[27:]}".rstrip())
    labels: list[tuple[int, str]] = []
    for name in ("H1", "H2", "H3"):
        start, end = cdr_ranges[name]
        for residue in range(start, end + 1):
            labels.append((residue, name))
            output_lines.append(f"REMARK PDBinfo-LABEL: {residue:4d} {name}")
    output_pdb.parent.mkdir(parents=True, exist_ok=True)
    output_pdb.write_text("\n".join(output_lines) + "\n", encoding="utf-8")

    audit: dict[str, object] = {
        "status": "PASS_HLT_FRAMEWORK_READY",
        "input_pdb": str(input_pdb),
        "output_pdb": str(output_pdb),
        "input_chain": input_chain,
        "output_chain": "H",
        "residue_count": len(residue_order),
        "atom_count": len(atoms),
        "cdr_ranges": {name: f"{start}-{end}" for name, (start, end) in cdr_ranges.items()},
        "cdr_label_count": len(labels),
        "claim_boundary": "predicted_parent_structure_for_rfantibody_generation_not_binding_truth",
    }
    if audit_path is not None:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-pdb", type=Path, required=True)
    parser.add_argument("--output-pdb", type=Path, required=True)
    parser.add_argument("--input-chain", default="H")
    parser.add_argument("--expected-residues", type=int, required=True)
    parser.add_argument("--h1", required=True)
    parser.add_argument("--h2", required=True)
    parser.add_argument("--h3", required=True)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args(argv)
    if len(args.input_chain) != 1 or args.expected_residues <= 0:
        parser.error("Require a one-character chain and positive residue count")
    return args


def main() -> None:
    args = parse_args()
    audit = build_hlt(
        args.input_pdb,
        args.output_pdb,
        args.input_chain,
        args.expected_residues,
        {"H1": parse_range(args.h1), "H2": parse_range(args.h2), "H3": parse_range(args.h3)},
        args.audit,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
