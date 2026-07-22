#!/usr/bin/env python3
"""Aggregate frozen clean-attention seeds without selecting a seed on development."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


HERE = Path(__file__).resolve().parent
RUNNER_PATH = HERE / "run_full10644_clean_attention_v1.py"
SPEC = importlib.util.spec_from_file_location("v211_clean_attention_runner_for_evaluation", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("runner_import_spec_invalid")
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)

SCHEMA_VERSION = "pvrig_v2_11_full10644_clean_attention_multiseed_evaluation_v1"
RESULT_NAME = "EARLY_ENRICHMENT.json"
ENSEMBLE_NAME = "ensemble_development_predictions.tsv"
SHA256SUMS_NAME = "SHA256SUMS"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RUNNER.CleanAttentionError(message)


def load_seed_prediction(
    seed_dir: Path,
    seed: int,
    truth: Mapping[str, RUNNER.CandidateRow],
) -> tuple[np.ndarray, dict[str, str]]:
    result_path = seed_dir / RUNNER.RESULT_NAME
    prediction_path = seed_dir / RUNNER.PREDICTION_NAME
    require(result_path.is_file() and not result_path.is_symlink(), f"seed_result_invalid:{seed}")
    require(prediction_path.is_file() and not prediction_path.is_symlink(), f"seed_prediction_invalid:{seed}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    require(result.get("status") == "PASS_FULL10644_CLEAN_ATTENTION_FIXED_EPOCH_TRAINING", f"seed_status_invalid:{seed}")
    require(result.get("lane") == RUNNER.LANE and int(result.get("seed", -1)) == seed, f"seed_identity_invalid:{seed}")
    require((result.get("outputs") or {}).get(RUNNER.PREDICTION_NAME) == RUNNER.sha256_file(prediction_path), f"seed_prediction_hash:{seed}")
    require(result.get("exact_min_inference") is True, f"seed_exact_min_contract:{seed}")

    loaded: dict[str, tuple[float, float]] = {}
    with prediction_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {
            "candidate_id", "parent_framework_cluster", "target_R_8X6B", "target_R_9E6Y",
            "target_R_dual_min", "prediction_R_8X6B", "prediction_R_9E6Y", "prediction_R_dual_min",
        }
        require(required <= set(reader.fieldnames or ()), f"seed_prediction_fields:{seed}")
        for raw in reader:
            candidate = raw["candidate_id"].strip()
            require(candidate in truth and candidate not in loaded, f"seed_candidate_closure:{seed}:{candidate}")
            row = truth[candidate]
            require(raw["parent_framework_cluster"].strip() == row.parent, f"seed_parent_mismatch:{seed}:{candidate}")
            target = tuple(float(raw[name]) for name in ("target_R_8X6B", "target_R_9E6Y"))
            prediction = tuple(float(raw[name]) for name in ("prediction_R_8X6B", "prediction_R_9E6Y"))
            require(all(math.isfinite(value) for value in target + prediction), f"seed_nonfinite:{seed}:{candidate}")
            require(max(abs(target[index] - row.targets[index]) for index in range(2)) <= 2e-8, f"seed_truth_mismatch:{seed}:{candidate}")
            require(abs(float(raw["target_R_dual_min"]) - min(target)) <= 2e-8, f"seed_truth_exact_min:{seed}:{candidate}")
            require(abs(float(raw["prediction_R_dual_min"]) - min(prediction)) <= 2e-8, f"seed_prediction_exact_min:{seed}:{candidate}")
            loaded[candidate] = prediction
    ordered_ids = sorted(truth)
    require(set(loaded) == set(ordered_ids), f"seed_development_exact_closure:{seed}:{len(loaded)}!={len(ordered_ids)}")
    return np.asarray([loaded[candidate] for candidate in ordered_ids], dtype=np.float64), {
        RUNNER.RESULT_NAME: RUNNER.sha256_file(result_path),
        RUNNER.PREDICTION_NAME: RUNNER.sha256_file(prediction_path),
    }


def seed_stability(candidate_ids: Sequence[str], predictions: Mapping[str, np.ndarray]) -> dict[str, Any]:
    labels = sorted(predictions, key=int)
    dual = {label: np.min(predictions[label], axis=1) for label in labels}
    stack = np.stack([dual[label] for label in labels])
    pairwise: dict[str, Any] = {}
    for left_index, left in enumerate(labels):
        for right in labels[left_index + 1:]:
            overlap: dict[str, Any] = {}
            for budget in (0.05, 0.10, 0.20):
                selected = max(1, math.ceil(len(candidate_ids) * budget))
                left_top = set(RUNNER.ranked_indices(candidate_ids, dual[left])[:selected])
                right_top = set(RUNNER.ranked_indices(candidate_ids, dual[right])[:selected])
                intersection = len(left_top & right_top)
                overlap[str(budget)] = {
                    "selected": selected,
                    "intersection": intersection,
                    "jaccard": intersection / len(left_top | right_top),
                }
            pairwise[f"{left}__{right}"] = {
                "R_dual_min_prediction_spearman": RUNNER.spearman(dual[left], dual[right]),
                "top_budget_overlap": overlap,
            }
    candidate_std = np.std(stack, axis=0)
    return {
        "seed_count": len(labels),
        "candidate_R_dual_min_prediction_std": {
            "mean": float(np.mean(candidate_std)),
            "p95": float(np.quantile(candidate_std, 0.95)),
            "max": float(np.max(candidate_std)),
        },
        "pairwise_seed_agreement": pairwise,
    }


def aggregate(contract_path: Path, run_root: Path, output_dir: Path) -> dict[str, Any]:
    contract = RUNNER.load_contract(contract_path)
    training_path = RUNNER._verify_bound_file(contract["training_table"], "training_table")
    split_path = RUNNER._verify_bound_file(contract["split_manifest"], "split_manifest")
    expected = contract["expected_counts"]
    rows = RUNNER.load_rows(training_path, int(expected["total"]))
    split = RUNNER.load_split(split_path, rows, int(expected["train"]), int(expected["development"]))
    development_rows = [rows[index] for index in split.development_indices]
    truth = {row.candidate_id: row for row in development_rows}
    candidate_ids = sorted(truth)
    parents = [truth[candidate].parent for candidate in candidate_ids]
    target = np.asarray([truth[candidate].targets for candidate in candidate_ids], dtype=np.float64)

    tasks = list(contract.get("four_gpu_tasks") or ())
    require(len(tasks) == 4 and len({int(task["seed"]) for task in tasks}) == 4, "four_seed_contract_invalid")
    require({int(task["gpu"]) for task in tasks} == {0, 1, 2, 3}, "four_gpu_contract_invalid")
    seed_predictions: dict[str, np.ndarray] = {}
    input_hashes: dict[str, dict[str, str]] = {}
    for task in tasks:
        seed = int(task["seed"])
        require(task.get("fold_id") == "D1", f"fold_contract_invalid:{seed}")
        prediction, hashes = load_seed_prediction(run_root / f"D1_seed{seed}", seed, truth)
        seed_predictions[str(seed)] = prediction
        input_hashes[str(seed)] = hashes
    ensemble = np.mean(np.stack([seed_predictions[str(int(task["seed"]))] for task in tasks]), axis=0)
    ensemble_metrics = RUNNER.comprehensive_metrics(candidate_ids, parents, target, ensemble)
    per_seed_metrics = {
        label: RUNNER.comprehensive_metrics(candidate_ids, parents, target, prediction)
        for label, prediction in seed_predictions.items()
    }

    require(not output_dir.exists(), "evaluation_output_exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        prediction_path = staging / ENSEMBLE_NAME
        with prediction_path.open("w", newline="", encoding="utf-8") as handle:
            fields = (
                "candidate_id", "parent_framework_cluster", "target_R_8X6B", "target_R_9E6Y",
                "target_R_dual_min", "ensemble_prediction_R_8X6B", "ensemble_prediction_R_9E6Y",
                "ensemble_prediction_R_dual_min",
            )
            writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for index, candidate in enumerate(candidate_ids):
                writer.writerow({
                    "candidate_id": candidate,
                    "parent_framework_cluster": truth[candidate].parent,
                    "target_R_8X6B": f"{target[index,0]:.12g}",
                    "target_R_9E6Y": f"{target[index,1]:.12g}",
                    "target_R_dual_min": f"{min(target[index]):.12g}",
                    "ensemble_prediction_R_8X6B": f"{ensemble[index,0]:.12g}",
                    "ensemble_prediction_R_9E6Y": f"{ensemble[index,1]:.12g}",
                    "ensemble_prediction_R_dual_min": f"{min(ensemble[index]):.12g}",
                })
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_FULL10644_CLEAN_ATTENTION_MULTISEED_EARLY_ENRICHMENT",
            "lane": RUNNER.LANE,
            "claim_boundary": RUNNER.CLAIM_BOUNDARY,
            "selection": "NONE_REPORT_ALL_FROZEN_SEEDS_AND_MEAN_R8_R9_ENSEMBLE",
            "counts": {
                "train": len(split.train_indices),
                "development": len(split.development_indices),
                "train_parents": len(split.train_parents),
                "development_parents": len(split.development_parents),
                "seed_runs": len(tasks),
            },
            "seeds": [int(task["seed"]) for task in tasks],
            "per_seed_metrics": per_seed_metrics,
            "mean_R8_R9_then_exact_min_ensemble_metrics": ensemble_metrics,
            "seed_stability": seed_stability(candidate_ids, seed_predictions),
            "inputs": {
                "contract_sha256": RUNNER.sha256_file(contract_path),
                "training_table_sha256": RUNNER.sha256_file(training_path),
                "split_manifest_sha256": RUNNER.sha256_file(split_path),
                "runner_sha256": RUNNER.sha256_file(RUNNER_PATH),
                "seed_artifacts": input_hashes,
            },
            "input_access": {"frozen_test_access_count": 0, "sealed_truth_access_count": 0},
            "outputs": {ENSEMBLE_NAME: RUNNER.sha256_file(prediction_path)},
        }
        result_path = staging / RESULT_NAME
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        hashes = {
            RESULT_NAME: RUNNER.sha256_file(result_path),
            ENSEMBLE_NAME: RUNNER.sha256_file(prediction_path),
        }
        (staging / SHA256SUMS_NAME).write_text(
            "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())), encoding="utf-8",
        )
        os.replace(staging, output_dir)
        return result
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = aggregate(args.contract, args.run_root, args.output_dir)
    print(json.dumps({
        "status": result["status"],
        "seed_runs": result["counts"]["seed_runs"],
        "development": result["counts"]["development"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
