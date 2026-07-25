#!/usr/bin/env python3
"""Freeze a 5-positive/4-disruptive-control Chai/Boltz calibration panel."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


POSITIVE_NAMES = (
    "PVRIG-151_HR151",
    "PVRIG-20",
    "PVRIG-30",
    "PVRIG-38",
    "PVRIG-39",
)
MUTANT_NAMES = (
    "mut_03_PVRIG-20_cdr3_arom_F99A",
    "mut_09_PVRIG-30_cdr3_arom_W100A",
    "mut_14_PVRIG-38_cdr3_arom_F100A",
    "mut_19_PVRIG-39_cdr3_arom_F99A",
)
IMGT_CDR_POSITIONS = {
    "imgt_cdr1": tuple(str(i) for i in range(27, 39)),
    "imgt_cdr2": tuple(str(i) for i in range(56, 66)),
    "imgt_cdr3": (
        "105", "106", "107", "108", "109", "110", "111",
        "111A", "111B", "111C", "112C", "112B", "112A",
        "112", "113", "114", "115", "116", "117",
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_fasta(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    name: str | None = None
    sequence: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if name is not None:
                records[name] = "".join(sequence).upper()
            name = line[1:].split("|", 1)[0]
            sequence = []
        elif name is not None:
            sequence.append(line)
    if name is not None:
        records[name] = "".join(sequence).upper()
    return records


def read_fasta_first(path: Path) -> str:
    records = read_fasta(path)
    if not records:
        raise ValueError(f"empty FASTA: {path}")
    return next(iter(records.values()))


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def slice_range(sequence: str, value: str) -> str:
    start, end = (int(token) for token in value.split("-", 1))
    return sequence[start - 1 : end]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positive-fasta", type=Path, required=True)
    parser.add_argument("--positive-anarci", type=Path, required=True)
    parser.add_argument("--mutant-panel", type=Path, required=True)
    parser.add_argument("--pvrig-fasta", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--shards", type=int, default=5)
    args = parser.parse_args()

    positives = read_fasta(args.positive_fasta)
    with args.positive_anarci.open(newline="", encoding="utf-8-sig") as handle:
        anarci = {
            row["Id"].split("|", 1)[0]: row for row in csv.DictReader(handle)
        }
    with args.mutant_panel.open(newline="", encoding="utf-8-sig") as handle:
        mutants = {row["mutant_name"]: row for row in csv.DictReader(handle)}
    pvrig = read_fasta_first(args.pvrig_fasta)

    entities: list[dict[str, str]] = []
    for name in POSITIVE_NAMES:
        sequence = positives[name]
        numbering = anarci[name]
        cdrs = {
            key: "".join(numbering[position] for position in positions).replace("-", "")
            for key, positions in IMGT_CDR_POSITIONS.items()
        }
        if any(value not in sequence for value in cdrs.values()):
            raise RuntimeError(f"ANARCI CDR motif mismatch: {name} {cdrs}")
        entities.append(
            {
                "candidate_id": safe_id(f"POS_{name}"),
                "source_name": name,
                "control_class": "EXPERIMENTAL_POSITIVE_BLOCKER",
                "expected_behavior": "POSITIVE_BLOCKER",
                "base_molecule": name,
                "mutation": "none",
                "sequence": sequence,
                **cdrs,
            }
        )
    for name in MUTANT_NAMES:
        row = mutants[name]
        sequence = row["sequence"].upper()
        cdrs = {
            "imgt_cdr1": slice_range(sequence, row["cdr1_range"]),
            "imgt_cdr2": slice_range(sequence, row["cdr2_range"]),
            "imgt_cdr3": slice_range(sequence, row["cdr3_range"]),
        }
        entities.append(
            {
                "candidate_id": safe_id(f"MUT_{name}"),
                "source_name": name,
                "control_class": "COMPUTATIONAL_DISRUPTIVE_CONTROL",
                "expected_behavior": "WEAKENED_OR_UNSTABLE_RELATIVE_TO_PARENT",
                "base_molecule": row["base_molecule"],
                "mutation": row["mutations_1based"],
                "sequence": sequence,
                **cdrs,
            }
        )
    if len(entities) != 9 or len({row["candidate_id"] for row in entities}) != 9:
        raise RuntimeError("control panel cardinality mismatch")

    project = args.project.resolve()
    manifests = project / "manifests"
    chai_inputs = project / "inputs" / "chai"
    boltz_inputs = project / "inputs" / "boltz"
    for path in (manifests, chai_inputs, boltz_inputs):
        path.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict[str, Any]] = []
    for index, entity in enumerate(entities, start=1):
        candidate = entity["candidate_id"]
        shard = (index - 1) % args.shards
        chai_path = chai_inputs / f"{candidate}.fasta"
        chai_path.write_text(
            f">protein|name=VHH\n{entity['sequence']}\n"
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
            f"      sequence: {entity['sequence']}\n"
            "      msa: empty\n"
            "  - protein:\n"
            "      id: B\n"
            f"      sequence: {pvrig}\n"
            "      msa: empty\n",
            encoding="ascii",
        )
        manifest_rows.append(
            {
                "top100_rank": index,
                **entity,
                "sequence_sha256": hashlib.sha256(
                    entity["sequence"].encode()
                ).hexdigest(),
                "route": "CALIBRATION_CONTROL",
                "structure_consistency_label": "NOT_RUN_CONTROL_PANEL",
                "monomer_high_uncertainty": "false",
                "max_pairwise_fr_rmsd_a": "",
                "max_pairwise_cdr3_rmsd_a": "",
                "shard": shard,
                "chai_input": str(chai_path),
                "chai_input_sha256": sha256_file(chai_path),
                "boltz_input": str(boltz_path),
                "boltz_input_sha256": sha256_file(boltz_path),
            }
        )

    manifest_path = manifests / "control_independent_complex_manifest.tsv"
    write_tsv(manifest_path, manifest_rows)
    protocol = {
        "schema_version": "pvrig.control.independent_complex.protocol.v1",
        "target": {
            "name": "PVRIG_8X6B_chainB_ECD",
            "sequence": pvrig,
            "sequence_sha256": hashlib.sha256(pvrig.encode()).hexdigest(),
        },
        "panel": {
            "experimental_positive_blockers": list(POSITIVE_NAMES),
            "computational_disruptive_controls": list(MUTANT_NAMES),
            "destructive_control_boundary": (
                "Alanine mutants are computational perturbation controls, not "
                "experimentally confirmed non-binders/non-blockers."
            ),
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
            "seed_rule": "100000 + panel_order",
        },
    }
    protocol_path = project / "PROTOCOL.json"
    protocol_path.write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt = {
        "schema_version": "pvrig.control.independent_complex.prepare.v1",
        "state": "READY",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": 9,
        "positive_count": 5,
        "disruptive_control_count": 4,
        "shard_count": args.shards,
        "shard_sizes": dict(
            sorted(Counter(str(row["shard"]) for row in manifest_rows).items())
        ),
        "input_hashes": {
            "positive_fasta": sha256_file(args.positive_fasta),
            "positive_anarci": sha256_file(args.positive_anarci),
            "mutant_panel": sha256_file(args.mutant_panel),
            "pvrig_fasta": sha256_file(args.pvrig_fasta),
        },
        "manifest_sha256": sha256_file(manifest_path),
        "protocol_sha256": sha256_file(protocol_path),
    }
    (project / "READY.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
