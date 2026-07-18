#!/usr/bin/env python3
"""Build a fail-closed receipt for the non-executable V2.4 prefreeze package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


EXPECTED_DRY_STATUS = "PASS_PREFREEZE_DRY_RUN_BLOCKED_PENDING_CALIBRATION"
EXPECTED_MANIFEST_STATUS = "PREFREEZE_DRY_RUN_PENDING_CALIBRATION_DO_NOT_START"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"json_root_not_object:{path}")
    return value


def build(
    *, manifest_path: Path, dry_run_path: Path, calibration_dry_run_path: Path,
    test_log_path: Path, launcher_path: Path, calibration_runner_path: Path,
    manifest_builder_path: Path, output_path: Path,
) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    dry = read_json(dry_run_path)
    if manifest.get("status") != EXPECTED_MANIFEST_STATUS:
        raise RuntimeError("manifest_not_prefreeze_calibration_pending")
    if manifest.get("production_authorized") is not False:
        raise RuntimeError("manifest_production_authorized")
    if dry.get("status") != EXPECTED_DRY_STATUS:
        raise RuntimeError("dry_run_status_invalid")
    if dry.get("runtime_absent") is not True:
        raise RuntimeError("dry_run_runtime_not_absent")
    if dry.get("tiny_smoke_command_count") != 4:
        raise RuntimeError("tiny_smoke_command_count_not_4")
    if dry.get("outer_development_planned_job_count") != 20:
        raise RuntimeError("outer_planned_job_count_not_20")
    if dry.get("outer_development_command_count") != 0:
        raise RuntimeError("outer_commands_exist_before_calibration")
    if dry.get("manifest_sha256") != sha256(manifest_path):
        raise RuntimeError("dry_run_manifest_sha256_mismatch")
    calibration_dry = read_json(calibration_dry_run_path)
    if calibration_dry.get("status") != "PASS_OPEN_ONLY_PRESTEP_CALIBRATION_DRY_RUN_NO_MUTATION":
        raise RuntimeError("calibration_dry_run_status_invalid")
    if calibration_dry.get("manifest_sha256") != sha256(manifest_path):
        raise RuntimeError("calibration_dry_run_manifest_sha256_mismatch")
    if calibration_dry.get("command_count") != 2 or calibration_dry.get("optimizer_steps_before_observation") != 0:
        raise RuntimeError("calibration_dry_run_command_or_step_contract")
    expected_phase_order = [
        "OPEN_ONLY_CONTACT_GRADIENT_CALIBRATION", "IMPLEMENTATION_FREEZE",
        "TINY_SMOKE", "FOUR_LANE_OUTER_DEVELOPMENT",
    ]
    if calibration_dry.get("phase_order") != expected_phase_order or dry.get("phase_order") != expected_phase_order:
        raise RuntimeError("phase_order_mismatch")
    if manifest.get("calibration_contract", {}).get("binding_status") != "PENDING_OPEN_ONLY_PRESTEP_CALIBRATION":
        raise RuntimeError("calibration_not_pending_open_only_prestep")
    if manifest_path.with_name("IMPLEMENTATION_FREEZE_V2_4.json").exists():
        raise RuntimeError("implementation_freeze_exists")

    test_log = test_log_path.read_text(encoding="utf-8")
    match = re.search(r"Ran (\d+) tests", test_log)
    if not match or "\nOK\n" not in test_log:
        raise RuntimeError("tests_not_proven_pass")
    artifacts = manifest.get("artifacts", {})
    payload = {
        "schema_version": "pvrig_v6_residue_v2_4_prefreeze_package_receipt_v1",
        "status": "PASS_PREFREEZE_DEPLOYMENT_PACKAGE_CALIBRATION_PENDING_NO_FREEZE",
        "production_authorized": False,
        "implementation_freeze_created": False,
        "runtime_created": False,
        "sealed_evaluation_access_count": 0,
        "prediction_metrics_access_count": 0,
        "tests": {"status": "PASS", "count": int(match.group(1)), "log_sha256": sha256(test_log_path)},
        "dry_run": {
            "status": dry["status"], "sha256": sha256(dry_run_path),
            "tiny_smoke_command_count": 4, "outer_planned_job_count": 20,
            "outer_executable_command_count": 0, "runtime_absent": True,
        },
        "calibration_dry_run": {
            "status": calibration_dry["status"], "sha256": sha256(calibration_dry_run_path),
            "command_count": 2, "optimizer_steps_before_observation": 0,
            "runtime_absent": True, "receipt_absent": True,
        },
        "bindings": {
            "manifest_sha256": sha256(manifest_path),
            "launcher_sha256": sha256(launcher_path),
            "calibration_runner_sha256": sha256(calibration_runner_path),
            "manifest_builder_sha256": sha256(manifest_builder_path),
            "training_tsv_sha256": artifacts["training_tsv"]["sha256"],
            "training_receipt_sha256": artifacts["training_receipt"]["sha256"],
            "trainer_sha256": artifacts["trainer"]["sha256"],
            "trainer_test_sha256": artifacts["trainer_test"]["sha256"],
            "model_sha256": artifacts["model"]["sha256"],
            "contact_formula_sha256": artifacts["contact_formula"]["sha256"],
            "outer_split_source_sha256": artifacts["outer_split_source"]["sha256"],
            "outer_split_materialization_receipt_sha256": artifacts["outer_split_materialization_receipt"]["sha256"],
        },
        "pending": ["CALIBRATION_RECEIPT.json", "frozen_lane_contact_weights", "IMPLEMENTATION_FREEZE_V2_4.json"],
        "next_permitted_action": "Run open-only optimizer-prestep contact-gradient calibration; do not run outer development.",
        "claim_boundary": manifest["claim_boundary"],
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": payload["status"], "output": str(output_path), "sha256": sha256(output_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dry-run", type=Path, required=True)
    parser.add_argument("--calibration-dry-run", type=Path, required=True)
    parser.add_argument("--test-log", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--calibration-runner", type=Path, required=True)
    parser.add_argument("--manifest-builder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(
        manifest_path=args.manifest, dry_run_path=args.dry_run,
        calibration_dry_run_path=args.calibration_dry_run,
        test_log_path=args.test_log, launcher_path=args.launcher,
        calibration_runner_path=args.calibration_runner,
        manifest_builder_path=args.manifest_builder, output_path=args.output,
    ), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
