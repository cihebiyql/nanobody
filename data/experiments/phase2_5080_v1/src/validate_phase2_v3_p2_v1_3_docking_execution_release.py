#!/usr/bin/env python3
"""Validate the frozen V1.3 development docking execution release."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
DEFAULT_MANIFEST = (
    EXP_DIR / "audits/phase2_v3_p2_v1_3_docking_execution_release_manifest.json"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(raw: str, data_root: Path = DATA_ROOT) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (data_root / path).resolve()


def validate_payload(payload: dict[str, Any], data_root: Path = DATA_ROOT) -> list[str]:
    errors: list[str] = []
    expected_scalars = {
        "schema_version": "phase2_v3_p2_v1_3_docking_execution_release_v1",
        "protocol_id": "DG_A_PVRIG_V1_3_DUAL47_COMPLETION15",
        "status": "FROZEN_V1_3_DOCKING_EXECUTION_RELEASE",
        "remote_launch_eligible": True,
        "remote_launch_run_count": 30,
        "formal_eligible": False,
        "docking_gold_release_eligible": False,
        "training_label_release_eligible": False,
        "p2_training_ready": False,
    }
    for field, expected in expected_scalars.items():
        if payload.get(field) != expected:
            errors.append(f"{field}_mismatch")

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return errors + ["artifacts_missing"]
    seen: set[str] = set()
    for index, item in enumerate(artifacts):
        if not isinstance(item, dict):
            errors.append(f"artifact_{index}_not_object")
            continue
        raw_path = str(item.get("path", ""))
        expected_hash = str(item.get("sha256", ""))
        expected_bytes = item.get("bytes")
        if not raw_path or raw_path in seen:
            errors.append(f"artifact_{index}_path_missing_or_duplicate")
            continue
        seen.add(raw_path)
        path = resolve_path(raw_path, data_root)
        if not path.is_file():
            errors.append(f"artifact_missing:{raw_path}")
            continue
        if not SHA256_RE.fullmatch(expected_hash) or sha256_file(path) != expected_hash:
            errors.append(f"artifact_hash_mismatch:{raw_path}")
        if not isinstance(expected_bytes, int) or path.stat().st_size != expected_bytes:
            errors.append(f"artifact_size_mismatch:{raw_path}")

    package_path = resolve_path(str(payload.get("package_audit_path", "")), data_root)
    prereg_path = resolve_path(str(payload.get("preregistration_path", "")), data_root)
    anchor_path = resolve_path(str(payload.get("anchor_readiness_path", "")), data_root)
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
        prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return errors + [f"bound_json_unreadable:{error}"]

    package_expected = {
        "status": "PASS_V1_3_DUAL47_COMPLETION15_PACKAGE_READY",
        "candidate_count": 47,
        "run_count": 94,
        "reuse_run_count": 64,
        "new_run_count": 30,
        "remote_jobs_launched": False,
        "formal_eligible": False,
        "training_label_release_eligible": False,
        "docking_gold_release_eligible": False,
        "p2_training_ready": False,
        "reuse_coordinate_payload_hash_closed": False,
        "reuse_coordinate_payload_state": "REMOTE_RECOVERY_REQUIRED_BEFORE_SCORING",
    }
    for field, expected in package_expected.items():
        if package.get(field) != expected:
            errors.append(f"package_{field}_mismatch")
    if prereg.get("status") != "PREREGISTERED_V1_3_DEVELOPMENT_ONLY_PENDING_IMPLEMENTATION":
        errors.append("preregistration_status_mismatch")
    if prereg.get("eligibility", {}).get("formal_eligible") is not False:
        errors.append("preregistration_formal_boundary_mismatch")
    if anchor.get("status") != "FAIL_FORMAL_ANCHOR_READINESS_ZERO_NEW_FAMILIES":
        errors.append("anchor_readiness_status_mismatch")
    if anchor.get("decision", {}).get("v1_3_formal_validation_permitted") is not False:
        errors.append("anchor_formal_boundary_mismatch")

    launch = payload.get("remote_launch_contract", {})
    launch_expected = {
        "max_workers": 5,
        "max_load1": 50,
        "load_poll_seconds": 30,
        "expected_new_cases": 15,
        "expected_new_runs": 30,
        "success_status": "PASS_4_EMREF_TOP8_READY",
        "source_stage": "4_emref",
        "backfill_allowed": False,
    }
    for field, expected in launch_expected.items():
        if launch.get(field) != expected:
            errors.append(f"launch_{field}_mismatch")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    errors = validate_payload(payload)
    result = {
        "status": (
            "PASS_V1_3_DOCKING_EXECUTION_RELEASE_VALIDATED"
            if not errors
            else "FAIL_V1_3_DOCKING_EXECUTION_RELEASE_INVALID"
        ),
        "valid": not errors,
        "manifest": str(args.manifest.resolve()),
        "manifest_sha256": sha256_file(args.manifest),
        "artifact_count": len(payload.get("artifacts", [])),
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
