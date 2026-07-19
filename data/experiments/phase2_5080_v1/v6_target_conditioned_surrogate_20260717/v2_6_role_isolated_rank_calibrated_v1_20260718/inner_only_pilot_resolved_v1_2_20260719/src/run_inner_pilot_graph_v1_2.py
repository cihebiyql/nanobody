#!/usr/bin/env python3
"""Fail-closed scheduler for the resolved V2.6 outer0/inner0 pilot."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


GPU_MAP = {1: "cuda:0", 4: "cuda:1", 5: "cuda:2", 6: "cuda:3"}
VISIBLE = "1,4,5,6"
INTEGRATION_FREEZE = "e73335c32e8495d609f9b5e6379ba648d1c38e4da49c40088468eae7308e3faa"
INTEGRATION_TRAINER = "e99146be166cab7f703bd6cbcad3594e196d7a155c422459cb16f8cbfc2b6a24"
SMOKE = "e6901c772411464d8b2fb906839dd07afcbfdfc39e1d8ec1d18b01e66b50ea21"


def require(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"json_not_regular:{path}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"json_not_object:{path}")
    return value


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def validate_smoke(smoke: dict[str, Any]) -> None:
    require(smoke.get("status") == "PASS", "smoke_status")
    require(smoke.get("precision") == "bf16", "smoke_bf16")
    require(smoke.get("integration_freeze_sha256") == INTEGRATION_FREEZE, "smoke_integration_freeze")
    require(smoke.get("integration_trainer_sha256") == INTEGRATION_TRAINER, "smoke_integration_trainer")
    require(smoke["be_trajectory"]["optimizer_steps"] == 20, "smoke_steps")
    require(smoke["be_trajectory"]["exact_scalar_trajectory_hash_match_every_step"] is True, "smoke_be")
    require(float(smoke["be_trajectory"]["maximum_scalar_shared_parameter_delta"]) <= 1e-7, "smoke_be_delta")
    require(smoke["f_shared_gated"]["kappa"] == 0.25, "smoke_kappa")
    require(smoke["f_shared_gated"]["gradient_budget_violation_count"] == 0, "smoke_budget")
    require(smoke["f_shared_gated"]["post_lambda_budget_pass_every_step"] is True, "smoke_budget_steps")
    require(smoke["gradient_accumulation"]["reduction"] == "EXACT_EFFECTIVE_MASS_WEIGHTED", "smoke_accumulation")
    require(smoke["exact_min"]["maximum_abs_error"] == 0.0, "smoke_exact_min")
    require(all(value == 0 for value in smoke["firewall"].values()), "smoke_firewall")


def validate_package(root: Path, manifest: dict[str, Any]) -> None:
    require(manifest.get("status") == "FROZEN_RESOLVED_AUTHORIZED", "manifest_status")
    require(manifest.get("execution_authorized") is True, "manifest_authorization")
    require(manifest.get("integration_freeze_sha256") == INTEGRATION_FREEZE, "manifest_integration_freeze")
    require(manifest.get("integration_trainer_sha256") == INTEGRATION_TRAINER, "manifest_integration_trainer")
    require(manifest.get("smoke_result_sha256") == SMOKE, "manifest_smoke")
    for relative, expected in manifest["files"].items():
        path = root / relative
        require(path.is_file() and not path.is_symlink(), f"package_file:{relative}")
        require(sha(path) == expected, f"package_hash:{relative}")


def validate_result(job: dict[str, Any]) -> bool:
    path = Path(job["expected_result"])
    if not path.is_file() or path.is_symlink():
        return False
    try:
        result = json.loads(path.read_text())
        if not str(result.get("status", "")).startswith("PASS") or result.get("job_id") != job["job_id"]:
            return False
        if any(result.get(field) != 0 for field in ("outer_test_truth_access_count", "outer_metrics_access_count", "v4_f_test32_access_count")):
            return False
        if job["kind"] == "GPU_INNER_PILOT":
            if result.get("exact_min_violation_count") != 0 or result.get("execution_wrapper_launched") is not True:
                return False
            for key in ("training_receipt", "step_evidence", "checkpoint", "predictions"):
                item = result["artifacts"][key]
                artifact = Path(job["output_dir"]) / item["path"]
                if not artifact.is_file() or artifact.is_symlink() or sha(artifact) != item["sha256"]:
                    return False
            step_item = result["artifacts"]["step_evidence"]
            lines = [line for line in (Path(job["output_dir"]) / step_item["path"]).read_text().splitlines() if line.strip()]
            if len(lines) != result["optimizer_steps"] or len(lines) != step_item["rows"]:
                return False
        return True
    except Exception:
        return False


def gpu_idle(index: int) -> bool:
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,name,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    for line in output:
        gpu, name, memory, utilization = [value.strip() for value in line.split(",", 3)]
        if int(gpu) == index:
            return name == "NVIDIA GeForce RTX 4090" and int(memory) <= 512 and int(utilization) <= 5
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--job-graph", type=Path, required=True)
    parser.add_argument("--expected-job-graph-sha256", required=True)
    parser.add_argument("--package-manifest", type=Path, required=True)
    parser.add_argument("--expected-package-manifest-sha256", required=True)
    parser.add_argument("--smoke-result", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args()
    require(not args.runtime_root.exists(), "runtime_root_exists")
    require(sha(args.job_graph) == args.expected_job_graph_sha256, "graph_hash")
    require(sha(args.package_manifest) == args.expected_package_manifest_sha256, "manifest_hash")
    require(sha(args.smoke_result) == SMOKE, "smoke_hash")
    graph = load_json(args.job_graph)
    manifest = load_json(args.package_manifest)
    validate_smoke(load_json(args.smoke_result))
    validate_package(args.package_root, manifest)
    require(graph.get("status") == "FROZEN_RESOLVED_AUTHORIZED", "graph_status")
    require(graph.get("cuda_visible_devices") == VISIBLE, "graph_visible")
    require(graph.get("physical_to_logical") == {str(key): value for key, value in GPU_MAP.items()}, "graph_gpu_map")
    require(all(graph.get(field) == 0 for field in ("outer_test_truth_access_count", "outer_metrics_access_count", "v4_f_test32_access_count")), "graph_firewall")
    jobs = {job["job_id"]: job for job in graph["jobs"]}
    require(len(jobs) == 9, "job_count")
    require(sum(job["kind"] == "GPU_INNER_PILOT" for job in jobs.values()) == 8, "gpu_job_count")
    require(sum(job["kind"] == "CPU_INNER_METRICS_COLLECT" for job in jobs.values()) == 1, "cpu_job_count")
    free = os.statvfs("/data1")
    require(free.f_bavail * free.f_frsize / (1024 ** 3) >= 100.0, "data1_free")
    for index in GPU_MAP:
        require(gpu_idle(index), f"gpu_not_idle:{index}")

    args.runtime_root.mkdir(parents=True)
    (args.runtime_root / "logs").mkdir()
    pending = set(jobs)
    completed: set[str] = set()
    running: dict[str, tuple[subprocess.Popen[Any], Any, int | None]] = {}
    environment = os.environ.copy()
    environment.update({
        "CUDA_VISIBLE_DEVICES": VISIBLE,
        "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
        "OMP_NUM_THREADS": "4",
        "MKL_NUM_THREADS": "4",
        "OPENBLAS_NUM_THREADS": "4",
    })
    failure = None
    while pending or running:
        for job_id, (process, handle, _gpu) in list(running.items()):
            returncode = process.poll()
            if returncode is None:
                continue
            handle.close()
            del running[job_id]
            if returncode != 0 or not validate_result(jobs[job_id]):
                failure = {"job_id": job_id, "returncode": returncode, "valid_result": validate_result(jobs[job_id])}
                break
            completed.add(job_id)
        if failure:
            break
        active_gpus = {gpu for _process, _handle, gpu in running.values() if gpu is not None}
        cpu_running = any(gpu is None for _process, _handle, gpu in running.values())
        started = False
        for job_id in sorted(pending):
            job = jobs[job_id]
            if not set(job["dependencies"]) <= completed:
                continue
            gpu = job.get("physical_gpu")
            if gpu is not None and (gpu in active_gpus or len(active_gpus) >= 4):
                continue
            if gpu is None and cpu_running:
                continue
            require(not Path(job["output_dir"]).exists(), f"output_exists:{job_id}")
            handle = (args.runtime_root / "logs" / f"{job_id}.log").open("ab", buffering=0)
            process = subprocess.Popen(job["command"], stdout=handle, stderr=subprocess.STDOUT, env=environment, start_new_session=True)
            running[job_id] = (process, handle, gpu)
            pending.remove(job_id)
            if gpu is not None:
                active_gpus.add(gpu)
            else:
                cpu_running = True
            started = True
        atomic_json(args.runtime_root / "GRAPH_STATUS.json", {
            "status": "RUNNING",
            "completed": len(completed),
            "pending": len(pending),
            "running": len(running),
            "running_jobs": sorted(running),
            "job_graph_sha256": args.expected_job_graph_sha256,
            "outer_test_truth_access_count": 0,
            "outer_metrics_access_count": 0,
            "v4_f_test32_access_count": 0,
        })
        if pending and not running and not started:
            failure = {"job_id": "DAG_DEADLOCK"}
            break
        if pending or running:
            time.sleep(args.poll_seconds)
    if failure:
        for process, handle, _gpu in running.values():
            process.terminate()
            handle.close()
        atomic_json(args.runtime_root / "TERMINAL.json", {"status": "FAIL", "failure": failure})
        return 1
    require(len(completed) == 9, "job_closure")
    atomic_json(args.runtime_root / "TERMINAL.json", {
        "status": "PASS",
        "completed": 9,
        "job_graph_sha256": args.expected_job_graph_sha256,
        "smoke_result_sha256": SMOKE,
        "outer_test_truth_access_count": 0,
        "outer_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
