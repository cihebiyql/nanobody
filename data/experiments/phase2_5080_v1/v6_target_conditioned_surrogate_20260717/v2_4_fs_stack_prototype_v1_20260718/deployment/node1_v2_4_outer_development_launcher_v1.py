#!/usr/bin/env python3
"""Fail-closed V2.4 post-calibration tiny-smoke and outer launcher.

Dry-run is non-mutating. Execution is impossible until a matching immutable
implementation freeze exists and every Node1 artifact closes to the manifest.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import pathlib
import subprocess
from collections import Counter
from typing import Any, Mapping, Sequence


LANE_GPU = {
    "A_VHH_ONLY": 1,
    "B_TARGET_NO_CONTACT": 2,
    "C_SPLIT_MARGINAL": 4,
    "D_SPLIT_PAIR": 5,
}
FOLDS = tuple(range(5))
CPU_THREADS_PER_PROCESS = 8
FREEZE_NAME = "IMPLEMENTATION_FREEZE_V2_4.json"
FREEZE_STATUS = "PASS_V2_4_IMPLEMENTATION_FROZEN_FOR_TINY_SMOKE_AND_OUTER_DEVELOPMENT"
FORBIDDEN_PATH_TOKENS = ("v4_f", "test32", "prospective_computational_test")
THREAD_ENVIRONMENT = {
    "OMP_NUM_THREADS": "8",
    "MKL_NUM_THREADS": "8",
    "OPENBLAS_NUM_THREADS": "8",
    "NUMEXPR_NUM_THREADS": "8",
    "TOKENIZERS_PARALLELISM": "false",
}


class DeploymentError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DeploymentError(message)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: pathlib.Path, label: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"{label}_missing_or_symlink:{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(payload, dict), f"{label}_not_object")
    return payload


def _safe_absolute(value: Any, label: str) -> pathlib.Path:
    require(isinstance(value, str) and value.startswith("/"), f"{label}_not_absolute")
    lowered = value.lower()
    require(not any(token in lowered for token in FORBIDDEN_PATH_TOKENS), f"forbidden_path:{label}:{value}")
    return pathlib.Path(value)


def load_manifest(path: pathlib.Path, *, allow_pending_calibration: bool = False) -> dict[str, Any]:
    payload = load_json(path, "manifest")
    status = payload.get("status")
    ready = status == "PREFREEZE_DRY_RUN_READY_DO_NOT_START"
    pending = status == "PREFREEZE_DRY_RUN_PENDING_CALIBRATION_DO_NOT_START"
    require(ready or (pending and allow_pending_calibration), "manifest_status")
    require(payload.get("production_authorized") is False, "manifest_authorization_flag")
    require(payload.get("sealed_evaluation_access_count") == 0, "sealed_access_nonzero")
    require(payload.get("prediction_metrics_access_count") == 0, "prediction_metric_access_nonzero")
    resources = payload.get("resources") or {}
    require(resources.get("lane_gpu_map") == LANE_GPU, "lane_gpu_map")
    require(resources.get("cpu_threads_per_process") == CPU_THREADS_PER_PROCESS, "cpu_thread_cap")
    require(resources.get("thread_environment") == THREAD_ENVIRONMENT, "thread_environment")
    execution = payload.get("execution") or {}
    require(
        execution.get("phase_order") == [
            "OPEN_ONLY_CONTACT_GRADIENT_CALIBRATION", "IMPLEMENTATION_FREEZE",
            "TINY_SMOKE", "FOUR_LANE_OUTER_DEVELOPMENT"
        ],
        "phase_order",
    )
    require(execution.get("outer_folds") == list(FOLDS), "outer_fold_closure")
    require(execution.get("lanes_concurrent") == 4, "lane_concurrency")
    require(execution.get("folds_sequential_within_lane") is True, "fold_sequence_contract")
    require(execution.get("tiny_smoke_must_pass_all_lanes") is True, "smoke_gate")
    _safe_absolute(payload.get("bundle_root"), "bundle_root")
    _safe_absolute(payload.get("runtime_root"), "runtime_root")
    _safe_absolute(payload.get("python"), "python")

    artifacts = payload.get("artifacts")
    require(isinstance(artifacts, dict) and artifacts, "artifacts_missing")
    for label, record in artifacts.items():
        require(isinstance(record, dict), f"artifact_record:{label}")
        _safe_absolute(record.get("node1_path"), f"artifact:{label}")
        digest = record.get("sha256")
        require(isinstance(digest, str) and len(digest) == 64, f"artifact_sha:{label}")
        require(isinstance(record.get("size_bytes"), int) and record["size_bytes"] >= 0, f"artifact_size:{label}")
        mode = record.get("validation_mode")
        require(mode in {"LOCAL_SOURCE_AND_NODE1", "INHERITED_NODE1_IMMUTABLE"}, f"artifact_validation_mode:{label}")
        if mode == "LOCAL_SOURCE_AND_NODE1":
            _safe_absolute(record.get("source_path"), f"artifact_source:{label}")
        else:
            require(isinstance(record.get("inherited_freeze_sha256"), str) and len(record["inherited_freeze_sha256"]) == 64, f"inherited_freeze:{label}")

    trainer = payload.get("trainer") or {}
    require(trainer.get("artifact_label") in artifacts, "trainer_artifact_label")
    template = trainer.get("argv_template")
    require(isinstance(template, list) and template, "trainer_argv_template")
    placeholders = {token[1:-1] for token in template if isinstance(token, str) and token.startswith("{") and token.endswith("}")}
    required_placeholders = {"python", "trainer", "lane", "split_manifest", "output_dir"}
    require(required_placeholders <= placeholders, "trainer_template_placeholders")
    tiny_argv = trainer.get("tiny_smoke_extra_argv")
    production_argv = trainer.get("outer_development_extra_argv")
    lane_production_argv = trainer.get("lane_outer_extra_argv")
    require(isinstance(tiny_argv, list) and "--tiny-e2e" in tiny_argv, "tiny_smoke_flag")
    if ready:
        require(isinstance(production_argv, list) and "--tiny-e2e" not in production_argv, "outer_development_flags")
        require(isinstance(lane_production_argv, dict) and set(lane_production_argv) == set(LANE_GPU), "lane_outer_argument_closure")
        require(all(isinstance(value, list) for value in lane_production_argv.values()), "lane_outer_arguments")
    else:
        require(production_argv is None and lane_production_argv is None, "pending_outer_arguments_must_be_null")
    require(trainer.get("required_result_file") == "RESULT.json", "trainer_result_contract")
    calibration = payload.get("calibration_contract") or {}
    _safe_absolute(calibration.get("calibration_runtime_root"), "calibration_runtime_root")
    _safe_absolute(calibration.get("calibration_receipt_node1_path"), "calibration_receipt_node1_path")
    require(calibration.get("open_only") is True, "calibration_open_only")
    require(calibration.get("optimizer_steps_before_observation") == 0, "calibration_not_prestep")
    require(calibration.get("outer_metrics_access_count") == 0, "calibration_outer_metric_access")
    require(calibration.get("prediction_metrics_access_count") == 0, "calibration_prediction_metric_access")
    grid = calibration.get("fixed_grid")
    require(isinstance(grid, list) and grid and all(isinstance(value, (int, float)) and value > 0 for value in grid), "calibration_grid")
    lane_weights = calibration.get("frozen_lane_contact_weights")
    if ready:
        require(calibration.get("receipt_artifact_label") == "calibration_receipt", "calibration_receipt_label")
        require("calibration_receipt" in artifacts, "calibration_receipt_artifact_missing")
        require(isinstance(lane_weights, dict) and set(lane_weights) == set(LANE_GPU), "calibration_lane_weight_closure")
        for lane, weights in lane_weights.items():
            argv = lane_production_argv[lane]
            require("--marginal-weight" in argv and "--pair-weight" in argv, f"lane_contact_arguments_missing:{lane}")
            marginal = float(argv[argv.index("--marginal-weight") + 1])
            pair = float(argv[argv.index("--pair-weight") + 1])
            require(marginal == float(weights["marginal"]) and pair == float(weights["pair"]), f"lane_contact_argument_mismatch:{lane}")
    else:
        require(calibration.get("binding_status") == "PENDING_OPEN_ONLY_PRESTEP_CALIBRATION", "pending_calibration_status")
        require(calibration.get("receipt_artifact_label") is None and lane_weights is None, "pending_calibration_binding_must_be_null")
    return payload


def validate_local_sources(manifest: Mapping[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for label, record in sorted(manifest["artifacts"].items()):
        if record["validation_mode"] != "LOCAL_SOURCE_AND_NODE1":
            continue
        path = pathlib.Path(record["source_path"])
        require(path.is_file() and not path.is_symlink(), f"local_source_missing_or_symlink:{label}:{path}")
        require(path.stat().st_size == record["size_bytes"], f"local_source_size:{label}")
        digest = sha256_file(path)
        require(digest == record["sha256"], f"local_source_sha:{label}:{digest}")
        observed[label] = digest
    return observed


def validate_node1_artifacts(manifest: Mapping[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for label, record in sorted(manifest["artifacts"].items()):
        path = pathlib.Path(record["node1_path"])
        require(path.is_file() and not path.is_symlink(), f"node1_artifact_missing_or_symlink:{label}:{path}")
        require(path.stat().st_size == record["size_bytes"], f"node1_artifact_size:{label}")
        digest = sha256_file(path)
        require(digest == record["sha256"], f"node1_artifact_sha:{label}:{digest}")
        observed[label] = digest
    return observed


def validate_training_contract(manifest: Mapping[str, Any], *, use_source: bool) -> dict[str, Any]:
    artifacts = manifest["artifacts"]
    key = "source_path" if use_source else "node1_path"
    table_path = pathlib.Path(artifacts["training_tsv"][key])
    receipt_path = pathlib.Path(artifacts["training_receipt"][key])
    with table_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    expected = manifest["expected_training_counts"]
    require(len(rows) == expected["rows"], "training_rows")
    require(len({row["candidate_id"] for row in rows}) == expected["unique_candidates"], "training_candidates")
    require(len({row["parent_framework_cluster"] for row in rows}) == expected["unique_parent_framework_clusters"], "training_parents")
    require(dict(Counter(row["teacher_source"] for row in rows)) == expected["teacher_sources"], "training_sources")
    require(dict(Counter(row["development_reliability_tier"] for row in rows)) == expected["reliability_tiers"], "training_reliability_tiers")
    receipt = load_json(receipt_path, "training_receipt")
    require(receipt.get("status") == "PASS_V2_4_SUPERVISED1507_MATERIALIZED", "training_receipt_status")
    require(receipt.get("output", {}).get("sha256") == artifacts["training_tsv"]["sha256"], "training_receipt_table_sha")
    return {"rows": len(rows), "parents": expected["unique_parent_framework_clusters"]}


def validate_calibration_receipt(manifest: Mapping[str, Any], *, use_source: bool) -> dict[str, Any]:
    contract = manifest["calibration_contract"]
    record = manifest["artifacts"][contract["receipt_artifact_label"]]
    path = pathlib.Path(record["source_path"] if use_source else record["node1_path"])
    receipt = load_json(path, "calibration_receipt")
    require(receipt.get("status") == "PASS_OPEN_ONLY_PRESTEP_CONTACT_GRADIENT_CALIBRATION_V2_4", "calibration_status")
    require(receipt.get("open_only") is True, "calibration_receipt_open_only")
    require(receipt.get("optimizer_steps_before_observation") == 0, "calibration_receipt_not_prestep")
    require(receipt.get("outer_metrics_access_count") == 0, "calibration_receipt_outer_metric_access")
    require(receipt.get("prediction_metrics_access_count") == 0, "calibration_receipt_prediction_metric_access")
    require(receipt.get("v4_f_test32_access_count") == 0, "calibration_receipt_v4f_access")
    require(receipt.get("fixed_grid") == contract["fixed_grid"], "calibration_grid_mismatch")
    require(receipt.get("frozen_lane_contact_weights") == contract["frozen_lane_contact_weights"], "calibration_lane_weights_mismatch")
    require(receipt.get("attention_temperatures") == contract["attention_temperatures"], "calibration_temperature_mismatch")
    return receipt


def substitute_command(
    manifest: Mapping[str, Any], *, lane: str, outer_fold: int, output_dir: pathlib.Path, smoke: bool
) -> list[str]:
    require(lane in LANE_GPU and outer_fold in FOLDS, "command_lane_or_fold")
    values = {
        "python": manifest["python"],
        "trainer": manifest["artifacts"][manifest["trainer"]["artifact_label"]]["node1_path"],
        "lane": lane,
        "outer_fold": str(outer_fold),
        "output_dir": str(output_dir),
        "split_manifest": manifest["artifacts"][f"outer_split_{outer_fold}"]["node1_path"],
        "vhh_graph_dir": str(pathlib.Path(manifest["artifacts"]["vhh_graph_cache_npz"]["node1_path"]).parent),
    }
    for label, record in manifest["artifacts"].items():
        values[label] = record["node1_path"]
    command: list[str] = []
    for token in manifest["trainer"]["argv_template"]:
        require(isinstance(token, str), "trainer_template_nonstring")
        if token.startswith("{") and token.endswith("}"):
            name = token[1:-1]
            require(name in values, f"unknown_command_placeholder:{name}")
            command.append(str(values[name]))
        else:
            require("{" not in token and "}" not in token, f"partial_placeholder_forbidden:{token}")
            command.append(token)
    if smoke:
        command.extend(manifest["trainer"]["tiny_smoke_extra_argv"])
    else:
        command.extend(manifest["trainer"]["outer_development_extra_argv"])
        command.extend(manifest["trainer"]["lane_outer_extra_argv"][lane])
    return command


def dry_run_plan(manifest_path: pathlib.Path, *, runtime_override: pathlib.Path | None = None) -> dict[str, Any]:
    manifest = load_manifest(manifest_path, allow_pending_calibration=True)
    calibration_ready = manifest["status"] == "PREFREEZE_DRY_RUN_READY_DO_NOT_START"
    observed = validate_local_sources(manifest)
    validate_training_contract(manifest, use_source=True)
    if calibration_ready:
        validate_calibration_receipt(manifest, use_source=True)
    runtime = runtime_override or pathlib.Path(manifest["runtime_root"])
    require(not os.path.lexists(runtime), f"runtime_must_be_absent_before_freeze:{runtime}")
    smoke = {}
    production = {}
    for lane in LANE_GPU:
        smoke_output = runtime / "tiny_smoke" / lane / "fold_0"
        smoke[lane] = {
            "physical_gpu": LANE_GPU[lane],
            "command": substitute_command(manifest, lane=lane, outer_fold=0, output_dir=smoke_output, smoke=True),
        }
        production[lane] = {"physical_gpu": LANE_GPU[lane]}
        if calibration_ready:
            production[lane]["commands"] = [
                    substitute_command(
                        manifest, lane=lane, outer_fold=fold,
                        output_dir=runtime / "outer_development" / lane / f"fold_{fold}", smoke=False,
                    )
                    for fold in FOLDS
                ]
        else:
            production[lane]["commands"] = []
            production[lane]["planned_outer_folds"] = list(FOLDS)
            production[lane]["blocked_by"] = "PENDING_OPEN_ONLY_PRESTEP_CALIBRATION"
    return {
        "schema_version": "pvrig_v6_residue_v2_4_node1_dry_run_v1",
        "status": (
            "PASS_PREFREEZE_DRY_RUN_NO_RUNTIME_MUTATION"
            if calibration_ready else "PASS_PREFREEZE_DRY_RUN_BLOCKED_PENDING_CALIBRATION"
        ),
        "manifest_sha256": sha256_file(manifest_path),
        "runtime_root": str(runtime),
        "runtime_absent": True,
        "local_source_sha256": observed,
        "phase_order": [
            "OPEN_ONLY_CONTACT_GRADIENT_CALIBRATION", "IMPLEMENTATION_FREEZE",
            "TINY_SMOKE", "FOUR_LANE_OUTER_DEVELOPMENT"
        ],
        "tiny_smoke": smoke,
        "outer_development": production,
        "tiny_smoke_command_count": 4,
        "outer_development_command_count": 20 if calibration_ready else 0,
        "outer_development_planned_job_count": 20,
        "cpu_threads_per_process": CPU_THREADS_PER_PROCESS,
        "thread_environment": THREAD_ENVIRONMENT,
        "production_authorized": False,
        "automatic_smoke_to_outer_transition": False,
        "outer_requires_frozen_calibration_receipt_sha256": (
            manifest["artifacts"]["calibration_receipt"]["sha256"] if calibration_ready else None
        ),
        "sealed_evaluation_access_count": 0,
        "prediction_metrics_access_count": 0,
    }


def validate_freeze(manifest_path: pathlib.Path, freeze_path: pathlib.Path) -> dict[str, Any]:
    freeze = load_json(freeze_path, "implementation_freeze")
    require(freeze_path.name == FREEZE_NAME, "freeze_filename")
    require(freeze.get("status") == FREEZE_STATUS, "freeze_status")
    require(freeze.get("production_training_started") is False, "freeze_training_started")
    require(freeze.get("manifest_sha256") == sha256_file(manifest_path), "freeze_manifest_sha")
    require(freeze.get("launcher_sha256") == sha256_file(pathlib.Path(__file__).resolve()), "freeze_launcher_sha")
    require(freeze.get("pending") == [], "freeze_pending")
    manifest = load_manifest(manifest_path)
    expected_artifacts = {label: record["sha256"] for label, record in sorted(manifest["artifacts"].items())}
    require(freeze.get("formal_artifact_sha256") == expected_artifacts, "freeze_artifact_closure")
    return freeze


def _run_one(
    manifest: Mapping[str, Any], *, lane: str, fold: int, output_dir: pathlib.Path, smoke: bool
) -> dict[str, Any]:
    require(not os.path.lexists(output_dir), f"trainer_output_already_exists:{output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    command = substitute_command(manifest, lane=lane, outer_fold=fold, output_dir=output_dir, smoke=smoke)
    environment = os.environ.copy()
    environment.update(THREAD_ENVIRONMENT)
    environment["CUDA_VISIBLE_DEVICES"] = str(LANE_GPU[lane])
    log_path = output_dir.parent / f"{output_dir.name}.trainer.log"
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=environment, check=False)
    require(completed.returncode == 0, f"trainer_failed:{lane}:{fold}:{completed.returncode}")
    result_path = output_dir / manifest["trainer"]["required_result_file"]
    result = load_json(result_path, f"trainer_result:{lane}:{fold}")
    require(str(result.get("status", "")).startswith("PASS"), f"trainer_result_status:{lane}:{fold}")
    observed_fold = (result.get("split") or {}).get("outer_fold", result.get("outer_fold"))
    require(result.get("lane") == lane and int(observed_fold) == fold, f"trainer_result_identity:{lane}:{fold}")
    return {
        "lane": lane,
        "outer_fold": fold,
        "physical_gpu": LANE_GPU[lane],
        "command_sha256": hashlib.sha256("\0".join(command).encode()).hexdigest(),
        "result_sha256": sha256_file(result_path),
        "log_sha256": sha256_file(log_path),
    }


def execute_smoke(manifest_path: pathlib.Path, freeze_path: pathlib.Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    freeze = validate_freeze(manifest_path, freeze_path)
    observed = validate_node1_artifacts(manifest)
    validate_training_contract(manifest, use_source=False)
    validate_calibration_receipt(manifest, use_source=False)
    runtime = pathlib.Path(manifest["runtime_root"])
    require(not os.path.lexists(runtime), f"runtime_must_be_absent_before_freeze:{runtime}")
    require(runtime.parent.is_dir() and not runtime.parent.is_symlink(), "runtime_parent_missing_or_symlink")
    runtime.mkdir(exist_ok=False)
    (runtime / "tiny_smoke").mkdir()
    (runtime / "status").mkdir()

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            lane: pool.submit(
                _run_one, manifest, lane=lane, fold=0,
                output_dir=runtime / "tiny_smoke" / lane / "fold_0", smoke=True,
            )
            for lane in LANE_GPU
        }
        smoke_results = {lane: future.result() for lane, future in futures.items()}

    receipt = {
        "schema_version": "pvrig_v6_residue_v2_4_node1_tiny_smoke_receipt_v1",
        "status": "PASS_V2_4_TINY_SMOKE_ALL_FOUR_LANES_STOP_BEFORE_OUTER",
        "manifest_sha256": sha256_file(manifest_path),
        "implementation_freeze_sha256": sha256_file(freeze_path),
        "formal_artifact_sha256": observed,
        "tiny_smoke": smoke_results,
        "outer_development_started": False,
        "automatic_smoke_to_outer_transition": False,
        "cpu_threads_per_process": CPU_THREADS_PER_PROCESS,
        "sealed_evaluation_access_count": 0,
        "prediction_metrics_access_count": 0,
        "freeze_status": freeze["status"],
    }
    receipt_path = runtime / "status" / "SMOKE_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def validate_smoke_receipt(manifest_path: pathlib.Path, freeze_path: pathlib.Path, runtime: pathlib.Path) -> dict[str, Any]:
    path = runtime / "status" / "SMOKE_RECEIPT.json"
    receipt = load_json(path, "smoke_receipt")
    require(receipt.get("status") == "PASS_V2_4_TINY_SMOKE_ALL_FOUR_LANES_STOP_BEFORE_OUTER", "smoke_receipt_status")
    require(receipt.get("manifest_sha256") == sha256_file(manifest_path), "smoke_manifest_sha")
    require(receipt.get("implementation_freeze_sha256") == sha256_file(freeze_path), "smoke_freeze_sha")
    require(receipt.get("outer_development_started") is False, "smoke_outer_started")
    require(set(receipt.get("tiny_smoke") or {}) == set(LANE_GPU), "smoke_lane_closure")
    return receipt


def execute_outer(manifest_path: pathlib.Path, freeze_path: pathlib.Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    freeze = validate_freeze(manifest_path, freeze_path)
    observed = validate_node1_artifacts(manifest)
    validate_training_contract(manifest, use_source=False)
    calibration = validate_calibration_receipt(manifest, use_source=False)
    runtime = pathlib.Path(manifest["runtime_root"])
    require(runtime.is_dir() and not runtime.is_symlink(), "smoke_runtime_missing_or_symlink")
    smoke_receipt = validate_smoke_receipt(manifest_path, freeze_path, runtime)
    outer_root = runtime / "outer_development"
    require(not os.path.lexists(outer_root), "outer_development_already_exists")
    outer_root.mkdir()

    def run_lane(lane: str) -> list[dict[str, Any]]:
        return [
            _run_one(
                manifest, lane=lane, fold=fold,
                output_dir=outer_root / lane / f"fold_{fold}", smoke=False,
            )
            for fold in FOLDS
        ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {lane: pool.submit(run_lane, lane) for lane in LANE_GPU}
        production_results = {lane: future.result() for lane, future in futures.items()}
    receipt = {
        "schema_version": "pvrig_v6_residue_v2_4_node1_outer_development_receipt_v1",
        "status": "PASS_FOUR_LANE_OUTER_DEVELOPMENT_AFTER_INDEPENDENT_GATES",
        "manifest_sha256": sha256_file(manifest_path),
        "implementation_freeze_sha256": sha256_file(freeze_path),
        "formal_artifact_sha256": observed,
        "smoke_receipt_sha256": sha256_file(runtime / "status" / "SMOKE_RECEIPT.json"),
        "calibration_receipt_sha256": manifest["artifacts"]["calibration_receipt"]["sha256"],
        "calibration_status": calibration["status"],
        "outer_development": production_results,
        "cpu_threads_per_process": CPU_THREADS_PER_PROCESS,
        "sealed_evaluation_access_count": 0,
        "prediction_metrics_access_count": 0,
        "freeze_status": freeze["status"],
    }
    receipt_path = runtime / "status" / "OUTER_DEVELOPMENT_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute-smoke", action="store_true")
    mode.add_argument("--execute-outer", action="store_true")
    parser.add_argument("--freeze", type=pathlib.Path)
    parser.add_argument("--runtime-override", type=pathlib.Path)
    args = parser.parse_args()
    if args.dry_run:
        require(args.freeze is None, "freeze_not_accepted_by_prefreeze_dry_run")
        result = dry_run_plan(args.manifest, runtime_override=args.runtime_override)
    elif args.execute_smoke:
        require(args.runtime_override is None, "runtime_override_forbidden_for_execution")
        require(args.freeze is not None, "implementation_freeze_required_for_execution")
        result = execute_smoke(args.manifest, args.freeze)
    else:
        require(args.runtime_override is None, "runtime_override_forbidden_for_execution")
        require(args.freeze is not None, "implementation_freeze_required_for_execution")
        result = execute_outer(args.manifest, args.freeze)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DeploymentError, OSError, json.JSONDecodeError) as error:
        print(f"FAIL_V2_4_DEPLOYMENT:{error}", file=os.sys.stderr)
        raise SystemExit(1)
