#!/usr/bin/env python3
"""Schedule six frozen open-inner eight-epoch contact-ablation jobs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


SCHEMA = "pvrig_v2_6_contact_ablation_eight_epoch_launcher_v1_4_2"
PYTHON = Path("/data1/qlyu/software/envs/pvrig-v6-tc/bin/python")
VISIBLE = "1,4,5,6"
JOB_SHA256 = "9c66e7019b7a5dd9d620a7648489c1406e321054306a12f12a28a019783d6790"
TRAINER_SHA256 = "a16bc446747edb95fdbc6d507c884a89810a97ec4f942dd895476c98a9f5f605"
INTEGRATION_FREEZE_SHA256 = "22f34aff3c5cd9b912f94e1266dffcb217c5767974160068365bea3889e0f4fc"
SMOKE_TERMINAL = Path("/data1/qlyu/projects/pvrig_v2_6_contact_ablation_cuda_smoke_runtime_v1_4_1_20260719/TERMINAL.json")
SMOKE_TERMINAL_SHA256 = "8cfb0326c372f3ae5592a5f8c196860c9e85e72658f4ffa3baad96da7616dac9"
FIREWALL = ("outer_test_truth_access_count", "outer_metrics_access_count", "v4_f_test32_access_count")
GPU_MAP = {1: "cuda:0", 4: "cuda:1", 5: "cuda:2", 6: "cuda:3"}
JOBS = (
    ("F0_MARGINAL_ONLY_NO_RANK", 43, 1, 1.0, 0.0),
    ("F0_PAIR_ONLY_NO_RANK", 43, 4, 0.0, 0.5),
    ("F0_MARGINAL_ONLY_NO_RANK", 97, 5, 1.0, 0.0),
    ("F0_PAIR_ONLY_NO_RANK", 97, 6, 0.0, 0.5),
    ("F0_MARGINAL_ONLY_NO_RANK", 193, 1, 1.0, 0.0),
    ("F0_PAIR_ONLY_NO_RANK", 193, 4, 0.0, 0.5),
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
    lines = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.used,utilization.gpu", "--format=csv,noheader,nounits"], check=True, capture_output=True, text=True).stdout.splitlines()
    for line in lines:
        gpu, name, memory, utilization = [part.strip() for part in line.split(",", 3)]
        if int(gpu) == index:
            return name == "NVIDIA GeForce RTX 4090" and int(memory) <= 512 and int(utilization) <= 5
    return False


def validate_result(output: Path, variant: str, seed: int, marginal: float, pair: float) -> None:
    path = output / "RESULT.json"
    require(path.is_file() and not path.is_symlink(), f"result_missing:{variant}:{seed}")
    result = json.loads(path.read_text())
    require(result.get("status") == "PASS_OPEN_INNER_CONTACT_ABLATION_EIGHT_EPOCH", f"result_status:{variant}:{seed}")
    require(result.get("variant") == variant and int(result.get("seed", -1)) == seed, f"result_identity:{variant}:{seed}")
    require(result.get("fixed_epochs") == 8 and result.get("optimizer_steps") == 544, f"result_steps:{variant}:{seed}")
    require(result.get("contact_ablation") == {"marginal_weight": marginal, "pair_weight": pair}, f"result_weights:{variant}:{seed}")
    require(result.get("exact_min_violation_count") == 0, f"exact_min:{variant}:{seed}")
    require(all(result.get(field) == 0 for field in FIREWALL), f"firewall:{variant}:{seed}")
    for artifact in result["artifacts"].values():
        target = output / artifact["path"]
        require(target.is_file() and not target.is_symlink() and sha(target) == artifact["sha256"], f"artifact:{variant}:{seed}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    args = parser.parse_args()
    require(not args.runtime_root.exists(), "runtime_root_exists")
    script = args.package_root / "run_contact_ablation_8epoch_v1_4_2.py"
    require(sha(script) == JOB_SHA256, "job_hash")
    require(sha(args.package_root / "integration_v1_4/real1507_role_isolated_trainer_v1_4.py") == TRAINER_SHA256, "trainer_hash")
    require(sha(args.package_root / "integration_v1_4/IMPLEMENTATION_FREEZE_V1_4.json") == INTEGRATION_FREEZE_SHA256, "integration_freeze_hash")
    require(sha(SMOKE_TERMINAL) == SMOKE_TERMINAL_SHA256, "smoke_terminal_hash")
    smoke = json.loads(SMOKE_TERMINAL.read_text())
    require(smoke.get("status") == "PASS_BOTH_CONTACT_ABLATION_CUDA_SMOKES" and all(smoke.get(field) == 0 for field in FIREWALL), "smoke_gate")
    require(all(gpu_idle(index) for index in GPU_MAP), "production_gpu_busy")
    args.runtime_root.mkdir(parents=True)
    (args.runtime_root / "logs").mkdir()
    environment = os.environ.copy()
    environment.update({"CUDA_VISIBLE_DEVICES": VISIBLE, "CUBLAS_WORKSPACE_CONFIG": ":4096:8", "OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4"})
    pending = list(JOBS)
    running = []
    completed = []
    failure = None
    while pending or running:
        for item in list(running):
            job, output, process, handle = item
            code = process.poll()
            if code is None:
                continue
            handle.close(); running.remove(item)
            variant, seed, physical, marginal, pair = job
            try:
                require(code == 0, f"returncode:{variant}:{seed}:{code}")
                validate_result(output, variant, seed, marginal, pair)
            except Exception as exc:
                failure = str(exc); break
            completed.append((variant, seed))
        if failure:
            for _job, _output, process, handle in running:
                process.terminate(); handle.close()
            break
        busy = {job[2] for job, _output, _process, _handle in running}
        for job in list(pending):
            variant, seed, physical, marginal, pair = job
            if physical in busy:
                continue
            output = args.runtime_root / variant / f"seed_{seed}"
            command = [str(PYTHON), str(script), "--package-root", str(args.package_root), "--output-dir", str(output), "--job-id", f"outer0.inner0.{variant}.seed{seed}", "--variant", variant, "--integration-lane", "F_SHARED_GATED_CONTACT_TRANSFER", "--seed", str(seed), "--lambda-rank", "0.0", "--physical-gpu", str(physical), "--device", GPU_MAP[physical]]
            handle = (args.runtime_root / "logs" / f"{variant}.seed{seed}.log").open("ab", buffering=0)
            process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, env=environment, start_new_session=True)
            running.append((job, output, process, handle)); pending.remove(job); busy.add(physical)
        atomic_json(args.runtime_root / "STATUS.json", {"schema_version": SCHEMA, "status": "RUNNING", "completed": completed, "pending": [[j[0], j[1]] for j in pending], "running": [[j[0], j[1], p.pid] for j, _o, p, _h in running], **{field: 0 for field in FIREWALL}})
        if pending or running:
            time.sleep(10)
    terminal = {"schema_version": SCHEMA, "status": "FAIL" if failure else "PASS_ALL_SIX_CONTACT_ABLATION_JOBS", "failure": failure, "completed": completed, **{field: 0 for field in FIREWALL}}
    atomic_json(args.runtime_root / "TERMINAL.json", terminal)
    return 1 if failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
