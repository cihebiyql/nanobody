#!/usr/bin/env python3
"""Build a non-launching Node1 package for V2.5 real outer0/inner0 smoke."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
SCHEMA_VERSION = "pvrig_v2_5_ortho_node1_smoke_package_v1"
CLAIM_BOUNDARY = (
    "Open-only computational surrogate of independent 8X6B/9E6Y Docking geometry; "
    "not binding probability, affinity, experimental blocking, Docking Gold, or submission evidence."
)
LANES = {
    "B_CLEAN_TARGET_ATTENTION": {"model_lane": "B_CLEAN_TARGET_ATTENTION", "encoder_gradient": "detached", "marginal": 0.0, "pair": 0.0, "gpu": 2},
    "E_DECOUPLED_CONTACT_DETACHED": {"model_lane": "E_DECOUPLED_CONTACT", "encoder_gradient": "detached", "marginal": 1.0, "pair": 0.5, "gpu": 4},
    "E_DECOUPLED_CONTACT_SHARED": {"model_lane": "E_DECOUPLED_CONTACT", "encoder_gradient": "shared", "marginal": 1.0, "pair": 0.5, "gpu": 5},
}
REMOTE_PACKAGE_ROOT = "/data1/qlyu/projects/pvrig_v2_5_ortho_heads_smoke_package_v1_20260718"
REMOTE_RUNTIME_ROOT = "/data1/qlyu/projects/pvrig_v2_5_ortho_heads_smoke_runtime_v1_20260718"
REMOTE_SOURCE_ROOT = "/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_2_1_20260718"
REMOTE_V24_ADAPTER = "/data1/qlyu/projects/pvrig_v6_residue_v2_4_deployment_bundle_v2_2_2_20260718/src/train_v2_4_base_split.py"
REMOTE_V23_BUNDLE = "/data1/qlyu/projects/pvrig_v6_residue_v2_3_deployment_bundle_v1_20260718"
REMOTE_TARGET_GRAPH = "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graphs_v2.pt"
REMOTE_PYTHON = "/data1/qlyu/software/envs/pvrig-v6-tc/bin/python"
REMOTE_ESM2 = "/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c"
REMOTE_ESM2_IDENTITY = f"{REMOTE_ESM2}/model.safetensors"
ESM2_SHA256 = "a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0"
V24_ADAPTER_SHA256 = "59245b7aa28c14e9134f15fa1c2f4717e3a3b3a7c3e044a4d7cda06afc1c685f"
TARGET_GRAPH_SHA256 = "59461f9d48e5995acd902ba8524caad5c779a3c8b54a5deee121f9c3be6adfbc"
CONTACT_FORMULA_SHA256 = "7abe8e845b33ef7c77a61397a826fb3e6f94fb34122b7abbc2ddbd77c6db2ec7"


class PackageBuildError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PackageBuildError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reject_sealed(value: Any) -> None:
    strings: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            strings.append(item)
        elif isinstance(item, Mapping):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)

    visit(value)
    for string in strings:
        normalized = string.lower().replace("-", "_")
        require("v4_f" not in normalized and "test32" not in normalized, "sealed_reference_forbidden")


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def read_candidate_ids(path: Path, *, id_column: str = "candidate_id") -> set[str]:
    require(id_column in {"candidate_id", "entity_id"}, f"unsupported_id_column:{id_column}")
    if path.suffix == ".gz":
        handle_context = gzip.open(path, mode="rt", newline="", encoding="utf-8-sig")
    else:
        handle_context = path.open(newline="", encoding="utf-8-sig")
    with handle_context as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None and id_column in reader.fieldnames, f"{id_column}_column_missing:{path}")
        values = [row[id_column] for row in reader]
    require(bool(values), f"candidate_rows_invalid:{path}")
    if "training" in path.name or id_column == "entity_id":
        require(len(values) == len(set(values)), f"candidate_ids_not_unique:{path}")
    return set(values)


def canonical_source_paths(source_root: Path) -> dict[str, Path]:
    base = source_root / "node1_bundle"
    return {
        "training_tsv": base / "inputs/split_training/outer_0_inner_0.tsv",
        "marginal_contact": base / "inputs/split_contacts/outer_0_inner_0.marginal.tsv.gz",
        "pair_contact": base / "inputs/split_contacts/outer_0_inner_0.pair.tsv.gz",
        "graph_manifest": base / "inputs/split_graphs/outer_0_inner_0/graph_manifest_v2.tsv",
        "graph_receipt": base / "inputs/split_graphs/outer_0_inner_0/graph_cache_receipt_v2.json",
        "graph_cache": base / "inputs/split_graphs/outer_0_inner_0/graph_cache_v2.npz",
        "split_manifest": base / "plan/trainer_splits/outer_0_inner_0.json",
        "contact_formula": base / "inputs/contact_score_formula_v1.json",
    }


def source_sha256_manifest(source_root: Path) -> dict[str, str]:
    path = source_root / "SHA256SUMS"
    require(path.is_file() and not path.is_symlink(), "source_sha256s_missing")
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        digest, relative = line.split("  ", 1)
        require(len(digest) == 64 and relative not in result, f"source_sha256s_invalid:{relative}")
        result[relative] = digest
    return result


def validate_source(source_root: Path) -> dict[str, Any]:
    paths = canonical_source_paths(source_root)
    source_hashes = source_sha256_manifest(source_root)
    for name, path in paths.items():
        require(path.is_file() and not path.is_symlink(), f"source_input_missing_or_symlink:{name}:{path}")
        relative = str(path.relative_to(source_root))
        require(source_hashes.get(relative) == sha256_file(path), f"source_package_sha256:{name}")
    split = json.loads(paths["split_manifest"].read_text())
    require(split.get("split_id") == "outer_0_inner_0" and split.get("outer_fold") == 0, "split_identity")
    require(split.get("open_only") is True and split.get("v4_f_test32_access_count") == 0, "split_not_open_only")
    require(split.get("fixed_epochs") == 8, "source_fixed_epochs_changed")
    actual_training_sha256 = sha256_file(paths["training_tsv"])
    declared_training_sha256 = str(split.get("training_tsv_sha256") or "")
    training = read_candidate_ids(paths["training_tsv"])
    marginal = read_candidate_ids(paths["marginal_contact"])
    pair = read_candidate_ids(paths["pair_contact"])
    graphs = read_candidate_ids(paths["graph_manifest"], id_column="entity_id")
    require(training == marginal == pair == graphs, "training_contact_graph_candidate_closure")
    with paths["training_tsv"].open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    parents = {row["parent_framework_cluster"] for row in rows}
    train_parents, score_parents = set(split["train_parents"]), set(split["score_parents"])
    require(parents == train_parents | score_parents and train_parents.isdisjoint(score_parents), "parent_split_closure")
    train_count = sum(row["parent_framework_cluster"] in train_parents for row in rows)
    score_count = sum(row["parent_framework_cluster"] in score_parents for row in rows)
    require((len(rows), len(parents), train_count, score_count) == (1269, 28, 1085, 184), "frozen_smoke_counts")
    require(sha256_file(paths["contact_formula"]) == CONTACT_FORMULA_SHA256, "contact_formula_hash")
    return {
        "paths": {name: str(path.resolve()) for name, path in paths.items()},
        "hashes": {name: sha256_file(path) for name, path in paths.items()},
        "split_training_hash_reconciliation": {
            "actual_subset_sha256": actual_training_sha256,
            "split_manifest_declared_sha256": declared_training_sha256,
            "matches": actual_training_sha256 == declared_training_sha256,
            "authority": "source_package_SHA256SUMS_plus_candidate_parent_semantic_closure",
            "note": "V1.2.1 subset recovery retained the earlier split metadata hash; actual subset bytes are independently package-hash bound.",
        },
        "counts": {"rows": 1269, "parents": 28, "train_rows": 1085, "score_rows": 184},
        "split": split,
    }


def remote_input_paths() -> dict[str, str]:
    return {
        "training_tsv": f"{REMOTE_SOURCE_ROOT}/inputs/split_training/outer_0_inner_0.tsv",
        "marginal_contact": f"{REMOTE_SOURCE_ROOT}/inputs/split_contacts/outer_0_inner_0.marginal.tsv.gz",
        "pair_contact": f"{REMOTE_SOURCE_ROOT}/inputs/split_contacts/outer_0_inner_0.pair.tsv.gz",
        "graph_cache_dir": f"{REMOTE_SOURCE_ROOT}/inputs/split_graphs/outer_0_inner_0",
        "split_manifest": f"{REMOTE_SOURCE_ROOT}/plan/trainer_splits/outer_0_inner_0.json",
        "contact_formula": f"{REMOTE_SOURCE_ROOT}/inputs/contact_score_formula_v1.json",
    }


def command_template(lane: str, mode: str, output_dir: str) -> list[str]:
    inputs = remote_input_paths()
    return [
        REMOTE_PYTHON,
        f"{REMOTE_PACKAGE_ROOT}/src/run_real1507_split_v1.py",
        "--mode", mode,
        "--lane-variant", lane,
        "--output-dir", output_dir,
        "--v2-4-adapter-path", REMOTE_V24_ADAPTER,
        "--expected-v2-4-adapter-sha256", V24_ADAPTER_SHA256,
        "--v2-3-bundle-root", REMOTE_V23_BUNDLE,
        "--training-tsv", inputs["training_tsv"],
        "--contact-tsv-gz", inputs["marginal_contact"],
        "--pair-contact-tsv-gz", inputs["pair_contact"],
        "--graph-cache-dir", inputs["graph_cache_dir"],
        "--target-graph-pt", REMOTE_TARGET_GRAPH,
        "--contact-formula-json", inputs["contact_formula"],
        "--split-manifest", inputs["split_manifest"],
        "--model-path", REMOTE_ESM2,
        "--model-identity-file", REMOTE_ESM2_IDENTITY,
        "--expected-model-sha256", ESM2_SHA256,
        "--device", "cuda",
        "--expected-rows", "1269",
        "--expected-parents", "28",
        "--expected-train-rows", "1085",
        "--expected-score-rows", "184",
    ]


def build_job_plan() -> dict[str, Any]:
    jobs = []
    for lane, spec in LANES.items():
        pre_id = f"{lane}.preoptimizer"
        pre_output = f"{REMOTE_RUNTIME_ROOT}/preoptimizer/{lane}"
        smoke_output = f"{REMOTE_RUNTIME_ROOT}/one_epoch_smoke/{lane}"
        jobs.append(
            {
                "job_id": pre_id,
                "kind": "GPU_REAL_PREOPTIMIZER_NO_OPTIMIZER",
                "lane": lane,
                "physical_gpu": spec["gpu"],
                "dependencies": [],
                "command": None,
                "command_template": command_template(lane, "preoptimizer", pre_output),
                "expected_result": f"{pre_output}/RESULT.json",
            }
        )
        jobs.append(
            {
                "job_id": f"{lane}.one_epoch_smoke",
                "kind": "GPU_REAL_ONE_EPOCH_TECHNICAL_SMOKE",
                "lane": lane,
                "physical_gpu": spec["gpu"],
                "dependencies": [pre_id],
                "command": None,
                "command_template": command_template(lane, "train-smoke", smoke_output),
                "expected_result": f"{smoke_output}/RESULT.json",
            }
        )
    plan = {
        "schema_version": "pvrig_v2_5_ortho_node1_smoke_nonlaunching_plan_v1",
        "status": "PASS_DRY_RUN_NOT_AUTHORIZED_NOT_LAUNCHED",
        "launch_authorized": False,
        "training_or_prediction_executed": False,
        "outer_fold": 0,
        "inner_fold": 0,
        "lanes": LANES,
        "job_count": len(jobs),
        "resources": {"physical_gpus": [2, 4, 5], "cpu_threads_per_job_max": 8},
        "jobs": jobs,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    reject_sealed(plan)
    require(all(job["command"] is None for job in jobs), "dry_plan_command_not_null")
    return plan


def build_package(output_dir: Path, source_root: Path) -> dict[str, Any]:
    require(not output_dir.exists(), f"output_exists:{output_dir}")
    source = validate_source(source_root)
    output_dir.mkdir(parents=True)
    src = output_dir / "src"
    src.mkdir()
    copies = {
        ROOT / "model/residue_model_v2_5_ortho.py": src / "residue_model_v2_5_ortho.py",
        ROOT / "trainer/train_v2_5_ortho_heads.py": src / "train_v2_5_ortho_heads.py",
        ROOT / "real1507/run_real1507_split_v1.py": src / "run_real1507_split_v1.py",
    }
    for source_path, target_path in copies.items():
        require(source_path.is_file(), f"source_code_missing:{source_path}")
        shutil.copy2(source_path, target_path)
    plan = build_job_plan()
    atomic_json(output_dir / "NONLAUNCHING_JOB_PLAN.json", plan)
    input_contract = {
        "schema_version": "pvrig_v2_5_ortho_outer0_inner0_input_contract_v1",
        "source_local_package": str(source_root.resolve()),
        "source_local_evidence": source,
        "remote_source_root": REMOTE_SOURCE_ROOT,
        "remote_inputs": remote_input_paths(),
        "external_code_and_model_hashes": {
            "v2_4_adapter": V24_ADAPTER_SHA256,
            "target_graphs_v2_pt": TARGET_GRAPH_SHA256,
            "esm2_650m_model_safetensors": ESM2_SHA256,
        },
        "training_contact_graph_candidate_closure": True,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    reject_sealed(input_contract)
    atomic_json(output_dir / "INPUT_CONTRACT.json", input_contract)
    code_hashes = {path.name: sha256_file(path) for path in src.iterdir() if path.is_file()}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_BUILD_TEST_DRY_RUN_NOT_DEPLOYED_NOT_LAUNCHED",
        "launch_authorized": False,
        "training_or_prediction_executed": False,
        "node1_package_root": REMOTE_PACKAGE_ROOT,
        "node1_runtime_root": REMOTE_RUNTIME_ROOT,
        "source_code_sha256": code_hashes,
        "job_plan": {
            "path": "NONLAUNCHING_JOB_PLAN.json",
            "sha256": sha256_file(output_dir / "NONLAUNCHING_JOB_PLAN.json"),
            "jobs": 6,
        },
        "input_contract": {
            "path": "INPUT_CONTRACT.json",
            "sha256": sha256_file(output_dir / "INPUT_CONTRACT.json"),
        },
        "fixed_lane_comparison": LANES,
        "preoptimizer_before_smoke": True,
        "one_epoch_smoke_only": True,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    reject_sealed(manifest)
    atomic_json(output_dir / "PACKAGE_MANIFEST.json", manifest)
    files = sorted(path for path in output_dir.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
    (output_dir / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path.relative_to(output_dir)}\n" for path in files)
    )
    return manifest


def audit_package(package_root: Path) -> dict[str, Any]:
    manifest = json.loads((package_root / "PACKAGE_MANIFEST.json").read_text())
    plan = json.loads((package_root / "NONLAUNCHING_JOB_PLAN.json").read_text())
    contract = json.loads((package_root / "INPUT_CONTRACT.json").read_text())
    require(manifest["launch_authorized"] is False, "manifest_authorized")
    require(plan["launch_authorized"] is False and plan["job_count"] == 6, "plan_authorized_or_count")
    require(set(plan["lanes"]) == set(LANES), "lane_set")
    require(all(job["command"] is None for job in plan["jobs"]), "command_not_null")
    require(sum(job["kind"].endswith("PREOPTIMIZER_NO_OPTIMIZER") for job in plan["jobs"]) == 3, "preoptimizer_count")
    require(sum("ONE_EPOCH" in job["kind"] for job in plan["jobs"]) == 3, "smoke_count")
    for lane in LANES:
        smoke = next(job for job in plan["jobs"] if job["job_id"] == f"{lane}.one_epoch_smoke")
        require(smoke["dependencies"] == [f"{lane}.preoptimizer"], f"smoke_dependency:{lane}")
    require(contract["training_contact_graph_candidate_closure"] is True, "input_closure")
    require(manifest["v4_f_test32_access_count"] == plan["v4_f_test32_access_count"] == contract["v4_f_test32_access_count"] == 0, "sealed_access")
    reject_sealed({"manifest": manifest, "plan": plan, "contract": contract})
    for name, expected in manifest["source_code_sha256"].items():
        require(sha256_file(package_root / "src" / name) == expected, f"source_hash:{name}")
    listed = {}
    for line in (package_root / "SHA256SUMS").read_text().splitlines():
        digest, relative = line.split("  ", 1)
        listed[relative] = digest
    actual_files = sorted(path for path in package_root.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
    require(set(listed) == {str(path.relative_to(package_root)) for path in actual_files}, "sha_file_closure")
    for path in actual_files:
        relative = str(path.relative_to(package_root))
        require(sha256_file(path) == listed[relative], f"sha_mismatch:{relative}")
    return {
        "schema_version": "pvrig_v2_5_ortho_node1_smoke_package_audit_v1",
        "status": "PASS_NONLAUNCHING_PACKAGE_AUDIT",
        "checked_files": len(actual_files),
        "jobs": 6,
        "launch_authorized": False,
        "training_or_prediction_executed": False,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--source-package-root", type=Path, required=True)
    value.add_argument("--audit-only", action="store_true")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    result = audit_package(args.output_dir) if args.audit_only else build_package(args.output_dir, args.source_package_root)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
