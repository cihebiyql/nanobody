#!/usr/bin/env python3
"""Evaluate frozen three-seed V3-P1 predictions without pre-evaluator label joins.

The evaluator is the first component allowed to join model predictions to the
frozen Teacher500 labels. Baseline selection is performed on development
parent clusters only, then applied unchanged to the formal test clusters.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from phase2_v3_p1_metrics import (  # noqa: E402
    geometry_metrics,
    ordinal_ranking_metrics,
    paired_parent_cluster_bootstrap,
    paired_parent_cluster_permutation,
)

EXPECTED_SEEDS = (83, 89, 97)
TIER_TO_RELEVANCE = {"G1": 4, "G2": 3, "G3": 2, "G4": 1, "G5": 0}
GEOMETRY_FIELDS = (
    "median_hotspot_overlap_8x6b",
    "median_hotspot_overlap_9e6y",
    "median_total_occlusion_8x6b",
    "median_total_occlusion_9e6y",
    "median_cdr3_occlusion_8x6b",
    "median_cdr3_occlusion_9e6y",
    "topk_a_or_b_fraction",
    "teacher_relevance_mean",
)
REQUIRED_CONTROL_TYPES = (
    "label_shuffle",
    "hotspot_shuffle",
    "antigen_ablation",
    "target_permutation",
    "vhh_only",
)
FORBIDDEN_PREDICTION_COLUMNS = {
    "label",
    "labels",
    "tier",
    "true_tier",
    "true_relevance",
    "teacher_relevance_mean",
    "teacher_relevance_median",
    "teacher_relevance_max",
    "provisional_stable_geometry_tier",
    "best_evidence_tier",
}
CLAIM_BOUNDARY = "pvrig_docking_geometry_surrogate_not_binding_or_experimental_blocking_truth"


@dataclass(frozen=True)
class GateThresholds:
    recall_at_20: float = 0.70
    enrichment_at_10: float = 3.0
    relevance_spearman: float = 0.35
    target_control_ef_drop: float = 0.25


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_seed_paths(values: Sequence[str]) -> dict[int, Path]:
    parsed: dict[int, Path] = {}
    for value in values:
        try:
            seed_text, path_text = value.split("=", 1)
            seed = int(seed_text)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Expected SEED=PATH, received {value!r}") from error
        if seed in parsed:
            raise ValueError(f"Duplicate prediction path for seed {seed}")
        parsed[seed] = Path(path_text)
    if set(parsed) != set(EXPECTED_SEEDS):
        raise ValueError(f"Seeds must be exactly {EXPECTED_SEEDS}, found {tuple(sorted(parsed))}")
    return parsed


def _assert_prediction_blind(frame: pd.DataFrame, source: str) -> None:
    forbidden = {
        column
        for column in frame.columns
        if column.lower() in FORBIDDEN_PREDICTION_COLUMNS or column.lower().startswith("true_")
    }
    if forbidden:
        raise ValueError(f"{source} contains pre-evaluator label columns: {sorted(forbidden)}")


def _prepare_teacher(teacher: pd.DataFrame) -> pd.DataFrame:
    required = {
        "candidate_id",
        "sequence_sha256",
        "formal_split",
        "parent_framework_cluster",
        "provisional_stable_geometry_tier",
        *GEOMETRY_FIELDS,
    }
    missing = required - set(teacher.columns)
    if missing:
        raise ValueError(f"Teacher file lacks required columns: {sorted(missing)}")
    teacher = teacher.loc[teacher["formal_split"].astype(str).isin(["dev", "test"])].copy()
    teacher["candidate_id"] = teacher["candidate_id"].astype(str)
    teacher["sequence_sha256"] = teacher["sequence_sha256"].astype(str)
    teacher["formal_split"] = teacher["formal_split"].astype(str)
    teacher["parent_framework_cluster"] = teacher["parent_framework_cluster"].astype(str)
    if teacher.empty or teacher["candidate_id"].duplicated().any():
        raise ValueError("Teacher dev/test candidate IDs must be non-empty and unique")
    if teacher["sequence_sha256"].str.fullmatch(r"[0-9a-fA-F]{64}").ne(True).any():
        raise ValueError("Teacher sequence_sha256 values must be 64 hexadecimal characters")
    if set(teacher["formal_split"].astype(str)) != {"dev", "test"}:
        raise ValueError("Teacher evaluation table must contain both dev and test splits")
    cluster_splits = teacher.groupby("parent_framework_cluster")["formal_split"].nunique()
    if int(cluster_splits.max()) != 1:
        raise ValueError("A parent framework cluster occurs in more than one formal split")
    tiers = teacher["provisional_stable_geometry_tier"].astype(str)
    unknown = sorted(set(tiers) - set(TIER_TO_RELEVANCE))
    if unknown:
        raise ValueError(f"Unknown geometry tiers: {unknown}")
    teacher["true_tier"] = tiers
    teacher["true_relevance"] = tiers.map(TIER_TO_RELEVANCE).astype(int)
    for field in GEOMETRY_FIELDS:
        teacher[field] = pd.to_numeric(teacher[field], errors="raise")
        if not np.isfinite(teacher[field].to_numpy(dtype=float)).all():
            raise ValueError(f"Teacher geometry field {field} is not finite")
    return teacher


def load_teacher_parts(open_path: Path, sealed_test_path: Path) -> pd.DataFrame:
    """Open dev labels and unseal formal test labels only inside evaluation."""
    development = pd.read_csv(open_path)
    sealed = pd.read_csv(sealed_test_path)
    if "formal_split" not in development or set(development["formal_split"].astype(str)) - {
        "train",
        "dev",
    }:
        raise ValueError("Open teacher labels must contain only train/dev rows")
    if "formal_split" not in sealed or set(sealed["formal_split"].astype(str)) != {"test"}:
        raise ValueError("Sealed formal labels must contain test rows only")
    if "sealed_status" not in sealed:
        raise ValueError("Sealed formal labels lack required sealed_status")
    if not sealed["sealed_status"].astype(str).eq("SEALED_FORMAL_TEST_LABEL").all():
        raise ValueError("Formal test label rows do not carry the required sealed status")
    development = development.loc[development["formal_split"].astype(str).eq("dev")].copy()
    if development.empty:
        raise ValueError("Open teacher labels contain no development rows")
    return _prepare_teacher(pd.concat([development, sealed], ignore_index=True, sort=False))


def _validate_identity_columns(prediction: pd.DataFrame, teacher: pd.DataFrame, source: str) -> None:
    for column in ("sequence_sha256", "formal_split", "parent_framework_cluster"):
        if column not in prediction:
            raise ValueError(f"{source} lacks frozen identity column {column}")
        expected = teacher[["candidate_id", column]].merge(
            prediction[["candidate_id", column]],
            on="candidate_id",
            how="inner",
            suffixes=("_teacher", "_prediction"),
            validate="one_to_many",
        )
        mismatch = expected[f"{column}_teacher"].astype(str) != expected[f"{column}_prediction"].astype(str)
        if mismatch.any():
            raise ValueError(f"{source} disagrees with frozen teacher {column}")


def merge_three_seed_predictions(
    teacher: pd.DataFrame, seed_paths: Mapping[int, Path]
) -> tuple[pd.DataFrame, dict[str, str]]:
    if set(seed_paths) != set(EXPECTED_SEEDS):
        raise ValueError(f"Prediction seeds must be exactly {EXPECTED_SEEDS}")
    test = teacher.loc[teacher["formal_split"].eq("test")].copy()
    base_columns = [
        "candidate_id",
        "sequence_sha256",
        "formal_split",
        "parent_framework_cluster",
        "true_tier",
        "true_relevance",
        *GEOMETRY_FIELDS,
    ]
    merged = test[base_columns].copy()
    expected_ids = set(test["candidate_id"].astype(str))
    hashes: dict[str, str] = {}
    for seed in EXPECTED_SEEDS:
        path = Path(seed_paths[seed])
        prediction = pd.read_csv(path)
        _assert_prediction_blind(prediction, f"seed {seed}")
        required = {
            "candidate_id",
            "sequence_sha256",
            "formal_split",
            "parent_framework_cluster",
            "predicted_relevance",
        } | {
            f"predicted_{field}" for field in GEOMETRY_FIELDS
        }
        missing = required - set(prediction.columns)
        if missing:
            raise ValueError(f"Seed {seed} lacks required prediction columns: {sorted(missing)}")
        prediction["candidate_id"] = prediction["candidate_id"].astype(str)
        if prediction["candidate_id"].duplicated().any():
            raise ValueError(f"Seed {seed} candidate IDs are duplicated")
        if "formal_split" in prediction:
            prediction = prediction.loc[prediction["formal_split"].astype(str).eq("test")].copy()
        ids = set(prediction["candidate_id"].astype(str))
        if ids != expected_ids:
            raise ValueError(
                f"Seed {seed} test candidate set differs: "
                f"missing={len(expected_ids - ids)}, extra={len(ids - expected_ids)}"
            )
        _validate_identity_columns(prediction, test, f"seed {seed}")
        keep = ["candidate_id", "predicted_relevance", *[f"predicted_{field}" for field in GEOMETRY_FIELDS]]
        renamed = {column: f"{column}_seed_{seed}" for column in keep if column != "candidate_id"}
        prediction = prediction[keep].rename(columns=renamed)
        for column in renamed.values():
            prediction[column] = pd.to_numeric(prediction[column], errors="raise")
            if not np.isfinite(prediction[column].to_numpy(dtype=float)).all():
                raise ValueError(f"Seed {seed} has non-finite values in {column}")
        merged = merged.merge(prediction, on="candidate_id", how="left", validate="one_to_one")
        hashes[f"seed_{seed}"] = sha256_file(path)

    relevance_columns = [f"predicted_relevance_seed_{seed}" for seed in EXPECTED_SEEDS]
    merged["ensemble_predicted_relevance"] = merged[relevance_columns].mean(axis=1)
    merged["ensemble_relevance_seed_std"] = merged[relevance_columns].std(axis=1, ddof=0)
    merged["ensemble_relevance_seed_range"] = merged[relevance_columns].max(axis=1) - merged[
        relevance_columns
    ].min(axis=1)
    for field in GEOMETRY_FIELDS:
        columns = [f"predicted_{field}_seed_{seed}" for seed in EXPECTED_SEEDS]
        merged[f"ensemble_predicted_{field}"] = merged[columns].mean(axis=1)
        merged[f"ensemble_predicted_{field}_seed_std"] = merged[columns].std(axis=1, ddof=0)
    return merged.sort_values("candidate_id").reset_index(drop=True), hashes


def select_strongest_baseline(
    teacher: pd.DataFrame, baseline_path: Path
) -> tuple[str, pd.DataFrame, dict[str, Any]]:
    baseline = pd.read_csv(baseline_path)
    _assert_prediction_blind(baseline, "baseline predictions")
    baseline_required = {
        "candidate_id",
        "sequence_sha256",
        "formal_split",
        "parent_framework_cluster",
    }
    if baseline_required - set(baseline):
        raise ValueError(f"Baseline file lacks identity columns: {sorted(baseline_required - set(baseline))}")
    baseline["candidate_id"] = baseline["candidate_id"].astype(str)
    if baseline["candidate_id"].duplicated().any():
        raise ValueError("Baseline candidate IDs must be present and unique")
    score_columns = sorted(column for column in baseline if column.startswith("baseline_"))
    if not score_columns:
        raise ValueError("Baseline file must contain at least one baseline_* score column")
    expected_ids = set(teacher["candidate_id"].astype(str))
    if set(baseline["candidate_id"].astype(str)) != expected_ids:
        raise ValueError("Baseline file must exactly cover frozen teacher dev/test candidates")
    _validate_identity_columns(baseline, teacher, "baseline predictions")
    for column in score_columns:
        baseline[column] = pd.to_numeric(baseline[column], errors="raise")
        if not np.isfinite(baseline[column].to_numpy(dtype=float)).all():
            raise ValueError(f"Baseline {column} contains non-finite scores")
    joined = teacher[["candidate_id", "formal_split", "true_relevance"]].merge(
        baseline[["candidate_id", *score_columns]], on="candidate_id", validate="one_to_one"
    )
    dev = joined.loc[joined["formal_split"].eq("dev")]
    dev_metrics = {
        column: ordinal_ranking_metrics(dev["true_relevance"], dev[column]) for column in score_columns
    }
    selected = max(
        score_columns,
        key=lambda column: (
            float(dev_metrics[column]["ordinal_ndcg_at_100"]),
            float(dev_metrics[column]["relevance_spearman"]),
            column,
        ),
    )
    return selected, baseline[["candidate_id", selected]], {
        "selection_split": "dev",
        "selection_metric": "ordinal_ndcg_at_100_then_relevance_spearman",
        "selected_baseline": selected,
        "candidate_baselines": score_columns,
        "dev_metrics": dev_metrics,
        "sha256": sha256_file(baseline_path),
    }


def load_controls(
    control_path: Path, test_teacher: pd.DataFrame
) -> tuple[dict[str, pd.DataFrame], str]:
    controls = pd.read_csv(control_path)
    _assert_prediction_blind(controls, "control predictions")
    required = {
        "candidate_id",
        "sequence_sha256",
        "formal_split",
        "parent_framework_cluster",
        "seed",
        "control_type",
        "predicted_relevance",
    }
    missing = required - set(controls.columns)
    if missing:
        raise ValueError(f"Control predictions lack columns: {sorted(missing)}")
    controls["seed"] = pd.to_numeric(controls["seed"], errors="raise").astype(int)
    controls["candidate_id"] = controls["candidate_id"].astype(str)
    controls["control_type"] = controls["control_type"].astype(str)
    if set(controls["control_type"]) != set(REQUIRED_CONTROL_TYPES):
        raise ValueError(
            f"Controls must be exactly {REQUIRED_CONTROL_TYPES}, found {tuple(sorted(set(controls['control_type'])))}"
        )
    expected_ids = set(test_teacher["candidate_id"].astype(str))
    output: dict[str, pd.DataFrame] = {}
    for control_type in REQUIRED_CONTROL_TYPES:
        block = controls.loc[controls["control_type"].eq(control_type)].copy()
        if set(block["seed"]) != set(EXPECTED_SEEDS):
            raise ValueError(f"{control_type} seeds must be exactly {EXPECTED_SEEDS}")
        if block.duplicated(["candidate_id", "seed"]).any():
            raise ValueError(f"{control_type} has duplicate candidate/seed rows")
        if set(block["candidate_id"].astype(str)) != expected_ids:
            raise ValueError(f"{control_type} does not exactly cover the formal test candidates")
        _validate_identity_columns(block, test_teacher, control_type)
        pivot = block.pivot(index="candidate_id", columns="seed", values="predicted_relevance")
        pivot = pivot.loc[sorted(expected_ids), list(EXPECTED_SEEDS)]
        pivot = pivot.apply(pd.to_numeric, errors="raise")
        if not np.isfinite(pivot.to_numpy(dtype=float)).all():
            raise ValueError(f"{control_type} contains non-finite scores")
        result = pivot.reset_index()
        result.columns = ["candidate_id", *[f"control_score_seed_{seed}" for seed in EXPECTED_SEEDS]]
        result["control_ensemble_score"] = result[
            [f"control_score_seed_{seed}" for seed in EXPECTED_SEEDS]
        ].mean(axis=1)
        output[control_type] = result
    return output, sha256_file(control_path)


def load_generic_replay_retention(
    path: Path, minimum_fraction: float = 0.90
) -> tuple[dict[str, Any], dict[str, bool]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    per_seed = payload.get("per_seed")
    if not isinstance(per_seed, dict) or {int(seed) for seed in per_seed} != set(EXPECTED_SEEDS):
        raise ValueError(f"Generic replay retention must contain exactly seeds {EXPECTED_SEEDS}")
    checks: dict[str, bool] = {}
    normalized: dict[str, dict[str, float]] = {}
    for seed in EXPECTED_SEEDS:
        record = per_seed[str(seed)] if str(seed) in per_seed else per_seed[seed]
        if not isinstance(record, dict):
            raise ValueError(f"Generic replay seed {seed} is not a metric object")
        normalized[str(seed)] = {}
        for metric in ("contact_auprc_retention_fraction", "paratope_auprc_retention_fraction"):
            value = float(record[metric])
            if not np.isfinite(value) or value < 0.0:
                raise ValueError(f"Invalid generic replay {metric} for seed {seed}")
            normalized[str(seed)][metric] = value
            checks[f"generic_replay_seed_{seed}_{metric}_ge_{minimum_fraction:g}"] = (
                value >= minimum_fraction
            )
    return {
        "schema_version": payload.get("schema_version", ""),
        "minimum_retention_fraction": minimum_fraction,
        "per_seed": normalized,
        "sha256": sha256_file(path),
    }, checks


def _top_fraction_seed_agreement(frame: pd.DataFrame, fraction: float = 0.20) -> dict[str, Any]:
    count = max(1, int(np.ceil(len(frame) * fraction)))
    top_sets = {
        str(seed): set(
            frame.nlargest(count, f"predicted_relevance_seed_{seed}")["candidate_id"].astype(str)
        )
        for seed in EXPECTED_SEEDS
    }
    intersection = set.intersection(*top_sets.values())
    union = set.union(*top_sets.values())
    return {
        "fraction": fraction,
        "per_seed_top_count": count,
        "three_seed_intersection_count": len(intersection),
        "three_seed_union_count": len(union),
        "three_seed_jaccard": float(len(intersection) / len(union)) if union else 1.0,
    }


def _screen_checks(metrics: Mapping[str, Any], threshold: GateThresholds) -> dict[str, bool]:
    return {
        "g1_g2_recall_at_20_ge_threshold": float(metrics["g1_g2_recall_at_20_percent"]) >= threshold.recall_at_20,
        "g1_g2_ef_at_10_ge_threshold": float(metrics["g1_g2_ef_at_10_percent"]) >= threshold.enrichment_at_10,
        "relevance_spearman_ge_threshold": float(metrics["relevance_spearman"]) >= threshold.relevance_spearman,
    }


def evaluate_formal(
    teacher_open_path: Path,
    teacher_test_sealed_path: Path,
    seed_paths: Mapping[int, Path],
    baseline_path: Path,
    control_path: Path,
    generic_replay_path: Path,
    output_dir: Path,
    bootstrap_replicates: int = 2000,
    permutation_replicates: int = 2000,
    threshold: GateThresholds = GateThresholds(),
) -> dict[str, Any]:
    teacher = load_teacher_parts(teacher_open_path, teacher_test_sealed_path)
    teacher_hashes = {
        "teacher_open_development": sha256_file(teacher_open_path),
        "teacher_formal_labels_sealed": sha256_file(teacher_test_sealed_path),
    }
    predictions, seed_hashes = merge_three_seed_predictions(teacher, seed_paths)
    selected_baseline, baseline_scores, baseline_selection = select_strongest_baseline(
        teacher, baseline_path
    )
    predictions = predictions.merge(
        baseline_scores.rename(columns={selected_baseline: "strongest_baseline_score"}),
        on="candidate_id",
        how="left",
        validate="one_to_one",
    )
    if predictions["strongest_baseline_score"].isna().any():
        raise ValueError("Selected baseline does not cover formal test candidates")
    controls, control_hash = load_controls(
        control_path, teacher.loc[teacher["formal_split"].eq("test")]
    )
    generic_replay, generic_replay_checks = load_generic_replay_retention(generic_replay_path)

    relevance = predictions["true_relevance"].to_numpy(dtype=float)
    clusters = predictions["parent_framework_cluster"].astype(str).tolist()
    ensemble = predictions["ensemble_predicted_relevance"].to_numpy(dtype=float)
    baseline = predictions["strongest_baseline_score"].to_numpy(dtype=float)
    ensemble_metrics = ordinal_ranking_metrics(relevance, ensemble)
    baseline_metrics = ordinal_ranking_metrics(relevance, baseline)
    seed_metrics = {
        str(seed): ordinal_ranking_metrics(
            relevance, predictions[f"predicted_relevance_seed_{seed}"].to_numpy(dtype=float)
        )
        for seed in EXPECTED_SEEDS
    }
    true_geometry = {field: predictions[field].to_numpy(dtype=float) for field in GEOMETRY_FIELDS}
    predicted_geometry = {
        field: predictions[f"ensemble_predicted_{field}"].to_numpy(dtype=float)
        for field in GEOMETRY_FIELDS
    }
    geometry = geometry_metrics(true_geometry, predicted_geometry)
    bootstrap = paired_parent_cluster_bootstrap(
        relevance,
        ensemble,
        baseline,
        clusters,
        replicates=bootstrap_replicates,
        seed=20260713,
    )
    permutation = paired_parent_cluster_permutation(
        relevance,
        ensemble,
        baseline,
        clusters,
        replicates=permutation_replicates,
        seed=20260714,
    )

    control_results: dict[str, Any] = {}
    control_checks: dict[str, bool] = {}
    candidate_ef = float(ensemble_metrics["g1_g2_ef_at_10_percent"])
    for control_type, control_scores in controls.items():
        joined = predictions[["candidate_id"]].merge(
            control_scores, on="candidate_id", validate="one_to_one"
        )
        metrics = ordinal_ranking_metrics(relevance, joined["control_ensemble_score"])
        passes_screen = all(_screen_checks(metrics, threshold).values())
        relative_ef_drop = float(
            (candidate_ef - float(metrics["g1_g2_ef_at_10_percent"]))
            / max(abs(candidate_ef), 1e-12)
        )
        candidate_ndcg_exceeds = float(ensemble_metrics["ordinal_ndcg_at_100"]) > float(
            metrics["ordinal_ndcg_at_100"]
        )
        if control_type == "label_shuffle":
            passed = (not passes_screen) and candidate_ndcg_exceeds
        else:
            passed = candidate_ndcg_exceeds and relative_ef_drop >= threshold.target_control_ef_drop
        control_checks[f"{control_type}_rejected"] = passed
        control_results[control_type] = {
            "metrics": metrics,
            "passes_primary_screen_thresholds": passes_screen,
            "candidate_minus_control_ndcg": float(ensemble_metrics["ordinal_ndcg_at_100"])
            - float(metrics["ordinal_ndcg_at_100"]),
            "candidate_relative_ef_drop": relative_ef_drop,
            "rejected_as_null_or_target_independent": passed,
        }

    primary_checks = _screen_checks(ensemble_metrics, threshold)
    primary_checks.update(
        {
            "ensemble_ndcg_exceeds_strongest_dev_selected_baseline": float(
                ensemble_metrics["ordinal_ndcg_at_100"]
            )
            > float(baseline_metrics["ordinal_ndcg_at_100"]),
            "all_three_seeds_ndcg_exceed_strongest_baseline": all(
                float(metrics["ordinal_ndcg_at_100"])
                > float(baseline_metrics["ordinal_ndcg_at_100"])
                for metrics in seed_metrics.values()
            ),
            "parent_cluster_bootstrap_ci_lower_gt_zero": float(bootstrap["ci95_lower"]) > 0.0,
            "paired_cluster_permutation_p_lt_0_05": float(permutation["two_sided_p_value"])
            < 0.05,
            **generic_replay_checks,
            **control_checks,
        }
    )
    uncertainty = {
        "mean_candidate_seed_std": float(predictions["ensemble_relevance_seed_std"].mean()),
        "median_candidate_seed_std": float(predictions["ensemble_relevance_seed_std"].median()),
        "max_candidate_seed_std": float(predictions["ensemble_relevance_seed_std"].max()),
        "top_20_percent_agreement": _top_fraction_seed_agreement(predictions),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(output_dir / "formal_test_predictions_with_teacher_labels.csv", index=False)
    result: dict[str, Any] = {
        "status": "PASS_V3_P1_FORMAL_SURROGATE_GATE"
        if all(primary_checks.values())
        else "FAIL_V3_P1_FORMAL_SURROGATE_GATE",
        "schema_version": "phase2_v3_p1_formal_evaluation_v1",
        "expected_seeds": list(EXPECTED_SEEDS),
        "teacher_rows": int(len(teacher)),
        "formal_test_rows": int(len(predictions)),
        "formal_test_parent_clusters": int(predictions["parent_framework_cluster"].nunique()),
        "strongest_baseline_selection": baseline_selection,
        "ensemble_metrics": ensemble_metrics,
        "per_seed_metrics": seed_metrics,
        "strongest_baseline_test_metrics": baseline_metrics,
        "geometry_metrics": geometry,
        "ensemble_uncertainty": uncertainty,
        "parent_cluster_bootstrap": bootstrap,
        "paired_parent_cluster_permutation": permutation,
        "control_results": control_results,
        "generic_replay_retention": generic_replay,
        "thresholds": {
            "g1_g2_recall_at_20": threshold.recall_at_20,
            "g1_g2_ef_at_10": threshold.enrichment_at_10,
            "relevance_spearman": threshold.relevance_spearman,
            "target_control_relative_ef_drop": threshold.target_control_ef_drop,
        },
        "checks": primary_checks,
        "all_checks_pass": all(primary_checks.values()),
        "test_label_join_boundary": "inside_this_evaluator_only",
        "teacher_join_mode": "open_dev_plus_evaluator_only_unsealed_test",
        "input_prediction_artifacts_label_blind": True,
        "artifact_sha256": {
            **teacher_hashes,
            "baseline_predictions": baseline_selection["sha256"],
            "control_predictions": control_hash,
            "generic_replay_retention": generic_replay["sha256"],
            **seed_hashes,
        },
        "known_limitations": [
            "Teacher labels are docking-derived geometry surrogates, not experimental binding or blocking truth.",
            "9E6Y labels rescore 8X6B-generated poses unless a later teacher version adds independent docking.",
            "With six formal test parent clusters, bootstrap and permutation inference has limited power.",
        ],
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json_atomic(output_dir / "formal_evaluation.json", result)
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher-open", type=Path, required=True)
    parser.add_argument("--teacher-test-sealed", type=Path, required=True)
    parser.add_argument(
        "--seed-prediction",
        action="append",
        required=True,
        help="Exactly three entries in SEED=PATH form for seeds 83, 89, and 97.",
    )
    parser.add_argument("--baseline-predictions", type=Path, required=True)
    parser.add_argument("--control-predictions", type=Path, required=True)
    parser.add_argument("--generic-replay-retention", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=2000)
    parser.add_argument("--permutation-replicates", type=int, default=2000)
    parser.add_argument("--recall-at-20-threshold", type=float, default=0.70)
    parser.add_argument("--ef-at-10-threshold", type=float, default=3.0)
    parser.add_argument("--relevance-spearman-threshold", type=float, default=0.35)
    parser.add_argument("--target-control-ef-drop", type=float, default=0.25)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    result = evaluate_formal(
        teacher_open_path=args.teacher_open,
        teacher_test_sealed_path=args.teacher_test_sealed,
        seed_paths=parse_seed_paths(args.seed_prediction),
        baseline_path=args.baseline_predictions,
        control_path=args.control_predictions,
        generic_replay_path=args.generic_replay_retention,
        output_dir=args.output_dir,
        bootstrap_replicates=args.bootstrap_replicates,
        permutation_replicates=args.permutation_replicates,
        threshold=GateThresholds(
            recall_at_20=args.recall_at_20_threshold,
            enrichment_at_10=args.ef_at_10_threshold,
            relevance_spearman=args.relevance_spearman_threshold,
            target_control_ef_drop=args.target_control_ef_drop,
        ),
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
