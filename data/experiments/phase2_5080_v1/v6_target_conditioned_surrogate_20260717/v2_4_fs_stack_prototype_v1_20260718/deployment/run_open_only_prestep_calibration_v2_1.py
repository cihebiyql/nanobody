#!/usr/bin/env python3
"""Run the superseding V2.1 open-only multibatch contact-gradient calibration.

V2 failed before model construction because the generic artifact expansion
overwrote the calibration-wrapper placeholder with the base trainer path.
V2.1 fixes only that command-construction defect and uses a new immutable
bundle/runtime attempt.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import pathlib
import subprocess
import sys
from typing import Any, Mapping

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import node1_v2_4_outer_development_launcher_v2 as deployment


CALIBRATION_LANES = ("C_SPLIT_MARGINAL", "D_SPLIT_PAIR")
OBSERVATION_SCHEMA = "pvrig_v2_4_open_only_prestep_multibatch_gradient_observation_v2"
OBSERVATION_STATUS = "PASS_OPEN_ONLY_PRESTEP_MULTIBATCH_CONTACT_GRADIENT_LANE_OBSERVATION_V2_4"
CALIBRATION_SCHEMA = (
    "pvrig_v6_residue_v2_4_open_only_prestep_calibration_receipt_"
    "v2_adaptive_multiseed_multibatch"
)
CALIBRATION_STATUS = (
    "PASS_OPEN_ONLY_PRESTEP_CONTACT_GRADIENT_CALIBRATION_"
    "V2_4_ADAPTIVE_V2_MULTIBATCH"
)
OBSERVATION_SELECTION_RULE = (
    "smallest_grid_value_with_median_in_band_and_per_batch_max_at_or_below_ceiling_"
    "before_optimizer_construction"
)
RECEIPT_SELECTION_RULE = (
    "per_contact_lane_smallest_grid_value_with_median_in_band_and_per_batch_max_"
    "at_or_below_ceiling_before_optimizer_construction"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise deployment.DeploymentError(message)


def command_sha256(command: list[str]) -> str:
    return hashlib.sha256("\0".join(command).encode()).hexdigest()


def calibration_command(
    manifest: Mapping[str, Any], *, lane: str, output_dir: pathlib.Path,
) -> list[str]:
    require(lane in CALIBRATION_LANES, "calibration_lane_invalid")
    artifacts = manifest["artifacts"]
    values = {
        "python": manifest["python"],
        "lane": lane,
        "outer_fold": "0",
        "output_dir": str(output_dir),
        "split_manifest": artifacts["outer_split_0"]["node1_path"],
        "vhh_graph_dir": str(pathlib.Path(artifacts["vhh_graph_cache_npz"]["node1_path"]).parent),
    }
    values.update({label: record["node1_path"] for label, record in artifacts.items()})
    # Artifact label ``trainer`` names the production base trainer.  Calibration
    # must execute the independent multibatch wrapper instead; assign this
    # placeholder only after expanding artifact labels so it cannot be clobbered.
    values["trainer"] = artifacts[manifest["trainer"]["calibration_artifact_label"]]["node1_path"]
    command = []
    for token in manifest["trainer"]["argv_template"]:
        if token.startswith("{") and token.endswith("}"):
            name = token[1:-1]
            require(name in values, f"calibration_unknown_placeholder:{name}")
            command.append(str(values[name]))
        else:
            require("{" not in token and "}" not in token, "calibration_partial_placeholder")
            command.append(token)
    frozen = manifest["trainer"]["frozen_noncalibration_parameters"]
    contract = manifest["calibration_contract"]
    command.extend([
        "--fixed-epochs", str(frozen["fixed_epochs"]),
        "--graph-hidden-dim", str(frozen["graph_hidden_dim"]),
        "--dropout", str(frozen["dropout"]),
        "--batch-size", str(frozen["batch_size"]),
        "--precision", str(frozen["precision"]),
        "--device", "cuda",
        "--calibration-only",
        "--calibration-grid", *[str(value) for value in contract["fixed_grid"]],
        "--pair-to-marginal-ratio", str(contract["pair_to_marginal_ratio"]),
        "--target-gradient-fraction-band",
        *[str(value) for value in contract["target_median_gradient_fraction_band"]],
        "--maximum-per-batch-gradient-fraction",
        str(contract["maximum_per_batch_gradient_fraction"]),
        "--calibration-batch-offsets",
        *[str(record["batch_offset"]) for record in contract["batch_selection"]["batch_records"]],
        "--expected-calibration-batch-candidate-sha256",
        *[
            str(record["candidate_ids_sha256"])
            for record in contract["batch_selection"]["batch_records"]
        ],
    ])
    require(
        command[1] == artifacts[manifest["trainer"]["calibration_artifact_label"]]["node1_path"],
        "calibration_command_not_using_multibatch_wrapper",
    )
    require(command[1] != artifacts[manifest["trainer"]["artifact_label"]]["node1_path"],
            "calibration_command_uses_base_trainer")
    return command


def validate_observation(payload: Mapping[str, Any], manifest: Mapping[str, Any], lane: str) -> dict[str, float]:
    contract = manifest["calibration_contract"]
    require(payload.get("schema_version") == OBSERVATION_SCHEMA, "calibration_observation_schema")
    require(payload.get("status") == OBSERVATION_STATUS, "calibration_observation_status")
    require(payload.get("lane") == lane, "calibration_observation_lane")
    require(payload.get("open_only") is True, "calibration_observation_not_open")
    require(payload.get("optimizer_constructed") is False, "calibration_optimizer_constructed")
    require(payload.get("optimizer_steps_before_observation") == 0, "calibration_optimizer_step_nonzero")
    require(payload.get("outer_metrics_access_count") == 0, "calibration_outer_metrics_access")
    require(payload.get("prediction_metrics_access_count") == 0, "calibration_prediction_metrics_access")
    require(payload.get("v4_f_test32_access_count") == 0, "calibration_v4f_access")
    require(payload.get("fixed_grid") == contract["fixed_grid"], "calibration_observation_grid")
    require(payload.get("pair_to_marginal_ratio") == contract["pair_to_marginal_ratio"], "calibration_observation_ratio")
    require(
        payload.get("target_median_gradient_fraction_band")
        == contract["target_median_gradient_fraction_band"],
        "calibration_observation_median_band",
    )
    require(
        payload.get("maximum_per_batch_gradient_fraction")
        == contract["maximum_per_batch_gradient_fraction"],
        "calibration_observation_maximum_fraction",
    )
    require(payload.get("selection_rule") == OBSERVATION_SELECTION_RULE, "calibration_observation_selection_rule")
    batch_selection = contract["batch_selection"]
    expected_records = batch_selection["batch_records"]
    require(payload.get("calibration_batch_count") == len(expected_records) == 8, "calibration_observation_batch_count")
    require(
        payload.get("calibration_batch_offsets")
        == [record["batch_offset"] for record in expected_records],
        "calibration_observation_batch_offsets",
    )
    provenance = payload.get("calibration_batch_provenance")
    require(isinstance(provenance, list) and len(provenance) == 8, "calibration_observation_batch_provenance")
    for observed, expected in zip(provenance, expected_records):
        require(observed.get("batch_id") == expected["batch_id"], "calibration_observation_batch_id")
        require(observed.get("batch_offset") == expected["batch_offset"], "calibration_observation_batch_offset")
        require(observed.get("forward_seed") == expected["forward_seed"], "calibration_observation_batch_forward_seed")
        require(observed.get("candidate_ids") == expected["candidate_ids"], "calibration_observation_batch_candidate_ids")
        require(
            observed.get("candidate_ids_sha256") == expected["candidate_ids_sha256"],
            "calibration_observation_batch_candidate_sha256",
        )
        require(observed.get("candidate_count") == expected["candidate_count"], "calibration_observation_batch_candidate_count")
        require(observed.get("teacher_source_counts") == expected["teacher_source_counts"], "calibration_observation_batch_teacher_sources")
        require(observed.get("contact_tier_counts") == expected["contact_tier_counts"], "calibration_observation_batch_contact_tiers")
        require(
            observed.get("parent_framework_clusters") == expected["parent_framework_clusters"],
            "calibration_observation_batch_parents",
        )
    observations = payload.get("observations")
    require(isinstance(observations, list) and len(observations) == len(contract["fixed_grid"]), "calibration_observation_grid_rows")
    eligible_weights = []
    median_low, median_high = contract["target_median_gradient_fraction_band"]
    maximum_ceiling = contract["maximum_per_batch_gradient_fraction"]
    for record, grid_value in zip(observations, contract["fixed_grid"]):
        require(float(record.get("marginal_weight")) == float(grid_value), "calibration_observation_grid_weight")
        per_batch = record.get("per_batch")
        require(isinstance(per_batch, list) and len(per_batch) == 8, "calibration_observation_per_batch_count")
        require(
            [item.get("batch_id") for item in per_batch]
            == [item["batch_id"] for item in expected_records],
            "calibration_observation_per_batch_ids",
        )
        fractions = []
        for item in per_batch:
            scalar_norm = float(item["scalar_gradient_l2_norm"])
            contact_norm = float(item["contact_gradient_l2_norm"])
            fraction = float(item["contact_gradient_fraction"])
            require(
                math.isfinite(scalar_norm) and scalar_norm >= 0
                and math.isfinite(contact_norm) and contact_norm >= 0,
                "calibration_observation_gradient_norm",
            )
            denominator = scalar_norm + contact_norm
            expected_fraction = contact_norm / denominator if denominator > 0 else 0.0
            require(math.isfinite(fraction) and abs(fraction - expected_fraction) <= 1e-12,
                    "calibration_observation_gradient_fraction")
            cosine = item.get("scalar_contact_cosine")
            require(cosine is None or math.isfinite(float(cosine)),
                    "calibration_observation_gradient_cosine")
            groups = item.get("gradient_groups")
            require(
                isinstance(groups, dict)
                and set(groups) == {
                    "shared_encoder", "pair_factors", "attention_contact_terminals", "scalar_head",
                },
                "calibration_observation_gradient_groups",
            )
            for group_record in groups.values():
                require(isinstance(group_record.get("parameter_tensor_count"), int)
                        and group_record["parameter_tensor_count"] > 0,
                        "calibration_observation_gradient_group_parameter_count")
                for field in ("scalar_gradient_l2_norm", "contact_gradient_l2_norm"):
                    value = float(group_record[field])
                    require(math.isfinite(value) and value >= 0,
                            "calibration_observation_gradient_group_norm")
                group_cosine = group_record.get("scalar_contact_cosine")
                require(group_cosine is None or math.isfinite(float(group_cosine)),
                        "calibration_observation_gradient_group_cosine")
            fractions.append(fraction)
        ordered = sorted(fractions)
        median = (ordered[3] + ordered[4]) / 2.0
        maximum = max(fractions)
        require(
            abs(float(record.get("median_contact_gradient_fraction")) - median) <= 1e-12,
            "calibration_observation_median_value",
        )
        require(
            abs(float(record.get("maximum_contact_gradient_fraction")) - maximum) <= 1e-12,
            "calibration_observation_maximum_value",
        )
        expected_eligible = median_low <= median <= median_high and maximum <= maximum_ceiling
        require(record.get("eligible") is expected_eligible, "calibration_observation_eligibility")
        if expected_eligible:
            eligible_weights.append(float(grid_value))
    require(bool(eligible_weights), "calibration_observation_no_eligible_weight")
    weights = payload.get("selected_contact_weights")
    require(isinstance(weights, dict) and set(weights) == {"marginal", "pair"}, "calibration_selected_weights")
    marginal, pair = float(weights["marginal"]), float(weights["pair"])
    require(marginal == min(eligible_weights), "calibration_selected_not_smallest_eligible")
    require(marginal in contract["fixed_grid"], "calibration_selected_marginal_off_grid")
    expected_pair = 0.0 if lane == "C_SPLIT_MARGINAL" else marginal * contract["pair_to_marginal_ratio"]
    require(abs(pair - expected_pair) <= 1e-15, "calibration_selected_pair_ratio")
    return {"marginal": marginal, "pair": pair}


def aggregate_receipt(
    manifest_path: pathlib.Path, manifest: Mapping[str, Any],
    observations: Mapping[str, tuple[pathlib.Path, Mapping[str, Any], str]],
) -> dict[str, Any]:
    require(set(observations) == set(CALIBRATION_LANES), "calibration_observation_lane_closure")
    weights = {
        "A_VHH_ONLY": {"marginal": 0.0, "pair": 0.0},
        "B_TARGET_NO_CONTACT": {"marginal": 0.0, "pair": 0.0},
    }
    observation_receipts = {}
    for lane in CALIBRATION_LANES:
        path, payload, command_hash = observations[lane]
        weights[lane] = validate_observation(payload, manifest, lane)
        observation_receipts[lane] = {
            "path": str(path), "sha256": deployment.sha256_file(path),
            "command_sha256": command_hash,
            "selected_contact_weights": weights[lane],
        }
    contract = manifest["calibration_contract"]
    adaptive = manifest["adaptive_supervision"]
    return {
        "schema_version": CALIBRATION_SCHEMA,
        "status": CALIBRATION_STATUS,
        "manifest_sha256": deployment.sha256_file(manifest_path),
        "trainer_sha256": manifest["artifacts"]["trainer"]["sha256"],
        "calibration_trainer_sha256": manifest["artifacts"]["calibration_trainer"]["sha256"],
        "calibration_runner_sha256": manifest["artifacts"]["calibration_runner"]["sha256"],
        "open_only": True,
        "optimizer_constructed_before_observation": False,
        "optimizer_steps_before_observation": 0,
        "outer_metrics_access_count": 0,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
        "fixed_grid": contract["fixed_grid"],
        "pair_to_marginal_ratio": contract["pair_to_marginal_ratio"],
        "target_median_gradient_fraction_band": contract["target_median_gradient_fraction_band"],
        "maximum_per_batch_gradient_fraction": contract["maximum_per_batch_gradient_fraction"],
        "calibration_batch_count": 8,
        "calibration_batch_contract_sha256": contract["batch_selection"]["contract_sha256"],
        "selection_rule": RECEIPT_SELECTION_RULE,
        "frozen_lane_contact_weights": weights,
        "attention_temperatures": contract["attention_temperatures"],
        "adaptive_input_contract_sha256": adaptive["input_contract_sha256"],
        "adaptive_source_receipt_sha256": adaptive["source_receipt_sha256"],
        "adaptive_v4d_source_receipt_sha256": adaptive["v4d_source_receipt_sha256"],
        "adaptive_teacher_generation": adaptive["teacher_generation"],
        "lane_observations": observation_receipts,
        "implementation_freeze_created": False,
        "production_runtime_created": False,
        "next_permitted_action": "Materialize hash-bound ready manifest, then independent implementation freeze, then Node1 tiny smoke.",
        "claim_boundary": manifest["claim_boundary"],
    }


def dry_run(manifest_path: pathlib.Path) -> dict[str, Any]:
    manifest = deployment.load_manifest(manifest_path, allow_pending_calibration=True)
    require(manifest["status"] == "PREFREEZE_V2_ADAPTIVE_MULTI_SEED_CALIBRATION_PENDING_DO_NOT_START", "calibration_requires_pending_manifest")
    deployment.validate_local_sources(manifest)
    deployment.validate_training_contract(manifest, use_source=True)
    contract = manifest["calibration_contract"]
    root = pathlib.Path(contract["calibration_runtime_root"])
    receipt = pathlib.Path(contract["calibration_receipt_node1_path"])
    require(not os.path.lexists(root), "calibration_runtime_must_be_absent")
    require(not os.path.lexists(receipt), "calibration_receipt_must_be_absent")
    commands = {
        lane: {
            "physical_gpu": deployment.LANE_GPU[lane],
            "command": calibration_command(manifest, lane=lane, output_dir=root / lane),
        }
        for lane in CALIBRATION_LANES
    }
    return {
        "schema_version": "pvrig_v6_residue_v2_4_calibration_dry_run_v2_adaptive_multiseed",
        "status": "PASS_V2_ADAPTIVE_OPEN_ONLY_PRESTEP_CALIBRATION_DRY_RUN_NO_MUTATION",
        "manifest_sha256": deployment.sha256_file(manifest_path),
        "phase_order": manifest["execution"]["phase_order"],
        "commands": commands,
        "command_count": 2,
        "optimizer_steps_before_observation": 0,
        "outer_metrics_access_count": 0,
        "prediction_metrics_access_count": 0,
        "runtime_absent": True,
        "receipt_absent": True,
        "production_authorized": False,
    }


def execute(manifest_path: pathlib.Path) -> dict[str, Any]:
    manifest = deployment.load_manifest(manifest_path, allow_pending_calibration=True)
    require(manifest["status"] == "PREFREEZE_V2_ADAPTIVE_MULTI_SEED_CALIBRATION_PENDING_DO_NOT_START", "calibration_requires_pending_manifest")
    deployment.validate_node1_artifacts(manifest)
    deployment.validate_training_contract(manifest, use_source=False)
    contract = manifest["calibration_contract"]
    root = pathlib.Path(contract["calibration_runtime_root"])
    receipt_path = pathlib.Path(contract["calibration_receipt_node1_path"])
    require(not os.path.lexists(root), "calibration_runtime_must_be_absent")
    require(root.parent.is_dir() and not root.parent.is_symlink(), "calibration_runtime_parent_missing_or_symlink")
    require(not os.path.lexists(receipt_path), "calibration_receipt_must_be_absent")
    root.mkdir()

    def run_lane(lane: str) -> tuple[pathlib.Path, Mapping[str, Any], str]:
        output = root / lane
        command = calibration_command(manifest, lane=lane, output_dir=output)
        environment = os.environ.copy(); environment.update(deployment.THREAD_ENVIRONMENT)
        environment["CUDA_VISIBLE_DEVICES"] = str(deployment.LANE_GPU[lane])
        log_path = root / f"{lane}.log"
        with log_path.open("w", encoding="utf-8") as log:
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=environment, check=False)
        require(completed.returncode == 0, f"calibration_trainer_failed:{lane}:{completed.returncode}")
        result_path = output / "CALIBRATION_OBSERVATION.json"
        payload = deployment.load_json(result_path, f"calibration_observation:{lane}")
        validate_observation(payload, manifest, lane)
        return result_path, payload, command_sha256(command)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {lane: pool.submit(run_lane, lane) for lane in CALIBRATION_LANES}
        observations = {lane: future.result() for lane, future in futures.items()}
    receipt = aggregate_receipt(manifest_path, manifest, observations)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / "CALIBRATION_RECEIPT.json").write_text(receipt_path.read_text(encoding="utf-8"), encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = dry_run(args.manifest) if args.dry_run else execute(args.manifest)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (deployment.DeploymentError, OSError, json.JSONDecodeError) as error:
        print(f"FAIL_V2_4_ADAPTIVE_V2_CALIBRATION:{error}", file=os.sys.stderr)
        raise SystemExit(1)
