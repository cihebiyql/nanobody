#!/usr/bin/env python3
"""Run adversarial tests and freeze the label-sealed V4-F96 evaluator package."""
from __future__ import annotations

import hashlib
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
EXP_DIR = SCRIPT_DIR.parent
EVALUATOR = SCRIPT_DIR / "evaluate_phase2_v4_f96_formal.py"
TESTS = SCRIPT_DIR / "test_evaluate_phase2_v4_f96_formal.py"
PREREG = EXP_DIR / "audits/phase2_v4_f96_formal_evaluator_v2_preregistration.json"
TEST_LOG = EXP_DIR / "audits/phase2_v4_f96_formal_evaluator_v1_tests.log"
FREEZE = EXP_DIR / "audits/phase2_v4_f96_formal_evaluator_v1_implementation_freeze.json"
RECEIPT = EXP_DIR / "audits/phase2_v4_f96_formal_evaluator_v1_implementation_freeze.receipt.json"
PYTHON = EXP_DIR / ".venv-phase2-5080/bin/python"
EXPECTED_PREREG_SHA256 = "05d5727c7568ac9563c75d7ec7b916f172eefd915a728b829d29c25a12079fc3"
EXPECTED_TEST_COUNT = 29
CANONICAL_FUTURE_LABEL_ROOT = EXP_DIR / "prepared/pvrig_v4_f96_formal_evaluation_v1"
CANONICAL_FORMAL_OUTPUT = EXP_DIR / "runs/pvrig_v4_f96_formal_evaluation_v1"
CANONICAL_PREDICTION_RECEIPT = EXP_DIR / "predictions/pvrig_v4_f_surrogate_predictions_v1/v4_f_96_frozen_surrogate_predictions.receipt.json"


class FreezeError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FreezeError(message)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_json(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def meta(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"freeze_input_missing_or_not_regular:{path}")
    return {"path": str(path.resolve()), "sha256": sha(path), "size_bytes": path.stat().st_size}


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def run_tests() -> dict[str, Any]:
    require(PYTHON.is_file(), "frozen_test_python_missing")
    compile_result = subprocess.run(
        [str(PYTHON), "-m", "py_compile", str(EVALUATOR), str(TESTS), str(SCRIPT_PATH)],
        cwd=EXP_DIR.parent.parent, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        check=False,
    )
    require(compile_result.returncode == 0, "evaluator_python_compile_failed")
    result = subprocess.run(
        [str(PYTHON), "-m", "unittest", "-v", "experiments.phase2_5080_v1.src.test_evaluate_phase2_v4_f96_formal"],
        cwd=EXP_DIR.parent.parent, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        check=False,
    )
    TEST_LOG.parent.mkdir(parents=True, exist_ok=True)
    TEST_LOG.write_text(result.stdout, encoding="utf-8")
    match = re.search(r"Ran\s+(\d+)\s+tests?\s+in", result.stdout)
    parsed = int(match.group(1)) if match else -1
    require(result.returncode == 0, "evaluator_adversarial_tests_failed")
    require(parsed == EXPECTED_TEST_COUNT, f"evaluator_test_count_mismatch:{parsed}")
    require(re.search(r"^OK\s*$", result.stdout, flags=re.MULTILINE) is not None, "evaluator_test_log_missing_OK")
    require("FAILED" not in result.stdout and "ERROR" not in result.stdout, "evaluator_test_log_contains_failure_token")
    return {"parsed_test_count": parsed, "unittest_status": "OK", "python_compile_status": "PASS_3_FILES", "return_code": result.returncode}


def verify_receipt() -> dict[str, Any]:
    require(FREEZE.is_file() and RECEIPT.is_file(), "implementation_freeze_or_receipt_missing")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    require(receipt.get("status") == "PASS_COMPLETE_HASH_CLOSURE_BEFORE_V4F96_LABEL_UNSEAL", "implementation_freeze_receipt_status_invalid")
    require((receipt.get("implementation_freeze") or {}).get("sha256") == sha(FREEZE), "implementation_freeze_receipt_hash_mismatch")
    require(receipt.get("evaluator_preregistration_sha256") == EXPECTED_PREREG_SHA256, "implementation_freeze_prereg_hash_mismatch")
    for name, item in (freeze.get("implementation_files") or {}).items():
        path = Path(item["path"])
        require(path.is_file() and not path.is_symlink() and sha(path) == item["sha256"], f"implementation_file_hash_mismatch:{name}")
    payload = dict(freeze)
    declared_payload_hash = payload.pop("payload_sha256", None)
    require(declared_payload_hash == sha_json(payload), "implementation_freeze_payload_hash_mismatch")
    return {"status": "PASS_V4_F96_FORMAL_EVALUATOR_PACKAGE_VERIFIED", "implementation_freeze_sha256": sha(FREEZE), "evaluator_sha256": sha(EVALUATOR), "test_count": freeze["test_execution"]["parsed_test_count"]}


def build() -> dict[str, Any]:
    require(
        not any(path.exists() for path in (TEST_LOG, FREEZE, RECEIPT)),
        "canonical_freeze_artifact_exists_refuse_overwrite_use_verify_only",
    )
    require(sha(PREREG) == EXPECTED_PREREG_SHA256, "preregistration_changed_before_implementation_freeze")
    require(not CANONICAL_FUTURE_LABEL_ROOT.exists(), "future_label_root_already_exists_refuse_clean_room_freeze")
    require(not CANONICAL_FORMAL_OUTPUT.exists(), "formal_output_already_exists_refuse_clean_room_freeze")
    test_execution = run_tests()
    files = {
        "evaluator": meta(EVALUATOR), "adversarial_tests": meta(TESTS),
        "freeze_builder": meta(SCRIPT_PATH), "preregistration": meta(PREREG),
        "test_log": meta(TEST_LOG),
    }
    payload: dict[str, Any] = {
        "schema_version": "phase2_v4_f96_formal_evaluator_implementation_freeze_v1",
        "status": "PASS_IMPLEMENTATION_FROZEN_BEFORE_V4F96_LABEL_UNSEAL",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "implementation_files": files,
        "test_execution": {**test_execution, "test_log": files["test_log"]},
        "pre_unseal_state": {
            "frozen_prediction_receipt_present": CANONICAL_PREDICTION_RECEIPT.is_file(),
            "future_full_qc_eligibility_or_docking_label_root_present": False,
            "formal_evaluation_output_present": False,
            "formal_evaluation_run_count": 0,
        },
        "label_access": {
            "v4_f96_docking_label_paths_accepted": 0,
            "v4_f96_docking_label_files_opened": 0,
            "v4_f96_docking_labels_read": False,
            "formal_evaluation_executed": False,
        },
        "frozen_scientific_contract": {
            "primary_endpoint": "R_dual_min", "endpoint_direction": "higher_is_better",
            "primary_model_family": "contact", "one_shot": True,
            "denominator": "all V4-F Full-QC hard-pass candidates with no replacement",
            "bootstrap_unit": "parent_framework_cluster", "bootstrap_replicates": 10000,
            "formal_statuses": [
                "PASS_V4_F96_COMPUTATIONAL_GEOMETRY_SURROGATE",
                "FAIL_V4_F96_COMPUTATIONAL_GEOMETRY_SURROGATE",
                "INSUFFICIENT_TECHNICAL_COVERAGE",
            ],
        },
        "claim_boundary": "Computational independent dual-receptor Docking geometry only; not binding, affinity, competition, Docking Gold, experimental blocking, or final submission authority.",
    }
    payload["payload_sha256"] = sha_json(payload)
    write_json(FREEZE, payload)
    receipt = {
        "schema_version": "phase2_v4_f96_formal_evaluator_implementation_freeze_receipt_v1",
        "status": "PASS_COMPLETE_HASH_CLOSURE_BEFORE_V4F96_LABEL_UNSEAL",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "implementation_freeze": meta(FREEZE),
        "evaluator_sha256": files["evaluator"]["sha256"],
        "evaluator_preregistration_sha256": EXPECTED_PREREG_SHA256,
        "test_log_sha256": files["test_log"]["sha256"],
        "parsed_test_count": test_execution["parsed_test_count"],
        "v4_f96_docking_label_paths_accepted": 0,
        "v4_f96_docking_labels_read": False,
        "formal_evaluation_executed": False,
    }
    write_json(RECEIPT, receipt)
    return verify_receipt()


def main() -> int:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--verify-only", action="store_true")
    args = arguments.parse_args()
    try:
        result = verify_receipt() if args.verify_only else build()
    except FreezeError as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
