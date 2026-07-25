#!/usr/bin/env python3
"""Run NanoNet plus eight resumable IgFold shards, then analyze Top200."""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


IGFOLD_PYTHON = Path("/data/qlyu/software/envs/vhh-igfold/bin/python")
NANONET = Path("/data/qlyu/software/vhh_eval_tools/bin/nanonet-predict")
BOLTZ_PYTHON = Path("/data/qlyu/anaconda3/envs/boltz/bin/python")


def write_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def count_nanonet(project: Path) -> int:
    return len(list((project / "models" / "nanonet").glob("*_nanonet_backbone_cb.pdb")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--script-root", type=Path, required=True)
    parser.add_argument("--gpus", default="0,1,2,3,4,5,6,7")
    args = parser.parse_args()

    project = args.project.resolve()
    script_root = args.script_root.resolve()
    status_dir = project / "status"
    logs = project / "logs"
    status_dir.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    lock_handle = (project / "CONTROLLER.lock").open("w")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("controller already running", file=sys.stderr)
        return 2
    lock_handle.write(str(os.getpid()) + "\n")
    lock_handle.flush()

    gpus = [token.strip() for token in args.gpus.split(",") if token.strip()]
    if len(gpus) != 8:
        raise ValueError("exactly eight GPU IDs are required for the eight frozen shards")

    state = {
        "schema_version": "pvrig.top200.structure_consistency.controller.v1",
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "state": "RUNNING",
        "gpus": gpus,
        "nanonet_count": count_nanonet(project),
    }
    write_json(project / "STATUS.json", state)
    (project / "RUNNING").write_text(str(os.getpid()) + "\n")

    try:
        if count_nanonet(project) != 200:
            env = os.environ.copy()
            env.update(
                {
                    "CUDA_VISIBLE_DEVICES": "-1",
                    "OMP_NUM_THREADS": "8",
                    "MKL_NUM_THREADS": "8",
                    "OPENBLAS_NUM_THREADS": "8",
                    "TF_FORCE_GPU_ALLOW_GROWTH": "true",
                }
            )
            with (logs / "nanonet.log").open("w") as log:
                subprocess.run(
                    [
                        str(NANONET),
                        str(project / "inputs" / "top200.fasta"),
                        "-o",
                        str(project / "models" / "nanonet"),
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=env,
                    check=True,
                )

        processes: list[tuple[int, subprocess.Popen[bytes], object]] = []
        for shard, gpu in enumerate(gpus):
            env = os.environ.copy()
            env.update(
                {
                    "CUDA_VISIBLE_DEVICES": gpu,
                    "OMP_NUM_THREADS": "2",
                    "MKL_NUM_THREADS": "2",
                    "OPENBLAS_NUM_THREADS": "2",
                    "NUMEXPR_NUM_THREADS": "2",
                }
            )
            log_handle = (logs / f"igfold_shard_{shard}.log").open("wb")
            process = subprocess.Popen(
                [
                    str(IGFOLD_PYTHON),
                    str(script_root / "run_igfold_shard.py"),
                    "--manifest",
                    str(project / "manifests" / "top200_structure_manifest.tsv"),
                    "--project",
                    str(project),
                    "--shard",
                    str(shard),
                    "--models",
                    "1",
                ],
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                env=env,
            )
            processes.append((shard, process, log_handle))
        failures: list[dict[str, int]] = []
        for shard, process, log_handle in processes:
            return_code = process.wait()
            log_handle.close()
            if return_code:
                failures.append({"shard": shard, "return_code": return_code})
        if failures:
            raise RuntimeError(f"IgFold shard failures: {failures}")

        with (logs / "analysis.log").open("w") as log:
            subprocess.run(
                [
                    str(BOLTZ_PYTHON),
                    str(script_root / "analyze_top200_structure_consistency.py"),
                    "--project",
                    str(project),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )

        with (
            project / "reports" / "TOP200_STRUCTURE_CONSISTENCY_SUMMARY.json"
        ).open() as handle:
            summary = json.load(handle)
        state.update(
            {
                "state": "COMPLETE",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "nanonet_count": count_nanonet(project),
                "summary": summary,
            }
        )
        write_json(project / "STATUS.json", state)
        (project / "COMPLETE").write_text(
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
