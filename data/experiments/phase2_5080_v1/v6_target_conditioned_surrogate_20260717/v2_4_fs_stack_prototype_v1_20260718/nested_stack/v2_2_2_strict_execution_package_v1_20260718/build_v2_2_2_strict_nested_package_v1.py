#!/usr/bin/env python3
"""Build an immutable, non-launching V2.2.2 strict nested-stack package.

This wrapper binds the post-calibration V2.2.2 evidence, adaptive contact
targets, canonical 1507-candidate whole-parent splits, Stage-1 V4H terminal
evidence, and the already implemented strict double-cross-fit DAG.  It does
not authorize or execute training.  The current ready manifest deliberately
has ``production_authorized=false`` and therefore every GPU command in the
materialized graph must remain null.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping


SCHEMA = "pvrig_v2_4_v2_2_2_strict_nested_execution_package_v1"
PACKAGE_STATUS = "PASS_AUDITED_DRY_RUN_NOT_AUTHORIZED_NOT_LAUNCHED"
GRAPH_STATUS = "DRY_RUN_PENDING_POSTCALIBRATION_FREEZE_DO_NOT_EXECUTE"
CLAIM_BOUNDARY = (
    "Open-only computational surrogate of independent 8X6B/9E6Y Docking "
    "geometry; not binding probability, affinity, experimental blocking, "
    "Docking Gold, or submission evidence."
)
GRAPH_CLAIM_BOUNDARY = (
    "Open-development computational surrogate of independent 8X6B/9E6Y "
    "Docking geometry; not binding probability, affinity, experimental "
    "blocking, Docking Gold, or submission evidence."
)

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
PHASE2 = ROOT.parents[1]
NESTED = ROOT / "nested_stack"
READY_DIR = ROOT / "deployment" / "prepared" / "node1_v2_2_2_ready_freeze_evidence_20260718"
SPLIT_DIR = ROOT / "split_contract" / "prepared" / "whole_parent_nested_splits_all_outer_seed1931_v3_parent_balanced_v2_4"
ADAPTIVE_DIR = PHASE2 / "prepared" / "pvrig_v2_4_adaptive_dual_targets_v1_20260718"
STAGE1_DIR = PHASE2 / "prepared" / "pvrig_v4_h_stage1_terminal_v1_20260717"
COARSE_DIR = ROOT.parent / "v2_5_coarse_pose_pilot_v1_20260718"

TRAINING = ROOT / "data_contract" / "materialized_v1" / "v6_supervised1507_v2_4.tsv"
OUTER = SPLIT_DIR / "outer_development_manifest.tsv"
INNER = SPLIT_DIR / "inner_nested_oof_manifest.tsv"
FORMULA = ROOT / "contact_contract" / "contact_score_formula_v1.json"
READY = READY_DIR / "V2_4_NODE1_READY_MANIFEST_V2_2_2.json"
PREFREEZE = READY_DIR / "V2_4_NODE1_PREFREEZE_MANIFEST_V2_2_2.json"
FREEZE = READY_DIR / "IMPLEMENTATION_FREEZE_V2_4_ADAPTIVE_V2_2_2.json"
CALIBRATION = READY_DIR / "CALIBRATION_RECEIPT.json"
BUNDLE_RECEIPT = READY_DIR / "BUNDLE_RECEIPT.json"
INDEPENDENT_AUDIT = READY_DIR / "POSTCALIBRATION_INDEPENDENT_AUDIT_V2_2_2.json"
ADAPTIVE_CONTRACT = ADAPTIVE_DIR / "ADAPTIVE_DUAL_SOURCE_INPUT_CONTRACT_V1.json"
ADAPTIVE_MARGINAL = ADAPTIVE_DIR / "marginal" / "v6_adaptive_dual_source_residue_contact_targets_v3.tsv.gz"
ADAPTIVE_PAIR = ADAPTIVE_DIR / "pair" / "v6_adaptive_dual_source_pair_contact_targets_v3.tsv.gz"
STAGE1_RECEIPT = STAGE1_DIR / "stage1_local_package_receipt.json"
STAGE1_RANKING = STAGE1_DIR / "stage1_seed917_ranking.tsv"
STAGE2_CANDIDATES = STAGE1_DIR / "stage2_selected_seed1931_candidates.tsv"

PLANNER = NESTED / "build_strict_nested_crossfit_plan_v1.py"
RUNNER = NESTED / "run_strict_nested_crossfit_graph_v1.py"
VALIDATOR = ROOT / "feature_contract" / "src" / "validate_receptor_compact_evidence_v2.py"
STACK_FITTER = ROOT / "src" / "fit_shared_nonnegative_stack_v2.py"

PACKAGE_NODE1_ROOT = "/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_package_v1_20260718"
RUNTIME_NODE1_ROOT = "/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_runtime_v1_20260718"

EXPECTED_HASHES = {
    READY: "c7c95697e40feffe6063f68daf2eabe6cc596f36f4547f563c96bdad973c6df2",
    PREFREEZE: "bbef3a0d4dc43f09ade77538b489b877945c59d4da78767f43febc463f2887d9",
    FREEZE: "d7c4975313c249e72e2490c85e545ae2ba8d03b0fd90d8b85cd82c23194f76fc",
    CALIBRATION: "ccd531b0c7d71665f285b1c438276907897481cc1faa923e9e795bbb00ecbc9a",
    BUNDLE_RECEIPT: "b0d9974a6d97c4487dffb5d72e86c076ae068db87f8934bb5d8e62a23987cd96",
    INDEPENDENT_AUDIT: "61d83f6497a176d5b99a7cc7b9455510cf21d49cc397ac1b73b6d152814f9929",
    TRAINING: "47c2c98fc282058e470ab0978b58daaf896262d593f017216cbc02cd5e6335e1",
    OUTER: "ce49916385ccb792b4b03dda72889ab8c72aaccd662ccfcdb1d30874bdd81e55",
    INNER: "b56cd47d2ea030cbf52cf2a966f503c1e5b8f9755329de62ad8e4343f32b6073",
    FORMULA: "7abe8e845b33ef7c77a61397a826fb3e6f94fb34122b7abbc2ddbd77c6db2ec7",
    ADAPTIVE_CONTRACT: "3c7b5b2148494e203ddbf17871ab12aca2d725e8e07f2e8e97074065f55a2382",
    ADAPTIVE_MARGINAL: "ed1d06b24e5315d2be38d55683f2bfadc5facd97a0086656ba3cc85e74ffcb28",
    ADAPTIVE_PAIR: "29783e9473862dacc92e4a31b99a9d2f8a6ecba125a7ffac9aebc44dfb91cd86",
    STAGE1_RECEIPT: "7140ccc86c68c8119a8fb61123b28aecd39eeffa8bf8b9ccb74f57a967ffa795",
    STAGE1_RANKING: "b1fdf2b74e1d9a34096c2ea57256fda1a9c28a32fcf6db70e21f1abc7bc1ed7d",
    STAGE2_CANDIDATES: "b728779b3e079870acc1dce0c830ece6774949f687270e04ce2354dc0f2297a1",
}

EXPECTED_LANE_WEIGHTS = {
    "B_TARGET_NO_CONTACT": (0.0, 0.0),
    "C_SPLIT_MARGINAL": (1.5, 0.0),
    "D_SPLIT_PAIR": (1.0, 0.5),
}
EXPECTED_GPU_MAP = {
    "B_TARGET_NO_CONTACT": 2,
    "C_SPLIT_MARGINAL": 4,
    "D_SPLIT_PAIR": 5,
}
EXPECTED_JOB_COUNTS = {
    "GPU_BASE_TRAIN_INNER": 75,
    "GPU_BASE_REFIT_OUTER_TRAIN": 15,
    "CPU_ASSEMBLE_INNER_OOF_BASE_FEATURE": 15,
    "CPU_VALIDATE_INNER_OOF_BASE_FEATURE": 15,
    "CPU_ASSEMBLE_OUTER_TEST_BASE_FEATURE": 15,
    "CPU_VALIDATE_OUTER_TEST_BASE_FEATURE": 15,
    "CPU_FIT_FIVE_PARAMETER_META": 15,
    "CPU_MATERIALIZE_OUTER_TEST_META_PREDICTION": 15,
    "CPU_VALIDATE_OUTER_TEST_META_PREDICTION": 15,
}


class PackageError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PackageError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"json_not_object:{path}")
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def argv_weights(tokens: list[str]) -> tuple[float, float]:
    require(tokens.count("--marginal-weight") == 1, "marginal_weight_argv_count")
    require(tokens.count("--pair-weight") == 1, "pair_weight_argv_count")
    return float(tokens[tokens.index("--marginal-weight") + 1]), float(tokens[tokens.index("--pair-weight") + 1])


def validate_lane_contract(ready: Mapping[str, Any]) -> None:
    lane_argv = (ready.get("trainer") or {}).get("lane_outer_extra_argv")
    require(isinstance(lane_argv, dict), "lane_outer_extra_argv_missing")
    for lane, expected in EXPECTED_LANE_WEIGHTS.items():
        require(lane in lane_argv, f"lane_argv_missing:{lane}")
        require(argv_weights(list(lane_argv[lane])) == expected, f"lane_weight_drift:{lane}")


def validate_inputs() -> dict[str, Any]:
    for path, expected in EXPECTED_HASHES.items():
        require(path.is_file(), f"missing_input:{path}")
        observed = sha256_file(path)
        require(observed == expected, f"sha256_mismatch:{path}:{observed}")

    ready = load_json(READY)
    require(ready.get("status") == "PREFREEZE_V2_2_2_ADAPTIVE_MULTI_SEED_READY_DO_NOT_START", "ready_status_drift")
    require(ready.get("production_authorized") is False, "unexpected_production_authorization")
    require(ready.get("claim_boundary") == (
        "Open-only adaptive-multiseed independent 8X6B/9E6Y computational Docking geometry surrogate; "
        "not binding, affinity, experimental blocking, Docking Gold, or submission evidence."
    ), "ready_claim_boundary_drift")
    require((ready.get("trainer") or {}).get("artifact_label") == "trainer", "trainer_artifact_label_drift")
    validate_lane_contract(ready)
    artifacts = ready.get("artifacts") or {}
    expected_artifacts = {
        "training_tsv": EXPECTED_HASHES[TRAINING],
        "adaptive_marginal_tsv_gz": EXPECTED_HASHES[ADAPTIVE_MARGINAL],
        "adaptive_pair_tsv_gz": EXPECTED_HASHES[ADAPTIVE_PAIR],
        "adaptive_input_contract": EXPECTED_HASHES[ADAPTIVE_CONTRACT],
        "contact_formula": EXPECTED_HASHES[FORMULA],
    }
    for name, expected in expected_artifacts.items():
        require((artifacts.get(name) or {}).get("sha256") == expected, f"ready_artifact_hash_drift:{name}")

    training_rows = read_tsv(TRAINING)
    require(len(training_rows) == 1507, "training_row_count_not_1507")
    sources = Counter(row["teacher_source"] for row in training_rows)
    require(sources == {"V4D_OPEN_MULTI_SEED": 226, "V4H_ADAPTIVE_SEED_RANKING": 1281}, f"teacher_source_counts:{sources}")
    v4h_candidates = {row["candidate_id"] for row in training_rows if row["teacher_source"] == "V4H_ADAPTIVE_SEED_RANKING"}
    stage1_rows = read_tsv(STAGE1_RANKING)
    require(len(stage1_rows) == 1320, "stage1_candidate_count_not_1320")
    stage1_analyzable = {row["candidate_id"] for row in stage1_rows if row["docking_evidence_tier"] == "DUAL_1_SEED"}
    stage1_incomplete = {row["candidate_id"] for row in stage1_rows if row["docking_evidence_tier"] == "TECHNICAL_INCOMPLETE"}
    require(len(stage1_analyzable) == 1281 and len(stage1_incomplete) == 39, "stage1_tier_counts_drift")
    require(v4h_candidates == stage1_analyzable, "v4h_training_not_exact_stage1_analyzable_set")
    stage2 = {row["candidate_id"] for row in read_tsv(STAGE2_CANDIDATES)}
    require(len(stage2) == 384 and stage2 <= stage1_analyzable, "stage2_selection_not_384_subset")
    receipt = load_json(STAGE1_RECEIPT)
    require(receipt.get("status") == "PASS_STAGE1_CORE_ARTIFACTS_LOCALLY_MATERIALIZED", "stage1_receipt_status")
    require(receipt.get("stage1_job_count") == 2640, "stage1_job_count")
    require(receipt.get("terminal_counts") == {"FAILED_MAX_ATTEMPTS": 4, "SUCCESS": 2636}, "stage1_terminal_counts")

    stack_text = STACK_FITTER.read_text(encoding="utf-8")
    for token in ("intercept_R8", "intercept_R9", "beta_M2", "beta_neural", "beta_contact"):
        require(f'"{token}"' in stack_text, f"five_parameter_stack_token_missing:{token}")
    for token in ("M2_R8", "neural_R8", "contact_score_R8", "M2_R9", "neural_R9", "contact_score_R9"):
        require(f'"{token}"' in stack_text, f"six_column_stack_token_missing:{token}")

    coarse_receipt = COARSE_DIR / "prepared" / "open1507_m2_c2_double_crossfit_stack_v1" / "RESULT_RECEIPT.json"
    coarse_metrics = COARSE_DIR / "prepared" / "open1507_m2_c2_double_crossfit_stack_v1" / "METRICS.json"
    require(coarse_receipt.is_file() and coarse_metrics.is_file(), "coarse_challenger_evidence_missing")
    coarse = load_json(coarse_receipt)
    require(coarse.get("status") == "DO_NOT_PROMOTE_M2_C2_STACK", "coarse_challenger_status_drift")

    return {
        "training_candidates": len(training_rows),
        "teacher_source_counts": dict(sorted(sources.items())),
        "stage1_jobs": 2640,
        "stage1_success": 2636,
        "stage1_technical_failures": 4,
        "stage1_ranked_candidates": 1320,
        "stage1_analyzable_candidates": 1281,
        "stage1_technical_incomplete_candidates": 39,
        "stage2_selected_candidates": 384,
        "v4h_training_exactly_matches_stage1_analyzable": True,
        "coarse_challenger_status": coarse["status"],
        "coarse_challenger_receipt_sha256": sha256_file(coarse_receipt),
        "coarse_challenger_metrics_sha256": sha256_file(coarse_metrics),
    }


def import_planner():
    spec = importlib.util.spec_from_file_location("strict_nested_planner_v1", PLANNER)
    require(spec is not None and spec.loader is not None, "planner_import_spec_failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_graph(graph: Mapping[str, Any]) -> dict[str, Any]:
    require(graph.get("status") == GRAPH_STATUS, "graph_status_not_dry_run")
    require(graph.get("execution_authorized") is False, "graph_unexpectedly_authorized")
    require(graph.get("sealed_evaluation_access_count") == 0, "sealed_access_nonzero")
    require(graph.get("prediction_metrics_access_count") == 0, "prediction_metrics_access_nonzero")
    require(graph.get("claim_boundary") == GRAPH_CLAIM_BOUNDARY, "graph_claim_boundary_drift")
    require(graph.get("stack_lanes") == list(EXPECTED_LANE_WEIGHTS), "stack_lane_order_drift")
    require((graph.get("resources") or {}).get("physical_gpu_by_lane") == EXPECTED_GPU_MAP, "gpu_map_drift")
    require((graph.get("resources") or {}).get("gpu_training_jobs") == 90, "gpu_job_count")
    require((graph.get("resources") or {}).get("cpu_postprocess_jobs") == 105, "cpu_job_count")
    jobs = list(graph.get("jobs") or [])
    require(len(jobs) == 195, "total_job_count_not_195")
    counts = Counter(job["kind"] for job in jobs)
    require(dict(counts) == EXPECTED_JOB_COUNTS, f"job_kind_counts_drift:{counts}")
    gpu_jobs = [job for job in jobs if job["kind"].startswith("GPU_")]
    require(len(gpu_jobs) == 90, "gpu_jobs_not_90")
    require(all(job.get("command") is None for job in gpu_jobs), "gpu_command_materialized_without_authorization")
    require({job["physical_gpu"] for job in gpu_jobs} == {2, 4, 5}, "gpu_set_drift")
    require(len(graph.get("split_manifests") or {}) == 30, "split_manifest_count_not_30")
    strictness = graph.get("strictness") or {}
    require(strictness.get("meta_fit_rows") == "inner whole-parent OOF only", "meta_fit_scope_drift")
    require(strictness.get("outer_labels_used_for_meta_fit") is False, "outer_label_leakage")
    require(strictness.get("same_rows_fit_and_evaluate_meta") is False, "same_row_meta_leakage")
    require(strictness.get("exact_min") == "prediction_R_dual_min=min(prediction_R8,prediction_R9)", "dual_min_drift")
    return {"jobs": len(jobs), "gpu_jobs": len(gpu_jobs), "cpu_jobs": len(jobs) - len(gpu_jobs), "job_counts": dict(sorted(counts.items()))}


def copy_file(source: Path, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    require(sha256_file(destination) == sha256_file(source), f"copy_hash_mismatch:{source}")
    return {"source_path": str(source), "relative_path": str(destination), "sha256": sha256_file(destination), "size_bytes": destination.stat().st_size}


def build(output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    require(not output_dir.exists(), f"output_exists:{output_dir}")
    input_summary = validate_inputs()
    try:
        output_dir.mkdir(parents=True)
        copied: dict[str, Any] = {}
        copy_specs = {
            "planner": (PLANNER, output_dir / "node1_bundle" / "src" / PLANNER.name),
            "runner": (RUNNER, output_dir / "node1_bundle" / "src" / RUNNER.name),
            "feature_validator": (VALIDATOR, output_dir / "node1_bundle" / "src" / VALIDATOR.name),
            "stack_fitter": (STACK_FITTER, output_dir / "node1_bundle" / "src" / STACK_FITTER.name),
            "training_tsv": (TRAINING, output_dir / "node1_bundle" / "inputs" / TRAINING.name),
            "outer_manifest": (OUTER, output_dir / "node1_bundle" / "inputs" / OUTER.name),
            "inner_manifest": (INNER, output_dir / "node1_bundle" / "inputs" / INNER.name),
            "contact_formula": (FORMULA, output_dir / "node1_bundle" / "inputs" / FORMULA.name),
            "ready_manifest": (READY, output_dir / "contracts" / READY.name),
            "prefreeze_manifest": (PREFREEZE, output_dir / "contracts" / PREFREEZE.name),
            "implementation_freeze": (FREEZE, output_dir / "contracts" / FREEZE.name),
            "calibration_receipt": (CALIBRATION, output_dir / "contracts" / CALIBRATION.name),
            "bundle_receipt": (BUNDLE_RECEIPT, output_dir / "contracts" / BUNDLE_RECEIPT.name),
            "independent_audit": (INDEPENDENT_AUDIT, output_dir / "contracts" / INDEPENDENT_AUDIT.name),
            "adaptive_input_contract": (ADAPTIVE_CONTRACT, output_dir / "contracts" / ADAPTIVE_CONTRACT.name),
            "stage1_receipt": (STAGE1_RECEIPT, output_dir / "contracts" / STAGE1_RECEIPT.name),
            "stage1_ranking": (STAGE1_RANKING, output_dir / "contracts" / STAGE1_RANKING.name),
            "stage2_candidates": (STAGE2_CANDIDATES, output_dir / "contracts" / STAGE2_CANDIDATES.name),
        }
        for name, (source, destination) in copy_specs.items():
            copied[name] = copy_file(source, destination)
            copied[name]["relative_path"] = str(destination.relative_to(output_dir))

        planner = import_planner()
        plan_dir = output_dir / "node1_bundle" / "plan"
        node1_input_root = Path(PACKAGE_NODE1_ROOT) / "inputs"
        planner.plan(SimpleNamespace(
            training_tsv=TRAINING,
            outer_manifest=OUTER,
            inner_manifest=INNER,
            deployment_manifest=READY,
            contact_formula=FORMULA,
            output_dir=plan_dir,
            runtime_root=RUNTIME_NODE1_ROOT,
            node1_plan_root=str(Path(PACKAGE_NODE1_ROOT) / "plan"),
            planner_node1_path=str(Path(PACKAGE_NODE1_ROOT) / "src" / PLANNER.name),
            feature_validator_node1_path=str(Path(PACKAGE_NODE1_ROOT) / "src" / VALIDATOR.name),
            stack_fitter_node1_path=str(Path(PACKAGE_NODE1_ROOT) / "src" / STACK_FITTER.name),
            inner_manifest_node1_path=str(node1_input_root / INNER.name),
            outer_manifest_node1_path=str(node1_input_root / OUTER.name),
            contact_formula_node1_path=str(node1_input_root / FORMULA.name),
        ))
        graph_path = plan_dir / "job_graph.json"
        graph_summary = validate_graph(load_json(graph_path))

        coarse_receipt = COARSE_DIR / "prepared" / "open1507_m2_c2_double_crossfit_stack_v1" / "RESULT_RECEIPT.json"
        coarse_metrics = coarse_receipt.with_name("METRICS.json")
        manifest = {
            "schema_version": SCHEMA,
            "status": PACKAGE_STATUS,
            "claim_boundary": CLAIM_BOUNDARY,
            "graph_claim_boundary": GRAPH_CLAIM_BOUNDARY,
            "launch_authorized": False,
            "training_or_prediction_executed": False,
            "sealed_evaluation_access_count": 0,
            "prediction_metrics_access_count": 0,
            "node1_package_root": PACKAGE_NODE1_ROOT,
            "node1_runtime_root": RUNTIME_NODE1_ROOT,
            "primary_stack": {
                "status": "AUDITED_DRY_RUN_PRIMARY",
                "input_columns": ["M2_R8", "neural_R8", "contact_score_R8", "M2_R9", "neural_R9", "contact_score_R9"],
                "parameter_names": ["intercept_R8", "intercept_R9", "beta_M2", "beta_neural", "beta_contact"],
                "parameter_count": 5,
                "shared_nonnegative_slopes": True,
                "meta_fit": "inner whole-parent OOF only",
                "meta_evaluation": "outer held-out whole parents only",
                "dual_target": "R_dual_min=min(R_8X6B,R_9E6Y)",
            },
            "lane_contract": {
                lane: {"marginal_weight": weights[0], "pair_weight": weights[1], "physical_gpu": EXPECTED_GPU_MAP[lane]}
                for lane, weights in EXPECTED_LANE_WEIGHTS.items()
            },
            "graph": {
                "relative_path": str(graph_path.relative_to(output_dir)),
                "sha256": sha256_file(graph_path),
                "status": GRAPH_STATUS,
                "execution_authorized": False,
                **graph_summary,
            },
            "input_reconciliation": input_summary,
            "copied_artifacts": copied,
            "adaptive_contact_artifacts_not_duplicated": {
                "marginal": {"source_path": str(ADAPTIVE_MARGINAL), "node1_path": load_json(READY)["artifacts"]["adaptive_marginal_tsv_gz"]["node1_path"], "sha256": EXPECTED_HASHES[ADAPTIVE_MARGINAL]},
                "pair": {"source_path": str(ADAPTIVE_PAIR), "node1_path": load_json(READY)["artifacts"]["adaptive_pair_tsv_gz"]["node1_path"], "sha256": EXPECTED_HASHES[ADAPTIVE_PAIR]},
            },
            "separate_challenger": {
                "name": "M2_PLUS_C2_COARSE",
                "included_in_primary_195_job_graph": False,
                "status": "SEPARATE_ALREADY_COMPLETED_DO_NOT_PROMOTE",
                "reason": "Strict double-cross-fit challenger evidence already exists and failed its predeclared promotion threshold; no post-hoc rerun is added.",
                "receipt_path": str(coarse_receipt),
                "receipt_sha256": sha256_file(coarse_receipt),
                "metrics_path": str(coarse_metrics),
                "metrics_sha256": sha256_file(coarse_metrics),
            },
            "authorization_gate": {
                "ready_manifest_production_authorized": False,
                "graph_execution_authorized": False,
                "gpu_commands_materialized": False,
                "required_next_event": "independent audit plus separately versioned explicit production authorization",
                "this_package_must_not_be_used_with_execute": True,
            },
        }
        manifest_path = output_dir / "PACKAGE_MANIFEST.json"
        write_json(manifest_path, manifest)
        immutable_audit = {
            "schema_version": "pvrig_v2_4_v2_2_2_strict_nested_execution_package_audit_v1",
            "status": PACKAGE_STATUS,
            "package_manifest_path": str(manifest_path),
            "package_manifest_sha256": sha256_file(manifest_path),
            "job_graph_path": str(graph_path),
            "job_graph_sha256": sha256_file(graph_path),
            "job_count": 195,
            "gpu_job_count": 90,
            "cpu_job_count": 105,
            "physical_gpus": [2, 4, 5],
            "training_or_prediction_executed": False,
            "launch_authorized": False,
            "sealed_evaluation_access_count": 0,
            "v4h_stage1_analyzable_exact_training_match": True,
        }
        write_json(output_dir / "IMMUTABLE_AUDIT.json", immutable_audit)
        checksum_paths = sorted(path for path in output_dir.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
        with (output_dir / "SHA256SUMS").open("w", encoding="utf-8") as handle:
            for path in checksum_paths:
                handle.write(f"{sha256_file(path)}  {path.relative_to(output_dir)}\n")
        return immutable_audit
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--output-dir", type=Path, required=True)
    return value


def main() -> int:
    result = build(parser().parse_args().output_dir)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
