#!/usr/bin/env python3
"""Build or verify the fail-closed Residue V2 implementation freeze.

The static freeze binds code, tests, governance, fixed inputs, the Node1
runtime identity, the 4-lane x 5-fold matrix, and the sealed-test boundary.
The ESM2-augmented PVRIG graph is deliberately bound in a second phase by
``DEPLOYMENT_INPUT_CLOSURE.json`` after GPU augmentation; it is never accepted
as an unverified static placeholder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "pvrig_v6_residue_v2_implementation_freeze_v1"
MATRIX_SCHEMA = "pvrig_v6_residue_v2_production_matrix_v1"
PRODUCTION_STATUS = "PASS_RESIDUE_V2_IMPLEMENTATION_FROZEN_FOR_NODE1_SMOKE"
PREPRODUCTION_STATUS = "PREPRODUCTION_PENDING_INPUTS_DO_NOT_TRAIN"
CHECK_STATUS = "PASS_RESIDUE_V2_IMPLEMENTATION_FREEZE_CHECK"
PENDING = "PENDING_REQUIRED_BEFORE_PRODUCTION"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

SCRIPT_PATH = Path(__file__).resolve()
RESIDUE_ROOT = SCRIPT_PATH.parents[1]
REPO_ROOT = SCRIPT_PATH.parents[5]
DEFAULT_MATRIX = RESIDUE_ROOT / "RESIDUE_V2_PRODUCTION_MATRIX.json"
DEFAULT_OUTPUT = RESIDUE_ROOT / "IMPLEMENTATION_FREEZE_V2.json"

CLAIM_BOUNDARY = (
    "Sequence and label-free-structure approximation of independent dual-receptor "
    "computational Docking geometry; not binding probability, affinity, experimental "
    "competition, blocking, Docking Gold, or final submission evidence."
)

LANE_GPU_MAP = {
    "A_DOMAIN": 1,
    "B_VHH3D": 2,
    "C_PATCH": 4,
    "D_FULL_PAIR": 5,
}
AUGMENTATION_GPU = 6
FORBIDDEN_GPUS = (0, 3)
RESERVED_GPUS = (7,)
FOLDS = tuple(range(5))

EXPECTED_IMPLEMENTATION_PATHS = frozenset(
    {
        "PLAN_V2_ZH.md",
        "CONTACT_LOSS_CALIBRATION_PREREGISTRATION_V2_1.json",
        "CONTACT_LOSS_CALIBRATION_PREREGISTRATION_V2_2.json",
        "LOSS_SCALE_PREFREEZE_AUDIT_ZH.md",
        "NUMERICAL_STABILITY_AMENDMENT_V2_3.json",
        "PREREGISTRATION_V2.json",
        "RESIDUE_V2_CONTRACT.json",
        "RESIDUE_V2_PRODUCTION_MATRIX.json",
        "V2_2_FORMAL_NUMERICAL_FAILURE_AUDIT_ZH.md",
        "contact_teacher_v4d/CONTRACT_V2.json",
        "contact_teacher_v4d/README_ZH.md",
        "contact_teacher_v4d/TEST_FIXTURE_CORRECTION_V2_1.md",
        "contact_teacher_v4d/src/extract_v4d_contact_teacher_v2.py",
        "contact_teacher_v4d/tests/test_extract_v4d_contact_teacher_v2.py",
        "calibration/CALIBRATION_SUPERSESSION_AUDIT_V1_TO_V1_2_ZH.md",
        "calibration/CONTACT_GRADIENT_CALIBRATION_MATRIX_V1.json",
        "calibration/CONTACT_GRADIENT_CALIBRATION_MATRIX_V1_1.json",
        "calibration/CONTACT_GRADIENT_CALIBRATION_MATRIX_V1_2.json",
        "calibration/NODE1_CONTACT_GRADIENT_CALIBRATION_RUNBOOK_V1.md",
        "calibration/NODE1_CONTACT_GRADIENT_CALIBRATION_RUNBOOK_V1_1.md",
        "calibration/NODE1_CONTACT_GRADIENT_CALIBRATION_RUNBOOK_V1_2.md",
        "calibration/node1_contact_gradient_calibration_v1.py",
        "calibration/node1_contact_gradient_calibration_v1_1.py",
        "calibration/node1_contact_gradient_calibration_v1_2.py",
        "calibration/test_node1_contact_gradient_calibration_v1.py",
        "calibration/test_node1_contact_gradient_calibration_v1_1.py",
        "calibration/test_node1_contact_gradient_calibration_v1_2.py",
        "deployment/NODE1_V2_PREFLIGHT.md",
        "deployment/NODE23_V4D_CONTACT_V2_VERIFICATION.md",
        "deployment/NODE1_RESIDUE_V2_FOUR_LANE_RUNBOOK_V1.md",
        "deployment/run_node23_v4d_contact_v2.sh",
        "deployment/node1_residue_v2_four_lane_v1.py",
        "deployment/test_node1_residue_v2_four_lane_v1.py",
        "src/augment_target_graph_esm2_v2.py",
        "src/build_dual_contact_targets_v2.py",
        "src/build_dual_pair_contact_targets_v2.py",
        "src/build_implementation_freeze_v2.py",
        "src/build_residue_graph_cache_v2.py",
        "src/build_target_graph_cache_v2.py",
        "src/collect_residue_oof_v2.py",
        "src/domain_balance_v2.py",
        "src/materialize_graph_inputs_v2.py",
        "src/residue_model_v2.py",
        "src/select_contact_loss_gradient_grid_v1.py",
        "src/select_contact_loss_gradient_grid_v2.py",
        "src/train_nested_residue_surrogate_v2.py",
        "tests/test_augment_target_graph_esm2_v2.py",
        "tests/test_build_dual_contact_targets_v2.py",
        "tests/test_build_dual_pair_contact_targets_v2.py",
        "tests/test_build_implementation_freeze_v2.py",
        "tests/test_build_residue_graph_cache_v2.py",
        "tests/test_build_target_graph_cache_v2.py",
        "tests/test_collect_residue_oof_v2.py",
        "tests/test_domain_balance_v2.py",
        "tests/test_materialize_graph_inputs_v2.py",
        "tests/test_residue_model_v2.py",
        "tests/test_select_contact_loss_gradient_grid_v1.py",
        "tests/test_select_contact_loss_gradient_grid_v2.py",
        "tests/test_train_nested_residue_surrogate_v2.py",
        "tests/test_v1_5_immutability.py",
    }
)

EXPECTED_ARTIFACT_LABELS = frozenset(
    {
        "training_tsv",
        "training_receipt",
        "v4d_teacher_receipt",
        "v4d_pair_teacher",
        "v4d_marginal_teacher",
        "v4d_pose_inventory",
        "dual_marginal_tsv_gz",
        "dual_marginal_receipt",
        "pair_contact_tsv_gz",
        "pair_contact_receipt",
        "vhh_graph_cache_npz",
        "vhh_graph_manifest",
        "vhh_graph_closure",
        "vhh_graph_cache_receipt",
        "vhh_graph_materialization_receipt",
        "base_target_cache_npz",
        "base_target_pt",
        "base_target_manifest",
        "base_target_receipt",
        "augment_target_script",
        "esm2_650m_model_identity",
        "augmented_target_graph",
        "contact_loss_amendment_v2_2",
        "contact_gradient_calibration_report_v2_2",
        "contact_gradient_calibration_receipt_v2_2",
        "residue_v1_residue_model",
        "residue_v1_base_trainer",
        "residue_v1_v1_5_trainer",
    }
)

EXPECTED_V1_5_IMMUTABLE = {
    "implementation_freeze_v1_5": "3a4046462bcf138c25c5c36005d1f6e24f2df3f931fe32369dba80ee834e155e",
    "production_matrix_v1_2": "48fadb1b104d7528a574972e5d391f88b1a21df375e281e119025e5ed170683d",
    "trainer_v1_5": "6c4ee5e9827854406615df6e61b63e5d445d27535eb00a44fca5570c062779af",
    "collector_v1_5": "a15db4aceaeb8c62bca277d9d39015aff3e7e95bacf30a3dd635c1d18558cee0",
    "residue_model_v1": "c6745faf5d9c4afb101015f751b89e2aefb82aa4ccfbf3259c2d2c9cba4b05bb",
    "dual_contact_builder_v1": "59f0f8bc2f311a776b2d61ea2d075d55488e811b68d55d3665e8a760069594e5",
}

EXPECTED_CONTACT_GOVERNANCE_HASHES = {
    "contact_loss_amendment_v2_2": "578e428ade29dba5271f5a34a3dfffa2ac4deb6a165a45d201256d71dac87fa2",
    "contact_gradient_calibration_report_v2_2": "d59ca85b9f6e968c3cacbfb8bef33f99521675eaa3a5e75f5fd5366dc3d9f1bd",
    "contact_gradient_calibration_receipt_v2_2": "54e2d7a03c1b44209641129951549edc1b47b4acb18315ecb25e8300f2dc894c",
}

EXPECTED_TRANSITIVE_HASHES = {
    "residue_v1_residue_model": "c6745faf5d9c4afb101015f751b89e2aefb82aa4ccfbf3259c2d2c9cba4b05bb",
    "residue_v1_base_trainer": "1bd76aa3128f7cbd54c94004760547102c402dc5127a896669e0e072ca7ed5d8",
    "residue_v1_v1_5_trainer": "6c4ee5e9827854406615df6e61b63e5d445d27535eb00a44fca5570c062779af",
}

EXPECTED_PROMOTION_GATES = {
    "global_spearman_delta_min": 0.010,
    "v4d_spearman_delta_min": 0.0,
    "v4h_spearman_delta_min": 0.0,
    "parent_win_delta_min": 0.01,
    "parent_loss_delta_max": -0.01,
    "global_parent_wins_strictly_greater_than_losses": True,
    "per_source_parent_wins_greater_than_or_equal_to_losses": True,
    "global_top20_budget": 302,
    "global_top20_net_hit_gain_min": 5,
    "v4d_top20_budget": 46,
    "v4h_top20_budget": 257,
    "per_source_top20_net_hit_gain_min": 0,
    "parent_bootstrap_positive_fraction_min": 0.80,
    "parent_bootstrap_median_delta_strictly_positive": True,
    "per_source_parent_bootstrap_positive_fraction_min": 0.80,
    "per_source_parent_bootstrap_median_delta_min": 0.0,
    "per_source_mae_max_degradation": 0.001,
    "all_required": True,
    "negative_status": "DO_NOT_PROMOTE_RESIDUE_V2",
    "positive_status": "PROMOTE_RESIDUE_V2_OVER_M2",
}

EXPECTED_TECHNICAL_SUPERSESSION = {
    "amendment": "NUMERICAL_STABILITY_AMENDMENT_V2_3.json",
    "partial_checkpoint_reuse": False,
    "superseded_freeze_sha256": "2659325b58d2c1e8faeb6f20b71cb63a6216a21ef5803d71886aa100c2eff471",
    "superseded_version": "V2.2",
}

EXPECTED_TRAINER_ARGUMENTS = {
    "structure_prefixes": [
        "ALL__",
        "CDR1_CDR2__", "CDR1_CDR3__", "CDR1_FRAMEWORK__", "CDR1__",
        "CDR2_CDR3__", "CDR2_FRAMEWORK__", "CDR2__",
        "CDR3_FRAMEWORK__", "CDR3__", "CDR_ALL__", "FRAMEWORK__",
    ],
    "structure_dim": 126,
    "ridge_alpha": 10.0,
    "graph_hidden_dim": 128,
    "dropout": 0.25,
    "residual_scale": 0.02,
    "huber_delta": 0.03,
    "dual_weight": 1.0,
    "receptor_weight": 0.35,
    "lane_contact_weights": {
        "A_DOMAIN": {"marginal_contact_weight": 0.01, "pair_contact_weight": 0.005},
        "B_VHH3D": {"marginal_contact_weight": 0.0025, "pair_contact_weight": 0.00125},
        "C_PATCH": {"marginal_contact_weight": 0.000625, "pair_contact_weight": 0.0003125},
        "D_FULL_PAIR": {"marginal_contact_weight": 0.000625, "pair_contact_weight": 0.0003125},
    },
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
    "maximum_epochs": 8,
}


class FreezeError(RuntimeError):
    """Raised when any frozen result-affecting binding is incomplete."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FreezeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    require(not path.is_symlink(), f"output_symlink_forbidden:{path}")
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


def snapshot(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"{label}_missing_or_symlink:{path}")
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}


def observed_implementation_paths(residue_root: Path) -> set[str]:
    result: set[str] = set()
    roots = (
        (residue_root, {".json", ".md"}),
        (residue_root / "src", {".py", ".sh"}),
        (residue_root / "tests", {".py"}),
        (residue_root / "contact_teacher_v4d", {".py", ".json", ".md"}),
        (residue_root / "calibration", {".py", ".json", ".md"}),
        # Runtime/smoke JSON receipts may live beside deployment code, but they
        # are evidence outputs, not executable or governance inputs.
        (residue_root / "deployment", {".py", ".sh", ".md"}),
    )
    for root, result_suffixes in roots:
        if not root.exists():
            continue
        iterator = root.iterdir() if root == residue_root else root.rglob("*")
        for path in iterator:
            if not path.is_file() and not path.is_symlink():
                continue
            relative = path.relative_to(residue_root).as_posix()
            if "__pycache__" in path.parts or path.suffix not in result_suffixes:
                continue
            if path.name.startswith("IMPLEMENTATION_FREEZE_V2"):
                continue
            result.add(relative)
    return result


def validate_exact_implementation_set(residue_root: Path, expected: Sequence[str]) -> dict[str, Any]:
    expected_set = set(expected)
    require(expected_set == set(EXPECTED_IMPLEMENTATION_PATHS), "matrix_implementation_allowlist_not_canonical")
    observed = observed_implementation_paths(residue_root)
    missing = sorted(expected_set - observed)
    extra = sorted(observed - expected_set)
    require(not missing, f"implementation_files_missing:{missing}")
    require(not extra, f"implementation_files_extra:{extra}")
    records: dict[str, Any] = {}
    for relative in sorted(expected_set):
        path = residue_root / relative
        records[relative] = snapshot(path, f"implementation:{relative}")
    return records


def runtime_identity() -> dict[str, Any]:
    try:
        import torch
    except ImportError as error:
        raise FreezeError("torch_import_failed") from error
    cuda = bool(torch.cuda.is_available())
    names = [torch.cuda.get_device_name(index) for index in range(torch.cuda.device_count())] if cuda else []
    return {
        # Preserve the invoked venv interpreter path. Resolving a venv symlink
        # to /usr/bin/python would discard the environment identity we freeze.
        "python_executable": str(Path(sys.executable)),
        "python_version": platform.python_version(),
        "torch_version": str(torch.__version__),
        "torch_cuda_version": str(torch.version.cuda),
        "cuda_available": cuda,
        "cuda_device_count": int(torch.cuda.device_count()),
        "cuda_device_names": names,
    }


def validate_runtime(expected: Mapping[str, Any], observed: Mapping[str, Any], production: bool) -> None:
    required = {
        "python_executable", "python_version", "torch_version", "torch_cuda_version",
        "cuda_available", "cuda_device_count_min", "gpu_name",
    }
    require(set(expected) == required, "runtime_identity_fields_invalid")
    if not production:
        return
    for key in ("python_executable", "python_version", "torch_version", "torch_cuda_version", "cuda_available"):
        require(observed.get(key) == expected[key], f"runtime_identity_mismatch:{key}:{observed.get(key)}:{expected[key]}")
    require(int(observed.get("cuda_device_count", 0)) >= int(expected["cuda_device_count_min"]), "runtime_cuda_device_count")
    names = list(observed.get("cuda_device_names") or [])
    require(len(names) >= 8, "runtime_cuda_device_names_incomplete")
    for physical in tuple(LANE_GPU_MAP.values()) + (AUGMENTATION_GPU,):
        require(names[physical] == expected["gpu_name"], f"runtime_gpu_identity:{physical}:{names[physical]}")


def validate_matrix(matrix: Mapping[str, Any]) -> None:
    require(matrix.get("schema_version") == MATRIX_SCHEMA, "matrix_schema_invalid")
    require(matrix.get("claim_boundary") == CLAIM_BOUNDARY, "matrix_claim_boundary_invalid")
    require(matrix.get("primary_target") == "R_dual_min", "matrix_primary_target_invalid")
    require(matrix.get("implementation_allowlist") == sorted(EXPECTED_IMPLEMENTATION_PATHS), "matrix_allowlist_invalid")
    require(matrix.get("promotion_gates") == EXPECTED_PROMOTION_GATES, "matrix_promotion_gates_invalid")
    require(matrix.get("technical_supersession") == EXPECTED_TECHNICAL_SUPERSESSION, "matrix_technical_supersession_invalid")
    require(matrix.get("bootstrap") == {"repetitions": 1000, "seed": 20260718}, "matrix_bootstrap_invalid")
    require(matrix.get("v1_5_immutable_sha256") == EXPECTED_V1_5_IMMUTABLE, "matrix_v1_5_immutable_invalid")

    deployment = matrix.get("node1_deployment")
    require(isinstance(deployment, Mapping), "node1_deployment_missing")
    for key in (
        "remote_root", "bundle_root", "python", "min_free_gib", "augmentation_gpu", "lane_gpu_map",
        "forbidden_gpus", "reserved_gpus", "cpu_threads_per_process", "artifacts", "trainer_arguments",
    ):
        require(key in deployment, f"node1_deployment_field_missing:{key}")
    require(str(deployment["remote_root"]).startswith("/data1/qlyu/projects/"), "remote_root_invalid")
    require(deployment["python"] == "/data1/qlyu/software/envs/pvrig-v6-tc/bin/python", "node1_python_invalid")
    require(deployment["min_free_gib"] == 200, "node1_min_free_gib_invalid")
    require(Path(str(deployment["bundle_root"])).is_absolute(), "bundle_root_invalid")
    require(deployment["augmentation_gpu"] == AUGMENTATION_GPU, "augmentation_gpu_invalid")
    require(deployment["lane_gpu_map"] == LANE_GPU_MAP, "lane_gpu_map_invalid")
    require(deployment["forbidden_gpus"] == list(FORBIDDEN_GPUS), "forbidden_gpu_map_invalid")
    require(deployment["reserved_gpus"] == list(RESERVED_GPUS), "reserved_gpu_map_invalid")
    require(deployment["cpu_threads_per_process"] == 8, "cpu_threads_per_process_invalid")
    assignments = {deployment["augmentation_gpu"], *deployment["lane_gpu_map"].values()}
    require(not assignments.intersection(FORBIDDEN_GPUS), "forbidden_gpu_assigned")
    require(not assignments.intersection(RESERVED_GPUS), "reserved_gpu_assigned")
    require(deployment["trainer_arguments"] == EXPECTED_TRAINER_ARGUMENTS, "trainer_arguments_invalid")

    artifacts = deployment["artifacts"]
    require(isinstance(artifacts, Mapping), "artifacts_not_object")
    require(set(artifacts) == set(EXPECTED_ARTIFACT_LABELS), "artifact_label_closure_invalid")
    for label, record in artifacts.items():
        require(isinstance(record, Mapping), f"artifact_record_invalid:{label}")
        require(Path(str(record.get("path", ""))).is_absolute(), f"artifact_path_not_absolute:{label}")
        if label == "augmented_target_graph":
            require(record.get("phase") == "post_augmentation_binding", "augmented_target_phase_invalid")
            require(record.get("sha256") is None, "augmented_target_static_hash_forbidden")
            require(record.get("closure_required") is True, "augmented_target_closure_not_required")
        else:
            require(record.get("phase") == "pre_freeze_binding", f"artifact_phase_invalid:{label}")
            digest = record.get("sha256")
            require(digest == PENDING or (isinstance(digest, str) and HEX64.fullmatch(digest)), f"artifact_sha_invalid:{label}")
    for label, digest in {**EXPECTED_CONTACT_GOVERNANCE_HASHES, **EXPECTED_TRANSITIVE_HASHES}.items():
        require(artifacts[label].get("sha256") == digest, f"artifact_frozen_hash_invalid:{label}")
    bundle_root = Path(str(deployment["bundle_root"]))
    expected_bundle_paths = {
        "contact_loss_amendment_v2_2": bundle_root / "inputs/contact_loss_amendment_v2_2/CONTACT_LOSS_AMENDMENT_V2_2.json",
        "contact_gradient_calibration_report_v2_2": bundle_root / "inputs/contact_loss_amendment_v2_2/CONTACT_GRADIENT_CALIBRATION_REPORT_V2_2.json",
        "contact_gradient_calibration_receipt_v2_2": bundle_root / "inputs/contact_loss_amendment_v2_2/RUN_RECEIPT.json",
        "residue_v1_residue_model": bundle_root / "residue_v1/src/residue_model.py",
        "residue_v1_base_trainer": bundle_root / "residue_v1/src/train_nested_residue_surrogate.py",
        "residue_v1_v1_5_trainer": bundle_root / "residue_v1/src/train_nested_residue_surrogate_v1_5.py",
    }
    for label, path in expected_bundle_paths.items():
        require(artifacts[label].get("path") == str(path), f"artifact_bundle_path_invalid:{label}")

    lanes = matrix.get("lanes")
    require(isinstance(lanes, list) and [row.get("lane") for row in lanes] == list(LANE_GPU_MAP), "lane_order_invalid")
    require(all(row.get("physical_gpu") == LANE_GPU_MAP[row["lane"]] for row in lanes), "lane_gpu_binding_invalid")
    require(all(row.get("outer_folds") == list(FOLDS) for row in lanes), "lane_fold_binding_invalid")
    runs = matrix.get("production_runs")
    expected_runs = [
        {"lane": lane, "outer_fold": fold, "physical_gpu": gpu}
        for lane, gpu in LANE_GPU_MAP.items() for fold in FOLDS
    ]
    require(runs == expected_runs, "production_4x5_run_closure_invalid")

    sealed = matrix.get("sealed_test32_exclusion")
    require(isinstance(sealed, Mapping), "sealed_test32_exclusion_missing")
    require(sealed.get("status") == "SEALED_UNTIL_PREDICTION_FREEZE", "sealed_test32_status_invalid")
    require(sealed.get("path_access_count") == 0, "sealed_test32_access_nonzero")
    require(sealed.get("training_use_forbidden") is True, "sealed_test32_training_not_forbidden")
    require(sealed.get("hyperparameter_use_forbidden") is True, "sealed_test32_tuning_not_forbidden")


def validate_artifacts(
    artifacts: Mapping[str, Mapping[str, Any]],
    *,
    production: bool,
) -> tuple[dict[str, Any], list[str]]:
    frozen: dict[str, Any] = {}
    pending: list[str] = []
    for label in sorted(artifacts):
        record = artifacts[label]
        path = Path(str(record["path"]))
        if record["phase"] == "post_augmentation_binding":
            frozen[label] = {
                "phase": "post_augmentation_binding",
                "path": str(path),
                "sha256": None,
                "closure_required": True,
                "closure_path": "status/DEPLOYMENT_INPUT_CLOSURE.json",
            }
            continue
        expected = str(record["sha256"])
        if expected == PENDING:
            pending.append(label)
            frozen[label] = {"phase": "pre_freeze_binding", "path": str(path), "sha256": PENDING}
            continue
        if not path.is_file() or path.is_symlink():
            if production or not record.get("remote_only", False):
                raise FreezeError(f"artifact_missing_or_symlink:{label}:{path}")
            pending.append(f"{label}:remote_validation")
            frozen[label] = {
                "phase": "pre_freeze_binding", "path": str(path), "sha256": expected,
                "availability": "REMOTE_VALIDATION_REQUIRED",
            }
            continue
        actual = sha256_file(path)
        require(actual == expected, f"artifact_hash_mismatch:{label}:{actual}:{expected}")
        frozen[label] = {"phase": "pre_freeze_binding", **snapshot(path, f"artifact:{label}")}
    if production:
        require(not pending, f"production_pending_artifacts_forbidden:{pending}")
    return frozen, pending


def validate_contact_governance(
    artifacts: Mapping[str, Mapping[str, Any]],
    trainer_arguments: Mapping[str, Any],
    *,
    production: bool,
) -> dict[str, Any]:
    labels = EXPECTED_CONTACT_GOVERNANCE_HASHES
    paths = {label: Path(str(artifacts[label]["path"])) for label in labels}
    if not production and any(not path.is_file() or path.is_symlink() for path in paths.values()):
        return {
            "status": "REMOTE_VALIDATION_REQUIRED_BEFORE_PRODUCTION",
            "expected_sha256": dict(EXPECTED_CONTACT_GOVERNANCE_HASHES),
        }
    amendment = load_json(paths["contact_loss_amendment_v2_2"], "contact_loss_amendment_v2_2")
    report = load_json(paths["contact_gradient_calibration_report_v2_2"], "contact_gradient_calibration_report_v2_2")
    receipt = load_json(paths["contact_gradient_calibration_receipt_v2_2"], "contact_gradient_calibration_receipt_v2_2")
    require(amendment.get("schema_version") == "pvrig_v6_residue_v2_contact_loss_amendment_v2_2", "contact_amendment_schema")
    require(amendment.get("status") == "FROZEN_BEFORE_ANY_FORMAL_RESIDUE_V2_TRAINING", "contact_amendment_status")
    require(amendment.get("lane_weights") == EXPECTED_TRAINER_ARGUMENTS["lane_contact_weights"], "contact_amendment_lane_weights")
    calibration = amendment.get("calibration") or {}
    require(calibration.get("v4_f_test32_access_count") == 0, "contact_amendment_v4f_access")
    require(calibration.get("input_hashes") and set(calibration["input_hashes"]) == set(LANE_GPU_MAP), "contact_amendment_input_hash_closure")
    require(report.get("status") == "PASS_OPEN_ONLY_ONE_BATCH_PRESTEP_LANE_SPECIFIC_GRADIENT_CALIBRATION", "contact_report_status")
    require(report.get("calibration") == calibration, "contact_report_calibration_mismatch")
    require(report.get("selection_used_prediction_metrics") is False, "contact_report_prediction_metrics_used")
    require(report.get("v4_f_test32_access_count") == 0, "contact_report_v4f_access")
    require(receipt.get("schema_version") == "pvrig_v6_residue_v2_contact_gradient_calibration_receipt_v2_2", "contact_receipt_schema")
    require(receipt.get("status") == report.get("status"), "contact_receipt_status")
    require(receipt.get("outputs") == {
        "CONTACT_GRADIENT_CALIBRATION_REPORT_V2_2.json": sha256_file(paths["contact_gradient_calibration_report_v2_2"]),
        "CONTACT_LOSS_AMENDMENT_V2_2.json": sha256_file(paths["contact_loss_amendment_v2_2"]),
    }, "contact_receipt_output_hashes")
    require(trainer_arguments.get("lane_contact_weights") == amendment.get("lane_weights"), "trainer_contact_weights_not_amendment")
    return {
        "status": "PASS_CONTACT_LOSS_AMENDMENT_V2_2_BOUND",
        "lane_weights": amendment["lane_weights"],
        "input_result_sha256": calibration["input_hashes"],
        "artifact_sha256": {label: sha256_file(path) for label, path in paths.items()},
        "prediction_metrics_used": False,
        "v4_f_test32_access_count": 0,
    }


def validate_v1_5(matrix: Mapping[str, Any], production: bool) -> tuple[dict[str, Any], list[str]]:
    paths = matrix.get("v1_5_immutable_paths")
    require(isinstance(paths, Mapping) and set(paths) == set(EXPECTED_V1_5_IMMUTABLE), "v1_5_path_closure_invalid")
    result: dict[str, Any] = {}
    pending: list[str] = []
    for label, expected in EXPECTED_V1_5_IMMUTABLE.items():
        path = Path(str(paths[label]))
        require(path.is_absolute(), f"v1_5_path_not_absolute:{label}")
        if not path.is_file() or path.is_symlink():
            if production:
                raise FreezeError(f"v1_5_file_missing_or_symlink:{label}:{path}")
            pending.append(f"v1_5:{label}:remote_validation")
            result[label] = {"path": str(path), "sha256": expected, "availability": "REMOTE_VALIDATION_REQUIRED"}
            continue
        actual = sha256_file(path)
        require(actual == expected, f"v1_5_hash_mismatch:{label}:{actual}:{expected}")
        result[label] = snapshot(path, f"v1_5:{label}")
    return result, pending


def build_payload(
    *,
    residue_root: Path,
    matrix_path: Path,
    production: bool,
    observed_runtime: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    matrix = load_json(matrix_path, "production_matrix")
    validate_matrix(matrix)
    implementation = validate_exact_implementation_set(residue_root, matrix["implementation_allowlist"])
    preregistration = load_json(residue_root / "PREREGISTRATION_V2.json", "preregistration")
    require(preregistration.get("promotion_gates") == EXPECTED_PROMOTION_GATES, "preregistration_promotion_gates_invalid")
    excluded = preregistration.get("sealed_and_excluded") or {}
    require(excluded.get("v4_f_test32_access") is True, "preregistration_test32_exclusion_invalid")
    require(excluded.get("open_development_hyperparameter_selection") is True, "preregistration_open_development_exclusion_invalid")
    runtime = dict(observed_runtime or runtime_identity())
    expected_runtime = matrix["node1_deployment"]["runtime_identity"]
    validate_runtime(expected_runtime, runtime, production)
    artifacts, artifact_pending = validate_artifacts(
        matrix["node1_deployment"]["artifacts"], production=production,
    )
    contact_governance = validate_contact_governance(
        matrix["node1_deployment"]["artifacts"],
        matrix["node1_deployment"]["trainer_arguments"],
        production=production,
    )
    v1_5, v1_pending = validate_v1_5(matrix, production)
    pending = sorted(artifact_pending + v1_pending)
    if production:
        require(not pending, f"production_pending_forbidden:{pending}")
    status = PRODUCTION_STATUS if production else PREPRODUCTION_STATUS
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "claim_boundary": CLAIM_BOUNDARY,
        "mode": "production" if production else "preproduction",
        "production_training_started": False,
        "matrix": snapshot(matrix_path, "production_matrix"),
        "implementation_files": implementation,
        "implementation_tree_sha256": sha256_json({key: row["sha256"] for key, row in implementation.items()}),
        "formal_artifacts": artifacts,
        "contact_loss_governance": contact_governance,
        "v1_5_immutable": v1_5,
        "runtime_identity_expected": expected_runtime,
        "runtime_identity_observed": runtime,
        "node1_deployment": matrix["node1_deployment"],
        "lanes": matrix["lanes"],
        "production_runs": matrix["production_runs"],
        "promotion_gates": matrix["promotion_gates"],
        "technical_supersession": matrix["technical_supersession"],
        "numerical_stability_amendment": snapshot(
            residue_root / "NUMERICAL_STABILITY_AMENDMENT_V2_3.json",
            "numerical_stability_amendment",
        ),
        "sealed_test32_exclusion": matrix["sealed_test32_exclusion"],
        "pending": pending,
        "post_augmentation_contract": {
            "phase": "post_augmentation_binding",
            "closure_path": str(Path(matrix["node1_deployment"]["remote_root"]) / "status/DEPLOYMENT_INPUT_CLOSURE.json"),
            "required_before_smoke_or_production": True,
            "static_augmented_target_sha256": None,
        },
    }
    return payload


def verify_freeze(
    freeze_path: Path,
    *,
    residue_root: Path,
    matrix_path: Path,
    require_production: bool,
    observed_runtime: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    frozen = load_json(freeze_path, "implementation_freeze")
    require(frozen.get("schema_version") == SCHEMA_VERSION, "freeze_schema_invalid")
    production = frozen.get("mode") == "production"
    if require_production:
        require(production and frozen.get("status") == PRODUCTION_STATUS, "production_freeze_required")
    expected = build_payload(
        residue_root=residue_root,
        matrix_path=matrix_path,
        production=production,
        observed_runtime=observed_runtime,
    )
    require(frozen == expected, "freeze_replay_mismatch")
    return {"status": CHECK_STATUS, "mode": frozen["mode"], "freeze_sha256": sha256_file(freeze_path)}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    value.add_argument("--residue-root", type=Path, default=RESIDUE_ROOT)
    value.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    value.add_argument("--production", action="store_true")
    value.add_argument("--check", type=Path)
    value.add_argument("--require-production", action="store_true")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.check is not None:
        result = verify_freeze(
            args.check,
            residue_root=args.residue_root,
            matrix_path=args.matrix,
            require_production=args.require_production,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    require(not args.output.exists(), f"freeze_output_must_not_exist:{args.output}")
    payload = build_payload(
        residue_root=args.residue_root,
        matrix_path=args.matrix,
        production=args.production,
    )
    atomic_json(args.output, payload)
    print(json.dumps({"status": payload["status"], "output": str(args.output), "sha256": sha256_file(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
