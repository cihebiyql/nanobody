#!/usr/bin/env python3
"""Fail-closed shared calibration artifact primitives for V2.20 V1.3.

This module does not train a model.  It freezes the lifecycle contract that one
calibration call creates one content-addressed fold artifact and both arms read
the exact same bytes before optimizer creation.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping


SCHEMA_VERSION = "pvrig.v220.shared_fold_calibration_artifact.v1"
PASS_STATUS = "PASS_CONTACT_WEIGHT_CALIBRATED_NO_OPTIMIZER"
ARTIFACT_STATUS = "PASS_V220_SHARED_FOLD_CALIBRATION_MATERIALIZED_NO_TRAINING"
LAMBDA_GRID = (0.00015625, 0.0003125, 0.000625, 0.00125, 0.0025)
CONTACT_BATCH_COUNT = 8
MAX_SEVERE_CONFLICT_BATCHES = 2
SEED = 43
ARMS = ("C0", "C1")


class SharedCalibrationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SharedCalibrationError(message)


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_mapping_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return sha256_bytes(payload)


def fold_frozen_bindings(
    *,
    upstream_runner_sha256: str,
    input_bindings: Mapping[str, Any],
    expected_initial_state_sha256: str,
    expected_initial_state_receipt_sha256: str,
) -> dict[str, str]:
    """Reduce the unchanged V1.2 fold inputs to a closed hash map."""

    return {
        "upstream_v1_2_runner": _sha_string(
            upstream_runner_sha256, "upstream_v1_2_runner"
        ),
        "fold_input_bindings": canonical_mapping_sha256(dict(input_bindings)),
        "initial_state": _sha_string(expected_initial_state_sha256, "initial_state"),
        "initial_state_receipt": _sha_string(
            expected_initial_state_receipt_sha256, "initial_state_receipt"
        ),
    }


def read_regular_snapshot(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise SharedCalibrationError(f"open_failed:{path}") from error
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode), f"not_regular:{path}")
        require(before.st_size > 0, f"empty:{path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        require(identity(before) == identity(after), f"changed_during_read:{path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def atomic_json_new(path: Path, payload: Mapping[str, Any]) -> str:
    require(not path.exists(), f"output_exists:{path}")
    raw = canonical_json_bytes(payload)
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
    require(read_regular_snapshot(path) == raw, f"json_replay:{path}")
    return sha256_bytes(raw)


def _sha_string(value: Any, label: str) -> str:
    require(isinstance(value, str) and len(value) == 64, f"invalid_sha:{label}")
    require(all(char in "0123456789abcdef" for char in value), f"invalid_sha:{label}")
    return value


def validate_calibration_payload(
    calibration: Mapping[str, Any],
    *,
    expected_model_state_sha256: str,
    expected_shared_parameter_order_sha256: str,
) -> None:
    require(calibration.get("status") == PASS_STATUS, "calibration_status")
    require(int(calibration.get("contact_batch_count", -1)) == CONTACT_BATCH_COUNT, "contact_batch_count")
    require(tuple(calibration.get("lambda_grid", ())) == LAMBDA_GRID, "lambda_grid")
    require(float(calibration.get("selected_contact_weight", -1.0)) in LAMBDA_GRID, "selected_lambda")
    require(
        int(calibration.get("severe_conflict_batch_count", 999))
        <= MAX_SEVERE_CONFLICT_BATCHES,
        "conflict_gate",
    )
    require(calibration.get("optimizer_created") is False, "optimizer_created")
    require(int(calibration.get("optimizer_steps", -1)) == 0, "optimizer_steps")
    require(calibration.get("training_started") is False, "training_started")
    if "backward_called" in calibration:
        require(calibration.get("backward_called") is False, "backward_called")
    before = _sha_string(calibration.get("model_state_sha256_before"), "model_before")
    after = _sha_string(calibration.get("model_state_sha256_after"), "model_after")
    require(before == after, "calibration_mutated_model")
    require(before == expected_model_state_sha256, "initial_model_state_binding")
    order = _sha_string(
        calibration.get("shared_parameter_order_sha256"), "shared_parameter_order"
    )
    require(order == expected_shared_parameter_order_sha256, "shared_parameter_order_binding")


def materialize_shared_calibration_once(
    *,
    output_path: Path,
    fold_id: int,
    calibration_fn: Callable[[], Mapping[str, Any]],
    frozen_bindings: Mapping[str, str],
    expected_model_state_sha256: str,
    expected_shared_parameter_order_sha256: str,
) -> tuple[str, bytes]:
    require(fold_id in range(5), "fold_id")
    require(not output_path.exists(), f"output_exists:{output_path}")
    require(bool(frozen_bindings), "frozen_bindings_empty")
    normalized_bindings = {
        str(label): _sha_string(value, f"binding:{label}")
        for label, value in sorted(frozen_bindings.items())
    }
    calibration = dict(calibration_fn())
    validate_calibration_payload(
        calibration,
        expected_model_state_sha256=expected_model_state_sha256,
        expected_shared_parameter_order_sha256=expected_shared_parameter_order_sha256,
    )
    # Keep the calibration fields top-level.  The unchanged V1.2 fold runner
    # consumes selected_contact_weight directly and serializes this mapping.
    # A flat artifact therefore lets each V1.3 arm replay these exact bytes
    # without changing the frozen loss implementation.
    artifact = dict(calibration)
    artifact.update({
        "shared_artifact_schema_version": SCHEMA_VERSION,
        "shared_artifact_status": ARTIFACT_STATUS,
        "fold_id": fold_id,
        "seed": SEED,
        "calibrator_invocations": 1,
        "optimizer_created": False,
        "optimizer_steps": 0,
        "backward_called": False,
        "training_started": False,
        "frozen_bindings": normalized_bindings,
    })
    raw = canonical_json_bytes(artifact)
    atomic_json_new(output_path, artifact)
    replay = read_regular_snapshot(output_path)
    require(replay == raw, "materialized_byte_replay")
    return sha256_bytes(raw), raw


def load_shared_calibration_for_arm(
    *,
    artifact_path: Path,
    expected_artifact_sha256: str,
    fold_id: int,
    arm: str,
    frozen_bindings: Mapping[str, str],
    expected_model_state_sha256: str,
    expected_shared_parameter_order_sha256: str,
    optimizer_created: bool,
    backward_called: bool,
    training_started: bool,
) -> tuple[dict[str, Any], bytes]:
    require(arm in ARMS, "arm")
    require(not optimizer_created, "arm_optimizer_created_before_calibration_validation")
    require(not backward_called, "arm_backward_before_calibration_validation")
    require(not training_started, "arm_training_started_before_calibration_validation")
    raw = read_regular_snapshot(artifact_path)
    require(sha256_bytes(raw) == expected_artifact_sha256, "artifact_sha256")
    try:
        artifact = json.loads(raw)
    except Exception as error:
        raise SharedCalibrationError("artifact_json") from error
    require(isinstance(artifact, dict), "artifact_mapping")
    require(artifact.get("shared_artifact_schema_version") == SCHEMA_VERSION, "artifact_schema")
    require(artifact.get("shared_artifact_status") == ARTIFACT_STATUS, "artifact_status")
    require(int(artifact.get("fold_id", -1)) == fold_id, "artifact_fold")
    require(int(artifact.get("seed", -1)) == SEED, "artifact_seed")
    require(int(artifact.get("calibrator_invocations", -1)) == 1, "calibrator_invocations")
    require(artifact.get("optimizer_created") is False, "artifact_optimizer_created")
    require(int(artifact.get("optimizer_steps", -1)) == 0, "artifact_optimizer_steps")
    require(artifact.get("backward_called") is False, "artifact_backward_called")
    require(artifact.get("training_started") is False, "artifact_training_started")
    expected_bindings = {
        str(label): _sha_string(value, f"expected_binding:{label}")
        for label, value in sorted(frozen_bindings.items())
    }
    require(artifact.get("frozen_bindings") == expected_bindings, "artifact_bindings")
    validate_calibration_payload(
        artifact,
        expected_model_state_sha256=expected_model_state_sha256,
        expected_shared_parameter_order_sha256=expected_shared_parameter_order_sha256,
    )
    return artifact, raw


def copy_exact_artifact_to_arm(*, raw: bytes, output_path: Path, expected_sha256: str) -> None:
    require(not output_path.exists(), f"arm_calibration_output_exists:{output_path}")
    require(sha256_bytes(raw) == expected_sha256, "arm_copy_input_sha256")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            output_path.unlink()
        except FileNotFoundError:
            pass
        raise
    require(sha256_bytes(read_regular_snapshot(output_path)) == expected_sha256, "arm_copy_sha256")
