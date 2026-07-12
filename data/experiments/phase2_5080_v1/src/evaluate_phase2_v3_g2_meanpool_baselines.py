#!/usr/bin/env python3
"""Evaluate frozen mean-pooled V3 baselines on the V3-G2 cluster-safe test."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
import torch

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from phase2_v3_contracts import sha256_file, write_csv_atomic, write_json_atomic
from phase2_v3_metrics import binary_ranking_metrics, macro_target_average_precision
from phase2_v3_model import (
    BindingPriorModel,
    fixed_esm2_cosine,
    frame_pair_indices,
    load_embedding_bank,
    score_model,
)

DEFAULT_BINDING = EXP_DIR / "prepared/phase2_v3_g2/binding_cluster_safe_v1.csv"
DEFAULT_EMBEDDINGS = EXP_DIR / "prepared/phase2_v3_binding/embeddings/embedding_manifest_v3.csv"
DEFAULT_RUN_ROOT = EXP_DIR / "runs/phase2_v3_g2_meanpool_baselines"
ELIGIBLE = ("prevalence", "frozen_esm2_cosine", "vhh_only", "esm2_pair", "v3_full")


def latest_train_summary(run_root: Path) -> Path:
    summaries = sorted(run_root.glob("*/train_summary.json"), key=lambda path: path.stat().st_mtime)
    if not summaries:
        raise FileNotFoundError(f"No mean-pool train summary under {run_root}")
    return summaries[-1]


def metric_bundle(labels: np.ndarray, scores: np.ndarray, targets: Sequence[str]) -> dict[str, Any]:
    metrics = binary_ranking_metrics(labels, scores)
    macro, per_target = macro_target_average_precision(labels, scores, targets)
    metrics.update({"macro_target_average_precision": macro, "target_average_precision": per_target})
    return metrics


def evaluate(
    train_summary_path: Path,
    binding_path: Path,
    embedding_manifest: Path,
    output_dir: Path | None,
    device_name: str,
    batch_size: int,
) -> dict[str, Any]:
    train_summary = json.loads(train_summary_path.read_text(encoding="utf-8"))
    frame = pd.read_csv(binding_path)
    test = frame[frame["split"].astype(str) == "test"].copy().reset_index(drop=True)
    train = frame[frame["split"].astype(str) == "train"]
    if test.empty or set(test["label"].astype(int).unique()) != {0, 1}:
        raise ValueError("Cluster-safe test must contain both real labels")
    device = torch.device(device_name)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    bank_cpu = load_embedding_bank(embedding_manifest)
    vhh_index, target_index = frame_pair_indices(test, bank_cpu)
    bank = bank_cpu.to(device)
    labels = test["label"].astype(int).to_numpy()
    targets = test["target_id"].astype(str).tolist()

    scores: dict[str, np.ndarray] = {
        "prevalence": np.full(len(test), float(train["label"].mean()), dtype=np.float64),
        "frozen_esm2_cosine": fixed_esm2_cosine(
            bank, vhh_index.to(device), target_index.to(device)
        ).detach().cpu().numpy(),
    }
    seed_metrics: dict[str, list[dict[str, Any]]] = {}
    for variant in ("vhh_only", "esm2_pair", "v3_full"):
        variant_scores = []
        seed_metrics[variant] = []
        for result in train_summary["results"][variant]:
            checkpoint_path = Path(result["checkpoint"])
            checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
            model = BindingPriorModel(**checkpoint["model_config"])
            model.load_state_dict(checkpoint["state_dict"])
            model.to(device)
            values = score_model(model, bank, vhh_index, target_index, batch_size, device).numpy()
            variant_scores.append(values)
            seed_metrics[variant].append(
                {
                    "seed": int(checkpoint["seed"]),
                    "checkpoint": str(checkpoint_path),
                    "checkpoint_sha256": sha256_file(checkpoint_path),
                    "test_metrics": metric_bundle(labels, values, targets),
                }
            )
        scores[variant] = np.mean(variant_scores, axis=0)

    test_metrics = {name: metric_bundle(labels, values, targets) for name, values in scores.items()}
    dev_metrics = train_summary["development_metrics"]
    strongest = max(
        ELIGIBLE,
        key=lambda name: (
            float(dev_metrics[name]["macro_target_average_precision"]),
            -ELIGIBLE.index(name),
        ),
    )
    output_dir = output_dir or train_summary_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    prediction_rows = []
    for index, row in test[["sample_id", "dataset_id", "target_id", "cluster_id", "label"]].iterrows():
        output = row.to_dict()
        output.update({name: float(values[index]) for name, values in scores.items()})
        prediction_rows.append(output)
    prediction_path = output_dir / "cluster_safe_test_predictions.csv"
    write_csv_atomic(prediction_path, prediction_rows, list(prediction_rows[0]))
    summary: dict[str, Any] = {
        "status": "PASS_MEANPOOL_BASELINES_EVALUATED",
        "schema_version": "phase2_v3_g2_meanpool_test_summary_v1",
        "train_summary": str(train_summary_path),
        "train_summary_sha256": sha256_file(train_summary_path),
        "binding_csv": str(binding_path),
        "binding_csv_sha256": sha256_file(binding_path),
        "embedding_manifest": str(embedding_manifest),
        "embedding_manifest_sha256": sha256_file(embedding_manifest),
        "test_rows": len(test),
        "strongest_baseline_selected_on_dev": strongest,
        "strongest_baseline_dev_macro_target_ap": float(dev_metrics[strongest]["macro_target_average_precision"]),
        "strongest_baseline_test_macro_target_ap": float(test_metrics[strongest]["macro_target_average_precision"]),
        "development_metrics": {name: dev_metrics[name] for name in ELIGIBLE},
        "test_metrics": test_metrics,
        "per_seed_test_metrics": seed_metrics,
        "test_predictions": str(prediction_path),
        "test_predictions_sha256": sha256_file(prediction_path),
        "claim_boundary": "mean_pooled_generic_binding_baseline_not_pvrig_blocking_truth",
    }
    write_json_atomic(output_dir / "cluster_safe_test_summary.json", summary)
    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-summary", type=Path)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--binding", type=Path, default=DEFAULT_BINDING)
    parser.add_argument("--embedding-manifest", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--batch-size", type=int, default=8192)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    train_summary = args.train_summary or latest_train_summary(args.run_root)
    summary = evaluate(
        train_summary,
        args.binding,
        args.embedding_manifest,
        args.output_dir,
        args.device,
        args.batch_size,
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "strongest_baseline": summary["strongest_baseline_selected_on_dev"],
                "test_macro_target_ap": summary["strongest_baseline_test_macro_target_ap"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
