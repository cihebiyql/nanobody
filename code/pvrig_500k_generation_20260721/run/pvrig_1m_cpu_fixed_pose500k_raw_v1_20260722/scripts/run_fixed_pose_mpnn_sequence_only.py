#!/usr/bin/env python3
"""Generate target-conditioned VHH sequences without materializing threaded PDBs.

This is a storage-efficient wrapper around RFantibody's ProteinMPNN utilities.
Every output sequence is conditioned on a frozen VHH--PVRIG complex pose.  The
target chain and framework residues remain fixed; only the requested VHH CDRs
are sampled.  Outputs are sequence/provenance records, not binding evidence.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import random
import tempfile
import time
from pathlib import Path

import numpy as np
import torch

import rfantibody.proteinmpnn.util_protein_mpnn as mpnn_util
from rfantibody.proteinmpnn.sample_features import SampleFeatures
from rfantibody.util.pose import Pose


AA = set("ACDEFGHIKLMNPQRSTVWY")
FIELDS = [
    "candidate_id",
    "sequence",
    "sequence_sha256",
    "task_id",
    "pose_id",
    "source_candidate_id",
    "source_molecule_name",
    "source_pose_rank",
    "normalized_pose_sha256",
    "target_patch",
    "design_method",
    "design_mode",
    "designed_regions",
    "temperature",
    "generation_seed",
    "sample_index",
    "proteinmpnn_score",
    "cdr1",
    "cdr2",
    "cdr3",
    "status",
]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def seed_all(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)


def model(checkpoint: Path):
    return mpnn_util.init_seq_optimize_model(
        "cpu",
        hidden_dim=128,
        num_layers=3,
        backbone_noise=0.0,
        num_connections=48,
        checkpoint_path=str(checkpoint),
    )


def cdr(sequence: str, positions: list[int]) -> str:
    # RFantibody PDBinfo CDR positions are one-indexed within the H chain.
    return "".join(sequence[position - 1] for position in positions)


def generate(args: argparse.Namespace, task: dict[str, str]) -> list[dict[str, object]]:
    pose_path = args.pose_root / task["normalized_pose_relpath"]
    observed = hashlib.sha256(pose_path.read_bytes()).hexdigest()
    if observed != task["normalized_pose_sha256"]:
        raise ValueError(f"pose hash mismatch: {pose_path}")

    pose = Pose.from_pdb(str(pose_path))
    features = SampleFeatures(pose, task["pose_id"])
    features.loop_string2fixed_res(task["loop_string"])
    if features.chains != ["H", "T"]:
        raise ValueError(f"expected H,T chains, found {features.chains}")
    h_length = int(np.sum(features.pose.chain == "H"))
    cdr_positions = {
        name: list(features.pose.cdr_dict[name]) for name in ("H1", "H2", "H3")
    }

    with tempfile.NamedTemporaryFile(suffix=".pdb", delete=False, dir=args.work_dir) as handle:
        feature_pdb = Path(handle.name)
    try:
        features.pose.dump_pdb(str(feature_pdb))
        feature_dict = mpnn_util.generate_seqopt_features(str(feature_pdb), features.chains)
        fixed_positions = {feature_pdb.stem: features.fixed_res}
        output: list[dict[str, object]] = []
        requested = int(task["sequence_count"])
        task_seed = int(task["generation_seed"])
        for start in range(0, requested, args.batch_size):
            count = min(args.batch_size, requested - start)
            seed_all(task_seed + start)
            settings = mpnn_util.set_default_args(count, omit_AAs=list("CX"), allow_x=False)
            settings["temperature"] = float(task["temperature"])
            generated = mpnn_util.generate_sequences(
                args.loaded_model,
                "cpu",
                feature_dict,
                settings,
                ["H"],
                ["T"],
                fixed_positions_dict=fixed_positions,
            )
            if len(generated) != count:
                raise RuntimeError(f"expected {count} sequences, received {len(generated)}")
            for offset, (sequence, score) in enumerate(generated):
                sample_index = start + offset
                sequence = str(sequence)
                if len(sequence) != h_length or set(sequence) - AA:
                    raise ValueError(f"invalid generated H-chain sequence at {sample_index}")
                candidate_id = f"P1MCPUFP__{task['task_id']}__{sample_index + 1:05d}"
                output.append(
                    {
                        "candidate_id": candidate_id,
                        "sequence": sequence,
                        "sequence_sha256": sha256_text(sequence),
                        "task_id": task["task_id"],
                        "pose_id": task["pose_id"],
                        "source_candidate_id": task["source_candidate_id"],
                        "source_molecule_name": task["source_molecule_name"],
                        "source_pose_rank": task["source_pose_rank"],
                        "normalized_pose_sha256": task["normalized_pose_sha256"],
                        "target_patch": task["target_patch"],
                        "design_method": "fixed_pose_proteinmpnn_cpu_sequence_only",
                        "design_mode": task["loop_string"].replace(",", ""),
                        "designed_regions": task["loop_string"],
                        "temperature": task["temperature"],
                        "generation_seed": task_seed,
                        "sample_index": sample_index,
                        "proteinmpnn_score": float(score),
                        "cdr1": cdr(sequence, cdr_positions["H1"]),
                        "cdr2": cdr(sequence, cdr_positions["H2"]),
                        "cdr3": cdr(sequence, cdr_positions["H3"]),
                        "status": "GENERATED_TARGET_CONDITIONED_SEQUENCE_ONLY",
                    }
                )
        return output
    finally:
        feature_pdb.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--pose-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        with gzip.open(args.output, "rt", encoding="utf-8") as handle:
            rows = sum(1 for _ in handle) - 1
        if rows > 0:
            print(json.dumps({"status": "ALREADY_COMPLETE", "records": rows}))
            return 0
        raise ValueError(f"empty existing output: {args.output}")
    with args.task.open(newline="", encoding="utf-8") as handle:
        tasks = list(csv.DictReader(handle, delimiter="\t"))
    if len(tasks) != 1:
        raise ValueError(f"expected exactly one task row, found {len(tasks)}")
    args.loaded_model = model(args.checkpoint)
    started = time.time()
    rows = generate(args, tasks[0])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    partial = args.output.with_suffix(args.output.suffix + ".partial")
    with gzip.open(partial, "wt", newline="", encoding="utf-8", compresslevel=1) as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    partial.replace(args.output)
    receipt = args.output.with_suffix(args.output.suffix + ".json")
    receipt.write_text(
        json.dumps(
            {
                "status": "SUCCESS",
                "task_id": tasks[0]["task_id"],
                "records": len(rows),
                "exact_unique_within_task": len({row["sequence_sha256"] for row in rows}),
                "seconds": time.time() - started,
                "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                "scientific_boundary": "target-conditioned sequence proposal; not binding, docking, affinity, or blocking evidence",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(receipt.read_text(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
