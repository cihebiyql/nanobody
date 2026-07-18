#!/usr/bin/env python3
"""Generate a tiny synthetic panel and run the complete V6 training CLI."""

from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import tempfile
from pathlib import Path
from typing import Sequence

import torch

import train_v6_multitask as trainer
from v6_model import AA_ALPHABET, require


def write_synthetic_table(path: Path, seed: int = 17) -> None:
    rng = random.Random(seed)
    feature_names = [f"structure_f{index:03d}" for index in range(126)]
    fields = [
        "candidate_id", "sequence", "parent_framework_cluster", "sample_weight",
        "R_8X6B", "R_9E6Y", "R_dual_min", *feature_names,
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fields, delimiter="\t")
        writer.writeheader()
        for parent in range(6):
            for member in range(4):
                sequence = "".join(rng.choice(AA_ALPHABET[:-1]) for _ in range(22 + member))
                structure = [rng.gauss(0, 1) for _ in range(126)]
                r8 = 0.52 + 0.025 * structure[0] - 0.010 * structure[1] + 0.002 * member
                r9 = 0.53 + 0.020 * structure[0] + 0.008 * structure[2] - 0.001 * member
                row = {
                    "candidate_id": f"P{parent}_C{member}",
                    "sequence": sequence,
                    "parent_framework_cluster": f"P{parent}",
                    "sample_weight": "1.0",
                    "R_8X6B": f"{r8:.8f}",
                    "R_9E6Y": f"{r9:.8f}",
                    "R_dual_min": f"{min(r8, r9):.8f}",
                }
                row.update({name: f"{value:.8f}" for name, value in zip(feature_names, structure)})
                writer.writerow(row)


def run(output_dir: Path, device: str, epochs: int) -> dict[str, object]:
    if device.startswith("cuda"):
        require(torch.cuda.is_available(), "cuda_smoke_requested_but_unavailable")
    output_dir.mkdir(parents=True, exist_ok=True)
    table = output_dir / "synthetic.tsv"
    write_synthetic_table(table)
    args = trainer.parser().parse_args([
        "--train-tsv", str(table),
        "--output-dir", str(output_dir / "run"),
        "--backbone-kind", "tiny",
        "--device", device,
        "--epochs", str(epochs),
        "--batch-size", "4",
        "--fold-count", "3",
        "--validation-fold", "0",
        "--warmup-steps", "0",
        "--fusion-dim", "32",
        "--contact-weight", "0",
        "--ranking-weight", "0.05",
        "--uncertainty-weight", "0.05",
        "--early-stopping-patience", str(epochs + 1),
    ])
    result = trainer.train(args)
    for name in ("best.pt", "last.pt", "metrics.jsonl", "contract.json", "result.json"):
        require((output_dir / "run" / name).is_file(), f"smoke_output_missing:{name}")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--epochs", type=int, default=2)
    args = parser.parse_args(argv)
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if args.output_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="v6_gpu_smoke_")
        output_dir = Path(temporary.name)
    else:
        output_dir = args.output_dir
    result = run(output_dir, args.device, args.epochs)
    print(json.dumps(result, sort_keys=True))
    if temporary is not None:
        temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

