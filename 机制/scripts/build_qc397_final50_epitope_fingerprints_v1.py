#!/usr/bin/env python3
"""Build multi-pose PVRIG contact fingerprints and deterministic clusters."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CUTOFF = 4.5
CLUSTER_SIMILARITY = 0.70
THREE_TO_ONE = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_contacts(path: Path) -> dict[int, str]:
    vhh_atoms: list[tuple[float, float, float]] = []
    target_atoms: list[tuple[float, float, float, int, str]] = []
    with path.open(errors="ignore") as handle:
        for line in handle:
            if not line.startswith(("ATOM  ", "HETATM")) or len(line) < 54:
                continue
            atom_name = line[12:16].strip()
            element = line[76:78].strip() or atom_name[:1]
            if element.upper() == "H":
                continue
            chain = line[21:22]
            try:
                xyz = (
                    float(line[30:38]),
                    float(line[38:46]),
                    float(line[46:54]),
                )
            except ValueError:
                continue
            if chain == "A":
                vhh_atoms.append(xyz)
            elif chain == "T":
                try:
                    position = int(line[22:26])
                except ValueError:
                    continue
                aa = THREE_TO_ONE.get(line[17:20].strip(), "X")
                target_atoms.append((*xyz, position, aa))
    if not vhh_atoms or not target_atoms:
        raise ValueError(f"required A/T atoms absent: {path}")

    width = CUTOFF
    bins: dict[tuple[int, int, int], list[tuple[float, float, float]]] = defaultdict(
        list
    )
    for x, y, z in vhh_atoms:
        bins[(math.floor(x / width), math.floor(y / width), math.floor(z / width))].append(
            (x, y, z)
        )
    cutoff_sq = CUTOFF * CUTOFF
    contacts: dict[int, str] = {}
    for x, y, z, position, aa in target_atoms:
        key = (math.floor(x / width), math.floor(y / width), math.floor(z / width))
        found = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for vx, vy, vz in bins.get(
                        (key[0] + dx, key[1] + dy, key[2] + dz), []
                    ):
                        if (
                            (x - vx) ** 2 + (y - vy) ** 2 + (z - vz) ** 2
                            <= cutoff_sq
                        ):
                            contacts[position] = aa
                            found = True
                            break
                    if found:
                        break
                if found:
                    break
            if found:
                break
    return contacts


def weighted_jaccard(a: dict[int, float], b: dict[int, float]) -> float:
    keys = set(a) | set(b)
    denominator = sum(max(a.get(key, 0.0), b.get(key, 0.0)) for key in keys)
    if denominator == 0:
        return 0.0
    return sum(min(a.get(key, 0.0), b.get(key, 0.0)) for key in keys) / denominator


def complete_link_clusters(
    ids: list[str], pair_similarity: dict[tuple[str, str], float]
) -> list[list[str]]:
    clusters = [[candidate_id] for candidate_id in ids]

    def similarity(left: list[str], right: list[str]) -> float:
        return min(
            pair_similarity[tuple(sorted((candidate_a, candidate_b)))]
            for candidate_a in left
            for candidate_b in right
        )

    while True:
        best: tuple[float, int, int] | None = None
        for left_index in range(len(clusters)):
            for right_index in range(left_index + 1, len(clusters)):
                value = similarity(clusters[left_index], clusters[right_index])
                candidate = (value, -left_index, -right_index)
                if best is None or candidate > best:
                    best = candidate
        if best is None or best[0] < CLUSTER_SIMILARITY:
            break
        left_index = -best[1]
        right_index = -best[2]
        merged = clusters[left_index] + clusters[right_index]
        clusters = [
            cluster
            for index, cluster in enumerate(clusters)
            if index not in {left_index, right_index}
        ]
        clusters.append(merged)
        clusters.sort(key=lambda cluster: min(ids.index(item) for item in cluster))
    return clusters


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-tsv", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--hotspot-csv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"output exists: {args.out}")
    args.out.mkdir(parents=True)

    freeze = sorted(
        read_tsv(args.freeze_tsv), key=lambda row: int(row["competition_rank_1_50"])
    )
    manifest = read_tsv(args.manifest)
    if len(freeze) != 50 or len(manifest) != 400:
        raise ValueError("expected Final50 and 400 poses")
    by_id = {row["candidate_id"]: row for row in freeze}
    manifest_ids = {row["candidate_id"] for row in manifest}
    if set(by_id) != manifest_ids:
        raise ValueError("freeze/manifest candidate membership mismatch")
    counts = Counter(row["candidate_id"] for row in manifest)
    if set(counts.values()) != {8}:
        raise ValueError("manifest is not exactly 8 poses per candidate")

    hotspot_rows = read_csv(args.hotspot_csv)
    hotspot_class = {
        int(row["uniprot_position"]): row["hotspot_class"] for row in hotspot_rows
    }
    core_positions = {
        position for position, category in hotspot_class.items() if category == "core_hotspot"
    }
    secondary_positions = {
        position
        for position, category in hotspot_class.items()
        if category == "secondary_hotspot"
    }

    pose_rows: list[dict[str, Any]] = []
    contact_counts: dict[str, Counter[int]] = defaultdict(Counter)
    residue_aa: dict[int, str] = {}
    for row in manifest:
        path = Path(row["pdb_path"])
        contacts = parse_contacts(path)
        for position, aa in contacts.items():
            residue_aa[position] = aa
            contact_counts[row["candidate_id"]][position] += 1
        pose_rows.append(
            {
                "candidate_id": row["candidate_id"],
                "submission_id": by_id[row["candidate_id"]]["submission_id"],
                "competition_rank_1_50": by_id[row["candidate_id"]][
                    "competition_rank_1_50"
                ],
                "conformation": row["conformation"],
                "seed": row["seed"],
                "contact_residue_count_4p5a": len(contacts),
                "contact_positions": ",".join(
                    f"{position}{contacts[position]}" for position in sorted(contacts)
                ),
                "core_hotspot_contacts": len(set(contacts) & core_positions),
                "secondary_hotspot_contacts": len(
                    set(contacts) & secondary_positions
                ),
                "pdb_path": str(path),
                "pdb_sha256": row["pdb_sha256"],
            }
        )

    vectors: dict[str, dict[int, float]] = {}
    for candidate_id in by_id:
        vectors[candidate_id] = {
            position: count / 8.0
            for position, count in contact_counts[candidate_id].items()
        }
    pair_similarity: dict[tuple[str, str], float] = {}
    pair_rows: list[dict[str, Any]] = []
    ordered_ids = [
        row["candidate_id"]
        for row in sorted(
            freeze, key=lambda row: int(row["competition_rank_1_50"])
        )
    ]
    for left_index, left in enumerate(ordered_ids):
        for right in ordered_ids[left_index + 1 :]:
            similarity = weighted_jaccard(vectors[left], vectors[right])
            pair_similarity[tuple(sorted((left, right)))] = similarity
            pair_rows.append(
                {
                    "candidate_id_a": left,
                    "submission_id_a": by_id[left]["submission_id"],
                    "competition_rank_a": by_id[left]["competition_rank_1_50"],
                    "candidate_id_b": right,
                    "submission_id_b": by_id[right]["submission_id"],
                    "competition_rank_b": by_id[right]["competition_rank_1_50"],
                    "weighted_jaccard_contact_similarity": f"{similarity:.6f}",
                }
            )
    clusters = complete_link_clusters(ordered_ids, pair_similarity)
    clusters.sort(
        key=lambda cluster: min(
            int(by_id[candidate_id]["competition_rank_1_50"])
            for candidate_id in cluster
        )
    )
    cluster_by_id: dict[str, str] = {}
    cluster_size: dict[str, int] = {}
    for index, cluster in enumerate(clusters, 1):
        cluster_id = f"EPI_{index:02d}"
        cluster_size[cluster_id] = len(cluster)
        for candidate_id in cluster:
            cluster_by_id[candidate_id] = cluster_id

    candidate_rows: list[dict[str, Any]] = []
    for row in freeze:
        candidate_id = row["candidate_id"]
        vector = vectors[candidate_id]
        consensus = {position for position, frequency in vector.items() if frequency >= 0.5}
        stable = {position for position, frequency in vector.items() if frequency >= 0.75}
        candidate_rows.append(
            {
                "submission_id": row["submission_id"],
                "competition_rank_1_50": row["competition_rank_1_50"],
                "mechanism_rank_immutable": row["mechanism_rank_immutable"],
                "candidate_id": candidate_id,
                "epitope_cluster_id": cluster_by_id[candidate_id],
                "epitope_cluster_size": cluster_size[cluster_by_id[candidate_id]],
                "pose_count": 8,
                "contact_union_residue_count": len(vector),
                "consensus_contact_residue_count_ge4of8": len(consensus),
                "stable_contact_residue_count_ge6of8": len(stable),
                "consensus_contact_positions": ",".join(
                    f"{position}{residue_aa.get(position, 'X')}"
                    for position in sorted(consensus)
                ),
                "stable_contact_positions": ",".join(
                    f"{position}{residue_aa.get(position, 'X')}"
                    for position in sorted(stable)
                ),
                "core_hotspot_consensus_contacts": len(consensus & core_positions),
                "secondary_hotspot_consensus_contacts": len(
                    consensus & secondary_positions
                ),
                "weighted_contact_fingerprint": ",".join(
                    f"{position}{residue_aa.get(position, 'X')}:{vector[position]:.3f}"
                    for position in sorted(vector)
                ),
                "method": (
                    "heavy-atom contact <=4.5A; frequency over 4 seeds x 2 "
                    "conformations; complete-link weighted-Jaccard clustering"
                ),
                "cluster_similarity_threshold": f"{CLUSTER_SIMILARITY:.2f}",
                "claim_boundary": (
                    "Computational contact-pattern cluster, not an experimental "
                    "epitope bin or binding competition result."
                ),
            }
        )

    pose_path = args.out / "Final50_epitope_contact_pose.tsv"
    pair_path = args.out / "Final50_epitope_pairwise_similarity.tsv"
    candidate_path = args.out / "Final50_epitope_fingerprint_clusters.tsv"
    write_tsv(pose_path, pose_rows)
    write_tsv(pair_path, pair_rows)
    write_tsv(candidate_path, candidate_rows)
    receipt = {
        "schema_version": "pvrig.qc397.final50.epitope_fingerprint.v1",
        "state": "COMPLETE",
        "candidates": 50,
        "poses": 400,
        "candidate_pairs": len(pair_rows),
        "clusters": len(clusters),
        "cluster_sizes": dict(Counter(row["epitope_cluster_id"] for row in candidate_rows)),
        "contact_cutoff_a": CUTOFF,
        "cluster_method": "complete-link weighted Jaccard",
        "cluster_similarity_threshold": CLUSTER_SIMILARITY,
        "input_sha256": {
            str(path): sha256(path)
            for path in (args.freeze_tsv, args.manifest, args.hotspot_csv)
        },
        "output_sha256": {
            pose_path.name: sha256(pose_path),
            pair_path.name: sha256(pair_path),
            candidate_path.name: sha256(candidate_path),
        },
        "claim_boundary": (
            "Computational multi-pose contact fingerprint clusters only; not "
            "experimental epitope binning or affinity/blocking evidence."
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (args.out / "EPITOPE_FINGERPRINT_RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
