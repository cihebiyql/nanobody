#!/usr/bin/env python3
"""Collect only predeclared outer0/inner0 open-validation pilot metrics.

GPU jobs must score without metrics.  This collector is the only component
allowed to join predictions to the inner0 score-parent truth.  It rejects any
outer-test or sealed reference and validates per-step/checkpoint/prediction
hash closure before computing metrics.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


VARIANT_SEEDS = {
    "F0_SHARED_GATED_NO_RANK": (43, 97, 193),
    "F1_SHARED_GATED_V4D_EXACT_MIN_RANK": (43, 97, 193),
    "B_SCALAR_ATTENTION_ONLY": (43,),
    "E_STRICT_DETACHED_DYNAMICS_CONTROL": (43,),
}


class ContractError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file() and not path.is_symlink(), f"tsv_not_regular:{path}")
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _rank(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and values[order[end]] == values[order[cursor]]:
            end += 1
        value = (cursor + end - 1) / 2.0 + 1.0
        for position in range(cursor, end):
            ranks[order[position]] = value
        cursor = end
    return ranks


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    require(len(left) == len(right) and len(left) >= 2, "pearson_length")
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    denominator = math.sqrt(
        sum((a - mean_left) ** 2 for a in left) * sum((b - mean_right) ** 2 for b in right)
    )
    return 0.0 if denominator == 0.0 else numerator / denominator


def metric_block(truth: Sequence[float], prediction: Sequence[float]) -> dict[str, float]:
    require(len(truth) == len(prediction) and len(truth) >= 2, "metric_length")
    errors = [predicted - observed for observed, predicted in zip(truth, prediction)]
    return {
        "spearman": _pearson(_rank(truth), _rank(prediction)),
        "mae": sum(abs(value) for value in errors) / len(errors),
        "rmse": math.sqrt(sum(value * value for value in errors) / len(errors)),
    }


def validate_job(job_dir: Path, variant: str, seed: int) -> tuple[list[dict[str, str]], dict[str, Any]]:
    result_path = job_dir / "RESULT.json"
    require(result_path.is_file() and not result_path.is_symlink(), f"result_missing:{variant}:{seed}")
    result = json.loads(result_path.read_text())
    require(str(result.get("status", "")).startswith("PASS"), f"job_not_pass:{variant}:{seed}")
    require(result.get("variant") == variant and int(result.get("seed", -1)) == seed, "job_identity_mismatch")
    require(int(result.get("outer_fold", -1)) == 0 and int(result.get("inner_fold", -1)) == 0, "job_split_mismatch")
    for field in ("outer_test_truth_access_count", "outer_metrics_access_count", "v4_f_test32_access_count"):
        require(result.get(field) == 0, f"job_firewall_nonzero:{field}")
    require(result.get("exact_min_violation_count") == 0, "job_exact_min_violation")
    artifacts = result.get("artifacts", {})
    required = {
        "training_receipt": "TRAINING_RECEIPT.json",
        "step_evidence": "STEP_EVIDENCE.jsonl",
        "checkpoint": "neural_head.pt",
        "predictions": "score_predictions_no_metrics.tsv",
    }
    for key, default_name in required.items():
        item = artifacts.get(key)
        require(isinstance(item, dict), f"job_artifact_missing:{key}")
        path = job_dir / str(item.get("path", default_name))
        require(path.is_file() and not path.is_symlink(), f"job_artifact_not_regular:{key}")
        require(sha256_file(path) == item.get("sha256"), f"job_artifact_hash:{key}")
    step_item = artifacts["step_evidence"]
    step_path = job_dir / str(step_item["path"])
    nonempty_lines = [line for line in step_path.read_text().splitlines() if line.strip()]
    require(len(nonempty_lines) == int(step_item.get("rows", -1)), "step_evidence_declared_rows")
    require(len(nonempty_lines) == int(result.get("optimizer_steps", -2)), "step_evidence_optimizer_steps")
    for line in nonempty_lines:
        event = json.loads(line)
        require(event.get("finite_state") is True, "step_nonfinite")
        require(event.get("v4_f_test32_access_count") == 0, "step_sealed_access")
    training = json.loads((job_dir / str(artifacts["training_receipt"]["path"])).read_text())
    require(training.get("score_truth_rows_accessed") == 0, "training_score_truth_access")
    require(training.get("outer_metrics_access_count") == 0, "training_outer_metrics_access")
    require(training.get("v4_f_test32_access_count") == 0, "training_sealed_access")
    predictions = read_tsv(job_dir / str(artifacts["predictions"]["path"]))
    require(len(predictions) == int(artifacts["predictions"].get("rows", -1)), "prediction_row_count")
    return predictions, result


def load_truth(training_tsv: Path, split_manifest: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    require(split_manifest.is_file() and not split_manifest.is_symlink(), "split_manifest_not_regular")
    split = json.loads(split_manifest.read_text())
    require(split.get("open_only") is True and split.get("split_id") == "outer_0_inner_0", "split_identity")
    require(int(split.get("outer_fold", -1)) == 0, "split_outer_fold")
    require(split.get("v4_f_test32_access_count") == 0, "split_sealed_access")
    train_parents = set(map(str, split["train_parents"]))
    score_parents = set(map(str, split["score_parents"]))
    require(train_parents.isdisjoint(score_parents), "split_parent_overlap")
    rows = read_tsv(training_tsv)
    observed_parents = {row["parent_framework_cluster"] for row in rows}
    require(observed_parents == train_parents | score_parents, "training_parent_closure")
    truth: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["parent_framework_cluster"] not in score_parents:
            continue
        candidate = row["candidate_id"]
        require(candidate not in truth, "truth_candidate_duplicate")
        r8 = float(row["R_8X6B"])
        r9 = float(row["R_9E6Y"])
        dual = float(row["R_dual_min"])
        require(abs(dual - min(r8, r9)) <= 1e-12, "truth_exact_min_violation")
        truth[candidate] = {"parent": row["parent_framework_cluster"], "R8": r8, "R9": r9, "Rdual": dual}
    require(truth, "inner_score_truth_empty")
    return truth, split


def aggregate_predictions(
    variant: str,
    seed_rows: Sequence[tuple[int, Sequence[dict[str, str]]]],
    truth: dict[str, dict[str, Any]],
) -> dict[str, dict[str, float]]:
    by_seed: dict[int, dict[str, dict[str, str]]] = {}
    for seed, rows in seed_rows:
        mapping = {row["candidate_id"]: row for row in rows}
        require(len(mapping) == len(rows), f"prediction_candidate_duplicate:{variant}:{seed}")
        require(set(mapping) == set(truth), f"prediction_truth_closure:{variant}:{seed}")
        by_seed[seed] = mapping
    require(set(by_seed) == set(VARIANT_SEEDS[variant]), f"seed_closure:{variant}")
    aggregated: dict[str, dict[str, float]] = {}
    for candidate in sorted(truth):
        r8_values = [float(by_seed[seed][candidate]["neural_R8"]) for seed in VARIANT_SEEDS[variant]]
        r9_values = [float(by_seed[seed][candidate]["neural_R9"]) for seed in VARIANT_SEEDS[variant]]
        for seed in VARIANT_SEEDS[variant]:
            row = by_seed[seed][candidate]
            require(abs(float(row["neural_Rdual"]) - min(float(row["neural_R8"]), float(row["neural_R9"]))) <= 1e-12, "prediction_exact_min")
        r8 = sum(r8_values) / len(r8_values)
        r9 = sum(r9_values) / len(r9_values)
        aggregated[candidate] = {"R8": r8, "R9": r9, "Rdual": min(r8, r9)}
    return aggregated


def parent_macro(
    truth: dict[str, dict[str, Any]], predictions: dict[str, dict[str, float]]
) -> dict[str, float]:
    groups: dict[str, list[str]] = defaultdict(list)
    for candidate, record in truth.items():
        groups[str(record["parent"])].append(candidate)
    blocks = []
    within = []
    for parent in sorted(groups):
        ids = groups[parent]
        observed = [float(truth[candidate]["Rdual"]) for candidate in ids]
        predicted = [float(predictions[candidate]["Rdual"]) for candidate in ids]
        block = metric_block(observed, predicted)
        blocks.append(block)
        if len(ids) >= 3:
            within.append(block["spearman"])
    return {
        "parent_count": len(groups),
        "macro_mae": sum(block["mae"] for block in blocks) / len(blocks),
        "macro_rmse": sum(block["rmse"] for block in blocks) / len(blocks),
        "macro_within_parent_spearman": sum(within) / len(within) if within else 0.0,
        "parents_within_spearman": len(within),
    }


def evaluate_variant(
    truth: dict[str, dict[str, Any]], predictions: dict[str, dict[str, float]]
) -> dict[str, Any]:
    ids = sorted(truth)
    metrics = {}
    for target in ("R8", "R9", "Rdual"):
        metrics[target] = metric_block(
            [float(truth[candidate][target]) for candidate in ids],
            [float(predictions[candidate][target]) for candidate in ids],
        )
    metrics["parent_macro_Rdual"] = parent_macro(truth, predictions)
    metrics["rows"] = len(ids)
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--training-tsv", type=Path, required=True)
    parser.add_argument("--expected-training-tsv-sha256", required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--expected-split-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require(args.job_id == "outer0.inner0.collect_open_inner_metrics", "collector_job_id")
    require(not args.output_dir.exists(), "output_dir_exists")
    require(sha256_file(args.training_tsv) == args.expected_training_tsv_sha256, "training_tsv_hash")
    require(sha256_file(args.split_manifest) == args.expected_split_manifest_sha256, "split_manifest_hash")
    truth, split = load_truth(args.training_tsv, args.split_manifest)
    variant_predictions = {}
    job_receipts = []
    for variant, seeds in VARIANT_SEEDS.items():
        seed_rows = []
        for seed in seeds:
            job_dir = args.runtime_root / "gpu_jobs" / variant / f"seed_{seed}"
            rows, result = validate_job(job_dir, variant, seed)
            seed_rows.append((seed, rows))
            job_receipts.append({"variant": variant, "seed": seed, "result_sha256": sha256_file(job_dir / "RESULT.json")})
        variant_predictions[variant] = aggregate_predictions(variant, seed_rows, truth)
    metrics = {variant: evaluate_variant(truth, prediction) for variant, prediction in variant_predictions.items()}
    comparisons = {
        "F1_minus_F0_Rdual_spearman": metrics["F1_SHARED_GATED_V4D_EXACT_MIN_RANK"]["Rdual"]["spearman"] - metrics["F0_SHARED_GATED_NO_RANK"]["Rdual"]["spearman"],
        "F0_minus_B_Rdual_spearman": metrics["F0_SHARED_GATED_NO_RANK"]["Rdual"]["spearman"] - metrics["B_SCALAR_ATTENTION_ONLY"]["Rdual"]["spearman"],
        "F0_minus_E_Rdual_spearman": metrics["F0_SHARED_GATED_NO_RANK"]["Rdual"]["spearman"] - metrics["E_STRICT_DETACHED_DYNAMICS_CONTROL"]["Rdual"]["spearman"],
    }
    result = {
        "schema_version": "pvrig_v2_6_inner_only_pilot_metrics_recovery_v1_2_1",
        "status": "PASS_OPEN_INNER_ONLY_PILOT_METRICS_RECOVERY_V1_2_1",
        "job_id": args.job_id,
        "claim_boundary": "open-development inner-validation computational Docking-geometry surrogate only",
        "split_id": split["split_id"],
        "inner_score_rows": len(truth),
        "inner_score_parents": len(split["score_parents"]),
        "variant_metrics": metrics,
        "comparisons": comparisons,
        "job_receipts": job_receipts,
        "outer_test_truth_access_count": 0,
        "outer_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
    }
    args.output_dir.mkdir(parents=True)
    atomic_json(args.output_dir / "INNER_PILOT_METRICS.json", result)
    atomic_json(args.output_dir / "RESULT.json", result)
    print(json.dumps({"status": result["status"], "rows": len(truth), **comparisons}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
