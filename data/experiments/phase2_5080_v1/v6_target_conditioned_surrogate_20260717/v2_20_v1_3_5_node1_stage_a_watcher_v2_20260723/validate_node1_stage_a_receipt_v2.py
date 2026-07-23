#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


STATUS = "PASS_NODE1_V220_V1_3_5_FIVE_FOLD_SHARED_CALIBRATION_LOAD_ONLY_NO_TRAINING"
SCHEMA = "pvrig.v220.v1_3_5_node1_preflight_receipt.v1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class ValidationError(RuntimeError):
    pass


def require(value: bool, message: str) -> None:
    if not value:
        raise ValidationError(message)


def read_regular(path: Path) -> bytes:
    require(path.is_file() and not path.is_symlink(), f"not_regular:{path}")
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    identity = lambda x: (x.st_dev, x.st_ino, x.st_mode, x.st_size, x.st_mtime_ns, x.st_ctime_ns)
    require(raw and identity(before) == identity(after), f"unstable_or_empty:{path}")
    return raw


def atomic_json_new(path: Path, payload: dict[str, Any]) -> None:
    require(not path.exists(), f"output_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    require(read_regular(path) == raw, "output_replay")


def validate(
    receipt_path: Path,
    sidecar_path: Path,
    content_path: Path,
    expected_freeze_sha: str,
    expected_prereg_sha: str,
) -> dict[str, Any]:
    require(SHA_RE.fullmatch(expected_freeze_sha) is not None, "freeze_sha")
    require(SHA_RE.fullmatch(expected_prereg_sha) is not None, "prereg_sha")
    raw = read_regular(receipt_path)
    digest = hashlib.sha256(raw).hexdigest()
    expected_sidecar = f"{digest}  {receipt_path.name}\n".encode()
    require(read_regular(sidecar_path) == expected_sidecar, "sidecar_mismatch")
    require(content_path.name == f"{receipt_path.stem}.{digest}.json", "content_name")
    require(read_regular(content_path) == raw, "content_copy_mismatch")
    try:
        value = json.loads(raw)
    except Exception as error:
        raise ValidationError("invalid_json") from error
    require(isinstance(value, dict), "not_mapping")
    require(value.get("schema_version") == SCHEMA, "schema")
    require(value.get("status") == STATUS, "status")
    require(value.get("implementation_freeze", {}).get("sha256") == expected_freeze_sha, "freeze_binding")
    require(value.get("preregistration", {}).get("sha256") == expected_prereg_sha, "prereg_binding")
    tests = value.get("tests", {})
    require(tests.get("combined_tests_run") == 148, "combined_tests")
    require(tests.get("legacy", {}).get("tests_run") == 102, "legacy_tests")
    require(tests.get("legacy", {}).get("ok") is True, "legacy_ok")
    require(tests.get("legacy", {}).get("python_version") == "Python 3.11.14", "legacy_python")
    require(tests.get("v1_3_5", {}).get("tests_run") == 46, "new_tests")
    require(tests.get("v1_3_5", {}).get("ok") is True, "new_ok")
    require(value.get("fold_count") == 5, "fold_count")
    require(value.get("calibrator_invocations_total") == 5, "calibrator_total")
    for key in (
        "optimizer_created", "backward_called", "training_started",
        "run_fold_core_called", "training_output_created", "training_sentinel_exists",
    ):
        require(value.get(key) is False, f"top_false:{key}")
    require(value.get("optimizer_steps") == 0, "top_optimizer_steps")
    folds = value.get("folds")
    require(isinstance(folds, dict) and set(folds) == {str(i) for i in range(5)}, "fold_keys")
    for fold in range(5):
        row = folds[str(fold)]
        require(row.get("calibrator_invocations") == 1, f"fold_calibrator:{fold}")
        require(row.get("same_bytes_for_both_arms") is True, f"fold_arm_bytes:{fold}")
        for key in (
            "optimizer_created", "backward_called", "training_started",
            "run_fold_core_called", "training_output_created",
        ):
            require(row.get(key) is False, f"fold_false:{fold}:{key}")
        require(row.get("optimizer_steps") == 0, f"fold_optimizer_steps:{fold}")
        for key in (
            "materialization_terminal_sha256", "shared_calibration_sha256", "load_only_receipt_sha256",
        ):
            require(SHA_RE.fullmatch(str(row.get(key, ""))) is not None, f"fold_sha:{fold}:{key}")
    return {
        "schema_version": "pvrig.v220.v1_3_5.node1_stage_a_return_validation.v2",
        "status": "PASS_VALIDATED_NODE1_STAGE_A_RECEIPT_NO_TRAINING",
        "source_receipt_sha256": digest,
        "implementation_freeze_sha256": expected_freeze_sha,
        "preregistration_sha256": expected_prereg_sha,
        "fold_count": 5,
        "combined_tests_run": 148,
        "training_authorized": False,
        "training_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--content-copy", type=Path, required=True)
    parser.add_argument("--expected-freeze-sha256", required=True)
    parser.add_argument("--expected-preregistration-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate(
        args.receipt, args.sidecar, args.content_copy,
        args.expected_freeze_sha256, args.expected_preregistration_sha256,
    )
    atomic_json_new(args.output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
