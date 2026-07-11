#!/usr/bin/env python3
"""Normalize a monomer PDB to one chain with sequential residue numbers."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in-pdb", required=True, type=Path)
    parser.add_argument("--out-pdb", required=True, type=Path)
    parser.add_argument("--chain-id", default="A", help="Target chain ID. Default: A")
    parser.add_argument("--source-chain", help="Optional source chain filter.")
    parser.add_argument("--start-resi", type=int, default=1, help="First residue number. Default: 1")
    parser.add_argument(
        "--expected-residue-count",
        type=int,
        help="Fail if the number of ATOM/HETATM residues differs from this value.",
    )
    return parser.parse_args()


def normalize_line(line: str, chain_id: str, resi: int) -> str:
    padded = line.rstrip("\n").ljust(80)
    return f"{padded[:21]}{chain_id}{resi:4d} {padded[27:]}\n"


def main() -> None:
    args = parse_args()
    if len(args.chain_id) != 1:
        raise SystemExit("--chain-id must be exactly one character")
    if args.source_chain and len(args.source_chain) != 1:
        raise SystemExit("--source-chain must be exactly one character")

    residue_map: dict[tuple[str, str, str], int] = {}
    next_resi = args.start_resi
    output_lines: list[str] = []
    atom_lines = 0

    for line in args.in_pdb.read_text(encoding="utf-8", errors="replace").splitlines(True):
        record = line[:6]
        if record not in {"ATOM  ", "HETATM"}:
            output_lines.append(line)
            continue
        padded = line.rstrip("\n").ljust(80)
        source_chain = padded[21]
        if args.source_chain and source_chain != args.source_chain:
            output_lines.append(line)
            continue
        residue_key = (source_chain, padded[22:26], padded[26])
        if residue_key not in residue_map:
            residue_map[residue_key] = next_resi
            next_resi += 1
        output_lines.append(normalize_line(line, args.chain_id, residue_map[residue_key]))
        atom_lines += 1

    residue_count = len(residue_map)
    if atom_lines == 0:
        raise SystemExit(f"no ATOM/HETATM records found in {args.in_pdb}")
    if args.expected_residue_count is not None and residue_count != args.expected_residue_count:
        raise SystemExit(
            f"residue count mismatch for {args.in_pdb}: "
            f"observed={residue_count} expected={args.expected_residue_count}"
        )

    args.out_pdb.parent.mkdir(parents=True, exist_ok=True)
    args.out_pdb.write_text("".join(output_lines), encoding="utf-8")
    print(f"normalized_pdb={args.out_pdb}")
    print(f"residue_count={residue_count}")
    print(f"atom_lines={atom_lines}")


if __name__ == "__main__":
    main()
