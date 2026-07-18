#!/usr/bin/env python3
"""Select lane-specific Residue V2 contact weights from frozen open gradients.

V1's shared-weight grid remains immutable and fail-closed.  V2.2 reuses the
same four hash-closed, one-batch pre-optimizer observations but selects the
smallest acceptable geometric-grid weight independently for each lane.
Prediction metrics, optimizer steps, and V4-F/test32 are outside this program.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import select_contact_loss_gradient_grid_v1 as v1


GRID = (0.0003125, 0.000625, 0.00125, 0.0025, 0.005, 0.01, 0.02)
AMENDMENT_SCHEMA = "pvrig_v6_residue_v2_contact_loss_amendment_v2_2"
CALIBRATION_SCHEMA = "pvrig_v6_residue_v2_contact_gradient_calibration_v2_2"
CALIBRATION_STATUS = "PASS_OPEN_ONLY_ONE_BATCH_PRESTEP_LANE_SPECIFIC_GRADIENT_CALIBRATION"
SELECTION_RULE = "per_lane_smallest_grid_entry_in_target_band_and_below_hard_ceiling"


def direct_contact_fraction(lane: str, raw: Mapping[str, Any], marginal_weight: float) -> float:
    pair_weight = marginal_weight / 2.0
    weights = dict(v1.NONCONTACT_WEIGHTS)
    weights["marginal"] = marginal_weight
    if lane == "D_FULL_PAIR":
        weights["pair"] = pair_weight
    weighted = {name: abs(float(weights[name])) * float(raw[name]) for name in weights}
    denominator = sum(weighted.values())
    v1.require(denominator > 0.0, f"gradient_denominator_invalid:{lane}")
    return (weighted["marginal"] + weighted.get("pair", 0.0)) / denominator


def build_calibration(
    observations: Mapping[str, Mapping[str, Any]],
    input_hashes: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    lane_grid_results: dict[str, list[dict[str, Any]]] = {}
    lane_selected_grid_index: dict[str, int] = {}
    lane_weights: dict[str, dict[str, float]] = {}
    for lane in v1.LANES:
        results: list[dict[str, Any]] = []
        passing: list[int] = []
        for index, marginal in enumerate(GRID):
            pair = marginal / 2.0
            fraction = direct_contact_fraction(
                lane, observations[lane]["unweighted_gradient_l2_norm"], marginal,
            )
            target_pass = v1.TARGET_MIN <= fraction <= v1.TARGET_MAX
            hard_pass = fraction <= v1.HARD_MAX
            results.append({
                "grid_index": index,
                "marginal_contact_weight": marginal,
                "pair_contact_weight": pair,
                "direct_contact_gradient_fraction": fraction,
                "in_target_band": target_pass,
                "hard_ceiling_pass": hard_pass,
            })
            if target_pass and hard_pass:
                passing.append(index)
        v1.require(bool(passing), f"no_grid_entry_places_lane_in_target_band:{lane}")
        selected_index = passing[0]
        selected_marginal = GRID[selected_index]
        lane_grid_results[lane] = results
        lane_selected_grid_index[lane] = selected_index
        lane_weights[lane] = {
            "marginal_contact_weight": selected_marginal,
            "pair_contact_weight": selected_marginal / 2.0,
        }

    calibration = {
        "schema_version": CALIBRATION_SCHEMA,
        "status": CALIBRATION_STATUS,
        "grid": [
            {"marginal_contact_weight": marginal, "pair_contact_weight": marginal / 2.0}
            for marginal in GRID
        ],
        "selection_rule": SELECTION_RULE,
        "target_fraction_min": v1.TARGET_MIN,
        "target_fraction_max": v1.TARGET_MAX,
        "hard_ceiling": v1.HARD_MAX,
        "lane_selected_grid_index": lane_selected_grid_index,
        "lane_weights": lane_weights,
        "lane_grid_results": lane_grid_results,
        "open_only": True,
        "optimizer_steps_before_observation": 0,
        "gradient_batches_per_lane": 1,
        "v4_f_test32_access_count": 0,
        "input_hashes": dict(input_hashes),
    }
    amendment = {
        "schema_version": AMENDMENT_SCHEMA,
        "status": v1.AMENDMENT_STATUS,
        "normalization": v1.NORMALIZATION,
        "positive_class_fraction": 0.5,
        "epsilon": 1e-8,
        "gradient_telemetry_batches_per_epoch": 1,
        "lane_weights": lane_weights,
        "exact_zero_is_observed_negative": True,
        "soft_target_contributes_positive_and_negative_mass": True,
        "class_missing_policy": "available_class_receives_full_weight; both_missing_is_unavailable",
        "source_normalization": "0.5*V4D+0.5*V4H after candidate/receptor reduction",
        "calibration": calibration,
    }
    report = {
        "schema_version": "pvrig_v6_residue_v2_contact_gradient_calibration_report_v2_2",
        "status": CALIBRATION_STATUS,
        "supersedes_selection_policy": "V1_SHARED_WEIGHT_GRID_FAIL_CLOSED_PRESERVED",
        "selection_used_prediction_metrics": False,
        "optimizer_steps_executed_by_selector": 0,
        "v4_f_test32_access_count": 0,
        "lane_observation_audit": {
            lane: {
                "result_sha256": input_hashes[lane],
                "candidate_ids_sha256": observations[lane]["candidate_ids_sha256"],
                "teacher_source_counts": observations[lane]["teacher_source_counts"],
                "unweighted_gradient_l2_norm": observations[lane]["unweighted_gradient_l2_norm"],
            }
            for lane in v1.LANES
        },
        "calibration": calibration,
    }
    return amendment, report


def run(args: argparse.Namespace) -> dict[str, Any]:
    v1.require(not args.output_dir.exists() and not args.output_dir.is_symlink(), "output_dir_must_not_exist")
    lane_paths = v1.parse_lane_results(args.lane_result)
    observations: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    for lane in v1.LANES:
        observations[lane], hashes[lane] = v1.load_observation(lane, lane_paths[lane])
    amendment, report = build_calibration(observations, hashes)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    v1.atomic_json(args.output_dir / "CONTACT_LOSS_AMENDMENT_V2_2.json", amendment)
    v1.atomic_json(args.output_dir / "CONTACT_GRADIENT_CALIBRATION_REPORT_V2_2.json", report)
    manifest = {
        name: v1.sha256_file(args.output_dir / name)
        for name in ("CONTACT_LOSS_AMENDMENT_V2_2.json", "CONTACT_GRADIENT_CALIBRATION_REPORT_V2_2.json")
    }
    v1.atomic_json(args.output_dir / "RUN_RECEIPT.json", {
        "schema_version": "pvrig_v6_residue_v2_contact_gradient_calibration_receipt_v2_2",
        "status": CALIBRATION_STATUS,
        "outputs": manifest,
        "claim_boundary": "Open-only lane-specific gradient-scale calibration; no prediction metric or V4-F/test32 access.",
    })
    return {"status": CALIBRATION_STATUS, "lane_weights": amendment["lane_weights"], "outputs": manifest}


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
