#!/usr/bin/env python3
"""Fail-closed Node1 CUDA/BF16 smoke launcher for the frozen V2.6 integration.

This is a deployment *preflight* surface.  The checked-in authorization
template is deliberately false and no smoke driver is bundled.  Execution is
possible only after a separate, content-addressed driver freeze and an explicit
authorization overlay are created, the live V2.5 DAG has reached its frozen
PASS terminal, and GPUs 1/2/4/5 are idle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "pvrig_v2_6_node1_cuda_smoke_launcher_v1"
CLAIM_BOUNDARY = (
    "Open-development CUDA/BF16 numerical and training-dynamics smoke for a "
    "computational 8X6B/9E6Y Docking-geometry surrogate only; not binding, "
    "affinity, experimental blocking, Docking Gold, sealed V4-F evidence, or "
    "submission truth."
)

FIXED_PYTHON = pathlib.Path("/data1/qlyu/software/envs/pvrig-v6-tc/bin/python")
FIXED_PHYSICAL_GPUS = (1, 2, 4, 5)
FIXED_GPU_MAP = {
    "BE_TRAJECTORY": 1,
    "GRADIENT_ACCUMULATION": 2,
    "F_GRADIENT_CAP": 4,
    "EXACT_MIN_FIREWALL_AUDIT": 5,
}
MIN_FREE_GIB = 100
MAX_GPU_MEMORY_MIB = 512
MAX_GPU_UTILIZATION_PERCENT = 5
FIXED_PRECISION = "bf16"
FIXED_OPTIMIZER_STEPS = 20
FIXED_GRADIENT_ACCUMULATION = 2
FIXED_KAPPA = 0.25
MAX_BE_TRAJECTORY_DELTA = 1e-7
EXACT_MIN_TOLERANCE = 1e-12

EXPECTED_INTEGRATION_FREEZE_SHA256 = (
    "8c6bd627b1f7381c76a97a821f9eafdf3115c1859bc4120890a7239c999e5d76"
)
EXPECTED_INTEGRATION_TRAINER_SHA256 = (
    "8625e7f27091f05dae3ef9cbb52a88efa87acc16daad4494c89752f64a947a02"
)
EXPECTED_RANK_FREEZE_SHA256 = (
    "fe276bd1601c77b07440e6f1960d13a75bf81ee7769a30c8bb0229a0ee3d77ac"
)
EXPECTED_RANK_CORE_SHA256 = (
    "b420766a7769a546418a68367b71742eb3ea7872dd2411a48609139a985ef2ec"
)
EXPECTED_V25_JOB_GRAPH_SHA256 = (
    "ea1c4c1eedf189d9542e3e73b0c0368777b4073468fd4e39535b28fd7fa24185"
)
EXPECTED_INTEGRATION_STATUS = "FROZEN_IMPLEMENTATION_TESTED_NONLAUNCHING_CPU_ONLY"
EXPECTED_RANK_STATUS = "FROZEN_IMPLEMENTATION_TESTED_AUDITED_NONLAUNCHING"
EXPECTED_DRIVER_FREEZE_STATUS = "FROZEN_NODE1_CUDA_SMOKE_DRIVER_TESTED_NONLAUNCHING"
EXPECTED_AUTHORIZATION_STATUS = "EXPLICITLY_AUTHORIZED_NODE1_CUDA_SMOKE"

FORBIDDEN_PATH_TOKENS = (
    "v4_f",
    "test32",
    "prospective_computational_test",
)


class PreflightError(RuntimeError):
    """A fail-closed deployment or validation error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PreflightError(message)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_regular_json(path: pathlib.Path, label: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"{label}_missing_or_symlink:{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PreflightError(f"{label}_invalid_json:{path}:{error}") from error
    require(isinstance(payload, dict), f"{label}_not_object:{path}")
    return payload


def validate_package_manifest(path: pathlib.Path) -> tuple[dict[str, Any], str]:
    """Validate the immutable preflight package before reading authorization."""
    manifest = load_regular_json(path, "package_manifest")
    require(manifest.get("status") == "PASS_IMMUTABLE_NONLAUNCHING_PREFLIGHT_BUILT", "package_status")
    require(manifest.get("execution_authorized") is False, "package_must_be_nonlaunching")
    require(manifest.get("integration_freeze_sha256") == EXPECTED_INTEGRATION_FREEZE_SHA256, "package_integration_binding")
    require(manifest.get("rank_freeze_sha256") == EXPECTED_RANK_FREEZE_SHA256, "package_rank_binding")
    require(manifest.get("rank_core_sha256") == EXPECTED_RANK_CORE_SHA256, "package_rank_core_binding")
    require(manifest.get("v4_f_test32_access_count") == 0, "package_v4f_access")
    package_root = path.parent.resolve()
    files = manifest.get("files")
    require(isinstance(files, dict) and files, "package_file_manifest_empty")
    for relative, expected in files.items():
        require(isinstance(relative, str) and relative and not relative.startswith("/"), "package_relative_path")
        require(".." not in pathlib.PurePosixPath(relative).parts, "package_parent_escape")
        require(_valid_sha256(expected), f"package_file_sha256_invalid:{relative}")
        artifact = package_root / relative
        require(artifact.is_file() and not artifact.is_symlink(), f"package_file_missing_or_symlink:{relative}")
        require(sha256_file(artifact) == expected, f"package_file_sha256_mismatch:{relative}")
    return manifest, sha256_file(path)


def reject_sealed_path(path: pathlib.Path, label: str) -> None:
    lowered = str(path).lower().replace("-", "_")
    require(
        not any(token in lowered for token in FORBIDDEN_PATH_TOKENS),
        f"sealed_or_test32_path_forbidden:{label}:{path}",
    )


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def validate_source_freezes(
    integration_freeze_path: pathlib.Path,
    rank_freeze_path: pathlib.Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind the immutable CPU integration and exact-min rank V1.1 freezes."""
    reject_sealed_path(integration_freeze_path, "integration_freeze")
    reject_sealed_path(rank_freeze_path, "rank_freeze")
    require(
        integration_freeze_path.is_file() and not integration_freeze_path.is_symlink(),
        "integration_freeze_missing_or_symlink",
    )
    require(
        rank_freeze_path.is_file() and not rank_freeze_path.is_symlink(),
        "rank_freeze_missing_or_symlink",
    )
    require(
        sha256_file(integration_freeze_path) == EXPECTED_INTEGRATION_FREEZE_SHA256,
        "integration_freeze_sha256_mismatch",
    )
    require(
        sha256_file(rank_freeze_path) == EXPECTED_RANK_FREEZE_SHA256,
        "rank_freeze_sha256_mismatch",
    )
    integration = load_regular_json(integration_freeze_path, "integration_freeze")
    rank = load_regular_json(rank_freeze_path, "rank_freeze")
    require(integration.get("status") == EXPECTED_INTEGRATION_STATUS, "integration_freeze_status")
    require(rank.get("status") == EXPECTED_RANK_STATUS, "rank_freeze_status")
    require(
        integration.get("files", {}).get("trainer/real1507_role_isolated_trainer_v1.py")
        == EXPECTED_INTEGRATION_TRAINER_SHA256,
        "integration_trainer_binding_mismatch",
    )
    require(
        integration.get("bound_dependencies", {}).get("rank_calibration_v1_1_core_sha256")
        == EXPECTED_RANK_CORE_SHA256,
        "integration_rank_core_binding_mismatch",
    )
    require(
        rank.get("files", {}).get("rank_calibration_core_v1_1.py")
        == EXPECTED_RANK_CORE_SHA256,
        "rank_core_binding_mismatch",
    )
    require(integration.get("data_access", {}).get("v4_f_test32_accessed") == 0, "integration_v4f_access")
    require(rank.get("data_access", {}).get("v4_f_or_test32_results_accessed") == 0, "rank_v4f_access")
    return integration, rank


def validate_driver_freeze(
    driver_freeze_path: pathlib.Path,
    *,
    expected_driver_freeze_sha256: str,
) -> tuple[dict[str, Any], pathlib.Path, str]:
    """Validate the later, separately frozen Node1 CUDA smoke driver."""
    reject_sealed_path(driver_freeze_path, "smoke_driver_freeze")
    require(_valid_sha256(expected_driver_freeze_sha256), "driver_freeze_expected_sha256_invalid")
    require(
        driver_freeze_path.is_file() and not driver_freeze_path.is_symlink(),
        "driver_freeze_missing_or_symlink",
    )
    require(
        sha256_file(driver_freeze_path) == expected_driver_freeze_sha256,
        "driver_freeze_sha256_mismatch",
    )
    freeze = load_regular_json(driver_freeze_path, "smoke_driver_freeze")
    require(freeze.get("status") == EXPECTED_DRIVER_FREEZE_STATUS, "driver_freeze_status")
    require(freeze.get("execution_authorized") is False, "driver_freeze_must_be_nonlaunching")
    require(freeze.get("v4_f_test32_access_count") == 0, "driver_freeze_v4f_access")
    require(freeze.get("integration_freeze_sha256") == EXPECTED_INTEGRATION_FREEZE_SHA256, "driver_integration_binding")
    require(freeze.get("rank_freeze_sha256") == EXPECTED_RANK_FREEZE_SHA256, "driver_rank_freeze_binding")
    require(freeze.get("rank_core_sha256") == EXPECTED_RANK_CORE_SHA256, "driver_rank_core_binding")
    contract = freeze.get("smoke_contract", {})
    require(contract.get("precision") == FIXED_PRECISION, "driver_precision_contract")
    require(contract.get("optimizer_steps") == FIXED_OPTIMIZER_STEPS, "driver_step_contract")
    require(contract.get("gradient_accumulation") == FIXED_GRADIENT_ACCUMULATION, "driver_accumulation_contract")
    require(math.isclose(float(contract.get("kappa", math.nan)), FIXED_KAPPA, rel_tol=0.0, abs_tol=0.0), "driver_kappa_contract")
    require(contract.get("physical_gpu_map") == FIXED_GPU_MAP, "driver_gpu_map_contract")
    driver_record = freeze.get("driver", {})
    driver_path = pathlib.Path(str(driver_record.get("path", "")))
    driver_sha256 = driver_record.get("sha256")
    reject_sealed_path(driver_path, "smoke_driver")
    require(driver_path.is_absolute(), "driver_path_not_absolute")
    require(_valid_sha256(driver_sha256), "driver_sha256_invalid")
    require(driver_path.is_file() and not driver_path.is_symlink(), "driver_missing_or_symlink")
    require(sha256_file(driver_path) == driver_sha256, "driver_sha256_mismatch")
    return freeze, driver_path, str(driver_sha256)


def validate_authorization(
    authorization_path: pathlib.Path,
    *,
    package_manifest_sha256: str,
    driver_freeze_sha256: str,
) -> dict[str, Any]:
    reject_sealed_path(authorization_path, "authorization")
    authorization = load_regular_json(authorization_path, "authorization")
    require(authorization.get("status") == EXPECTED_AUTHORIZATION_STATUS, "authorization_status")
    require(authorization.get("execution_authorized") is True, "authorization_false")
    require(authorization.get("package_manifest_sha256") == package_manifest_sha256, "authorization_package_binding")
    require(authorization.get("integration_freeze_sha256") == EXPECTED_INTEGRATION_FREEZE_SHA256, "authorization_integration_binding")
    require(authorization.get("rank_freeze_sha256") == EXPECTED_RANK_FREEZE_SHA256, "authorization_rank_binding")
    require(authorization.get("rank_core_sha256") == EXPECTED_RANK_CORE_SHA256, "authorization_rank_core_binding")
    require(authorization.get("driver_freeze_sha256") == driver_freeze_sha256, "authorization_driver_binding")
    require(authorization.get("v4_f_test32_access_count") == 0, "authorization_v4f_access")
    return authorization


def validate_v25_terminal(terminal_path: pathlib.Path) -> dict[str, Any]:
    terminal = load_regular_json(terminal_path, "v25_terminal")
    require(terminal.get("status") == "PASS", "v25_terminal_not_pass")
    require(terminal.get("returncode") == 0, "v25_terminal_returncode")
    require(terminal.get("completed") == 301, "v25_terminal_job_closure")
    require(terminal.get("job_graph_sha256") == EXPECTED_V25_JOB_GRAPH_SHA256, "v25_terminal_graph_binding")
    require(terminal.get("v4_f_test32_access_count") == 0, "v25_terminal_v4f_access")
    return terminal


def validate_environment_probe(probe: Mapping[str, Any]) -> None:
    require(probe.get("python_path") == str(FIXED_PYTHON), "python_path_mismatch")
    require(probe.get("cuda_available") is True, "cuda_unavailable")
    require(probe.get("bf16_supported") is True, "bf16_unsupported")
    require(str(probe.get("torch", "")).endswith("+cu124"), "torch_cuda_build_mismatch")
    require(str(probe.get("cuda_version", "")) == "12.4", "cuda_version_mismatch")


def probe_environment() -> dict[str, Any]:
    """Read the fixed Node1 Python/CUDA environment at launch time."""
    require(FIXED_PYTHON.is_file() and not FIXED_PYTHON.is_symlink(), "fixed_python_missing_or_symlink")
    program = (
        "import json,torch;"
        "print(json.dumps({'python_path':__import__('sys').executable,"
        "'torch':torch.__version__,'cuda_available':torch.cuda.is_available(),"
        "'cuda_version':torch.version.cuda,'bf16_supported':"
        "(torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False)}))"
    )
    completed = subprocess.run(
        [str(FIXED_PYTHON), "-c", program],
        check=False,
        capture_output=True,
        text=True,
    )
    require(completed.returncode == 0, f"environment_probe_failed:{completed.returncode}")
    try:
        probe = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise PreflightError(f"environment_probe_invalid_json:{error}") from error
    require(isinstance(probe, dict), "environment_probe_not_object")
    validate_environment_probe(probe)
    return probe


def validate_resource_probe(probe: Mapping[str, Any]) -> None:
    require(float(probe.get("data1_free_gib", -1.0)) >= MIN_FREE_GIB, "data1_free_space_below_gate")
    gpu_rows = probe.get("gpus")
    require(isinstance(gpu_rows, list), "gpu_probe_not_list")
    by_index = {int(row["index"]): row for row in gpu_rows}
    require(set(by_index) == set(FIXED_PHYSICAL_GPUS), "gpu_probe_index_set")
    for index in FIXED_PHYSICAL_GPUS:
        row = by_index[index]
        require(row.get("name") == "NVIDIA GeForce RTX 4090", f"gpu_model_mismatch:{index}")
        require(float(row.get("memory_used_mib", math.inf)) <= MAX_GPU_MEMORY_MIB, f"gpu_memory_busy:{index}")
        require(float(row.get("utilization_percent", math.inf)) <= MAX_GPU_UTILIZATION_PERCENT, f"gpu_utilization_busy:{index}")
        require(int(row.get("compute_process_count", -1)) == 0, f"gpu_compute_process_busy:{index}")


def probe_resources() -> dict[str, Any]:
    """Read /data1 and the exact physical GPU allowlist at launch time."""
    usage = shutil.disk_usage("/data1")
    gpu_query = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,uuid,memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    require(gpu_query.returncode == 0, f"gpu_probe_failed:{gpu_query.returncode}")
    process_query = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    require(process_query.returncode == 0, f"gpu_process_probe_failed:{process_query.returncode}")
    process_counts: dict[str, int] = {}
    for line in process_query.stdout.splitlines():
        if not line.strip():
            continue
        uuid, _pid = [value.strip() for value in line.split(",", 1)]
        process_counts[uuid] = process_counts.get(uuid, 0) + 1
    rows: list[dict[str, Any]] = []
    for line in gpu_query.stdout.splitlines():
        if not line.strip():
            continue
        fields = [value.strip() for value in line.split(",")]
        require(len(fields) == 5, "gpu_probe_field_count")
        index = int(fields[0])
        if index not in FIXED_PHYSICAL_GPUS:
            continue
        rows.append({
            "index": index,
            "name": fields[1],
            "uuid": fields[2],
            "memory_used_mib": float(fields[3]),
            "utilization_percent": float(fields[4]),
            "compute_process_count": process_counts.get(fields[2], 0),
        })
    probe = {
        "data1_free_gib": usage.free / (1024 ** 3),
        "gpus": rows,
    }
    validate_resource_probe(probe)
    return probe


def active_v25_processes() -> list[str]:
    """Return live V2.5 formal scheduler/workers without modifying them."""
    completed = subprocess.run(
        ["pgrep", "-af", "pvrig_v2_5_ortho_formal_nested|run_formal_job_graph_v1.py"],
        check=False,
        capture_output=True,
        text=True,
    )
    require(completed.returncode in {0, 1}, f"v25_process_probe_failed:{completed.returncode}")
    return [line for line in completed.stdout.splitlines() if line.strip()]


def validate_smoke_result(result_path: pathlib.Path) -> dict[str, Any]:
    result = load_regular_json(result_path, "smoke_result")
    require(result.get("schema_version") == "pvrig_v2_6_node1_cuda_smoke_result_v1", "result_schema")
    require(result.get("status") == "PASS", "result_status")
    require(result.get("precision") == FIXED_PRECISION, "result_precision")
    require(result.get("physical_gpu_map") == FIXED_GPU_MAP, "result_gpu_map")
    require(result.get("integration_freeze_sha256") == EXPECTED_INTEGRATION_FREEZE_SHA256, "result_integration_binding")
    require(result.get("rank_freeze_sha256") == EXPECTED_RANK_FREEZE_SHA256, "result_rank_binding")
    require(result.get("rank_core_sha256") == EXPECTED_RANK_CORE_SHA256, "result_rank_core_binding")

    trajectory = result.get("be_trajectory", {})
    require(trajectory.get("optimizer_steps") == FIXED_OPTIMIZER_STEPS, "be_step_count")
    require(float(trajectory.get("maximum_scalar_shared_parameter_delta", math.inf)) <= MAX_BE_TRAJECTORY_DELTA, "be_trajectory_delta")
    require(trajectory.get("main_rng_restored_every_step") is True, "be_rng_not_restored")
    require(trajectory.get("finite_state_every_step") is True, "be_nonfinite_state")

    accumulation = result.get("gradient_accumulation", {})
    require(accumulation.get("microbatches_per_optimizer_step") == FIXED_GRADIENT_ACCUMULATION, "accumulation_factor")
    require(accumulation.get("optimizer_steps") == FIXED_OPTIMIZER_STEPS, "accumulation_step_count")
    require(accumulation.get("microbatches_consumed") == 2 * FIXED_OPTIMIZER_STEPS, "accumulation_microbatch_closure")
    require(accumulation.get("reduction") == "MEAN_ACTUAL_WINDOW_BEFORE_ONE_ROLE_ISOLATED_STEP", "accumulation_reduction")
    require(accumulation.get("global_all_parameter_clip_used") is False, "global_clip_used")

    shared = result.get("f_shared_gated", {})
    require(shared.get("optimizer_steps") == FIXED_OPTIMIZER_STEPS, "f_step_count")
    require(math.isclose(float(shared.get("kappa", math.nan)), FIXED_KAPPA, rel_tol=0.0, abs_tol=0.0), "f_kappa")
    require(shared.get("telemetry_event_count") == FIXED_OPTIMIZER_STEPS, "f_telemetry_count")
    require(shared.get("gradient_budget_violation_count") == 0, "f_gradient_budget_violation")
    require(shared.get("main_rng_restored_every_step") is True, "f_rng_not_restored")
    require(shared.get("finite_state_every_step") is True, "f_nonfinite_state")

    exact_min = result.get("exact_min", {})
    require(exact_min.get("independent_rdual_output_trained") is False, "independent_rdual_trained")
    require(float(exact_min.get("maximum_abs_error", math.inf)) <= EXACT_MIN_TOLERANCE, "exact_min_error")
    require(exact_min.get("inference_semantics") == "exact_min(R_8X6B,R_9E6Y)", "exact_min_semantics")

    firewall = result.get("firewall", {})
    require(firewall.get("v4_f_test32_access_count") == 0, "result_v4f_access")
    require(firewall.get("score_partition_truth_access_count") == 0, "score_truth_access")
    require(firewall.get("outer_metrics_access_count") == 0, "outer_metrics_access")
    require(firewall.get("candidate_docking_pose_input_count") == 0, "candidate_pose_input_access")
    return result


def build_driver_command(
    *,
    driver_path: pathlib.Path,
    runtime_root: pathlib.Path,
    integration_freeze_path: pathlib.Path,
    rank_freeze_path: pathlib.Path,
) -> list[str]:
    return [
        str(FIXED_PYTHON),
        str(driver_path),
        "--runtime-root", str(runtime_root),
        "--integration-freeze", str(integration_freeze_path),
        "--expected-integration-freeze-sha256", EXPECTED_INTEGRATION_FREEZE_SHA256,
        "--rank-freeze", str(rank_freeze_path),
        "--expected-rank-freeze-sha256", EXPECTED_RANK_FREEZE_SHA256,
        "--expected-rank-core-sha256", EXPECTED_RANK_CORE_SHA256,
        "--physical-gpus", ",".join(str(value) for value in FIXED_PHYSICAL_GPUS),
        "--precision", FIXED_PRECISION,
        "--optimizer-steps", str(FIXED_OPTIMIZER_STEPS),
        "--gradient-accumulation", str(FIXED_GRADIENT_ACCUMULATION),
        "--kappa", str(FIXED_KAPPA),
        "--result", str(runtime_root / "SMOKE_RESULT.json"),
    ]


def execute(
    *,
    package_manifest_path: pathlib.Path,
    authorization_path: pathlib.Path,
    integration_freeze_path: pathlib.Path,
    rank_freeze_path: pathlib.Path,
    driver_freeze_path: pathlib.Path,
    expected_driver_freeze_sha256: str,
    v25_terminal_path: pathlib.Path,
    runtime_root: pathlib.Path,
) -> dict[str, Any]:
    """Execute only after every immutable and live precondition passes."""
    _package_manifest, package_manifest_sha = validate_package_manifest(package_manifest_path)
    validate_source_freezes(integration_freeze_path, rank_freeze_path)
    _driver_freeze, driver_path, driver_sha = validate_driver_freeze(
        driver_freeze_path,
        expected_driver_freeze_sha256=expected_driver_freeze_sha256,
    )
    validate_authorization(
        authorization_path,
        package_manifest_sha256=package_manifest_sha,
        driver_freeze_sha256=expected_driver_freeze_sha256,
    )
    validate_v25_terminal(v25_terminal_path)
    require(not active_v25_processes(), "v25_processes_still_active")
    environment_probe = probe_environment()
    resource_probe = probe_resources()
    reject_sealed_path(runtime_root, "runtime_root")
    require(runtime_root.is_absolute() and str(runtime_root).startswith("/data1/qlyu/projects/"), "runtime_root_not_data1")
    require(not os.path.lexists(runtime_root), "runtime_root_exists")
    runtime_root.mkdir(parents=True, mode=0o750)
    command = build_driver_command(
        driver_path=driver_path,
        runtime_root=runtime_root,
        integration_freeze_path=integration_freeze_path,
        rank_freeze_path=rank_freeze_path,
    )
    environment = os.environ.copy()
    environment.update({
        "CUDA_VISIBLE_DEVICES": ",".join(str(value) for value in FIXED_PHYSICAL_GPUS),
        "OMP_NUM_THREADS": "4",
        "MKL_NUM_THREADS": "4",
        "OPENBLAS_NUM_THREADS": "4",
    })
    completed = subprocess.run(command, env=environment, check=False)
    require(completed.returncode == 0, f"smoke_driver_failed:{completed.returncode}")
    result_path = runtime_root / "SMOKE_RESULT.json"
    result = validate_smoke_result(result_path)
    terminal = {
        "schema_version": f"{SCHEMA_VERSION}_terminal_v1",
        "status": "PASS",
        "returncode": 0,
        "claim_boundary": CLAIM_BOUNDARY,
        "command": command,
        "package_manifest_sha256": package_manifest_sha,
        "authorization_sha256": sha256_file(authorization_path),
        "integration_freeze_sha256": EXPECTED_INTEGRATION_FREEZE_SHA256,
        "rank_freeze_sha256": EXPECTED_RANK_FREEZE_SHA256,
        "rank_core_sha256": EXPECTED_RANK_CORE_SHA256,
        "driver_freeze_sha256": expected_driver_freeze_sha256,
        "driver_sha256": driver_sha,
        "environment_probe": environment_probe,
        "resource_probe": resource_probe,
        "smoke_result_sha256": sha256_file(result_path),
        "v4_f_test32_access_count": result["firewall"]["v4_f_test32_access_count"],
    }
    terminal_path = runtime_root / "TERMINAL.json"
    temporary = runtime_root / f".TERMINAL.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(terminal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, terminal_path)
    return terminal


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--package-manifest", type=pathlib.Path, required=True)
    parser.add_argument("--authorization", type=pathlib.Path, required=True)
    parser.add_argument("--integration-freeze", type=pathlib.Path, required=True)
    parser.add_argument("--rank-freeze", type=pathlib.Path, required=True)
    parser.add_argument("--driver-freeze", type=pathlib.Path, required=True)
    parser.add_argument("--expected-driver-freeze-sha256", required=True)
    parser.add_argument("--v25-terminal", type=pathlib.Path, required=True)
    parser.add_argument("--runtime-root", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    require(args.execute, "explicit_execute_flag_required")
    terminal = execute(
        package_manifest_path=args.package_manifest,
        authorization_path=args.authorization,
        integration_freeze_path=args.integration_freeze,
        rank_freeze_path=args.rank_freeze,
        driver_freeze_path=args.driver_freeze,
        expected_driver_freeze_sha256=args.expected_driver_freeze_sha256,
        v25_terminal_path=args.v25_terminal,
        runtime_root=args.runtime_root,
    )
    print(json.dumps(terminal, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreflightError as error:
        print(f"FAIL_CLOSED:{error}", file=sys.stderr)
        raise SystemExit(2)
