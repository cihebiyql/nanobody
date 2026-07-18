#!/usr/bin/env python3
"""Fail-closed Node1 resource/input preflight for a future Residue V2.4 run.

This draft has no training mode.  It never creates the runtime root and does
not materialize trainer commands before a separate V2.4 implementation freeze
binds the code, arguments, and open-input manifest.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
from collections import Counter
from typing import Any


BUNDLE_ROOT = pathlib.Path("/data1/qlyu/projects/pvrig_v6_residue_v2_4_deployment_bundle_v1_20260718")
RUNTIME_ROOT = pathlib.Path("/data1/qlyu/projects/pvrig_v6_residue_v2_4_four_lane_oof_v1_20260718")
FIXED_PYTHON = pathlib.Path("/data1/qlyu/software/envs/pvrig-v6-tc/bin/python")
FUTURE_FREEZE = BUNDLE_ROOT / "residue_v2/IMPLEMENTATION_FREEZE_V2_4.json"
LANE_GPU = {"A_DOMAIN": 1, "B_VHH3D": 2, "C_PATCH": 4, "D_FULL_PAIR": 5}
AUGMENTATION_GPU = 6
FORBIDDEN_GPUS = (0, 3)
RESERVED_GPUS = (7,)
CPU_THREADS_PER_PROCESS = 8
TOTAL_TRAINING_CPU_CAP = 32
MIN_FREE_GIB = 200
MIN_AVAILABLE_MEMORY_GIB = 128
MAX_ASSIGNED_GPU_MEMORY_MIB = 512
MAX_ASSIGNED_GPU_UTILIZATION = 5


class DraftPreflightError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DraftPreflightError(message)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path: pathlib.Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"manifest_missing_or_symlink:{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(payload.get("status") == "DRAFT_OPEN_INPUT_CLOSURE_DO_NOT_TRAIN", "manifest_status")
    require(payload.get("teacher_source_is_model_feature") is False, "teacher_source_feature_boundary")
    require(payload.get("prediction_metrics_access_count") == 0, "prediction_metric_access")
    require(payload.get("sealed_evaluation_access_count") == 0, "sealed_evaluation_access")
    return payload


def verify_open_inputs(manifest: dict[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for label, record in sorted(manifest["inputs"].items()):
        path = pathlib.Path(record["path"])
        require(path.is_file() and not path.is_symlink(), f"input_missing_or_symlink:{label}:{path}")
        digest = sha256_file(path)
        require(digest == record["sha256"], f"input_sha_mismatch:{label}:{digest}")
        observed[label] = digest
    training_path = pathlib.Path(manifest["inputs"]["training_tsv"]["path"])
    with training_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    expected = manifest["expected_training_counts"]
    require(len(rows) == expected["rows"], "training_row_count")
    require(len({row["candidate_id"] for row in rows}) == expected["unique_candidates"], "training_candidate_count")
    require(
        len({row["parent_framework_cluster"] for row in rows}) == expected["unique_parent_framework_clusters"],
        "training_parent_count",
    )
    sources = dict(sorted(Counter(row["teacher_source"] for row in rows).items()))
    require(sources == expected["teacher_sources"], f"training_source_counts:{sources}")
    return observed


def gpu_inventory() -> list[dict[str, Any]]:
    output = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        text=True,
    )
    rows: list[dict[str, Any]] = []
    for line in output.splitlines():
        index, uuid, name, total, used, free, utilization = [part.strip() for part in line.split(",")]
        rows.append(
            {
                "index": int(index),
                "uuid": uuid,
                "name": name,
                "memory_total_mib": int(total),
                "memory_used_mib": int(used),
                "memory_free_mib": int(free),
                "utilization_percent": int(utilization),
            }
        )
    return rows


def gpu_process_uuids() -> set[str]:
    command = [
        "nvidia-smi",
        "--query-compute-apps=gpu_uuid",
        "--format=csv,noheader,nounits",
    ]
    output = subprocess.run(command, text=True, capture_output=True, check=False)
    return {line.strip() for line in output.stdout.splitlines() if line.strip()}


def available_memory_gib() -> float:
    for line in pathlib.Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 1024 / 1024
    raise DraftPreflightError("memavailable_missing")


def plan() -> dict[str, Any]:
    return {
        "schema_version": "pvrig_v6_residue_v2_4_node1_four_lane_draft_v1",
        "status": "DRAFT_PLAN_DO_NOT_TRAIN",
        "bundle_root": str(BUNDLE_ROOT),
        "runtime_root": str(RUNTIME_ROOT),
        "future_freeze": str(FUTURE_FREEZE),
        "fixed_python": str(FIXED_PYTHON),
        "lane_gpu_map": LANE_GPU,
        "augmentation_gpu": AUGMENTATION_GPU,
        "forbidden_gpus": list(FORBIDDEN_GPUS),
        "reserved_gpus": list(RESERVED_GPUS),
        "cpu_threads_per_process": CPU_THREADS_PER_PROCESS,
        "total_training_cpu_cap": TOTAL_TRAINING_CPU_CAP,
        "minimum_free_gib": MIN_FREE_GIB,
        "runtime_must_be_absent_before_formal_launch": True,
        "future_launcher_contract": "four lanes run concurrently; five outer folds are sequential within each lane; collectors start only after all five lane folds pass",
        "training_mode_available_in_this_draft": False,
        "prediction_metrics_access_count": 0,
        "sealed_evaluation_access_count": 0,
    }


def preflight(manifest_path: pathlib.Path) -> dict[str, Any]:
    require(BUNDLE_ROOT.is_dir() and not BUNDLE_ROOT.is_symlink(), "draft_bundle_root_missing_or_symlink")
    require(not RUNTIME_ROOT.exists(), f"runtime_root_must_remain_absent:{RUNTIME_ROOT}")
    # A Python executable inside a conda/venv environment is normally a
    # versioned symlink.  The future freeze must bind the environment identity;
    # this resource draft only requires the frozen path to resolve and execute.
    require(FIXED_PYTHON.is_file() and os.access(FIXED_PYTHON, os.X_OK), "fixed_python_missing_or_not_executable")
    require(os.cpu_count() is not None and os.cpu_count() >= 64, "cpu_count_below_64")
    memory_gib = available_memory_gib()
    require(memory_gib >= MIN_AVAILABLE_MEMORY_GIB, f"available_memory_below_{MIN_AVAILABLE_MEMORY_GIB}_gib")
    disk = shutil.disk_usage("/data1")
    free_gib = disk.free / 1024**3
    require(free_gib >= MIN_FREE_GIB, f"data1_free_space_below_{MIN_FREE_GIB}_gib")
    gpus = gpu_inventory()
    require(len(gpus) >= 8, "gpu_count_below_8")
    by_index = {row["index"]: row for row in gpus}
    active = gpu_process_uuids()
    for lane, index in LANE_GPU.items():
        require(index not in FORBIDDEN_GPUS and index not in RESERVED_GPUS, f"lane_gpu_policy:{lane}:{index}")
        row = by_index[index]
        require(row["uuid"] not in active, f"assigned_gpu_has_compute_process:{lane}:{index}")
        require(row["memory_used_mib"] <= MAX_ASSIGNED_GPU_MEMORY_MIB, f"assigned_gpu_memory_busy:{lane}:{index}")
        require(row["utilization_percent"] <= MAX_ASSIGNED_GPU_UTILIZATION, f"assigned_gpu_utilization_busy:{lane}:{index}")
    manifest = load_manifest(manifest_path)
    observed = verify_open_inputs(manifest)
    result = plan()
    result.update(
        {
            "status": "PASS_V2_4_RESOURCE_AND_OPEN_INPUT_PREFLIGHT_DO_NOT_TRAIN",
            "available_memory_gib": memory_gib,
            "data1_free_gib": free_gib,
            "assigned_gpu_snapshot": {lane: by_index[index] for lane, index in LANE_GPU.items()},
            "open_input_sha256": observed,
            "future_freeze_present": FUTURE_FREEZE.is_file(),
            "production_start_authorized": False,
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", action="store_true")
    group.add_argument("--preflight", action="store_true")
    parser.add_argument(
        "--manifest",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().with_name("V2_4_INPUT_MANIFEST_DRAFT.json"),
    )
    args = parser.parse_args()
    result = plan() if args.plan else preflight(args.manifest)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except DraftPreflightError as error:
        print(f"FAIL_V2_4_DRAFT_PREFLIGHT:{error}", file=os.sys.stderr)
        raise SystemExit(1)
