#!/usr/bin/env python3
"""Collect audited early-enrichment metrics on open inner validation only."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "pvrig_v2_6_open_inner_early_enrichment_v1"
FIREWALL_FIELDS = ("outer_test_truth_access_count", "outer_metrics_access_count", "v4_f_test32_access_count")
POSITIVE_FRACTIONS = (0.10, 0.20)
BUDGET_FRACTIONS = (0.05, 0.10, 0.20)


class ContractError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
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


def load_truth(training_tsv: Path, split_manifest: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    split = json.loads(split_manifest.read_text())
    require(split.get("open_only") is True and split.get("split_id") == "outer_0_inner_0", "split_identity")
    require(split.get("v4_f_test32_access_count") == 0, "split_sealed_access")
    score_parents = set(map(str, split["score_parents"]))
    train_parents = set(map(str, split["train_parents"]))
    require(score_parents.isdisjoint(train_parents), "parent_overlap")
    truth = {}
    for row in read_tsv(training_tsv):
        if row["parent_framework_cluster"] not in score_parents:
            continue
        candidate = row["candidate_id"]
        require(candidate not in truth, "truth_duplicate")
        r8, r9, dual = float(row["R_8X6B"]), float(row["R_9E6Y"]), float(row["R_dual_min"])
        require(abs(dual - min(r8, r9)) <= 1e-12, "truth_exact_min")
        truth[candidate] = {"parent": row["parent_framework_cluster"], "Rdual": dual}
    require(len(truth) == 184, "truth_row_count")
    return truth, split


def validate_job(job_dir: Path, variant: str, seed: int, truth_ids: set[str]) -> dict[str, dict[str, float]]:
    result_path = job_dir / "RESULT.json"
    require(result_path.is_file() and not result_path.is_symlink(), f"result_missing:{variant}:{seed}")
    result = json.loads(result_path.read_text())
    require(str(result.get("status", "")).startswith("PASS"), f"result_status:{variant}:{seed}")
    require(result.get("variant") == variant and int(result.get("seed", -1)) == seed, "result_identity")
    require(int(result.get("outer_fold", -1)) == 0 and int(result.get("inner_fold", -1)) == 0, "result_split")
    require(all(result.get(field) == 0 for field in FIREWALL_FIELDS), "result_firewall")
    require(result.get("exact_min_violation_count") == 0, "result_exact_min")
    item = result["artifacts"]["predictions"]
    prediction_path = job_dir / item["path"]
    require(prediction_path.is_file() and not prediction_path.is_symlink(), "prediction_missing")
    require(sha256_file(prediction_path) == item["sha256"], "prediction_hash")
    rows = read_tsv(prediction_path)
    require(len(rows) == item["rows"], "prediction_rows")
    mapping = {}
    for row in rows:
        candidate = row["candidate_id"]
        r8, r9, dual = float(row["neural_R8"]), float(row["neural_R9"]), float(row["neural_Rdual"])
        require(abs(dual - min(r8, r9)) <= 1e-12, "prediction_exact_min")
        require(candidate not in mapping, "prediction_duplicate")
        mapping[candidate] = {"R8": r8, "R9": r9}
    require(set(mapping) == truth_ids, "prediction_truth_closure")
    return mapping


def aggregate(seed_maps: Sequence[Mapping[str, Mapping[str, float]]]) -> dict[str, float]:
    candidates = set(seed_maps[0])
    require(all(set(item) == candidates for item in seed_maps), "seed_candidate_closure")
    result = {}
    for candidate in candidates:
        r8 = sum(item[candidate]["R8"] for item in seed_maps) / len(seed_maps)
        r9 = sum(item[candidate]["R9"] for item in seed_maps) / len(seed_maps)
        result[candidate] = min(r8, r9)
    return result


def top_ids(values: Mapping[str, float], count: int) -> list[str]:
    return [candidate for candidate, _score in sorted(values.items(), key=lambda item: (-item[1], item[0]))[:count]]


def score_tie_diagnostics(values: Mapping[str, float]) -> dict[str, Any]:
    groups: dict[float, int] = defaultdict(int)
    for score in values.values():
        groups[float(score)] += 1
    return {
        "unique_score_count": len(groups),
        "maximum_exact_tie_size": max(groups.values()),
        "rows_in_nontrivial_exact_ties": sum(size for size in groups.values() if size > 1),
    }


def boundary_tie_hits(
    truth_positives: set[str], prediction: Mapping[str, float], budget_count: int
) -> dict[str, Any]:
    ordered = top_ids(prediction, len(prediction))
    cutoff = float(prediction[ordered[budget_count - 1]])
    above = {candidate for candidate, score in prediction.items() if float(score) > cutoff}
    tied = {candidate for candidate, score in prediction.items() if float(score) == cutoff}
    slots = budget_count - len(above)
    require(0 < slots <= len(tied), "boundary_tie_slot_contract")
    positive_above = len(above & truth_positives)
    positive_tied = len(tied & truth_positives)
    nonpositive_tied = len(tied) - positive_tied
    deterministic = set(ordered[:budget_count])
    return {
        "cutoff_score": cutoff,
        "strictly_above_count": len(above),
        "cutoff_exact_tie_count": len(tied),
        "slots_selected_from_cutoff_tie": slots,
        "positive_strictly_above": positive_above,
        "positive_in_cutoff_tie": positive_tied,
        "deterministic_candidate_id_tiebreak_hits": len(deterministic & truth_positives),
        "worst_case_hits": positive_above + max(0, slots - nonpositive_tied),
        "best_case_hits": positive_above + min(slots, positive_tied),
        "uniform_random_tie_expected_hits": positive_above + slots * positive_tied / len(tied),
        "tiebreak_policy": "score_desc_then_candidate_id_asc",
    }


def dcg(binary: Sequence[int]) -> float:
    return sum(value / math.log2(index + 2) for index, value in enumerate(binary))


def enrichment_block(truth: Mapping[str, float], prediction: Mapping[str, float]) -> dict[str, Any]:
    n = len(truth)
    output = {}
    for positive_fraction in POSITIVE_FRACTIONS:
        positive_count = math.ceil(n * positive_fraction)
        positive_floor_count = max(1, math.floor(n * positive_fraction))
        positives = set(top_ids(truth, positive_count))
        prevalence = positive_count / n
        budget_metrics = {}
        for budget_fraction in BUDGET_FRACTIONS:
            budget_count = math.ceil(n * budget_fraction)
            budget_floor_count = max(1, math.floor(n * budget_fraction))
            selected = top_ids(prediction, budget_count)
            floor_selected = top_ids(prediction, budget_floor_count)
            hits = sum(candidate in positives for candidate in selected)
            precision = hits / budget_count
            recall = hits / positive_count
            binary = [int(candidate in positives) for candidate in selected]
            ideal = [1] * min(positive_count, budget_count) + [0] * max(0, budget_count - positive_count)
            budget_metrics[f"pred_top_{int(budget_fraction*100)}pct"] = {
                "budget_count": budget_count,
                "raw_budget_count": n * budget_fraction,
                "budget_count_rounding": "ceil",
                "hits": hits,
                "precision": precision,
                "recall": recall,
                "enrichment_factor": precision / prevalence,
                "binary_ndcg": dcg(binary) / dcg(ideal),
                "boundary_tie": boundary_tie_hits(positives, prediction, budget_count),
                "floor_rounding_sensitivity": {
                    "budget_count": budget_floor_count,
                    "hits": sum(candidate in positives for candidate in floor_selected),
                    "boundary_tie": boundary_tie_hits(positives, prediction, budget_floor_count),
                },
            }
        output[f"true_top_{int(positive_fraction*100)}pct"] = {
            "positive_count": positive_count,
            "positive_floor_count": positive_floor_count,
            "positive_count_rounding": "ceil",
            "prevalence": prevalence,
            "budgets": budget_metrics,
        }
    return output


def within_parent(truth_records: Mapping[str, Mapping[str, Any]], prediction: Mapping[str, float]) -> dict[str, Any]:
    groups: dict[str, list[str]] = defaultdict(list)
    for candidate, row in truth_records.items():
        groups[str(row["parent"])].append(candidate)
    parent_rows = []
    for parent, candidates in sorted(groups.items()):
        n = len(candidates)
        positive_count = math.ceil(n * 0.20)
        budget_count = math.ceil(n * 0.20)
        local_truth = {candidate: float(truth_records[candidate]["Rdual"]) for candidate in candidates}
        local_prediction = {candidate: prediction[candidate] for candidate in candidates}
        positives = set(top_ids(local_truth, positive_count))
        selected = top_ids(local_prediction, budget_count)
        hits = sum(candidate in positives for candidate in selected)
        recall = hits / positive_count
        precision = hits / budget_count
        prevalence = positive_count / n
        parent_rows.append({"parent": parent, "rows": n, "hits": hits, "recall": recall, "enrichment_factor": precision / prevalence})
    return {
        "parent_count": len(parent_rows),
        "macro_recall_true_top20_at_pred_top20": sum(row["recall"] for row in parent_rows) / len(parent_rows),
        "macro_enrichment_true_top20_at_pred_top20": sum(row["enrichment_factor"] for row in parent_rows) / len(parent_rows),
        "parents": parent_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-manifest", type=Path, required=True)
    parser.add_argument("--expected-experiment-manifest-sha256", required=True)
    parser.add_argument("--training-tsv", type=Path, required=True)
    parser.add_argument("--expected-training-tsv-sha256", required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--expected-split-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output_dir.exists(), "output_dir_exists")
    require(sha256_file(args.experiment_manifest) == args.expected_experiment_manifest_sha256, "experiment_manifest_hash")
    require(sha256_file(args.training_tsv) == args.expected_training_tsv_sha256, "training_tsv_hash")
    require(sha256_file(args.split_manifest) == args.expected_split_manifest_sha256, "split_manifest_hash")
    manifest = json.loads(args.experiment_manifest.read_text())
    require(manifest.get("open_inner_only") is True and manifest.get("split_id") == "outer_0_inner_0", "manifest_split")
    require(all(manifest.get(field) == 0 for field in FIREWALL_FIELDS), "manifest_firewall")
    truth_records, split = load_truth(args.training_tsv, args.split_manifest)
    truth_ids = set(truth_records)
    truth = {candidate: float(row["Rdual"]) for candidate, row in truth_records.items()}
    variant_results = {}
    ranking_rows = []
    for variant in manifest["variants"]:
        name = variant["name"]
        jobs = variant["jobs"]
        require(jobs and len({int(job["seed"]) for job in jobs}) == len(jobs), f"seed_duplicate:{name}")
        seed_maps = [validate_job(Path(job["job_dir"]), name, int(job["seed"]), truth_ids) for job in jobs]
        prediction = aggregate(seed_maps)
        variant_results[name] = {
            "seed_count": len(jobs),
            "seeds": sorted(int(job["seed"]) for job in jobs),
            "score_tie_diagnostics": score_tie_diagnostics(prediction),
            "global": enrichment_block(truth, prediction),
            "within_parent": within_parent(truth_records, prediction),
        }
        for rank, candidate in enumerate(top_ids(prediction, len(prediction)), 1):
            ranking_rows.append({"variant": name, "rank": rank, "candidate_id": candidate, "predicted_Rdual": prediction[candidate], "true_Rdual": truth[candidate], "parent": truth_records[candidate]["parent"]})
    result = {
        "schema_version": SCHEMA,
        "status": "PASS_OPEN_INNER_EARLY_ENRICHMENT",
        "claim_boundary": "open-development inner-validation computational Docking-geometry enrichment only",
        "split_id": split["split_id"],
        "rows": len(truth),
        "parents": len(split["score_parents"]),
        "variant_metrics": variant_results,
        **{field: 0 for field in FIREWALL_FIELDS},
    }
    args.output_dir.mkdir(parents=True)
    atomic_json(args.output_dir / "EARLY_ENRICHMENT.json", result)
    with (args.output_dir / "OPEN_INNER_RANKINGS.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ranking_rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(ranking_rows)
    atomic_json(args.output_dir / "RESULT.json", result)
    print(json.dumps({"status": result["status"], "variants": sorted(variant_results), "rows": len(truth)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
