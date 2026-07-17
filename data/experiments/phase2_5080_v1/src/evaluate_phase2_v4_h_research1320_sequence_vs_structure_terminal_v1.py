#!/usr/bin/env python3
"""Evaluate frozen V4-H sequence/structure surrogates after terminal unseal."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

import numpy as np


SCHEMA_VERSION = "phase2_v4_h_research1320_sequence_vs_structure_terminal_evaluation_v1"
STATUS = "COMPLETE_RESEARCH_ONLY_TERMINAL_V4_H_SEQUENCE_VS_STRUCTURE_EVALUATION"
EXPECTED_SEQUENCE_SHA256 = "a87d37d9edf130b2eb82e301746d52abee4a56fd7babf5bde4b5b0eefcc92fbc"
EXPECTED_STRUCTURE_SHA256 = "f864c675db2c9ec449e52a7debacdd283ff5d404f40b6abfbd9cb0ef3e6b9d5a"
EXPECTED_BALANCED_SHA256 = "a700adc22920d28c9dcddfabb5512dd125a047c771a0c47cb2e8315f830ab842"
EXPECTED_PREREG_SHA256 = "2bfd76ef451a8576077fe92ba5ef6fc82d053eeb46d79c35080ab762e3b080c8"
EXPECTED_ROWS = 1320
BOOTSTRAP_REPLICATES = 5000
BOOTSTRAP_SEED = 20260717
ANALYZABLE = "ANALYZABLE"
TECHNICAL_INCOMPLETE = "TECHNICAL_INCOMPLETE"
CLAIM_BOUNDARY = (
    "Research-only evaluation against terminal computational docking geometry "
    "R_dual_min; not Docking Gold, binding probability, affinity, competition, "
    "experimental blocking, formal prospective validation, or final submission authority."
)


class EvaluationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvaluationError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: Sequence[str] | None = None) -> None:
    require(bool(rows) or bool(fields), f"empty_table_without_schema:{path.name}")
    fieldnames = list(fields or rows[0].keys())
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(path, buffer.getvalue().encode("utf-8"))


def average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    return ranks


def spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    left, right = average_ranks(y_true), average_ranks(y_pred)
    if float(np.std(left)) < 1e-12 or float(np.std(right)) < 1e-12:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def ndcg(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    def dcg(order: np.ndarray) -> float:
        return float(sum((2.0 ** float(y_true[index]) - 1.0) / math.log2(rank + 2.0) for rank, index in enumerate(order)))
    predicted = np.argsort(-y_pred, kind="mergesort")
    ideal = np.argsort(-y_true, kind="mergesort")
    denominator = dcg(ideal)
    return dcg(predicted) / denominator if denominator > 0 else 0.0


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    require(len(y_true) == len(y_pred) and len(y_true) >= 4, "metric_rows_invalid")
    require(np.isfinite(y_true).all() and np.isfinite(y_pred).all(), "metric_nonfinite")
    pearson = 0.0 if float(np.std(y_true)) < 1e-12 or float(np.std(y_pred)) < 1e-12 else float(np.corrcoef(y_true, y_pred)[0, 1])
    budget = max(1, math.ceil(0.20 * len(y_true)))
    truth = set(np.argsort(-y_true, kind="mergesort")[:budget].tolist())
    predicted = set(np.argsort(-y_pred, kind="mergesort")[:budget].tolist())
    return {
        "spearman": spearman(y_true, y_pred),
        "pearson": pearson,
        "mae": float(np.mean(np.abs(y_true - y_pred))),
        "ndcg": ndcg(y_true, y_pred),
        "top20_percent_recall": len(truth & predicted) / len(truth),
    }


def parent_center(values: np.ndarray, groups: Sequence[str]) -> np.ndarray:
    output = values.copy()
    by_group: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        by_group[str(group)].append(index)
    for indices in by_group.values():
        output[indices] -= float(np.mean(values[indices]))
    return output


def group_bootstrap_delta(
    y_true: np.ndarray,
    sequence_pred: np.ndarray,
    structure_pred: np.ndarray,
    groups: Sequence[str],
    replicates: int,
    seed: int,
) -> dict[str, float]:
    by_group: dict[str, np.ndarray] = {}
    for group in sorted(set(groups)):
        by_group[group] = np.asarray([index for index, value in enumerate(groups) if value == group], dtype=np.int64)
    names = sorted(by_group)
    require(len(names) >= 2, "bootstrap_groups_too_few")
    rng = np.random.default_rng(seed)
    deltas = np.empty(replicates, dtype=np.float64)
    for replicate in range(replicates):
        sampled = rng.choice(names, size=len(names), replace=True)
        indices = np.concatenate([by_group[str(group)] for group in sampled])
        deltas[replicate] = spearman(y_true[indices], structure_pred[indices]) - spearman(y_true[indices], sequence_pred[indices])
    return {
        "replicates": replicates,
        "seed": seed,
        "median_delta_spearman_M2_minus_M1": float(np.median(deltas)),
        "ci95_low": float(np.quantile(deltas, 0.025)),
        "ci95_high": float(np.quantile(deltas, 0.975)),
        "fraction_delta_gt_0": float(np.mean(deltas > 0)),
    }


def evaluate(
    teacher_path: Path,
    terminal_receipt_path: Path,
    sequence_path: Path,
    structure_path: Path,
    balanced_path: Path,
    preregistration_path: Path,
    output_dir: Path,
    *,
    expected_teacher_sha256: str,
    expected_terminal_receipt_sha256: str,
    expected_sequence_sha256: str = EXPECTED_SEQUENCE_SHA256,
    expected_structure_sha256: str = EXPECTED_STRUCTURE_SHA256,
    expected_balanced_sha256: str = EXPECTED_BALANCED_SHA256,
    expected_prereg_sha256: str = EXPECTED_PREREG_SHA256,
    expected_rows: int = EXPECTED_ROWS,
    bootstrap_replicates: int = BOOTSTRAP_REPLICATES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_exists:{output_dir}")
    pinned = (
        (teacher_path, expected_teacher_sha256, "teacher_hash_mismatch"),
        (terminal_receipt_path, expected_terminal_receipt_sha256, "terminal_receipt_hash_mismatch"),
        (sequence_path, expected_sequence_sha256, "sequence_ranking_hash_mismatch"),
        (structure_path, expected_structure_sha256, "structure_ranking_hash_mismatch"),
        (balanced_path, expected_balanced_sha256, "balanced_panel_hash_mismatch"),
        (preregistration_path, expected_prereg_sha256, "preregistration_hash_mismatch"),
    )
    for path, expected, error in pinned:
        require(sha256_file(path) == expected, error)
    receipt = json.loads(terminal_receipt_path.read_text())
    require(receipt.get("status") == "COMPLETE_V4_H_TERMINAL_IMMUTABLE_TEACHER", "terminal_receipt_status_invalid")
    require(receipt.get("campaign_terminal") is True, "campaign_not_terminal")
    require(receipt.get("teacher_sha256") == expected_teacher_sha256, "terminal_receipt_teacher_hash_mismatch")
    require(receipt.get("expected_candidate_rows") == expected_rows, "terminal_receipt_candidate_count_invalid")
    require(sorted(receipt.get("required_receptors") or []) == ["8X6B", "9E6Y"], "terminal_receipt_receptors_invalid")
    require(receipt.get("partial_teacher_consumption_forbidden") is True, "partial_teacher_gate_missing")

    teacher_fields, teacher_rows = load_tsv(teacher_path)
    required_teacher = {"candidate_id", "teacher_state", "technical_incomplete_reason", "R_dual_min"}
    require(required_teacher <= set(teacher_fields), "teacher_fields_missing")
    require(len(teacher_rows) == expected_rows, "teacher_row_count_invalid")
    require(len({row["candidate_id"] for row in teacher_rows}) == expected_rows, "teacher_candidate_ids_not_unique")
    teacher_by_id = {row["candidate_id"]: row for row in teacher_rows}

    _sequence_fields, sequence_rows = load_tsv(sequence_path)
    _structure_fields, structure_rows = load_tsv(structure_path)
    _balanced_fields, balanced_rows = load_tsv(balanced_path)
    require(len(sequence_rows) == len(structure_rows) == expected_rows, "prediction_row_count_invalid")
    sequence_by_id = {row["candidate_id"]: row for row in sequence_rows}
    structure_by_id = {row["candidate_id"]: row for row in structure_rows}
    require(len(sequence_by_id) == len(structure_by_id) == expected_rows, "prediction_candidate_ids_not_unique")
    require(set(teacher_by_id) == set(sequence_by_id) == set(structure_by_id), "teacher_prediction_candidate_set_mismatch")
    balanced_by_id = {row["candidate_id"]: row for row in balanced_rows}
    require(len(balanced_by_id) == len(balanced_rows), "balanced_candidate_ids_not_unique")
    require(set(balanced_by_id) <= set(teacher_by_id), "balanced_candidate_not_in_teacher")

    analyzable: list[dict[str, Any]] = []
    incomplete_rows: list[dict[str, Any]] = []
    for candidate_id in sorted(teacher_by_id):
        teacher = teacher_by_id[candidate_id]
        sequence = sequence_by_id[candidate_id]
        structure = structure_by_id[candidate_id]
        for field in ("sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode"):
            require(sequence[field] == structure[field], f"prediction_metadata_mismatch:{candidate_id}:{field}")
        state = teacher["teacher_state"]
        if state == ANALYZABLE:
            require(not teacher["technical_incomplete_reason"].strip(), f"analyzable_has_incomplete_reason:{candidate_id}")
            require(teacher["R_dual_min"].strip(), f"analyzable_target_missing:{candidate_id}")
            target = float(teacher["R_dual_min"])
            require(np.isfinite(target), f"analyzable_target_nonfinite:{candidate_id}")
            analyzable.append({
                "candidate_id": candidate_id,
                "parent_framework_cluster": sequence["parent_framework_cluster"],
                "target_patch_id": sequence["target_patch_id"],
                "design_mode": sequence["design_mode"],
                "target": target,
                "sequence_prediction": float(sequence["predicted_R_dual_min_sequence_only"]),
                "structure_prediction": float(structure["predicted_R_dual_min_structure_only"]),
            })
        elif state == TECHNICAL_INCOMPLETE:
            require(bool(teacher["technical_incomplete_reason"].strip()), f"incomplete_reason_missing:{candidate_id}")
            require(not teacher["R_dual_min"].strip(), f"incomplete_target_must_be_empty:{candidate_id}")
            incomplete_rows.append({
                "schema_version": SCHEMA_VERSION,
                "candidate_id": candidate_id,
                "technical_incomplete_reason": teacher["technical_incomplete_reason"],
                "claim_boundary": CLAIM_BOUNDARY,
            })
        else:
            raise EvaluationError(f"teacher_state_invalid:{candidate_id}:{state}")
    require(len(analyzable) >= 4, "analyzable_rows_too_few")
    require(len(analyzable) + len(incomplete_rows) == expected_rows, "teacher_state_partition_invalid")

    y = np.asarray([row["target"] for row in analyzable], dtype=np.float64)
    m1 = np.asarray([row["sequence_prediction"] for row in analyzable], dtype=np.float64)
    m2 = np.asarray([row["structure_prediction"] for row in analyzable], dtype=np.float64)
    groups = [row["parent_framework_cluster"] for row in analyzable]
    global_metrics = {"M1_SEQUENCE_ONLY": metrics(y, m1), "M2_STRUCTURE_ONLY": metrics(y, m2)}
    bootstrap = group_bootstrap_delta(y, m1, m2, groups, bootstrap_replicates, bootstrap_seed)

    parent_rows: list[dict[str, Any]] = []
    for parent in sorted(set(groups)):
        indices = np.asarray([index for index, group in enumerate(groups) if group == parent], dtype=np.int64)
        if len(indices) < 4:
            continue
        parent_rows.append({
            "schema_version": SCHEMA_VERSION,
            "parent_framework_cluster": parent,
            "analyzable_rows": len(indices),
            "M1_sequence_spearman": f"{spearman(y[indices], m1[indices]):.12g}",
            "M2_structure_spearman": f"{spearman(y[indices], m2[indices]):.12g}",
            "delta_M2_minus_M1": f"{spearman(y[indices], m2[indices]) - spearman(y[indices], m1[indices]):.12g}",
            "claim_boundary": CLAIM_BOUNDARY,
        })
    require(bool(parent_rows), "no_parent_with_sufficient_rows")
    m1_parent = np.asarray([float(row["M1_sequence_spearman"]) for row in parent_rows])
    m2_parent = np.asarray([float(row["M2_structure_spearman"]) for row in parent_rows])
    parent_summary = {
        "parents_with_sufficient_rows": len(parent_rows),
        "M1_macro_mean_spearman": float(np.mean(m1_parent)),
        "M1_macro_median_spearman": float(np.median(m1_parent)),
        "M2_macro_mean_spearman": float(np.mean(m2_parent)),
        "M2_macro_median_spearman": float(np.median(m2_parent)),
    }
    centered_y = parent_center(y, groups)
    parent_centered = {
        "M1_SEQUENCE_ONLY_spearman": spearman(centered_y, parent_center(m1, groups)),
        "M2_STRUCTURE_ONLY_spearman": spearman(centered_y, parent_center(m2, groups)),
    }

    stratified: dict[str, Any] = {}
    for field in ("target_patch_id", "design_mode"):
        values = sorted({row[field] for row in analyzable})
        stratified[field] = {}
        for value in values:
            indices = np.asarray([index for index, row in enumerate(analyzable) if row[field] == value], dtype=np.int64)
            if len(indices) >= 4:
                stratified[field][value] = {
                    "rows": len(indices),
                    "M1_sequence_spearman": spearman(y[indices], m1[indices]),
                    "M2_structure_spearman": spearman(y[indices], m2[indices]),
                }

    def target_distribution(indices: np.ndarray) -> dict[str, float | int]:
        values = y[indices]
        return {
            "rows": len(indices), "mean": float(np.mean(values)), "median": float(np.median(values)),
            "q10": float(np.quantile(values, 0.10)), "q90": float(np.quantile(values, 0.90)),
        }
    c0283_indices = np.asarray([index for index, group in enumerate(groups) if group == "C0283"], dtype=np.int64)
    other_indices = np.asarray([index for index, group in enumerate(groups) if group != "C0283"], dtype=np.int64)
    c0283 = {
        "C0283": target_distribution(c0283_indices) if len(c0283_indices) else None,
        "other_parents": target_distribution(other_indices) if len(other_indices) else None,
    }

    balanced_analysis: dict[str, Any] = {"candidate_rows": len(balanced_rows), "by_role": {}}
    for role in sorted({row["portfolio_role"] for row in balanced_rows}):
        candidate_ids = {row["candidate_id"] for row in balanced_rows if row["portfolio_role"] == role}
        indices = np.asarray([index for index, row in enumerate(analyzable) if row["candidate_id"] in candidate_ids], dtype=np.int64)
        balanced_analysis["by_role"][role] = {
            "planned_rows": len(candidate_ids),
            "analyzable_rows": len(indices),
            "technical_incomplete_rows": len(candidate_ids) - len(indices),
            "M1_SEQUENCE_ONLY": metrics(y[indices], m1[indices]) if len(indices) >= 4 else None,
            "M2_STRUCTURE_ONLY": metrics(y[indices], m2[indices]) if len(indices) >= 4 else None,
        }

    output_dir.mkdir(parents=True)
    parent_path = output_dir / "v4h_research1320_terminal_per_parent_v1.tsv"
    incomplete_path = output_dir / "v4h_research1320_terminal_technical_incomplete_v1.tsv"
    write_tsv(parent_path, parent_rows)
    write_tsv(
        incomplete_path,
        incomplete_rows,
        fields=("schema_version", "candidate_id", "technical_incomplete_reason", "claim_boundary"),
    )
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "input_hashes": {
            "teacher": expected_teacher_sha256,
            "terminal_receipt": expected_terminal_receipt_sha256,
            "sequence_ranking": expected_sequence_sha256,
            "structure_ranking": expected_structure_sha256,
            "balanced132": expected_balanced_sha256,
            "preregistration": expected_prereg_sha256,
        },
        "candidate_rows": expected_rows,
        "analyzable_rows": len(analyzable),
        "technical_incomplete_rows": len(incomplete_rows),
        "technical_incomplete_reasons": dict(sorted(Counter(row["technical_incomplete_reason"] for row in incomplete_rows).items())),
        "global_metrics": global_metrics,
        "paired_parent_group_bootstrap": bootstrap,
        "per_parent_summary": parent_summary,
        "parent_centered": parent_centered,
        "stratified": stratified,
        "C0283_target_distribution": c0283,
        "balanced132": balanced_analysis,
        "interpretation_authority": "RESEARCH_ONLY_NO_FORMAL_PASS",
        "outputs": {
            "per_parent": {"path": parent_path.name, "sha256": sha256_file(parent_path)},
            "technical_incomplete": {"path": incomplete_path.name, "sha256": sha256_file(incomplete_path)},
        },
    }
    audit_path = output_dir / "v4h_research1320_sequence_vs_structure_terminal_evaluation_v1.audit.json"
    atomic_write(audit_path, (json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"))
    receipt_payload = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "audit_sha256": sha256_file(audit_path),
        "teacher_sha256": expected_teacher_sha256,
        "analyzable_rows": len(analyzable),
        "technical_incomplete_rows": len(incomplete_rows),
        "formal_pass_claimed": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    receipt_path = output_dir / "v4h_research1320_sequence_vs_structure_terminal_evaluation_v1.receipt.json"
    atomic_write(receipt_path, (json.dumps(receipt_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": STATUS,
        "analyzable_rows": len(analyzable),
        "technical_incomplete_rows": len(incomplete_rows),
        "global_metrics": global_metrics,
        "parent_centered": parent_centered,
        "bootstrap": bootstrap,
        "receipt_sha256": sha256_file(receipt_path),
        "formal_pass_claimed": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--terminal-receipt", type=Path, required=True)
    parser.add_argument("--sequence-ranking", type=Path, required=True)
    parser.add_argument("--structure-ranking", type=Path, required=True)
    parser.add_argument("--balanced132", type=Path, required=True)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--expected-teacher-sha256", required=True)
    parser.add_argument("--expected-terminal-receipt-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = evaluate(
        args.teacher, args.terminal_receipt, args.sequence_ranking, args.structure_ranking,
        args.balanced132, args.preregistration, args.output_dir,
        expected_teacher_sha256=args.expected_teacher_sha256,
        expected_terminal_receipt_sha256=args.expected_terminal_receipt_sha256,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
