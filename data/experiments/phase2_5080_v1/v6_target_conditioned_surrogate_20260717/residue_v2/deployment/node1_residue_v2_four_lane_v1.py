#!/usr/bin/env python3
"""Fail-closed Node1 launcher for Residue V2 target augmentation and four-lane OOF.

The launcher never copies data from a docking campaign and never opens V4-F/test32.
Every executable/input SHA is read from IMPLEMENTATION_FREEZE_V2.json.  An initial
run requires a brand-new runtime root; a resume is accepted only when the bootstrap,
post-augmentation input closure, and every reused terminal close to the current
freeze and command hashes.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence


REMOTE_ROOT = pathlib.Path(
    "/data1/qlyu/projects/pvrig_v6_residue_v2_3_four_lane_oof_v1_20260718"
)
FIXED_PYTHON = pathlib.Path("/data1/qlyu/software/envs/pvrig-v6-tc/bin/python")
MIN_FREE_GIB = 200
AUGMENTATION_GPU = 6
FORBIDDEN_GPUS = (0, 3)
RESERVED_GPUS = (7,)
CPU_THREADS_PER_PROCESS = 8
MAX_PREFLIGHT_GPU_MEMORY_MIB = 512
MAX_PREFLIGHT_GPU_UTILIZATION_PERCENT = 5
LANE_GPU = {
    "A_DOMAIN": 1,
    "B_VHH3D": 2,
    "C_PATCH": 4,
    "D_FULL_PAIR": 5,
}
FOLDS = tuple(range(5))
FORBIDDEN_PATH_TOKENS = (
    "v4_f",
    "test32",
    "prospective_computational_test",
)
FREEZE_NAME = "IMPLEMENTATION_FREEZE_V2.json"
BOOTSTRAP_NAME = "BOOTSTRAP_RECEIPT.json"
INPUT_CLOSURE_NAME = "DEPLOYMENT_INPUT_CLOSURE.json"
TERMINAL_NAME = "TERMINAL.json"

MATRIX_STATIC_ARTIFACTS = {
    "augment_target_script",
    "base_target_cache_npz",
    "base_target_manifest",
    "base_target_pt",
    "base_target_receipt",
    "dual_marginal_receipt",
    "dual_marginal_tsv_gz",
    "esm2_650m_model_identity",
    "pair_contact_receipt",
    "pair_contact_tsv_gz",
    "training_receipt",
    "training_tsv",
    "v4d_marginal_teacher",
    "v4d_pair_teacher",
    "v4d_pose_inventory",
    "v4d_teacher_receipt",
    "vhh_graph_cache_npz",
    "vhh_graph_cache_receipt",
    "vhh_graph_closure",
    "vhh_graph_manifest",
    "vhh_graph_materialization_receipt",
    "contact_loss_amendment_v2_2",
    "contact_gradient_calibration_report_v2_2",
    "contact_gradient_calibration_receipt_v2_2",
    "residue_v1_residue_model",
    "residue_v1_base_trainer",
    "residue_v1_v1_5_trainer",
}
VIRTUAL_IMPLEMENTATION_ARTIFACTS = {"trainer", "collector", "preregistration"}
STATIC_ARTIFACTS = MATRIX_STATIC_ARTIFACTS | VIRTUAL_IMPLEMENTATION_ARTIFACTS
POST_ARTIFACT = "augmented_target_graph"
IMPLEMENTATION_RUNTIME_PATHS = {
    "trainer": "src/train_nested_residue_surrogate_v2.py",
    "collector": "src/collect_residue_oof_v2.py",
    "preregistration": "PREREGISTRATION_V2.json",
}
LOCAL_TRANSITIVE_RUNTIME_PATHS = {
    "residue_v1_residue_model": "residue_v1/src/residue_model.py",
    "residue_v1_base_trainer": "residue_v1/src/train_nested_residue_surrogate.py",
    "residue_v1_v1_5_trainer": "residue_v1/src/train_nested_residue_surrogate_v1_5.py",
}
NUMERICAL_AMENDMENT_RELATIVE = "NUMERICAL_STABILITY_AMENDMENT_V2_3.json"
EXPECTED_TECHNICAL_SUPERSESSION = {
    "amendment": NUMERICAL_AMENDMENT_RELATIVE,
    "partial_checkpoint_reuse": False,
    "superseded_freeze_sha256": "2659325b58d2c1e8faeb6f20b71cb63a6216a21ef5803d71886aa100c2eff471",
    "superseded_version": "V2.2",
}
TRAINER_ARGUMENTS = {
    "structure_prefixes",
    "structure_dim",
    "ridge_alpha",
    "graph_hidden_dim",
    "dropout",
    "residual_scale",
    "huber_delta",
    "dual_weight",
    "receptor_weight",
    "lane_contact_weights",
    "contact_positive_class_fraction",
    "contact_balance_epsilon",
    "component_gradient_telemetry_batches",
    "ranking_weight",
    "ranking_minimum_delta",
    "ranking_temperature",
    "residual_l2_weight",
    "gradient_accumulation",
    "head_learning_rate",
    "weight_decay",
    "gradient_clip",
    "evaluation_batch_size",
    "precision",
    "seed",
    "maximum_epochs",
}


class DeploymentError(RuntimeError):
    """A fail-closed deployment contract violation."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DeploymentError(message)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_sha(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def atomic_json(path: pathlib.Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_regular_json(path: pathlib.Path, label: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"{label}_missing_or_symlink:{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeploymentError(f"{label}_invalid_json:{path}:{error}") from error
    require(isinstance(payload, dict), f"{label}_not_object:{path}")
    return payload


@dataclass(frozen=True)
class Artifact:
    label: str
    path: pathlib.Path
    sha256: str | None
    phase: str


@dataclass(frozen=True)
class FreezeContext:
    path: pathlib.Path
    sha256: str
    payload: Mapping[str, Any]
    deployment: Mapping[str, Any]
    artifacts: Mapping[str, Artifact]


def _artifact_from_payload(label: str, raw: Any) -> Artifact:
    require(isinstance(raw, dict), f"artifact_not_object:{label}")
    phase = str(raw.get("phase", "pre_freeze_binding"))
    path_text = raw.get("path")
    require(isinstance(path_text, str) and path_text.startswith("/"), f"artifact_path_not_absolute:{label}")
    path = pathlib.Path(path_text)
    lowered = path_text.lower()
    require(not any(token in lowered for token in FORBIDDEN_PATH_TOKENS), f"sealed_or_test32_artifact_forbidden:{label}:{path}")
    expected = raw.get("sha256")
    if phase == "post_augmentation_binding":
        require(label == POST_ARTIFACT, f"post_augmentation_phase_wrong_label:{label}")
        require(expected in (None, ""), "post_augmentation_sha_must_not_be_prefilled")
        return Artifact(label, path, None, phase)
    require(phase == "pre_freeze_binding", f"artifact_phase_invalid:{label}:{phase}")
    require(isinstance(expected, str) and len(expected) == 64, f"artifact_sha_invalid:{label}")
    return Artifact(label, path, expected, phase)


def load_freeze(
    freeze_path: pathlib.Path,
    *,
    expected_root: pathlib.Path = REMOTE_ROOT,
    expected_python: pathlib.Path = FIXED_PYTHON,
) -> FreezeContext:
    payload = load_regular_json(freeze_path, "implementation_freeze")
    require(freeze_path.name == FREEZE_NAME, f"freeze_filename_invalid:{freeze_path.name}")
    require(payload.get("mode") == "production", "production_freeze_mode_required")
    require(payload.get("status") == "PASS_RESIDUE_V2_IMPLEMENTATION_FROZEN_FOR_NODE1_SMOKE", "production_freeze_status_required")
    require(payload.get("production_training_started") is False, "freeze_production_training_flag_not_false")
    require(payload.get("pending") == [], "freeze_pending_inputs_not_empty")
    deployment = payload.get("node1_deployment")
    require(isinstance(deployment, dict), "node1_deployment_missing")
    require(deployment.get("remote_root") == str(expected_root), "remote_root_not_frozen")
    require(deployment.get("python") == str(expected_python), "python_path_not_frozen")
    require(deployment.get("min_free_gib") == MIN_FREE_GIB, "minimum_free_gib_not_frozen")
    require(deployment.get("augmentation_gpu") == AUGMENTATION_GPU, "augmentation_gpu_not_frozen")
    require(deployment.get("lane_gpu_map") == LANE_GPU, "lane_gpu_map_not_frozen")
    require(deployment.get("forbidden_gpus") == list(FORBIDDEN_GPUS), "forbidden_gpus_not_frozen")
    require(deployment.get("reserved_gpus") == list(RESERVED_GPUS), "reserved_gpus_not_frozen")
    require(deployment.get("cpu_threads_per_process") == CPU_THREADS_PER_PROCESS, "cpu_threads_not_frozen")
    raw_artifacts = payload.get("formal_artifacts")
    require(isinstance(raw_artifacts, dict), "deployment_artifacts_missing")
    require(set(raw_artifacts) == MATRIX_STATIC_ARTIFACTS | {POST_ARTIFACT}, "deployment_artifact_set_not_exact")
    artifacts = {label: _artifact_from_payload(label, raw) for label, raw in raw_artifacts.items()}
    governance = payload.get("contact_loss_governance") or {}
    require(governance.get("status") == "PASS_CONTACT_LOSS_AMENDMENT_V2_2_BOUND", "contact_loss_governance_not_bound")
    require(governance.get("lane_weights") == deployment.get("trainer_arguments", {}).get("lane_contact_weights"), "contact_loss_lane_weights_not_frozen")
    require(governance.get("prediction_metrics_used") is False, "contact_loss_prediction_metrics_used")
    require(governance.get("v4_f_test32_access_count") == 0, "contact_loss_v4f_access")
    implementation = payload.get("implementation_files")
    require(isinstance(implementation, dict), "implementation_files_missing")
    bundle_root = pathlib.Path(str(deployment.get("bundle_root", "")))
    require(bundle_root.is_absolute(), "bundle_root_not_absolute")
    implementation_hashes: dict[str, str] = {}
    for relative, record in implementation.items():
        require(isinstance(relative, str) and relative and not relative.startswith("/"), f"implementation_relative_path_invalid:{relative}")
        require(".." not in pathlib.PurePosixPath(relative).parts, f"implementation_parent_escape:{relative}")
        require(isinstance(record, dict), f"implementation_record_invalid:{relative}")
        digest = record.get("sha256")
        require(isinstance(digest, str) and len(digest) == 64, f"implementation_sha_invalid:{relative}")
        artifacts[f"implementation::{relative}"] = Artifact(
            f"implementation::{relative}", bundle_root / "residue_v2" / relative,
            digest, "pre_freeze_binding",
        )
        implementation_hashes[relative] = digest
    require(canonical_json_sha(implementation_hashes) == payload.get("implementation_tree_sha256"), "implementation_tree_sha_mismatch")
    require(payload.get("technical_supersession") == EXPECTED_TECHNICAL_SUPERSESSION, "technical_supersession_not_frozen")
    numerical = payload.get("numerical_stability_amendment")
    require(isinstance(numerical, dict), "numerical_stability_amendment_missing")
    numerical_record = implementation.get(NUMERICAL_AMENDMENT_RELATIVE)
    require(isinstance(numerical_record, dict), "numerical_stability_amendment_implementation_missing")
    require(numerical.get("sha256") == numerical_record.get("sha256"), "numerical_stability_amendment_sha_mismatch")
    for label, relative in IMPLEMENTATION_RUNTIME_PATHS.items():
        record = implementation.get(relative)
        require(isinstance(record, dict), f"implementation_binding_missing:{relative}")
        digest = record.get("sha256")
        require(isinstance(digest, str) and len(digest) == 64, f"implementation_sha_invalid:{relative}")
        artifacts[label] = Artifact(label, bundle_root / "residue_v2" / relative, digest, "pre_freeze_binding")
    # The V2 trainer resolves these frozen V1 modules through its sibling
    # ``residue_v1/src`` directory.  Bind the exact files that Python will
    # import, rather than validating only the archival copies named in the
    # static input matrix.
    for label, relative in LOCAL_TRANSITIVE_RUNTIME_PATHS.items():
        source = artifacts.get(label)
        require(isinstance(source, Artifact), f"transitive_static_binding_missing:{label}")
        artifacts[f"local_transitive::{label}"] = Artifact(
            f"local_transitive::{label}", bundle_root / relative,
            source.sha256, "pre_freeze_binding",
        )
    require(artifacts[POST_ARTIFACT].path == expected_root / "cache/pvrig_graphs/esm2_650m_v2", "augmented_target_output_path_not_frozen")
    require((payload.get("post_augmentation_contract") or {}).get("required_before_smoke_or_production") is True, "post_augmentation_contract_missing")
    sealed = payload.get("sealed_test32_exclusion") or {}
    require(sealed.get("path_access_count") == 0, "sealed_test32_access_nonzero")
    require(sealed.get("training_use_forbidden") is True, "sealed_test32_training_contract")
    trainer_arguments = deployment.get("trainer_arguments")
    require(isinstance(trainer_arguments, dict), "trainer_arguments_missing")
    require(set(trainer_arguments) == TRAINER_ARGUMENTS, "trainer_argument_set_not_exact")
    prefixes = trainer_arguments["structure_prefixes"]
    require(isinstance(prefixes, list) and prefixes and all(isinstance(x, str) and x for x in prefixes), "structure_prefixes_invalid")
    require(trainer_arguments["maximum_epochs"] >= 1, "maximum_epochs_invalid")
    require(trainer_arguments["precision"] == "bf16", "precision_not_bf16")
    return FreezeContext(freeze_path, sha256_file(freeze_path), payload, deployment, artifacts)


def validate_static_artifacts(context: FreezeContext) -> dict[str, str]:
    observed: dict[str, str] = {}
    for label in sorted(context.artifacts):
        if label == POST_ARTIFACT:
            continue
        artifact = context.artifacts[label]
        require(artifact.path.is_file() and not artifact.path.is_symlink(), f"artifact_missing_or_symlink:{label}:{artifact.path}")
        actual = sha256_file(artifact.path)
        require(actual == artifact.sha256, f"artifact_sha_mismatch:{label}:{actual}:{artifact.sha256}")
        observed[label] = actual
    graph_parents = {
        context.artifacts[label].path.parent
        for label in ("vhh_graph_cache_npz", "vhh_graph_manifest", "vhh_graph_cache_receipt")
    }
    require(len(graph_parents) == 1, "vhh_graph_artifacts_not_co_located")
    model_identity = context.artifacts["esm2_650m_model_identity"].path
    require(model_identity.name == "model.safetensors", "esm2_identity_filename_invalid")
    return observed


def validate_fresh_root(
    root: pathlib.Path,
    *,
    minimum_free_gib: int = MIN_FREE_GIB,
    disk_usage: Callable[[str | os.PathLike[str]], Any] = shutil.disk_usage,
) -> int:
    require(not os.path.lexists(root), f"runtime_root_must_not_exist:{root}")
    parent = root.parent
    require(parent.is_dir() and not parent.is_symlink(), f"runtime_parent_missing_or_symlink:{parent}")
    free = int(disk_usage(parent).free)
    free_gib = free // (1024 ** 3)
    require(free >= minimum_free_gib * 1024 ** 3, f"free_space_below_{minimum_free_gib}GiB:{free_gib}")
    return free_gib


def verify_python(path: pathlib.Path) -> None:
    require(path == FIXED_PYTHON, f"python_not_fixed:{path}")
    require(path.exists() and os.access(path, os.X_OK), f"python_missing_or_not_executable:{path}")


def validate_gpu_inventory(
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[int]:
    completed = runner(
        ["nvidia-smi", "--query-gpu=index,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    )
    rows: dict[int, tuple[int, int]] = {}
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        fields = [field.strip() for field in line.split(",")]
        require(len(fields) == 3, f"nvidia_smi_row_invalid:{line}")
        index, memory_mib, utilization = (int(field) for field in fields)
        require(index not in rows, f"nvidia_smi_duplicate_gpu:{index}")
        rows[index] = (memory_mib, utilization)
    indices = sorted(rows)
    required = sorted({AUGMENTATION_GPU, *LANE_GPU.values()})
    require(all(index in indices for index in required), f"required_gpu_missing:{required}:{indices}")
    require(all(index in indices for index in (*FORBIDDEN_GPUS, *RESERVED_GPUS)), "gpu_policy_inventory_incomplete")
    assignments = {AUGMENTATION_GPU, *LANE_GPU.values()}
    require(not assignments.intersection(FORBIDDEN_GPUS), "forbidden_gpu_assignment")
    require(not assignments.intersection(RESERVED_GPUS), "reserved_gpu_assignment")
    for index in required:
        memory_mib, utilization = rows[index]
        require(
            memory_mib <= MAX_PREFLIGHT_GPU_MEMORY_MIB and utilization <= MAX_PREFLIGHT_GPU_UTILIZATION_PERCENT,
            f"required_gpu_not_idle:{index}:memory_mib={memory_mib}:utilization={utilization}",
        )
    return indices


def bootstrap_receipt_payload(context: FreezeContext, observed: Mapping[str, str], free_gib: int) -> dict[str, Any]:
    return {
        "schema_version": "pvrig_v6_residue_v2_node1_bootstrap_v1",
        "status": "PASS_NEW_RUNTIME_ROOT_BOOTSTRAPPED",
        "created_at_utc": utc_now(),
        "runtime_root": str(REMOTE_ROOT),
        "implementation_freeze_sha256": context.sha256,
        "static_artifact_sha256": dict(sorted(observed.items())),
        "free_gib_before_creation": free_gib,
        "gpu0_forbidden": True,
        "gpu3_forbidden": True,
        "forbidden_gpus": list(FORBIDDEN_GPUS),
        "reserved_gpus": list(RESERVED_GPUS),
        "cpu_threads_per_process": CPU_THREADS_PER_PROCESS,
        "augmentation_gpu": AUGMENTATION_GPU,
        "lane_gpu_map": LANE_GPU,
        "v4_f_test32_synced_or_opened": False,
    }


def initialize_runtime_root(context: FreezeContext, observed: Mapping[str, str], free_gib: int) -> pathlib.Path:
    validate_fresh_root(REMOTE_ROOT, minimum_free_gib=MIN_FREE_GIB)
    REMOTE_ROOT.mkdir(parents=False, exist_ok=False)
    for relative in (
        "status", "logs", "cache/pvrig_graphs", "runtime/smoke",
        *[f"runtime/{lane}/production" for lane in LANE_GPU],
        *[f"runtime/{lane}/collector" for lane in LANE_GPU],
    ):
        (REMOTE_ROOT / relative).mkdir(parents=True, exist_ok=False)
    receipt_path = REMOTE_ROOT / "status" / BOOTSTRAP_NAME
    atomic_json(receipt_path, bootstrap_receipt_payload(context, observed, free_gib))
    return receipt_path


def validate_bootstrap_resume(context: FreezeContext, observed: Mapping[str, str]) -> pathlib.Path:
    require(REMOTE_ROOT.is_dir() and not REMOTE_ROOT.is_symlink(), "resume_root_missing_or_symlink")
    path = REMOTE_ROOT / "status" / BOOTSTRAP_NAME
    payload = load_regular_json(path, "bootstrap_receipt")
    require(payload.get("status") == "PASS_NEW_RUNTIME_ROOT_BOOTSTRAPPED", "bootstrap_status_invalid")
    require(payload.get("runtime_root") == str(REMOTE_ROOT), "bootstrap_root_mismatch")
    require(payload.get("implementation_freeze_sha256") == context.sha256, "bootstrap_freeze_sha_mismatch")
    require(payload.get("static_artifact_sha256") == dict(sorted(observed.items())), "bootstrap_static_artifacts_mismatch")
    require(payload.get("gpu0_forbidden") is True, "bootstrap_gpu0_contract_invalid")
    require(payload.get("gpu3_forbidden") is True, "bootstrap_gpu3_contract_invalid")
    require(payload.get("forbidden_gpus") == list(FORBIDDEN_GPUS), "bootstrap_forbidden_gpu_contract_invalid")
    require(payload.get("reserved_gpus") == list(RESERVED_GPUS), "bootstrap_reserved_gpu_contract_invalid")
    require(payload.get("cpu_threads_per_process") == CPU_THREADS_PER_PROCESS, "bootstrap_cpu_cap_invalid")
    require(payload.get("v4_f_test32_synced_or_opened") is False, "bootstrap_sealed_boundary_invalid")
    return path


def augmentation_command(context: FreezeContext) -> list[str]:
    artifact = context.artifacts
    return [
        str(FIXED_PYTHON), str(artifact["augment_target_script"].path),
        "--base-target-pt", str(artifact["base_target_pt"].path),
        "--target-manifest", str(artifact["base_target_manifest"].path),
        "--base-target-receipt", str(artifact["base_target_receipt"].path),
        "--model-path", str(artifact["esm2_650m_model_identity"].path.parent),
        "--model-identity-file", str(artifact["esm2_650m_model_identity"].path),
        "--output-dir", str(artifact[POST_ARTIFACT].path),
        "--device", "cuda:0",
    ]


def _run_logged(command: Sequence[str], *, gpu: int, log_path: pathlib.Path) -> int:
    require(gpu not in FORBIDDEN_GPUS, f"forbidden_gpu_execution:{gpu}")
    require(gpu not in RESERVED_GPUS, f"reserved_gpu_execution:{gpu}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({
        "CUDA_VISIBLE_DEVICES": str(gpu),
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OMP_NUM_THREADS": str(CPU_THREADS_PER_PROCESS),
        "MKL_NUM_THREADS": str(CPU_THREADS_PER_PROCESS),
        "OPENBLAS_NUM_THREADS": str(CPU_THREADS_PER_PROCESS),
        "NUMEXPR_NUM_THREADS": str(CPU_THREADS_PER_PROCESS),
    })
    with log_path.open("ab") as handle:
        completed = subprocess.run(list(command), env=environment, stdout=handle, stderr=subprocess.STDOUT, check=False)
    return int(completed.returncode)


def validate_augmented_target(context: FreezeContext) -> dict[str, Any]:
    output_root = context.artifacts[POST_ARTIFACT].path
    current_path = output_root / "CURRENT.json"
    current = load_regular_json(current_path, "augmented_target_current")
    require(current.get("schema_version") == "pvrig_v6_target_graphs_esm2_650m_v2", "augmented_current_schema")
    artifact_rel = current.get("artifact_relative_path")
    receipt_rel = current.get("receipt_relative_path")
    require(isinstance(artifact_rel, str) and isinstance(receipt_rel, str), "augmented_current_paths_missing")
    artifact_path = output_root / artifact_rel
    receipt_path = output_root / receipt_rel
    require(artifact_path.is_file() and not artifact_path.is_symlink(), "augmented_target_missing_or_symlink")
    require(receipt_path.is_file() and not receipt_path.is_symlink(), "augmented_receipt_missing_or_symlink")
    artifact_sha = sha256_file(artifact_path)
    receipt_sha = sha256_file(receipt_path)
    require(artifact_sha == current.get("artifact_sha256"), "augmented_target_current_hash_mismatch")
    require(receipt_sha == current.get("receipt_sha256"), "augmented_receipt_current_hash_mismatch")
    receipt = load_regular_json(receipt_path, "augmented_target_receipt")
    require(receipt.get("schema_version") == "pvrig_v6_target_graphs_esm2_650m_v2", "augmented_receipt_schema")
    require(receipt.get("status") == "PASS_TARGET_GRAPHS_ESM2_650M_AUGMENTED", "augmented_receipt_status")
    require((receipt.get("output") or {}).get("sha256") == artifact_sha, "augmented_receipt_output_hash")
    require((receipt.get("inference") or {}).get("augmented_feature_dim") == 1310, "augmented_feature_dim_invalid")
    require((receipt.get("inference") or {}).get("dtype") == "bfloat16", "augmented_inference_dtype_invalid")
    require((receipt.get("inference") or {}).get("stored_dtype") == "float32", "augmented_storage_dtype_invalid")
    require((receipt.get("inference") or {}).get("network_access") == "disabled", "augmented_network_not_disabled")
    sealed = receipt.get("sealed_boundary") or {}
    require(sealed.get("teacher_source_is_model_feature") is False, "augmented_teacher_source_boundary")
    require(sealed.get("candidate_docking_pose_files_opened") == 0, "augmented_candidate_pose_boundary")
    static = context.artifacts
    expected_inputs = {
        "base_target_pt": static["base_target_pt"].sha256,
        "target_manifest": static["base_target_manifest"].sha256,
        "base_target_receipt": static["base_target_receipt"].sha256,
        "model_identity_file": static["esm2_650m_model_identity"].sha256,
    }
    require(receipt.get("input_hashes") == expected_inputs, "augmented_input_hash_closure")
    require(receipt.get("implementation_sha256") == static["augment_target_script"].sha256, "augmentation_script_hash_mismatch")
    return {
        "artifact_path": str(artifact_path),
        "artifact_sha256": artifact_sha,
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha,
        "current_path": str(current_path),
        "current_sha256": sha256_file(current_path),
    }


def write_input_closure(context: FreezeContext, augmented: Mapping[str, Any], observed: Mapping[str, str]) -> pathlib.Path:
    path = REMOTE_ROOT / "status" / INPUT_CLOSURE_NAME
    payload = {
        "schema_version": "pvrig_v6_residue_v2_node1_input_closure_v1",
        "status": "PASS_DEPLOYMENT_INPUT_CLOSURE",
        "created_at_utc": utc_now(),
        "implementation_freeze_sha256": context.sha256,
        "static_artifact_sha256": dict(sorted(observed.items())),
        "augmented_target_graph": dict(augmented),
        "gpu0_forbidden": True,
        "gpu3_forbidden": True,
        "forbidden_gpus": list(FORBIDDEN_GPUS),
        "reserved_gpus": list(RESERVED_GPUS),
        "cpu_threads_per_process": CPU_THREADS_PER_PROCESS,
        "augmentation_physical_gpu": AUGMENTATION_GPU,
        "v4_f_test32_synced_or_opened": False,
    }
    if path.exists():
        existing = load_regular_json(path, "deployment_input_closure")
        for key in ("implementation_freeze_sha256", "static_artifact_sha256", "augmented_target_graph"):
            require(existing.get(key) == payload[key], f"existing_input_closure_mismatch:{key}")
        require(existing.get("status") == payload["status"], "existing_input_closure_status")
        return path
    atomic_json(path, payload)
    return path


def validate_input_closure(context: FreezeContext, observed: Mapping[str, str]) -> dict[str, Any]:
    path = REMOTE_ROOT / "status" / INPUT_CLOSURE_NAME
    payload = load_regular_json(path, "deployment_input_closure")
    require(payload.get("status") == "PASS_DEPLOYMENT_INPUT_CLOSURE", "input_closure_status_invalid")
    require(payload.get("implementation_freeze_sha256") == context.sha256, "input_closure_freeze_sha")
    require(payload.get("static_artifact_sha256") == dict(sorted(observed.items())), "input_closure_static_sha")
    require(payload.get("augmented_target_graph") == validate_augmented_target(context), "input_closure_augmented_mismatch")
    require(payload.get("gpu0_forbidden") is True, "input_closure_gpu0_boundary")
    require(payload.get("gpu3_forbidden") is True, "input_closure_gpu3_boundary")
    require(payload.get("forbidden_gpus") == list(FORBIDDEN_GPUS), "input_closure_forbidden_gpus")
    require(payload.get("reserved_gpus") == list(RESERVED_GPUS), "input_closure_reserved_gpus")
    require(payload.get("cpu_threads_per_process") == CPU_THREADS_PER_PROCESS, "input_closure_cpu_cap")
    require(payload.get("v4_f_test32_synced_or_opened") is False, "input_closure_sealed_boundary")
    return payload


def _trainer_common_arguments(context: FreezeContext, lane: str) -> list[str]:
    artifacts = context.artifacts
    frozen = context.deployment["trainer_arguments"]
    lane_weights = frozen["lane_contact_weights"][lane]
    command = [
        str(FIXED_PYTHON), str(artifacts["trainer"].path),
        "--training-tsv", str(artifacts["training_tsv"].path),
        "--contact-tsv-gz", str(artifacts["dual_marginal_tsv_gz"].path),
        "--contact-receipt", str(artifacts["dual_marginal_receipt"].path),
        "--preregistration", str(artifacts["preregistration"].path),
        "--backbone-kind", "hf",
        "--model-path", str(artifacts["esm2_650m_model_identity"].path.parent),
        "--model-identity-file", str(artifacts["esm2_650m_model_identity"].path),
        "--expected-model-sha256", str(artifacts["esm2_650m_model_identity"].sha256),
        "--structure-dim", str(frozen["structure_dim"]),
        "--ridge-alpha", str(frozen["ridge_alpha"]),
        "--graph-hidden-dim", str(frozen["graph_hidden_dim"]),
        "--dropout", str(frozen["dropout"]),
        "--residual-scale", str(frozen["residual_scale"]),
        "--huber-delta", str(frozen["huber_delta"]),
        "--dual-weight", str(frozen["dual_weight"]),
        "--receptor-weight", str(frozen["receptor_weight"]),
        "--marginal-contact-weight", str(lane_weights["marginal_contact_weight"]),
        "--pair-contact-weight", str(lane_weights["pair_contact_weight"]),
        "--contact-positive-class-fraction", str(frozen["contact_positive_class_fraction"]),
        "--contact-balance-epsilon", str(frozen["contact_balance_epsilon"]),
        "--component-gradient-telemetry-batches", str(frozen["component_gradient_telemetry_batches"]),
        "--ranking-weight", str(frozen["ranking_weight"]),
        "--ranking-minimum-delta", str(frozen["ranking_minimum_delta"]),
        "--ranking-temperature", str(frozen["ranking_temperature"]),
        "--residual-l2-weight", str(frozen["residual_l2_weight"]),
        "--gradient-accumulation", str(frozen["gradient_accumulation"]),
        "--head-learning-rate", str(frozen["head_learning_rate"]),
        "--weight-decay", str(frozen["weight_decay"]),
        "--gradient-clip", str(frozen["gradient_clip"]),
        "--evaluation-batch-size", str(frozen["evaluation_batch_size"]),
        "--precision", str(frozen["precision"]),
        "--seed", str(frozen["seed"]),
        "--device", "cuda:0",
    ]
    for prefix in frozen["structure_prefixes"]:
        command.extend(("--structure-prefix", str(prefix)))
    return command


def trainer_command(
    context: FreezeContext,
    input_closure: Mapping[str, Any],
    *,
    lane: str,
    fold: int,
    output_dir: pathlib.Path,
    smoke: bool,
) -> list[str]:
    require(lane in LANE_GPU, f"lane_invalid:{lane}")
    require(fold in FOLDS, f"fold_invalid:{fold}")
    command = _trainer_common_arguments(context, lane)
    command.extend(("--lane", lane, "--outer-fold", str(fold), "--output-dir", str(output_dir)))
    if lane in {"B_VHH3D", "C_PATCH", "D_FULL_PAIR"}:
        command.extend(("--graph-cache-dir", str(context.artifacts["vhh_graph_cache_npz"].path.parent)))
    if lane in {"C_PATCH", "D_FULL_PAIR"}:
        target = input_closure["augmented_target_graph"]
        command.extend(("--target-graph-pt", target["artifact_path"], "--target-graph-receipt", target["receipt_path"]))
    if lane == "D_FULL_PAIR":
        command.extend(("--pair-contact-tsv-gz", str(context.artifacts["pair_contact_tsv_gz"].path)))
    if smoke:
        command.extend(("--smoke-mode", "--max-epochs", "1"))
    else:
        command.extend(("--contact-loss-amendment", str(context.artifacts["contact_loss_amendment_v2_2"].path)))
        command.extend(("--max-epochs", str(context.deployment["trainer_arguments"]["maximum_epochs"])))
    return command


def command_sha(command: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps(list(command), separators=(",", ":")).encode("utf-8")).hexdigest()


def _validate_result_output(output_dir: pathlib.Path, *, lane: str, fold: int) -> dict[str, Any]:
    result_path = output_dir / "RESULT.json"
    result = load_regular_json(result_path, "trainer_result")
    require(result.get("status") == "PASS_OUTER_FOLD_COMPLETE", "trainer_result_status")
    require(result.get("lane") == lane and result.get("outer_fold") == fold, "trainer_result_identity")
    artifacts = result.get("artifacts") or {}
    for filename in ("contract.json", "head_final.pt", "outer_test_predictions.tsv"):
        path = output_dir / filename
        require(path.is_file() and not path.is_symlink(), f"trainer_artifact_missing_or_symlink:{filename}")
        require(artifacts.get(filename) == sha256_file(path), f"trainer_artifact_hash_mismatch:{filename}")
    return {"result_path": str(result_path), "result_sha256": sha256_file(result_path)}


def terminal_payload(
    *,
    status: str,
    context: FreezeContext,
    closure_sha: str,
    lane: str,
    fold: int | None,
    command: Sequence[str],
    return_code: int,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "pvrig_v6_residue_v2_node1_stage_terminal_v1",
        "status": status,
        "created_at_utc": utc_now(),
        "implementation_freeze_sha256": context.sha256,
        "deployment_input_closure_sha256": closure_sha,
        "lane": lane,
        "outer_fold": fold,
        "command_sha256": command_sha(command),
        "return_code": return_code,
        "physical_gpu": LANE_GPU[lane],
        "gpu0_forbidden": True,
        "gpu3_forbidden": True,
        "forbidden_gpus": list(FORBIDDEN_GPUS),
        "reserved_gpus": list(RESERVED_GPUS),
        "cpu_threads_per_process": CPU_THREADS_PER_PROCESS,
        "evidence": dict(evidence or {}),
    }


def validate_reusable_terminal(
    terminal_path: pathlib.Path,
    *,
    context: FreezeContext,
    closure_sha: str,
    lane: str,
    fold: int,
    command: Sequence[str],
    output_dir: pathlib.Path,
) -> bool:
    if not terminal_path.exists():
        return False
    terminal = load_regular_json(terminal_path, "fold_terminal")
    require(terminal.get("status") == "PASS_FOLD_COMPLETE", "resume_terminal_not_pass")
    require(terminal.get("implementation_freeze_sha256") == context.sha256, "resume_freeze_sha_mismatch")
    require(terminal.get("deployment_input_closure_sha256") == closure_sha, "resume_input_closure_sha_mismatch")
    require(terminal.get("lane") == lane and terminal.get("outer_fold") == fold, "resume_fold_identity")
    require(terminal.get("command_sha256") == command_sha(command), "resume_command_sha_mismatch")
    require(terminal.get("return_code") == 0, "resume_return_code_not_zero")
    evidence = _validate_result_output(output_dir, lane=lane, fold=fold)
    require(terminal.get("evidence") == evidence, "resume_result_evidence_mismatch")
    return True


def run_fold(
    context: FreezeContext,
    input_closure: Mapping[str, Any],
    *,
    lane: str,
    fold: int,
    smoke: bool,
) -> pathlib.Path:
    closure_path = REMOTE_ROOT / "status" / INPUT_CLOSURE_NAME
    closure_sha = sha256_file(closure_path)
    if smoke:
        stage_root = REMOTE_ROOT / "runtime" / "smoke" / lane
    else:
        stage_root = REMOTE_ROOT / "runtime" / lane / "production" / f"fold_{fold}"
    output_dir = stage_root / "output"
    terminal_path = stage_root / TERMINAL_NAME
    command = trainer_command(context, input_closure, lane=lane, fold=fold, output_dir=output_dir, smoke=smoke)
    expected_pass = "PASS_SMOKE_COMPLETE" if smoke else "PASS_FOLD_COMPLETE"
    if terminal_path.exists():
        if smoke:
            terminal = load_regular_json(terminal_path, "smoke_terminal")
            require(terminal.get("status") == expected_pass, "resume_smoke_terminal_not_pass")
            require(terminal.get("implementation_freeze_sha256") == context.sha256, "resume_smoke_freeze_sha")
            require(terminal.get("deployment_input_closure_sha256") == closure_sha, "resume_smoke_closure_sha")
            require(terminal.get("command_sha256") == command_sha(command), "resume_smoke_command_sha")
            require(terminal.get("evidence") == _validate_result_output(output_dir, lane=lane, fold=fold), "resume_smoke_evidence")
            return terminal_path
        if validate_reusable_terminal(
            terminal_path, context=context, closure_sha=closure_sha, lane=lane,
            fold=fold, command=command, output_dir=output_dir,
        ):
            return terminal_path
    require(not stage_root.exists(), f"stage_exists_without_reusable_pass_terminal:{stage_root}")
    stage_root.mkdir(parents=True, exist_ok=False)
    return_code = _run_logged(command, gpu=LANE_GPU[lane], log_path=stage_root / "run.log")
    evidence: dict[str, Any] = {}
    status = expected_pass
    if return_code == 0:
        try:
            evidence = _validate_result_output(output_dir, lane=lane, fold=fold)
        except Exception:
            status = "FAIL_OUTPUT_VALIDATION"
    else:
        status = "FAIL_TRAINER_RETURN_CODE"
    atomic_json(terminal_path, terminal_payload(
        status=status, context=context, closure_sha=closure_sha, lane=lane,
        fold=fold, command=command, return_code=return_code, evidence=evidence,
    ))
    require(status == expected_pass, f"training_stage_failed:{lane}:{fold}:{status}")
    return terminal_path


def collector_command(context: FreezeContext, lane: str, output_dir: pathlib.Path) -> list[str]:
    command = [
        str(FIXED_PYTHON), str(context.artifacts["collector"].path),
        "--training-tsv", str(context.artifacts["training_tsv"].path),
        "--preregistration", str(context.artifacts["preregistration"].path),
        "--output-dir", str(output_dir),
        "--bootstrap-repetitions", "1000",
        "--bootstrap-seed", "20260718",
    ]
    for fold in FOLDS:
        command.extend(("--prediction-tsv", str(
            REMOTE_ROOT / "runtime" / lane / "production" / f"fold_{fold}" / "output" / "outer_test_predictions.tsv"
        )))
    return command


def run_collector(context: FreezeContext, lane: str) -> pathlib.Path:
    closure_path = REMOTE_ROOT / "status" / INPUT_CLOSURE_NAME
    closure_sha = sha256_file(closure_path)
    stage_root = REMOTE_ROOT / "runtime" / lane / "collector" / "formal"
    output_dir = stage_root / "output"
    terminal_path = stage_root / TERMINAL_NAME
    command = collector_command(context, lane, output_dir)
    if terminal_path.exists():
        terminal = load_regular_json(terminal_path, "collector_terminal")
        require(terminal.get("status") == "PASS_COLLECTOR_COMPLETE", "resume_collector_not_pass")
        require(terminal.get("implementation_freeze_sha256") == context.sha256, "resume_collector_freeze_sha")
        require(terminal.get("deployment_input_closure_sha256") == closure_sha, "resume_collector_closure_sha")
        require(terminal.get("command_sha256") == command_sha(command), "resume_collector_command_sha")
        report_path = output_dir / "OOF_PROMOTION_REPORT.json"
        report = load_regular_json(report_path, "collector_report")
        require(terminal.get("evidence", {}).get("report_sha256") == sha256_file(report_path), "resume_collector_report_sha")
        return terminal_path
    require(not stage_root.exists(), f"collector_stage_exists_without_pass_terminal:{lane}")
    stage_root.mkdir(parents=True, exist_ok=False)
    return_code = _run_logged(command, gpu=LANE_GPU[lane], log_path=stage_root / "run.log")
    evidence: dict[str, Any] = {}
    status = "FAIL_COLLECTOR_RETURN_CODE"
    if return_code == 0:
        report_path = output_dir / "OOF_PROMOTION_REPORT.json"
        report = load_regular_json(report_path, "collector_report")
        gates = json.loads(context.artifacts["preregistration"].path.read_text(encoding="utf-8"))["promotion_gates"]
        require(report.get("status") in {gates["negative_status"], gates["positive_status"]}, "collector_report_status_invalid")
        evidence = {"report_path": str(report_path), "report_sha256": sha256_file(report_path), "decision": report["status"]}
        status = "PASS_COLLECTOR_COMPLETE"
    atomic_json(terminal_path, terminal_payload(
        status=status, context=context, closure_sha=closure_sha, lane=lane,
        fold=None, command=command, return_code=return_code, evidence=evidence,
    ))
    require(status == "PASS_COLLECTOR_COMPLETE", f"collector_failed:{lane}:{status}")
    return terminal_path


def dry_run_plan(context: FreezeContext) -> dict[str, Any]:
    dummy_closure = {
        "augmented_target_graph": {
            "artifact_path": "$AUGMENTED_TARGET_PT_FROM_DEPLOYMENT_INPUT_CLOSURE",
            "receipt_path": "$AUGMENTED_TARGET_RECEIPT_FROM_DEPLOYMENT_INPUT_CLOSURE",
        }
    }
    return {
        "status": "PASS_DRY_RUN_PLAN_NO_MUTATION",
        "runtime_root": str(REMOTE_ROOT),
        "implementation_freeze_sha256": context.sha256,
        "augmentation": {"physical_gpu": AUGMENTATION_GPU, "command": augmentation_command(context)},
        "smoke": {
            lane: {
                "physical_gpu": gpu,
                "command": trainer_command(
                    context, dummy_closure, lane=lane, fold=0,
                    output_dir=REMOTE_ROOT / "runtime" / "smoke" / lane / "output", smoke=True,
                ),
            }
            for lane, gpu in LANE_GPU.items()
        },
        "production": {
            lane: {
                "physical_gpu": gpu,
                "fold_order": list(FOLDS),
                "commands": [
                    trainer_command(
                        context, dummy_closure, lane=lane, fold=fold,
                        output_dir=REMOTE_ROOT / "runtime" / lane / "production" / f"fold_{fold}" / "output",
                        smoke=False,
                    )
                    for fold in FOLDS
                ],
            }
            for lane, gpu in LANE_GPU.items()
        },
        "collectors_after_all_20_folds": list(LANE_GPU),
        "v4_f_test32_synced_or_opened": False,
    }


def run_pipeline(context: FreezeContext, *, resume: bool) -> dict[str, Any]:
    verify_python(FIXED_PYTHON)
    observed = validate_static_artifacts(context)
    validate_gpu_inventory()
    if resume:
        validate_bootstrap_resume(context, observed)
    else:
        free_gib = validate_fresh_root(REMOTE_ROOT)
        initialize_runtime_root(context, observed, free_gib)
    augmented_root = context.artifacts[POST_ARTIFACT].path
    if not augmented_root.exists():
        rc = _run_logged(
            augmentation_command(context), gpu=AUGMENTATION_GPU,
            log_path=REMOTE_ROOT / "logs" / "target_esm2_augmentation.log",
        )
        require(rc == 0, f"target_augmentation_failed:{rc}")
    augmented = validate_augmented_target(context)
    closure_path = write_input_closure(context, augmented, observed)
    input_closure = validate_input_closure(context, observed)
    # Smoke lanes run in parallel.  Production is prohibited until all four pass.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            lane: executor.submit(run_fold, context, input_closure, lane=lane, fold=0, smoke=True)
            for lane in LANE_GPU
        }
        smoke_terminals = {lane: str(future.result()) for lane, future in futures.items()}
    # Four lanes run concurrently; each lane owns a strictly sequential 0..4 fold loop.
    def run_lane(lane: str) -> list[str]:
        return [str(run_fold(context, input_closure, lane=lane, fold=fold, smoke=False)) for fold in FOLDS]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {lane: executor.submit(run_lane, lane) for lane in LANE_GPU}
        fold_terminals = {lane: future.result() for lane, future in futures.items()}
    # Barrier above proves all 20 folds before any collector starts.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {lane: executor.submit(run_collector, context, lane) for lane in LANE_GPU}
        collectors = {lane: str(future.result()) for lane, future in futures.items()}
    terminal = {
        "schema_version": "pvrig_v6_residue_v2_node1_four_lane_terminal_v1",
        "status": "PASS_ALL_FOUR_LANES_20_FOLDS_AND_COLLECTORS",
        "created_at_utc": utc_now(),
        "implementation_freeze_sha256": context.sha256,
        "deployment_input_closure_sha256": sha256_file(closure_path),
        "smoke_terminals": smoke_terminals,
        "fold_terminals": fold_terminals,
        "collector_terminals": collectors,
        "gpu0_forbidden": True,
        "gpu3_forbidden": True,
        "forbidden_gpus": list(FORBIDDEN_GPUS),
        "reserved_gpus": list(RESERVED_GPUS),
        "cpu_threads_per_process": CPU_THREADS_PER_PROCESS,
        "v4_f_test32_synced_or_opened": False,
    }
    atomic_json(REMOTE_ROOT / "status" / "FOUR_LANE_TERMINAL.json", terminal)
    return terminal


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--implementation-freeze", required=True, type=pathlib.Path)
    group = value.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--run", action="store_true")
    group.add_argument("--resume", action="store_true")
    return value


def main() -> None:
    args = parser().parse_args()
    context = load_freeze(args.implementation_freeze)
    observed = validate_static_artifacts(context)
    if args.dry_run:
        verify_python(FIXED_PYTHON)
        validate_gpu_inventory()
        free_gib = validate_fresh_root(REMOTE_ROOT)
        plan = dry_run_plan(context)
        plan["free_gib"] = free_gib
        plan["static_artifact_sha256"] = observed
        print(json.dumps(plan, indent=2, sort_keys=True))
        return
    print(json.dumps(run_pipeline(context, resume=args.resume), indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (DeploymentError, subprocess.CalledProcessError) as error:
        print(f"FAIL_NODE1_RESIDUE_V2_DEPLOYMENT:{error}", file=sys.stderr)
        raise SystemExit(1)
