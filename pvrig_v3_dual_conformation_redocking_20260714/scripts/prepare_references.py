#!/usr/bin/env python3
"""Normalize PVRIG/PVRL2 reference structures for deterministic V3 scoring."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

from common import atomic_write_text, is_standard_atom_line, project_root, sha256_file, write_json, write_tsv

REFERENCE_CONFIG = {
    "8x6b": {
        "source": Path("inputs/source/8X6B.pdb"),
        "pvrig_chain": "B",
        "pvrl2_chain": "A",
        "pvrig_offset": 38,
    },
    "9e6y": {
        "source": Path("inputs/source/9E6Y.pdb"),
        "pvrig_chain": "A",
        "pvrl2_chain": "D",
        "pvrig_offset": 40,
    },
}
HOTSPOT_SOURCE = Path("inputs/source/PVRIG_hotspot_set_v1.csv")
NORMALIZED_DIR = Path("inputs/normalized")
SUMMARY_PATH = Path("reports/reference_normalization_summary.json")
HOTSPOT_OUTPUT = Path("inputs/normalized/interface_hotspots_uniprot.tsv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=project_root(), help="Project root")
    return parser.parse_args()


def normalize_atom_line(line: str, chain: str, residue_number: int, serial: int) -> str:
    # PDB columns are fixed-width; preserve coordinates/atom identity and rewrite serial/chain/residue.
    return f"ATOM  {serial:5d}{line[11:21]}{chain}{residue_number:4d}{line[26:66]}{line[66:]}".rstrip() + "\n"


def normalize_reference(root: Path, reference_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    source = root / cfg["source"]
    if not source.exists():
        raise FileNotFoundError(source)

    receptor_lines: list[str] = []
    tl_lines: list[str] = []
    residue_seen: set[tuple[str, int, str]] = set()
    atom_count = 0
    receptor_atom_count = 0
    serial = 1

    for raw in source.read_text(encoding="utf-8", errors="replace").splitlines(True):
        if not is_standard_atom_line(raw):
            continue
        source_chain = raw[21]
        if source_chain == cfg["pvrig_chain"]:
            residue_number = int(raw[22:26]) + int(cfg["pvrig_offset"])
            out = normalize_atom_line(raw, "T", residue_number, serial)
            receptor_lines.append(out)
            tl_lines.append(out)
            receptor_atom_count += 1
            atom_count += 1
            residue_seen.add(("T", residue_number, raw[17:20].strip()))
            serial += 1
        elif source_chain == cfg["pvrl2_chain"]:
            residue_number = int(raw[22:26])
            out = normalize_atom_line(raw, "L", residue_number, serial)
            tl_lines.append(out)
            atom_count += 1
            residue_seen.add(("L", residue_number, raw[17:20].strip()))
            serial += 1

    if not receptor_lines or not tl_lines:
        raise ValueError(f"{reference_id}: no normalized atoms produced")

    receptor_text = "".join(receptor_lines) + "TER\nEND\n"
    tl_text = "".join(tl_lines) + "TER\nEND\n"
    receptor_path = root / NORMALIZED_DIR / f"{reference_id}_pvrig_receptor.pdb"
    tl_path = root / NORMALIZED_DIR / f"{reference_id}_TL_reference.pdb"
    atomic_write_text(receptor_path, receptor_text)
    atomic_write_text(tl_path, tl_text)

    return {
        "source": str(cfg["source"]),
        "source_sha256": sha256_file(source),
        "pvrig_chain": "T",
        "pvrl2_chain": "L",
        "pvrig_offset_applied": cfg["pvrig_offset"],
        "outputs": {
            "receptor_only": {
                "path": str(receptor_path.relative_to(root)),
                "sha256": sha256_file(receptor_path),
                "atom_count": receptor_atom_count,
                "residue_count": len({item for item in residue_seen if item[0] == "T"}),
            },
            "tl_reference": {
                "path": str(tl_path.relative_to(root)),
                "sha256": sha256_file(tl_path),
                "atom_count": atom_count,
                "residue_count": len(residue_seen),
            },
        },
    }


def load_hotspots(root: Path) -> tuple[dict[str, Any], list[dict[str, object]]]:
    path = root / HOTSPOT_SOURCE
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row["hotspot_class"] in {"core_hotspot", "secondary_hotspot"}:
                rows.append(row)
    unique: dict[int, dict[str, str]] = {}
    for row in rows:
        unique[int(row["uniprot_position"])] = row
    ordered = sorted(unique.values(), key=lambda row: int(row["alignment_col"]))
    anchors = [row for idx, row in enumerate(ordered) if idx % 2 == 0]
    holdouts = [row for idx, row in enumerate(ordered) if idx % 2 == 1]
    if len(ordered) != 23 or len(anchors) != 12 or len(holdouts) != 11:
        raise ValueError(
            f"unexpected hotspot split: total={len(ordered)} anchors={len(anchors)} holdouts={len(holdouts)}"
        )
    split_rows: list[dict[str, object]] = []
    anchor_positions = {int(row["uniprot_position"]) for row in anchors}
    for row in ordered:
        position = int(row["uniprot_position"])
        split_rows.append(
            {
                "alignment_col": int(row["alignment_col"]),
                "uniprot_position": position,
                "uniprot_aa": row["uniprot_aa"],
                "hotspot_id": row["hotspot_id"],
                "hotspot_class": row["hotspot_class"],
                "priority_weight": row["priority_weight"],
                "restraint_role": "AIR_ANCHOR" if position in anchor_positions else "SCORING_HOLDOUT",
                "pdb_8x6b_ref": row["pdb_8x6b_ref"],
                "pdb_9e6y_ref": row["pdb_9e6y_ref"],
            }
        )
    write_tsv(
        root / HOTSPOT_OUTPUT,
        split_rows,
        [
            "alignment_col",
            "uniprot_position",
            "uniprot_aa",
            "hotspot_id",
            "hotspot_class",
            "priority_weight",
            "restraint_role",
            "pdb_8x6b_ref",
            "pdb_9e6y_ref",
        ],
    )
    summary = {
        "source": str(HOTSPOT_SOURCE),
        "source_sha256": sha256_file(path),
        "normalized_table": str(HOTSPOT_OUTPUT),
        "normalized_table_sha256": sha256_file(root / HOTSPOT_OUTPUT),
        "split_algorithm": "sort_alignment_col_then_even_index_anchor",
        "soft_hint_rows_excluded": True,
        "unique_interface_residue_count": len(ordered),
        "air_anchor_count": len(anchors),
        "holdout_count": len(holdouts),
        "all_uniprot_positions": [int(row["uniprot_position"]) for row in ordered],
        "air_anchor_uniprot_positions": [int(row["uniprot_position"]) for row in anchors],
        "holdout_uniprot_positions": [int(row["uniprot_position"]) for row in holdouts],
    }
    return summary, split_rows


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    try:
        references = {
            reference_id: normalize_reference(root, reference_id, cfg)
            for reference_id, cfg in sorted(REFERENCE_CONFIG.items())
        }
        hotspot_summary, _hotspot_rows = load_hotspots(root)
        summary = {
            "schema_version": 1,
            "numbering": "UniProt_Q6DKI7",
            "atom_filter": "standard_amino_acid_ATOM_only",
            "references": references,
            "hotspots": hotspot_summary,
        }
        write_json(root / SUMMARY_PATH, summary)
    except Exception as exc:  # pragma: no cover - exercised through subprocess failure paths.
        print(f"prepare_references failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
