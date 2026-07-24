#!/usr/bin/env python3
"""Strictly aggregate independent Node1 DeepNano and NanoBind GPU shards."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


def read_fasta_ids(path: Path) -> list[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    ids: list[str] = []
    with opener(path, "rt") as handle:
        for line in handle:
            if line.startswith(">"):
                ids.append(line[1:].split()[0])
    return ids


def load_model_rows(root: Path, model: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    pattern = "deepnano_binding.csv" if model == "deepnano" else "nanobind_binding.csv"
    id_column = "Nanobody ID" if model == "deepnano" else "nanobody_id"
    for task in sorted((root / model).glob("task_*")):
        receipt = task / "COMPLETE.json"
        if not receipt.exists() or json.loads(receipt.read_text()).get("status") != "PASS":
            raise ValueError(f"Incomplete {model} task: {task}")
        path = task / "output" / pattern
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                candidate_id = row[id_column]
                if candidate_id in rows:
                    raise ValueError(f"Duplicate {model} candidate: {candidate_id}")
                rows[candidate_id] = row
    return rows


def percentile_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = np.arange(len(values), dtype=float)
    if len(values) > 1:
        ranks /= len(values) - 1
    return ranks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("input_fasta", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--expected-records", type=int, default=300000)
    args = parser.parse_args()

    input_ids = read_fasta_ids(args.input_fasta)
    if len(input_ids) != args.expected_records or len(set(input_ids)) != len(input_ids):
        raise ValueError("Input FASTA count/uniqueness mismatch")
    deepnano = load_model_rows(args.root, "deepnano")
    nanobind = load_model_rows(args.root, "nanobind")
    expected_ids = set(input_ids)
    if set(deepnano) != expected_ids or set(nanobind) != expected_ids:
        raise ValueError("Model output IDs do not exactly match input FASTA")

    deep_values = np.asarray([float(deepnano[cid]["Prediction"]) for cid in input_ids])
    nano_values = np.asarray([float(nanobind[cid]["probability"]) for cid in input_ids])
    disagreement = np.abs(percentile_ranks(deep_values) - percentile_ranks(nano_values))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "candidate_id",
                "deepnano_binding_prior",
                "nanobind_binding_prior",
                "nanobind_binary_prediction",
                "binding_model_percentile_disagreement",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        for index, candidate_id in enumerate(input_ids):
            writer.writerow(
                {
                    "candidate_id": candidate_id,
                    "deepnano_binding_prior": repr(float(deep_values[index])),
                    "nanobind_binding_prior": repr(float(nano_values[index])),
                    "nanobind_binary_prediction": nanobind[candidate_id]["prediction"],
                    "binding_model_percentile_disagreement": repr(
                        float(disagreement[index])
                    ),
                }
            )

    summary = {
        "status": "PASS",
        "records": len(input_ids),
        "output": str(args.output),
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "deepnano_min_median_max": [
            float(deep_values.min()),
            float(np.median(deep_values)),
            float(deep_values.max()),
        ],
        "nanobind_min_median_max": [
            float(nano_values.min()),
            float(np.median(nano_values)),
            float(nano_values.max()),
        ],
        "disagreement_median_q95": [
            float(np.median(disagreement)),
            float(np.quantile(disagreement, 0.95)),
        ],
        "scientific_boundary": "weak binding priors; not Kd, IC50, or blocking evidence",
    }
    args.output.with_suffix(args.output.suffix + ".summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
