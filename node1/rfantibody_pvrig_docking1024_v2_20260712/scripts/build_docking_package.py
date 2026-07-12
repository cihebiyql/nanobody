#!/usr/bin/env python3
"""Build a resumable NanoBodyBuilder2 + HADDOCK3 docking work package.

The builder only materializes manifests, per-candidate HADDOCK configs, restraints,
and provenance. It does not start NanoBodyBuilder2 or HADDOCK3.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE_BOUNDARY = "nbb2_haddock_guided_geometry_proxy_not_binding_or_blocker_proof"
RESTRAINT_POLICY = "all_candidate_cdr_residues_to_8x6b_full_interface_hotspot_union"
DEFAULT_GPUS = "1,2,3,4,5,7"
VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding=encoding)
    tmp.replace(path)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows:
        raise ValueError(f"candidate TSV is empty: {path}")
    return rows


def sequence_for(row: dict[str, str]) -> str:
    for key in ("sequence", "qc_synthesis_sequence", "vhh_seq"):
        value = (row.get(key) or "").strip().upper()
        if value:
            return value
    raise ValueError(f"{row.get('candidate_id', '<missing candidate_id>')}: missing sequence")


def unique_range(sequence: str, cdr: str, label: str, candidate_id: str) -> tuple[int, int]:
    cdr = cdr.strip().upper()
    if not cdr:
        raise ValueError(f"{candidate_id}: missing {label}")
    start = sequence.find(cdr)
    if start < 0 or sequence.find(cdr, start + 1) >= 0:
        raise ValueError(f"{candidate_id}: {label} is absent or ambiguous in sequence")
    return start + 1, start + len(cdr)


def read_hotspots(path: Path) -> list[int]:
    hotspots = [int(value) for value in path.read_text(encoding="ascii").split() if value.strip()]
    if not hotspots:
        raise ValueError(f"hotspot file has no residues: {path}")
    return hotspots


def pdb_chain_residues(path: Path) -> dict[str, set[int]]:
    chains: dict[str, set[int]] = {}
    for line in path.read_text(encoding="ascii", errors="replace").splitlines():
        if not line.startswith("ATOM") or len(line) < 27:
            continue
        chain = line[21].strip()
        try:
            residue = int(line[22:26])
        except ValueError:
            continue
        chains.setdefault(chain, set()).add(residue)
    return chains


def write_restraints(path: Path, cdr_residues: list[int], hotspots: list[int], receptor_chain: str) -> None:
    lines: list[str] = [
        f"! policy: {RESTRAINT_POLICY}",
        f"! receptor_chain: {receptor_chain}",
        "! active receptor residues are the full 8X6B PVRIG interface hotspot union",
    ]
    for residue in cdr_residues:
        lines.append(f"assign (resi {residue} and segid A)")
        lines.append("(")
        for index, hotspot in enumerate(hotspots):
            prefix = "       " if index == 0 else "        or\n       "
            lines.append(f"{prefix}(resi {hotspot} and segid {receptor_chain})")
        lines.append(") 2.0 2.0 0.0\n")
    atomic_write_text(path, "\n".join(lines) + "\n", encoding="ascii")


def write_haddock_config(path: Path, candidate_id: str, receptor_name: str, restraint_name: str, ncores: int) -> None:
    config = f'''# {candidate_id} VHH to PVRIG 8X6B full-interface-guided HADDOCK3 docking
# Boundary: {EVIDENCE_BOUNDARY}
# Restraint policy: {RESTRAINT_POLICY}
run_dir = "run_{candidate_id}_pvrig_8x6b_full_interface"
mode = "local"
ncores = {ncores}

molecules = [
    "data/{candidate_id}_vhh_chainA.pdb",
    "data/{receptor_name}",
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
    atomic_write_text(path, config, encoding="ascii")


def write_tsv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def build_package(
    run_root: Path,
    candidates_tsv: Path,
    expected_count: int,
    receptor_chain: str,
    ncores_per_haddock: int,
    gpu_ids: str,
) -> dict[str, object]:
    candidates_tsv = candidates_tsv.resolve()
    rows = read_tsv(candidates_tsv)
    required = {"candidate_id", "cdr1", "cdr2", "cdr3"}
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"candidate TSV is missing fields: {sorted(missing)}")
    if expected_count and len(rows) != expected_count:
        raise ValueError(f"expected {expected_count} candidates, found {len(rows)}")

    ids = [row["candidate_id"].strip() for row in rows]
    if any(not value for value in ids):
        raise ValueError("candidate TSV contains blank candidate_id")
    duplicated_ids = sorted(candidate_id for candidate_id, count in Counter(ids).items() if count > 1)
    if duplicated_ids:
        raise ValueError(f"duplicate candidate_id values: {duplicated_ids[:5]}")

    sequences = [sequence_for(row) for row in rows]
    bad_sequences = [ids[index] for index, sequence in enumerate(sequences) if set(sequence) - VALID_AA]
    if bad_sequences:
        raise ValueError(f"noncanonical amino acids in candidates: {bad_sequences[:5]}")
    sequence_hashes = [sha256_text(sequence) for sequence in sequences]
    if len(set(sequence_hashes)) != len(sequence_hashes):
        raise ValueError("candidate sequences are not exact-unique")

    input_dir = run_root / "inputs"
    hotspot_path = input_dir / "hotspot_residues_8x6b.txt"
    receptor_path = input_dir / "pvrig_8x6b_chainT.pdb"
    interface_path = input_dir / "PVRIG_hotspot_set_v1.csv"
    for path in (hotspot_path, receptor_path, interface_path):
        if not path.is_file():
            raise ValueError(f"missing required input asset: {path}")
    hotspots = read_hotspots(hotspot_path)
    receptor_chains = pdb_chain_residues(receptor_path)
    if receptor_chain not in receptor_chains:
        raise ValueError(f"receptor chain {receptor_chain!r} is absent from {receptor_path}")
    missing_hotspots = sorted(set(hotspots) - receptor_chains[receptor_chain])
    if missing_hotspots:
        raise ValueError(f"receptor is missing hotspot residues: {missing_hotspots}")

    docking_root = run_root / "docking"
    manifest_rows: list[dict[str, object]] = []
    for rank, (row, sequence, digest) in enumerate(zip(rows, sequences, sequence_hashes), start=1):
        candidate_id = row["candidate_id"].strip()
        ranges = [unique_range(sequence, row[name], name, candidate_id) for name in ("cdr1", "cdr2", "cdr3")]
        cdr_residues = [residue for start, end in ranges for residue in range(start, end + 1)]
        candidate_dir = docking_root / "haddock" / candidate_id
        data_dir = candidate_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(receptor_path, data_dir / receptor_path.name)
        shutil.copy2(hotspot_path, data_dir / hotspot_path.name)
        restraint_name = f"{candidate_id}_cdr_to_8x6b_full_interface_ambig.tbl"
        write_restraints(data_dir / restraint_name, cdr_residues, hotspots, receptor_chain)
        cfg_name = f"{candidate_id}_pvrig_8x6b_full_interface.cfg"
        write_haddock_config(candidate_dir / cfg_name, candidate_id, receptor_path.name, restraint_name, ncores_per_haddock)
        atomic_write_text(data_dir / f"cdr_residues_{candidate_id}_seq_numbering.txt", "\n".join(map(str, cdr_residues)) + "\n", "ascii")

        manifest_rows.append(
            {
                "candidate_id": candidate_id,
                "sequence": sequence,
                "sequence_sha256": digest,
                "cohort_rank": row.get("docking_cohort_rank") or rank,
                "cdr1_start_1based": ranges[0][0],
                "cdr1_end_1based": ranges[0][1],
                "cdr2_start_1based": ranges[1][0],
                "cdr2_end_1based": ranges[1][1],
                "cdr3_start_1based": ranges[2][0],
                "cdr3_end_1based": ranges[2][1],
                "cdr_residues": ",".join(map(str, cdr_residues)),
                "hotspot_residues_8x6b": ",".join(map(str, hotspots)),
                "receptor_pdb": str(receptor_path),
                "receptor_pdb_sha256": sha256_file(receptor_path),
                "restraint_file": str(data_dir / restraint_name),
                "haddock_cfg": str(candidate_dir / cfg_name),
                "restraint_policy": RESTRAINT_POLICY,
                "evidence_boundary": EVIDENCE_BOUNDARY,
            }
        )

    fields = [
        "candidate_id",
        "sequence",
        "sequence_sha256",
        "cohort_rank",
        "cdr1_start_1based",
        "cdr1_end_1based",
        "cdr2_start_1based",
        "cdr2_end_1based",
        "cdr3_start_1based",
        "cdr3_end_1based",
        "cdr_residues",
        "hotspot_residues_8x6b",
        "receptor_pdb",
        "receptor_pdb_sha256",
        "restraint_file",
        "haddock_cfg",
        "restraint_policy",
        "evidence_boundary",
    ]
    manifest_path = docking_root / "manifests" / "docking_candidates.tsv"
    write_tsv(manifest_path, manifest_rows, fields)
    for subdir in ("locks/nbb2", "locks/haddock", "state/nbb2", "state/haddock", "logs/nbb2", "logs/haddock", "reports"):
        (docking_root / subdir).mkdir(parents=True, exist_ok=True)

    summary: dict[str, object] = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "candidate_tsv": str(candidates_tsv),
        "candidate_tsv_sha256": sha256_file(candidates_tsv),
        "candidate_count": len(manifest_rows),
        "unique_candidate_sequences": len(set(sequence_hashes)),
        "manifest": str(manifest_path),
        "gpu_ids_for_nbb2": gpu_ids,
        "haddock_target": "8X6B PVRIG full-interface hotspot union",
        "haddock_ncores_per_job": ncores_per_haddock,
        "receptor_chain": receptor_chain,
        "hotspot_residue_count": len(hotspots),
        "restraint_policy": RESTRAINT_POLICY,
        "evidence_boundary": EVIDENCE_BOUNDARY,
        "all_checks_passed": True,
    }
    atomic_write_text(docking_root / "package_summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--candidates", type=Path, default=None)
    parser.add_argument("--expected-count", type=int, default=1024)
    parser.add_argument("--receptor-chain", default="T")
    parser.add_argument("--haddock-ncores", type=int, default=4)
    parser.add_argument("--gpu-ids", default=DEFAULT_GPUS)
    args = parser.parse_args()
    candidates = args.candidates or args.run_root / "data" / "candidates.tsv"
    summary = build_package(args.run_root.resolve(), candidates, args.expected_count, args.receptor_chain, args.haddock_ncores, args.gpu_ids)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
