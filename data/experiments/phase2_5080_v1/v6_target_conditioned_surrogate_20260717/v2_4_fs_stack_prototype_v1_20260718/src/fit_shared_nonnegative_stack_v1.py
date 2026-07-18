#!/usr/bin/env python3
"""Fit the preregistration candidate V2.4 five-parameter FS stack.

The model is intentionally small and receptor explicit::

    pred_R8 = intercept_R8 + beta_M2*M2_R8
                              + beta_neural*neural_R8
                              + beta_contact*contact_R8
    pred_R9 = intercept_R9 + beta_M2*M2_R9
                              + beta_neural*neural_R9
                              + beta_contact*contact_R9

The three shared slopes are constrained to be non-negative.  R_dual is always
computed as the exact minimum of the two receptor predictions.  This module is
a prototype implementation and does not convert docking geometry into an
experimental binding/blocking claim.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from scipy.optimize import lsq_linear


SCHEMA_VERSION = "pvrig_v2_4_fs_stack_input_v1"
PROVENANCE_SCHEMA_VERSION = "pvrig_v2_4_fs_stack_fold_provenance_v1"
MODEL_VERSION = "pvrig_v2_4_five_parameter_shared_nonnegative_stack_v1"
CLAIM_BOUNDARY = (
    "Computational surrogate of independent 8X6B/9E6Y docking geometry only; "
    "not a binding probability, Kd estimate, experimental blocker label, or "
    "Docking Gold label."
)

REQUIRED_COLUMNS = (
    "candidate_id",
    "teacher_source",
    "parent_framework_cluster",
    "outer_fold",
    "R_8X6B",
    "R_9E6Y",
    "M2_R8",
    "M2_R9",
    "neural_R8",
    "neural_R9",
    "contact_score_R8",
    "contact_score_R9",
    "feature_outer_fold",
    "base_training_parent_set_sha256",
    "base_model_receipt_sha256",
)

NUMERIC_COLUMNS = (
    "R_8X6B",
    "R_9E6Y",
    "M2_R8",
    "M2_R9",
    "neural_R8",
    "neural_R9",
    "contact_score_R8",
    "contact_score_R9",
)

PARAMETER_NAMES = (
    "intercept_R8",
    "intercept_R9",
    "beta_M2",
    "beta_neural",
    "beta_contact",
)


class StackValidationError(ValueError):
    """Raised when input or provenance violates the frozen prototype contract."""


@dataclass(frozen=True)
class SharedStackModel:
    intercept_R8: float
    intercept_R9: float
    beta_M2: float
    beta_neural: float
    beta_contact: float

    @property
    def parameter_count(self) -> int:
        return 5

    def as_vector(self) -> np.ndarray:
        return np.asarray(
            [
                self.intercept_R8,
                self.intercept_R9,
                self.beta_M2,
                self.beta_neural,
                self.beta_contact,
            ],
            dtype=np.float64,
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_parent_set_sha256(parents: Iterable[str]) -> str:
    values = sorted(set(parents))
    payload = "".join(f"{value}\n" for value in values).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise StackValidationError(f"missing_header:{path}")
        rows = list(reader)
    validate_input_rows(rows, fieldnames=reader.fieldnames)
    return rows


def validate_input_rows(
    rows: Sequence[Mapping[str, str]], *, fieldnames: Sequence[str] | None = None
) -> None:
    if not rows:
        raise StackValidationError("empty_input")
    observed = set(fieldnames if fieldnames is not None else rows[0].keys())
    missing = [column for column in REQUIRED_COLUMNS if column not in observed]
    if missing:
        raise StackValidationError("missing_required_columns:" + ",".join(missing))

    candidate_ids: set[str] = set()
    parent_sources: dict[str, str] = {}
    for index, row in enumerate(rows, start=1):
        for column in REQUIRED_COLUMNS:
            if column not in row or str(row[column]).strip() == "":
                raise StackValidationError(f"blank_required_value:row={index}:column={column}")
        candidate_id = str(row["candidate_id"])
        if candidate_id in candidate_ids:
            raise StackValidationError(f"duplicate_candidate_id:{candidate_id}")
        candidate_ids.add(candidate_id)

        parent = str(row["parent_framework_cluster"])
        source = str(row["teacher_source"])
        previous_source = parent_sources.setdefault(parent, source)
        if previous_source != source:
            raise StackValidationError(
                f"parent_in_multiple_sources:{parent}:{previous_source}:{source}"
            )

        for column in NUMERIC_COLUMNS:
            try:
                value = float(row[column])
            except (TypeError, ValueError) as exc:
                raise StackValidationError(
                    f"non_numeric_value:row={index}:column={column}"
                ) from exc
            if not math.isfinite(value):
                raise StackValidationError(
                    f"non_finite_value:row={index}:column={column}"
                )

        for column in (
            "base_training_parent_set_sha256",
            "base_model_receipt_sha256",
        ):
            if not _is_sha256(str(row[column])):
                raise StackValidationError(
                    f"invalid_sha256:row={index}:column={column}"
                )


def compute_source_parent_candidate_weights(
    rows: Sequence[Mapping[str, str]],
) -> tuple[np.ndarray, dict[str, Any]]:
    """Return frozen 0.5/source -> equal parent -> equal candidate weights."""
    validate_input_rows(rows)
    sources = sorted({str(row["teacher_source"]) for row in rows})
    if len(sources) != 2:
        raise StackValidationError(
            f"expected_exactly_two_teacher_sources:observed={len(sources)}"
        )

    source_to_parents: dict[str, dict[str, list[int]]] = {}
    for index, row in enumerate(rows):
        source = str(row["teacher_source"])
        parent = str(row["parent_framework_cluster"])
        source_to_parents.setdefault(source, {}).setdefault(parent, []).append(index)

    weights = np.zeros(len(rows), dtype=np.float64)
    source_audit: dict[str, Any] = {}
    for source in sources:
        parent_map = source_to_parents[source]
        parent_mass = 0.5 / len(parent_map)
        parent_audit: dict[str, Any] = {}
        for parent in sorted(parent_map):
            indices = parent_map[parent]
            candidate_weight = parent_mass / len(indices)
            weights[indices] = candidate_weight
            parent_audit[parent] = {
                "candidate_count": len(indices),
                "candidate_weight": candidate_weight,
                "mass": float(weights[indices].sum()),
            }
        source_audit[source] = {
            "parent_count": len(parent_map),
            "mass": float(
                sum(parent_info["mass"] for parent_info in parent_audit.values())
            ),
            "parents": parent_audit,
        }

    if not np.isclose(weights.sum(), 1.0, rtol=0.0, atol=1e-14):
        raise StackValidationError(f"weight_sum_not_one:{weights.sum():.17g}")
    for source in sources:
        if not np.isclose(source_audit[source]["mass"], 0.5, rtol=0.0, atol=1e-14):
            raise StackValidationError(f"source_mass_not_half:{source}")

    return weights, {
        "contract": "0.5/source -> equal parent within source -> equal candidate within parent",
        "candidate_weight_sum": float(weights.sum()),
        "sources": source_audit,
    }


def _float(row: Mapping[str, str], column: str) -> float:
    return float(row[column])


def build_receptor_design(
    rows: Sequence[Mapping[str, str]], candidate_weights: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if len(rows) != len(candidate_weights):
        raise StackValidationError("row_weight_length_mismatch")
    design = np.empty((2 * len(rows), 5), dtype=np.float64)
    target = np.empty(2 * len(rows), dtype=np.float64)
    receptor_weights = np.repeat(candidate_weights / 2.0, 2)

    for index, row in enumerate(rows):
        row8 = 2 * index
        row9 = row8 + 1
        design[row8] = [
            1.0,
            0.0,
            _float(row, "M2_R8"),
            _float(row, "neural_R8"),
            _float(row, "contact_score_R8"),
        ]
        design[row9] = [
            0.0,
            1.0,
            _float(row, "M2_R9"),
            _float(row, "neural_R9"),
            _float(row, "contact_score_R9"),
        ]
        target[row8] = _float(row, "R_8X6B")
        target[row9] = _float(row, "R_9E6Y")

    return design, target, receptor_weights


def fit_shared_nonnegative_stack(
    rows: Sequence[Mapping[str, str]],
) -> tuple[SharedStackModel, dict[str, Any]]:
    candidate_weights, weight_audit = compute_source_parent_candidate_weights(rows)
    design, target, receptor_weights = build_receptor_design(rows, candidate_weights)
    weighted_design = design * np.sqrt(receptor_weights)[:, None]
    weighted_target = target * np.sqrt(receptor_weights)

    rank = int(np.linalg.matrix_rank(weighted_design))
    if rank != 5:
        raise StackValidationError(f"rank_deficient_design:rank={rank}:expected=5")

    result = lsq_linear(
        weighted_design,
        weighted_target,
        bounds=(
            np.asarray([-np.inf, -np.inf, 0.0, 0.0, 0.0]),
            np.asarray([np.inf, np.inf, np.inf, np.inf, np.inf]),
        ),
        method="trf",
        tol=1e-14,
        lsmr_tol=1e-14,
        max_iter=5000,
        verbose=0,
    )
    if not result.success:
        raise RuntimeError(f"bounded_least_squares_failed:{result.message}")
    theta = result.x.astype(np.float64, copy=True)
    theta[2:] = np.maximum(theta[2:], 0.0)
    model = SharedStackModel(*map(float, theta))
    if model.parameter_count != 5 or len(model.as_vector()) != 5:
        raise AssertionError("five_parameter_contract_broken")

    prediction = design @ model.as_vector()
    residual = prediction - target
    fit_audit = {
        "model_version": MODEL_VERSION,
        "parameter_count": 5,
        "parameter_names": list(PARAMETER_NAMES),
        "shared_nonnegative_slopes": ["beta_M2", "beta_neural", "beta_contact"],
        "design_rank": rank,
        "optimizer": "scipy.optimize.lsq_linear",
        "optimizer_status": int(result.status),
        "optimizer_message": result.message,
        "optimizer_iterations": int(result.nit),
        "weighted_cost": float(result.cost),
        "weighted_receptor_mae": float(
            np.sum(receptor_weights * np.abs(residual)) / receptor_weights.sum()
        ),
        "weight_audit": weight_audit,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    return model, fit_audit


def predict_shared_stack(
    model: SharedStackModel, rows: Sequence[Mapping[str, str]]
) -> list[dict[str, Any]]:
    validate_input_rows(rows)
    output: list[dict[str, Any]] = []
    for row in rows:
        pred8 = np.float64(
            model.intercept_R8
            + model.beta_M2 * _float(row, "M2_R8")
            + model.beta_neural * _float(row, "neural_R8")
            + model.beta_contact * _float(row, "contact_score_R8")
        )
        pred9 = np.float64(
            model.intercept_R9
            + model.beta_M2 * _float(row, "M2_R9")
            + model.beta_neural * _float(row, "neural_R9")
            + model.beta_contact * _float(row, "contact_score_R9")
        )
        dual = np.minimum(pred8, pred9)
        if dual.tobytes() != np.minimum(pred8, pred9).tobytes():
            raise AssertionError("R_dual_not_exact_minimum")
        output.append(
            {
                "candidate_id": row["candidate_id"],
                "teacher_source": row["teacher_source"],
                "parent_framework_cluster": row["parent_framework_cluster"],
                "outer_fold": row["outer_fold"],
                "R_8X6B": _float(row, "R_8X6B"),
                "R_9E6Y": _float(row, "R_9E6Y"),
                "R_dual_min": float(
                    np.minimum(_float(row, "R_8X6B"), _float(row, "R_9E6Y"))
                ),
                "prediction_R8": float(pred8),
                "prediction_R9": float(pred9),
                "prediction_R_dual_min": float(dual),
                "feature_outer_fold": row["feature_outer_fold"],
                "base_training_parent_set_sha256": row[
                    "base_training_parent_set_sha256"
                ],
                "base_model_receipt_sha256": row["base_model_receipt_sha256"],
            }
        )
    return output


def load_provenance(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != PROVENANCE_SCHEMA_VERSION:
        raise StackValidationError("provenance_schema_version_mismatch")
    if not isinstance(data.get("feature_receipts"), dict):
        raise StackValidationError("missing_feature_receipts")
    if not isinstance(data.get("stack_outer_folds"), dict):
        raise StackValidationError("missing_stack_outer_folds")
    return data


def _validate_parent_list_digest(block: Mapping[str, Any], list_key: str, digest_key: str) -> set[str]:
    parents_raw = block.get(list_key)
    if not isinstance(parents_raw, list) or not parents_raw:
        raise StackValidationError(f"missing_or_empty_parent_list:{list_key}")
    parents = {str(value) for value in parents_raw}
    if len(parents) != len(parents_raw):
        raise StackValidationError(f"duplicate_parent_in_list:{list_key}")
    observed_digest = str(block.get(digest_key, ""))
    expected_digest = canonical_parent_set_sha256(parents)
    if observed_digest != expected_digest:
        raise StackValidationError(
            f"parent_set_digest_mismatch:{digest_key}:expected={expected_digest}:observed={observed_digest}"
        )
    return parents


def validate_fold_provenance(
    fit_rows: Sequence[Mapping[str, str]],
    score_rows: Sequence[Mapping[str, str]],
    provenance: Mapping[str, Any],
    outer_fold: str,
) -> dict[str, Any]:
    validate_input_rows(fit_rows)
    validate_input_rows(score_rows)
    fold_block = provenance["stack_outer_folds"].get(str(outer_fold))
    if not isinstance(fold_block, dict):
        raise StackValidationError(f"missing_stack_outer_fold:{outer_fold}")

    meta_train_parents = _validate_parent_list_digest(
        fold_block,
        "meta_training_parent_framework_clusters",
        "meta_training_parent_set_sha256",
    )
    score_parents = _validate_parent_list_digest(
        fold_block,
        "score_parent_framework_clusters",
        "score_parent_set_sha256",
    )
    overlap = meta_train_parents & score_parents
    if overlap:
        raise StackValidationError(
            "meta_train_score_parent_overlap:" + ",".join(sorted(overlap))
        )

    fit_observed = {str(row["parent_framework_cluster"]) for row in fit_rows}
    score_observed = {str(row["parent_framework_cluster"]) for row in score_rows}
    if fit_observed != meta_train_parents:
        raise StackValidationError("fit_parent_set_not_equal_manifest")
    if score_observed != score_parents:
        raise StackValidationError("score_parent_set_not_equal_manifest")
    for row in fit_rows:
        if str(row["outer_fold"]) == str(outer_fold):
            raise StackValidationError(
                f"fit_row_uses_held_out_outer_fold:{row['candidate_id']}:{outer_fold}"
            )
    for row in score_rows:
        if str(row["outer_fold"]) != str(outer_fold):
            raise StackValidationError(
                f"score_row_outer_fold_mismatch:{row['candidate_id']}:{row['outer_fold']}:{outer_fold}"
            )

    receipts = provenance["feature_receipts"]
    for role, rows in (("fit", fit_rows), ("score", score_rows)):
        for row in rows:
            receipt_sha = str(row["base_model_receipt_sha256"])
            receipt = receipts.get(receipt_sha)
            if not isinstance(receipt, dict):
                raise StackValidationError(
                    f"unknown_base_model_receipt:{role}:{row['candidate_id']}:{receipt_sha}"
                )
            if str(receipt.get("feature_outer_fold")) != str(row["feature_outer_fold"]):
                raise StackValidationError(
                    f"feature_fold_mismatch:{role}:{row['candidate_id']}"
                )
            training_parents = _validate_parent_list_digest(
                receipt,
                "training_parent_framework_clusters",
                "training_parent_set_sha256",
            )
            if str(row["base_training_parent_set_sha256"]) != str(
                receipt["training_parent_set_sha256"]
            ):
                raise StackValidationError(
                    f"row_training_parent_digest_mismatch:{role}:{row['candidate_id']}"
                )
            parent = str(row["parent_framework_cluster"])
            if parent in training_parents:
                raise StackValidationError(
                    f"base_feature_parent_leakage:{role}:{row['candidate_id']}:{parent}"
                )

    return {
        "outer_fold": str(outer_fold),
        "meta_training_parent_count": len(meta_train_parents),
        "score_parent_count": len(score_parents),
        "fit_candidate_count": len(fit_rows),
        "score_candidate_count": len(score_rows),
        "feature_receipt_count": len(
            {
                str(row["base_model_receipt_sha256"])
                for row in [*fit_rows, *score_rows]
            }
        ),
        "status": "PASS_NO_PARENT_LEAKAGE",
    }


def _format_float(value: Any) -> str:
    return format(float(value), ".17g")


def write_predictions(path: Path, predictions: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = [
        "candidate_id",
        "teacher_source",
        "parent_framework_cluster",
        "outer_fold",
        "R_8X6B",
        "R_9E6Y",
        "R_dual_min",
        "prediction_R8",
        "prediction_R9",
        "prediction_R_dual_min",
        "feature_outer_fold",
        "base_training_parent_set_sha256",
        "base_model_receipt_sha256",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in predictions:
            serialized = dict(row)
            for column in (
                "R_8X6B",
                "R_9E6Y",
                "R_dual_min",
                "prediction_R8",
                "prediction_R9",
                "prediction_R_dual_min",
            ):
                serialized[column] = _format_float(serialized[column])
            writer.writerow(serialized)


def run(args: argparse.Namespace) -> dict[str, Any]:
    fit_path = Path(args.fit_tsv).resolve()
    score_path = Path(args.score_tsv).resolve()
    provenance_path = Path(args.provenance_json).resolve()
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise StackValidationError(f"nonempty_output_directory:{output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    fit_rows = read_tsv(fit_path)
    score_rows = read_tsv(score_path)
    provenance = load_provenance(provenance_path)
    provenance_audit = validate_fold_provenance(
        fit_rows, score_rows, provenance, str(args.outer_fold)
    )
    model, fit_audit = fit_shared_nonnegative_stack(fit_rows)
    predictions = predict_shared_stack(model, score_rows)

    predictions_path = output_dir / "outer_test_predictions.tsv"
    write_predictions(predictions_path, predictions)
    model_payload = {
        "schema_version": "pvrig_v2_4_fs_stack_model_v1",
        "model_version": MODEL_VERSION,
        "parameter_count": 5,
        "parameters": asdict(model),
        "input_artifacts": {
            "fit_tsv": {"path": str(fit_path), "sha256": sha256_file(fit_path)},
            "score_tsv": {"path": str(score_path), "sha256": sha256_file(score_path)},
            "provenance_json": {
                "path": str(provenance_path),
                "sha256": sha256_file(provenance_path),
            },
        },
        "fold_provenance_audit": provenance_audit,
        "fit_audit": fit_audit,
        "prediction_contract": "R_dual_min = exact min(prediction_R8, prediction_R9)",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    model_path = output_dir / "model.json"
    model_path.write_text(
        json.dumps(model_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    receipt = {
        "status": "PASS_PROTOTYPE_STACK_FIT",
        "model_json_sha256": sha256_file(model_path),
        "outer_test_predictions_sha256": sha256_file(predictions_path),
        "outer_fold": str(args.outer_fold),
        "prediction_count": len(predictions),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    receipt_path = output_dir / "receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-tsv", required=True)
    parser.add_argument("--score-tsv", required=True)
    parser.add_argument("--provenance-json", required=True)
    parser.add_argument("--outer-fold", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    receipt = run(args)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
