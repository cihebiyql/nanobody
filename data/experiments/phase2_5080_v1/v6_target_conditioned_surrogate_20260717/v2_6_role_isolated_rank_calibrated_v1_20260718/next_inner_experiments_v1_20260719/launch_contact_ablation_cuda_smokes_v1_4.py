#!/usr/bin/env python3
"""Fail-closed launcher for the two V1.4 CUDA smoke jobs only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


SCHEMA = "pvrig_v2_6_contact_ablation_cuda_smoke_launcher_v1_4"
PYTHON = Path("/data1/qlyu/software/envs/pvrig-v6-tc/bin/python")
VISIBLE = "1,4,5,6"
SMOKE_JOB_SHA256 = "2ae1e1c03648dfc9a721958656c6e1532aaa9c883b48b01e2b7b04019ca3efa8"
TRAINER_SHA256 = "a16bc446747edb95fdbc6d507c884a89810a97ec4f942dd895476c98a9f5f605"
INTEGRATION_FREEZE_SHA256 = "22f34aff3c5cd9b912f94e1266dffcb217c5767974160068365bea3889e0f4fc"
FIREWALL = ("outer_test_truth_access_count", "outer_metrics_access_count", "v4_f_test32_access_count")
JOBS = (
    ("F0_MARGINAL_ONLY_NO_RANK", 5, "cuda:2", 1.0, 0.0),
    ("F0_PAIR_ONLY_NO_RANK", 6, "cuda:3", 0.0, 0.5),
)


def require(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def gpu_idle(index: int) -> bool:
    lines = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,name,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    for line in lines:
        gpu, name, memory, utilization = [part.strip() for part in line.split(",", 3)]
        if int(gpu) == index:
            return name == "NVIDIA GeForce RTX 4090" and int(memory) <= 512 and int(utilization) <= 5
    return False


def validate_result(path: Path, variant: str, marginal: float, pair: float) -> None:
    require(path.is_file() and not path.is_symlink(), f"result_missing:{variant}")
    result = json.loads(path.read_text())
    require(result.get("status") == "PASS_OPEN_INNER_CONTACT_ABLATION_CUDA_SMOKE", f"result_status:{variant}")
    require(result.get("variant") == variant and result.get("fixed_epochs") == 1, f"result_identity:{variant}")
    require(result.get("contact_ablation") == {"marginal_weight": marginal, "pair_weight": pair}, f"result_weights:{variant}")
    require(result.get("exact_min_violation_count") == 0, f"exact_min:{variant}")
    require(all(result.get(field) == 0 for field in FIREWALL), f"firewall:{variant}")
    output = path.parent
    for artifact in result["artifacts"].values():
        target = output / artifact["path"]
        require(target.is_file() and not target.is_symlink() and sha(target) == artifact["sha256"], f"artifact:{variant}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    args = parser.parse_args()
    require(not args.runtime_root.exists(), "runtime_root_exists")
    job_script = args.package_root / "run_contact_ablation_cuda_smoke_v1_4.py"
    trainer = args.package_root / "integration_v1_4/real1507_role_isolated_trainer_v1_4.py"
    freeze = args.package_root / "integration_v1_4/IMPLEMENTATION_FREEZE_V1_4.json"
    require(sha(job_script) == SMOKE_JOB_SHA256, "smoke_job_hash")
    require(sha(trainer) == TRAINER_SHA256, "trainer_hash")
    require(sha(freeze) == INTEGRATION_FREEZE_SHA256, "integration_freeze_hash")
    require(all(gpu_idle(index) for index in (5, 6)), "smoke_gpu_busy")
    args.runtime_root.mkdir(parents=True)
    (args.runtime_root / "logs").mkdir()
    environment = os.environ.copy()
    environment.update({"CUDA_VISIBLE_DEVICES": VISIBLE, "CUBLAS_WORKSPACE_CONFIG": ":4096:8", "OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4"})
    processes = []
    for variant, physical, device, marginal, pair in JOBS:
        output = args.runtime_root / variant
        command = [str(PYTHON), str(job_script), "--package-root", str(args.package_root), "--output-dir", str(output), "--job-id", f"outer0.inner0.cuda_smoke.{variant}.seed43", "--variant", variant, "--integration-lane", "F_SHARED_GATED_CONTACT_TRANSFER", "--seed", "43", "--lambda-rank", "0.0", "--physical-gpu", str(physical), "--device", device]
        handle = (args.runtime_root / "logs" / f"{variant}.log").open("ab", buffering=0)
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, env=environment, start_new_session=True)
        processes.append((variant, marginal, pair, output, process, handle, command))
    atomic_json(args.runtime_root / "LAUNCH_RECEIPT.json", {"schema_version": SCHEMA, "status": "RUNNING_CUDA_SMOKE_ONLY", "jobs": [{"variant": variant, "pid": process.pid, "command": command} for variant, _m, _p, _o, process, _h, command in processes], **{field: 0 for field in FIREWALL}})
    failure = None
    while processes:
        for item in list(processes):
            variant, marginal, pair, output, process, handle, _command = item
            code = process.poll()
            if code is None:
                continue
            handle.close()
            processes.remove(item)
            try:
                require(code == 0, f"returncode:{variant}:{code}")
                validate_result(output / "RESULT.json", variant, marginal, pair)
            except Exception as exc:
                failure = str(exc)
                break
        if failure:
            for _v, _m, _p, _o, process, handle, _c in processes:
                process.terminate(); handle.close()
            break
        if processes:
            time.sleep(10)
    atomic_json(args.runtime_root / "TERMINAL.json", {"schema_version": SCHEMA, "status": "FAIL" if failure else "PASS_BOTH_CONTACT_ABLATION_CUDA_SMOKES", "failure": failure, **{field: 0 for field in FIREWALL}})
    return 1 if failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
