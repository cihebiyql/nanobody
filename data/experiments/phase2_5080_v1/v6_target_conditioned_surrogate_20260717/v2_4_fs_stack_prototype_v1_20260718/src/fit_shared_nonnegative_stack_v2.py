#!/usr/bin/env python3
"""Fit the numerically gated V2.4 five-parameter shared-slope stack."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import lsq_linear


MODEL_VERSION = "pvrig_v2_4_five_parameter_shared_nonnegative_stack_v2"
FIT_ROLE = "INNER_OOF_BASE_FEATURE"
SCORE_ROLE = "OUTER_TEST_BASE_FEATURE"
FIXED_RIDGE_ALPHA = 1.0e-3
FIXED_CONDITION_NUMBER_CEILING = 1.0e6
FIXED_MINIMUM_FEATURE_SCALE = 1.0e-8
SCALING_CONTRACT = "weighted_shared_receptor_zscore_meta_train_only_v1"
PARAMETER_NAMES = (
    "intercept_R8",
    "intercept_R9",
    "beta_M2",
    "beta_neural",
    "beta_contact",
)
FEATURE_NAMES = ("M2", "neural", "contact")
REQUIRED_COLUMNS = (
    "evidence_role",
    "candidate_id",
    "teacher_source",
    "parent_framework_cluster",
    "outer_fold",
    "R_8X6B",
    "R_9E6Y",
    "M2_R8",
    "neural_R8",
    "contact_score_R8",
    "M2_R9",
    "neural_R9",
    "contact_score_R9",
)
_V4F_TOKEN = re.compile(r"(^|[/\\._-])v4[/\\._-]?f($|[/\\._-])", re.IGNORECASE)


class StackV2Error(ValueError):
    pass


@dataclass(frozen=True)
class ScalingStats:
    M2_mean: float
    M2_scale: float
    neural_mean: float
    neural_scale: float
    contact_mean: float
    contact_scale: float

    def means(self) -> np.ndarray:
        return np.asarray([self.M2_mean, self.neural_mean, self.contact_mean], dtype=np.float64)

    def scales(self) -> np.ndarray:
        return np.asarray([self.M2_scale, self.neural_scale, self.contact_scale], dtype=np.float64)


@dataclass(frozen=True)
class SharedStackV2Model:
    intercept_R8: float
    intercept_R9: float
    beta_M2: float
    beta_neural: float
    beta_contact: float
    scaling: ScalingStats

    @property
    def parameter_count(self) -> int:
        return 5

    def theta(self) -> np.ndarray:
        return np.asarray(
            [self.intercept_R8, self.intercept_R9, self.beta_M2, self.beta_neural, self.beta_contact],
            dtype=np.float64,
        )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_parent_set_sha256(parents: Sequence[str]) -> str:
    payload = "".join(f"{parent}\n" for parent in sorted(set(parents))).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_rows(rows: Sequence[Mapping[str, str]], expected_role: str) -> None:
    if not rows:
        raise StackV2Error("empty_rows")
    seen: set[str] = set()
    parent_source: dict[str, str] = {}
    for row_number, row in enumerate(rows, start=2):
        for column in REQUIRED_COLUMNS:
            if str(row.get(column, "")).strip() == "":
                raise StackV2Error(f"missing_value:row={row_number}:column={column}")
        if row["evidence_role"] != expected_role:
            raise StackV2Error(f"evidence_role_mismatch:row={row_number}")
        candidate = row["candidate_id"]
        if candidate in seen:
            raise StackV2Error(f"duplicate_candidate_id:{candidate}")
        seen.add(candidate)
        source = row["teacher_source"]
        parent = row["parent_framework_cluster"]
        if _V4F_TOKEN.search(source) or re.sub(r"[^a-z0-9]", "", source.lower()) == "v4f":
            raise StackV2Error(f"forbidden_v4f_source:{candidate}")
        previous = parent_source.setdefault(parent, source)
        if previous != source:
            raise StackV2Error(f"parent_in_multiple_sources:{parent}")
        for column in REQUIRED_COLUMNS[5:]:
            try:
                value = float(row[column])
            except ValueError as exc:
                raise StackV2Error(f"non_numeric:row={row_number}:column={column}") from exc
            if not math.isfinite(value):
                raise StackV2Error(f"non_finite:row={row_number}:column={column}")


def read_rows(path: Path, expected_role: str) -> list[dict[str, str]]:
    if _V4F_TOKEN.search(str(path.resolve())):
        raise StackV2Error(f"forbidden_v4f_input_path:{path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    validate_rows(rows, expected_role)
    return rows


def hierarchical_weights(rows: Sequence[Mapping[str, str]]) -> np.ndarray:
    sources = sorted({row["teacher_source"] for row in rows})
    if len(sources) != 2:
        raise StackV2Error(f"expected_two_sources:observed={len(sources)}")
    groups: dict[str, dict[str, list[int]]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(row["teacher_source"], {}).setdefault(row["parent_framework_cluster"], []).append(index)
    weights = np.zeros(len(rows), dtype=np.float64)
    for source in sources:
        parent_map = groups[source]
        for indices in parent_map.values():
            weights[indices] = 0.5 / len(parent_map) / len(indices)
    if not np.isclose(weights.sum(), 1.0, rtol=0.0, atol=1e-14):
        raise StackV2Error("hierarchical_weight_sum_not_one")
    return weights


def raw_receptor_arrays(
    rows: Sequence[Mapping[str, str]], candidate_weights: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    features = np.empty((2 * len(rows), 3), dtype=np.float64)
    receptor = np.empty(2 * len(rows), dtype=np.int8)
    target = np.empty(2 * len(rows), dtype=np.float64)
    weights = np.repeat(candidate_weights / 2.0, 2)
    for index, row in enumerate(rows):
        row8, row9 = 2 * index, 2 * index + 1
        features[row8] = [float(row["M2_R8"]), float(row["neural_R8"]), float(row["contact_score_R8"])]
        features[row9] = [float(row["M2_R9"]), float(row["neural_R9"]), float(row["contact_score_R9"])]
        receptor[row8], receptor[row9] = 0, 1
        target[row8], target[row9] = float(row["R_8X6B"]), float(row["R_9E6Y"])
    return features, receptor, target, weights


def fit_scaling(features: np.ndarray, weights: np.ndarray) -> ScalingStats:
    means = np.sum(weights[:, None] * features, axis=0) / weights.sum()
    variances = np.sum(weights[:, None] * (features - means) ** 2, axis=0) / weights.sum()
    scales = np.sqrt(variances)
    for name, scale in zip(FEATURE_NAMES, scales):
        if not math.isfinite(float(scale)) or scale < FIXED_MINIMUM_FEATURE_SCALE:
            raise StackV2Error(f"feature_scale_below_fixed_minimum:{name}:{scale}")
    return ScalingStats(
        M2_mean=float(means[0]), M2_scale=float(scales[0]),
        neural_mean=float(means[1]), neural_scale=float(scales[1]),
        contact_mean=float(means[2]), contact_scale=float(scales[2]),
    )


def scaled_design(
    features: np.ndarray, receptor: np.ndarray, scaling: ScalingStats
) -> np.ndarray:
    standardized = (features - scaling.means()) / scaling.scales()
    design = np.zeros((len(features), 5), dtype=np.float64)
    design[:, 0] = receptor == 0
    design[:, 1] = receptor == 1
    design[:, 2:] = standardized
    return design


def fit_stack_v2(
    rows: Sequence[Mapping[str, str]],
) -> tuple[SharedStackV2Model, dict[str, Any]]:
    validate_rows(rows, FIT_ROLE)
    candidate_weights = hierarchical_weights(rows)
    features, receptor, target, weights = raw_receptor_arrays(rows, candidate_weights)
    scaling = fit_scaling(features, weights)
    design = scaled_design(features, receptor, scaling)
    weighted_design = design * np.sqrt(weights)[:, None]
    weighted_target = target * np.sqrt(weights)
    condition_number = float(np.linalg.cond(weighted_design))
    if not math.isfinite(condition_number) or condition_number > FIXED_CONDITION_NUMBER_CEILING:
        raise StackV2Error(
            f"condition_number_above_fixed_ceiling:{condition_number}:"
            f"ceiling={FIXED_CONDITION_NUMBER_CEILING}"
        )

    ridge_design = np.zeros((3, 5), dtype=np.float64)
    ridge_design[:, 2:] = np.eye(3) * math.sqrt(FIXED_RIDGE_ALPHA)
    augmented_design = np.vstack([weighted_design, ridge_design])
    augmented_target = np.concatenate([weighted_target, np.zeros(3, dtype=np.float64)])
    result = lsq_linear(
        augmented_design,
        augmented_target,
        bounds=(
            np.asarray([-np.inf, -np.inf, 0.0, 0.0, 0.0]),
            np.asarray([np.inf, np.inf, np.inf, np.inf, np.inf]),
        ),
        method="trf", tol=1e-14, lsmr_tol=1e-14, max_iter=5000,
    )
    if not result.success:
        raise RuntimeError(f"bounded_ridge_fit_failed:{result.message}")
    theta = result.x.copy()
    theta[2:] = np.maximum(theta[2:], 0.0)
    model = SharedStackV2Model(*map(float, theta), scaling=scaling)
    return model, {
        "model_version": MODEL_VERSION,
        "parameter_count": model.parameter_count,
        "parameter_names": list(PARAMETER_NAMES),
        "scaling_contract": SCALING_CONTRACT,
        "scaling_stats": asdict(scaling),
        "fixed_ridge_alpha": FIXED_RIDGE_ALPHA,
        "regularized_parameters": ["beta_M2", "beta_neural", "beta_contact"],
        "fixed_condition_number_ceiling": FIXED_CONDITION_NUMBER_CEILING,
        "observed_condition_number": condition_number,
        "fixed_minimum_feature_scale": FIXED_MINIMUM_FEATURE_SCALE,
        "optimizer": "scipy.optimize.lsq_linear",
        "optimizer_cost": float(result.cost),
    }


def predict_stack_v2(
    model: SharedStackV2Model, rows: Sequence[Mapping[str, str]]
) -> list[dict[str, Any]]:
    validate_rows(rows, SCORE_ROLE)
    weights = np.full(len(rows), 1.0 / len(rows), dtype=np.float64)
    features, receptor, _, _ = raw_receptor_arrays(rows, weights)
    predictions = scaled_design(features, receptor, model.scaling) @ model.theta()
    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        pred8 = np.float64(predictions[2 * index])
        pred9 = np.float64(predictions[2 * index + 1])
        dual = np.minimum(pred8, pred9)
        output.append({
            "candidate_id": row["candidate_id"],
            "teacher_source": row["teacher_source"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "outer_fold": row["outer_fold"],
            "prediction_R8": float(pred8),
            "prediction_R9": float(pred9),
            "prediction_R_dual_min": float(dual),
        })
    return output


def run(args: argparse.Namespace) -> dict[str, Any]:
    fit_path = Path(args.fit_tsv).resolve()
    score_path = Path(args.score_tsv).resolve()
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise StackV2Error(f"nonempty_output_directory:{output_dir}")
    fit_rows = read_rows(fit_path, FIT_ROLE)
    score_rows = read_rows(score_path, SCORE_ROLE)
    model, audit = fit_stack_v2(fit_rows)
    predictions = predict_stack_v2(model, score_rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    fit_parents = sorted({row["parent_framework_cluster"] for row in fit_rows})
    fit_parent_digest = canonical_parent_set_sha256(fit_parents)
    model_path = output_dir / "model.json"
    model_path.write_text(json.dumps({
        "model_version": MODEL_VERSION,
        "parameter_count": 5,
        "parameters": {name: float(value) for name, value in zip(PARAMETER_NAMES, model.theta())},
        "scaling": asdict(model.scaling),
        "audit": audit,
        "fit_tsv_sha256": sha256_file(fit_path),
        "score_tsv_sha256": sha256_file(score_path),
        "fit_evidence_role": FIT_ROLE,
        "fit_parent_framework_clusters": fit_parents,
        "fit_parent_set_sha256": fit_parent_digest,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    prediction_path = output_dir / "outer_test_meta_predictions.tsv"
    columns = (
        "candidate_id", "teacher_source", "parent_framework_cluster", "outer_fold",
        "prediction_R8", "prediction_R9", "prediction_R_dual_min",
    )
    with prediction_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in predictions:
            serialized = dict(row)
            for column in ("prediction_R8", "prediction_R9", "prediction_R_dual_min"):
                serialized[column] = format(serialized[column], ".17g")
            writer.writerow(serialized)
    receipt = {
        "status": "PASS_NUMERICALLY_GATED_FIVE_PARAMETER_STACK",
        "model_json_sha256": sha256_file(model_path),
        "prediction_tsv_sha256": sha256_file(prediction_path),
        "prediction_count": len(predictions),
        "parameter_count": 5,
        "fixed_ridge_alpha": FIXED_RIDGE_ALPHA,
        "fixed_condition_number_ceiling": FIXED_CONDITION_NUMBER_CEILING,
        "scaling_contract": SCALING_CONTRACT,
        "fit_tsv_sha256": sha256_file(fit_path),
        "fit_parent_set_sha256": fit_parent_digest,
    }
    (output_dir / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-tsv", required=True)
    parser.add_argument("--score-tsv", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main() -> int:
    print(json.dumps(run(build_parser().parse_args()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
