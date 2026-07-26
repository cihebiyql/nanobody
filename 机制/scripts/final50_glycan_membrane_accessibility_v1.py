#!/usr/bin/env python3
"""Audit potential PVRIG N-glycan-anchor clearance in frozen Final50 poses.

This dependency-free script deliberately does *not* build glycan conformers.
It identifies N-X-S/T sequons in the resolved target chain, reports the
candidate-to-Asn-anchor distance in every frozen complex, and labels the
membrane question unresolved when the supplied structures do not contain a
membrane anchor.  It is a geometric triage sidecar, not a glycosylation,
cell-surface accessibility, affinity, or blocking prediction.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AA3 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing empty TSV: {path}")
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_pdb(path: Path) -> dict[str, OrderedDict[tuple[str, str], dict[str, Any]]]:
    chains: dict[str, OrderedDict[tuple[str, str], dict[str, Any]]] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.startswith(("ATOM  ", "HETATM")) or len(raw) < 54:
            continue
        residue_name = raw[17:20].strip().upper()
        if residue_name not in AA3:
            continue
        chain = raw[21:22].strip()
        if not chain:
            continue
        residue_key = (raw[22:26].strip(), raw[26:27].strip())
        try:
            xyz = (float(raw[30:38]), float(raw[38:46]), float(raw[46:54]))
        except ValueError:
            continue
        atom = raw[12:16].strip()
        residue = chains.setdefault(chain, OrderedDict()).setdefault(
            residue_key, {"name": residue_name, "atoms": []}
        )
        residue["atoms"].append((atom, xyz))
    return chains


def min_distance(left: list[tuple[float, float, float]], right: list[tuple[float, float, float]]) -> float:
    best = math.inf
    for ax, ay, az in left:
        for bx, by, bz in right:
            d = math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)
            if d < best:
                best = d
    return best


def target_sequons(target: OrderedDict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    keys = list(target)
    seq = "".join(AA3[target[key]["name"]] for key in keys)
    out: list[dict[str, Any]] = []
    for index in range(len(seq) - 2):
        if seq[index] == "N" and seq[index + 1] != "P" and seq[index + 2] in {"S", "T"}:
            out.append(
                {
                    "sequence_position": index + 1,
                    "sequon": seq[index:index + 3],
                    "pdb_residue_number": keys[index][0],
                    "pdb_insertion_code": keys[index][1],
                    "residue_key": keys[index],
                }
            )
    return out


def status_for(distance: float) -> str:
    if distance < 10.0:
        return "POTENTIAL_GLYCAN_ANCHOR_PROXIMAL_LT10A"
    if distance < 20.0:
        return "POTENTIAL_GLYCAN_ANCHOR_NEARBY_10_TO_20A"
    return "GLYCAN_ANCHOR_CLEAR_GEOMETRIC_PROXY_GE20A"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--representative-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--candidate-chain", default="A")
    parser.add_argument("--target-chain", default="T")
    args = parser.parse_args()

    manifest = read_tsv(args.representative_manifest)
    if len(manifest) != 400:
        raise ValueError(f"expected 400 frozen representative poses, found {len(manifest)}")
    if len({row["candidate_id"] for row in manifest}) != 50:
        raise ValueError("manifest must cover exactly 50 candidates")

    pose_rows: list[dict[str, Any]] = []
    candidate_rows: dict[str, list[dict[str, Any]]] = {}
    observed_sequons: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in manifest:
        pdb = Path(row["pdb_path"])
        if not pdb.is_file():
            raise FileNotFoundError(pdb)
        chains = parse_pdb(pdb)
        if args.candidate_chain not in chains or args.target_chain not in chains:
            raise ValueError(f"{pdb}: missing required chains {args.candidate_chain}/{args.target_chain}")
        candidate_atoms = [xyz for residue in chains[args.candidate_chain].values() for _atom, xyz in residue["atoms"]]
        sequons = target_sequons(chains[args.target_chain])
        if not sequons:
            raise ValueError(f"{pdb}: no N-X-S/T sequon in target chain")
        for sequon in sequons:
            residue = chains[args.target_chain][sequon["residue_key"]]
            anchor_atoms = [xyz for _atom, xyz in residue["atoms"]]
            distance = min_distance(candidate_atoms, anchor_atoms)
            observation = {
                "candidate_id": row["candidate_id"],
                "final_rank": row.get("final_rank", ""),
                "top10_rank": row.get("top10_rank", ""),
                "conformation": row.get("conformation", ""),
                "seed": row.get("seed", ""),
                "pdb_path": str(pdb),
                "pdb_sha256": sha256_file(pdb),
                "pvrig_sequon": sequon["sequon"],
                "pvrig_chain_sequence_position": sequon["sequence_position"],
                "pvrig_pdb_residue_number": sequon["pdb_residue_number"],
                "pvrig_pdb_insertion_code": sequon["pdb_insertion_code"],
                "candidate_to_sequon_asn_anchor_min_distance_a": round(distance, 6),
                "glycan_anchor_geometry_status": status_for(distance),
                "membrane_orientation_status": "NOT_RESOLVED_ISOLATED_DOMAIN_PVRIG_41_TO_152",
                "claim_boundary": "N-X-S/T sequon-anchor geometry only; no glycan conformer, membrane, VHH-hFc, cell-surface accessibility, affinity, or blocking prediction.",
            }
            pose_rows.append(observation)
            candidate_rows.setdefault(row["candidate_id"], []).append(observation)
            observed_sequons[(sequon["sequon"], sequon["pdb_residue_number"], sequon["pdb_insertion_code"])] = sequon

    summary_rows: list[dict[str, Any]] = []
    for candidate_id, items in sorted(candidate_rows.items(), key=lambda item: int(item[1][0]["final_rank"])):
        distances = [float(item["candidate_to_sequon_asn_anchor_min_distance_a"]) for item in items]
        final_rank = items[0]["final_rank"]
        top10_rank = items[0]["top10_rank"]
        minimum = min(distances)
        summary_rows.append(
            {
                "candidate_id": candidate_id,
                "final_rank": final_rank,
                "top10_rank": top10_rank,
                "representative_pose_count": len(items),
                "resolved_target_sequons": ";".join(
                    f"{value['sequon']}@{value['pdb_residue_number']}" for value in observed_sequons.values()
                ),
                "minimum_candidate_to_sequon_asn_anchor_distance_a": round(minimum, 6),
                "pose_count_anchor_distance_lt10a": sum(distance < 10.0 for distance in distances),
                "pose_count_anchor_distance_lt20a": sum(distance < 20.0 for distance in distances),
                "glycan_accessibility_status": status_for(minimum),
                "membrane_orientation_status": "NOT_RESOLVED_ISOLATED_DOMAIN_PVRIG_41_TO_152",
                "submission_rank_use": "REVIEW_ONLY_NOT_A_RANK_FEATURE",
                "claim_boundary": "Potential sequon-anchor proximity only; actual PVRIG glycoforms and membrane/Fc geometry were not modeled.",
            }
        )

    args.out.mkdir(parents=True, exist_ok=True)
    pose_path = args.out / "Final50_PVRIG_glycan_accessibility_pose.tsv"
    candidate_path = args.out / "Final50_PVRIG_glycan_accessibility.tsv"
    write_tsv(pose_path, pose_rows)
    write_tsv(candidate_path, summary_rows)
    receipt = {
        "schema_version": "pvrig.final50.glycan_membrane_accessibility.v1",
        "state": "COMPLETE_REVIEW_ONLY",
        "candidate_count": len(summary_rows),
        "pose_count": len(pose_rows),
        "resolved_target_sequons": [
            {key: value[key] for key in ("sequon", "sequence_position", "pdb_residue_number", "pdb_insertion_code")}
            for value in observed_sequons.values()
        ],
        "membrane_status": "NOT_RESOLVED_ISOLATED_DOMAIN_PVRIG_41_TO_152",
        "input_manifest_sha256": sha256_file(args.representative_manifest),
        "output_sha256": {
            pose_path.name: sha256_file(pose_path),
            candidate_path.name: sha256_file(candidate_path),
        },
        "claim_boundary": "No glycan conformer, membrane plane, full ECD stalk, or VHH-hFc was modeled; output cannot establish cell-surface accessibility, affinity, or blocking.",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (args.out / "GLYCAN_MEMBRANE_ACCESSIBILITY_RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
