#!/usr/bin/env python3
"""Frozen V2.20 whole-parent OOF early-enrichment evaluator and bootstrap."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import stat
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


SCHEMA = "pvrig_v2_20_oof_evaluator_v1"
DEFAULT_BOOTSTRAP_REPLICATES = 10_000
DEFAULT_BOOTSTRAP_SEED = 20_260_723
FORBIDDEN_PATH_TOKENS = (
    "open_development", "open-development", "frozen_test", "frozen-test",
    "test32", "sealed", "quarantine",
)


class EvaluationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvaluationError(message)


def assert_train_oof_path(path: Path, label: str) -> None:
    lowered = str(path).lower()
    for token in FORBIDDEN_PATH_TOKENS:
        require(token not in lowered, f"forbidden_path:{label}:{token}:{path}")


def read_regular_snapshot(path: Path, label: str) -> bytes:
    assert_train_oof_path(path, label)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise EvaluationError(f"open_failed:{label}:{path}") from error
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_size > 0, f"invalid_regular_file:{label}:{path}")
        blocks: list[bytes] = []
        while True:
            block = os.read(descriptor, 8 * 1024 * 1024)
            if not block:
                break
            blocks.append(block)
        after = os.fstat(descriptor)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        require(identity(before) == identity(after), f"changed_during_read:{label}:{path}")
        return b"".join(blocks)
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class OOFRow:
    candidate_id: str
    parent_id: str
    true_r8: float
    true_r9: float
    true_rdual: float
    pred_r8: float
    pred_r9: float
    pred_rdual: float


def _resolve_field(fields: Sequence[str], candidates: Sequence[str], label: str) -> str:
    matches = [field for field in candidates if field in fields]
    require(len(matches) == 1, f"field_resolution_failed:{label}:{matches}")
    return matches[0]


def infer_prediction_fields(fields: Sequence[str]) -> tuple[str, str, str]:
    known = (
        ("B_TOP5_L1__R8", "B_TOP5_L1__R9", "B_TOP5_L1__Rdual_exact_min"),
        ("pred_R8", "pred_R9", "pred_Rdual"),
        ("prediction_R8", "prediction_R9", "prediction_Rdual"),
        ("prediction_R_8X6B", "prediction_R_9E6Y", "prediction_R_dual_min"),
    )
    matches = [triple for triple in known if set(triple) <= set(fields)]
    if len(matches) == 1:
        return matches[0]
    prefixes: list[tuple[str, str, str]] = []
    for field in fields:
        if not field.endswith("__R8"):
            continue
        prefix = field[:-4]
        triple = (field, prefix + "__R9", prefix + "__Rdual_exact_min")
        if set(triple) <= set(fields):
            prefixes.append(triple)
    require(len(prefixes) == 1, f"prediction_field_inference_ambiguous:{prefixes}")
    return prefixes[0]


def load_oof_tsv(path: Path, prediction_fields: tuple[str, str, str] | None = None) -> tuple[list[OOFRow], str]:
    raw = read_regular_snapshot(path, "oof_predictions")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""), delimiter="\t")
        fields = list(reader.fieldnames or ())
        table = [dict(row) for row in reader]
    except Exception as error:
        raise EvaluationError("invalid_oof_tsv") from error
    require(fields and len(fields) == len(set(fields)) and table, "invalid_oof_table")
    candidate_field = _resolve_field(fields, ("candidate_id",), "candidate")
    parent_field = _resolve_field(fields, ("parent_framework_cluster", "parent_id"), "parent")
    truth8_field = _resolve_field(fields, ("truth_R8", "true_R8", "target_R_8X6B"), "truth_r8")
    truth9_field = _resolve_field(fields, ("truth_R9", "true_R9", "target_R_9E6Y"), "truth_r9")
    truth_dual_field = _resolve_field(fields, ("truth_Rdual_exact_min", "true_Rdual", "target_R_dual_min"), "truth_rdual")
    pred8_field, pred9_field, pred_dual_field = prediction_fields or infer_prediction_fields(fields)
    require({pred8_field, pred9_field, pred_dual_field} <= set(fields), "prediction_fields_missing")

    rows: list[OOFRow] = []
    seen: set[str] = set()
    for raw_row in table:
        candidate = raw_row[candidate_field]
        require(candidate and candidate not in seen, f"candidate_duplicate:{candidate}")
        seen.add(candidate)
        try:
            values = tuple(float(raw_row[field]) for field in (
                truth8_field, truth9_field, truth_dual_field, pred8_field, pred9_field, pred_dual_field,
            ))
        except Exception as error:
            raise EvaluationError(f"numeric_parse_failed:{candidate}") from error
        require(all(math.isfinite(value) for value in values), f"nonfinite:{candidate}")
        true8, true9, true_dual, pred8, pred9, pred_dual = values
        require(abs(true_dual - min(true8, true9)) <= 1e-12, f"truth_exact_min_mismatch:{candidate}")
        require(abs(pred_dual - min(pred8, pred9)) <= 1e-12, f"prediction_exact_min_mismatch:{candidate}")
        rows.append(OOFRow(candidate, raw_row[parent_field], *values))
    require(all(row.parent_id for row in rows), "empty_parent_id")
    return rows, hashlib.sha256(raw).hexdigest()


def _rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2.0 + 1.0
        start = end
    return ranks


def spearman(target: np.ndarray, prediction: np.ndarray) -> float:
    left, right = _rankdata(np.asarray(target, dtype=np.float64)), _rankdata(np.asarray(prediction, dtype=np.float64))
    if np.std(left) == 0.0 or np.std(right) == 0.0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def ranked_indices(candidate_ids: Sequence[str], scores: np.ndarray) -> list[int]:
    require(len(candidate_ids) == len(scores), "ranking_length_mismatch")
    return sorted(range(len(scores)), key=lambda index: (-float(scores[index]), candidate_ids[index]))


def _binary_ndcg(candidate_ids: Sequence[str], relevance: np.ndarray, scores: np.ndarray, k: int) -> float:
    order = ranked_indices(candidate_ids, scores)[:k]
    discounts = np.log2(np.arange(2, k + 2, dtype=np.float64))
    dcg = float(np.sum(relevance[order] / discounts))
    positives = min(int(np.sum(relevance)), k)
    if positives == 0:
        return 0.0
    ideal = np.log2(np.arange(2, positives + 2, dtype=np.float64))
    return dcg / float(np.sum(1.0 / ideal))


def enrichment_at(
    candidate_ids: Sequence[str],
    truth: np.ndarray,
    score: np.ndarray,
    *,
    true_fraction: float = 0.10,
    budget_fraction: float = 0.05,
) -> dict[str, Any]:
    count = len(candidate_ids)
    require(count == len(truth) == len(score) and count > 0, "enrichment_length_invalid")
    positives = max(1, math.ceil(count * true_fraction))
    selected = max(1, math.ceil(count * budget_fraction))
    true_indices = set(ranked_indices(candidate_ids, truth)[:positives])
    predicted_indices = set(ranked_indices(candidate_ids, score)[:selected])
    hits = len(true_indices & predicted_indices)
    precision = hits / selected
    recall = hits / positives
    prevalence = positives / count
    relevance = np.asarray([1.0 if index in true_indices else 0.0 for index in range(count)], dtype=np.float64)
    return {
        "true_top_fraction": true_fraction,
        "predicted_budget_fraction": budget_fraction,
        "n": count,
        "positives": positives,
        "selected": selected,
        "hits": hits,
        "precision": precision,
        "recall": recall,
        "enrichment_factor": precision / prevalence,
        "binary_ndcg": _binary_ndcg(candidate_ids, relevance, score, selected),
    }


def evaluate_rows(rows: Sequence[OOFRow]) -> dict[str, Any]:
    require(bool(rows), "oof_rows_empty")
    candidate_ids = [row.candidate_id for row in rows]
    require(len(candidate_ids) == len(set(candidate_ids)), "candidate_ids_not_unique")
    truth = np.asarray([row.true_rdual for row in rows], dtype=np.float64)
    prediction = np.asarray([row.pred_rdual for row in rows], dtype=np.float64)
    budget5 = enrichment_at(candidate_ids, truth, prediction, true_fraction=0.10, budget_fraction=0.05)
    budget10 = enrichment_at(candidate_ids, truth, prediction, true_fraction=0.10, budget_fraction=0.10)
    return {
        "schema_version": SCHEMA,
        "rows": len(rows),
        "parents": len({row.parent_id for row in rows}),
        "EF_true_top10_at_budget5": budget5["enrichment_factor"],
        "hits_at_budget5": budget5["hits"],
        "selected_at_budget5": budget5["selected"],
        "positives_true_top10": budget5["positives"],
        "precision_at_budget5": budget5["precision"],
        "recall_at_budget5": budget5["recall"],
        "binary_ndcg_at_budget5": budget5["binary_ndcg"],
        "EF_true_top10_at_budget10": budget10["enrichment_factor"],
        "Rdual_Spearman": spearman(truth, prediction),
        "Rdual_MAE": float(np.mean(np.abs(prediction - truth))),
        "rounding": "max(1, ceil(n*fraction))",
        "tie_break": "candidate_id ascending after score descending",
    }


def _validate_aligned_models(models: Mapping[str, Sequence[OOFRow]]) -> tuple[list[str], list[OOFRow], dict[str, np.ndarray]]:
    require(len(models) >= 2, "paired_bootstrap_requires_two_models")
    names = list(models)
    reference = list(models[names[0]])
    require(reference, "paired_reference_empty")
    reference_by_id = {row.candidate_id: row for row in reference}
    require(len(reference_by_id) == len(reference), "paired_reference_duplicate_candidate")
    predictions: dict[str, np.ndarray] = {}
    for name, supplied in models.items():
        by_id = {row.candidate_id: row for row in supplied}
        require(len(by_id) == len(supplied) and set(by_id) == set(reference_by_id), f"paired_candidate_closure:{name}")
        ordered: list[float] = []
        for row in reference:
            candidate = by_id[row.candidate_id]
            require(
                (candidate.parent_id, candidate.true_r8, candidate.true_r9, candidate.true_rdual)
                == (row.parent_id, row.true_r8, row.true_r9, row.true_rdual),
                f"paired_truth_or_parent_mismatch:{name}:{row.candidate_id}",
            )
            ordered.append(candidate.pred_rdual)
        predictions[name] = np.asarray(ordered, dtype=np.float64)
    return names, reference, predictions


def _top_k_mask(scores: np.ndarray, candidate_rank: np.ndarray, draw_ordinal: np.ndarray, k: int) -> np.ndarray:
    """Exact top-k under (-score, candidate_id, duplicated-parent draw ordinal)."""

    count = len(scores)
    require(0 < k <= count, "top_k_invalid")
    threshold = float(np.partition(scores, count - k)[count - k])
    mask = scores > threshold
    remaining = k - int(np.sum(mask))
    boundary = np.flatnonzero(scores == threshold)
    require(0 <= remaining <= len(boundary), "top_k_boundary_invalid")
    if remaining:
        order = np.lexsort((draw_ordinal[boundary], candidate_rank[boundary]))
        mask[boundary[order[:remaining]]] = True
    require(int(np.sum(mask)) == k, "top_k_count_mismatch")
    return mask


def paired_parent_bootstrap(
    models: Mapping[str, Sequence[OOFRow]],
    *,
    paired_deltas: Sequence[tuple[str, str]],
    replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
    expected_parents: int | None = None,
) -> dict[str, Any]:
    require(replicates > 0, "bootstrap_replicates_invalid")
    names, reference, predictions = _validate_aligned_models(models)
    for left, right in paired_deltas:
        require(left in models and right in models and left != right, f"paired_delta_invalid:{left}:{right}")

    parent_groups: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(reference):
        parent_groups[row.parent_id].append(index)
    parents = sorted(parent_groups)
    require(expected_parents is None or len(parents) == expected_parents, "bootstrap_parent_count_mismatch")
    groups = [np.asarray(parent_groups[parent], dtype=np.int64) for parent in parents]
    candidate_order = sorted(range(len(reference)), key=lambda index: reference[index].candidate_id)
    base_candidate_rank = np.empty(len(reference), dtype=np.int64)
    base_candidate_rank[candidate_order] = np.arange(len(reference), dtype=np.int64)
    truth = np.asarray([row.true_rdual for row in reference], dtype=np.float64)
    rng = np.random.default_rng(seed)
    distributions = {name: np.empty(replicates, dtype=np.float64) for name in names}

    for replicate in range(replicates):
        draws = rng.integers(0, len(parents), size=len(parents), endpoint=False)
        multiplicities = Counter(int(item) for item in draws)
        row_parts: list[np.ndarray] = []
        ordinal_parts: list[np.ndarray] = []
        for draw_ordinal, parent_index in enumerate(draws):
            group = groups[int(parent_index)]
            row_parts.append(group)
            ordinal = draw_ordinal if multiplicities[int(parent_index)] > 1 else -1
            ordinal_parts.append(np.full(len(group), ordinal, dtype=np.int64))
        row_indices = np.concatenate(row_parts)
        draw_ordinals = np.concatenate(ordinal_parts)
        ranks = base_candidate_rank[row_indices]
        replicate_truth = truth[row_indices]
        count = len(row_indices)
        positives = max(1, math.ceil(count * 0.10))
        selected = max(1, math.ceil(count * 0.05))
        true_mask = _top_k_mask(replicate_truth, ranks, draw_ordinals, positives)
        prevalence = positives / count
        for name in names:
            predicted_mask = _top_k_mask(predictions[name][row_indices], ranks, draw_ordinals, selected)
            hits = int(np.sum(true_mask & predicted_mask))
            distributions[name][replicate] = (hits / selected) / prevalence

    point = {name: evaluate_rows(models[name]) for name in names}
    model_summary: dict[str, Any] = {}
    for name in names:
        values = distributions[name]
        lower, upper = np.percentile(values, [2.5, 97.5], method="linear")
        model_summary[name] = {
            "point_EF_true_top10_at_budget5": point[name]["EF_true_top10_at_budget5"],
            "bootstrap_mean": float(np.mean(values)),
            "bootstrap_percentile_95_ci": [float(lower), float(upper)],
            "distribution_sha256": hashlib.sha256(values.astype("<f8", copy=False).tobytes()).hexdigest(),
        }

    delta_summary: dict[str, Any] = {}
    for left, right in paired_deltas:
        values = distributions[left] - distributions[right]
        lower, upper = np.percentile(values, [2.5, 97.5], method="linear")
        key = f"{left}_minus_{right}"
        delta_summary[key] = {
            "point_delta": point[left]["EF_true_top10_at_budget5"] - point[right]["EF_true_top10_at_budget5"],
            "bootstrap_mean_delta": float(np.mean(values)),
            "paired_percentile_95_ci": [float(lower), float(upper)],
            "distribution_sha256": hashlib.sha256(values.astype("<f8", copy=False).tobytes()).hexdigest(),
        }

    return {
        "schema_version": SCHEMA,
        "status": "PASS_WHOLE_PARENT_PAIRED_BOOTSTRAP",
        "replicates": replicates,
        "seed": seed,
        "parents": len(parents),
        "sampling_unit": "whole parent cluster with replacement",
        "duplicate_tie_break": "(candidate_id, parent draw ordinal); ordinal participates only when its parent is duplicated",
        "metric_recomputation": "replicate-local true top10 and budget5 with ceil rounding",
        "percentile_method": "numpy linear 2.5/97.5",
        "models": model_summary,
        "paired_deltas": delta_summary,
        "input_access": {"open_development_rows": 0, "frozen_test_rows": 0},
    }


def _parse_named_path(value: str) -> tuple[str, Path]:
    try:
        name, path = value.split("=", 1)
    except ValueError as error:
        raise argparse.ArgumentTypeError("input must be NAME=PATH") from error
    if not name or not path:
        raise argparse.ArgumentTypeError("input must be NAME=PATH")
    return name, Path(path)


def _parse_delta(value: str) -> tuple[str, str]:
    try:
        left, right = value.split("-", 1)
    except ValueError as error:
        raise argparse.ArgumentTypeError("delta must be LEFT-RIGHT") from error
    if not left or not right:
        raise argparse.ArgumentTypeError("delta must be LEFT-RIGHT")
    return left, right


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", type=_parse_named_path, required=True, help="NAME=PATH; repeat for paired bootstrap")
    parser.add_argument("--delta", action="append", type=_parse_delta, default=[])
    parser.add_argument("--bootstrap-replicates", type=int, default=DEFAULT_BOOTSTRAP_REPLICATES)
    parser.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    parser.add_argument("--expected-parents", type=int)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args(argv)
    named_paths = dict(args.input)
    require(len(named_paths) == len(args.input), "duplicate_input_name")
    loaded: dict[str, list[OOFRow]] = {}
    input_hashes: dict[str, str] = {}
    for name, path in named_paths.items():
        rows, digest = load_oof_tsv(path)
        loaded[name] = rows
        input_hashes[name] = digest
    payload: dict[str, Any] = {
        "schema_version": SCHEMA,
        "status": "PASS_FROZEN_V220_OOF_EVALUATION",
        "metrics": {name: evaluate_rows(rows) for name, rows in loaded.items()},
        "input_hashes": input_hashes,
        "input_access": {"open_development_rows": 0, "frozen_test_rows": 0},
    }
    if len(loaded) >= 2:
        deltas = args.delta
        if not deltas and {"C1", "C0", "B0"} <= set(loaded):
            deltas = [("C1", "C0"), ("C1", "B0")]
        require(bool(deltas), "paired_delta_required_for_multiple_inputs")
        payload["bootstrap"] = paired_parent_bootstrap(
            loaded,
            paired_deltas=deltas,
            replicates=args.bootstrap_replicates,
            seed=args.bootstrap_seed,
            expected_parents=args.expected_parents,
        )
    rendered = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output_json is not None:
        assert_train_oof_path(args.output_json, "output_json")
        with args.output_json.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
