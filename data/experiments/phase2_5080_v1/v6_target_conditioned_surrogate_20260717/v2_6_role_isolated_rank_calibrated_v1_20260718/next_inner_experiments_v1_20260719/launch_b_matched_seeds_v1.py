#!/usr/bin/env python3
"""Launch the two missing matched B seeds on open outer0/inner0 only.

This is a resource-extension launcher around the already frozen V1.3 pilot
job wrapper.  It does not change model code, losses, split, epochs, or inputs.
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


SCHEMA = "pvrig_v2_6_b_matched_seed_extension_launcher_v1"
PACKAGE = Path("/data1/qlyu/projects/pvrig_v2_6_inner_only_pilot_resolved_v1_2_20260719")
WRAPPER = PACKAGE / "src/run_inner_pilot_job_v1_2.py"
PYTHON = Path("/data1/qlyu/software/envs/pvrig-v6-tc/bin/python")
WRAPPER_SHA256 = "cedf5adc404646f2a083a58723753115be888abe40931841a99865013835b10e"
PACKAGE_MANIFEST_SHA256 = "a0193fadcda0400cb249144430ee2835c64fcbca51ff18631e96acfa78a04f59"
VISIBLE = "1,4,5,6"
JOBS = (
    {"seed": 97, "physical_gpu": 1, "device": "cuda:0"},
    {"seed": 193, "physical_gpu": 4, "device": "cuda:1"},
)
FIREWALL_FIELDS = (
    "outer_test_truth_access_count",
    "outer_metrics_access_count",
    "v4_f_test32_access_count",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def gpu_state(index: int) -> tuple[str, int, int]:
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,name,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    for line in output:
        gpu, name, memory, utilization = [item.strip() for item in line.split(",", 3)]
        if int(gpu) == index:
            return name, int(memory), int(utilization)
    raise RuntimeError(f"gpu_missing:{index}")


def validate_result(output_dir: Path, seed: int) -> None:
    result_path = output_dir / "RESULT.json"
    require(result_path.is_file() and not result_path.is_symlink(), f"result_missing:{seed}")
    result = json.loads(result_path.read_text())
    require(result.get("status") == "PASS_INNER_ONLY_EIGHT_EPOCH_PILOT_JOB", f"result_status:{seed}")
    require(result.get("variant") == "B_SCALAR_ATTENTION_ONLY", f"result_variant:{seed}")
    require(int(result.get("seed", -1)) == seed, f"result_seed:{seed}")
    require(result.get("exact_min_violation_count") == 0, f"result_exact_min:{seed}")
    require(all(result.get(field) == 0 for field in FIREWALL_FIELDS), f"result_firewall:{seed}")
    for artifact in result["artifacts"].values():
        path = output_dir / artifact["path"]
        require(path.is_file() and not path.is_symlink(), f"artifact_missing:{seed}:{path.name}")
        require(sha256_file(path) == artifact["sha256"], f"artifact_hash:{seed}:{path.name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    args = parser.parse_args()
    require(not args.runtime_root.exists(), "runtime_root_exists")
    require(PYTHON.is_file() and WRAPPER.is_file(), "frozen_runtime_missing")
    require(sha256_file(WRAPPER) == WRAPPER_SHA256, "wrapper_hash")
    require(sha256_file(PACKAGE / "PACKAGE_MANIFEST.json") == PACKAGE_MANIFEST_SHA256, "package_manifest_hash")
    free = os.statvfs("/data1")
    require(free.f_bavail * free.f_frsize >= 100 * 1024**3, "data1_free_below_100GiB")
    for job in JOBS:
        name, memory, utilization = gpu_state(job["physical_gpu"])
        require(name == "NVIDIA GeForce RTX 4090", f"gpu_model:{job['physical_gpu']}")
        require(memory <= 512 and utilization <= 5, f"gpu_busy:{job['physical_gpu']}:{memory}:{utilization}")

    args.runtime_root.mkdir(parents=True)
    (args.runtime_root / "logs").mkdir()
    environment = os.environ.copy()
    environment.update({
        "CUDA_VISIBLE_DEVICES": VISIBLE,
        "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
        "OMP_NUM_THREADS": "4",
        "MKL_NUM_THREADS": "4",
        "OPENBLAS_NUM_THREADS": "4",
    })
    running = []
    for job in JOBS:
        seed = job["seed"]
        output = args.runtime_root / "gpu_jobs/B_SCALAR_ATTENTION_ONLY" / f"seed_{seed}"
        command = [
            str(PYTHON), str(WRAPPER), "--package-root", str(PACKAGE),
            "--output-dir", str(output), "--job-id", f"outer0.inner0.B_SCALAR_ATTENTION_ONLY.seed{seed}",
            "--variant", "B_SCALAR_ATTENTION_ONLY", "--integration-lane", "B_SCALAR_ATTENTION_ONLY",
            "--seed", str(seed), "--lambda-rank", "0.0",
            "--physical-gpu", str(job["physical_gpu"]), "--device", job["device"],
        ]
        handle = (args.runtime_root / "logs" / f"B.seed{seed}.log").open("ab", buffering=0)
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, env=environment, start_new_session=True)
        running.append((job, output, process, handle, command))
    atomic_json(args.runtime_root / "LAUNCH_RECEIPT.json", {
        "schema_version": SCHEMA,
        "status": "RUNNING",
        "jobs": [{**job, "pid": process.pid, "command": command} for job, _output, process, _handle, command in running],
        "frozen_wrapper_sha256": WRAPPER_SHA256,
        "frozen_package_manifest_sha256": PACKAGE_MANIFEST_SHA256,
        **{field: 0 for field in FIREWALL_FIELDS},
    })
    failure = None
    while running:
        for item in list(running):
            job, output, process, handle, _command = item
            code = process.poll()
            if code is None:
                continue
            handle.close()
            running.remove(item)
            if code != 0:
                failure = {"seed": job["seed"], "returncode": code}
                break
            try:
                validate_result(output, job["seed"])
            except Exception as exc:
                failure = {"seed": job["seed"], "validation_error": str(exc)}
                break
        if failure:
            for _job, _output, process, handle, _command in running:
                process.terminate()
                handle.close()
            break
        if running:
            time.sleep(args.poll_seconds)
    terminal = {
        "schema_version": SCHEMA,
        "status": "FAIL" if failure else "PASS_B_MATCHED_SEEDS_97_193",
        "failure": failure,
        "seeds": [97, 193],
        **{field: 0 for field in FIREWALL_FIELDS},
    }
    atomic_json(args.runtime_root / "TERMINAL.json", terminal)
    return 1 if failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
