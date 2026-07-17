#!/usr/bin/env python3
"""One-shot V4-F96 formal evaluator for computational dual-Docking geometry.

The evaluator validates the frozen, label-free prediction receipt before it
opens any Full-QC eligibility or Docking-label receipt.  It evaluates only the
predeclared contact-family score against continuous R_dual_min.  This is not a
binding, affinity, competition, Docking Gold, or experimental blocking test.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
EXP_DIR = SCRIPT_DIR.parent
PREREG_PATH = EXP_DIR / "audits/phase2_v4_f96_formal_evaluator_v2_preregistration.json"
EXPECTED_PREREG_SHA256 = "05d5727c7568ac9563c75d7ec7b916f172eefd915a728b829d29c25a12079fc3"
EXPECTED_MANIFEST_SHA256 = "3f3c504844756703acecf586b2b218f2e2855c3a108ee22656c8f08e7f57e334"
EXPECTED_MANIFEST_AUDIT_SHA256 = "fc24cc2bd203100e29be897e87850a67ddc362b1fa1635d4172ec4335f5083a1"
EXPECTED_MANIFEST_RECEIPT_SHA256 = "3adc1e3194bdc5846f35b99020c3c996859caf3e3abc2b8e02df6ac75296512f"
EXPECTED_ROW_COUNT = 96
MODEL_SPLIT = "PROSPECTIVE_V4_F_COMPUTATIONAL_HOLDOUT"
EXPECTED_PARENT_CLUSTERS = ("C0198", "C0379", "C0401", "C0515")
EXPECTED_SEEDS = (917, 1931, 3253)

PREDICTION_SCHEMA_VERSION = "phase2_v4_f_frozen_surrogate_predictions_v1"
PREDICTION_STATUS = "PASS_V4_F_96_UNLABELED_PREDICTIONS_FROZEN"
PREDICTION_FIELDS = (
    "candidate_id", "sequence_sha256", "model_split", "parent_id",
    "parent_framework_cluster", "design_method", "design_mode", "target_patch_id",
    "cdr3_length", "base_selected_model", "base_predicted_geometry_score",
    "base_prediction_uncertainty", "embedding_selected_model",
    "embedding_predicted_geometry_score", "embedding_prediction_uncertainty",
    "contact_selected_model", "contact_predicted_geometry_score",
    "contact_prediction_uncertainty",
)
IDENTITY_FIELDS = PREDICTION_FIELDS[:9]
PRIMARY_POLICY = {
    "schema_version": "phase2_v4_f_primary_evaluation_policy_v1",
    "primary_model_family": "contact",
    "primary_prediction_column": "contact_predicted_geometry_score",
    "primary_uncertainty_column": "contact_prediction_uncertainty",
    "primary_model_selection": (
        "use the contact-stage selected_candidate_model frozen on OPEN_DEVELOPMENT; "
        "no post-Docking family switching or ensemble reweighting"
    ),
    "primary_endpoint": "continuous independent-dual-receptor R_dual_min",
    "endpoint_direction": "higher_is_better",
    "primary_metric": "spearman",
    "secondary_metrics": ["ndcg", "top_quartile_recall_at_20pct_budget", "mae"],
    "resampling_unit": "parent_framework_cluster",
    "confidence_interval": "two-sided parent-cluster bootstrap 95 percent CI",
    "multiplicity_policy": (
        "single preregistered contact-family primary test; base and embedding families "
        "are descriptive secondary analyses only"
    ),
    "tie_break": "candidate_id ascending after exact score and uncertainty ties",
    "full_qc_attrition": (
        "report all Full-QC failures; evaluate the primary endpoint only for the frozen "
        "policy-defined Docking set without replacement or score-based substitution"
    ),
    "forbidden_after_unseal": [
        "switch primary model family", "change endpoint or direction",
        "change metric hierarchy", "tune weights or thresholds on V4-F Docking labels",
    ],
}
ELIGIBILITY_SCHEMA_VERSION = "phase2_v4_f96_full_qc_eligibility_receipt_v1"
ELIGIBILITY_STATUS = "PASS_V4_F96_FULL_QC_ELIGIBILITY_FROZEN_NO_REPLACEMENT"
ELIGIBILITY_FIELDS = (
    "candidate_id", "sequence_sha256", "parent_framework_cluster", "model_split",
    "full_qc_hard_pass", "full_qc_status", "replacement_used",
)
LABEL_SCHEMA_VERSION = "phase2_v4_f96_dual_docking_label_receipt_v1"
LABEL_STATUS = "PASS_V4_F96_DUAL_DOCKING_LABEL_RELEASE"
LABEL_FIELDS = (
    "candidate_id", "sequence_sha256", "parent_framework_cluster", "model_split",
    "docking_status", "R_dual_min", "successful_seed_count_8X6B",
    "successful_seed_ids_8X6B", "successful_seed_count_9E6Y",
    "successful_seed_ids_9E6Y", "independent_receptor_docking",
    "technical_failure_reason",
)
ANALYZABLE_STATUS = "PASS_COMPLETE_DUAL_DOCKING"
TECHNICAL_FAILURE_STATUS = "TECHNICAL_FAILURE"
PREDECLARED_SHORTCUTS = {
    "constant", "parent_only", "metadata_shortcut", "cdr3_only",
    "handcrafted_full_sequence", "generic_prior_only", "cdr_length_only",
}
CLAIM_BOUNDARY = (
    "V4-F96 one-shot evaluation of fixed-PVRIG computational independent-dual-receptor "
    "Docking geometry only; not binding, affinity, competition, Docking Gold, "
    "experimental blocking, or final submission authority."
)
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20_260_717
MIN_HARD_PASS = 64
MIN_ANALYZABLE = 64
MIN_ANALYZABLE_FRACTION = 0.80
MIN_PER_PARENT = 8
MIN_BOOTSTRAP_VALID_FRACTION = 0.80
THRESHOLDS = {
    "overall_contact_spearman_minimum": 0.30,
    "parent_cluster_bootstrap_ci95_lower_strictly_greater_than": 0.0,
    "parent_macro_spearman_minimum": 0.20,
    "minimum_nonnegative_parent_spearman_count": 3,
    "top_quartile_recall_at_20pct_budget_minimum": 0.50,
    "selective_risk_mae_reduction_minimum": 0.10,
    "high_vs_low_uncertainty_quartile_mae_ratio_minimum": 1.25,
    "ef_at_top10_minimum": 3.0,
    "ef_at_top10_parent_bootstrap_ci95_lower_strictly_greater_than_random_baseline": 1.0,
    "overall_spearman_delta_over_strongest_shortcut_minimum": 0.05,
    "minimum_nonnegative_parent_delta_count": 3,
}
OUTPUT_FILES = (
    "v4_f96_formal_evaluation_summary.json",
    "v4_f96_formal_per_parent_metrics.tsv",
    "v4_f96_formal_evaluation.receipt.json",
)
CANONICAL_MANIFEST = EXP_DIR / "data_splits/pvrig_v4_f/prospective_holdout96_manifest.tsv"
CANONICAL_MANIFEST_AUDIT = EXP_DIR / "data_splits/pvrig_v4_f/prospective_holdout96_audit.json"
CANONICAL_MANIFEST_RECEIPT = EXP_DIR / "data_splits/pvrig_v4_f/prospective_holdout96_receipt.json"
CANONICAL_PREDICTION_RECEIPT = EXP_DIR / "predictions/pvrig_v4_f_surrogate_predictions_v1/v4_f_96_frozen_surrogate_predictions.receipt.json"
CANONICAL_FORMAL_INPUT_ROOT = EXP_DIR / "prepared/pvrig_v4_f96_formal_evaluation_v1"
CANONICAL_ELIGIBILITY_RECEIPT = CANONICAL_FORMAL_INPUT_ROOT / "full_qc_eligibility.receipt.json"
CANONICAL_LABEL_RECEIPT = CANONICAL_FORMAL_INPUT_ROOT / "dual_docking_labels.receipt.json"
CANONICAL_OUTPUT_DIR = EXP_DIR / "runs/pvrig_v4_f96_formal_evaluation_v1"
CANONICAL_ONE_SHOT_LOCK = EXP_DIR / "runs/.pvrig_v4_f96_formal_evaluation_v1.one_shot.lock"
CANONICAL_IMPLEMENTATION_FREEZE = EXP_DIR / "audits/phase2_v4_f96_formal_evaluator_v1_implementation_freeze.json"
CANONICAL_IMPLEMENTATION_FREEZE_RECEIPT = EXP_DIR / "audits/phase2_v4_f96_formal_evaluator_v1_implementation_freeze.receipt.json"
CANONICAL_TRUST_ANCHOR = EXP_DIR / "audits/phase2_v4_f96_formal_evaluator_v1_runtime_trust_anchor.json"
TRUST_ANCHOR_ENV = "V4F96_FORMAL_TRUST_ANCHOR_SHA256"


class FormalEvaluationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Snapshot:
    path: Path
    payload: bytes
    sha256: str


@dataclass(frozen=True)
class EvaluationInputs:
    manifest: Path
    manifest_audit: Path
    manifest_receipt: Path
    prediction_receipt: Path
    eligibility_receipt: Path
    label_receipt: Path
    output_dir: Path
    trust_anchor: Path | None = None
    test_only: bool = False
    bootstrap_replicates: int = BOOTSTRAP_REPLICATES


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FormalEvaluationError(message)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def snapshot(path: Path, label: str) -> Snapshot:
    require(not path.is_symlink(), f"{label}_symlink_forbidden")
    resolved = path.resolve()
    require(resolved.is_file(), f"{label}_missing_or_not_regular")
    payload = resolved.read_bytes()
    return Snapshot(resolved, payload, sha256_bytes(payload))


def parse_json(source: Snapshot, label: str) -> dict[str, Any]:
    try:
        value = json.loads(source.payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise FormalEvaluationError(f"{label}_invalid_json") from exc
    require(isinstance(value, dict), f"{label}_not_object")
    return value


def parse_tsv(source: Snapshot, label: str) -> tuple[list[dict[str, str]], tuple[str, ...]]:
    try:
        text = source.payload.decode("utf-8-sig")
        reader = csv.DictReader(text.splitlines(), delimiter="\t")
        fields = tuple(reader.fieldnames or ())
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise FormalEvaluationError(f"{label}_invalid_tsv") from exc
    require(bool(fields), f"{label}_missing_header")
    require(
        all(None not in row and all(value is not None for value in row.values()) for row in rows),
        f"{label}_ragged_or_extra_cells",
    )
    return rows, fields


def parse_bool(value: str, field: str) -> bool:
    lowered = str(value).strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise FormalEvaluationError(f"invalid_boolean:{field}:{value!r}")


def finite_float(value: Any, field: str) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError) as exc:
        raise FormalEvaluationError(f"invalid_float:{field}") from exc
    require(math.isfinite(output), f"nonfinite_float:{field}")
    return output


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(
            payload, indent=2, sort_keys=True, ensure_ascii=False,
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
    )


def write_tsv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def rank_average(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    require(values.ndim == 1 and np.isfinite(values).all(), "rank_input_invalid")
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    index = 0
    while index < len(values):
        end = index + 1
        while end < len(values) and values[order[end]] == values[order[index]]:
            end += 1
        ranks[order[index:end]] = (index + end - 1) / 2.0 + 1.0
        index = end
    return ranks


def spearman(labels: np.ndarray, scores: np.ndarray) -> float | None:
    labels = np.asarray(labels, dtype=float)
    scores = np.asarray(scores, dtype=float)
    require(labels.ndim == scores.ndim == 1 and len(labels) == len(scores), "spearman_shape_mismatch")
    require(len(labels) >= 2 and np.isfinite(labels).all() and np.isfinite(scores).all(), "spearman_input_invalid")
    left, right = rank_average(labels), rank_average(scores)
    left -= left.mean()
    right -= right.mean()
    denominator = float(np.sqrt(np.sum(left * left) * np.sum(right * right)))
    if denominator == 0.0:
        return None
    return float(np.sum(left * right) / denominator)


def ndcg(labels: np.ndarray, scores: np.ndarray, candidate_ids: Sequence[str]) -> float | None:
    labels = np.asarray(labels, dtype=float)
    scores = np.asarray(scores, dtype=float)
    require(len(labels) == len(scores) == len(candidate_ids), "ndcg_shape_mismatch")
    require(np.isfinite(labels).all() and np.isfinite(scores).all(), "ndcg_input_invalid")
    require(np.all(labels >= 0.0), "ndcg_requires_nonnegative_labels")
    predicted = sorted(range(len(labels)), key=lambda i: (-scores[i], str(candidate_ids[i])))
    ideal = sorted(range(len(labels)), key=lambda i: (-labels[i], str(candidate_ids[i])))
    discount = np.log2(np.arange(len(labels), dtype=float) + 2.0)
    observed = float(sum(labels[index] / discount[rank] for rank, index in enumerate(predicted)))
    maximum = float(sum(labels[index] / discount[rank] for rank, index in enumerate(ideal)))
    return None if maximum == 0.0 else observed / maximum


def top_quartile_recall_at_20pct(
    labels: np.ndarray, scores: np.ndarray, candidate_ids: Sequence[str]
) -> dict[str, Any]:
    count = len(labels)
    require(count > 0 and count == len(scores) == len(candidate_ids), "recall_shape_mismatch")
    truth_count = max(1, math.ceil(0.25 * count))
    budget_count = max(1, math.ceil(0.20 * count))
    truth = set(sorted(range(count), key=lambda i: (-labels[i], str(candidate_ids[i])))[:truth_count])
    selected = set(sorted(range(count), key=lambda i: (-scores[i], str(candidate_ids[i])))[:budget_count])
    return {
        "value": len(truth & selected) / truth_count,
        "truth_top_quartile_count": truth_count,
        "budget_count": budget_count,
        "realized_budget_fraction": budget_count / count,
    }


def enrichment_factor_at_10pct(
    labels: np.ndarray, scores: np.ndarray, candidate_ids: Sequence[str]
) -> dict[str, Any]:
    count = len(labels)
    require(count > 0 and count == len(scores) == len(candidate_ids), "ef10_shape_mismatch")
    truth_count = max(1, math.ceil(0.25 * count))
    budget_count = max(1, math.ceil(0.10 * count))
    truth = set(
        sorted(range(count), key=lambda i: (-labels[i], str(candidate_ids[i])))[:truth_count]
    )
    selected = set(
        sorted(range(count), key=lambda i: (-scores[i], str(candidate_ids[i])))[:budget_count]
    )
    hits = len(truth & selected)
    prevalence = truth_count / count
    hit_rate = hits / budget_count
    return {
        "value": hit_rate / prevalence,
        "random_ranking_baseline": 1.0,
        "truth_top_quartile_count": truth_count,
        "budget_count": budget_count,
        "realized_budget_fraction": budget_count / count,
        "hit_count": hits,
        "hit_rate": hit_rate,
        "prevalence": prevalence,
    }


def metric_bundle(rows: Sequence[Mapping[str, Any]], score_field: str) -> dict[str, Any]:
    labels = np.asarray([float(row["R_dual_min"]) for row in rows], dtype=float)
    scores = np.asarray([float(row[score_field]) for row in rows], dtype=float)
    ids = [str(row["candidate_id"]) for row in rows]
    recall = top_quartile_recall_at_20pct(labels, scores, ids)
    ef10 = enrichment_factor_at_10pct(labels, scores, ids)
    return {
        "row_count": len(rows),
        "spearman": spearman(labels, scores),
        "ndcg": ndcg(labels, scores, ids),
        "top_quartile_recall_at_20pct_budget": recall,
        "enrichment_factor_at_10pct": ef10,
        "mae": float(np.mean(np.abs(scores - labels))),
    }


def uncertainty_selective_risk(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    require(count >= 4, "selective_risk_requires_four_rows")
    ordered = sorted(
        rows,
        key=lambda row: (-float(row["contact_prediction_uncertainty"]), str(row["candidate_id"])),
    )
    quartile = max(1, math.ceil(0.25 * count))
    high = ordered[:quartile]
    retained = ordered[quartile:]
    low = list(reversed(ordered[-quartile:]))
    def mae(part: Sequence[Mapping[str, Any]]) -> float:
        return float(np.mean([
            abs(float(row["contact_predicted_geometry_score"]) - float(row["R_dual_min"]))
            for row in part
        ]))
    overall = mae(rows)
    retained_mae = mae(retained)
    high_mae = mae(high)
    low_mae = mae(low)
    reduction = None if overall == 0.0 else (overall - retained_mae) / overall
    if low_mae == 0.0:
        ratio = None
        zero_denominator_case = (
            "HIGH_POSITIVE_LOW_ZERO" if high_mae > 0.0 else "BOTH_ZERO"
        )
    else:
        ratio = high_mae / low_mae
        zero_denominator_case = None
    return {
        "removed_highest_uncertainty_count": quartile,
        "retained_count": len(retained),
        "overall_mae": overall,
        "retained_mae": retained_mae,
        "mae_reduction_fraction": reduction,
        "highest_uncertainty_quartile_mae": high_mae,
        "lowest_uncertainty_quartile_mae": low_mae,
        "high_vs_low_uncertainty_quartile_mae_ratio": ratio,
        "high_vs_low_ratio_zero_denominator_case": zero_denominator_case,
    }


def bootstrap_parent_clusters(
    rows: Sequence[Mapping[str, Any]],
    *,
    score_field: str,
    baseline_field: str | None,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    require(replicates > 0, "bootstrap_replicates_must_be_positive")
    parents = sorted({str(row["parent_framework_cluster"]) for row in rows})
    groups = {parent: [row for row in rows if str(row["parent_framework_cluster"]) == parent] for parent in parents}
    rng = np.random.default_rng(seed)
    estimates: list[float] = []
    ef10_values: list[float] = []
    deltas: list[float] = []
    for _ in range(replicates):
        sampled = rng.integers(0, len(parents), size=len(parents))
        selected = [row for index in sampled for row in groups[parents[int(index)]]]
        labels = np.asarray([float(row["R_dual_min"]) for row in selected], dtype=float)
        scores = np.asarray([float(row[score_field]) for row in selected], dtype=float)
        estimate = spearman(labels, scores)
        ef10_values.append(
            enrichment_factor_at_10pct(
                labels,
                scores,
                [f"{row['candidate_id']}@{position}" for position, row in enumerate(selected)],
            )["value"]
        )
        if estimate is not None:
            estimates.append(estimate)
            if baseline_field is not None:
                baseline = np.asarray([float(row[baseline_field]) for row in selected], dtype=float)
                comparator = spearman(labels, baseline)
                if comparator is not None:
                    deltas.append(estimate - comparator)
    def interval(values: Sequence[float]) -> dict[str, Any]:
        if not values:
            return {"valid_replicates": 0, "valid_fraction": 0.0, "ci95_lower": None, "ci95_upper": None, "median": None}
        array = np.asarray(values, dtype=float)
        return {
            "valid_replicates": len(values),
            "valid_fraction": len(values) / replicates,
            "ci95_lower": float(np.quantile(array, 0.025)),
            "ci95_upper": float(np.quantile(array, 0.975)),
            "median": float(np.median(array)),
        }
    return {
        "unit": "parent_framework_cluster", "parent_count": len(parents),
        "replicates": replicates, "seed": seed,
        "contact_spearman": interval(estimates),
        "contact_enrichment_factor_at_10pct": interval(ef10_values),
        "contact_minus_shortcut_spearman_delta": interval(deltas) if baseline_field else None,
    }


def validate_preregistration(test_only: bool) -> Snapshot:
    prereg = snapshot(PREREG_PATH, "evaluator_preregistration")
    require(prereg.sha256 == EXPECTED_PREREG_SHA256, "evaluator_preregistration_hash_mismatch")
    payload = parse_json(prereg, "evaluator_preregistration")
    require(payload.get("status") == "FROZEN_V2_BEFORE_V4_F96_DOCKING_LABELS_EXIST_OR_ARE_OPENED", "evaluator_preregistration_status_invalid")
    require((payload.get("label_access_at_freeze") or {}).get("v4_f96_docking_labels_read") is False, "evaluator_preregistration_labels_were_read")
    return prereg


def guard_production_paths(config: EvaluationInputs) -> None:
    if config.test_only:
        return
    required = {
        "manifest": (config.manifest, CANONICAL_MANIFEST),
        "manifest_audit": (config.manifest_audit, CANONICAL_MANIFEST_AUDIT),
        "manifest_receipt": (config.manifest_receipt, CANONICAL_MANIFEST_RECEIPT),
        "prediction_receipt": (config.prediction_receipt, CANONICAL_PREDICTION_RECEIPT),
        "eligibility_receipt": (config.eligibility_receipt, CANONICAL_ELIGIBILITY_RECEIPT),
        "label_receipt": (config.label_receipt, CANONICAL_LABEL_RECEIPT),
        "output_dir": (config.output_dir, CANONICAL_OUTPUT_DIR),
        "trust_anchor": (config.trust_anchor or Path("."), CANONICAL_TRUST_ANCHOR),
    }
    for label, (actual, expected) in required.items():
        require(actual.absolute() == expected.absolute(), f"production_path_override_forbidden:{label}")


def validate_runtime_trust(
    config: EvaluationInputs,
    implementation: Snapshot,
    prereg: Snapshot,
) -> tuple[Snapshot | None, dict[str, str]]:
    if config.test_only:
        return None, {}
    require(config.trust_anchor is not None, "production_runtime_trust_anchor_required")
    anchor = snapshot(config.trust_anchor, "runtime_trust_anchor")
    declared_hash = os.environ.get(TRUST_ANCHOR_ENV, "").strip().lower()
    require(len(declared_hash) == 64 and declared_hash == anchor.sha256, "runtime_trust_anchor_launcher_binding_missing_or_invalid")
    payload = parse_json(anchor, "runtime_trust_anchor")
    require(
        payload.get("schema_version") == "phase2_v4_f96_formal_evaluator_runtime_trust_anchor_v1"
        and payload.get("status") == "PASS_NONCIRCULAR_RUNTIME_TRUST_ANCHOR_FROZEN",
        "runtime_trust_anchor_schema_or_status_invalid",
    )
    files = payload.get("files")
    require(isinstance(files, dict), "runtime_trust_anchor_files_missing")
    expected_roles = {
        "evaluator", "adversarial_tests", "freeze_builder", "preregistration",
        "test_log", "implementation_freeze", "implementation_freeze_receipt",
    }
    require(set(files) == expected_roles, "runtime_trust_anchor_file_set_invalid")
    observed: dict[str, Snapshot] = {}
    for role, item in files.items():
        require(isinstance(item, dict), f"runtime_trust_anchor_file_entry_invalid:{role}")
        bound = snapshot(Path(str(item.get("path", ""))), f"runtime_trust_anchor_file:{role}")
        require(bound.sha256 == item.get("sha256"), f"runtime_trust_anchor_file_hash_mismatch:{role}")
        observed[role] = bound
    require(observed["evaluator"].path == implementation.path and observed["evaluator"].sha256 == implementation.sha256, "runtime_trust_anchor_evaluator_mismatch")
    require(observed["preregistration"].path == prereg.path and observed["preregistration"].sha256 == prereg.sha256, "runtime_trust_anchor_preregistration_mismatch")
    require(observed["implementation_freeze"].path == CANONICAL_IMPLEMENTATION_FREEZE.resolve(), "runtime_trust_anchor_freeze_path_invalid")
    require(observed["implementation_freeze_receipt"].path == CANONICAL_IMPLEMENTATION_FREEZE_RECEIPT.resolve(), "runtime_trust_anchor_freeze_receipt_path_invalid")
    freeze = parse_json(observed["implementation_freeze"], "implementation_freeze")
    freeze_receipt = parse_json(observed["implementation_freeze_receipt"], "implementation_freeze_receipt")
    require(freeze.get("status") == "PASS_IMPLEMENTATION_FROZEN_BEFORE_V4F96_LABEL_UNSEAL", "implementation_freeze_status_invalid")
    without_hash = dict(freeze)
    declared_payload_hash = without_hash.pop("payload_sha256", None)
    require(declared_payload_hash == sha256_json(without_hash), "implementation_freeze_payload_hash_mismatch")
    require(
        freeze_receipt.get("status") == "PASS_COMPLETE_HASH_CLOSURE_BEFORE_V4F96_LABEL_UNSEAL"
        and (freeze_receipt.get("implementation_freeze") or {}).get("sha256")
        == observed["implementation_freeze"].sha256,
        "implementation_freeze_receipt_closure_invalid",
    )
    for role in ("evaluator", "adversarial_tests", "freeze_builder", "preregistration", "test_log"):
        frozen_item = (freeze.get("implementation_files") or {}).get(role)
        require(
            isinstance(frozen_item, dict)
            and frozen_item.get("path") == str(observed[role].path)
            and frozen_item.get("sha256") == observed[role].sha256,
            f"implementation_freeze_file_binding_invalid:{role}",
        )
    require(freeze_receipt.get("evaluator_sha256") == implementation.sha256, "implementation_freeze_receipt_evaluator_mismatch")
    require(freeze_receipt.get("evaluator_preregistration_sha256") == prereg.sha256, "implementation_freeze_receipt_preregistration_mismatch")
    return anchor, {
        "trust_anchor_sha256": anchor.sha256,
        "implementation_freeze_sha256": observed["implementation_freeze"].sha256,
        "implementation_freeze_receipt_sha256": observed["implementation_freeze_receipt"].sha256,
    }


def acquire_one_shot_lock(
    config: EvaluationInputs,
    trust_anchor_sha256: str | None,
    prediction_receipt_sha256: str,
    eligibility_receipt_sha256: str,
) -> Snapshot:
    lock_path = (
        CANONICAL_ONE_SHOT_LOCK
        if not config.test_only
        else config.output_dir.parent / f".{config.output_dir.name}.one_shot.lock"
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "phase2_v4_f96_formal_evaluation_one_shot_lock_v1",
        "status": "FORMAL_LABEL_UNSEAL_COMMITTED_NO_RETRY_UNDER_V1",
        "output_dir": str(config.output_dir.resolve()),
        "trust_anchor_sha256": trust_anchor_sha256,
        "prediction_receipt_sha256": prediction_receipt_sha256,
        "eligibility_receipt_sha256": eligibility_receipt_sha256,
        "pid": os.getpid(),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    try:
        descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    except FileExistsError as exc:
        raise FormalEvaluationError("formal_one_shot_lock_already_exists_no_retry") from exc
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory_descriptor = os.open(lock_path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    return snapshot(lock_path, "formal_one_shot_lock")


def validate_panel(config: EvaluationInputs) -> tuple[list[dict[str, str]], dict[str, Snapshot]]:
    sources = {
        "manifest": snapshot(config.manifest, "panel_manifest"),
        "audit": snapshot(config.manifest_audit, "panel_audit"),
        "receipt": snapshot(config.manifest_receipt, "panel_receipt"),
    }
    if not config.test_only:
        require(sources["manifest"].sha256 == EXPECTED_MANIFEST_SHA256, "panel_manifest_production_hash_mismatch")
        require(sources["audit"].sha256 == EXPECTED_MANIFEST_AUDIT_SHA256, "panel_audit_production_hash_mismatch")
        require(sources["receipt"].sha256 == EXPECTED_MANIFEST_RECEIPT_SHA256, "panel_receipt_production_hash_mismatch")
    rows, fields = parse_tsv(sources["manifest"], "panel_manifest")
    required = set(IDENTITY_FIELDS)
    require(required <= set(fields), "panel_manifest_identity_fields_missing")
    require(len(rows) == EXPECTED_ROW_COUNT, "panel_manifest_row_count_invalid")
    require(len({row["candidate_id"] for row in rows}) == len(rows), "panel_manifest_duplicate_candidate")
    require(all(row.get("model_split") == MODEL_SPLIT for row in rows), "panel_manifest_split_invalid")
    require(set(row["parent_framework_cluster"] for row in rows) == set(EXPECTED_PARENT_CLUSTERS), "panel_manifest_parent_clusters_invalid")
    audit = parse_json(sources["audit"], "panel_audit")
    receipt = parse_json(sources["receipt"], "panel_receipt")
    expected_mode = "test_only" if config.test_only else "production"
    if config.test_only:
        require(audit.get("execution_mode") in {"test_only", "production"}, "panel_audit_test_mode_invalid")
        require(receipt.get("execution_mode") in {"test_only", "production"}, "panel_receipt_test_mode_invalid")
    else:
        require(audit.get("execution_mode") == expected_mode and receipt.get("execution_mode") == expected_mode, "panel_execution_mode_invalid")
    require(receipt.get("manifest_sha256") == sources["manifest"].sha256, "panel_receipt_manifest_hash_mismatch")
    require(receipt.get("audit_file_sha256") == sources["audit"].sha256, "panel_receipt_audit_hash_mismatch")
    return rows, sources


def validate_prediction_release(
    config: EvaluationInputs,
    panel_rows: list[dict[str, str]],
    panel_sources: Mapping[str, Snapshot],
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Snapshot]]:
    """Validate frozen predictions completely. No label/eligibility path is touched here."""
    receipt_source = snapshot(config.prediction_receipt, "prediction_receipt")
    receipt = parse_json(receipt_source, "prediction_receipt")
    expected_mode = "test_only" if config.test_only else "production"
    require(receipt.get("schema_version") == PREDICTION_SCHEMA_VERSION, "prediction_receipt_schema_invalid")
    require(receipt.get("status") == PREDICTION_STATUS, "prediction_receipt_status_invalid")
    require(receipt.get("execution_mode") == expected_mode, "prediction_receipt_execution_mode_invalid")
    require(receipt.get("row_count") == EXPECTED_ROW_COUNT, "prediction_receipt_row_count_invalid")
    require(receipt.get("v4_f_labels_read") is False and receipt.get("v4_f_label_paths_accepted") == 0, "prediction_receipt_not_label_blind")
    require(receipt.get("primary_evaluation_policy") == PRIMARY_POLICY, "prediction_receipt_policy_mismatch")
    require(receipt.get("primary_evaluation_policy_sha256") == sha256_json(PRIMARY_POLICY), "prediction_receipt_policy_hash_mismatch")
    holdout = receipt.get("holdout") or {}
    require(holdout == {
        "manifest_sha256": panel_sources["manifest"].sha256,
        "audit_sha256": panel_sources["audit"].sha256,
        "manifest_receipt_sha256": panel_sources["receipt"].sha256,
    }, "prediction_receipt_panel_binding_mismatch")
    outputs = receipt.get("outputs")
    require(isinstance(outputs, dict) and set(outputs) == {"predictions", "audit"}, "prediction_receipt_outputs_invalid")
    prediction_source = snapshot(Path(outputs["predictions"]["path"]), "frozen_predictions")
    audit_source = snapshot(Path(outputs["audit"]["path"]), "prediction_audit")
    require(outputs["predictions"].get("sha256") == prediction_source.sha256, "prediction_tsv_hash_mismatch")
    require(outputs["audit"].get("sha256") == audit_source.sha256, "prediction_audit_hash_mismatch")
    audit = parse_json(audit_source, "prediction_audit")
    require(audit.get("status") == PREDICTION_STATUS and audit.get("execution_mode") == expected_mode, "prediction_audit_status_or_mode_invalid")
    require(audit.get("row_count") == EXPECTED_ROW_COUNT, "prediction_audit_row_count_invalid")
    require(audit.get("v4_f_labels_read") is False and audit.get("v4_f_label_files_opened") == 0 and audit.get("v4_f_label_paths_accepted") == 0, "prediction_audit_not_label_blind")
    require(audit.get("prediction_sha256") == prediction_source.sha256, "prediction_audit_tsv_hash_mismatch")
    require(audit.get("primary_evaluation_policy") == PRIMARY_POLICY and audit.get("primary_evaluation_policy_sha256") == sha256_json(PRIMARY_POLICY), "prediction_audit_policy_mismatch")
    if not config.test_only:
        input_hashes = receipt.get("input_hashes")
        require(isinstance(input_hashes, dict) and input_hashes, "prediction_receipt_input_hashes_missing")
        require(receipt.get("input_count") == len(input_hashes), "prediction_receipt_input_count_mismatch")
        require(receipt.get("input_closure_sha256") == sha256_json(input_hashes), "prediction_receipt_input_closure_mismatch")
        require(audit.get("input_hashes") == input_hashes and audit.get("input_count") == len(input_hashes) and audit.get("input_closure_sha256") == receipt.get("input_closure_sha256"), "prediction_audit_input_closure_mismatch")
        for path_text, expected_hash in input_hashes.items():
            bound = snapshot(Path(path_text), "prediction_bound_input")
            require(bound.sha256 == expected_hash, f"prediction_bound_input_hash_mismatch:{path_text}")
        source_hashes = receipt.get("execution_source_hashes")
        require(isinstance(source_hashes, dict) and source_hashes, "prediction_receipt_execution_sources_missing")
        require(receipt.get("execution_source_closure_sha256") == sha256_json(source_hashes), "prediction_receipt_execution_source_closure_mismatch")
        require(audit.get("execution_source_hashes") == source_hashes and audit.get("execution_source_closure_sha256") == receipt.get("execution_source_closure_sha256"), "prediction_audit_execution_sources_mismatch")
        for path_text, expected_hash in source_hashes.items():
            require(input_hashes.get(path_text) == expected_hash, f"prediction_execution_source_not_input_bound:{path_text}")
        freezer_path = str((SCRIPT_DIR / "freeze_phase2_v4_f_surrogate_predictions.py").resolve())
        require(receipt.get("freezer_implementation_sha256") == input_hashes.get(freezer_path), "prediction_freezer_implementation_not_bound")
    rows, fields = parse_tsv(prediction_source, "frozen_predictions")
    require(fields == PREDICTION_FIELDS, "prediction_fields_not_exactly_frozen")
    require(len(rows) == EXPECTED_ROW_COUNT, "prediction_row_count_invalid")
    require([row["candidate_id"] for row in rows] == [row["candidate_id"] for row in panel_rows], "prediction_candidate_order_mismatch")
    for predicted, panel in zip(rows, panel_rows):
        for field in IDENTITY_FIELDS:
            require(predicted.get(field) == panel.get(field), f"prediction_identity_mismatch:{field}:{panel['candidate_id']}")
        for family in ("base", "embedding", "contact"):
            require(bool(predicted.get(f"{family}_selected_model", "").strip()), f"prediction_model_missing:{family}")
            score = finite_float(predicted.get(f"{family}_predicted_geometry_score"), f"prediction:{family}")
            uncertainty = finite_float(predicted.get(f"{family}_prediction_uncertainty"), f"prediction_uncertainty:{family}")
            require(uncertainty >= 0.0, f"prediction_uncertainty_negative:{family}")
            predicted[f"{family}_predicted_geometry_score"] = score  # type: ignore[assignment]
            predicted[f"{family}_prediction_uncertainty"] = uncertainty  # type: ignore[assignment]
    model_names: dict[str, str] = {}
    for family in ("base", "embedding", "contact"):
        names = {str(row[f"{family}_selected_model"]) for row in rows}
        require(len(names) == 1, f"{family}_model_identity_varies_by_row")
        model_names[family] = next(iter(names))
    require(model_names["contact"] not in PREDECLARED_SHORTCUTS, "contact_primary_is_shortcut")
    require(
        receipt.get("prediction_models") == model_names
        and audit.get("prediction_models") == model_names,
        "prediction_model_identity_receipt_mismatch",
    )
    return rows, receipt, {"receipt": receipt_source, "predictions": prediction_source, "audit": audit_source}


def load_eligibility_after_prediction_gate(
    config: EvaluationInputs,
    panel_rows: list[dict[str, str]],
    panel_sources: Mapping[str, Snapshot],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Snapshot]]:
    receipt_source = snapshot(config.eligibility_receipt, "eligibility_receipt")
    receipt = parse_json(receipt_source, "eligibility_receipt")
    mode = "test_only" if config.test_only else "production"
    require(receipt.get("schema_version") == ELIGIBILITY_SCHEMA_VERSION and receipt.get("status") == ELIGIBILITY_STATUS, "eligibility_receipt_schema_or_status_invalid")
    require(receipt.get("execution_mode") == mode, "eligibility_receipt_execution_mode_invalid")
    require(receipt.get("manifest_sha256") == panel_sources["manifest"].sha256, "eligibility_receipt_manifest_hash_mismatch")
    artifact = receipt.get("eligibility") or {}
    source = snapshot(Path(str(artifact.get("path", ""))), "eligibility_tsv")
    require(artifact.get("sha256") == source.sha256, "eligibility_tsv_hash_mismatch")
    rows, fields = parse_tsv(source, "eligibility_tsv")
    require(fields == ELIGIBILITY_FIELDS and len(rows) == EXPECTED_ROW_COUNT, "eligibility_schema_or_count_invalid")
    require([row["candidate_id"] for row in rows] == [row["candidate_id"] for row in panel_rows], "eligibility_candidate_order_mismatch")
    normalized: list[dict[str, Any]] = []
    for row, panel in zip(rows, panel_rows):
        for field in ("candidate_id", "sequence_sha256", "parent_framework_cluster", "model_split"):
            require(row.get(field) == panel.get(field), f"eligibility_identity_mismatch:{field}:{panel['candidate_id']}")
        hard_pass = parse_bool(row["full_qc_hard_pass"], "full_qc_hard_pass")
        replacement = parse_bool(row["replacement_used"], "replacement_used")
        require(not replacement, f"replacement_forbidden:{panel['candidate_id']}")
        require(bool(row["full_qc_status"].strip()), f"full_qc_status_missing:{panel['candidate_id']}")
        normalized.append({**row, "full_qc_hard_pass": hard_pass, "replacement_used": replacement})
    hard_count = sum(row["full_qc_hard_pass"] for row in normalized)
    require(receipt.get("row_count") == EXPECTED_ROW_COUNT and receipt.get("hard_pass_count") == hard_count and receipt.get("replacement_count") == 0, "eligibility_receipt_counts_invalid")
    return normalized, receipt, {"receipt": receipt_source, "tsv": source}


def parse_seed_ids(text: str, count: int, field: str) -> tuple[int, ...]:
    stripped = text.strip()
    try:
        values = (
            tuple(int(value) for value in stripped.split(",") if value.strip())
            if stripped else ()
        )
    except ValueError as exc:
        raise FormalEvaluationError(f"invalid_seed_id:{field}") from exc
    require(len(values) == count and len(set(values)) == len(values), f"seed_ids_count_or_duplicate:{field}")
    require(set(values) <= set(EXPECTED_SEEDS), f"unexpected_seed_id:{field}")
    return tuple(sorted(values))


def load_labels_after_prediction_gate(
    config: EvaluationInputs,
    panel_sources: Mapping[str, Snapshot],
    prediction_sources: Mapping[str, Snapshot],
    eligibility_rows: list[dict[str, Any]],
    eligibility_sources: Mapping[str, Snapshot],
    prereg_source: Snapshot,
    implementation_source: Snapshot,
    runtime_trust: Mapping[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Snapshot]]:
    receipt_source = snapshot(config.label_receipt, "docking_label_receipt")
    receipt = parse_json(receipt_source, "docking_label_receipt")
    mode = "test_only" if config.test_only else "production"
    require(receipt.get("schema_version") == LABEL_SCHEMA_VERSION and receipt.get("status") == LABEL_STATUS, "label_receipt_schema_or_status_invalid")
    require(receipt.get("execution_mode") == mode, "label_receipt_execution_mode_invalid")
    require(receipt.get("prediction_receipt_sha256") == prediction_sources["receipt"].sha256, "label_receipt_prediction_binding_mismatch")
    require(receipt.get("evaluator_preregistration_sha256") == prereg_source.sha256, "label_receipt_prereg_binding_mismatch")
    require(receipt.get("evaluator_implementation_sha256") == implementation_source.sha256, "label_receipt_evaluator_binding_mismatch")
    if not config.test_only:
        require(
            receipt.get("runtime_trust_anchor_sha256")
            == runtime_trust.get("trust_anchor_sha256")
            and receipt.get("implementation_freeze_sha256")
            == runtime_trust.get("implementation_freeze_sha256")
            and receipt.get("implementation_freeze_receipt_sha256")
            == runtime_trust.get("implementation_freeze_receipt_sha256"),
            "label_receipt_runtime_trust_binding_mismatch",
        )
    require(receipt.get("manifest_sha256") == panel_sources["manifest"].sha256, "label_receipt_manifest_binding_mismatch")
    require(receipt.get("eligibility_sha256") == eligibility_sources["tsv"].sha256, "label_receipt_eligibility_binding_mismatch")
    require(receipt.get("all_jobs_terminal") is True, "label_receipt_jobs_not_all_terminal")
    require(receipt.get("receptors") == ["8X6B", "9E6Y"], "label_receipt_receptors_invalid")
    require(receipt.get("seeds") == list(EXPECTED_SEEDS), "label_receipt_seed_matrix_invalid")
    artifact = receipt.get("labels") or {}
    source = snapshot(Path(str(artifact.get("path", ""))), "docking_labels")
    require(artifact.get("sha256") == source.sha256, "docking_label_tsv_hash_mismatch")
    rows, fields = parse_tsv(source, "docking_labels")
    require(fields == LABEL_FIELDS, "docking_label_schema_invalid")
    eligible = [row for row in eligibility_rows if row["full_qc_hard_pass"]]
    require(len(rows) == len(eligible), "docking_label_count_not_equal_hard_pass_denominator")
    require([row["candidate_id"] for row in rows] == [row["candidate_id"] for row in eligible], "docking_label_candidate_order_mismatch")
    normalized: list[dict[str, Any]] = []
    for row, expected in zip(rows, eligible):
        for field in ("candidate_id", "sequence_sha256", "parent_framework_cluster", "model_split"):
            require(row.get(field) == expected.get(field), f"docking_label_identity_mismatch:{field}:{expected['candidate_id']}")
        require(parse_bool(row["independent_receptor_docking"], "independent_receptor_docking"), f"independent_receptor_docking_false:{row['candidate_id']}")
        counts: dict[str, int] = {}
        for receptor in ("8X6B", "9E6Y"):
            try:
                count = int(row[f"successful_seed_count_{receptor}"])
            except ValueError as exc:
                raise FormalEvaluationError(f"invalid_seed_count:{row['candidate_id']}:{receptor}") from exc
            require(0 <= count <= len(EXPECTED_SEEDS), f"seed_count_out_of_range:{row['candidate_id']}:{receptor}")
            parse_seed_ids(row[f"successful_seed_ids_{receptor}"], count, f"{row['candidate_id']}:{receptor}")
            counts[receptor] = count
        status = row["docking_status"]
        if status == ANALYZABLE_STATUS:
            require(counts["8X6B"] >= 2 and counts["9E6Y"] >= 2, f"analyzable_seed_completeness_failed:{row['candidate_id']}")
            value = finite_float(row["R_dual_min"], f"R_dual_min:{row['candidate_id']}")
            require(0.0 <= value <= 1.0, f"R_dual_min_out_of_bounds:{row['candidate_id']}")
            require(row["technical_failure_reason"].strip() == "", f"analyzable_row_has_failure_reason:{row['candidate_id']}")
        elif status == TECHNICAL_FAILURE_STATUS:
            require(row["R_dual_min"].strip() == "", f"technical_failure_R_dual_min_must_be_blank:{row['candidate_id']}")
            require(bool(row["technical_failure_reason"].strip()), f"technical_failure_reason_missing:{row['candidate_id']}")
            value = None
        else:
            raise FormalEvaluationError(f"unknown_docking_status:{row['candidate_id']}:{status}")
        normalized.append({**row, "R_dual_min": value, "successful_seed_count_8X6B": counts["8X6B"], "successful_seed_count_9E6Y": counts["9E6Y"]})
    analyzable_count = sum(row["docking_status"] == ANALYZABLE_STATUS for row in normalized)
    technical_count = sum(row["docking_status"] == TECHNICAL_FAILURE_STATUS for row in normalized)
    expected_terminal_jobs = len(eligible) * 2 * len(EXPECTED_SEEDS)
    require(
        receipt.get("eligible_hard_pass_count") == len(eligible)
        and receipt.get("label_row_count") == len(rows)
        and receipt.get("analyzable_count") == analyzable_count
        and receipt.get("technical_failure_count") == technical_count
        and receipt.get("expected_receptor_seed_job_count") == expected_terminal_jobs
        and receipt.get("terminal_receptor_seed_job_count") == expected_terminal_jobs,
        "label_receipt_counts_invalid",
    )
    return normalized, receipt, {"receipt": receipt_source, "tsv": source}


def join_evaluation_rows(
    predictions: list[dict[str, str]], labels: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {row["candidate_id"]: row for row in predictions}
    require(len(by_id) == len(predictions), "prediction_duplicate_candidate")
    output: list[dict[str, Any]] = []
    for label in labels:
        prediction = by_id.get(label["candidate_id"])
        require(prediction is not None, f"prediction_missing_for_label:{label['candidate_id']}")
        for field in ("sequence_sha256", "parent_framework_cluster", "model_split"):
            require(prediction[field] == label[field], f"prediction_label_identity_mismatch:{field}:{label['candidate_id']}")
        output.append({**prediction, **label})
    return output


def identify_frozen_shortcut(
    prediction_rows: Sequence[Mapping[str, Any]],
    receipt: Mapping[str, Any],
) -> tuple[str, str] | None:
    candidates: list[tuple[str, str, str]] = []
    for family in ("base", "embedding"):
        names = {str(row[f"{family}_selected_model"]) for row in prediction_rows}
        require(len(names) == 1, f"{family}_model_identity_varies_by_row")
        name = next(iter(names))
        if name in PREDECLARED_SHORTCUTS:
            candidates.append((name, family, f"{family}_predicted_geometry_score"))
    declared = receipt.get("strongest_shortcut_model")
    if not candidates:
        require(declared in {None, ""}, "prediction_receipt_declares_absent_shortcut")
        return None
    require(isinstance(declared, str) and declared, "shortcut_present_without_prefrozen_comparator_identity")
    require(declared != "constant", "constant_shortcut_not_rank_comparable_for_spearman_delta")
    matches = [candidate for candidate in candidates if candidate[0] == declared]
    require(len(matches) == 1, "prediction_receipt_shortcut_identity_mismatch")
    return matches[0][0], matches[0][2]


def evaluate_metrics(
    joined_rows: list[dict[str, Any]],
    hard_pass_count: int,
    frozen_shortcut: tuple[str, str] | None,
    bootstrap_replicates: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    analyzable = [row for row in joined_rows if row["docking_status"] == ANALYZABLE_STATUS]
    technical = [row for row in joined_rows if row["docking_status"] == TECHNICAL_FAILURE_STATUS]
    by_parent = {parent: [row for row in analyzable if row["parent_framework_cluster"] == parent] for parent in EXPECTED_PARENT_CLUSTERS}
    coverage_checks = {
        "hard_pass_count_ge_64": hard_pass_count >= MIN_HARD_PASS,
        "analyzable_count_ge_64": len(analyzable) >= MIN_ANALYZABLE,
        "analyzable_fraction_ge_0_80": (len(analyzable) / hard_pass_count if hard_pass_count else 0.0) >= MIN_ANALYZABLE_FRACTION,
        "all_four_parent_clusters_represented": all(by_parent[parent] for parent in EXPECTED_PARENT_CLUSTERS),
        "each_parent_has_at_least_8_analyzable": all(len(by_parent[parent]) >= MIN_PER_PARENT for parent in EXPECTED_PARENT_CLUSTERS),
    }
    coverage_sufficient = all(coverage_checks.values())
    if not coverage_sufficient:
        parent_rows = [{
            "parent_framework_cluster": parent,
            "analyzable_count": len(by_parent[parent]),
            "contact_spearman": "", "contact_ndcg": "",
            "contact_top_quartile_recall_at_20pct_budget": "",
            "contact_enrichment_factor_at_10pct": "",
            "contact_mae": "", "shortcut_name": "", "shortcut_spearman": "",
            "contact_minus_shortcut_spearman_delta": "",
        } for parent in EXPECTED_PARENT_CLUSTERS]
        return ({
            "status": "INSUFFICIENT_TECHNICAL_COVERAGE", "hard_pass_count": hard_pass_count,
            "analyzable_count": len(analyzable), "technical_failure_count": len(technical),
            "analyzable_fraction_of_hard_pass": len(analyzable) / hard_pass_count if hard_pass_count else 0.0,
            "coverage_checks": coverage_checks, "metrics": None, "decision_gates": {},
        }, parent_rows)
    contact = metric_bundle(analyzable, "contact_predicted_geometry_score")
    descriptive = {
        "base": metric_bundle(analyzable, "base_predicted_geometry_score"),
        "embedding": metric_bundle(analyzable, "embedding_predicted_geometry_score"),
    }
    selective = uncertainty_selective_risk(analyzable)
    shortcut = frozen_shortcut
    shortcut_metrics = metric_bundle(analyzable, shortcut[1]) if shortcut else None
    bootstrap = bootstrap_parent_clusters(
        analyzable, score_field="contact_predicted_geometry_score",
        baseline_field=shortcut[1] if shortcut else None,
        replicates=bootstrap_replicates, seed=BOOTSTRAP_SEED,
    )
    parent_rows: list[dict[str, Any]] = []
    parent_metrics: dict[str, Any] = {}
    for parent in EXPECTED_PARENT_CLUSTERS:
        rows = by_parent[parent]
        if rows:
            primary = metric_bundle(rows, "contact_predicted_geometry_score")
            base_metric = metric_bundle(rows, "base_predicted_geometry_score")
            embedding_metric = metric_bundle(rows, "embedding_predicted_geometry_score")
            shortcut_metric = metric_bundle(rows, shortcut[1]) if shortcut else None
        else:
            primary = base_metric = embedding_metric = shortcut_metric = None
        parent_metrics[parent] = {
            "contact": primary, "base": base_metric, "embedding": embedding_metric,
            "shortcut": shortcut_metric,
        }
        parent_rows.append({
            "parent_framework_cluster": parent, "analyzable_count": len(rows),
            "contact_spearman": "" if primary is None or primary["spearman"] is None else primary["spearman"],
            "contact_ndcg": "" if primary is None or primary["ndcg"] is None else primary["ndcg"],
            "contact_top_quartile_recall_at_20pct_budget": "" if primary is None else primary["top_quartile_recall_at_20pct_budget"]["value"],
            "contact_enrichment_factor_at_10pct": "" if primary is None else primary["enrichment_factor_at_10pct"]["value"],
            "contact_mae": "" if primary is None else primary["mae"],
            "shortcut_name": "" if shortcut is None else shortcut[0],
            "shortcut_spearman": "" if shortcut_metric is None or shortcut_metric["spearman"] is None else shortcut_metric["spearman"],
            "contact_minus_shortcut_spearman_delta": "" if shortcut_metric is None or shortcut_metric["spearman"] is None or primary is None or primary["spearman"] is None else primary["spearman"] - shortcut_metric["spearman"],
        })
    finite_parent_rhos = [payload["contact"]["spearman"] for payload in parent_metrics.values() if payload["contact"] is not None and payload["contact"]["spearman"] is not None]
    def parent_macro(family: str) -> dict[str, float | None]:
        bundles = [payload[family] for payload in parent_metrics.values() if payload[family] is not None]
        def average(values: Sequence[float | None]) -> float | None:
            finite = [float(value) for value in values if value is not None]
            return float(np.mean(finite)) if finite else None
        return {
            "spearman": average([bundle["spearman"] for bundle in bundles]),
            "ndcg": average([bundle["ndcg"] for bundle in bundles]),
            "top_quartile_recall_at_20pct_budget": average([
                bundle["top_quartile_recall_at_20pct_budget"]["value"] for bundle in bundles
            ]),
            "enrichment_factor_at_10pct": average([
                bundle["enrichment_factor_at_10pct"]["value"] for bundle in bundles
            ]),
            "mae": average([bundle["mae"] for bundle in bundles]),
            "defined_parent_count": len(bundles),
        }
    parent_macro_metrics = {
        family: parent_macro(family) for family in ("contact", "base", "embedding")
    }
    parent_macro_spearman = parent_macro_metrics["contact"]["spearman"]
    nonnegative_parent_count = sum(value >= 0.0 for value in finite_parent_rhos)
    bootstrap_valid = bootstrap["contact_spearman"]["valid_fraction"] >= MIN_BOOTSTRAP_VALID_FRACTION
    coverage_checks["parent_bootstrap_valid_fraction_ge_0_80"] = bootstrap_valid
    coverage_sufficient = coverage_sufficient and bootstrap_valid
    primary_rho = contact["spearman"]
    ci_lower = bootstrap["contact_spearman"]["ci95_lower"]
    recall_value = contact["top_quartile_recall_at_20pct_budget"]["value"]
    ef10_value = contact["enrichment_factor_at_10pct"]["value"]
    ef10_ci_lower = bootstrap["contact_enrichment_factor_at_10pct"]["ci95_lower"]
    reduction = selective["mae_reduction_fraction"]
    ratio = selective["high_vs_low_uncertainty_quartile_mae_ratio"]
    ratio_zero_case = selective["high_vs_low_ratio_zero_denominator_case"]
    gates: dict[str, bool] = {
        "overall_contact_spearman_ge_0_30": primary_rho is not None and primary_rho >= THRESHOLDS["overall_contact_spearman_minimum"],
        "parent_cluster_bootstrap_ci95_lower_gt_0": ci_lower is not None and ci_lower > 0.0,
        "parent_macro_spearman_ge_0_20": parent_macro_spearman is not None and parent_macro_spearman >= THRESHOLDS["parent_macro_spearman_minimum"],
        "at_least_3_nonnegative_parent_spearman": nonnegative_parent_count >= THRESHOLDS["minimum_nonnegative_parent_spearman_count"],
        "top_quartile_recall_at_20pct_ge_0_50": recall_value >= THRESHOLDS["top_quartile_recall_at_20pct_budget_minimum"],
        "enrichment_factor_at_10pct_ge_3_0": ef10_value >= THRESHOLDS["ef_at_top10_minimum"],
        "ef10_parent_bootstrap_ci95_lower_gt_random_1_0": (
            ef10_ci_lower is not None
            and ef10_ci_lower
            > THRESHOLDS["ef_at_top10_parent_bootstrap_ci95_lower_strictly_greater_than_random_baseline"]
        ),
        "selective_risk_mae_reduction_ge_0_10": reduction is not None and reduction >= THRESHOLDS["selective_risk_mae_reduction_minimum"],
        "high_vs_low_uncertainty_mae_ratio_ge_1_25": (
            (ratio is not None and ratio >= THRESHOLDS["high_vs_low_uncertainty_quartile_mae_ratio_minimum"])
            or ratio_zero_case == "HIGH_POSITIVE_LOW_ZERO"
        ),
    }
    shortcut_decision = None
    if shortcut:
        shortcut_rho = shortcut_metrics["spearman"] if shortcut_metrics else None
        delta = None if primary_rho is None or shortcut_rho is None else primary_rho - shortcut_rho
        parent_deltas = [
            row["contact_minus_shortcut_spearman_delta"] for row in parent_rows
            if row["contact_minus_shortcut_spearman_delta"] != ""
        ]
        shortcut_gates = {
            "overall_spearman_delta_ge_0_05": delta is not None and delta >= THRESHOLDS["overall_spearman_delta_over_strongest_shortcut_minimum"],
            "at_least_3_nonnegative_parent_deltas": sum(value >= 0.0 for value in parent_deltas) >= THRESHOLDS["minimum_nonnegative_parent_delta_count"],
        }
        gates.update({f"conditional_shortcut_{key}": value for key, value in shortcut_gates.items()})
        shortcut_decision = {"name": shortcut[0], "metrics": shortcut_metrics, "overall_spearman_delta": delta, "gates": shortcut_gates}
    if not coverage_sufficient:
        status = "INSUFFICIENT_TECHNICAL_COVERAGE"
    elif all(gates.values()):
        status = "PASS_V4_F96_COMPUTATIONAL_GEOMETRY_SURROGATE"
    else:
        status = "FAIL_V4_F96_COMPUTATIONAL_GEOMETRY_SURROGATE"
    return ({
        "status": status, "hard_pass_count": hard_pass_count,
        "analyzable_count": len(analyzable), "technical_failure_count": len(technical),
        "analyzable_fraction_of_hard_pass": len(analyzable) / hard_pass_count if hard_pass_count else 0.0,
        "coverage_checks": coverage_checks,
        "metrics": {
            "contact_primary": contact, "base_descriptive": descriptive["base"],
            "embedding_descriptive": descriptive["embedding"],
            "uncertainty_selective_risk": selective,
            "per_parent": parent_metrics,
            "parent_macro": parent_macro_metrics,
            "parent_macro_spearman": parent_macro_spearman,
            "nonnegative_parent_spearman_count": nonnegative_parent_count,
            "parent_cluster_bootstrap": bootstrap,
            "conditional_shortcut": shortcut_decision,
        },
        "decision_gates": gates,
    }, parent_rows)


def verify_snapshots_unchanged(sources: Iterable[Snapshot]) -> None:
    for source in sources:
        require(source.path.is_file() and not source.path.is_symlink(), f"input_changed_or_missing:{source.path}")
        require(sha256_bytes(source.path.read_bytes()) == source.sha256, f"input_changed_during_evaluation:{source.path}")


def run_evaluation(config: EvaluationInputs) -> dict[str, Any]:
    require(config.bootstrap_replicates == BOOTSTRAP_REPLICATES or config.test_only, "production_bootstrap_replicates_frozen")
    guard_production_paths(config)
    implementation = snapshot(SCRIPT_PATH, "evaluator_implementation")
    prereg = validate_preregistration(config.test_only)
    trust_anchor, runtime_trust = validate_runtime_trust(config, implementation, prereg)
    panel_rows, panel_sources = validate_panel(config)
    # Security boundary: this complete prediction gate occurs before either future
    # label-bearing receipt path is inspected, stat'ed, or opened.
    predictions, prediction_receipt, prediction_sources = validate_prediction_release(config, panel_rows, panel_sources)
    frozen_shortcut = identify_frozen_shortcut(predictions, prediction_receipt)
    if config.output_dir.exists():
        require(
            config.output_dir.is_dir()
            and not config.output_dir.is_symlink()
            and not any(config.output_dir.iterdir()),
            "formal_output_directory_not_empty_one_shot_refusal",
        )
    eligibility, eligibility_receipt, eligibility_sources = load_eligibility_after_prediction_gate(config, panel_rows, panel_sources)
    one_shot_lock = acquire_one_shot_lock(
        config, runtime_trust.get("trust_anchor_sha256"),
        prediction_sources["receipt"].sha256,
        eligibility_sources["receipt"].sha256,
    )
    labels, label_receipt, label_sources = load_labels_after_prediction_gate(
        config, panel_sources, prediction_sources, eligibility, eligibility_sources,
        prereg, implementation, runtime_trust,
    )
    joined = join_evaluation_rows(predictions, labels)
    hard_pass_count = sum(row["full_qc_hard_pass"] for row in eligibility)
    evaluation, parent_rows = evaluate_metrics(
        joined, hard_pass_count, frozen_shortcut, config.bootstrap_replicates
    )
    all_sources = [
        implementation, prereg,
        *([] if trust_anchor is None else [trust_anchor]),
        *panel_sources.values(), *prediction_sources.values(),
        *eligibility_sources.values(), *label_sources.values(), one_shot_lock,
    ]
    verify_snapshots_unchanged(all_sources)
    config.output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{config.output_dir.name}.stage.", dir=config.output_dir.parent))
    try:
        summary_path = staging / OUTPUT_FILES[0]
        parent_path = staging / OUTPUT_FILES[1]
        receipt_path = staging / OUTPUT_FILES[2]
        summary = {
            "schema_version": "phase2_v4_f96_one_shot_formal_evaluation_v1",
            "status": evaluation["status"],
            "execution_mode": "test_only" if config.test_only else "production",
            "primary_endpoint": "R_dual_min", "endpoint_direction": "higher_is_better",
            "primary_model_family": "contact", "one_shot": True,
            "denominator_policy": "all frozen V4-F Full-QC hard-pass candidates; no replacement",
            "panel_row_count": len(panel_rows), "full_qc_hard_fail_count": len(panel_rows) - hard_pass_count,
            **evaluation,
            "input_hashes": {str(source.path): source.sha256 for source in all_sources},
            "prediction_receipt_sha256": prediction_sources["receipt"].sha256,
            "eligibility_receipt_sha256": eligibility_sources["receipt"].sha256,
            "label_receipt_sha256": label_sources["receipt"].sha256,
            "evaluator_implementation_sha256": implementation.sha256,
            "evaluator_preregistration_sha256": prereg.sha256,
            "runtime_trust": runtime_trust,
            "one_shot_lock": {"path": str(one_shot_lock.path), "sha256": one_shot_lock.sha256},
            "thresholds": THRESHOLDS,
            "label_access": {"prediction_gate_completed_before_label_receipt_open": True, "docking_labels_read_inside_one_shot_evaluator": True},
            "claim_boundary": CLAIM_BOUNDARY,
            "runtime_authority": (
                "Production output is authoritative only when invoked through the "
                "hash-frozen canonical launcher recorded by the independent deployment receipt; "
                "direct evaluator execution is non-authoritative."
            ),
        }
        write_json(summary_path, summary)
        write_tsv(parent_path, parent_rows, (
            "parent_framework_cluster", "analyzable_count", "contact_spearman", "contact_ndcg",
            "contact_top_quartile_recall_at_20pct_budget", "contact_mae", "shortcut_name",
            "contact_enrichment_factor_at_10pct",
            "shortcut_spearman", "contact_minus_shortcut_spearman_delta",
        ))
        verify_snapshots_unchanged(all_sources)
        receipt = {
            "schema_version": "phase2_v4_f96_one_shot_formal_evaluation_receipt_v1",
            "status": "PASS_FORMAL_EVALUATION_ARTIFACT_HASH_CLOSURE",
            "scientific_status": evaluation["status"],
            "execution_mode": "test_only" if config.test_only else "production",
            "one_shot": True,
            "outputs": {
                "summary": {"path": str((config.output_dir / OUTPUT_FILES[0]).resolve()), "sha256": sha256_bytes(summary_path.read_bytes())},
                "per_parent_metrics": {"path": str((config.output_dir / OUTPUT_FILES[1]).resolve()), "sha256": sha256_bytes(parent_path.read_bytes())},
            },
            "prediction_receipt_sha256": prediction_sources["receipt"].sha256,
            "eligibility_receipt_sha256": eligibility_sources["receipt"].sha256,
            "label_receipt_sha256": label_sources["receipt"].sha256,
            "evaluator_implementation_sha256": implementation.sha256,
            "evaluator_preregistration_sha256": prereg.sha256,
            "runtime_trust": runtime_trust,
            "one_shot_lock": {"path": str(one_shot_lock.path), "sha256": one_shot_lock.sha256},
            "publication": {"receipt_published_last": True, "rerun_under_same_version_forbidden": True},
            "claim_boundary": CLAIM_BOUNDARY,
            "runtime_authority": (
                "Canonical hash-frozen launcher plus deployment receipt required; "
                "direct evaluator execution is non-authoritative."
            ),
        }
        write_json(receipt_path, receipt)
        verify_snapshots_unchanged(all_sources)
        config.output_dir.mkdir(parents=True, exist_ok=True)
        for name in OUTPUT_FILES:
            os.replace(staging / name, config.output_dir / name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return summary


def parser() -> argparse.ArgumentParser:
    output = argparse.ArgumentParser(description=__doc__)
    output.add_argument("--manifest", type=Path, default=CANONICAL_MANIFEST)
    output.add_argument("--manifest-audit", type=Path, default=CANONICAL_MANIFEST_AUDIT)
    output.add_argument("--manifest-receipt", type=Path, default=CANONICAL_MANIFEST_RECEIPT)
    output.add_argument("--prediction-receipt", type=Path, default=CANONICAL_PREDICTION_RECEIPT)
    output.add_argument("--eligibility-receipt", type=Path, default=CANONICAL_ELIGIBILITY_RECEIPT)
    output.add_argument("--label-receipt", type=Path, default=CANONICAL_LABEL_RECEIPT)
    output.add_argument("--output-dir", type=Path, default=CANONICAL_OUTPUT_DIR)
    output.add_argument("--trust-anchor", type=Path, default=CANONICAL_TRUST_ANCHOR)
    output.add_argument("--test-only", action="store_true", help=argparse.SUPPRESS)
    output.add_argument("--bootstrap-replicates", type=int, default=BOOTSTRAP_REPLICATES, help=argparse.SUPPRESS)
    return output


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        summary = run_evaluation(EvaluationInputs(
            manifest=args.manifest, manifest_audit=args.manifest_audit,
            manifest_receipt=args.manifest_receipt, prediction_receipt=args.prediction_receipt,
            eligibility_receipt=args.eligibility_receipt, label_receipt=args.label_receipt,
            output_dir=args.output_dir, trust_anchor=args.trust_anchor,
            test_only=args.test_only,
            bootstrap_replicates=args.bootstrap_replicates,
        ))
    except FormalEvaluationError as exc:
        print(json.dumps({"status": "ERROR_FAIL_CLOSED", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": summary["status"], "output_dir": str(args.output_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
