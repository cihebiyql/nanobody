#!/usr/bin/env python3
"""Build the immutable, nonlaunching V2.5 causal-ablation plan package."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


INFERENCE_PERTURBATIONS = (
    "HOTSPOT_INTERFACE_MASK_SWAP",
    "RECEPTOR_CONFORMER_SWAP",
    "TARGET_RESIDUE_FEATURE_PERMUTATION",
)
OUTER_FOLDS = range(5)
INNER_FOLDS = range(5)
SEEDS = (43, 97, 193)
EXPECTED_LIVE_GRAPH_SHA = "ea1c4c1eedf189d9542e3e73b0c0368777b4073468fd4e39535b28fd7fa24185"
SEALED_TOKENS = ("v4_f", "v4-f", "test32", "sealed")


class BuildError(RuntimeError):
    pass


def require(value: bool, message: str) -> None:
    if not value:
        raise BuildError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def dump_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")


def reject_sealed_path(path: Path) -> None:
    lowered = str(path).casefold()
    require(not any(token in lowered for token in SEALED_TOKENS), f"sealed_path:{path}")


def _external_clean_outer(outer: int, seed: int) -> str:
    return f"formal_v1_3:E_DECOUPLED_CONTACT_SHARED:outer_{outer}:seed_{seed}:RESULT.json"


def _external_clean_selection(outer: int) -> str:
    return f"formal_v1_3:E_DECOUPLED_CONTACT_SHARED:outer_{outer}:SELECTION.json"


def build_job_graph() -> dict[str, Any]:
    jobs: list[dict[str, Any]] = []
    meta_jobs: list[str] = []

    for outer in OUTER_FOLDS:
        for perturbation in INFERENCE_PERTURBATIONS:
            inference_ids: list[str] = []
            for seed in SEEDS:
                job_id = f"o{outer}.{perturbation}.s{seed}.infer"
                inference_ids.append(job_id)
                jobs.append({
                    "job_id": job_id,
                    "kind": "GPU_INFERENCE_PERTURB",
                    "outer_fold": outer,
                    "seed": seed,
                    "perturbation": perturbation,
                    "dependencies": [],
                    "external_dependencies": [_external_clean_outer(outer, seed)],
                    "execution_authorized": False,
                    "runner_interface": "causal_inference_adapter_v1_REQUIRED_FUTURE_VERSION",
                })
            ensemble_id = f"o{outer}.{perturbation}.ensemble"
            jobs.append({
                "job_id": ensemble_id,
                "kind": "CPU_INFERENCE_ENSEMBLE",
                "outer_fold": outer,
                "perturbation": perturbation,
                "dependencies": inference_ids,
                "external_dependencies": [],
                "execution_authorized": False,
                "runner_interface": "causal_ensemble_adapter_v1_REQUIRED_FUTURE_VERSION",
            })
            meta_id = f"o{outer}.{perturbation}.nested_meta_evaluate"
            jobs.append({
                "job_id": meta_id,
                "kind": "CPU_NESTED_META_EVALUATE",
                "outer_fold": outer,
                "perturbation": perturbation,
                "dependencies": [ensemble_id],
                "external_dependencies": [
                    f"strict_meta_v1_1:outer_{outer}:PRETRUTH_PARAMETERS.json",
                ],
                "execution_authorized": False,
                "runner_interface": "causal_meta_evaluator_v1_REQUIRED_FUTURE_VERSION",
            })
            meta_jobs.append(meta_id)

        shuffle_inner_ids: list[str] = []
        for inner in INNER_FOLDS:
            job_id = f"o{outer}.CONTACT_LABEL_WITHIN_PARENT_DONOR_SHUFFLE.i{inner}.retrain"
            shuffle_inner_ids.append(job_id)
            jobs.append({
                "job_id": job_id,
                "kind": "GPU_CONTACT_SHUFFLE_INNER_RETRAIN",
                "outer_fold": outer,
                "inner_fold": inner,
                "seed": 43,
                "donor_seed": 1931,
                "perturbation": "CONTACT_LABEL_WITHIN_PARENT_DONOR_SHUFFLE",
                "dependencies": [],
                "external_dependencies": [_external_clean_selection(outer)],
                "execution_authorized": False,
                "runner_interface": "contact_donor_shuffle_training_adapter_v1_REQUIRED_FUTURE_VERSION",
            })
        shuffle_outer_ids: list[str] = []
        for seed in SEEDS:
            job_id = f"o{outer}.CONTACT_LABEL_WITHIN_PARENT_DONOR_SHUFFLE.s{seed}.outer_retrain"
            shuffle_outer_ids.append(job_id)
            jobs.append({
                "job_id": job_id,
                "kind": "GPU_CONTACT_SHUFFLE_OUTER_RETRAIN",
                "outer_fold": outer,
                "seed": seed,
                "donor_seed": 1931,
                "perturbation": "CONTACT_LABEL_WITHIN_PARENT_DONOR_SHUFFLE",
                "dependencies": [],
                "external_dependencies": [_external_clean_selection(outer)],
                "execution_authorized": False,
                "runner_interface": "contact_donor_shuffle_training_adapter_v1_REQUIRED_FUTURE_VERSION",
            })
        shuffle_ensemble = f"o{outer}.CONTACT_LABEL_WITHIN_PARENT_DONOR_SHUFFLE.ensemble"
        jobs.append({
            "job_id": shuffle_ensemble,
            "kind": "CPU_CONTACT_SHUFFLE_ENSEMBLE",
            "outer_fold": outer,
            "perturbation": "CONTACT_LABEL_WITHIN_PARENT_DONOR_SHUFFLE",
            "dependencies": shuffle_outer_ids,
            "external_dependencies": [],
            "execution_authorized": False,
            "runner_interface": "causal_ensemble_adapter_v1_REQUIRED_FUTURE_VERSION",
        })
        shuffle_meta = f"o{outer}.CONTACT_LABEL_WITHIN_PARENT_DONOR_SHUFFLE.nested_meta_evaluate"
        jobs.append({
            "job_id": shuffle_meta,
            "kind": "CPU_NESTED_META_EVALUATE",
            "outer_fold": outer,
            "perturbation": "CONTACT_LABEL_WITHIN_PARENT_DONOR_SHUFFLE",
            "dependencies": shuffle_inner_ids + [shuffle_ensemble],
            "external_dependencies": [],
            "execution_authorized": False,
            "runner_interface": "causal_meta_evaluator_v1_REQUIRED_FUTURE_VERSION",
        })
        meta_jobs.append(shuffle_meta)

        omit_meta = f"o{outer}.NO_CONTACT_META_EVIDENCE.nested_meta_evaluate"
        jobs.append({
            "job_id": omit_meta,
            "kind": "CPU_NESTED_META_EVALUATE",
            "outer_fold": outer,
            "perturbation": "NO_CONTACT_META_EVIDENCE",
            "dependencies": [],
            "external_dependencies": [
                f"strict_meta_v1_1:outer_{outer}:clean_inner_OOF_features",
                f"strict_meta_v1_1:outer_{outer}:clean_outer_predictions",
            ],
            "execution_authorized": False,
            "runner_interface": "causal_meta_evaluator_v1_REQUIRED_FUTURE_VERSION",
        })
        meta_jobs.append(omit_meta)

    jobs.append({
        "job_id": "causal_ablation.collect",
        "kind": "CPU_FINAL_COLLECT",
        "dependencies": meta_jobs,
        "external_dependencies": [],
        "execution_authorized": False,
        "runner_interface": "causal_final_collector_v1_REQUIRED_FUTURE_VERSION",
    })
    counts = Counter(job["kind"] for job in jobs)
    expected = Counter({
        "GPU_INFERENCE_PERTURB": 45,
        "CPU_INFERENCE_ENSEMBLE": 15,
        "GPU_CONTACT_SHUFFLE_INNER_RETRAIN": 25,
        "GPU_CONTACT_SHUFFLE_OUTER_RETRAIN": 15,
        "CPU_CONTACT_SHUFFLE_ENSEMBLE": 5,
        "CPU_NESTED_META_EVALUATE": 25,
        "CPU_FINAL_COLLECT": 1,
    })
    require(counts == expected and len(jobs) == 131, "causal_job_counts")
    return {
        "schema_version": "pvrig_v2_5_causal_ablation_nonlaunching_job_graph_v1",
        "status": "FROZEN_NONLAUNCHING_PLAN_ONLY",
        "execution_authorized": False,
        "training_or_prediction_executed": False,
        "live_301_job_graph_modified": False,
        "upstream_live_job_graph_sha256": EXPECTED_LIVE_GRAPH_SHA,
        "claim_boundary": "diagnostic open-development computational Docking-geometry causal sensitivity only",
        "resources_if_separately_authorized_in_a_future_version": {
            "physical_gpu_allowlist": [1, 2, 4, 5],
            "max_gpu_jobs": 4,
            "max_cpu_jobs": 2,
        },
        "job_counts": dict(counts) | {"GPU_TOTAL": 85, "CPU_TOTAL": 46, "TOTAL": 131},
        "v4_f_test32_access_count": 0,
        "jobs": jobs,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    source = args.source_root.resolve()
    output = args.output_root.resolve()
    reject_sealed_path(source)
    reject_sealed_path(output)
    require(not output.exists(), "output_exists")

    contract_path = source / "CAUSAL_ABLATION_CONTRACT_V1.json"
    contract = json.loads(contract_path.read_text())
    require(contract["status"] == "FROZEN_PRE_OUTER_RESULT_NONLAUNCHING", "contract_status")
    for binding in contract["upstream_bindings"].values():
        path = (source / binding["path"]).resolve()
        reject_sealed_path(path)
        require(path.is_file() and not path.is_symlink(), f"upstream_missing:{path}")
        require(sha256(path) == binding["sha256"], f"upstream_hash:{path}")
    live_graph = (source / contract["upstream_bindings"]["formal_job_graph"]["path"]).resolve()
    require(sha256(live_graph) == EXPECTED_LIVE_GRAPH_SHA, "live_graph_changed_before_build")

    (output / "src").mkdir(parents=True)
    shutil.copy2(contract_path, output / contract_path.name)
    for name in (
        "causal_perturbations_v1.py",
        "validate_causal_ablation_package_v1.py",
        "watch_formal_terminal_then_mark_ablation_ready_v1.py",
    ):
        shutil.copy2(source / "src" / name, output / "src" / name)
    dump_json(output / "ABLATION_JOB_GRAPH.json", build_job_graph())

    files = {
        str(path.relative_to(output)): sha256(path)
        for path in sorted(output.rglob("*")) if path.is_file()
    }
    manifest = {
        "schema_version": "pvrig_v2_5_causal_ablation_nonlaunching_package_v1",
        "status": "PASS_IMMUTABLE_NONLAUNCHING_PLAN_BUILT",
        "launch_authorized": False,
        "training_or_prediction_executed": False,
        "contract_sha256": files["CAUSAL_ABLATION_CONTRACT_V1.json"],
        "job_graph_sha256": files["ABLATION_JOB_GRAPH.json"],
        "upstream_live_job_graph_sha256": EXPECTED_LIVE_GRAPH_SHA,
        "upstream_live_job_graph_modified": False,
        "job_count": 131,
        "gpu_job_count": 85,
        "cpu_job_count": 46,
        "files": files,
        "v4_f_test32_access_count": 0,
    }
    dump_json(output / "PACKAGE_MANIFEST.json", manifest)
    sums = {
        str(path.relative_to(output)): sha256(path)
        for path in sorted(output.rglob("*")) if path.is_file()
    }
    (output / "SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(sums.items()))
    )
    require(sha256(live_graph) == EXPECTED_LIVE_GRAPH_SHA, "live_graph_changed_during_build")
    print(json.dumps({
        "status": "PASS_IMMUTABLE_NONLAUNCHING_PLAN_BUILT",
        "jobs": 131,
        "gpu_jobs": 85,
        "cpu_jobs": 46,
        "contract_sha256": manifest["contract_sha256"],
        "job_graph_sha256": manifest["job_graph_sha256"],
        "live_graph_modified": False,
        "v4_f_test32_access_count": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

