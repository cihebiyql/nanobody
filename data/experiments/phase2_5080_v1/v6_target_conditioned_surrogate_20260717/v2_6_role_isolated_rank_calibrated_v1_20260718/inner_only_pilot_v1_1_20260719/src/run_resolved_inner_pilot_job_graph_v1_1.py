#!/usr/bin/env python3
"""Fail-closed scheduler for a future fully resolved V2.6 inner pilot graph.

The current package contains an unresolved template and this scheduler will
reject it.  Integration V1.2 is already hash-bound.  A future
content-addressed package must supply a real CUDA driver, PASS smoke receipt,
exact authorization overlay and executable commands before runtime creation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


PHYSICAL_TO_LOGICAL = {1: "cuda:0", 2: "cuda:1", 4: "cuda:2", 5: "cuda:3"}
INTEGRATION_V12_FREEZE_SHA256 = "538abbcc495cd357b74880e6cef02626c7c969929ca891d566f99ab3e694b681"
INTEGRATION_V12_TRAINER_SHA256 = "036fb5f1d8b443bc3fd514ae6fe43970af42b6d078c378233f2825550b61d4e4"
TRAINING_SPLIT_SHA256 = "f09070d3f193c152a07d0a57da4f5ecc602a4bb3a7a609a941af8176242c77dd"
LABEL_SHA256 = "044df3c1d4268421c3058cd28c45785ae98b3a1693b12248fdc8d35a2609de3a"


class ContractError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_regular_json(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"json_not_regular:{path}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"json_not_object:{path}")
    return value


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def validate_smoke(receipt: dict[str, Any]) -> None:
    require(str(receipt.get("status", "")).startswith("PASS"), "cuda_smoke_not_pass")
    require(receipt.get("bf16_cuda") is True, "cuda_smoke_not_bf16")
    require(float(receipt.get("be_max_scalar_shared_parameter_delta", 1.0)) <= 1e-7, "cuda_smoke_be_delta")
    require(receipt.get("gradient_accumulation_closure") is True, "cuda_smoke_accumulation")
    require(receipt.get("f_shared_gradient_budget_kappa") == 0.25, "cuda_smoke_kappa")
    require(receipt.get("f_shared_gradient_budget_violation_count") == 0, "cuda_smoke_cap_violation")
    require(receipt.get("exact_min_violation_count") == 0, "cuda_smoke_exact_min")
    require(receipt.get("finite_state") is True, "cuda_smoke_nonfinite")
    require(receipt.get("contact_rng_restoration") is True, "cuda_smoke_rng")
    for field in ("outer_test_truth_access_count", "outer_metrics_access_count", "v4_f_test32_access_count"):
        require(receipt.get(field) == 0, f"cuda_smoke_firewall:{field}")


def validate_graph(graph: dict[str, Any], overlay: dict[str, Any]) -> dict[str, dict[str, Any]]:
    require(graph.get("status") == "FROZEN_RESOLVED_PENDING_AUTHORIZATION", "graph_not_resolved")
    require(graph.get("execution_authorized") is False, "graph_must_remain_nonauthorized")
    require(graph.get("launchable") is True, "graph_not_launchable")
    require(overlay.get("status") == "EXPLICITLY_AUTHORIZED_V1_1_PILOT_WITH_INTEGRATION_V1_2", "overlay_status")
    require(overlay.get("execution_authorized") is True, "overlay_not_authorized")
    require(overlay.get("integration_schema_version", "").endswith("_v1_2"), "integration_not_v1_2")
    require(overlay.get("integration_v1_2_freeze_sha256") == INTEGRATION_V12_FREEZE_SHA256, "integration_v1_2_freeze_overlay")
    require(overlay.get("integration_v1_2_trainer_sha256") == INTEGRATION_V12_TRAINER_SHA256, "integration_v1_2_trainer_overlay")
    require(overlay.get("integration_v1_forbidden") is True, "integration_v1_not_forbidden")
    require(overlay.get("integration_v1_1_forbidden") is True, "integration_v1_1_not_forbidden")
    require(overlay.get("outer0_inner0_training_partition_sha256") == TRAINING_SPLIT_SHA256, "training_partition_sha_missing")
    require(overlay.get("outer0_inner0_rank_label_sha256") == LABEL_SHA256, "rank_label_sha_missing")
    for field in ("outer0_inner0_training_partition_sha256", "outer0_inner0_rank_label_sha256"):
        value = str(overlay[field])
        require(len(value) == 64 and all(character in "0123456789abcdef" for character in value), f"invalid_sha256:{field}")
    bound_files = overlay.get("bound_regular_files")
    require(isinstance(bound_files, list), "bound_regular_files_missing")
    logical = {str(item.get("logical_name")) for item in bound_files if isinstance(item, dict)}
    require(
        {"cuda_driver_v1_2", "cuda_driver_v1_2_freeze"} <= logical,
        "future_bound_file_roles_missing",
    )
    require(not ({"integration_v1", "integration_v1_1"} & logical), "superseded_integration_bound_forbidden")
    integration = graph.get("integration_v1_2_binding", {})
    require(integration.get("freeze_sha256") == INTEGRATION_V12_FREEZE_SHA256, "graph_integration_v1_2_freeze")
    require(integration.get("trainer_sha256") == INTEGRATION_V12_TRAINER_SHA256, "graph_integration_v1_2_trainer")
    require(integration.get("outer0_inner0_training_split_sha256") == TRAINING_SPLIT_SHA256, "graph_training_split")
    require(integration.get("outer0_inner0_label_sha256") == LABEL_SHA256, "graph_label")
    resources = graph.get("resources", {})
    require(resources.get("physical_gpu_allowlist") == [1, 2, 4, 5], "gpu_allowlist")
    require(resources.get("cuda_visible_devices") == "1,2,4,5", "cuda_visible_devices")
    require(resources.get("physical_to_logical_cuda_map") == {str(k): v for k, v in PHYSICAL_TO_LOGICAL.items()}, "gpu_map")
    jobs = graph.get("jobs")
    require(isinstance(jobs, list) and len(jobs) == 9, "job_count")
    result = {str(job["job_id"]): job for job in jobs}
    require(len(result) == 9, "job_id_duplicate")
    gpu_jobs = [job for job in jobs if job.get("kind") == "GPU_INNER_PILOT"]
    cpu_jobs = [job for job in jobs if job.get("kind") == "CPU_INNER_METRICS_COLLECT"]
    require(len(gpu_jobs) == 8 and len(cpu_jobs) == 1, "job_kind_count")
    for job in gpu_jobs:
        physical = int(job["physical_gpu"])
        require(job.get("logical_device") == PHYSICAL_TO_LOGICAL[physical], "job_gpu_map")
        require(isinstance(job.get("command"), list) and job["command"], "gpu_command_unresolved")
        command_text = " ".join(map(str, job["command"])).lower()
        require(job["logical_device"] in job["command"], "logical_device_not_in_command")
        require("outer_0_inner_0" in command_text, "fixed_split_not_in_command")
        require("v4_f" not in command_text and "test32" not in command_text, "sealed_command")
    require(isinstance(cpu_jobs[0].get("command"), list) and cpu_jobs[0]["command"], "collector_command_unresolved")
    require(set(cpu_jobs[0]["dependencies"]) == {job["job_id"] for job in gpu_jobs}, "collector_dependency_closure")
    for field in ("outer_test_truth_access_count", "outer_metrics_access_count", "v4_f_test32_access_count"):
        require(graph.get(field) == 0 and overlay.get(field) == 0, f"graph_overlay_firewall:{field}")
    return result


def validate_bound_regular_files(overlay: dict[str, Any]) -> None:
    for item in overlay["bound_regular_files"]:
        require(isinstance(item, dict), "bound_file_entry")
        path = Path(str(item.get("path", "")))
        expected = str(item.get("sha256", ""))
        require(path.is_absolute(), f"bound_file_not_absolute:{path}")
        require(path.is_file() and not path.is_symlink(), f"bound_file_not_regular:{path}")
        require(len(expected) == 64 and sha256_file(path) == expected, f"bound_file_hash:{path}")


def validate_external_inputs(path: Path) -> None:
    value = load_regular_json(path)
    require(value.get("status") == "FROZEN_OUTER0_INNER0_ONLY", "external_inputs_status")
    require(value.get("outer_test_files_bound") == 0 and value.get("v4_f_test32_access_count") == 0, "external_inputs_firewall")
    files = value.get("files")
    require(isinstance(files, list) and len(files) == 11, "external_inputs_count")
    for item in files:
        source = Path(str(item["path"]))
        require(source.is_file() and not source.is_symlink(), f"external_input_not_regular:{source}")
        require(sha256_file(source) == item["sha256"], f"external_input_hash:{source}")


def validate_package_manifest(path: Path) -> None:
    manifest = load_regular_json(path)
    require(manifest.get("integration_v1_2_bound") is True, "package_integration_v1_2_not_bound")
    require(manifest.get("integration_v1_forbidden") is True, "package_integration_v1_not_forbidden")
    require(manifest.get("integration_v1_1_forbidden") is True, "package_integration_v1_1_not_forbidden")
    require(manifest.get("launch_authorized") is False, "package_manifest_mutated_authorized")
    bundle = path.parent / "node1_bundle"
    for relative, expected in manifest.get("files", {}).items():
        source = bundle / relative
        require(source.is_file() and not source.is_symlink(), f"package_file_not_regular:{relative}")
        require(sha256_file(source) == expected, f"package_file_hash:{relative}")
    known = manifest.get("known_dependency_hashes", {})
    require(known.get("v2_6_integration_v1_2_freeze_sha256") == INTEGRATION_V12_FREEZE_SHA256, "package_integration_freeze")
    require(known.get("v2_6_integration_v1_2_trainer_sha256") == INTEGRATION_V12_TRAINER_SHA256, "package_integration_trainer")
    require(known.get("v2_6_outer0_inner0_training_split_sha256") == TRAINING_SPLIT_SHA256, "package_training_split")
    require(known.get("v2_6_outer0_inner0_label_sha256") == LABEL_SHA256, "package_label")


def idle_gpu_gate() -> None:
    query = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,name,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    observed = {}
    for line in query:
        index, name, memory, utilization = [value.strip() for value in line.split(",", 3)]
        if int(index) in PHYSICAL_TO_LOGICAL:
            observed[int(index)] = (name, int(memory), int(utilization))
    require(set(observed) == set(PHYSICAL_TO_LOGICAL), "gpu_inventory")
    for index, (name, memory, utilization) in observed.items():
        require(name == "NVIDIA GeForce RTX 4090", f"gpu_name:{index}")
        require(memory <= 512 and utilization <= 5, f"gpu_busy:{index}:{memory}:{utilization}")
    gpu_uuid_lines = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    selected_uuids = {
        uuid.strip()
        for line in gpu_uuid_lines
        for index, uuid in [line.split(",", 1)]
        if int(index.strip()) in PHYSICAL_TO_LOGICAL
    }
    processes = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=gpu_uuid,pid", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip().splitlines()
    selected_processes = [line for line in processes if line.split(",", 1)[0].strip() in selected_uuids]
    require(not selected_processes, "selected_gpu_compute_processes_present")
    available = os.statvfs("/data1")
    gib = available.f_bavail * available.f_frsize / (1024**3)
    require(gib >= 100.0, f"data1_free_below_100GiB:{gib:.3f}")


def valid_result(job: dict[str, Any]) -> bool:
    path = Path(job["expected_result"])
    if not path.is_file() or path.is_symlink():
        return False
    try:
        result = json.loads(path.read_text())
    except Exception:
        return False
    if not str(result.get("status", "")).startswith("PASS") or result.get("job_id") != job["job_id"]:
        return False
    if any(result.get(field) != 0 for field in ("outer_test_truth_access_count", "outer_metrics_access_count", "v4_f_test32_access_count")):
        return False
    if job.get("kind") == "GPU_INNER_PILOT":
        if result.get("exact_min_violation_count") != 0:
            return False
        artifacts = result.get("artifacts")
        if not isinstance(artifacts, dict):
            return False
        required = ("training_receipt", "step_evidence", "checkpoint", "predictions")
        if any(not isinstance(artifacts.get(key), dict) for key in required):
            return False
        for key in required:
            item = artifacts[key]
            artifact = Path(job["output_dir"]) / str(item.get("path", ""))
            if not artifact.is_file() or artifact.is_symlink() or sha256_file(artifact) != item.get("sha256"):
                return False
        step_item = artifacts["step_evidence"]
        step_path = Path(job["output_dir"]) / str(step_item["path"])
        lines = [line for line in step_path.read_text().splitlines() if line.strip()]
        if len(lines) != int(step_item.get("rows", -1)) or len(lines) != int(result.get("optimizer_steps", -2)):
            return False
        try:
            events = [json.loads(line) for line in lines]
        except Exception:
            return False
        if any(event.get("finite_state") is not True or event.get("v4_f_test32_access_count") != 0 for event in events):
            return False
        training_path = Path(job["output_dir"]) / str(artifacts["training_receipt"]["path"])
        try:
            training = json.loads(training_path.read_text())
        except Exception:
            return False
        if any(training.get(field) != 0 for field in ("outer_test_truth_access_count", "outer_metrics_access_count", "v4_f_test32_access_count")):
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-graph", type=Path, required=True)
    parser.add_argument("--expected-job-graph-sha256", required=True)
    parser.add_argument("--authorization-overlay", type=Path, required=True)
    parser.add_argument("--expected-authorization-overlay-sha256", required=True)
    parser.add_argument("--cuda-smoke-receipt", type=Path, required=True)
    parser.add_argument("--expected-cuda-smoke-receipt-sha256", required=True)
    parser.add_argument("--package-manifest", type=Path, required=True)
    parser.add_argument("--expected-package-manifest-sha256", required=True)
    parser.add_argument("--external-input-bindings", type=Path, required=True)
    parser.add_argument("--expected-external-input-bindings-sha256", required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    require(sha256_file(args.job_graph) == args.expected_job_graph_sha256, "job_graph_hash")
    require(sha256_file(args.authorization_overlay) == args.expected_authorization_overlay_sha256, "overlay_hash")
    require(sha256_file(args.cuda_smoke_receipt) == args.expected_cuda_smoke_receipt_sha256, "smoke_hash")
    require(sha256_file(args.package_manifest) == args.expected_package_manifest_sha256, "package_manifest_hash")
    require(sha256_file(args.external_input_bindings) == args.expected_external_input_bindings_sha256, "external_input_bindings_hash")
    graph = load_regular_json(args.job_graph)
    overlay = load_regular_json(args.authorization_overlay)
    smoke = load_regular_json(args.cuda_smoke_receipt)
    jobs = validate_graph(graph, overlay)
    validate_smoke(smoke)
    validate_bound_regular_files(overlay)
    validate_external_inputs(args.external_input_bindings)
    validate_package_manifest(args.package_manifest)
    require(overlay.get("job_graph_sha256") == args.expected_job_graph_sha256, "overlay_graph_binding")
    require(overlay.get("cuda_smoke_receipt_sha256") == args.expected_cuda_smoke_receipt_sha256, "overlay_smoke_binding")
    require(overlay.get("package_manifest_sha256") == args.expected_package_manifest_sha256, "overlay_package_binding")
    require(overlay.get("external_input_bindings_sha256") == args.expected_external_input_bindings_sha256, "overlay_external_binding")
    require(not args.runtime_root.exists(), "runtime_root_exists")
    idle_gpu_gate()
    args.runtime_root.mkdir(parents=True)
    logs = args.runtime_root / "logs"
    logs.mkdir()
    completed: set[str] = set()
    pending = set(jobs)
    running: dict[str, tuple[subprocess.Popen[Any], Any, int | None]] = {}
    environment_base = os.environ.copy()
    environment_base.update(
        {
            "CUDA_VISIBLE_DEVICES": "1,2,4,5",
            "OMP_NUM_THREADS": "4",
            "MKL_NUM_THREADS": "4",
            "OPENBLAS_NUM_THREADS": "4",
        }
    )
    failure = None
    while pending or running:
        for job_id, (process, log_handle, _physical) in list(running.items()):
            returncode = process.poll()
            if returncode is None:
                continue
            log_handle.close()
            del running[job_id]
            if returncode != 0 or not valid_result(jobs[job_id]):
                failure = {"job_id": job_id, "returncode": returncode, "valid_result": valid_result(jobs[job_id])}
                break
            completed.add(job_id)
        if failure:
            break
        active_physical = {physical for _process, _handle, physical in running.values() if physical is not None}
        active_cpu = sum(physical is None for _process, _handle, physical in running.values())
        started = False
        for job_id in sorted(pending):
            job = jobs[job_id]
            if not set(job["dependencies"]) <= completed:
                continue
            physical = job.get("physical_gpu")
            if physical is not None and (physical in active_physical or len(active_physical) >= 4):
                continue
            if physical is None and active_cpu >= 1:
                continue
            require(not Path(job["output_dir"]).exists(), f"output_exists:{job_id}")
            log_handle = (logs / f"{job_id}.log").open("ab", buffering=0)
            process = subprocess.Popen(job["command"], stdout=log_handle, stderr=subprocess.STDOUT, env=environment_base, start_new_session=True)
            running[job_id] = (process, log_handle, physical)
            pending.remove(job_id)
            if physical is not None:
                active_physical.add(physical)
            else:
                active_cpu += 1
            started = True
        atomic_json(
            args.runtime_root / "GRAPH_STATUS.json",
            {
                "status": "RUNNING",
                "completed": len(completed),
                "pending": len(pending),
                "running": len(running),
                "running_jobs": sorted(running),
                "job_graph_sha256": args.expected_job_graph_sha256,
                "outer_test_truth_access_count": 0,
                "outer_metrics_access_count": 0,
                "v4_f_test32_access_count": 0,
            },
        )
        if pending and not running and not started:
            failure = {"job_id": "DAG_DEADLOCK"}
            break
        if pending or running:
            time.sleep(args.poll_seconds)
    if failure:
        for process, handle, _physical in running.values():
            process.terminate()
            handle.close()
        atomic_json(args.runtime_root / "TERMINAL.json", {"status": "FAIL", "failure": failure, "returncode": 1})
        return 1
    require(len(completed) == 9, "terminal_job_closure")
    atomic_json(
        args.runtime_root / "TERMINAL.json",
        {
            "status": "PASS",
            "returncode": 0,
            "completed": 9,
            "job_graph_sha256": args.expected_job_graph_sha256,
            "cuda_smoke_receipt_sha256": args.expected_cuda_smoke_receipt_sha256,
            "authorization_overlay_sha256": args.expected_authorization_overlay_sha256,
            "outer_test_truth_access_count": 0,
            "outer_metrics_access_count": 0,
            "v4_f_test32_access_count": 0,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
