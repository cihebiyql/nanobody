#!/usr/bin/env python3
"""Validate five no-training calibration/load-only folds and publish a receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Sequence


MATERIALIZATION_STATUS = "PASS_V220_SHARED_FOLD_CALIBRATION_MATERIALIZED_NO_TRAINING"
LOAD_ONLY_STATUS = "PASS_V220_V1_3_1_SHARED_CALIBRATION_SEPARATE_PROCESS_LOAD_ONLY"
PREFLIGHT_STATUS = "PASS_NODE1_V220_V1_3_3_FIVE_FOLD_SHARED_CALIBRATION_LOAD_ONLY_NO_TRAINING"
FALSE_FIELDS = (
    "optimizer_created",
    "backward_called",
    "training_started",
)


class PreflightError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PreflightError(message)


def read_regular(path: Path) -> bytes:
    require(path.is_file() and not path.is_symlink(), f"not_regular:{path}")
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    identity = lambda value: (
        value.st_dev, value.st_ino, value.st_mode, value.st_size,
        value.st_mtime_ns, value.st_ctime_ns,
    )
    require(identity(before) == identity(after) and raw, f"unstable_or_empty:{path}")
    return raw


def sha256_file(path: Path) -> str:
    return hashlib.sha256(read_regular(path)).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(read_regular(path))
    except Exception as error:
        raise PreflightError(f"invalid_json:{path}") from error
    require(isinstance(value, dict), f"not_mapping:{path}")
    return value


def atomic_json_new(path: Path, payload: dict[str, Any]) -> str:
    require(not path.exists(), f"output_exists:{path}")
    raw = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        require(not path.exists(), f"output_race:{path}")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    require(read_regular(path) == raw, f"output_replay:{path}")
    return hashlib.sha256(raw).hexdigest()


def parse_test_log(path: Path, expected_tests: int) -> dict[str, Any]:
    text = read_regular(path).decode("utf-8", "strict")
    matches = re.findall(r"^Ran (\d+) tests? in [^\n]+$", text, re.MULTILINE)
    require(matches, f"test_count_missing:{path}")
    require(int(matches[-1]) == expected_tests, f"test_count:{path}")
    require(re.search(r"^OK$", text, re.MULTILINE) is not None, f"test_not_ok:{path}")
    return {"path": str(path), "sha256": sha256_file(path), "tests_run": expected_tests, "ok": True}


def parse_legacy_test_log(path: Path) -> dict[str, Any]:
    parsed = parse_test_log(path, 102)
    text = read_regular(path).decode("utf-8", "strict")
    marker = "PASS_LEGACY_102_PYTHON311_COMPATIBLE python=Python 3.11.14"
    require(text.splitlines().count(marker) == 1, f"legacy_python311_marker:{path}")
    parsed["python_version"] = "Python 3.11.14"
    parsed["compatibility_marker"] = marker
    return parsed


def validate_false_contract(value: dict[str, Any], label: str) -> None:
    for field in FALSE_FIELDS:
        require(value.get(field) is False, f"{label}:{field}")
    require(int(value.get("optimizer_steps", -1)) == 0, f"{label}:optimizer_steps")


def build(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    require(len(args.expected_implementation_freeze_sha256) == 64, "implementation_freeze_sha")
    require(sha256_file(args.implementation_freeze) == args.expected_implementation_freeze_sha256, "implementation_freeze_hash")
    freeze = load_json(args.implementation_freeze)
    require(
        freeze.get("status") == "FROZEN_V1_3_3_IMPLEMENTATION_PENDING_INDEPENDENT_REVIEW_AND_NODE1_PREFLIGHT",
        "implementation_freeze_status",
    )
    require(freeze.get("training_started") is False, "freeze_training_started")
    prereg_sha = sha256_file(args.preregistration)
    require(prereg_sha == freeze["implementation_hashes"]["PREREGISTRATION_PHASE1_TECHNICAL_RECOVERY_V1_3_3.json"], "prereg_hash")
    prereg = load_json(args.preregistration)
    require(prereg["authorization"]["training_authorized"] is False, "prereg_training_authorized")
    legacy = parse_legacy_test_log(args.legacy_test_log)
    new = parse_test_log(args.v1_3_3_test_log, args.expected_new_tests)
    require(not args.training_sentinel.exists(), "training_sentinel_exists")

    folds: dict[str, Any] = {}
    shared_hashes: set[str] = set()
    for fold in range(5):
        shared_dir = args.runtime_root / "shared_calibration" / f"fold_{fold}"
        terminal_path = shared_dir / "MATERIALIZATION_TERMINAL.json"
        rc_path = shared_dir / "MATERIALIZATION_COMMAND.rc"
        artifact_path = shared_dir / "CONTACT_WEIGHT_CALIBRATION.json"
        load_path = args.runtime_root / "load_only" / f"fold_{fold}.json"
        require(read_regular(rc_path).strip() == b"0", f"materializer_rc:fold_{fold}")
        terminal = load_json(terminal_path)
        artifact = load_json(artifact_path)
        loaded = load_json(load_path)
        require(terminal.get("status") == MATERIALIZATION_STATUS, f"materialization_status:fold_{fold}")
        require(loaded.get("status") == LOAD_ONLY_STATUS, f"load_status:fold_{fold}")
        require(int(terminal.get("fold_id", -1)) == fold == int(loaded.get("fold_id", -1)), f"fold_id:{fold}")
        require(int(terminal.get("seed", -1)) == 43 == int(loaded.get("seed", -1)), f"seed:{fold}")
        require(int(terminal.get("calibrator_invocations", -1)) == 1, f"calibrator_count:{fold}")
        validate_false_contract(terminal, f"terminal:{fold}")
        validate_false_contract(loaded, f"load:{fold}")
        require(loaded.get("run_fold_core_called") is False, f"run_fold_core:{fold}")
        require(loaded.get("training_output_created") is False, f"training_output:{fold}")
        require(loaded.get("same_bytes_for_both_arms") is True, f"arm_bytes:{fold}")
        artifact_sha = sha256_file(artifact_path)
        require(terminal.get("shared_calibration_sha256") == artifact_sha, f"terminal_artifact_hash:{fold}")
        for arm in ("C0", "C1"):
            require(loaded["loaded_arms"][arm]["shared_artifact_sha256"] == artifact_sha, f"load_artifact_hash:{fold}:{arm}")
        require(artifact.get("fold_id") == fold and artifact.get("seed") == 43, f"artifact_identity:{fold}")
        require(artifact.get("calibrator_invocations") == 1, f"artifact_calls:{fold}")
        validate_false_contract(artifact, f"artifact:{fold}")
        shared_hashes.add(artifact_sha)
        folds[str(fold)] = {
            "materialization_terminal_sha256": sha256_file(terminal_path),
            "shared_calibration_sha256": artifact_sha,
            "load_only_receipt_sha256": sha256_file(load_path),
            "calibrator_invocations": 1,
            "same_bytes_for_both_arms": True,
            "optimizer_created": False,
            "optimizer_steps": 0,
            "backward_called": False,
            "training_started": False,
            "run_fold_core_called": False,
            "training_output_created": False,
        }
    require(len(folds) == 5 and len(shared_hashes) == 5, "five_distinct_fold_artifacts")
    forbidden = []
    for path in args.runtime_root.rglob("*"):
        if path.is_file() and any(token in path.name for token in ("fold_checkpoint", "fold_predictions", "RESULT.json")):
            forbidden.append(str(path))
    require(not forbidden, "training_artifacts_present")
    payload = {
        "schema_version": "pvrig.v220.v1_3_3_node1_preflight_receipt.v1",
        "status": PREFLIGHT_STATUS,
        "claim_boundary": "Five-fold shared-calibration materialize/load-only preflight; no optimizer, backward, run_fold_core or training.",
        "implementation_freeze": {
            "path": str(args.implementation_freeze),
            "sha256": args.expected_implementation_freeze_sha256,
        },
        "preregistration": {"path": str(args.preregistration), "sha256": prereg_sha},
        "tests": {"legacy": legacy, "v1_3_3": new, "combined_tests_run": 102 + args.expected_new_tests},
        "folds": folds,
        "fold_count": 5,
        "calibrator_invocations_total": 5,
        "optimizer_created": False,
        "optimizer_steps": 0,
        "backward_called": False,
        "training_started": False,
        "run_fold_core_called": False,
        "training_output_created": False,
        "training_sentinel_path": str(args.training_sentinel),
        "training_sentinel_exists": False,
    }
    digest = atomic_json_new(args.output_receipt, payload)
    content_path = args.output_receipt.with_name(f"{args.output_receipt.stem}.{digest}.json")
    require(not content_path.exists(), f"content_receipt_exists:{content_path}")
    content_path.write_bytes(read_regular(args.output_receipt))
    require(sha256_file(content_path) == digest, "content_receipt_hash")
    args.output_receipt.with_suffix(args.output_receipt.suffix + ".sha256").write_text(f"{digest}  {args.output_receipt.name}\n")
    return payload, digest


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--runtime-root", type=Path, required=True)
    value.add_argument("--training-sentinel", type=Path, required=True)
    value.add_argument("--implementation-freeze", type=Path, required=True)
    value.add_argument("--expected-implementation-freeze-sha256", required=True)
    value.add_argument("--preregistration", type=Path, required=True)
    value.add_argument("--legacy-test-log", type=Path, required=True)
    value.add_argument("--v1-3-3-test-log", type=Path, required=True)
    value.add_argument("--expected-new-tests", type=int, required=True)
    value.add_argument("--output-receipt", type=Path, required=True)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    payload, digest = build(args)
    print(json.dumps({"status": payload["status"], "sha256": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
