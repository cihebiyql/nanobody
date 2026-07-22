#!/usr/bin/env python3
"""Aggregate the promoted V2.13 variant across frozen seeds 43/917/1931."""

from __future__ import annotations

import argparse
import csv
import hashlib
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
SPEC = importlib.util.spec_from_file_location("v213_selector_for_multiseed", HERE / "select_phase_a_variant_v1.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("selector_import_invalid")
SELECTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SELECTOR
SPEC.loader.exec_module(SELECTOR)

SCHEMA = "pvrig_v2_13_phase_b_3seed_aggregate_v1"
SEEDS = (43, 917, 1931)


class AggregateError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AggregateError(message)


def sha256_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"regular_file_required:{path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"tsv_invalid:{path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields, rows = list(reader.fieldnames or ()), [dict(row) for row in reader]
    require(fields and rows, f"tsv_empty:{path}")
    return fields, rows


def rank_percentile(values: np.ndarray) -> np.ndarray:
    return (SELECTOR.rankdata(values) - 1.0) / max(1, len(values) - 1)


def aggregate(
    promotion_contract: Path,
    selection_path: Path,
    seed_paths: Mapping[int, Path],
    output_dir: Path,
) -> dict[str, Any]:
    require(not output_dir.exists(), "output_exists")
    promotion = json.loads(promotion_contract.read_text(encoding="utf-8"))
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    require(promotion.get("schema_version") == "pvrig_v2_13_phase_b_promotion_contract_v1", "promotion_schema")
    require(promotion.get("status") == "FROZEN_RESULT_BLIND_DURING_PHASE_A_TRAINING", "promotion_status")
    require(selection.get("status") == "PASS_PHASE_A_VARIANT_PROMOTED", "selection_status")
    require(selection.get("input_access") == {"open_development_rows": 0, "frozen_test_rows": 0}, "selection_access")
    variant = selection.get("selected_variant")
    require(variant in {"L1", "L2", "L3"}, "variant_invalid")
    require(set(seed_paths) == set(SEEDS), "seed_path_closure")
    loaded: dict[int, dict[str, dict[str, str]]] = {}
    fields_required = {"candidate_id", "sequence_sha256", "parent_framework_cluster", "fold_id", "seed", "variant", "truth_R8", "truth_R9", "truth_Rdual_exact_min"}
    for seed, path in sorted(seed_paths.items()):
        fields, rows = read_tsv(path)
        prediction_fields = {f"B_TOP5_{variant}__R8", f"B_TOP5_{variant}__R9", f"B_TOP5_{variant}__Rdual_exact_min"}
        require(fields_required | prediction_fields <= set(fields), f"seed_fields:{seed}")
        by_id = {row["candidate_id"]: row for row in rows}
        require(len(by_id) == len(rows) == 9849, f"seed_candidate_closure:{seed}")
        require({int(row["seed"]) for row in rows} == {seed}, f"seed_identity:{seed}")
        require({row["variant"] for row in rows} == {variant}, f"variant_identity:{seed}")
        loaded[seed] = by_id
    candidates = sorted(loaded[43])
    require(all(set(loaded[seed]) == set(candidates) for seed in SEEDS), "cross_seed_candidate_closure")
    ids, sequence_sha, parents, folds, truth = [], [], [], [], []
    receptor_by_seed: dict[int, list[tuple[float, float]]] = {seed: [] for seed in SEEDS}
    for candidate in candidates:
        reference = loaded[43][candidate]
        ids.append(candidate); sequence_sha.append(reference["sequence_sha256"]); parents.append(reference["parent_framework_cluster"]); folds.append(int(reference["fold_id"]))
        truth_pair = (float(reference["truth_R8"]), float(reference["truth_R9"]))
        require(abs(float(reference["truth_Rdual_exact_min"]) - min(truth_pair)) <= 4e-8, f"truth_exact_min:{candidate}")
        truth.append(truth_pair)
        for seed in SEEDS:
            row = loaded[seed][candidate]
            require((row["sequence_sha256"], row["parent_framework_cluster"], int(row["fold_id"])) == (sequence_sha[-1], parents[-1], folds[-1]), f"identity_mismatch:{seed}:{candidate}")
            seed_truth = (float(row["truth_R8"]), float(row["truth_R9"]))
            require(max(abs(a-b) for a, b in zip(seed_truth, truth_pair)) <= 4e-8, f"truth_mismatch:{seed}:{candidate}")
            pair = (float(row[f"B_TOP5_{variant}__R8"]), float(row[f"B_TOP5_{variant}__R9"]))
            reported = float(row[f"B_TOP5_{variant}__Rdual_exact_min"])
            require(all(math.isfinite(value) for value in pair) and abs(reported-min(pair)) <= 4e-8, f"prediction_exact_min:{seed}:{candidate}")
            receptor_by_seed[seed].append(pair)
    truth_array = np.asarray(truth, dtype=np.float64)
    seed_arrays = {seed: np.asarray(receptor_by_seed[seed], dtype=np.float64) for seed in SEEDS}
    mean_receptor = np.mean(np.stack([seed_arrays[seed] for seed in SEEDS]), axis=0)
    mean_dual = np.min(mean_receptor, axis=1)
    seed_dual = {seed: np.min(seed_arrays[seed], axis=1) for seed in SEEDS}
    mean_rank = np.mean(np.column_stack([rank_percentile(seed_dual[seed]) for seed in SEEDS]), axis=1)
    truth_dual = np.min(truth_array, axis=1)
    fold_array = np.asarray(folds, dtype=np.int64)
    primary_metrics = SELECTOR.metrics(ids, fold_array, truth_dual, mean_dual)
    per_seed_metrics = {str(seed): SELECTOR.metrics(ids, fold_array, truth_dual, seed_dual[seed]) for seed in SEEDS}
    mean_rank_metrics = SELECTOR.metrics(ids, fold_array, truth_dual, mean_rank)
    phase_c = promotion["phase_c_gate"]
    selected_seed43_ef5 = float(selection["variants"][variant]["pooled_ef5"])
    checks = {
        "ensemble_ef5_not_below_seed43": primary_metrics["pooled_ef5"] >= selected_seed43_ef5,
        "ef10": primary_metrics["pooled_ef10"] >= float(phase_c["minimum_ef10"]),
        "spearman": primary_metrics["rdual_spearman"] >= float(phase_c["minimum_rdual_spearman"]),
        "mae": primary_metrics["rdual_mae"] <= float(phase_c["maximum_rdual_mae"]),
        "seed_count": sum(value["pooled_ef5"] >= float(promotion["baseline"]["ef5"])-0.20 for value in per_seed_metrics.values()) >= int(phase_c["minimum_seeds_with_ef5_at_least_baseline_minus_0p20"]),
        "minimum_seed": min(value["pooled_ef5"] for value in per_seed_metrics.values()) >= float(phase_c["minimum_allowed_seed_ef5"]),
    }
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        output_name = f"TOP5_{variant}_3SEED_OOF_PREDICTIONS.tsv"
        output_path = staging / output_name
        fields = ["candidate_id", "sequence_sha256", "parent_framework_cluster", "fold_id", "truth_R8", "truth_R9", "truth_Rdual_exact_min"]
        for seed in SEEDS:
            fields += [f"seed{seed}_R8", f"seed{seed}_R9", f"seed{seed}_Rdual_exact_min", f"seed{seed}_rank_percentile"]
        fields += ["mean_R8", "mean_R9", "primary_Rdual_exact_min", "mean_seed_rank", "seed_Rdual_std"]
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n"); writer.writeheader()
            ranks = {seed: rank_percentile(seed_dual[seed]) for seed in SEEDS}
            for index, candidate in enumerate(ids):
                row: dict[str, Any] = {"candidate_id": candidate, "sequence_sha256": sequence_sha[index], "parent_framework_cluster": parents[index], "fold_id": folds[index], "truth_R8": truth_array[index,0], "truth_R9": truth_array[index,1], "truth_Rdual_exact_min": truth_dual[index]}
                for seed in SEEDS:
                    row.update({f"seed{seed}_R8": seed_arrays[seed][index,0], f"seed{seed}_R9": seed_arrays[seed][index,1], f"seed{seed}_Rdual_exact_min": seed_dual[seed][index], f"seed{seed}_rank_percentile": ranks[seed][index]})
                row.update({"mean_R8": mean_receptor[index,0], "mean_R9": mean_receptor[index,1], "primary_Rdual_exact_min": mean_dual[index], "mean_seed_rank": mean_rank[index], "seed_Rdual_std": float(np.std([seed_dual[seed][index] for seed in SEEDS]))})
                writer.writerow(row)
        metrics = {"primary_mean_receptors_then_min": primary_metrics, "secondary_mean_seed_rank": mean_rank_metrics, "per_seed": per_seed_metrics, "phase_c_gate_checks": checks}
        metrics_path = staging / "PHASE_B_METRICS.json"; metrics_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
        receipt = {
            "schema_version": SCHEMA,
            "status": "PASS_PHASE_B_PROMOTED_TO_PHASE_C" if all(checks.values()) else "PASS_PHASE_B_COMPLETE_NO_PHASE_C_PROMOTION",
            "selected_variant": variant,
            "counts": {"candidates": 9849, "parents": len(set(parents)), "seeds": 3, "folds": len(set(folds))},
            "primary_ensemble": "mean_R8_and_mean_R9_then_exact_min",
            "bad_seed_excluded": False,
            "input_bindings": {"promotion_contract_sha256": sha256_file(promotion_contract), "selection_sha256": sha256_file(selection_path), "seed_oof": {str(seed): sha256_file(seed_paths[seed]) for seed in SEEDS}},
            "input_access": {"open_development_rows": 0, "frozen_test_rows": 0},
            "outputs": {output_name: sha256_file(output_path), "PHASE_B_METRICS.json": sha256_file(metrics_path)},
        }
        receipt_path = staging / "PHASE_B_RECEIPT.json"; receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        hashes = {path.name: sha256_file(path) for path in staging.iterdir() if path.is_file()}
        (staging / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name,digest in sorted(hashes.items())))
        os.replace(staging, output_dir)
        return receipt
    finally:
        if staging.exists(): shutil.rmtree(staging)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promotion-contract", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--seed43-oof", type=Path, required=True)
    parser.add_argument("--seed917-oof", type=Path, required=True)
    parser.add_argument("--seed1931-oof", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = aggregate(args.promotion_contract, args.selection, {43: args.seed43_oof, 917: args.seed917_oof, 1931: args.seed1931_oof}, args.output_dir)
    print(json.dumps({"status": result["status"], "selected_variant": result["selected_variant"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
