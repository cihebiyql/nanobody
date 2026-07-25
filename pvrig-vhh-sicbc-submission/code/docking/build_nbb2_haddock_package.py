#!/usr/bin/env python3
"""Build a resumable NanoBodyBuilder2/HADDOCK3 package from RF2-selected candidates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


HOTSPOT_SETS = {
    "A": "57,101,106",
    "B": "62,101,106",
    "C": "97,101,105,106",
    "D": "33,36,105,106",
}
EVIDENCE_BOUNDARY = "guided_docking_geometry_proxy_not_binding_or_blocker_proof"
RESTRAINT_POLICY = "all_cdr_residues_to_full_8x6b_interface_hotspot_union_confirmatory"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def unique_range(sequence: str, cdr: str) -> tuple[int, int]:
    start = sequence.find(cdr)
    if start < 0 or sequence.find(cdr, start + 1) >= 0:
        raise ValueError(f"CDR is missing or ambiguous: {cdr}")
    return start + 1, start + len(cdr)


def write_restraints(path: Path, cdr_residues: list[int], hotspots: list[int]) -> None:
    lines: list[str] = []
    for residue in cdr_residues:
        lines.append(f"assign (resi {residue} and segid A)")
        lines.append("(")
        for index, hotspot in enumerate(hotspots):
            prefix = "       " if index == 0 else "        or\n       "
            lines.append(f"{prefix}(resi {hotspot} and segid B)")
        lines.append(") 2.0 2.0 0.0\n")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def build(top_tsv: Path, assets_root: Path, helpers_root: Path, package_root: Path, shards: int) -> dict[str, object]:
    rows = read_tsv(top_tsv)
    if not rows:
        raise ValueError("RF2-selected docking input is empty")
    if shards < 1:
        raise ValueError("shards must be positive")
    required = {"candidate_id", "hotspot_set", "backbone_index", "mpnn_index", "cdr1", "cdr2", "cdr3"}
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"RF2 selected TSV is missing fields: {sorted(missing)}")
    candidate_ids = [row["candidate_id"] for row in rows]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("duplicate candidate ID in RF2 selected TSV")

    baseline_files = [
        "pvrig_8x6b_chainB.pdb",
        "hotspot_residues_8x6b.txt",
        "8X6B.pdb",
        "9E6Y.pdb",
        "PVRIG_hotspot_set_v1.csv",
    ]
    helper_files = ["normalize_pdb_chain.py", "validate_pdb_sequence.py", "pdb_geometry_qc.py"]
    for name in baseline_files:
        if not (assets_root / name).is_file():
            raise ValueError(f"missing docking asset: {assets_root / name}")
    for name in helper_files:
        if not (helpers_root / name).is_file():
            raise ValueError(f"missing docking helper: {helpers_root / name}")
    hotspots = [int(value) for value in (assets_root / "hotspot_residues_8x6b.txt").read_text().split()]

    package_root.mkdir(parents=True, exist_ok=True)
    shard_rows: dict[int, list[dict[str, object]]] = {index: [] for index in range(shards)}
    sorted_rows = sorted(
        rows,
        key=lambda row: (int(row.get("docking_selection_rank") or 10**9), row["candidate_id"]),
    )
    for index, row in enumerate(sorted_rows):
        sequence = row.get("qc_synthesis_sequence") or row.get("sequence")
        if not sequence:
            raise ValueError(f"{row['candidate_id']}: missing sequence")
        if not sequence.endswith("WGQGTLVTVSS"):
            raise ValueError(f"{row['candidate_id']}: docking sequence lacks restored FR4 terminal S")
        ranges = [unique_range(sequence, row[name]) for name in ("cdr1", "cdr2", "cdr3")]
        cdr_residues = [residue for start, end in ranges for residue in range(start, end + 1)]
        shard = index % shards
        selected = {
            **row,
            "vhh_seq": sequence,
            "vhh_seq_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest(),
            "cdr1_start_1based": ranges[0][0],
            "cdr1_end_1based": ranges[0][1],
            "cdr2_start_1based": ranges[1][0],
            "cdr2_end_1based": ranges[1][1],
            "cdr3_start_1based": ranges[2][0],
            "cdr3_end_1based": ranges[2][1],
            "generation_hotspots_8x6b": HOTSPOT_SETS[row["hotspot_set"]],
            "restraint_policy": RESTRAINT_POLICY,
            "evidence_boundary": EVIDENCE_BOUNDARY,
        }
        shard_rows[shard].append(selected)

        shard_root = package_root / f"shard_{shard}"
        data_dir = shard_root / "haddock3" / row["candidate_id"] / "data"
        candidate_dir = data_dir.parent
        data_dir.mkdir(parents=True, exist_ok=True)
        (shard_root / "monomer" / row["candidate_id"]).mkdir(parents=True, exist_ok=True)
        (shard_root / "reports" / row["candidate_id"]).mkdir(parents=True, exist_ok=True)
        (candidate_dir / "logs").mkdir(parents=True, exist_ok=True)
        (data_dir / f"cdr_residues_{row['candidate_id']}_seq_numbering.txt").write_text(
            "\n".join(map(str, cdr_residues)) + "\n", encoding="ascii"
        )
        shutil.copy2(assets_root / "hotspot_residues_8x6b.txt", data_dir / "hotspot_residues_8x6b.txt")
        restraint_name = f"{row['candidate_id']}_cdr_to_pvrig_hotspot_ambig.tbl"
        write_restraints(data_dir / restraint_name, cdr_residues, hotspots)
        config = f'''# {row['candidate_id']} VHH to PVRIG 8X6B full-interface-guided HADDOCK3 docking
# Boundary: {EVIDENCE_BOUNDARY}
# Restraint policy: {RESTRAINT_POLICY}
run_dir = "run_{row['candidate_id']}_pvrig_hotspot"
mode = "local"
ncores = 4

molecules = [
    "data/{row['candidate_id']}_vhh_chainA.pdb",
    "data/pvrig_8x6b_chainB.pdb",
]

[topoaa]

[rigidbody]
ambig_fname = "data/{restraint_name}"
tolerance = 5
sampling = 40

[seletop]
select = 10

[flexref]
tolerance = 10
ambig_fname = "data/{restraint_name}"

[emref]
ambig_fname = "data/{restraint_name}"

[clustfcc]
min_population = 1

[seletopclusts]
top_models = 4
'''
        (candidate_dir / f"{row['candidate_id']}_pvrig_hotspot.cfg").write_text(config, encoding="ascii")

    for shard, selected_rows in shard_rows.items():
        shard_root = package_root / f"shard_{shard}"
        for directory in ("inputs", "scripts", "logs", "manifests", "monomer", "haddock3", "reports"):
            (shard_root / directory).mkdir(parents=True, exist_ok=True)
        for name in baseline_files:
            shutil.copy2(assets_root / name, shard_root / "inputs" / name)
        for name in helper_files:
            shutil.copy2(helpers_root / name, shard_root / "scripts" / name)
        manifest_path = shard_root / "manifests" / "selected_candidates_manifest.tsv"
        fields = list(selected_rows[0]) if selected_rows else []
        with manifest_path.open("w", newline="", encoding="utf-8") as handle:
            if fields:
                writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
                writer.writeheader()
                writer.writerows(selected_rows)
        runtime_path = shard_root / "manifests" / "runtime_candidates.tsv"
        with runtime_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            writer.writerow(["candidate_id", "vhh_seq", "vhh_seq_sha256", "cdr3_range", "selection_rank"])
            for row in selected_rows:
                writer.writerow(
                    [
                        row["candidate_id"],
                        row["vhh_seq"],
                        row["vhh_seq_sha256"],
                        f"{row['cdr3_start_1based']}-{row['cdr3_end_1based']}",
                        row.get("docking_selection_rank", ""),
                    ]
                )

    summary: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "top_tsv": str(top_tsv),
        "top_tsv_sha256": sha256_file(top_tsv),
        "candidate_count": len(rows),
        "shards": shards,
        "shard_counts": {str(key): len(value) for key, value in shard_rows.items()},
        "hotspot_set_counts": dict(sorted(Counter(row["hotspot_set"] for row in rows).items())),
        "restraint_policy": RESTRAINT_POLICY,
        "evidence_boundary": EVIDENCE_BOUNDARY,
        "all_checks_passed": True,
    }
    (package_root / "package_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("top_tsv", type=Path)
    parser.add_argument("assets_root", type=Path)
    parser.add_argument("helpers_root", type=Path)
    parser.add_argument("package_root", type=Path)
    parser.add_argument("--shards", type=int, default=4)
    args = parser.parse_args()
    print(json.dumps(build(args.top_tsv, args.assets_root, args.helpers_root, args.package_root, args.shards), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
