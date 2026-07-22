#!/usr/bin/env python3
"""Add RFantibody PDBinfo CDR labels to normalized positive complex poses."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path


AA3 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def h_sequence(lines: list[str]) -> str:
    residues = []
    for line in lines:
        if line.startswith("ATOM") and line[12:16].strip() == "CA" and line[21] == "H":
            residues.append(AA3[line[17:20]])
    return "".join(residues)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pose-table", type=Path, required=True)
    parser.add_argument("--pose-root", type=Path, required=True)
    parser.add_argument("--cdr-table", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output-table", type=Path, required=True)
    args = parser.parse_args()
    if args.output_root.exists() or args.output_table.exists():
        raise FileExistsError("refusing to overwrite labeled pose outputs")
    cdrs = {row["record_id"]: row for row in read_tsv(args.cdr_table)}
    rows = read_tsv(args.pose_table)
    output_rows = []
    args.output_root.mkdir(parents=True)
    for row in rows:
        source = args.pose_root / row["normalized_pose_relpath"]
        lines = source.read_text(encoding="ascii", errors="strict").splitlines()
        sequence = h_sequence(lines)
        known = cdrs[row["source_candidate_id"]]
        remarks = []
        for loop, field in (("H1", "cdr1"), ("H2", "cdr2"), ("H3", "cdr3")):
            segment = known[field]
            if sequence.count(segment) != 1:
                raise ValueError(f"{row['pose_id']} {loop} is not uniquely present in H sequence")
            start = sequence.index(segment) + 1
            remarks.extend(f"REMARK PDBinfo-LABEL:{position:5d} {loop}" for position in range(start, start + len(segment)))
        output = args.output_root / source.name
        body = [line for line in lines if not line.startswith("REMARK PDBinfo-LABEL") and line != "END"]
        output.write_text("\n".join(body + remarks + ["END", ""]) , encoding="ascii")
        updated = dict(row)
        updated["normalized_pose_relpath"] = str(output.relative_to(args.pose_root))
        updated["normalized_pose_sha256"] = digest(output)
        updated["cdr_label_status"] = "EXACT_SEQUENCE_MATCH_3_OF_3"
        output_rows.append(updated)
    args.output_table.parent.mkdir(parents=True, exist_ok=True)
    with args.output_table.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(output_rows)
    print(f"labeled_poses={len(output_rows)} sources={len({r['source_candidate_id'] for r in output_rows})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
