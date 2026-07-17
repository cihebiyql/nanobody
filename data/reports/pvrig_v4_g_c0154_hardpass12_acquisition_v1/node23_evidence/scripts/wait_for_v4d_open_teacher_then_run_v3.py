#!/usr/bin/env python3
"""Immutable V3 waiter for the 72-job V4-G12 acquisition package."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


FIXED_ROOT = Path("/data/qlyu/projects/pvrig_v4_g_c0154_hardpass12_dual_redocking_v1_20260717")
EXPECTED_V2_ANCHOR_SHA256 = "7144e6a6adc0fa72e13c9a4f6edb4bde3913281bdea64e70cd18e2e58d9a4e3b"
EXPECTED_V2_FREEZE_SHA256 = "b15c5b32a0d5f6a00c3abe26bbbb9ee149b48724e0ec7fa08d717eccba352b99"
EXPECTED_V2_STOP_RECEIPT_SHA256 = "0a1ead8e7849ff90dd768e3462be4fddc55c7bbc583cb07a4c35ed314a48c43b"
EXPECTED_V3_ANCHOR_SHA256 = "5b149b478f5550559822a33223ae1fca81d564927e7e7a6b99770cc5c57f9242"
EXPECTED_V3_POLICY_FREEZE_SHA256 = "0ef462a5d7e1b8d73580b9bfb169bb2bf1cd624cde9e91a12d1751024ad7d7ab"

V2_ANCHOR = FIXED_ROOT / "WAITER_TRUST_ANCHOR_V2.json"
V2_FREEZE = FIXED_ROOT / "WAITER_V2_IMPLEMENTATION_FREEZE.json"
V2_STOP = FIXED_ROOT / "status/waiter_v2_stopped_for_v3_security_fix.json"
V3_ANCHOR = FIXED_ROOT / "WAITER_TRUST_ANCHOR_V3.json"
V3_POLICY_FREEZE = FIXED_ROOT / "WAITER_V3_POLICY_FREEZE.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bootstrap_verify(path: Path, expected: str, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError(f"bootstrap_missing:{label}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"bootstrap_nonregular_or_symlink:{label}")
    observed = sha256_file(path)
    if observed != expected:
        raise RuntimeError(f"bootstrap_sha256_mismatch:{label}:{observed}")


def load_object(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"bootstrap_json_not_object:{path.name}")
    return payload


def load_policy(path: Path):
    spec = importlib.util.spec_from_file_location("waiter_v3_policy_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("policy_import_spec_failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def append_log(message: str) -> None:
    with (FIXED_ROOT / "logs/waiter_v3.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{message} {datetime.now(timezone.utc).isoformat()}\n")


def bootstrap():
    # These expected values are literal code constants, never loaded from the
    # mutable artifact they authenticate.
    bootstrap_verify(V2_ANCHOR, EXPECTED_V2_ANCHOR_SHA256, "v2_anchor")
    bootstrap_verify(V2_FREEZE, EXPECTED_V2_FREEZE_SHA256, "v2_freeze")
    bootstrap_verify(V2_STOP, EXPECTED_V2_STOP_RECEIPT_SHA256, "v2_stop_receipt")
    bootstrap_verify(V3_ANCHOR, EXPECTED_V3_ANCHOR_SHA256, "v3_anchor")
    bootstrap_verify(V3_POLICY_FREEZE, EXPECTED_V3_POLICY_FREEZE_SHA256, "v3_policy_freeze")

    anchor = load_object(V3_ANCHOR)
    policy_freeze = load_object(V3_POLICY_FREEZE)
    stop = load_object(V2_STOP)
    if anchor.get("status") != "TRUST_ANCHOR_V3_POLICY_FROZEN_BEFORE_WAITER_GENERATION":
        raise RuntimeError("v3_anchor_status_invalid")
    if policy_freeze.get("status") != "FROZEN_BEFORE_V3_WAITER_GENERATION":
        raise RuntimeError("v3_policy_freeze_status_invalid")
    if policy_freeze.get("trust_anchor_v3_sha256") != EXPECTED_V3_ANCHOR_SHA256:
        raise RuntimeError("v3_policy_freeze_anchor_binding_invalid")
    if policy_freeze.get("v2_trust_anchor_sha256") != EXPECTED_V2_ANCHOR_SHA256:
        raise RuntimeError("v3_policy_freeze_v2_anchor_binding_invalid")
    if policy_freeze.get("v2_implementation_freeze_sha256") != EXPECTED_V2_FREEZE_SHA256:
        raise RuntimeError("v3_policy_freeze_v2_freeze_binding_invalid")
    if policy_freeze.get("waiter_v3_policy_sha256") != anchor["v3_policy"]["sha256"]:
        raise RuntimeError("v3_policy_freeze_policy_binding_invalid")
    if policy_freeze.get("security_tests_sha256") != anchor["v3_policy"]["security_tests_sha256"]:
        raise RuntimeError("v3_policy_freeze_test_binding_invalid")
    if policy_freeze.get("acquisition_protocol_lock_sha256") != anchor["acquisition_protocol_lock"]["sha256"]:
        raise RuntimeError("v3_policy_freeze_protocol_lock_binding_invalid")
    if stop.get("status") != "PASS_V2_STOPPED_BEFORE_ANY_ACQUISITION_WORK":
        raise RuntimeError("v2_stop_receipt_status_invalid")

    policy_path = Path(anchor["v3_policy"]["path"])
    release_verifier = Path(anchor["v3_policy"]["open_teacher_release_verifier_path"])
    security_tests = Path(anchor["v3_policy"]["security_tests_path"])
    bootstrap_verify(policy_path, policy_freeze["waiter_v3_policy_sha256"], "v3_policy")
    bootstrap_verify(release_verifier, policy_freeze["open_teacher_release_verifier_sha256"], "release_verifier")
    bootstrap_verify(security_tests, policy_freeze["security_tests_sha256"], "security_tests")
    policy = load_policy(policy_path)
    return anchor, policy_freeze, policy, release_verifier


def verify_all(anchor: dict, policy_freeze: dict, policy, release_verifier: Path):
    # Recheck immutable V2/V3 roots and every runtime code/input byte on each poll.
    bootstrap_verify(V2_ANCHOR, EXPECTED_V2_ANCHOR_SHA256, "v2_anchor")
    bootstrap_verify(V2_FREEZE, EXPECTED_V2_FREEZE_SHA256, "v2_freeze")
    bootstrap_verify(V2_STOP, EXPECTED_V2_STOP_RECEIPT_SHA256, "v2_stop_receipt")
    bootstrap_verify(V3_ANCHOR, EXPECTED_V3_ANCHOR_SHA256, "v3_anchor")
    bootstrap_verify(V3_POLICY_FREEZE, EXPECTED_V3_POLICY_FREEZE_SHA256, "v3_policy_freeze")
    policy.verify_expected_artifact(
        Path(anchor["v3_policy"]["path"]), policy_freeze["waiter_v3_policy_sha256"], "v3_policy"
    )
    policy.verify_expected_artifact(
        release_verifier, policy_freeze["open_teacher_release_verifier_sha256"], "release_verifier"
    )
    for item in anchor["open_teacher_code_bindings"]:
        policy.verify_expected_artifact(Path(item["path"]), item["sha256"], "open_teacher_code")
    runtime = policy.verify_runtime_identity(anchor, os.environ)
    if Path(sys.executable).resolve(strict=True) != runtime.python_resolved:
        raise policy.GateError("runtime_python_executable_identity_mismatch")
    if os.getpriority(os.PRIO_PROCESS, 0) != int(anchor["controller_execution"]["nice"]):
        raise policy.GateError("runtime_nice_identity_mismatch")
    lock = anchor["acquisition_protocol_lock"]
    closure = policy.verify_protocol_lock(
        runtime.package_root, Path(lock["path"]), lock["sha256"]
    )
    if closure["verified_file_count"] != int(lock["expected_file_count"]):
        raise policy.GateError("protocol_lock_verified_file_count_mismatch")
    if closure["verified_total_bytes"] != int(lock["expected_total_bytes"]):
        raise policy.GateError("protocol_lock_verified_total_bytes_mismatch")
    zero_state = policy.zero_acquisition_state(runtime.package_root)
    external = policy.assess_external_gate(anchor, runtime, release_verifier)
    return runtime, closure, zero_state, external


def main() -> int:
    (FIXED_ROOT / "status").mkdir(exist_ok=True)
    (FIXED_ROOT / "logs").mkdir(exist_ok=True)
    (FIXED_ROOT / "status/waiter_v3.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    try:
        anchor, policy_freeze, policy, release_verifier = bootstrap()
        runtime = policy.verify_runtime_identity(anchor, os.environ)
        append_log("V3_BOOTSTRAP_PASS")
        while True:
            runtime, closure, zero_state, external = verify_all(
                anchor, policy_freeze, policy, release_verifier
            )
            gate = {
                "schema_version": "pvrig_v4_g_c0154_hardpass12_waiter_gate_v3",
                "status": "READY" if external["ready"] else "WAITING",
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                "immutable_trust_chain": "PASS",
                "complete_protocol_lock_closure": closure,
                "zero_acquisition_state": zero_state,
                **external,
            }
            atomic_json(FIXED_ROOT / "status/waiter_gate_v3.json", gate)
            if not external["ready"]:
                append_log("WAIT_V4D_OPEN_TEACHER_TEST32_SEALED_OR_LOAD")
                time.sleep(runtime.poll_seconds)
                continue

            # Final immediate revalidation closes the polling-to-exec gap as far
            # as possible without opening any result or teacher rows.
            runtime, closure, zero_state, external = verify_all(
                anchor, policy_freeze, policy, release_verifier
            )
            if not external["ready"]:
                append_log("FINAL_RECHECK_RETURNED_TO_WAIT")
                continue
            atomic_json(FIXED_ROOT / "status/waiter_gate_v3.json", {
                "schema_version": "pvrig_v4_g_c0154_hardpass12_waiter_gate_v3",
                "status": "PASS_STARTING_ACQUISITION_CONTROLLER",
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                "immutable_trust_chain": "PASS",
                "complete_protocol_lock_closure": closure,
                "zero_acquisition_state": zero_state,
                **external,
            })
            append_log("GATE_V3_PASS_START_ACQUISITION")
            execution = anchor["controller_execution"]
            argv = [
                str(runtime.python_resolved), execution["script"], *execution["argv"],
            ]
            os.execve(
                str(runtime.python_resolved), argv,
                policy.build_controller_environment(anchor, runtime),
            )
    except Exception as exc:  # fail closed before any controller exec
        payload = {
            "schema_version": "pvrig_v4_g_c0154_hardpass12_waiter_failed_closed_v3",
            "status": "FAILED_CLOSED",
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "error_type": type(exc).__name__,
            "reason": str(exc),
            "controller_started": False,
        }
        atomic_json(FIXED_ROOT / "status/waiter_v3.failed_closed.json", payload)
        append_log(f"FAILED_CLOSED {type(exc).__name__}:{exc}")
        return 73
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
