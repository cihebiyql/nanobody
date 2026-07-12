#!/usr/bin/env python3
"""Collect RFantibody ProteinMPNN outputs into a balanced 1,000-sequence pool."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pickle
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}
VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")
SETS = ("A", "B", "C", "D")
HOTSPOTS = {
    "A": "T57,T101,T106",
    "B": "T62,T101,T106",
    "C": "T97,T101,T105,T106",
    "D": "T33,T36,T105,T106",
}
UNIPROT = {
    "A": "R95,F139,W144",
    "B": "W100,F139,W144",
    "C": "K135,F139,S143,W144",
    "D": "S71,T74,S143,W144",
}
TAG_RE = re.compile(r"design_(\d+)_dldesign_(\d+)\.pdb$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("/data/qlyu/projects/pvrig_rfantibody_1000_20260712"),
    )
    parser.add_argument("--target-count", type=int, default=1000)
    parser.add_argument("--per-set", type=int, default=250)
    parser.add_argument("--initial-sibling-cap", type=int, default=5)
    return parser.parse_args()


def parse_pdb(path: Path) -> tuple[str, dict[str, str], list[str]]:
    residues: dict[tuple[str, int, str], str] = {}
    labels: dict[str, list[int]] = defaultdict(list)
    errors: list[str] = []

    for line in path.read_text().splitlines():
        if line.startswith("ATOM  ") and len(line) >= 27:
            if line[21] != "H" or line[12:16].strip() != "CA":
                continue
            altloc = line[16]
            if altloc not in (" ", "A"):
                continue
            key = (line[21], int(line[22:26]), line[26])
            aa = AA3_TO_1.get(line[17:20].strip())
            if aa is None:
                errors.append(f"unknown_residue:{line[17:20].strip()}")
                continue
            residues.setdefault(key, aa)
        elif line.startswith("REMARK PDBinfo-LABEL:"):
            parts = line.split()
            if len(parts) >= 4:
                labels[parts[-1]].append(int(parts[-2]))

    ordered = sorted(residues.items(), key=lambda item: (item[0][1], item[0][2]))
    sequence = "".join(aa for _, aa in ordered)
    by_resid = {key[1]: aa for key, aa in ordered}
    cdrs = {
        cdr: "".join(by_resid[n] for n in sorted(set(labels.get(cdr, []))) if n in by_resid)
        for cdr in ("H1", "H2", "H3")
    }

    if not sequence:
        errors.append("empty_H_chain")
    if set(sequence) - VALID_AA:
        errors.append("noncanonical_amino_acid")
    if not 105 <= len(sequence) <= 140:
        errors.append("unexpected_length")
    for cdr in ("H1", "H2", "H3"):
        if not cdrs[cdr]:
            errors.append(f"missing_{cdr}")

    return sequence, cdrs, errors


def load_trb(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        data = pickle.load(handle)
    plddt = data.get("plddt")
    final_plddt_mean = None
    if plddt is not None:
        try:
            final_plddt_mean = float(plddt[-1].mean())
        except (IndexError, TypeError, AttributeError):
            pass
    return {
        "rfd_mindist": float(data["mindist"]) if "mindist" in data else None,
        "rfd_averagemin": float(data["averagemin"]) if "averagemin" in data else None,
        "rfd_final_plddt_mean": final_plddt_mean,
        "h1_len": int(data["H1_len"]) if "H1_len" in data else None,
        "h2_len": int(data["H2_len"]) if "H2_len" in data else None,
        "h3_len": int(data["H3_len"]) if "H3_len" in data else None,
    }


def collect(run_root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for set_id in SETS:
        sequence_dir = run_root / "sets" / f"set_{set_id}" / "sequences"
        backbone_dir = run_root / "sets" / f"set_{set_id}" / "backbones"
        for pdb_path in sorted(sequence_dir.glob("design_*_dldesign_*.pdb")):
            match = TAG_RE.search(pdb_path.name)
            if not match:
                continue
            backbone_index, mpnn_index = map(int, match.groups())
            sequence, cdrs, errors = parse_pdb(pdb_path)
            backbone_path = backbone_dir / f"design_{backbone_index}.pdb"
            trb_path = backbone_dir / f"design_{backbone_index}.trb"
            trb = load_trb(trb_path) if trb_path.exists() else {}
            rows.append({
                "candidate_id": f"PVRIG_RFAb_v0_{set_id}_bb{backbone_index:03d}_mpn{mpnn_index:02d}",
                "hotspot_set": set_id,
                "hotspots_pdb": HOTSPOTS[set_id],
                "hotspots_uniprot": UNIPROT[set_id],
                "framework_id": "h-NbBCII10",
                "backbone_index": backbone_index,
                "mpnn_index": mpnn_index,
                "sequence": sequence,
                "sequence_length": len(sequence),
                "cdr1": cdrs["H1"],
                "cdr2": cdrs["H2"],
                "cdr3": cdrs["H3"],
                "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                "valid_sequence": not errors,
                "validation_errors": ";".join(sorted(set(errors))),
                "backbone_pdb": str(backbone_path),
                "backbone_trb": str(trb_path),
                "mpnn_pdb": str(pdb_path),
                "rf2_status": "not_run_by_generation_plan",
                "final_label": "PASS_SEQUENCE_GENERATION_NEEDS_RF2_DOCKING" if not errors else "FAIL_SEQUENCE_FORMAT",
                **trb,
            })
    return rows


def select_balanced(
    rows: list[dict[str, object]], per_set: int, initial_sibling_cap: int
) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    selected_hashes: set[str] = set()

    for set_id in SETS:
        candidates = [
            row for row in rows
            if row["hotspot_set"] == set_id and row["valid_sequence"]
        ]
        candidates.sort(key=lambda row: (row["mpnn_index"], row["backbone_index"]))
        set_selected: list[dict[str, object]] = []
        sibling_counts: Counter[int] = Counter()

        for cap in range(initial_sibling_cap, 9):
            for row in candidates:
                if len(set_selected) >= per_set:
                    break
                digest = str(row["sequence_sha256"])
                bb = int(row["backbone_index"])
                if digest in selected_hashes or sibling_counts[bb] >= cap:
                    continue
                selected_hashes.add(digest)
                sibling_counts[bb] += 1
                set_selected.append(row)
            if len(set_selected) >= per_set:
                break

        if len(set_selected) < per_set:
            raise RuntimeError(
                f"hotspot set {set_id} has only {len(set_selected)} selectable unique sequences; "
                "run a top-up before finalizing"
            )
        selected.extend(set_selected[:per_set])
    return selected


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise RuntimeError(f"No rows available for {path}")
    fields = list(rows[0].keys())
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    if args.target_count != args.per_set * len(SETS):
        raise SystemExit("target-count must equal per-set multiplied by four hotspot sets")

    final_dir = args.run_root / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    rows = collect(args.run_root)
    write_tsv(final_dir / "raw_candidates.tsv", rows)

    selected = select_balanced(rows, args.per_set, args.initial_sibling_cap)
    if len(selected) != args.target_count:
        raise RuntimeError(f"selected {len(selected)} rows, expected {args.target_count}")

    write_tsv(final_dir / "pvrig_rfantibody_1000.tsv", selected)
    with (final_dir / "pvrig_rfantibody_1000.fasta").open("w") as handle:
        for row in selected:
            handle.write(
                f">{row['candidate_id']}|hotspot_set={row['hotspot_set']}|"
                f"backbone={row['backbone_index']}|mpnn={row['mpnn_index']}|"
                "status=NEEDS_RF2_DOCKING\n"
            )
            handle.write(str(row["sequence"]) + "\n")

    raw_hash_counts = Counter(str(row["sequence_sha256"]) for row in rows if row["valid_sequence"])
    selected_by_set = Counter(str(row["hotspot_set"]) for row in selected)
    selected_by_backbone = Counter(
        (str(row["hotspot_set"]), int(row["backbone_index"])) for row in selected
    )
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_root": str(args.run_root),
        "raw_pdb_records": len(rows),
        "raw_valid_records": sum(bool(row["valid_sequence"]) for row in rows),
        "raw_unique_sequences": len(raw_hash_counts),
        "raw_duplicate_records": sum(count - 1 for count in raw_hash_counts.values()),
        "selected_records": len(selected),
        "selected_unique_sequences": len({row["sequence_sha256"] for row in selected}),
        "selected_by_hotspot_set": dict(sorted(selected_by_set.items())),
        "selected_unique_backbones": len(selected_by_backbone),
        "selected_max_siblings_per_backbone": max(selected_by_backbone.values()),
        "rf2_status": "not_run_by_generation_plan",
        "scientific_boundary": "Generated hotspot-conditioned candidates are not validated binders or blockers.",
    }
    (final_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    manifest = []
    for path in sorted(final_dir.glob("*")):
        if path.is_file() and path.name != "sha256sums.txt":
            manifest.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (final_dir / "sha256sums.txt").write_text("\n".join(manifest) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
