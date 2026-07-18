#!/usr/bin/env python3
"""Run the open-only Residue V2 contact-gradient calibration on Node1.

This launcher is intentionally separate from the formal OOF deployment.  It
V1_1 closes the full repo-local import graph and runs one full1507, outer-fold-0, one-epoch smoke per lane, reads only the first
pre-optimizer gradient observation, and invokes the frozen grid selector.  It
never updates the production matrix/freeze and never opens V4-F/test32.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


MATRIX_SCHEMA = "pvrig_v6_residue_v2_contact_gradient_calibration_matrix_v1_2"
MATRIX_STATUS = "FROZEN_OPEN_ONLY_PREPRODUCTION_CALIBRATION_MATRIX"
BOOTSTRAP_SCHEMA = "pvrig_v6_residue_v2_contact_gradient_calibration_bootstrap_v1_2"
TERMINAL_SCHEMA = "pvrig_v6_residue_v2_contact_gradient_calibration_terminal_v1_2"
TERMINAL_STATUS = "PASS_OPEN_ONLY_CONTACT_GRADIENT_CALIBRATION_TERMINAL"
OBSERVATION_SCHEMA = "pvrig_v6_residue_v2_contact_gradient_observation_v1"
SELECTOR_STATUS = "PASS_OPEN_ONLY_ONE_BATCH_PRESTEP_GRADIENT_CALIBRATION"
LANES = ("A_DOMAIN", "B_VHH3D", "C_PATCH", "D_FULL_PAIR")
LANE_GPU = {"A_DOMAIN": 1, "B_VHH3D": 2, "C_PATCH": 3, "D_FULL_PAIR": 4}
AUGMENTATION_GPU = 5
OUTER_FOLD = 0
MAX_EPOCHS = 1
FORBIDDEN_PATH_TOKENS = ("v4_f", "test32", "prospective_computational_test")
STATIC_LABELS = {
    "trainer", "residue_model", "augment_target_script", "selector", "preregistration",
    "base_trainer_v1", "base_trainer_v1_5", "base_residue_model_v1", "build_residue_graph_cache_v2", "domain_balance_v2",
    "training_tsv", "training_receipt", "dual_marginal_tsv_gz", "dual_marginal_receipt",
    "pair_contact_tsv_gz", "pair_contact_receipt", "vhh_graph_cache_npz",
    "vhh_graph_manifest", "vhh_graph_closure", "vhh_graph_cache_receipt",
    "vhh_graph_materialization_receipt", "base_target_pt", "base_target_manifest",
    "base_target_receipt", "esm2_650m_model_identity",
}
GRAPH_LANES = {"B_VHH3D", "C_PATCH", "D_FULL_PAIR"}
TARGET_LANES = {"C_PATCH", "D_FULL_PAIR"}
PAIR_LANES = {"D_FULL_PAIR"}
STRUCTURE_PREFIXES = (
    "ALL__",
    "CDR1_CDR2__", "CDR1_CDR3__", "CDR1_FRAMEWORK__", "CDR1__",
    "CDR2_CDR3__", "CDR2_FRAMEWORK__", "CDR2__",
    "CDR3_FRAMEWORK__", "CDR3__", "CDR_ALL__", "FRAMEWORK__",
)
TRAINER_ARGUMENTS = {
    "structure_dim": 126,
    "ridge_alpha": 10.0,
    "graph_hidden_dim": 128,
    "dropout": 0.25,
    "residual_scale": 0.02,
    "huber_delta": 0.03,
    "dual_weight": 1.0,
    "receptor_weight": 0.35,
    "marginal_contact_weight": 0.0001,
    "pair_contact_weight": 0.00005,
    "contact_positive_class_fraction": 0.5,
    "contact_balance_epsilon": 1e-8,
    "component_gradient_telemetry_batches": 1,
    "ranking_weight": 0.0001,
    "ranking_minimum_delta": 0.02,
    "ranking_temperature": 0.03,
    "residual_l2_weight": 0.05,
    "gradient_accumulation": 2,
    "head_learning_rate": 0.0001,
    "weight_decay": 0.02,
    "gradient_clip": 1.0,
    "evaluation_batch_size": 16,
    "precision": "bf16",
    "seed": 43,
}

SCRIPT = Path(__file__).resolve()
DEFAULT_MATRIX = SCRIPT.with_name("CONTACT_GRADIENT_CALIBRATION_MATRIX_V1_2.json")


class CalibrationLaunchError(RuntimeError):
    """Fail-closed calibration deployment error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CalibrationLaunchError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(dict(payload), handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def load_json(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"{label}_missing_or_symlink:{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(payload, dict), f"{label}_not_object")
    return payload


@dataclass(frozen=True)
class Artifact:
    label: str
    path: Path
    sha256: str


@dataclass(frozen=True)
class Context:
    matrix_path: Path
    matrix_sha256: str
    matrix: Mapping[str, Any]
    bundle_root: Path
    runtime_root: Path
    python: Path
    artifacts: Mapping[str, Artifact]


def load_context(matrix_path: Path) -> Context:
    matrix = load_json(matrix_path, "calibration_matrix")
    require(matrix.get("schema_version") == MATRIX_SCHEMA, "matrix_schema_invalid")
    require(matrix.get("status") == MATRIX_STATUS, "matrix_status_invalid")
    require(matrix.get("mode") == "OPEN_ONLY_PREPRODUCTION_NOT_FORMAL_OOF", "matrix_mode_invalid")
    require(matrix.get("outer_fold") == OUTER_FOLD and matrix.get("maximum_epochs") == MAX_EPOCHS, "calibration_fold_or_epoch_invalid")
    require(matrix.get("smoke_mode") is True, "calibration_smoke_mode_required")
    require(matrix.get("lane_gpu_map") == LANE_GPU, "lane_gpu_map_invalid")
    require(matrix.get("augmentation_gpu") == AUGMENTATION_GPU, "augmentation_gpu_invalid")
    sealed = matrix.get("sealed_boundary") or {}
    require(sealed.get("v4_f_test32_access_count") == 0, "matrix_test32_access_nonzero")
    require(sealed.get("prediction_metrics_used_for_selection") is False, "matrix_prediction_metric_selection")
    require(sealed.get("formal_oof_started") is False, "matrix_formal_oof_flag")
    bundle = Path(str(matrix.get("bundle_root", "")))
    runtime = Path(str(matrix.get("runtime_root", "")))
    python = Path(str(matrix.get("python", "")))
    require(bundle.is_absolute() and runtime.is_absolute() and python.is_absolute(), "matrix_absolute_paths_required")
    require(bundle != runtime and not runtime.is_relative_to(bundle), "calibration_root_bundle_overlap")
    raw = matrix.get("artifacts")
    require(isinstance(raw, Mapping) and set(raw) == STATIC_LABELS, "static_artifact_label_closure")
    artifacts: dict[str, Artifact] = {}
    for label, row in raw.items():
        require(isinstance(row, Mapping), f"artifact_record_invalid:{label}")
        path = Path(str(row.get("path", "")))
        digest = row.get("sha256")
        require(path.is_absolute(), f"artifact_path_not_absolute:{label}")
        require(isinstance(digest, str) and len(digest) == 64, f"artifact_sha_invalid:{label}")
        lowered = str(path).lower()
        require(not any(token in lowered for token in FORBIDDEN_PATH_TOKENS), f"sealed_path_forbidden:{label}:{path}")
        artifacts[label] = Artifact(label, path, digest)
    require(matrix.get("original_preregistration_sha256") == artifacts["preregistration"].sha256, "original_prereg_hash_binding")
    require(matrix.get("launcher_sha256") == sha256_file(SCRIPT), "launcher_sha256_mismatch")
    require(matrix.get("trainer_arguments") == TRAINER_ARGUMENTS, "trainer_arguments_invalid")
    require(matrix.get("structure_prefixes") == list(STRUCTURE_PREFIXES), "structure_prefixes_invalid")
    expected_bundle_paths = {
        "trainer": bundle / "residue_v2/src/train_nested_residue_surrogate_v2.py",
        "residue_model": bundle / "residue_v2/src/residue_model_v2.py",
        "augment_target_script": bundle / "residue_v2/src/augment_target_graph_esm2_v2.py",
        "selector": bundle / "residue_v2/src/select_contact_loss_gradient_grid_v1.py",
        "preregistration": bundle / "residue_v2/PREREGISTRATION_V2.json",
        "base_trainer_v1": bundle / "residue_v1/src/train_nested_residue_surrogate.py",
        "base_trainer_v1_5": bundle / "residue_v1/src/train_nested_residue_surrogate_v1_5.py",
        "base_residue_model_v1": bundle / "residue_v1/src/residue_model.py",
        "build_residue_graph_cache_v2": bundle / "residue_v2/src/build_residue_graph_cache_v2.py",
        "domain_balance_v2": bundle / "residue_v2/src/domain_balance_v2.py",
    }
    for label, expected_path in expected_bundle_paths.items():
        require(artifacts[label].path == expected_path, f"bundle_implementation_path_invalid:{label}")
    return Context(matrix_path, sha256_file(matrix_path), matrix, bundle, runtime, python, artifacts)


def validate_static_artifacts(context: Context) -> dict[str, str]:
    observed: dict[str, str] = {}
    for label in sorted(STATIC_LABELS):
        artifact = context.artifacts[label]
        require(artifact.path.is_file() and not artifact.path.is_symlink(), f"artifact_missing_or_symlink:{label}:{artifact.path}")
        actual = sha256_file(artifact.path)
        require(actual == artifact.sha256, f"artifact_sha_mismatch:{label}:{actual}:{artifact.sha256}")
        observed[label] = actual
    prereg = load_json(context.artifacts["preregistration"].path, "original_preregistration")
    require("contact_loss_amendment" not in prereg, "original_preregistration_mutated_with_amendment")
    require(sha256_file(context.artifacts["preregistration"].path) == context.matrix["original_preregistration_sha256"], "original_preregistration_changed")
    return observed


def available_gib(path: Path) -> int:
    usage = shutil.disk_usage(path)
    return int(usage.free // (1024 ** 3))


def probe_gpus(indices: Sequence[int]) -> dict[int, dict[str, int]]:
    command = [
        "nvidia-smi", "--query-gpu=index,memory.used,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    rows: dict[int, dict[str, int]] = {}
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        fields = [int(value.strip()) for value in line.split(",")]
        require(len(fields) == 3, f"gpu_probe_row_invalid:{line}")
        rows[fields[0]] = {"memory_used_mib": fields[1], "utilization_percent": fields[2]}
    require(set(indices) <= set(rows), "gpu_probe_index_missing")
    return {index: rows[index] for index in indices}


def validate_gpu_idle(rows: Mapping[int, Mapping[str, int]]) -> None:
    for index in tuple(LANE_GPU.values()) + (AUGMENTATION_GPU,):
        require(index in rows, f"gpu_idle_record_missing:{index}")
        require(int(rows[index]["memory_used_mib"]) <= 256, f"gpu_memory_not_idle:{index}")
        require(int(rows[index]["utilization_percent"]) <= 10, f"gpu_utilization_not_idle:{index}")


CommandRunner = Callable[[Sequence[str], Mapping[str, str], Path], None]


def subprocess_runner(command: Sequence[str], environment: Mapping[str, str], log_path: Path) -> None:
    completed = subprocess.run(
        list(command), check=False, capture_output=True, text=True, env=dict(environment),
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps({"argv": list(command), "returncode": completed.returncode}, sort_keys=True) +
        "\n--- stdout ---\n" + completed.stdout + "\n--- stderr ---\n" + completed.stderr,
        encoding="utf-8",
    )
    require(completed.returncode == 0, f"command_failed:{completed.returncode}:{command[1] if len(command)>1 else command[0]}")


def base_environment(gpu: int) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update({
        "CUDA_VISIBLE_DEVICES": str(gpu),
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OMP_NUM_THREADS": "8",
        "MKL_NUM_THREADS": "8",
        "OPENBLAS_NUM_THREADS": "8",
        "NUMEXPR_NUM_THREADS": "8",
    })
    return environment


def augmentation_command(context: Context, output_root: Path) -> list[str]:
    a = context.artifacts
    return [
        str(context.python), str(a["augment_target_script"].path),
        "--base-target-pt", str(a["base_target_pt"].path),
        "--target-manifest", str(a["base_target_manifest"].path),
        "--base-target-receipt", str(a["base_target_receipt"].path),
        "--model-path", str(a["esm2_650m_model_identity"].path.parent),
        "--model-identity-file", str(a["esm2_650m_model_identity"].path),
        "--output-dir", str(output_root), "--device", "cuda:0",
    ]


def validate_augmented_delivery(context: Context, root: Path) -> tuple[Path, Path, dict[str, Any]]:
    current = load_json(root / "CURRENT.json", "augmented_current")
    require(current.get("schema_version") == "pvrig_v6_target_graphs_esm2_650m_v2", "augmented_current_schema")
    artifact = root / str(current.get("artifact_relative_path", ""))
    receipt_path = root / str(current.get("receipt_relative_path", ""))
    require(artifact.resolve().is_relative_to(root.resolve()) and receipt_path.resolve().is_relative_to(root.resolve()), "augmented_path_escape")
    require(artifact.is_file() and not artifact.is_symlink(), "augmented_artifact_missing_or_symlink")
    require(receipt_path.is_file() and not receipt_path.is_symlink(), "augmented_receipt_missing_or_symlink")
    require(sha256_file(artifact) == current.get("artifact_sha256"), "augmented_artifact_sha")
    require(sha256_file(receipt_path) == current.get("receipt_sha256"), "augmented_receipt_sha")
    receipt = load_json(receipt_path, "augmented_receipt")
    require(receipt.get("status") == "PASS_TARGET_GRAPHS_ESM2_650M_AUGMENTED", "augmented_receipt_status")
    require(receipt.get("implementation_sha256") == context.artifacts["augment_target_script"].sha256, "augmented_implementation_sha")
    expected_inputs = {
        "base_target_pt": context.artifacts["base_target_pt"].sha256,
        "target_manifest": context.artifacts["base_target_manifest"].sha256,
        "base_target_receipt": context.artifacts["base_target_receipt"].sha256,
        "model_identity_file": context.artifacts["esm2_650m_model_identity"].sha256,
    }
    require(receipt.get("input_hashes") == expected_inputs, "augmented_input_hashes")
    sealed = receipt.get("sealed_boundary") or {}
    require(sealed.get("candidate_docking_pose_files_opened") == 0, "augmented_candidate_pose_access")
    return artifact, receipt_path, receipt


def trainer_command(context: Context, lane: str, output: Path, augmented: Path, augmented_receipt: Path) -> list[str]:
    a = context.artifacts
    t = context.matrix["trainer_arguments"]
    command = [
        str(context.python), str(a["trainer"].path),
        "--training-tsv", str(a["training_tsv"].path),
        "--contact-tsv-gz", str(a["dual_marginal_tsv_gz"].path),
        "--contact-receipt", str(a["dual_marginal_receipt"].path),
        "--preregistration", str(a["preregistration"].path),
        "--output-dir", str(output), "--lane", lane, "--outer-fold", "0",
        "--smoke-mode", "--max-epochs", "1", "--device", "cuda:0",
        "--backbone-kind", "hf", "--model-path", str(a["esm2_650m_model_identity"].path.parent),
        "--model-identity-file", str(a["esm2_650m_model_identity"].path),
        "--expected-model-sha256", a["esm2_650m_model_identity"].sha256,
    ]
    for prefix in context.matrix["structure_prefixes"]:
        command.extend(("--structure-prefix", str(prefix)))
    flags = {
        "structure_dim": "--structure-dim", "ridge_alpha": "--ridge-alpha",
        "graph_hidden_dim": "--graph-hidden-dim", "dropout": "--dropout",
        "residual_scale": "--residual-scale", "huber_delta": "--huber-delta",
        "dual_weight": "--dual-weight", "receptor_weight": "--receptor-weight",
        "marginal_contact_weight": "--marginal-contact-weight",
        "pair_contact_weight": "--pair-contact-weight",
        "contact_positive_class_fraction": "--contact-positive-class-fraction",
        "contact_balance_epsilon": "--contact-balance-epsilon",
        "component_gradient_telemetry_batches": "--component-gradient-telemetry-batches",
        "ranking_weight": "--ranking-weight", "ranking_minimum_delta": "--ranking-minimum-delta",
        "ranking_temperature": "--ranking-temperature", "residual_l2_weight": "--residual-l2-weight",
        "gradient_accumulation": "--gradient-accumulation", "head_learning_rate": "--head-learning-rate",
        "weight_decay": "--weight-decay", "gradient_clip": "--gradient-clip",
        "evaluation_batch_size": "--evaluation-batch-size", "precision": "--precision", "seed": "--seed",
    }
    for name, flag in flags.items():
        command.extend((flag, str(t[name])))
    if lane in GRAPH_LANES:
        command.extend(("--graph-cache-dir", str(a["vhh_graph_cache_npz"].path.parent)))
    if lane in TARGET_LANES:
        command.extend(("--target-graph-pt", str(augmented), "--target-graph-receipt", str(augmented_receipt)))
    if lane in PAIR_LANES:
        command.extend(("--pair-contact-tsv-gz", str(a["pair_contact_tsv_gz"].path)))
    return command


def validate_lane_result(lane: str, path: Path) -> dict[str, Any]:
    payload = load_json(path, f"lane_result:{lane}")
    require(payload.get("status") == "PASS_OUTER_FOLD_COMPLETE", f"lane_result_status:{lane}")
    require(payload.get("lane") == lane and payload.get("outer_fold") == 0, f"lane_result_identity:{lane}")
    observation = payload.get("contact_gradient_calibration_observation")
    require(isinstance(observation, Mapping), f"lane_first_prestep_observation_missing:{lane}")
    require(observation.get("schema_version") == OBSERVATION_SCHEMA, f"lane_observation_schema:{lane}")
    require(observation.get("gradient_batch_index") == 0, f"lane_observation_not_first_batch:{lane}")
    require(observation.get("gradient_batches_in_observation") == 1, f"lane_observation_batch_count:{lane}")
    require(observation.get("optimizer_steps_before_observation") == 0, f"lane_observation_post_optimizer:{lane}")
    require(observation.get("open_only") is True, f"lane_observation_not_open_only:{lane}")
    require(observation.get("v4_f_test32_access_count") == 0, f"lane_test32_access:{lane}")
    require(observation.get("prediction_metrics_access_count") == 0, f"lane_prediction_metric_access:{lane}")
    require(observation.get("outer_fold") == 0, f"lane_observation_outer_fold:{lane}")
    return payload


def selector_command(context: Context, lane_results: Mapping[str, Path], output: Path) -> list[str]:
    command = [str(context.python), str(context.artifacts["selector"].path)]
    for lane in LANES:
        command.extend(("--lane-result", f"{lane}={lane_results[lane]}"))
    command.extend(("--output-dir", str(output)))
    return command


def validate_selector_output(output: Path) -> dict[str, Any]:
    amendment = output / "CONTACT_LOSS_AMENDMENT_V1.json"
    report = output / "CONTACT_GRADIENT_CALIBRATION_REPORT_V1.json"
    receipt_path = output / "RUN_RECEIPT.json"
    for label, path in (("amendment", amendment), ("report", report), ("receipt", receipt_path)):
        require(path.is_file() and not path.is_symlink(), f"selector_{label}_missing_or_symlink")
    receipt = load_json(receipt_path, "selector_receipt")
    require(receipt.get("status") == SELECTOR_STATUS, "selector_receipt_status")
    outputs = receipt.get("outputs") or {}
    require(outputs.get(amendment.name) == sha256_file(amendment), "selector_amendment_sha")
    require(outputs.get(report.name) == sha256_file(report), "selector_report_sha")
    amendment_payload = load_json(amendment, "contact_loss_amendment")
    calibration = amendment_payload.get("calibration") or {}
    require(calibration.get("v4_f_test32_access_count") == 0, "selector_test32_access")
    require(calibration.get("optimizer_steps_before_observation") == 0, "selector_post_optimizer")
    return {
        "amendment_sha256": sha256_file(amendment),
        "report_sha256": sha256_file(report),
        "receipt_sha256": sha256_file(receipt_path),
        "selected_weights": calibration.get("selected_weights"),
    }


def publish_content_addressed(runtime_root: Path, staging: Path) -> tuple[Path, dict[str, Any]]:
    validation = validate_selector_output(staging)
    root = runtime_root / "calibration"
    destination = root / "by_sha256" / validation["amendment_sha256"]
    require(not destination.exists() and not destination.is_symlink(), "calibration_content_address_collision")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, destination)
    current = {
        "schema_version": "pvrig_v6_residue_v2_contact_gradient_calibration_current_v1_2",
        "amendment_sha256": validation["amendment_sha256"],
        "relative_path": str(destination.relative_to(root)),
        **validation,
    }
    atomic_json(root / "CURRENT.json", current)
    return destination, validation


def validate_published(runtime_root: Path) -> tuple[Path, dict[str, Any]]:
    root = runtime_root / "calibration"
    current = load_json(root / "CURRENT.json", "calibration_current")
    destination = root / str(current.get("relative_path", ""))
    require(destination.resolve().is_relative_to(root.resolve()), "calibration_current_path_escape")
    validation = validate_selector_output(destination)
    for field in ("amendment_sha256", "report_sha256", "receipt_sha256"):
        require(current.get(field) == validation[field], f"calibration_current_hash:{field}")
    return destination, validation


def bootstrap_payload(context: Context, static_hashes: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schema_version": BOOTSTRAP_SCHEMA,
        "mode": "OPEN_ONLY_PREPRODUCTION_NOT_FORMAL_OOF",
        "matrix_sha256": context.matrix_sha256,
        "launcher_sha256": sha256_file(SCRIPT),
        "static_artifact_sha256": dict(sorted(static_hashes.items())),
        "original_preregistration_sha256": context.matrix["original_preregistration_sha256"],
        "lane_gpu_map": LANE_GPU,
        "augmentation_gpu": AUGMENTATION_GPU,
        "outer_fold": 0,
        "maximum_epochs": 1,
        "smoke_mode": True,
        "v4_f_test32_access_count": 0,
        "formal_oof_started": False,
    }


def validate_resume_bootstrap(context: Context, static_hashes: Mapping[str, str]) -> dict[str, Any]:
    path = context.runtime_root / "status/BOOTSTRAP_RECEIPT.json"
    observed = load_json(path, "calibration_bootstrap")
    require(observed == bootstrap_payload(context, static_hashes), "calibration_bootstrap_replay_mismatch")
    return observed


def run_lanes(
    context: Context,
    augmented: Path,
    augmented_receipt: Path,
    runner: CommandRunner,
) -> dict[str, Path]:
    results: dict[str, Path] = {}
    pending: list[str] = []
    for lane in LANES:
        output = context.runtime_root / "lanes" / lane / "outer_fold0"
        result = output / "RESULT.json"
        if result.is_file():
            validate_lane_result(lane, result)
            results[lane] = result
        else:
            require(not output.exists() and not output.is_symlink(), f"lane_partial_output_requires_manual_audit:{lane}")
            pending.append(lane)

    def execute_lane(lane: str) -> tuple[str, Path]:
        output = context.runtime_root / "lanes" / lane / "outer_fold0"
        command = trainer_command(context, lane, output, augmented, augmented_receipt)
        runner(command, base_environment(LANE_GPU[lane]), context.runtime_root / "logs" / f"{lane}.log")
        result = output / "RESULT.json"
        validate_lane_result(lane, result)
        return lane, result

    if pending:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(pending)) as pool:
            futures = [pool.submit(execute_lane, lane) for lane in pending]
            for future in concurrent.futures.as_completed(futures):
                lane, result = future.result()
                results[lane] = result
    require(set(results) == set(LANES), "lane_result_closure")
    return results


def terminal_payload(
    context: Context,
    lane_results: Mapping[str, Path],
    publication: Path,
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": TERMINAL_SCHEMA,
        "status": TERMINAL_STATUS,
        "mode": "OPEN_ONLY_PREPRODUCTION_NOT_FORMAL_OOF",
        "matrix_sha256": context.matrix_sha256,
        "original_preregistration_sha256": context.matrix["original_preregistration_sha256"],
        "lane_result_sha256": {lane: sha256_file(lane_results[lane]) for lane in LANES},
        "content_addressed_publication": str(publication),
        **dict(validation),
        "outer_fold": 0,
        "maximum_epochs": 1,
        "smoke_mode": True,
        "first_prestep_observation_per_lane": True,
        "v4_f_test32_access_count": 0,
        "prediction_metrics_used_for_selection": False,
        "formal_oof_started": False,
        "production_matrix_or_freeze_updated": False,
    }


def execute(
    context: Context,
    *,
    mode: str,
    runner: CommandRunner = subprocess_runner,
    gpu_probe: Callable[[Sequence[int]], Mapping[int, Mapping[str, int]]] = probe_gpus,
    free_gib: Callable[[Path], int] = available_gib,
) -> dict[str, Any]:
    require(mode in {"dry-run", "run", "resume"}, "mode_invalid")
    static_hashes = validate_static_artifacts(context)
    require(str(Path(sys.executable)) == str(context.python) or mode == "dry-run", "canonical_python_required")
    if mode == "dry-run":
        require(not os.path.lexists(context.runtime_root), "dry_run_requires_fresh_runtime_root")
        return {
            "status": "PASS_CONTACT_GRADIENT_CALIBRATION_DRY_RUN",
            "writes": 0,
            "matrix_sha256": context.matrix_sha256,
            "static_artifacts": len(static_hashes),
            "lane_commands": {
                lane: trainer_command(
                    context, lane, context.runtime_root / "lanes" / lane / "outer_fold0",
                    context.runtime_root / "cache/targets/PENDING.pt",
                    context.runtime_root / "cache/targets/PENDING.receipt.json",
                )
                for lane in LANES
            },
            "v4_f_test32_access_count": 0,
            "formal_oof_started": False,
        }

    if mode == "run":
        require(not os.path.lexists(context.runtime_root), "run_requires_new_runtime_root")
        require(context.runtime_root.parent.is_dir() and not context.runtime_root.parent.is_symlink(), "runtime_parent_invalid")
        require(free_gib(context.runtime_root.parent) >= int(context.matrix["minimum_free_gib"]), "insufficient_free_space")
        gpu_rows = dict(gpu_probe(tuple(LANE_GPU.values()) + (AUGMENTATION_GPU,)))
        validate_gpu_idle(gpu_rows)
        context.runtime_root.mkdir(parents=False, exist_ok=False)
        atomic_json(context.runtime_root / "status/BOOTSTRAP_RECEIPT.json", bootstrap_payload(context, static_hashes))
    else:
        require(context.runtime_root.is_dir() and not context.runtime_root.is_symlink(), "resume_runtime_root_invalid")
        validate_resume_bootstrap(context, static_hashes)
        gpu_rows = dict(gpu_probe(tuple(LANE_GPU.values()) + (AUGMENTATION_GPU,)))
        validate_gpu_idle(gpu_rows)

    augmentation_root = context.runtime_root / "cache/pvrig_graphs/esm2_650m_v2"
    if not augmentation_root.exists():
        runner(
            augmentation_command(context, augmentation_root),
            base_environment(AUGMENTATION_GPU),
            context.runtime_root / "logs/augmentation.log",
        )
    augmented, augmented_receipt, _ = validate_augmented_delivery(context, augmentation_root)
    lane_results = run_lanes(context, augmented, augmented_receipt, runner)
    require(sha256_file(context.artifacts["preregistration"].path) == context.matrix["original_preregistration_sha256"], "preregistration_changed_during_calibration")

    current_path = context.runtime_root / "calibration/CURRENT.json"
    if current_path.is_file():
        publication, validation = validate_published(context.runtime_root)
    else:
        staging = context.runtime_root / "calibration_selector_output"
        require(not staging.exists() and not staging.is_symlink(), "selector_staging_already_exists")
        runner(
            selector_command(context, lane_results, staging),
            {**dict(os.environ), "CUDA_VISIBLE_DEVICES": ""},
            context.runtime_root / "logs/selector.log",
        )
        publication, validation = publish_content_addressed(context.runtime_root, staging)
    terminal = terminal_payload(context, lane_results, publication, validation)
    terminal_path = context.runtime_root / "status/TERMINAL.json"
    if terminal_path.is_file():
        require(load_json(terminal_path, "calibration_terminal") == terminal, "terminal_replay_mismatch")
    else:
        atomic_json(terminal_path, terminal)
    return terminal


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("mode", choices=("dry-run", "run", "resume"))
    value.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    context = load_context(args.matrix)
    result = execute(context, mode=args.mode)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
