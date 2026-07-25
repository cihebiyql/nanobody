#!/usr/bin/env python3
"""Freeze Top100 candidate/PVRIG inputs for independent Boltz and Chai runs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_fasta_first(path: Path) -> str:
    sequence: list[str] = []
    started = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if started and sequence:
                break
            started = True
            continue
        if started:
            sequence.append(line)
    value = "".join(sequence).upper()
    if not value:
        raise ValueError(f"empty FASTA: {path}")
    return value


def write_tsv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top200", type=Path, required=True)
    parser.add_argument("--structure-metrics", type=Path, required=True)
    parser.add_argument("--pvrig-fasta", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--shards", type=int, default=8)
    args = parser.parse_args()

    with args.top200.open(newline="", encoding="utf-8-sig") as handle:
        top200 = list(csv.DictReader(handle, delimiter="\t"))
    top100 = sorted(
        (row for row in top200 if int(row["top200_rank"]) <= 100),
        key=lambda row: int(row["top200_rank"]),
    )
    if len(top100) != 100:
        raise ValueError(f"expected Top100, found {len(top100)}")

    with args.structure_metrics.open(newline="", encoding="utf-8-sig") as handle:
        structure = {
            row["candidate_id"]: row
            for row in csv.DictReader(handle, delimiter="\t")
        }
    pvrig = read_fasta_first(args.pvrig_fasta)
    project = args.project.resolve()
    manifests = project / "manifests"
    chai_inputs = project / "inputs" / "chai"
    boltz_inputs = project / "inputs" / "boltz"
    for path in (manifests, chai_inputs, boltz_inputs):
        path.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict[str, object]] = []
    for row in top100:
        candidate = row["candidate_id"]
        rank = int(row["top200_rank"])
        shard = (rank - 1) % args.shards
        structure_row = structure[candidate]
        chai_path = chai_inputs / f"{candidate}.fasta"
        chai_path.write_text(
            f">protein|name=VHH\n{row['sequence']}\n"
            f">protein|name=PVRIG\n{pvrig}\n",
            encoding="ascii",
        )
        shard_dir = boltz_inputs / f"shard_{shard}"
        shard_dir.mkdir(parents=True, exist_ok=True)
        boltz_path = shard_dir / f"{candidate}.yaml"
        boltz_path.write_text(
            "version: 1\n"
            "sequences:\n"
            "  - protein:\n"
            "      id: H\n"
            f"      sequence: {row['sequence']}\n"
            "      msa: empty\n"
            "  - protein:\n"
            "      id: B\n"
            f"      sequence: {pvrig}\n"
            "      msa: empty\n",
            encoding="ascii",
        )
        manifest_rows.append(
            {
                "top100_rank": rank,
                "candidate_id": candidate,
                "sequence": row["sequence"],
                "sequence_sha256": row["sequence_sha256"],
                "imgt_cdr1": row["IMGT_CDR1"],
                "imgt_cdr2": row["IMGT_CDR2"],
                "imgt_cdr3": row["IMGT_CDR3"],
                "route": row["route"],
                "structure_consistency_label": structure_row[
                    "structure_consistency_label"
                ],
                "monomer_high_uncertainty": structure_row["high_uncertainty"],
                "max_pairwise_fr_rmsd_a": structure_row[
                    "max_pairwise_fr_rmsd_a"
                ],
                "max_pairwise_cdr3_rmsd_a": structure_row[
                    "max_pairwise_cdr3_rmsd_a"
                ],
                "shard": shard,
                "chai_input": str(chai_path),
                "chai_input_sha256": sha256_file(chai_path),
                "boltz_input": str(boltz_path),
                "boltz_input_sha256": sha256_file(boltz_path),
            }
        )

    manifest_path = manifests / "top100_independent_complex_manifest.tsv"
    fields = list(manifest_rows[0])
    write_tsv(manifest_path, manifest_rows, fields)
    protocol = {
        "schema_version": "pvrig.top100.independent_complex.protocol.v1",
        "target": {
            "name": "PVRIG_8X6B_chainB_ECD",
            "sequence": pvrig,
            "sequence_sha256": hashlib.sha256(pvrig.encode()).hexdigest(),
        },
        "boltz": {
            "msa": "empty",
            "recycling_steps": 3,
            "sampling_steps": 50,
            "diffusion_samples": 1,
            "max_parallel_samples": 1,
            "output_format": "pdb",
            "no_kernels": True,
        },
        "chai": {
            "use_esm_embeddings": False,
            "use_msa_server": False,
            "use_templates_server": False,
            "num_trunk_recycles": 3,
            "num_diffn_timesteps": 50,
            "num_diffn_samples": 2,
            "num_trunk_samples": 1,
            "low_memory": True,
            "seed_rule": "100000 + top100_rank",
        },
        "claim_boundary": (
            "These are unconstrained independent complex predictions. They are "
            "not experimental binders/blockers and are not HADDOCK confirmations."
        ),
    }
    protocol_path = project / "PROTOCOL.json"
    protocol_path.write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt = {
        "schema_version": "pvrig.top100.independent_complex.prepare.v1",
        "state": "READY",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(manifest_rows),
        "monomer_high_uncertainty_count": sum(
            row["monomer_high_uncertainty"] == "true"
            for row in manifest_rows
        ),
        "shard_count": args.shards,
        "shard_sizes": dict(
            sorted(Counter(str(row["shard"]) for row in manifest_rows).items())
        ),
        "top200_sha256": sha256_file(args.top200),
        "structure_metrics_sha256": sha256_file(args.structure_metrics),
        "pvrig_fasta_sha256": sha256_file(args.pvrig_fasta),
        "manifest_sha256": sha256_file(manifest_path),
        "protocol_sha256": sha256_file(protocol_path),
    }
    (project / "PREPARE_RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
