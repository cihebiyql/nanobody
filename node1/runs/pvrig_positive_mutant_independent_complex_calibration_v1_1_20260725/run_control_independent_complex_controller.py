#!/usr/bin/env python3
"""Run Boltz-2 and Chai-1 control-panel shards without HADDOCK restraints."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


BOLTZ = Path("/data/qlyu/anaconda3/envs/boltz/bin/boltz")
CHAI_PYTHON = Path("/data/qlyu/software/envs/chai1/bin/python")


def write_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run_parallel(
    commands: list[tuple[int, list[str], dict[str, str], Path]]
) -> list[dict[str, int]]:
    running: list[tuple[int, subprocess.Popen[bytes], object]] = []
    for shard, command, env, log_path in commands:
        log_handle = log_path.open("wb")
        process = subprocess.Popen(
            command, stdout=log_handle, stderr=subprocess.STDOUT, env=env
        )
        running.append((shard, process, log_handle))
    failures: list[dict[str, int]] = []
    for shard, process, log_handle in running:
        code = process.wait()
        log_handle.close()
        if code:
            failures.append({"shard": shard, "return_code": code})
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--script-root", type=Path, required=True)
    parser.add_argument("--gpus", default="1,2,3,4,6")
    args = parser.parse_args()

    project = args.project.resolve()
    script_root = args.script_root.resolve()
    gpus = [token.strip() for token in args.gpus.split(",") if token.strip()]
    if not gpus or len(gpus) != len(set(gpus)):
        raise ValueError("one or more unique GPU IDs required")
    manifest_path = (
        project / "manifests" / "control_independent_complex_manifest.tsv"
    )
    import csv
    with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
        manifest = list(csv.DictReader(handle, delimiter="\t"))
    expected_candidates = len(manifest)
    if expected_candidates != 9:
        raise ValueError(f"expected 9 controls, found {expected_candidates}")
    logs = project / "logs"
    status_dir = project / "status"
    logs.mkdir(parents=True, exist_ok=True)
    status_dir.mkdir(parents=True, exist_ok=True)

    lock_handle = (project / "CONTROLLER.lock").open("w")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 2
    lock_handle.write(str(os.getpid()) + "\n")
    lock_handle.flush()
    state: dict[str, object] = {
        "schema_version": "pvrig.control.independent_complex.controller.v1",
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "state": "RUNNING_BOLTZ",
        "gpus": gpus,
    }
    write_json(project / "STATUS.json", state)
    (project / "RUNNING").write_text(str(os.getpid()) + "\n")
    try:
        boltz_commands = []
        for shard, gpu in enumerate(gpus):
            env = os.environ.copy()
            env.update(
                {
                    "CUDA_VISIBLE_DEVICES": gpu,
                    "BOLTZ_CACHE": "/data/qlyu/.boltz",
                    "OMP_NUM_THREADS": "2",
                    "MKL_NUM_THREADS": "2",
                    "OPENBLAS_NUM_THREADS": "2",
                }
            )
            boltz_commands.append(
                (
                    shard,
                    [
                        str(BOLTZ), "predict",
                        str(project / "inputs" / "boltz" / f"shard_{shard}"),
                        "--out_dir",
                        str(project / "outputs" / "boltz" / f"shard_{shard}"),
                        "--cache", "/data/qlyu/.boltz",
                        "--recycling_steps", "3",
                        "--sampling_steps", "50",
                        "--diffusion_samples", "1",
                        "--max_parallel_samples", "1",
                        "--num_workers", "0",
                        "--preprocessing-threads", "2",
                        "--output_format", "pdb",
                        "--no_kernels",
                        "--override",
                    ],
                    env,
                    logs / f"boltz_shard_{shard}.log",
                )
            )
        failures = run_parallel(boltz_commands)
        if failures:
            raise RuntimeError(f"Boltz shard failures: {failures}")
        boltz_count = len(
            list((project / "outputs" / "boltz").rglob("*_model_0.pdb"))
        )
        if boltz_count != expected_candidates:
            raise RuntimeError(
                f"expected {expected_candidates} Boltz PDBs, found {boltz_count}"
            )

        state.update(
            {
                "state": "RUNNING_CHAI",
                "boltz_completed_at": datetime.now(timezone.utc).isoformat(),
                "boltz_pdb_count": boltz_count,
            }
        )
        write_json(project / "STATUS.json", state)
        chai_commands = []
        for shard, gpu in enumerate(gpus):
            env = os.environ.copy()
            env.update(
                {
                    "CUDA_VISIBLE_DEVICES": gpu,
                    "CHAI_DOWNLOADS_DIR": "/data/qlyu/software/models/chai1",
                    "OMP_NUM_THREADS": "2",
                    "MKL_NUM_THREADS": "2",
                    "OPENBLAS_NUM_THREADS": "2",
                }
            )
            chai_commands.append(
                (
                    shard,
                    [
                        str(CHAI_PYTHON),
                        str(script_root / "run_chai_control_shard.py"),
                        "--manifest",
                        str(
                            project / "manifests"
                            / "control_independent_complex_manifest.tsv"
                        ),
                        "--project", str(project),
                        "--shard", str(shard),
                    ],
                    env,
                    logs / f"chai_shard_{shard}.log",
                )
            )
        failures = run_parallel(chai_commands)
        if failures:
            raise RuntimeError(f"Chai shard failures: {failures}")
        chai_count = len(
            list((project / "outputs" / "chai").rglob("pred.model_idx_*.cif"))
        )
        if chai_count != expected_candidates * 2:
            raise RuntimeError(
                f"expected {expected_candidates * 2} Chai CIFs, found {chai_count}"
            )

        state.update(
            {
                "state": "RAW_PREDICTIONS_COMPLETE",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "boltz_pdb_count": boltz_count,
                "chai_cif_count": chai_count,
                "next_required_stage": (
                    "normalize chains, align to 8X6B/9E6Y, score hotspot/"
                    "PVRL2 occlusion/CDR dominance, then compare tools"
                ),
            }
        )
        write_json(project / "STATUS.json", state)
        (project / "RAW_PREDICTIONS_COMPLETE").write_text(
            datetime.now(timezone.utc).isoformat() + "\n"
        )
        return 0
    except Exception as exc:
        state.update(
            {
                "state": "FAILED",
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        write_json(project / "STATUS.json", state)
        raise
    finally:
        running = project / "RUNNING"
        if running.exists():
            running.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
