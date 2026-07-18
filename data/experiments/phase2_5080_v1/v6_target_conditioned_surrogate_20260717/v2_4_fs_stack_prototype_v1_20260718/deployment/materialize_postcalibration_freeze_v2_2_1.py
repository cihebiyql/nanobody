#!/usr/bin/env python3
"""Materialize V2.2.1 from its corrected immutable prefreeze manifest.

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


PENDING_STATUS = "PREFREEZE_V2_2_1_ADAPTIVE_MULTI_SEED_CALIBRATION_PENDING_DO_NOT_START"
READY_STATUS = "PREFREEZE_V2_2_1_ADAPTIVE_MULTI_SEED_READY_DO_NOT_START"
FREEZE_SCHEMA = "pvrig_v6_residue_v2_4_implementation_freeze_v2_2_1_status_constant_corrected"
FREEZE_STATUS = "PASS_V2_4_ADAPTIVE_MULTI_SEED_IMPLEMENTATION_V2_2_1_FROZEN_FOR_TINY_SMOKE_AND_OUTER_DEVELOPMENT"
CALIBRATION_STATUS = "PASS_OPEN_ONLY_PRESTEP_CONTACT_GRADIENT_CALIBRATION_V2_4_ADAPTIVE_V2_2_1_STATUS_CONSTANT_CORRECTED"
OBSERVATION_STATUS = "PASS_OPEN_ONLY_PRESTEP_MULTIBATCH_CONTACT_GRADIENT_LANE_OBSERVATION_V2_4_V2_2_CLAIM_ALIGNED"
CALIBRATION_SCHEMA = "pvrig_v6_residue_v2_4_open_only_prestep_calibration_receipt_v2_2_1_status_constant_corrected"
OBSERVATION_SCHEMA = "pvrig_v2_4_open_only_prestep_multibatch_gradient_observation_v2_2_claim_aligned"
MANIFEST_SCHEMA = "pvrig_v6_residue_v2_4_node1_deployment_manifest_v2_2_1_status_constant_corrected"
ADAPTIVE_INPUT_STATUS = "FROZEN_V2_4_ADAPTIVE_MULTI_SEED_DUAL_SOURCE_INPUTS"
ADAPTIVE_TEACHER_GENERATION = "V4D_MULTI_SEED_PLUS_V4H_ADAPTIVE_MULTI_SEED_V2"
SUPERSESSION_VERSION = "V2.2_CLAIM_BOUNDARY_ALIGNMENT_ONLY"
BUNDLE_REVISION = "V2.2.1_STATUS_CONSTANT_ONLY"
TRAINER_RESULT_CLAIM_BOUNDARY = (
    "Open-only computational surrogate of independent 8X6B/9E6Y Docking "
    "geometry; not binding probability, affinity, experimental blocking, "
    "Docking Gold, or submission evidence."
)
CLAIM_BOUNDARY = (
    "Open-only adaptive-multiseed independent 8X6B/9E6Y computational Docking "
    "geometry surrogate; not binding, affinity, experimental blocking, Docking Gold, "
    "or submission evidence."
)
EXPECTED_CONTACT_WEIGHTS = {
    "C_SPLIT_MARGINAL": {"marginal": 1.5, "pair": 0.0},
    "D_SPLIT_PAIR": {"marginal": 1.0, "pair": 0.5},
}
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
OBSERVATION_SELECTION_RULE = (
    "smallest_grid_value_with_median_in_band_and_per_batch_max_at_or_below_ceiling_"
    "before_optimizer_construction"
)
RECEIPT_SELECTION_RULE = (
    "per_contact_lane_smallest_grid_value_with_median_in_band_and_per_batch_max_"
    "at_or_below_ceiling_before_optimizer_construction"
)
MANIFEST_SELECTION_RULE = (
    "per_lane_smallest_grid_value_with_median_in_band_and_per_batch_max_at_or_below_"
    "ceiling_before_optimizer_step"
)
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
    require(manifest.get("schema_version") == MANIFEST_SCHEMA, "prefreeze_manifest_schema")
    require(manifest.get("manifest_generation") == "V2_2_1_STATUS_CONSTANT_CORRECTED", "prefreeze_manifest_generation")
    require(manifest.get("status") == PENDING_STATUS, "prefreeze_manifest_status")
    require(manifest.get("production_authorized") is False, "prefreeze_production_authorized")
    require(manifest.get("claim_boundary") == CLAIM_BOUNDARY, "prefreeze_claim_boundary")
    require(manifest.get("trainer_result_claim_boundary") == TRAINER_RESULT_CLAIM_BOUNDARY,
            "prefreeze_trainer_result_claim_boundary")
    supersession = manifest.get("technical_supersession") or {}
    require(supersession.get("version") == SUPERSESSION_VERSION, "prefreeze_supersession_version")
    require(supersession.get("bundle_revision") == BUNDLE_REVISION, "prefreeze_bundle_revision")
    require(supersession.get("numeric_method_changes") == 0, "prefreeze_numeric_method_change")
    require(supersession.get("v2_1_selected_contact_weights") == EXPECTED_CONTACT_WEIGHTS,
            "prefreeze_v2_1_weight_contract")
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
        "trainer", "calibration_trainer", "prefreeze_builder",
        "calibration_runner", "calibration_runner_test", "deployment_launcher",
        "deployment_launcher_test", "contact_formula", "postcalibration_materializer",
        "postcalibration_materializer_test", "v2_migration_test",
        "bundle_materializer", "v2_2_supersession_audit", "v2_2_1_status_supersession_audit",
        "adaptive_input_contract", "v4h_adaptive_source_receipt",
        "v4d_source_receipt",
        "adaptive_marginal_tsv_gz", "adaptive_marginal_receipt",
        "adaptive_pair_tsv_gz", "adaptive_pair_receipt",
    }
    require(required <= set(artifacts), "required_formal_artifact_missing")
    for label, record in sorted(artifacts.items()):
        validate_artifact_record(label, record)
    require(
        artifacts["postcalibration_materializer"]["sha256"]
        == sha256_file(pathlib.Path(__file__).resolve()),
        "running_materializer_not_bound_by_prefreeze_manifest",
    )
    adaptive = manifest.get("adaptive_supervision") or {}
    require(adaptive.get("status") == ADAPTIVE_INPUT_STATUS, "adaptive_supervision_status")
    require(adaptive.get("teacher_generation") == ADAPTIVE_TEACHER_GENERATION, "adaptive_teacher_generation")
    require(adaptive.get("legacy_stage1_inputs_forbidden") is True, "adaptive_legacy_stage1_gate")
    require(adaptive.get("input_contract_sha256") == artifacts["adaptive_input_contract"]["sha256"], "adaptive_contract_sha")
    require(adaptive.get("source_receipt_sha256") == artifacts["v4h_adaptive_source_receipt"]["sha256"], "adaptive_source_receipt_sha")
    require(adaptive.get("v4d_source_receipt_sha256") == artifacts["v4d_source_receipt"]["sha256"], "adaptive_v4d_source_receipt_sha")
    trainer = manifest.get("trainer") or {}
    require(trainer.get("artifact_label") == "trainer", "trainer_artifact_label")
    require(trainer.get("calibration_artifact_label") == "calibration_trainer", "calibration_trainer_artifact_label")
    template = trainer.get("argv_template")
    require(isinstance(template, list) and template, "trainer_argv_template")
    require(template.count("--contact-formula-json") == 1, "contact_formula_flag_must_be_unique")
    formula_index = template.index("--contact-formula-json")
    require(formula_index + 1 < len(template) and template[formula_index + 1] == "{contact_formula}", "contact_formula_placeholder_binding")
    require(trainer.get("outer_development_extra_argv") is None, "prefreeze_outer_argv_must_be_null")
    require(trainer.get("lane_outer_extra_argv") is None, "prefreeze_lane_argv_must_be_null")

    contract = manifest.get("calibration_contract") or {}
    require(contract.get("binding_status") == "PENDING_V2_2_1_ADAPTIVE_OPEN_ONLY_PRESTEP_CALIBRATION", "calibration_binding_status")
    require(contract.get("receipt_artifact_label") is None, "calibration_receipt_label_must_be_null")
    require(contract.get("frozen_lane_contact_weights") is None, "prefreeze_weights_must_be_null")
    require(contract.get("open_only") is True, "calibration_open_only_contract")
    require(contract.get("optimizer_steps_before_observation") == 0, "calibration_prestep_contract")
    require(contract.get("outer_metrics_access_count") == 0, "calibration_outer_access_contract")
    require(contract.get("prediction_metrics_access_count") == 0, "calibration_prediction_access_contract")
    grid = contract.get("fixed_grid")
    require(isinstance(grid, list) and grid == sorted(set(grid)) and all(isinstance(x, (int, float)) and x > 0 for x in grid), "calibration_grid_contract")
    band = contract.get("target_median_gradient_fraction_band")
    require(isinstance(band, list) and len(band) == 2 and 0 <= float(band[0]) <= float(band[1]) <= 1, "calibration_band_contract")
    ceiling = contract.get("maximum_per_batch_gradient_fraction")
    require(
        isinstance(ceiling, (int, float)) and float(band[1]) <= float(ceiling) <= 1,
        "calibration_maximum_fraction_contract",
    )
    ratio = contract.get("pair_to_marginal_ratio")
    require(isinstance(ratio, (int, float)) and 0 < float(ratio) <= 1, "calibration_pair_ratio_contract")
    require(contract.get("attention_temperatures") == {"8x6b": 1.0, "9e6y": 1.0}, "attention_temperature_contract")
    require(contract.get("selection_rule") == MANIFEST_SELECTION_RULE, "calibration_selection_rule_contract")
    batches = contract.get("batch_selection")
    require(isinstance(batches, dict), "calibration_batch_selection_contract")
    require(batches.get("selection_algorithm") == "evenly_spaced_complete_batches_after_python_random_seed_shuffle_v1", "calibration_batch_algorithm")
    require(batches.get("seed") == 43 and batches.get("batch_size") == 8, "calibration_batch_seed_or_size")
    batch_records = batches.get("batch_records")
    require(isinstance(batch_records, list) and len(batch_records) == 8, "calibration_batch_record_count")
    require(len({record["batch_offset"] for record in batch_records}) == 8, "calibration_batch_offsets_duplicate")
    require(len({candidate for record in batch_records for candidate in record["candidate_ids"]}) == 64, "calibration_batch_candidate_reuse")
    require(isinstance(batches.get("contract_sha256"), str) and len(batches["contract_sha256"]) == 64, "calibration_batch_contract_sha")
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
        "trainer": artifacts[manifest["trainer"]["calibration_artifact_label"]]["node1_path"],
        "lane": lane,
        "outer_fold": "0",
        "output_dir": str(output_dir),
        "split_manifest": artifacts["outer_split_0"]["node1_path"],
        "vhh_graph_dir": str(pathlib.Path(artifacts["vhh_graph_cache_npz"]["node1_path"]).parent),
    }
    values.update({label: record["node1_path"] for label, record in artifacts.items()})
    values["trainer"] = artifacts[manifest["trainer"]["calibration_artifact_label"]]["node1_path"]
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
        "--target-gradient-fraction-band", *[str(value) for value in contract["target_median_gradient_fraction_band"]],
        "--maximum-per-batch-gradient-fraction", str(contract["maximum_per_batch_gradient_fraction"]),
        "--calibration-batch-offsets",
        *[str(record["batch_offset"]) for record in contract["batch_selection"]["batch_records"]],
        "--expected-calibration-batch-candidate-sha256",
        *[str(record["candidate_ids_sha256"]) for record in contract["batch_selection"]["batch_records"]],
    ])
    require(command[1] == values["trainer"], "calibration_command_not_using_v2_2_wrapper")
    require(command[1] != artifacts[manifest["trainer"]["artifact_label"]]["node1_path"],
            "calibration_command_uses_base_trainer")
    return command


def _validate_observation_grid(payload: Mapping[str, Any], manifest: Mapping[str, Any], lane: str) -> dict[str, float]:
    contract = manifest["calibration_contract"]
    grid = [float(value) for value in contract["fixed_grid"]]
    ratio = float(contract["pair_to_marginal_ratio"])
    lower, upper = (float(value) for value in contract["target_median_gradient_fraction_band"])
    maximum_ceiling = float(contract["maximum_per_batch_gradient_fraction"])
    observations = payload.get("observations")
    require(isinstance(observations, list) and len(observations) == len(grid), f"observation_grid_row_count:{lane}")
    eligible: list[dict[str, float]] = []
    for expected_marginal, raw in zip(grid, observations):
        require(isinstance(raw, dict), f"observation_grid_row_invalid:{lane}")
        marginal = float(raw.get("marginal_weight"))
        pair = float(raw.get("pair_weight"))
        per_batch = raw.get("per_batch")
        require(isinstance(per_batch, list) and len(per_batch) == 8, f"observation_per_batch_count:{lane}")
        fractions = []
        for batch_record in per_batch:
            scalar_norm = float(batch_record.get("scalar_gradient_l2_norm"))
            contact_norm = float(batch_record.get("contact_gradient_l2_norm"))
            fraction = float(batch_record.get("contact_gradient_fraction"))
            require(
                math.isfinite(scalar_norm) and scalar_norm >= 0
                and math.isfinite(contact_norm) and contact_norm >= 0,
                f"observation_gradient_norm:{lane}",
            )
            denominator = scalar_norm + contact_norm
            expected_fraction = contact_norm / denominator if denominator > 0 else 0.0
            require(
                math.isfinite(fraction) and abs(fraction - expected_fraction) <= 1e-12,
                f"observation_gradient_fraction:{lane}",
            )
            cosine = batch_record.get("scalar_contact_cosine")
            require(cosine is None or math.isfinite(float(cosine)), f"observation_gradient_cosine:{lane}")
            groups = batch_record.get("gradient_groups")
            require(
                isinstance(groups, dict)
                and set(groups) == {
                    "shared_encoder", "pair_factors", "attention_contact_terminals", "scalar_head",
                },
                f"observation_gradient_groups:{lane}",
            )
            for group_record in groups.values():
                require(
                    isinstance(group_record.get("parameter_tensor_count"), int)
                    and group_record["parameter_tensor_count"] > 0,
                    f"observation_gradient_group_parameter_count:{lane}",
                )
                for field in ("scalar_gradient_l2_norm", "contact_gradient_l2_norm"):
                    value = float(group_record.get(field))
                    require(math.isfinite(value) and value >= 0, f"observation_gradient_group_norm:{lane}")
                group_cosine = group_record.get("scalar_contact_cosine")
                require(
                    group_cosine is None or math.isfinite(float(group_cosine)),
                    f"observation_gradient_group_cosine:{lane}",
                )
            fractions.append(fraction)
        ordered = sorted(fractions)
        median = (ordered[3] + ordered[4]) / 2.0
        maximum = max(fractions)
        require(marginal == expected_marginal, f"observation_grid_order:{lane}")
        expected_pair = 0.0 if lane == "C_SPLIT_MARGINAL" else marginal * ratio
        require(abs(pair - expected_pair) <= 1e-15, f"observation_pair_ratio:{lane}")
        require(abs(float(raw.get("median_contact_gradient_fraction")) - median) <= 1e-12, f"observation_median_mismatch:{lane}")
        require(abs(float(raw.get("maximum_contact_gradient_fraction")) - maximum) <= 1e-12, f"observation_maximum_mismatch:{lane}")
        expected_eligible = lower <= median <= upper and maximum <= maximum_ceiling
        require(raw.get("eligible") is expected_eligible, f"observation_eligibility_mismatch:{lane}")
        if expected_eligible:
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
    require(receipt.get("calibration_trainer_sha256") == manifest["artifacts"]["calibration_trainer"]["sha256"], "calibration_receipt_calibration_trainer_sha256")
    require(receipt.get("calibration_runner_sha256") == manifest["artifacts"]["calibration_runner"]["sha256"], "calibration_receipt_runner_sha256")
    require(receipt.get("open_only") is True, "calibration_receipt_not_open_only")
    require(receipt.get("optimizer_constructed_before_observation") is False, "calibration_receipt_optimizer_constructed")
    require(receipt.get("optimizer_steps_before_observation") == 0, "calibration_receipt_optimizer_steps")
    require(receipt.get("outer_metrics_access_count") == 0, "calibration_receipt_outer_access")
    require(receipt.get("prediction_metrics_access_count") == 0, "calibration_receipt_prediction_access")
    require(receipt.get("v4_f_test32_access_count") == 0, "calibration_receipt_sealed_access")
    require(receipt.get("fixed_grid") == contract["fixed_grid"], "calibration_receipt_grid")
    require(receipt.get("pair_to_marginal_ratio") == contract["pair_to_marginal_ratio"], "calibration_receipt_pair_ratio")
    require(receipt.get("target_median_gradient_fraction_band") == contract["target_median_gradient_fraction_band"], "calibration_receipt_band")
    require(receipt.get("maximum_per_batch_gradient_fraction") == contract["maximum_per_batch_gradient_fraction"], "calibration_receipt_maximum_fraction")
    require(receipt.get("calibration_batch_count") == 8, "calibration_receipt_batch_count")
    require(receipt.get("calibration_batch_contract_sha256") == contract["batch_selection"]["contract_sha256"], "calibration_receipt_batch_contract_sha")
    require(receipt.get("attention_temperatures") == contract["attention_temperatures"], "calibration_receipt_temperatures")
    require(receipt.get("selection_rule") == RECEIPT_SELECTION_RULE, "calibration_receipt_selection_rule")
    require(receipt.get("implementation_freeze_created") is False, "calibration_receipt_prior_freeze")
    require(receipt.get("production_runtime_created") is False, "calibration_receipt_prior_runtime")
    require(receipt.get("claim_boundary") == manifest["claim_boundary"], "calibration_receipt_claim_boundary")
    require(receipt.get("technical_supersession_version") == SUPERSESSION_VERSION,
            "calibration_receipt_supersession_version")
    require(receipt.get("bundle_revision") == BUNDLE_REVISION, "calibration_receipt_bundle_revision")
    require(receipt.get("trainer_result_claim_boundary") == TRAINER_RESULT_CLAIM_BOUNDARY,
            "calibration_receipt_trainer_result_claim_boundary")
    require(receipt.get("v2_1_selected_weight_equivalence_required") == EXPECTED_CONTACT_WEIGHTS,
            "calibration_receipt_v2_1_weight_contract")
    adaptive = manifest["adaptive_supervision"]
    require(receipt.get("adaptive_input_contract_sha256") == adaptive["input_contract_sha256"], "calibration_receipt_adaptive_contract_sha")
    require(receipt.get("adaptive_source_receipt_sha256") == adaptive["source_receipt_sha256"], "calibration_receipt_adaptive_source_sha")
    require(receipt.get("adaptive_v4d_source_receipt_sha256") == adaptive["v4d_source_receipt_sha256"], "calibration_receipt_adaptive_v4d_source_sha")
    require(receipt.get("adaptive_teacher_generation") == ADAPTIVE_TEACHER_GENERATION, "calibration_receipt_adaptive_generation")

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
        require(payload.get("target_median_gradient_fraction_band") == contract["target_median_gradient_fraction_band"], f"calibration_observation_band:{lane}")
        require(payload.get("maximum_per_batch_gradient_fraction") == contract["maximum_per_batch_gradient_fraction"], f"calibration_observation_maximum_fraction:{lane}")
        require(payload.get("selection_rule") == OBSERVATION_SELECTION_RULE, f"calibration_observation_selection_rule:{lane}")
        require(payload.get("claim_boundary") == manifest["claim_boundary"], f"calibration_observation_claim_boundary:{lane}")
        require(payload.get("technical_supersession_version") == SUPERSESSION_VERSION,
                f"calibration_observation_supersession_version:{lane}")
        split = payload.get("split")
        require(isinstance(split, dict), f"calibration_observation_split:{lane}")
        require(split.get("outer_fold") == 0, f"calibration_observation_outer_fold:{lane}")
        require(split.get("open_only") is True, f"calibration_observation_split_not_open:{lane}")
        require(split.get("v4_f_test32_access_count") == 0, f"calibration_observation_split_sealed_access:{lane}")
        require(split.get("fixed_epochs") == manifest["trainer"]["frozen_noncalibration_parameters"]["fixed_epochs"], f"calibration_observation_fixed_epochs:{lane}")
        expected_batches = contract["batch_selection"]["batch_records"]
        require(payload.get("calibration_batch_count") == 8, f"calibration_observation_batch_count:{lane}")
        require(payload.get("calibration_batch_offsets") == [record["batch_offset"] for record in expected_batches], f"calibration_observation_batch_offsets:{lane}")
        provenance = payload.get("calibration_batch_provenance")
        require(isinstance(provenance, list) and len(provenance) == 8, f"calibration_observation_provenance:{lane}")
        for observed, expected in zip(provenance, expected_batches):
            require(observed.get("batch_id") == expected["batch_id"], f"calibration_observation_batch_id:{lane}")
            require(observed.get("batch_offset") == expected["batch_offset"], f"calibration_observation_batch_offset:{lane}")
            require(observed.get("forward_seed") == expected["forward_seed"], f"calibration_observation_batch_forward_seed:{lane}")
            require(observed.get("candidate_ids") == expected["candidate_ids"], f"calibration_observation_batch_ids:{lane}")
            require(observed.get("candidate_ids_sha256") == expected["candidate_ids_sha256"], f"calibration_observation_batch_sha:{lane}")
            require(observed.get("candidate_count") == expected["candidate_count"], f"calibration_observation_batch_count_field:{lane}")
            require(observed.get("teacher_source_counts") == expected["teacher_source_counts"], f"calibration_observation_batch_teacher_sources:{lane}")
            require(observed.get("contact_tier_counts") == expected["contact_tier_counts"], f"calibration_observation_batch_contact_tiers:{lane}")
            require(
                observed.get("parent_framework_clusters") == expected["parent_framework_clusters"],
                f"calibration_observation_batch_parents:{lane}",
            )
        selected = _validate_observation_grid(payload, manifest, lane)
        require(selected == EXPECTED_CONTACT_WEIGHTS[lane], f"calibration_v2_1_weight_equivalence:{lane}")
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
    require(ready_manifest_path.name == "V2_4_NODE1_READY_MANIFEST_V2_2_1.json", "ready_manifest_filename")
    require(freeze_path.name == "IMPLEMENTATION_FREEZE_V2_4_ADAPTIVE_V2_2_1.json", "implementation_freeze_filename")
    require(not os.path.lexists(ready_manifest_path), f"ready_manifest_exists:{ready_manifest_path}")
    require(not os.path.lexists(freeze_path), f"implementation_freeze_exists:{freeze_path}")
    manifest = validate_prefreeze_manifest(prefreeze_manifest_path)
    bundle_root = pathlib.Path(manifest["bundle_root"])
    require(
        prefreeze_manifest_path == bundle_root / "V2_4_NODE1_PREFREEZE_MANIFEST_V2_2_1.json",
        "prefreeze_manifest_noncanonical_path",
    )
    require(
        ready_manifest_path == bundle_root / "V2_4_NODE1_READY_MANIFEST_V2_2_1.json",
        "ready_manifest_noncanonical_path",
    )
    require(
        freeze_path == bundle_root / "IMPLEMENTATION_FREEZE_V2_4_ADAPTIVE_V2_2_1.json",
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
        "binding_status": "FROZEN_V2_2_1_ADAPTIVE_OPEN_ONLY_PRESTEP_CALIBRATION",
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
        "schema_version": FREEZE_SCHEMA,
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
            "target_median_gradient_fraction_band": manifest["calibration_contract"]["target_median_gradient_fraction_band"],
            "maximum_per_batch_gradient_fraction": manifest["calibration_contract"]["maximum_per_batch_gradient_fraction"],
            "calibration_batch_count": 8,
            "calibration_batch_contract_sha256": manifest["calibration_contract"]["batch_selection"]["contract_sha256"],
            "pair_to_marginal_ratio": manifest["calibration_contract"]["pair_to_marginal_ratio"],
            "lane_observation_sha256": {
                lane: receipt["lane_observations"][lane]["sha256"] for lane in CONTACT_LANES
            },
            "lane_command_sha256": {
                lane: receipt["lane_observations"][lane]["command_sha256"] for lane in CONTACT_LANES
            },
        },
        "adaptive_supervision": copy.deepcopy(manifest["adaptive_supervision"]),
        "sealed_evaluation_access_count": 0,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
        "pending": [],
        "next_permitted_action": "Run the four-lane Node1 tiny smoke through the frozen launcher; outer development remains smoke-gated.",
        "claim_boundary": manifest["claim_boundary"],
        "trainer_result_claim_boundary": manifest["trainer_result_claim_boundary"],
        "bundle_revision": BUNDLE_REVISION,
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
        print(f"FAIL_V2_4_ADAPTIVE_V2_2_1_POSTCALIBRATION_FREEZE:{error}", file=os.sys.stderr)
        raise SystemExit(1)
