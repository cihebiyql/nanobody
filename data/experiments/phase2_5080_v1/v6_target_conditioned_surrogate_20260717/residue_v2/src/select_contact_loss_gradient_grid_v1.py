#!/usr/bin/env python3
"""Select the frozen Residue V2 contact-loss weights from open-only gradients.

The selector reads exactly one pre-optimizer, one-batch gradient observation
from each of the four lane RESULT.json files.  It never reads prediction
metrics and never runs an optimizer.  It emits an amendment only when the
smallest frozen grid entry places every lane in the 5%-20% direct-contact
gradient band without exceeding the 30% hard ceiling.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


LANES = ("A_DOMAIN", "B_VHH3D", "C_PATCH", "D_FULL_PAIR")
SOURCES = ("V4D_OPEN_MULTI_SEED", "V4H_STAGE1_SEED917")
GRID = (
    (0.0025, 0.00125),
    (0.005, 0.0025),
    (0.01, 0.005),
    (0.02, 0.01),
)
TARGET_MIN = 0.05
TARGET_MAX = 0.20
HARD_MAX = 0.30
AMENDMENT_SCHEMA = "pvrig_v6_residue_v2_contact_loss_amendment_v1"
AMENDMENT_STATUS = "FROZEN_BEFORE_ANY_FORMAL_RESIDUE_V2_TRAINING"
NORMALIZATION = "per_candidate_per_receptor_soft_positive_negative_balanced_then_equal_source"
OBSERVATION_SCHEMA = "pvrig_v6_residue_v2_contact_gradient_observation_v1"
CALIBRATION_SCHEMA = "pvrig_v6_residue_v2_contact_gradient_calibration_v1"
CALIBRATION_STATUS = "PASS_OPEN_ONLY_ONE_BATCH_PRESTEP_GRADIENT_CALIBRATION"
SELECTION_RULE = "smallest_grid_entry_with_all_lanes_in_target_band_and_no_lane_above_hard_ceiling"
NONCONTACT_WEIGHTS = {"dual": 1.0, "receptor": 0.35, "ranking": 0.0001, "residual": 0.05}


class CalibrationError(RuntimeError):
    """Fail-closed open-only gradient calibration error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CalibrationError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def parse_lane_results(values: Sequence[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        lane, separator, raw_path = value.partition("=")
        require(bool(separator) and lane in LANES and bool(raw_path), f"lane_result_syntax:{value}")
        require(lane not in parsed, f"lane_result_duplicate:{lane}")
        parsed[lane] = Path(raw_path)
    require(set(parsed) == set(LANES), "lane_result_closure")
    return parsed


def load_observation(lane: str, path: Path) -> tuple[dict[str, Any], str]:
    require(path.is_file() and not path.is_symlink(), f"lane_result_missing_or_symlink:{lane}")
    result_hash = sha256_file(path)
    payload = json.loads(path.read_text())
    require(isinstance(payload, Mapping), f"lane_result_not_object:{lane}")
    require(payload.get("lane") == lane, f"lane_result_lane_mismatch:{lane}")
    observation = payload.get("contact_gradient_calibration_observation")
    require(isinstance(observation, Mapping), f"gradient_observation_missing:{lane}")
    required = {
        "schema_version", "lane", "gradient_batch_index", "gradient_batches_in_observation",
        "optimizer_steps_before_observation", "candidate_ids_sha256", "candidate_count",
        "teacher_source_counts", "unweighted_gradient_l2_norm", "component_weights",
        "weighted_gradient_l2_norm", "weighted_gradient_fraction",
        "direct_contact_gradient_fraction", "open_only", "v4_f_test32_access_count",
        "prediction_metrics_access_count", "outer_fold", "inner_fold", "training_stage",
    }
    require(set(observation) == required, f"gradient_observation_field_closure:{lane}")
    require(observation.get("schema_version") == OBSERVATION_SCHEMA, f"gradient_observation_schema:{lane}")
    require(observation.get("lane") == lane, f"gradient_observation_lane:{lane}")
    require(int(observation.get("gradient_batch_index", -1)) == 0, f"gradient_observation_not_first_batch:{lane}")
    require(int(observation.get("gradient_batches_in_observation", -1)) == 1, f"gradient_observation_batch_count:{lane}")
    require(int(observation.get("optimizer_steps_before_observation", -1)) == 0, f"gradient_observation_post_optimizer:{lane}")
    require(observation.get("training_stage") == "first_inner_selection_epoch0_first_batch", f"gradient_observation_stage:{lane}")
    require(observation.get("open_only") is True, f"gradient_observation_not_open_only:{lane}")
    require(int(observation.get("v4_f_test32_access_count", -1)) == 0, f"gradient_observation_v4f_access:{lane}")
    require(int(observation.get("prediction_metrics_access_count", -1)) == 0, f"gradient_observation_prediction_metric_access:{lane}")
    source_counts = observation.get("teacher_source_counts")
    require(isinstance(source_counts, Mapping) and set(source_counts) == set(SOURCES), f"gradient_observation_source_closure:{lane}")
    require({source: int(source_counts[source]) for source in SOURCES} == {SOURCES[0]: 2, SOURCES[1]: 6}, f"gradient_observation_source_quota:{lane}")
    require(int(observation.get("candidate_count", -1)) == 8, f"gradient_observation_candidate_count:{lane}")
    candidate_hash = observation.get("candidate_ids_sha256")
    require(isinstance(candidate_hash, str) and len(candidate_hash) == 64, f"gradient_observation_candidate_hash:{lane}")
    raw = observation.get("unweighted_gradient_l2_norm")
    weights = observation.get("component_weights")
    expected_components = set(NONCONTACT_WEIGHTS) | {"marginal"} | ({"pair"} if lane == "D_FULL_PAIR" else set())
    require(isinstance(raw, Mapping) and set(raw) == expected_components, f"gradient_observation_raw_component_closure:{lane}")
    require(isinstance(weights, Mapping) and set(weights) == expected_components, f"gradient_observation_weight_component_closure:{lane}")
    require(all(math.isfinite(float(raw[name])) and float(raw[name]) >= 0.0 for name in expected_components), f"gradient_observation_raw_norm:{lane}")
    for name, expected in NONCONTACT_WEIGHTS.items():
        require(float(weights[name]) == expected, f"gradient_observation_noncontact_weight:{lane}:{name}")
    return dict(observation), result_hash


def direct_contact_fraction(lane: str, raw: Mapping[str, Any], marginal_weight: float, pair_weight: float) -> float:
    weights = dict(NONCONTACT_WEIGHTS)
    weights["marginal"] = marginal_weight
    if lane == "D_FULL_PAIR":
        weights["pair"] = pair_weight
    weighted = {name: abs(float(weights[name])) * float(raw[name]) for name in weights}
    denominator = sum(weighted.values())
    require(denominator > 0.0 and math.isfinite(denominator), f"gradient_denominator_invalid:{lane}")
    numerator = weighted["marginal"] + (weighted.get("pair") or 0.0)
    return numerator / denominator


def build_calibration(observations: Mapping[str, Mapping[str, Any]], input_hashes: Mapping[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    grid_results: list[dict[str, Any]] = []
    passing: list[int] = []
    for index, (marginal, pair) in enumerate(GRID):
        fractions = {
            lane: direct_contact_fraction(
                lane, observations[lane]["unweighted_gradient_l2_norm"], marginal, pair,
            )
            for lane in LANES
        }
        target_pass = all(TARGET_MIN <= fraction <= TARGET_MAX for fraction in fractions.values())
        hard_pass = all(fraction <= HARD_MAX for fraction in fractions.values())
        grid_results.append({
            "grid_index": index,
            "marginal_contact_weight": marginal,
            "pair_contact_weight": pair,
            "lane_direct_contact_gradient_fractions": fractions,
            "all_lanes_in_target_band": target_pass,
            "hard_ceiling_pass": hard_pass,
        })
        if target_pass and hard_pass:
            passing.append(index)
    require(bool(passing), "no_grid_entry_places_all_lanes_in_target_band")
    selected = passing[0]
    marginal, pair = GRID[selected]
    calibration = {
        "schema_version": CALIBRATION_SCHEMA,
        "status": CALIBRATION_STATUS,
        "grid": [
            {"marginal_contact_weight": grid_marginal, "pair_contact_weight": grid_pair}
            for grid_marginal, grid_pair in GRID
        ],
        "selection_rule": SELECTION_RULE,
        "target_fraction_min": TARGET_MIN,
        "target_fraction_max": TARGET_MAX,
        "hard_ceiling": HARD_MAX,
        "selected_grid_index": selected,
        "selected_weights": {"marginal_contact_weight": marginal, "pair_contact_weight": pair},
        "grid_results": grid_results,
        "open_only": True,
        "optimizer_steps_before_observation": 0,
        "gradient_batches_per_lane": 1,
        "v4_f_test32_access_count": 0,
        "input_hashes": dict(input_hashes),
    }
    amendment = {
        "schema_version": AMENDMENT_SCHEMA,
        "status": AMENDMENT_STATUS,
        "normalization": NORMALIZATION,
        "positive_class_fraction": 0.5,
        "epsilon": 1e-8,
        "gradient_telemetry_batches_per_epoch": 1,
        "marginal_contact_weight": marginal,
        "pair_contact_weight": pair,
        "exact_zero_is_observed_negative": True,
        "soft_target_contributes_positive_and_negative_mass": True,
        "class_missing_policy": "available_class_receives_full_weight; both_missing_is_unavailable",
        "source_normalization": "0.5*V4D+0.5*V4H after candidate/receptor reduction",
        "calibration": calibration,
    }
    report = {
        "schema_version": "pvrig_v6_residue_v2_contact_gradient_calibration_report_v1",
        "status": CALIBRATION_STATUS,
        "selection_used_prediction_metrics": False,
        "optimizer_steps_executed_by_selector": 0,
        "lane_observation_audit": {
            lane: {
                "result_sha256": input_hashes[lane],
                "candidate_ids_sha256": observations[lane]["candidate_ids_sha256"],
                "teacher_source_counts": observations[lane]["teacher_source_counts"],
                "unweighted_gradient_l2_norm": observations[lane]["unweighted_gradient_l2_norm"],
            }
            for lane in LANES
        },
        "calibration": calibration,
    }
    return amendment, report


def run(args: argparse.Namespace) -> dict[str, Any]:
    require(not args.output_dir.exists() and not args.output_dir.is_symlink(), "output_dir_must_not_exist")
    lane_paths = parse_lane_results(args.lane_result)
    observations: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    for lane in LANES:
        observations[lane], hashes[lane] = load_observation(lane, lane_paths[lane])
    amendment, report = build_calibration(observations, hashes)
    # No output directory, and therefore no amendment, is created on failure.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    atomic_json(args.output_dir / "CONTACT_LOSS_AMENDMENT_V1.json", amendment)
    atomic_json(args.output_dir / "CONTACT_GRADIENT_CALIBRATION_REPORT_V1.json", report)
    manifest = {
        name: sha256_file(args.output_dir / name)
        for name in ("CONTACT_LOSS_AMENDMENT_V1.json", "CONTACT_GRADIENT_CALIBRATION_REPORT_V1.json")
    }
    atomic_json(args.output_dir / "RUN_RECEIPT.json", {
        "schema_version": "pvrig_v6_residue_v2_contact_gradient_calibration_receipt_v1",
        "status": CALIBRATION_STATUS,
        "outputs": manifest,
        "claim_boundary": "Open-only preproduction gradient-scale calibration; no prediction metric or V4-F/test32 access.",
    })
    return {"status": CALIBRATION_STATUS, "selected_weights": amendment["calibration"]["selected_weights"], "outputs": manifest}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--lane-result", action="append", required=True, metavar="LANE=RESULT_JSON")
    value.add_argument("--output-dir", type=Path, required=True)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    result = run(parser().parse_args(argv))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
