#!/usr/bin/env python3
"""Fit a frozen four-modal OOF portfolio and evaluate only on open development."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import pickle
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import minimize
from scipy.stats import rankdata, spearmanr
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error


SCHEMA = "pvrig_v2_12_oof_early_enrichment_portfolio_v1"
CONTRACT_SCHEMA = "pvrig_v2_12_oof_early_enrichment_portfolio_contract_v1"
BASES = ("S0", "M2", "C2", "B")
LEGACY_COLUMNS = {
    "S0": "S0_MATCHED_ESM2_650M_PCA_ELASTICNET",
    "M2": "M2_STRUCTURE_ALPHA10",
    "C2": "C2_COARSE_POSE_PCA8",
}
CLAIM = (
    "Open-development computational dual-receptor Docking-geometry surrogate portfolio; "
    "not binding, affinity, experimental blocking, Docking Gold, sealed-test, or submission evidence."
)
FORBIDDEN_PATH_TOKENS = ("test32", "sealed_truth", "frozen_test", "frozen-test", "v4_f")


class PortfolioError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PortfolioError(message)


def reject_path(path: Path, role: str) -> None:
    normalized = str(path.resolve()).lower().replace("-", "_")
    for token in FORBIDDEN_PATH_TOKENS:
        require(token.replace("-", "_") not in normalized, f"forbidden_{role}_path:{token}")


def sha256_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"regular_file_required:{path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_hash(path: Path, expected: str, role: str) -> None:
    reject_path(path, role)
    require(len(expected) == 64 and sha256_file(path) == expected.lower(), f"{role}_sha256_mismatch")


def load_tsv(path: Path, role: str) -> tuple[list[str], list[dict[str, str]]]:
    reject_path(path, role)
    require(path.is_file() and not path.is_symlink(), f"{role}_invalid")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields, rows = list(reader.fieldnames or ()), [dict(row) for row in reader]
    require(fields and rows, f"{role}_empty")
    return fields, rows


def exact_min(values: np.ndarray) -> np.ndarray:
    require(values.ndim == 2 and values.shape[1] == 2, "two_receptor_shape")
    return np.minimum(values[:, 0], values[:, 1])


def matrix_by_candidate(
    rows: Sequence[Mapping[str, str]],
    prefix: str,
    r8_suffix: str = "__R8",
    r9_suffix: str = "__R9",
) -> dict[str, tuple[float, float]]:
    result: dict[str, tuple[float, float]] = {}
    for row in rows:
        candidate = row["candidate_id"]
        require(candidate not in result, f"duplicate_candidate:{candidate}")
        values = (float(row[f"{prefix}{r8_suffix}"]), float(row[f"{prefix}{r9_suffix}"]))
        require(all(math.isfinite(value) for value in values), f"nonfinite_prediction:{candidate}:{prefix}")
        result[candidate] = values
    return result


def load_inputs(
    teacher_path: Path,
    legacy_oof_path: Path,
    clean_oof_path: Path,
    legacy_dev_path: Path,
    clean_dev_path: Path,
) -> dict[str, Any]:
    teacher_fields, teacher = load_tsv(teacher_path, "teacher")
    require({"candidate_id", "sequence_sha256", "parent_framework_cluster", "teacher_source", "sample_weight", "R_8X6B", "R_9E6Y"} <= set(teacher_fields), "teacher_fields")
    require(len(teacher) == 9849, f"teacher_rows:{len(teacher)}")
    teacher_by = {row["candidate_id"]: row for row in teacher}
    require(len(teacher_by) == 9849, "teacher_duplicate")

    _, legacy_oof = load_tsv(legacy_oof_path, "legacy_oof")
    _, clean_oof = load_tsv(clean_oof_path, "clean_oof")
    require(len(legacy_oof) == len(clean_oof) == 9849, "oof_row_count")
    legacy_by = {row["candidate_id"]: row for row in legacy_oof}
    clean_by = {row["candidate_id"]: row for row in clean_oof}
    require(len(legacy_by) == len(clean_by) == 9849 and set(legacy_by) == set(clean_by) == set(teacher_by), "oof_candidate_closure")

    candidate_ids = [row["candidate_id"] for row in teacher]
    parents = [row["parent_framework_cluster"] for row in teacher]
    truth = np.asarray([[float(row["R_8X6B"]), float(row["R_9E6Y"])] for row in teacher], dtype=np.float64)
    bases: dict[str, np.ndarray] = {}
    for name, prefix in LEGACY_COLUMNS.items():
        values = matrix_by_candidate(legacy_oof, prefix)
        bases[name] = np.asarray([values[candidate] for candidate in candidate_ids], dtype=np.float64)
    clean_values = matrix_by_candidate(clean_oof, "B_CLEAN_TARGET_ATTENTION")
    bases["B"] = np.asarray([clean_values[candidate] for candidate in candidate_ids], dtype=np.float64)
    for candidate in candidate_ids:
        parent = teacher_by[candidate]["parent_framework_cluster"]
        require(legacy_by[candidate]["parent_framework_cluster"] == parent, f"legacy_parent:{candidate}")
        require(clean_by[candidate]["parent_framework_cluster"] == parent, f"clean_parent:{candidate}")
        reference = (float(teacher_by[candidate]["R_8X6B"]), float(teacher_by[candidate]["R_9E6Y"]))
        legacy_truth = (float(legacy_by[candidate]["truth_R8"]), float(legacy_by[candidate]["truth_R9"]))
        clean_truth = (float(clean_by[candidate]["truth_R8"]), float(clean_by[candidate]["truth_R9"]))
        require(max(abs(a-b) for a, b in zip(reference, legacy_truth)) <= 4e-8, f"legacy_truth:{candidate}")
        require(max(abs(a-b) for a, b in zip(reference, clean_truth)) <= 4e-8, f"clean_truth:{candidate}")

    _, legacy_dev = load_tsv(legacy_dev_path, "legacy_development")
    _, clean_dev = load_tsv(clean_dev_path, "clean_development")
    require(len(legacy_dev) == len(clean_dev) == 795, "development_row_count")
    legacy_dev_by = {row["candidate_id"]: row for row in legacy_dev}
    clean_dev_by = {row["candidate_id"]: row for row in clean_dev}
    require(len(legacy_dev_by) == len(clean_dev_by) == 795 and set(legacy_dev_by) == set(clean_dev_by), "development_candidate_closure")
    dev_ids = [row["candidate_id"] for row in legacy_dev]
    dev_parents = [row["parent_framework_cluster"] for row in legacy_dev]
    require(set(parents).isdisjoint(dev_parents), "train_development_parent_overlap")
    dev_truth = np.asarray([[float(row["truth_R8"]), float(row["truth_R9"])] for row in legacy_dev], dtype=np.float64)
    dev_bases: dict[str, np.ndarray] = {}
    for name, prefix in LEGACY_COLUMNS.items():
        values = matrix_by_candidate(legacy_dev, prefix)
        dev_bases[name] = np.asarray([values[candidate] for candidate in dev_ids], dtype=np.float64)
    clean_dev_values = matrix_by_candidate(clean_dev, "prediction", "_R_8X6B", "_R_9E6Y")
    dev_bases["B"] = np.asarray([clean_dev_values[candidate] for candidate in dev_ids], dtype=np.float64)
    for index, candidate in enumerate(dev_ids):
        clean = clean_dev_by[candidate]
        require(clean["parent_framework_cluster"] == dev_parents[index], f"clean_dev_parent:{candidate}")
        clean_truth = (float(clean["target_R_8X6B"]), float(clean["target_R_9E6Y"]))
        require(max(abs(a-b) for a, b in zip(clean_truth, dev_truth[index])) <= 4e-8, f"clean_dev_truth:{candidate}")

    weights = hierarchical_weights(teacher)
    return {
        "candidate_ids": candidate_ids, "parents": parents, "truth": truth, "bases": bases, "weights": weights,
        "dev_candidate_ids": dev_ids, "dev_parents": dev_parents, "dev_truth": dev_truth, "dev_bases": dev_bases,
    }


def hierarchical_weights(rows: Sequence[Mapping[str, str]]) -> np.ndarray:
    groups: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for index, row in enumerate(rows):
        groups[row["teacher_source"]][row["parent_framework_cluster"]].append(index)
    weights = np.zeros(len(rows), dtype=np.float64)
    for parents in groups.values():
        for indices in parents.values():
            for index in indices:
                weights[index] = 1.0 / len(groups) / len(parents) / len(indices)
    reliability = np.asarray([float(row["sample_weight"]) for row in rows], dtype=np.float64)
    require(np.isfinite(reliability).all() and np.all(reliability > 0), "sample_weight_invalid")
    weights *= reliability
    weights /= weights.mean()
    return weights


def fit_convex4(truth: np.ndarray, bases: Mapping[str, np.ndarray], weights: np.ndarray) -> dict[str, Any]:
    names = BASES
    stack = np.stack([bases[name] for name in names], axis=2)
    normalized = weights / weights.sum()

    def objective(beta: np.ndarray) -> float:
        error = np.einsum("nrb,b->nr", stack, beta) - truth
        return float(np.sum(normalized[:, None] * error * error) + 0.01 * beta @ beta)

    def gradient(beta: np.ndarray) -> np.ndarray:
        error = np.einsum("nrb,b->nr", stack, beta) - truth
        return 2 * np.einsum("n,nr,nrb->b", normalized, error, stack) + 0.02 * beta

    result = minimize(
        objective,
        np.full(4, 0.25),
        jac=gradient,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * 4,
        constraints=[{"type": "eq", "fun": lambda value: float(value.sum() - 1.0), "jac": lambda value: np.ones_like(value)}],
        options={"ftol": 1e-14, "maxiter": 2000},
    )
    require(bool(result.success), f"convex_fit:{result.message}")
    beta = np.maximum(result.x, 0.0)
    beta /= beta.sum()
    return {"names": names, "weights": beta, "l2": 0.01}


def predict_convex(model: Mapping[str, Any], bases: Mapping[str, np.ndarray]) -> np.ndarray:
    result = sum(float(weight) * bases[name] for name, weight in zip(model["names"], model["weights"]))
    require(result.shape[1] == 2 and np.isfinite(result).all(), "convex_prediction")
    return result


def fit_positive_ridge(truth: np.ndarray, bases: Mapping[str, np.ndarray], weights: np.ndarray) -> list[Ridge]:
    models = []
    for receptor in range(2):
        features = np.column_stack([bases[name][:, receptor] for name in BASES])
        model = Ridge(alpha=1.0, positive=True, solver="lbfgs")
        model.fit(features, truth[:, receptor], sample_weight=weights)
        models.append(model)
    return models


def predict_positive_ridge(models: Sequence[Ridge], bases: Mapping[str, np.ndarray]) -> np.ndarray:
    result = np.column_stack([
        model.predict(np.column_stack([bases[name][:, receptor] for name in BASES]))
        for receptor, model in enumerate(models)
    ])
    require(np.isfinite(result).all(), "ridge_prediction")
    return result


def percentile_scores(bases: Mapping[str, np.ndarray]) -> np.ndarray:
    values = []
    for name in BASES:
        dual = exact_min(bases[name])
        values.append((rankdata(dual, method="average") - 1.0) / max(1, len(dual) - 1))
    return np.column_stack(values)


def classifier_features(bases: Mapping[str, np.ndarray]) -> np.ndarray:
    scores = percentile_scores(bases)
    dual = np.column_stack([exact_min(bases[name]) for name in BASES])
    gap = np.column_stack([np.abs(bases[name][:, 0] - bases[name][:, 1]) for name in BASES])
    result = np.column_stack([dual, gap, scores, dual.mean(1), dual.std(1), scores.mean(1), scores.min(1)])
    require(result.shape[1] == 16 and np.isfinite(result).all(), "classifier_feature_shape")
    return result


def fit_classifier(truth: np.ndarray, bases: Mapping[str, np.ndarray], weights: np.ndarray) -> HistGradientBoostingClassifier:
    dual = exact_min(truth)
    threshold = np.sort(dual)[-max(1, math.ceil(len(dual) * 0.10))]
    labels = (dual >= threshold).astype(np.int64)
    positive = labels.sum()
    balanced = weights.copy()
    balanced[labels == 1] *= len(labels) / (2.0 * positive)
    balanced[labels == 0] *= len(labels) / (2.0 * (len(labels) - positive))
    model = HistGradientBoostingClassifier(
        max_depth=2,
        max_iter=64,
        learning_rate=0.05,
        min_samples_leaf=128,
        l2_regularization=5.0,
        random_state=43,
    )
    model.fit(classifier_features(bases), labels, sample_weight=balanced)
    model.training_threshold_ = float(threshold)
    return model


def ranked(candidate_ids: Sequence[str], values: np.ndarray) -> list[int]:
    return sorted(range(len(values)), key=lambda index: (-float(values[index]), candidate_ids[index]))


def enrichment(candidate_ids: Sequence[str], truth: np.ndarray, score: np.ndarray) -> list[dict[str, Any]]:
    result = []
    truth_order, score_order = ranked(candidate_ids, truth), ranked(candidate_ids, score)
    for truth_fraction in (0.10, 0.20):
        positives = max(1, math.ceil(len(truth) * truth_fraction))
        truth_set = set(truth_order[:positives])
        prevalence = positives / len(truth)
        for budget in (0.05, 0.10, 0.20):
            selected = max(1, math.ceil(len(truth) * budget))
            hits = len(truth_set & set(score_order[:selected]))
            precision = hits / selected
            result.append({
                "true_top_fraction": truth_fraction,
                "predicted_budget_fraction": budget,
                "selected": selected,
                "hits": hits,
                "precision": precision,
                "recall": hits / positives,
                "enrichment_factor": precision / prevalence,
            })
    return result


def ranking_metrics(candidate_ids: Sequence[str], parents: Sequence[str], truth: np.ndarray, score: np.ndarray) -> dict[str, Any]:
    dual = exact_min(truth)
    statistic = spearmanr(dual, score).statistic
    by_parent: dict[str, list[int]] = defaultdict(list)
    for index, parent in enumerate(parents):
        by_parent[parent].append(index)
    recalls = []
    for indices in by_parent.values():
        count = max(1, math.ceil(len(indices) * 0.20))
        true_top = set(sorted(indices, key=lambda index: (-dual[index], candidate_ids[index]))[:count])
        predicted_top = set(sorted(indices, key=lambda index: (-score[index], candidate_ids[index]))[:count])
        recalls.append(len(true_top & predicted_top) / count)
    return {
        "spearman": float(statistic) if np.isfinite(statistic) else 0.0,
        "early_enrichment": enrichment(candidate_ids, dual, score),
        "within_parent_top20_macro_recall": float(np.mean(recalls)),
    }


def continuous_metrics(candidate_ids: Sequence[str], parents: Sequence[str], truth: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    dual_truth, dual_prediction = exact_min(truth), exact_min(prediction)
    result = ranking_metrics(candidate_ids, parents, truth, dual_prediction)
    result.update({
        "R8_mae": float(mean_absolute_error(truth[:, 0], prediction[:, 0])),
        "R9_mae": float(mean_absolute_error(truth[:, 1], prediction[:, 1])),
        "Rdual_mae": float(mean_absolute_error(dual_truth, dual_prediction)),
        "Rdual_rmse": float(mean_squared_error(dual_truth, dual_prediction) ** 0.5),
        "exact_min_violation_count": 0,
    })
    return result


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> dict[str, Any]:
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    require(contract.get("schema_version") == CONTRACT_SCHEMA and contract.get("status") == "FROZEN_BEFORE_CLEAN_OOF_UNSEAL", "contract_invalid")
    require(not args.output_dir.exists(), "output_exists")
    paths = (args.teacher, args.legacy_oof, args.clean_oof, args.legacy_development, args.clean_development)
    expected = (args.teacher_sha256, args.legacy_oof_sha256, args.clean_oof_sha256, args.legacy_development_sha256, args.clean_development_sha256)
    for path, digest, role in zip(paths, expected, ("teacher", "legacy_oof", "clean_oof", "legacy_dev", "clean_dev")):
        verify_hash(path, digest, role)
    data = load_inputs(*paths)
    convex = fit_convex4(data["truth"], data["bases"], data["weights"])
    ridge = fit_positive_ridge(data["truth"], data["bases"], data["weights"])
    classifier = fit_classifier(data["truth"], data["bases"], data["weights"])
    dev_continuous = {
        "CONVEX4_L2_0P01": predict_convex(convex, data["dev_bases"]),
        "POSITIVE_RIDGE4_ALPHA1": predict_positive_ridge(ridge, data["dev_bases"]),
    }
    dev_percentiles = percentile_scores(data["dev_bases"])
    dev_rank_scores = {
        "RANK_PERCENTILE_MEAN4": dev_percentiles.mean(1),
        "RANK_PERCENTILE_MIN4": dev_percentiles.min(1),
        "HGB_TOP10_CHALLENGER": classifier.predict_proba(classifier_features(data["dev_bases"]))[:, 1],
    }
    base_metrics = {name: continuous_metrics(data["dev_candidate_ids"], data["dev_parents"], data["dev_truth"], values) for name, values in data["dev_bases"].items()}
    continuous_results = {name: continuous_metrics(data["dev_candidate_ids"], data["dev_parents"], data["dev_truth"], values) for name, values in dev_continuous.items()}
    ranking_results = {name: ranking_metrics(data["dev_candidate_ids"], data["dev_parents"], data["dev_truth"], values) for name, values in dev_rank_scores.items()}
    args.output_dir.mkdir(parents=True)
    prediction_rows = []
    for index, candidate in enumerate(data["dev_candidate_ids"]):
        row: dict[str, Any] = {
            "candidate_id": candidate,
            "parent_framework_cluster": data["dev_parents"][index],
            "truth_R8": data["dev_truth"][index, 0],
            "truth_R9": data["dev_truth"][index, 1],
            "truth_Rdual_exact_min": exact_min(data["dev_truth"])[index],
        }
        for name, values in data["dev_bases"].items():
            row[f"{name}__R8"] = values[index, 0]
            row[f"{name}__R9"] = values[index, 1]
            row[f"{name}__Rdual_exact_min"] = min(values[index])
        for name, values in dev_continuous.items():
            row[f"{name}__R8"] = values[index, 0]
            row[f"{name}__R9"] = values[index, 1]
            row[f"{name}__Rdual_exact_min"] = min(values[index])
        for name, values in dev_rank_scores.items():
            row[f"{name}__frontscreen_score"] = values[index]
        prediction_rows.append(row)
    write_tsv(args.output_dir / "OPEN_DEVELOPMENT_PORTFOLIO_PREDICTIONS.tsv", prediction_rows)
    metrics = {
        "schema_version": SCHEMA,
        "status": "PASS_OPEN_DEVELOPMENT_PORTFOLIO_COMPLETE",
        "claim_boundary": CLAIM,
        "counts": {"fit_oof_rows": 9849, "development_rows": 795, "fit_parents": len(set(data["parents"])), "development_parents": len(set(data["dev_parents"]))},
        "fit": {
            "convex_weights": {name: float(weight) for name, weight in zip(convex["names"], convex["weights"])},
            "positive_ridge_coefficients": {f"R{8 if receptor == 0 else 9}": {name: float(value) for name, value in zip(BASES, model.coef_)} for receptor, model in enumerate(ridge)},
            "classifier_training_threshold": float(classifier.training_threshold_),
            "development_used_for_fit_or_selection": False,
            "meta_train_performance_reported_as_oof": False,
        },
        "open_development": {"bases": base_metrics, "continuous_heads": continuous_results, "ranking_heads": ranking_results},
        "inputs": {role: {"path": str(path), "sha256": sha256_file(path)} for role, path in zip(("teacher", "legacy_oof", "clean_oof", "legacy_dev", "clean_dev"), paths)},
        "frozen_test_access_count": 0,
        "sealed_truth_access_count": 0,
    }
    metrics_path = args.output_dir / "METRICS.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    with (args.output_dir / "MODEL_ARTIFACT.pkl").open("wb") as handle:
        pickle.dump({"schema_version": SCHEMA, "convex": convex, "ridge": ridge, "classifier": classifier, "base_order": BASES}, handle, protocol=pickle.HIGHEST_PROTOCOL)
    receipt = {
        "schema_version": SCHEMA,
        "status": metrics["status"],
        "development_used_for_fit_or_selection": False,
        "frozen_test_access_count": 0,
        "claim_boundary": CLAIM,
    }
    (args.output_dir / "RUN_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    hashes = {path.name: sha256_file(path) for path in args.output_dir.iterdir() if path.is_file() and path.name != "SHA256SUMS"}
    (args.output_dir / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())), encoding="utf-8")
    return {"status": metrics["status"], "output_dir": str(args.output_dir), "convex_weights": metrics["fit"]["convex_weights"]}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--contract", type=Path, required=True)
    for name in ("teacher", "legacy-oof", "clean-oof", "legacy-development", "clean-development"):
        value.add_argument(f"--{name}", type=Path, required=True)
        value.add_argument(f"--{name}-sha256", required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    result = run(parser().parse_args(argv))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
