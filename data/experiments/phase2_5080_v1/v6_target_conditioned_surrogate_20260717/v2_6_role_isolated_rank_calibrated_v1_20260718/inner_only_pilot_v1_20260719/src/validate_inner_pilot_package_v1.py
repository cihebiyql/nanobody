#!/usr/bin/env python3
"""Static audit for the V2.6 unresolved inner-pilot skeleton package."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


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


def load(path: Path) -> dict:
    require(path.is_file() and not path.is_symlink(), f"not_regular:{path}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"not_object:{path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    args = parser.parse_args()
    manifest = load(args.package_root / "PACKAGE_MANIFEST.json")
    bundle = args.package_root / "node1_bundle"
    require(manifest.get("status") == "PASS_IMMUTABLE_NONLAUNCHING_SKELETON_BUILT", "manifest_status")
    require(manifest.get("launch_authorized") is False and manifest.get("launchable") is False, "manifest_launchability")
    require(manifest.get("training_or_prediction_executed") is False, "manifest_execution")
    require(manifest.get("integration_v1_forbidden") is True, "integration_v1_not_forbidden")
    for relative, expected in manifest["files"].items():
        path = bundle / relative
        require(path.is_file() and not path.is_symlink(), f"package_file_not_regular:{relative}")
        require(sha256_file(path) == expected, f"package_file_hash:{relative}")
    graph_path = bundle / "plan" / "PILOT_JOB_GRAPH_TEMPLATE.json"
    require(sha256_file(graph_path) == manifest["job_graph_template_sha256"], "graph_manifest_hash")
    graph = load(graph_path)
    require(graph.get("status") == "FROZEN_UNRESOLVED_NONLAUNCHING_TEMPLATE", "graph_status")
    require(graph.get("execution_authorized") is False and graph.get("launchable") is False, "graph_launchability")
    jobs = graph.get("jobs")
    require(isinstance(jobs, list) and len(jobs) == 9, "job_count")
    require(len({job["job_id"] for job in jobs}) == 9, "job_id_duplicate")
    counts = Counter(job["kind"] for job in jobs)
    require(counts == Counter({"GPU_INNER_PILOT": 8, "CPU_INNER_METRICS_COLLECT": 1}), "job_kind_counts")
    gpu_jobs = [job for job in jobs if job["kind"] == "GPU_INNER_PILOT"]
    expected = [
        ("F0_SHARED_GATED_NO_RANK", 43, 1, "cuda:0", 0.0),
        ("F0_SHARED_GATED_NO_RANK", 97, 2, "cuda:1", 0.0),
        ("F0_SHARED_GATED_NO_RANK", 193, 4, "cuda:2", 0.0),
        ("F1_SHARED_GATED_V4D_EXACT_MIN_RANK", 43, 5, "cuda:3", 0.1),
        ("F1_SHARED_GATED_V4D_EXACT_MIN_RANK", 97, 1, "cuda:0", 0.1),
        ("F1_SHARED_GATED_V4D_EXACT_MIN_RANK", 193, 2, "cuda:1", 0.1),
        ("B_SCALAR_ATTENTION_ONLY", 43, 4, "cuda:2", 0.0),
        ("E_STRICT_DETACHED_DYNAMICS_CONTROL", 43, 5, "cuda:3", 0.0),
    ]
    observed = [(job["variant"], job["seed"], job["physical_gpu"], job["logical_device"], job["rank_lambda"]) for job in gpu_jobs]
    require(observed == expected, "pilot_matrix_or_gpu_mapping")
    for job in gpu_jobs:
        require(job.get("command") is None, "unresolved_gpu_job_has_command")
        require(job.get("cuda_visible_devices") == "1,2,4,5", "job_cuda_visible_devices")
        require(job.get("outer_fold") == 0 and job.get("inner_fold") == 0, "job_split")
        require(len(job.get("required_artifacts", [])) == 5, "job_artifact_contract")
    collector = [job for job in jobs if job["kind"] == "CPU_INNER_METRICS_COLLECT"][0]
    require(collector.get("command") is None, "unresolved_collector_has_command")
    require(set(collector["dependencies"]) == {job["job_id"] for job in gpu_jobs}, "collector_dependency_closure")
    resources = graph["resources"]
    require(resources["physical_gpu_allowlist"] == [1, 2, 4, 5], "gpu_allowlist")
    require(resources["physical_to_logical_cuda_map"] == {"1": "cuda:0", "2": "cuda:1", "4": "cuda:2", "5": "cuda:3"}, "gpu_map")
    external = load(bundle / "contracts" / "EXTERNAL_INPUT_BINDINGS.json")
    require(external.get("status") == "FROZEN_OUTER0_INNER0_ONLY", "external_status")
    require(external.get("count") == 11 and len(external.get("files", [])) == 11, "external_count")
    for row in external["files"]:
        lowered = row["path"].lower()
        require("v4_f" not in lowered and "test32" not in lowered, "external_sealed")
        require(not any(f"outer_{fold}" in lowered for fold in (1, 2, 3, 4)), "external_other_outer_fold")
    contract = load(bundle / "contracts" / "INNER_PILOT_CONTRACT_V1.json")
    require(contract.get("status", "").startswith("FROZEN_NONLAUNCHING_BLOCKED"), "contract_status")
    require(contract["known_blocked_integration_v1"]["integration_v1_forbidden"] is True, "contract_v1_forbidden")
    require(contract["required_future_bindings"]["integration_v1_1"].startswith("UNRESOLVED"), "future_integration_not_unresolved")
    for field in ("outer_test_truth_access_count", "outer_metrics_access_count", "v4_f_test32_access_count"):
        require(graph.get(field) == 0 and manifest.get(field) == 0, f"firewall_nonzero:{field}")
    print(
        json.dumps(
            {
                "status": "PASS_IMMUTABLE_NONLAUNCHING_SKELETON_AUDIT",
                "jobs": 9,
                "gpu_jobs": 8,
                "launchable": False,
                "external_bindings": 11,
                "job_graph_template_sha256": manifest["job_graph_template_sha256"],
                "v4_f_test32_access_count": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
