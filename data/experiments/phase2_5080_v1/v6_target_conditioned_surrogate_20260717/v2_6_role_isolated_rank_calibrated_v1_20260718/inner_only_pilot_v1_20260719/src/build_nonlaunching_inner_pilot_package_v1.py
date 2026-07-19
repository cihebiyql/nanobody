#!/usr/bin/env python3
"""Build the immutable, deliberately unresolved V2.6 inner-pilot skeleton.

The skeleton is not a runnable training package.  It freezes the eight GPU
jobs, evidence schema, resource mapping and the exact known input bindings.
The training command remains absent until a reviewed V1.1 integration and
CUDA driver are supplied by a separately SHA-bound authorization overlay.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


PHYSICAL_GPUS = (1, 2, 4, 5)
PHYSICAL_TO_LOGICAL = {1: "cuda:0", 2: "cuda:1", 4: "cuda:2", 5: "cuda:3"}
VARIANTS = (
    ("F0_SHARED_GATED_NO_RANK", "F_SHARED_GATED_CONTACT_TRANSFER", (43, 97, 193), 0.0),
    ("F1_SHARED_GATED_V4D_EXACT_MIN_RANK", "F_SHARED_GATED_CONTACT_TRANSFER", (43, 97, 193), 0.1),
    ("B_SCALAR_ATTENTION_ONLY", "B_SCALAR_ATTENTION_ONLY", (43,), 0.0),
    ("E_STRICT_DETACHED_DYNAMICS_CONTROL", "E_STRICT_DETACHED_DYNAMICS_CONTROL", (43,), 0.0),
)


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


def dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def select_external_bindings(path: Path) -> list[dict[str, str]]:
    source = json.loads(path.read_text())
    require(isinstance(source.get("files"), list), "external_binding_schema")
    exact_suffixes = (
        "/plan/trainer_splits/outer_0_inner_0.json",
        "/inputs/split_training/outer_0_inner_0.tsv",
        "/inputs/split_contacts/outer_0_inner_0.marginal.tsv.gz",
        "/inputs/split_contacts/outer_0_inner_0.pair.tsv.gz",
        "/inputs/split_graphs/outer_0_inner_0/graph_cache_receipt_v2.json",
        "/inputs/split_graphs/outer_0_inner_0/graph_cache_v2.npz",
        "/inputs/split_graphs/outer_0_inner_0/graph_manifest_v2.tsv",
        "/inputs/base_target_graphs/target_graphs_v2.pt",
        "/inputs/contact_score_formula_v1.json",
        "/src/train_v2_4_base_split.py",
        "/model.safetensors",
    )
    selected = [
        {"path": str(item["path"]), "sha256": str(item["sha256"])}
        for item in source["files"]
        if str(item["path"]).endswith(exact_suffixes)
    ]
    observed_suffixes = {suffix for suffix in exact_suffixes if any(row["path"].endswith(suffix) for row in selected)}
    require(observed_suffixes == set(exact_suffixes), "external_binding_selection_incomplete")
    require(len({row["path"] for row in selected}) == len(selected), "external_binding_duplicate")
    forbidden = ("v4_f", "test32", "/outer_0.tsv", "/outer_1", "/outer_2", "/outer_3", "/outer_4")
    require(not any(any(token in row["path"].lower() for token in forbidden) for row in selected), "forbidden_external_binding")
    return sorted(selected, key=lambda row: row["path"])


def build_job_graph(node_package_root: str, node_runtime_root: str) -> dict[str, Any]:
    jobs: list[dict[str, Any]] = []
    gpu_cursor = 0
    for variant, lane, seeds, rank_lambda in VARIANTS:
        for seed in seeds:
            physical = PHYSICAL_GPUS[gpu_cursor % len(PHYSICAL_GPUS)]
            logical = PHYSICAL_TO_LOGICAL[physical]
            gpu_cursor += 1
            job_id = f"outer0.inner0.{variant}.seed{seed}"
            output = f"{node_runtime_root}/gpu_jobs/{variant}/seed_{seed}"
            jobs.append(
                {
                    "job_id": job_id,
                    "kind": "GPU_INNER_PILOT",
                    "variant": variant,
                    "integration_lane": lane,
                    "outer_fold": 0,
                    "inner_fold": 0,
                    "seed": seed,
                    "rank_lambda": rank_lambda,
                    "physical_gpu": physical,
                    "logical_device": logical,
                    "cuda_visible_devices": "1,2,4,5",
                    "dependencies": [],
                    "command": None,
                    "command_contract": {
                        "driver": "REQUIRE_FUTURE_SHA_BOUND_V1_1_CUDA_DRIVER",
                        "device_argv": logical,
                        "fixed_epochs": 8,
                        "gradient_accumulation": 2,
                        "precision": "bf16",
                        "output_dir": output,
                    },
                    "output_dir": output,
                    "expected_result": f"{output}/RESULT.json",
                    "required_artifacts": [
                        "RESULT.json",
                        "TRAINING_RECEIPT.json",
                        "STEP_EVIDENCE.jsonl",
                        "neural_head.pt",
                        "score_predictions_no_metrics.tsv",
                    ],
                }
            )
    require(len(jobs) == 8, "gpu_job_count")
    collector_id = "outer0.inner0.collect_open_inner_metrics"
    collector_output = f"{node_runtime_root}/inner_metrics"
    jobs.append(
        {
            "job_id": collector_id,
            "kind": "CPU_INNER_METRICS_COLLECT",
            "outer_fold": 0,
            "inner_fold": 0,
            "dependencies": [job["job_id"] for job in jobs],
            "command": None,
            "command_contract": {
                "collector": f"{node_package_root}/node1_bundle/pilot/collect_inner_pilot_metrics_v1.py",
                "truth_role": "OPEN_INNER0_SCORE_PARENTS_ONLY",
                "outer_test_truth_access_count": 0,
            },
            "output_dir": collector_output,
            "expected_result": f"{collector_output}/RESULT.json",
        }
    )
    return {
        "schema_version": "pvrig_v2_6_inner_only_pilot_job_graph_template_v1",
        "status": "FROZEN_UNRESOLVED_NONLAUNCHING_TEMPLATE",
        "execution_authorized": False,
        "launchable": False,
        "unresolved_reason": "integration V1.1, CUDA driver, smoke PASS receipt and authorization overlay are not bound",
        "claim_boundary": "open-development inner-validation computational Docking-geometry surrogate only",
        "fixed_split": {"outer_fold": 0, "inner_fold": 0},
        "resources": {
            "physical_gpu_allowlist": list(PHYSICAL_GPUS),
            "cuda_visible_devices": "1,2,4,5",
            "physical_to_logical_cuda_map": {str(key): value for key, value in PHYSICAL_TO_LOGICAL.items()},
            "max_gpu_jobs": 4,
            "max_cpu_jobs": 1,
            "cpu_threads_per_job": 4,
        },
        "job_counts": {"GPU_INNER_PILOT": 8, "CPU_INNER_METRICS_COLLECT": 1, "TOTAL": 9},
        "jobs": jobs,
        "outer_test_truth_access_count": 0,
        "outer_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--v2-5-external-bindings", type=Path, required=True)
    parser.add_argument("--node-package-root", required=True)
    parser.add_argument("--node-runtime-root", required=True)
    args = parser.parse_args()

    require(not args.output_root.exists(), "output_root_exists")
    require("v4_f" not in args.node_package_root.lower() and "test32" not in args.node_package_root.lower(), "sealed_package_path")
    require("v4_f" not in args.node_runtime_root.lower() and "test32" not in args.node_runtime_root.lower(), "sealed_runtime_path")
    bundle = args.output_root / "node1_bundle"
    for subdir in ("contracts", "pilot", "plan"):
        (bundle / subdir).mkdir(parents=True, exist_ok=True)

    copied = (
        (args.source_root / "INNER_PILOT_CONTRACT_V1.json", bundle / "contracts" / "INNER_PILOT_CONTRACT_V1.json"),
        (args.source_root / "src" / "collect_inner_pilot_metrics_v1.py", bundle / "pilot" / "collect_inner_pilot_metrics_v1.py"),
        (args.source_root / "src" / "run_resolved_inner_pilot_job_graph_v1.py", bundle / "pilot" / "run_resolved_inner_pilot_job_graph_v1.py"),
        (args.source_root / "src" / "validate_inner_pilot_package_v1.py", bundle / "pilot" / "validate_inner_pilot_package_v1.py"),
    )
    for source, target in copied:
        require(source.is_file() and not source.is_symlink(), f"source_not_regular:{source}")
        shutil.copy2(source, target)

    external = select_external_bindings(args.v2_5_external_bindings)
    dump(
        bundle / "contracts" / "EXTERNAL_INPUT_BINDINGS.json",
        {
            "schema_version": "pvrig_v2_6_inner_pilot_external_input_bindings_v1",
            "status": "FROZEN_OUTER0_INNER0_ONLY",
            "files": external,
            "count": len(external),
            "outer_test_files_bound": 0,
            "v4_f_test32_access_count": 0,
        },
    )
    graph = build_job_graph(args.node_package_root, args.node_runtime_root)
    dump(bundle / "plan" / "PILOT_JOB_GRAPH_TEMPLATE.json", graph)

    files = {
        str(path.relative_to(bundle)): sha256_file(path)
        for path in sorted(bundle.rglob("*"))
        if path.is_file()
    }
    known_dependencies = {
        "v2_5_trainer_sha256": "af93c39054a1a73568a68d498406fb3eddbffe1d688c93e16f59319148e285b0",
        "v2_5_model_sha256": "26a193e7f854cdbce586c2fa89df947f0bd7218c3c675733c1724e7e7ee3c521",
        "v2_5_real1507_runner_sha256": "f7c4e813f19d9034a945982d029118dc87cc6c420f1f8c8cf898bfec74065b7f",
        "v2_6_role_optimizer_core_sha256": "2dadc945ec30eb802ca9f32fac84ce647783b9defc36db68f345fc00e972f363",
        "v2_6_rank_v1_1_core_sha256": "b420766a7769a546418a68367b71742eb3ea7872dd2411a48609139a985ef2ec",
        "v2_6_delta_noise_binding_sha256": "0a613b87509699a28d134c02514b1240e50a06a5aefddb5ca4a9d8202cde0a0c",
    }
    manifest = {
        "schema_version": "pvrig_v2_6_inner_only_pilot_skeleton_package_v1",
        "status": "PASS_IMMUTABLE_NONLAUNCHING_SKELETON_BUILT",
        "launch_authorized": False,
        "launchable": False,
        "training_or_prediction_executed": False,
        "node1_package_root": args.node_package_root,
        "node1_runtime_root": args.node_runtime_root,
        "job_graph_template_sha256": files["plan/PILOT_JOB_GRAPH_TEMPLATE.json"],
        "job_count": 9,
        "gpu_job_count": 8,
        "cpu_job_count": 1,
        "physical_gpus": list(PHYSICAL_GPUS),
        "known_dependency_hashes": known_dependencies,
        "future_bindings_resolved": False,
        "integration_v1_forbidden": True,
        "external_input_binding_count": len(external),
        "files": files,
        "outer_test_truth_access_count": 0,
        "outer_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
    }
    dump(args.output_root / "PACKAGE_MANIFEST.json", manifest)
    all_files = {
        str(path.relative_to(args.output_root)): sha256_file(path)
        for path in sorted(args.output_root.rglob("*"))
        if path.is_file()
    }
    (args.output_root / "SHA256SUMS").write_text(
        "".join(f"{digest}  {relative}\n" for relative, digest in sorted(all_files.items()))
    )
    print(json.dumps({"status": manifest["status"], "jobs": 9, "gpu_jobs": 8, "launchable": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
