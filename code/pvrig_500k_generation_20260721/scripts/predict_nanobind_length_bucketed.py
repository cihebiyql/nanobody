#!/usr/bin/env python3
"""Batch NanoBind sequence inference without cross-length padding drift."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import torch
from Bio import SeqIO


def read_fasta(path: Path) -> list[tuple[str, str]]:
    records = [(record.id, str(record.seq)) for record in SeqIO.parse(path, "fasta")]
    if not records:
        raise ValueError(f"No FASTA records found in {path}")
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nanobind-root", type=Path, required=True)
    parser.add_argument("--nanobody-fasta", type=Path, required=True)
    parser.add_argument("--antigen-fasta", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    if args.batch_size < 1:
        parser.error("--batch-size must be >= 1")
    sys.path.insert(0, str(args.nanobind_root))
    from models.NanoBind_seq import NanoBind_seq

    nanobodies = read_fasta(args.nanobody_fasta)
    antigens = read_fasta(args.antigen_fasta)
    if len(nanobodies) != len(antigens):
        raise ValueError(
            f"Nanobody/antigen record count mismatch: {len(nanobodies)} != {len(antigens)}"
        )

    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(f"CUDA device requested but CUDA is unavailable: {args.device}")

    model_root = args.nanobind_root / "models" / "esm2_t6_8M_UR50D"
    checkpoint = (
        args.nanobind_root
        / "output"
        / "checkpoint"
        / "NanoBind_seq(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_good.model"
    )
    model = NanoBind_seq(
        pretrained_model=str(model_root),
        hidden_size=320,
        finetune=0,
    ).to(device)
    weights = torch.load(checkpoint, map_location=device)
    incompatible = model.load_state_dict(weights, strict=False)
    unexpected = [
        key
        for key in incompatible.unexpected_keys
        if key != "pretrained_model.embeddings.position_ids"
    ]
    if incompatible.missing_keys or unexpected:
        raise RuntimeError(
            f"Checkpoint incompatibility: missing={incompatible.missing_keys}, "
            f"unexpected={unexpected}"
        )
    model.eval()

    # The upstream model averages over padded positions without masking them.
    # Exact (VHH length, antigen length) buckets preserve one-by-one semantics.
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, ((_, nb_sequence), (_, ag_sequence)) in enumerate(zip(nanobodies, antigens)):
        buckets[(len(nb_sequence), len(ag_sequence))].append(index)

    probabilities: list[float | None] = [None] * len(nanobodies)
    with torch.no_grad():
        for length_key in sorted(buckets):
            indices = buckets[length_key]
            for start in range(0, len(indices), args.batch_size):
                batch_indices = indices[start : start + args.batch_size]
                nb_sequences = [nanobodies[index][1] for index in batch_indices]
                ag_sequences = [antigens[index][1] for index in batch_indices]
                values = model(nb_sequences, ag_sequences, device).detach().cpu().reshape(-1)
                for index, value in zip(batch_indices, values.tolist()):
                    probabilities[index] = float(value)

    if any(value is None for value in probabilities):
        raise RuntimeError("Missing NanoBind prediction")
    final_probabilities = [float(value) for value in probabilities]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "pair_id": index + 1,
            "nanobody_id": nanobodies[index][0],
            "antigen_id": antigens[index][0],
            "probability": probability,
            "prediction": 1 if probability > 0.3 else 0,
        }
        for index, probability in enumerate(final_probabilities)
    ]
    with args.output.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "pair_id",
                "nanobody_id",
                "antigen_id",
                "probability",
                "prediction",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
