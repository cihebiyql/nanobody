#!/usr/bin/env python3
"""Materialize the hash-bound V2.4 ready manifest and implementation freeze.

This is a post-calibration, pre-runtime operation.  It verifies the formal
prefreeze manifest, both real C/D calibration observations, the aggregate
calibration receipt, the contact-score formula, and every Node1 artifact.  It
then freezes the selected contact weights into the production argv.  It never
creates the production runtime and never launches training.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import pathlib
import stat
import tempfile
from typing import Any, Mapping, Sequence


PENDING_STATUS = "PREFREEZE_DRY_RUN_PENDING_CALIBRATION_DO_NOT_START"
READY_STATUS = "PREFREEZE_DRY_RUN_READY_DO_NOT_START"
FREEZE_STATUS = "PASS_V2_4_IMPLEMENTATION_FROZEN_FOR_TINY_SMOKE_AND_OUTER_DEVELOPMENT"
CALIBRATION_STATUS = "PASS_OPEN_ONLY_PRESTEP_CONTACT_GRADIENT_CALIBRATION_V2_4"
OBSERVATION_STATUS = "PASS_OPEN_ONLY_PRESTEP_CONTACT_GRADIENT_LANE_OBSERVATION_V2_4"
CALIBRATION_SCHEMA = "pvrig_v6_residue_v2_4_open_only_prestep_calibration_receipt_v1"
OBSERVATION_SCHEMA = "pvrig_v2_4_open_only_prestep_gradient_observation_v1"
LANES = ("A_VHH_ONLY", "B_TARGET_NO_CONTACT", "C_SPLIT_MARGINAL", "D_SPLIT_PAIR")
CONTACT_LANES = ("C_SPLIT_MARGINAL", "D_SPLIT_PAIR")
LANE_GPU = {
    "A_VHH_ONLY": 1,
    "B_TARGET_NO_CONTACT": 2,
    "C_SPLIT_MARGINAL": 4,
    "D_SPLIT_PAIR": 5,
}
NODE1_PYTHON = "/data1/qlyu/software/envs/pvrig-v6-tc/bin/python"
THREAD_ENVIRONMENT = {
    "OMP_NUM_THREADS": "8",
    "MKL_NUM_THREADS": "8",
    "OPENBLAS_NUM_THREADS": "8",
    "NUMEXPR_NUM_THREADS": "8",
    "TOKENIZERS_PARALLELISM": "false",
}
PHASE_ORDER = [
    "OPEN_ONLY_CONTACT_GRADIENT_CALIBRATION",
    "IMPLEMENTATION_FREEZE",
    "TINY_SMOKE",
    "FOUR_LANE_OUTER_DEVELOPMENT",
]
FORMULA_VERSION = "pvrig_v2_4_contact_composite_v1_equal_weight_preregistered"
FORMULA_WEIGHTS = {"hotspot_contact_mass": 0.5, "interface_specificity": 0.5}
FORBIDDEN_PATH_TOKENS = ("v4_f", "test32", "prospective_computational_test")


class FreezeMaterializationError(RuntimeError):
    """A fail-closed post-calibration validation failure."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FreezeMaterializationError(message)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def command_sha256(command: Sequence[str]) -> str:
    return hashlib.sha256("\0".join(command).encode()).hexdigest()


def load_regular_json(path: pathlib.Path, label: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise FreezeMaterializationError(f"{label}_missing:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"{label}_not_regular_or_symlink:{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FreezeMaterializationError(f"{label}_invalid_json:{path}") from exc
    require(isinstance(payload, dict), f"{label}_not_object:{path}")
    return payload


def safe_absolute(value: Any, label: str) -> pathlib.Path:
    require(isinstance(value, str) and value.startswith("/"), f"{label}_not_absolute")
    lowered = value.lower()
    require(not any(token in lowered for token in FORBIDDEN_PATH_TOKENS), f"{label}_sealed_path:{value}")
    return pathlib.Path(value)


def validate_artifact_record(label: str, record: Mapping[str, Any]) -> pathlib.Path:
    require(isinstance(record, Mapping), f"artifact_record_invalid:{label}")
    path = safe_absolute(record.get("node1_path"), f"artifact_node1_path:{label}")
    digest = record.get("sha256")
    require(isinstance(digest, str) and len(digest) == 64, f"artifact_sha256_invalid:{label}")
    require(isinstance(record.get("size_bytes"), int) and int(record["size_bytes"]) >= 0, f"artifact_size_invalid:{label}")
    require(record.get("validation_mode") in {"LOCAL_SOURCE_AND_NODE1", "INHERITED_NODE1_IMMUTABLE"}, f"artifact_validation_mode:{label}")
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise FreezeMaterializationError(f"node1_artifact_missing:{label}:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"node1_artifact_not_regular_or_symlink:{label}:{path}")
    require(metadata.st_size == int(record["size_bytes"]), f"node1_artifact_size_mismatch:{label}")
    require(sha256_file(path) == digest, f"node1_artifact_sha256_mismatch:{label}")
    return path


def validate_prefreeze_manifest(path: pathlib.Path) -> dict[str, Any]:
    manifest = load_regular_json(path, "prefreeze_manifest")
    require(manifest.get("status") == PENDING_STATUS, "prefreeze_manifest_status")
    require(manifest.get("production_authorized") is False, "prefreeze_production_authorized")
    require(manifest.get("sealed_evaluation_access_count") == 0, "prefreeze_sealed_access_nonzero")
    require(manifest.get("prediction_metrics_access_count") == 0, "prefreeze_prediction_access_nonzero")
    require(manifest.get("python") == NODE1_PYTHON, "node1_python_contract")
    resources = manifest.get("resources") or {}
    require(resources.get("lane_gpu_map") == LANE_GPU, "node1_gpu_contract")
    require(resources.get("cpu_threads_per_process") == 8, "node1_cpu_thread_contract")
    require(resources.get("thread_environment") == THREAD_ENVIRONMENT, "node1_thread_environment_contract")
    execution = manifest.get("execution") or {}
    require(execution.get("phase_order") == PHASE_ORDER, "phase_order_contract")
    require(execution.get("outer_folds") == [0, 1, 2, 3, 4], "outer_fold_contract")
    require(execution.get("lanes_concurrent") == 4, "lane_concurrency_contract")
    require(execution.get("folds_sequential_within_lane") is True, "fold_sequence_contract")
    require(execution.get("tiny_smoke_must_pass_all_lanes") is True, "tiny_smoke_gate_contract")
    require(execution.get("automatic_smoke_to_outer_transition") is False, "automatic_transition_forbidden")
    require(manifest.get("runtime_must_remain_absent_until_implementation_freeze") is True, "runtime_absence_contract")
    runtime_root = safe_absolute(manifest.get("runtime_root"), "runtime_root")
    require(not os.path.lexists(runtime_root), f"production_runtime_exists_before_freeze:{runtime_root}")
    safe_absolute(manifest.get("bundle_root"), "bundle_root")

    artifacts = manifest.get("artifacts")
    require(isinstance(artifacts, dict) and artifacts, "formal_artifacts_missing")
    required = {
        "trainer", "calibration_runner", "deployment_launcher", "contact_formula",
        "postcalibration_materializer",
    }
    require(required <= set(artifacts), "required_formal_artifact_missing")
    for label, record in sorted(artifacts.items()):
        validate_artifact_record(label, record)
    require(
        artifacts["postcalibration_materializer"]["sha256"]
        == sha256_file(pathlib.Path(__file__).resolve()),
        "running_materializer_not_bound_by_prefreeze_manifest",
    )
    trainer = manifest.get("trainer") or {}
    require(trainer.get("artifact_label") == "trainer", "trainer_artifact_label")
    template = trainer.get("argv_template")
    require(isinstance(template, list) and template, "trainer_argv_template")
    require(template.count("--contact-formula-json") == 1, "contact_formula_flag_must_be_unique")
    formula_index = template.index("--contact-formula-json")
    require(formula_index + 1 < len(template) and template[formula_index + 1] == "{contact_formula}", "contact_formula_placeholder_binding")
    require(trainer.get("outer_development_extra_argv") is None, "prefreeze_outer_argv_must_be_null")
    require(trainer.get("lane_outer_extra_argv") is None, "prefreeze_lane_argv_must_be_null")

    contract = manifest.get("calibration_contract") or {}
    require(contract.get("binding_status") == "PENDING_OPEN_ONLY_PRESTEP_CALIBRATION", "calibration_binding_status")
    require(contract.get("receipt_artifact_label") is None, "calibration_receipt_label_must_be_null")
    require(contract.get("frozen_lane_contact_weights") is None, "prefreeze_weights_must_be_null")
    require(contract.get("open_only") is True, "calibration_open_only_contract")
    require(contract.get("optimizer_steps_before_observation") == 0, "calibration_prestep_contract")
    require(contract.get("outer_metrics_access_count") == 0, "calibration_outer_access_contract")
    require(contract.get("prediction_metrics_access_count") == 0, "calibration_prediction_access_contract")
    grid = contract.get("fixed_grid")
    require(isinstance(grid, list) and grid == sorted(set(grid)) and all(isinstance(x, (int, float)) and x > 0 for x in grid), "calibration_grid_contract")
    band = contract.get("target_gradient_fraction_band")
    require(isinstance(band, list) and len(band) == 2 and 0 <= float(band[0]) <= float(band[1]) <= 1, "calibration_band_contract")
    ratio = contract.get("pair_to_marginal_ratio")
    require(isinstance(ratio, (int, float)) and 0 < float(ratio) <= 1, "calibration_pair_ratio_contract")
    require(contract.get("attention_temperatures") == {"8x6b": 1.0, "9e6y": 1.0}, "attention_temperature_contract")
    require(contract.get("selection_rule") == "per_lane_smallest_grid_value_in_target_band_before_optimizer_step", "calibration_selection_rule_contract")
    calibration_root = safe_absolute(contract.get("calibration_runtime_root"), "calibration_runtime_root")
    require(calibration_root.is_dir() and not calibration_root.is_symlink(), "calibration_runtime_missing_or_symlink")
    safe_absolute(contract.get("calibration_receipt_node1_path"), "calibration_receipt_node1_path")
    return manifest


def validate_formula(manifest: Mapping[str, Any]) -> dict[str, Any]:
    record = manifest["artifacts"]["contact_formula"]
    formula_path = pathlib.Path(record["node1_path"])
    formula = load_regular_json(formula_path, "contact_formula")
    require(sha256_file(formula_path) == record["sha256"], "contact_formula_sha256")
    require(formula.get("formula_version") == FORMULA_VERSION, "contact_formula_version")
    require(formula.get("receptors") == ["R8", "R9"], "contact_formula_receptors")
    require(formula.get("inputs_per_receptor") == ["hotspot_contact_mass", "interface_specificity"], "contact_formula_inputs")
    require(formula.get("weights") == FORMULA_WEIGHTS, "contact_formula_weights")
    require(float(formula.get("intercept")) == 0.0, "contact_formula_intercept")
    require(formula.get("clipping") is False, "contact_formula_clipping")
    require(formula.get("label_access") is False, "contact_formula_label_access")
    require(formula.get("outer_result_tuning") is False, "contact_formula_outer_tuning")
    return formula


def calibration_command(manifest: Mapping[str, Any], lane: str, output_dir: pathlib.Path) -> list[str]:
    require(lane in CONTACT_LANES, "calibration_command_lane")
    artifacts = manifest["artifacts"]
    values: dict[str, str] = {
        "python": manifest["python"],
        "trainer": artifacts[manifest["trainer"]["artifact_label"]]["node1_path"],
        "lane": lane,
        "outer_fold": "0",
        "output_dir": str(output_dir),
        "split_manifest": artifacts["outer_split_0"]["node1_path"],
        "vhh_graph_dir": str(pathlib.Path(artifacts["vhh_graph_cache_npz"]["node1_path"]).parent),
    }
    values.update({label: record["node1_path"] for label, record in artifacts.items()})
    command: list[str] = []
    for token in manifest["trainer"]["argv_template"]:
        require(isinstance(token, str), "calibration_template_nonstring")
        if token.startswith("{") and token.endswith("}"):
            name = token[1:-1]
            require(name in values, f"calibration_unknown_placeholder:{name}")
            command.append(values[name])
        else:
            require("{" not in token and "}" not in token, f"calibration_partial_placeholder:{token}")
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


def _validate_observation_grid(payload: Mapping[str, Any], manifest: Mapping[str, Any], lane: str) -> dict[str, float]:
    contract = manifest["calibration_contract"]
    grid = [float(value) for value in contract["fixed_grid"]]
    ratio = float(contract["pair_to_marginal_ratio"])
    lower, upper = (float(value) for value in contract["target_gradient_fraction_band"])
    observations = payload.get("observations")
    require(isinstance(observations, list) and len(observations) == len(grid), f"observation_grid_row_count:{lane}")
    eligible: list[dict[str, float]] = []
    for expected_marginal, raw in zip(grid, observations):
        require(isinstance(raw, dict), f"observation_grid_row_invalid:{lane}")
        marginal = float(raw.get("marginal_weight"))
        pair = float(raw.get("pair_weight"))
        scalar_norm = float(raw.get("scalar_gradient_l2_norm"))
        contact_norm = float(raw.get("contact_gradient_l2_norm"))
        fraction = float(raw.get("contact_gradient_fraction"))
        require(all(math.isfinite(x) for x in (marginal, pair, scalar_norm, contact_norm, fraction)), f"observation_nonfinite:{lane}")
        require(marginal == expected_marginal, f"observation_grid_order:{lane}")
        expected_pair = 0.0 if lane == "C_SPLIT_MARGINAL" else marginal * ratio
        require(abs(pair - expected_pair) <= 1e-15, f"observation_pair_ratio:{lane}")
        require(scalar_norm >= 0 and contact_norm >= 0, f"observation_gradient_negative:{lane}")
        denominator = scalar_norm + contact_norm
        expected_fraction = contact_norm / denominator if denominator > 0 else 0.0
        require(abs(fraction - expected_fraction) <= 1e-12, f"observation_gradient_fraction_mismatch:{lane}")
        if lower <= fraction <= upper:
            eligible.append({"marginal": marginal, "pair": pair})
    require(bool(eligible), f"observation_no_eligible_grid_value:{lane}")
    expected_selected = min(eligible, key=lambda item: item["marginal"])
    selected = payload.get("selected_contact_weights")
    require(isinstance(selected, dict) and set(selected) == {"marginal", "pair"}, f"observation_selected_weights:{lane}")
    observed_selected = {"marginal": float(selected["marginal"]), "pair": float(selected["pair"])}
    require(observed_selected == expected_selected, f"observation_selection_not_smallest_eligible:{lane}")
    return observed_selected


def validate_calibration_receipt(
    manifest_path: pathlib.Path,
    manifest: Mapping[str, Any],
    receipt_path: pathlib.Path,
) -> tuple[dict[str, Any], dict[str, dict[str, float]]]:
    receipt = load_regular_json(receipt_path, "calibration_receipt")
    contract = manifest["calibration_contract"]
    require(receipt_path == pathlib.Path(contract["calibration_receipt_node1_path"]), "calibration_receipt_noncanonical_path")
    require(receipt.get("schema_version") == CALIBRATION_SCHEMA, "calibration_receipt_schema")
    require(receipt.get("status") == CALIBRATION_STATUS, "calibration_receipt_status")
    require(receipt.get("manifest_sha256") == sha256_file(manifest_path), "calibration_receipt_manifest_sha256")
    require(receipt.get("trainer_sha256") == manifest["artifacts"]["trainer"]["sha256"], "calibration_receipt_trainer_sha256")
    require(receipt.get("calibration_runner_sha256") == manifest["artifacts"]["calibration_runner"]["sha256"], "calibration_receipt_runner_sha256")
    require(receipt.get("open_only") is True, "calibration_receipt_not_open_only")
    require(receipt.get("optimizer_constructed_before_observation") is False, "calibration_receipt_optimizer_constructed")
    require(receipt.get("optimizer_steps_before_observation") == 0, "calibration_receipt_optimizer_steps")
    require(receipt.get("outer_metrics_access_count") == 0, "calibration_receipt_outer_access")
    require(receipt.get("prediction_metrics_access_count") == 0, "calibration_receipt_prediction_access")
    require(receipt.get("v4_f_test32_access_count") == 0, "calibration_receipt_sealed_access")
    require(receipt.get("fixed_grid") == contract["fixed_grid"], "calibration_receipt_grid")
    require(receipt.get("pair_to_marginal_ratio") == contract["pair_to_marginal_ratio"], "calibration_receipt_pair_ratio")
    require(receipt.get("target_gradient_fraction_band") == contract["target_gradient_fraction_band"], "calibration_receipt_band")
    require(receipt.get("attention_temperatures") == contract["attention_temperatures"], "calibration_receipt_temperatures")
    require(receipt.get("selection_rule") == "per_contact_lane_smallest_grid_value_in_target_band_before_optimizer_construction", "calibration_receipt_selection_rule")
    require(receipt.get("implementation_freeze_created") is False, "calibration_receipt_prior_freeze")
    require(receipt.get("production_runtime_created") is False, "calibration_receipt_prior_runtime")
    require(receipt.get("claim_boundary") == manifest["claim_boundary"], "calibration_receipt_claim_boundary")

    lane_records = receipt.get("lane_observations")
    require(isinstance(lane_records, dict) and set(lane_records) == set(CONTACT_LANES), "calibration_observation_lane_closure")
    weights: dict[str, dict[str, float]] = {
        "A_VHH_ONLY": {"marginal": 0.0, "pair": 0.0},
        "B_TARGET_NO_CONTACT": {"marginal": 0.0, "pair": 0.0},
    }
    calibration_root = pathlib.Path(contract["calibration_runtime_root"])
    for lane in CONTACT_LANES:
        record = lane_records[lane]
        require(isinstance(record, dict), f"calibration_observation_record:{lane}")
        observation_path = safe_absolute(record.get("path"), f"calibration_observation_path:{lane}")
        expected_path = calibration_root / lane / "CALIBRATION_OBSERVATION.json"
        require(observation_path == expected_path, f"calibration_observation_noncanonical_path:{lane}")
        payload = load_regular_json(observation_path, f"calibration_observation:{lane}")
        require(record.get("sha256") == sha256_file(observation_path), f"calibration_observation_sha256:{lane}")
        require(payload.get("schema_version") == OBSERVATION_SCHEMA, f"calibration_observation_schema:{lane}")
        require(payload.get("status") == OBSERVATION_STATUS, f"calibration_observation_status:{lane}")
        require(payload.get("lane") == lane, f"calibration_observation_lane:{lane}")
        require(payload.get("open_only") is True, f"calibration_observation_open_only:{lane}")
        require(payload.get("optimizer_constructed") is False, f"calibration_observation_optimizer_constructed:{lane}")
        require(payload.get("optimizer_steps_before_observation") == 0, f"calibration_observation_optimizer_steps:{lane}")
        require(payload.get("outer_metrics_access_count") == 0, f"calibration_observation_outer_access:{lane}")
        require(payload.get("prediction_metrics_access_count") == 0, f"calibration_observation_prediction_access:{lane}")
        require(payload.get("v4_f_test32_access_count") == 0, f"calibration_observation_sealed_access:{lane}")
        require(payload.get("fixed_grid") == contract["fixed_grid"], f"calibration_observation_grid:{lane}")
        require(payload.get("pair_to_marginal_ratio") == contract["pair_to_marginal_ratio"], f"calibration_observation_ratio:{lane}")
        require(payload.get("target_gradient_fraction_band") == contract["target_gradient_fraction_band"], f"calibration_observation_band:{lane}")
        require(payload.get("selection_rule") == "smallest_grid_value_in_target_band_before_optimizer_construction", f"calibration_observation_selection_rule:{lane}")
        require(payload.get("claim_boundary") == manifest["claim_boundary"], f"calibration_observation_claim_boundary:{lane}")
        split = payload.get("split")
        require(isinstance(split, dict), f"calibration_observation_split:{lane}")
        require(split.get("outer_fold") == 0, f"calibration_observation_outer_fold:{lane}")
        require(split.get("open_only") is True, f"calibration_observation_split_not_open:{lane}")
        require(split.get("v4_f_test32_access_count") == 0, f"calibration_observation_split_sealed_access:{lane}")
        require(split.get("fixed_epochs") == manifest["trainer"]["frozen_noncalibration_parameters"]["fixed_epochs"], f"calibration_observation_fixed_epochs:{lane}")
        require(isinstance(payload.get("observed_training_batch_candidate_ids"), list) and payload["observed_training_batch_candidate_ids"], f"calibration_observation_batch_empty:{lane}")
        selected = _validate_observation_grid(payload, manifest, lane)
        require(record.get("selected_contact_weights") == selected, f"calibration_observation_record_weights:{lane}")
        expected_command = calibration_command(manifest, lane, observation_path.parent)
        require(record.get("command_sha256") == command_sha256(expected_command), f"calibration_observation_command_sha256:{lane}")
        weights[lane] = selected
    require(receipt.get("frozen_lane_contact_weights") == weights, "calibration_receipt_frozen_weights")
    return receipt, weights


def _weight_text(value: float) -> str:
    require(math.isfinite(value) and value >= 0, "contact_weight_nonfinite_or_negative")
    return repr(float(value))


def frozen_lane_argv(weights: Mapping[str, Mapping[str, float]]) -> dict[str, list[str]]:
    require(set(weights) == set(LANES), "lane_weight_closure")
    result: dict[str, list[str]] = {}
    for lane in LANES:
        lane_weights = weights[lane]
        require(set(lane_weights) == {"marginal", "pair"}, f"lane_weight_fields:{lane}")
        result[lane] = [
            "--marginal-weight", _weight_text(float(lane_weights["marginal"])),
            "--pair-weight", _weight_text(float(lane_weights["pair"])),
        ]
    return result


def outer_development_argv(manifest: Mapping[str, Any]) -> list[str]:
    frozen = manifest["trainer"]["frozen_noncalibration_parameters"]
    return [
        "--backbone-kind", "hf",
        "--fixed-epochs", str(frozen["fixed_epochs"]),
        "--graph-hidden-dim", str(frozen["graph_hidden_dim"]),
        "--dropout", str(frozen["dropout"]),
        "--batch-size", str(frozen["batch_size"]),
        "--device", "cuda",
        "--precision", str(frozen["precision"]),
    ]


def validate_test_alias(
    alias_path: pathlib.Path | None,
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if alias_path is None:
        return []
    try:
        metadata = alias_path.lstat()
    except FileNotFoundError as exc:
        raise FreezeMaterializationError(f"test_alias_missing:{alias_path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"test_alias_not_regular_or_symlink:{alias_path}")
    canonical = pathlib.Path(manifest["artifacts"]["contact_formula"]["node1_path"])
    require(alias_path != canonical, "test_alias_must_not_equal_production_formula_path")
    digest = sha256_file(alias_path)
    require(digest == manifest["artifacts"]["contact_formula"]["sha256"], "test_alias_formula_sha256")
    template_text = "\0".join(manifest["trainer"]["argv_template"])
    require(str(alias_path) not in template_text, "test_alias_referenced_by_production_argv")
    require(all(str(alias_path) != record["node1_path"] for record in manifest["artifacts"].values()), "test_alias_must_not_be_formal_artifact")
    return [{
        "role": "TEST_IMPORT_LAYOUT_COMPATIBILITY_ONLY",
        "path": str(alias_path),
        "sha256": digest,
        "size_bytes": metadata.st_size,
        "production_input": False,
        "formal_artifact": False,
    }]


def atomic_json(path: pathlib.Path, payload: Mapping[str, Any]) -> None:
    require(path.is_absolute(), f"output_not_absolute:{path}")
    require(not os.path.lexists(path), f"output_already_exists:{path}")
    require(path.parent.is_dir() and not path.parent.is_symlink(), f"output_parent_missing_or_symlink:{path.parent}")
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(content)
        temporary = pathlib.Path(handle.name)
    try:
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def materialize(
    *,
    prefreeze_manifest_path: pathlib.Path,
    calibration_receipt_path: pathlib.Path,
    ready_manifest_path: pathlib.Path,
    freeze_path: pathlib.Path,
    test_only_contact_formula_alias: pathlib.Path | None = None,
) -> dict[str, Any]:
    require(ready_manifest_path != freeze_path, "ready_and_freeze_output_collision")
    require(ready_manifest_path.name == "V2_4_NODE1_READY_MANIFEST_V1.json", "ready_manifest_filename")
    require(freeze_path.name == "IMPLEMENTATION_FREEZE_V2_4.json", "implementation_freeze_filename")
    require(not os.path.lexists(ready_manifest_path), f"ready_manifest_exists:{ready_manifest_path}")
    require(not os.path.lexists(freeze_path), f"implementation_freeze_exists:{freeze_path}")
    manifest = validate_prefreeze_manifest(prefreeze_manifest_path)
    bundle_root = pathlib.Path(manifest["bundle_root"])
    require(
        prefreeze_manifest_path == bundle_root / "V2_4_NODE1_PREFREEZE_MANIFEST_V1.json",
        "prefreeze_manifest_noncanonical_path",
    )
    require(
        ready_manifest_path == bundle_root / "V2_4_NODE1_READY_MANIFEST_V1.json",
        "ready_manifest_noncanonical_path",
    )
    require(
        freeze_path == bundle_root / "IMPLEMENTATION_FREEZE_V2_4.json",
        "implementation_freeze_noncanonical_path",
    )
    formula = validate_formula(manifest)
    receipt, weights = validate_calibration_receipt(prefreeze_manifest_path, manifest, calibration_receipt_path)
    test_aliases = validate_test_alias(test_only_contact_formula_alias, manifest)

    receipt_digest = sha256_file(calibration_receipt_path)
    ready = copy.deepcopy(manifest)
    ready["status"] = READY_STATUS
    ready["production_authorized"] = False
    ready["source_prefreeze_manifest_sha256"] = sha256_file(prefreeze_manifest_path)
    ready["artifacts"]["calibration_receipt"] = {
        "source_path": str(calibration_receipt_path),
        "node1_path": manifest["calibration_contract"]["calibration_receipt_node1_path"],
        "sha256": receipt_digest,
        "size_bytes": calibration_receipt_path.stat().st_size,
        "validation_mode": "LOCAL_SOURCE_AND_NODE1",
    }
    ready["trainer"]["outer_development_extra_argv"] = outer_development_argv(manifest)
    ready["trainer"]["lane_outer_extra_argv"] = frozen_lane_argv(weights)
    ready["calibration_contract"].update({
        "binding_status": "FROZEN_OPEN_ONLY_PRESTEP_CALIBRATION",
        "receipt_artifact_label": "calibration_receipt",
        "receipt_sha256": receipt_digest,
        "frozen_lane_contact_weights": weights,
        "optimizer_constructed_before_observation": False,
        "contact_formula_sha256": manifest["artifacts"]["contact_formula"]["sha256"],
        "contact_formula_version": formula["formula_version"],
    })
    ready["pending"] = []
    ready["implementation_freeze_required"] = True
    ready["implementation_freeze_path"] = str(freeze_path)
    ready["runtime_absent_at_ready_manifest_materialization"] = True
    ready["sealed_evaluation_access_count"] = 0
    ready["prediction_metrics_access_count"] = 0
    atomic_json(ready_manifest_path, ready)

    formal_artifacts = {label: record["sha256"] for label, record in sorted(ready["artifacts"].items())}
    launcher_sha = ready["artifacts"]["deployment_launcher"]["sha256"]
    freeze = {
        "schema_version": "pvrig_v6_residue_v2_4_implementation_freeze_v1",
        "status": FREEZE_STATUS,
        "production_authorized": False,
        "production_training_started": False,
        "production_runtime_created": False,
        "runtime_absent_at_freeze": True,
        "manifest_path": str(ready_manifest_path),
        "manifest_sha256": sha256_file(ready_manifest_path),
        "source_prefreeze_manifest_path": str(prefreeze_manifest_path),
        "source_prefreeze_manifest_sha256": sha256_file(prefreeze_manifest_path),
        "calibration_receipt_path": str(calibration_receipt_path),
        "calibration_receipt_sha256": receipt_digest,
        "calibration_receipt_status": receipt["status"],
        "launcher_sha256": launcher_sha,
        "materializer_sha256": ready["artifacts"]["postcalibration_materializer"]["sha256"],
        "formal_artifact_sha256": formal_artifacts,
        "formal_artifact_count": len(formal_artifacts),
        "test_only_artifact_aliases": test_aliases,
        "node1_execution_contract": {
            "python": NODE1_PYTHON,
            "lane_gpu_map": LANE_GPU,
            "cpu_threads_per_process": 8,
            "thread_environment": THREAD_ENVIRONMENT,
        },
        "phase_order": PHASE_ORDER,
        "frozen_lane_contact_weights": weights,
        "lane_outer_extra_argv": ready["trainer"]["lane_outer_extra_argv"],
        "outer_development_extra_argv": ready["trainer"]["outer_development_extra_argv"],
        "contact_formula": {
            "sha256": manifest["artifacts"]["contact_formula"]["sha256"],
            "formula_version": formula["formula_version"],
            "weights": formula["weights"],
            "intercept": formula["intercept"],
            "label_access": formula["label_access"],
            "outer_result_tuning": formula["outer_result_tuning"],
            "calibration_command_hash_bound": True,
        },
        "calibration_evidence": {
            "open_only": True,
            "optimizer_constructed_before_observation": False,
            "optimizer_steps_before_observation": 0,
            "fixed_grid": manifest["calibration_contract"]["fixed_grid"],
            "target_gradient_fraction_band": manifest["calibration_contract"]["target_gradient_fraction_band"],
            "pair_to_marginal_ratio": manifest["calibration_contract"]["pair_to_marginal_ratio"],
            "lane_observation_sha256": {
                lane: receipt["lane_observations"][lane]["sha256"] for lane in CONTACT_LANES
            },
            "lane_command_sha256": {
                lane: receipt["lane_observations"][lane]["command_sha256"] for lane in CONTACT_LANES
            },
        },
        "sealed_evaluation_access_count": 0,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
        "pending": [],
        "next_permitted_action": "Run the four-lane Node1 tiny smoke through the frozen launcher; outer development remains smoke-gated.",
        "claim_boundary": manifest["claim_boundary"],
    }
    try:
        atomic_json(freeze_path, freeze)
    except Exception:
        ready_manifest_path.unlink(missing_ok=True)
        raise
    return {
        "status": FREEZE_STATUS,
        "ready_manifest_path": str(ready_manifest_path),
        "ready_manifest_sha256": sha256_file(ready_manifest_path),
        "implementation_freeze_path": str(freeze_path),
        "implementation_freeze_sha256": sha256_file(freeze_path),
        "formal_artifact_count": len(formal_artifacts),
        "test_only_alias_count": len(test_aliases),
        "production_runtime_created": False,
        "production_training_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefreeze-manifest", type=pathlib.Path, required=True)
    parser.add_argument("--calibration-receipt", type=pathlib.Path, required=True)
    parser.add_argument("--ready-manifest", type=pathlib.Path, required=True)
    parser.add_argument("--implementation-freeze", type=pathlib.Path, required=True)
    parser.add_argument("--test-only-contact-formula-alias", type=pathlib.Path)
    args = parser.parse_args()
    result = materialize(
        prefreeze_manifest_path=args.prefreeze_manifest,
        calibration_receipt_path=args.calibration_receipt,
        ready_manifest_path=args.ready_manifest,
        freeze_path=args.implementation_freeze,
        test_only_contact_formula_alias=args.test_only_contact_formula_alias,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FreezeMaterializationError, OSError, json.JSONDecodeError, ValueError, TypeError) as error:
        print(f"FAIL_V2_4_POSTCALIBRATION_FREEZE:{error}", file=os.sys.stderr)
        raise SystemExit(1)
