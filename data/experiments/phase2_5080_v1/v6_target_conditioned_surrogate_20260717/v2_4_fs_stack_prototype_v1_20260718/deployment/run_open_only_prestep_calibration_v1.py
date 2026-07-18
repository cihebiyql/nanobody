#!/usr/bin/env python3
"""Run the real open-only pre-optimizer-step V2.4 contact-gradient calibration."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import pathlib
import subprocess
import sys
from typing import Any, Mapping

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import node1_v2_4_outer_development_launcher_v1 as deployment


CALIBRATION_LANES = ("C_SPLIT_MARGINAL", "D_SPLIT_PAIR")


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
        "trainer": artifacts[manifest["trainer"]["artifact_label"]]["node1_path"],
        "lane": lane,
        "outer_fold": "0",
        "output_dir": str(output_dir),
        "split_manifest": artifacts["outer_split_0"]["node1_path"],
        "vhh_graph_dir": str(pathlib.Path(artifacts["vhh_graph_cache_npz"]["node1_path"]).parent),
    }
    values.update({label: record["node1_path"] for label, record in artifacts.items()})
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
        "--target-gradient-fraction-band", *[str(value) for value in contract["target_gradient_fraction_band"]],
    ])
    return command


def validate_observation(payload: Mapping[str, Any], manifest: Mapping[str, Any], lane: str) -> dict[str, float]:
    contract = manifest["calibration_contract"]
    require(payload.get("status") == "PASS_OPEN_ONLY_PRESTEP_CONTACT_GRADIENT_LANE_OBSERVATION_V2_4", "calibration_observation_status")
    require(payload.get("lane") == lane, "calibration_observation_lane")
    require(payload.get("open_only") is True, "calibration_observation_not_open")
    require(payload.get("optimizer_constructed") is False, "calibration_optimizer_constructed")
    require(payload.get("optimizer_steps_before_observation") == 0, "calibration_optimizer_step_nonzero")
    require(payload.get("outer_metrics_access_count") == 0, "calibration_outer_metrics_access")
    require(payload.get("prediction_metrics_access_count") == 0, "calibration_prediction_metrics_access")
    require(payload.get("v4_f_test32_access_count") == 0, "calibration_v4f_access")
    require(payload.get("fixed_grid") == contract["fixed_grid"], "calibration_observation_grid")
    require(payload.get("pair_to_marginal_ratio") == contract["pair_to_marginal_ratio"], "calibration_observation_ratio")
    require(payload.get("target_gradient_fraction_band") == contract["target_gradient_fraction_band"], "calibration_observation_band")
    weights = payload.get("selected_contact_weights")
    require(isinstance(weights, dict) and set(weights) == {"marginal", "pair"}, "calibration_selected_weights")
    marginal, pair = float(weights["marginal"]), float(weights["pair"])
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
    return {
        "schema_version": "pvrig_v6_residue_v2_4_open_only_prestep_calibration_receipt_v1",
        "status": "PASS_OPEN_ONLY_PRESTEP_CONTACT_GRADIENT_CALIBRATION_V2_4",
        "manifest_sha256": deployment.sha256_file(manifest_path),
        "trainer_sha256": manifest["artifacts"]["trainer"]["sha256"],
        "calibration_runner_sha256": manifest["artifacts"]["calibration_runner"]["sha256"],
        "open_only": True,
        "optimizer_constructed_before_observation": False,
        "optimizer_steps_before_observation": 0,
        "outer_metrics_access_count": 0,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
        "fixed_grid": contract["fixed_grid"],
        "pair_to_marginal_ratio": contract["pair_to_marginal_ratio"],
        "target_gradient_fraction_band": contract["target_gradient_fraction_band"],
        "selection_rule": "per_contact_lane_smallest_grid_value_in_target_band_before_optimizer_construction",
        "frozen_lane_contact_weights": weights,
        "attention_temperatures": contract["attention_temperatures"],
        "lane_observations": observation_receipts,
        "implementation_freeze_created": False,
        "production_runtime_created": False,
        "next_permitted_action": "Materialize hash-bound ready manifest, then independent implementation freeze, then Node1 tiny smoke.",
        "claim_boundary": manifest["claim_boundary"],
    }


def dry_run(manifest_path: pathlib.Path) -> dict[str, Any]:
    manifest = deployment.load_manifest(manifest_path, allow_pending_calibration=True)
    require(manifest["status"] == "PREFREEZE_DRY_RUN_PENDING_CALIBRATION_DO_NOT_START", "calibration_requires_pending_manifest")
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
        "schema_version": "pvrig_v6_residue_v2_4_calibration_dry_run_v1",
        "status": "PASS_OPEN_ONLY_PRESTEP_CALIBRATION_DRY_RUN_NO_MUTATION",
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
    require(manifest["status"] == "PREFREEZE_DRY_RUN_PENDING_CALIBRATION_DO_NOT_START", "calibration_requires_pending_manifest")
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
        print(f"FAIL_V2_4_CALIBRATION:{error}", file=os.sys.stderr)
        raise SystemExit(1)
