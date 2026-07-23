#!/usr/bin/env python3
"""Render a gated V1.3.2 training launcher after preflight and approval.

This program never imports the training runner, creates an optimizer, or starts
training.  It only validates immutable evidence and creates a launcher plus a
final authorization document in a previously absent directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Sequence


PREFLIGHT_STATUS = "PASS_NODE1_V220_V1_3_2_FIVE_FOLD_SHARED_CALIBRATION_LOAD_ONLY_NO_TRAINING"
APPROVAL_STATUS = "APPROVE_V220_V1_3_2_TECHNICAL_RECOVERY_TRAINING"
FREEZE_STATUS = "FROZEN_V1_3_2_IMPLEMENTATION_PENDING_INDEPENDENT_REVIEW_AND_NODE1_PREFLIGHT"


class FinalizationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FinalizationError(message)


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
        raise FinalizationError(f"invalid_json:{path}") from error
    require(isinstance(value, dict), f"not_mapping:{path}")
    return value


def validate_package_closure(
    package_root: Path,
    freeze_path: Path,
    freeze_sha: str,
    expected: Sequence[str],
    implementation_hashes: dict[str, str],
) -> None:
    expected_set = set(expected)
    require(len(expected_set) == len(expected) and expected_set, "package_allowlist")
    observed: set[str] = set()
    for path in package_root.rglob("*"):
        relative = path.relative_to(package_root)
        require(not path.is_symlink(), f"package_symlink:{relative}")
        if path.is_file():
            observed.add(relative.as_posix())
    require(observed == expected_set, f"package_allowlist_drift:{sorted(observed ^ expected_set)}")
    try:
        freeze_relative = freeze_path.resolve(strict=True).relative_to(package_root).as_posix()
    except ValueError as error:
        raise FinalizationError("freeze_outside_package") from error
    sidecar_relative = freeze_relative + ".sha256"
    require(
        expected_set - set(implementation_hashes) == {freeze_relative, sidecar_relative}
        and set(implementation_hashes) <= expected_set,
        "package_hash_closure",
    )
    sidecar = package_root / sidecar_relative
    require(
        read_regular(sidecar) == f"{freeze_sha}  {Path(freeze_relative).name}\n".encode(),
        "freeze_sidecar",
    )


def escaped_double_quoted(value: str) -> str:
    require("\n" not in value and "\r" not in value, "unsafe_path_newline")
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")


def validate_preflight(value: dict[str, Any], *, freeze_sha: str, prereg_sha: str) -> None:
    require(value.get("status") == PREFLIGHT_STATUS, "preflight_status")
    require(value.get("implementation_freeze", {}).get("sha256") == freeze_sha, "preflight_freeze_binding")
    require(value.get("preregistration", {}).get("sha256") == prereg_sha, "preflight_prereg_binding")
    require(int(value.get("fold_count", -1)) == 5, "preflight_fold_count")
    require(int(value.get("calibrator_invocations_total", -1)) == 5, "preflight_calibrator_count")
    for field in ("optimizer_created", "backward_called", "training_started", "run_fold_core_called", "training_output_created"):
        require(value.get(field) is False, f"preflight_{field}")
    require(int(value.get("optimizer_steps", -1)) == 0, "preflight_optimizer_steps")
    require(value.get("training_sentinel_exists") is False, "preflight_training_sentinel")
    folds = value.get("folds")
    require(isinstance(folds, dict) and set(folds) == {str(i) for i in range(5)}, "preflight_folds")
    for fold, evidence in folds.items():
        require(evidence.get("calibrator_invocations") == 1, f"fold_calls:{fold}")
        require(evidence.get("same_bytes_for_both_arms") is True, f"fold_arm_bytes:{fold}")
        for field in ("optimizer_created", "backward_called", "training_started", "run_fold_core_called", "training_output_created"):
            require(evidence.get(field) is False, f"fold_{fold}_{field}")
        require(evidence.get("optimizer_steps") == 0, f"fold_{fold}_optimizer_steps")


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    package_root = args.package_root.resolve(strict=True)
    freeze_sha = sha256_file(args.implementation_freeze)
    prereg_sha = sha256_file(args.preregistration)
    preflight_sha = sha256_file(args.preflight_receipt)
    approval_sha = sha256_file(args.approval_receipt)
    require(freeze_sha == args.expected_implementation_freeze_sha256, "freeze_sha256")
    require(prereg_sha == args.expected_preregistration_sha256, "prereg_sha256")
    require(preflight_sha == args.expected_preflight_receipt_sha256, "preflight_sha256")
    require(approval_sha == args.expected_approval_receipt_sha256, "approval_sha256")

    freeze = load_json(args.implementation_freeze)
    prereg = load_json(args.preregistration)
    preflight = load_json(args.preflight_receipt)
    approval = load_json(args.approval_receipt)
    require(freeze.get("status") == FREEZE_STATUS, "freeze_status")
    require(freeze.get("training_authorized") is False, "freeze_training_authorized")
    require(freeze.get("training_started") is False, "freeze_training_started")
    require(prereg.get("authorization", {}).get("training_authorized") is False, "prereg_training_authorized")
    require(
        freeze.get("implementation_hashes", {}).get("PREREGISTRATION_PHASE1_TECHNICAL_RECOVERY_V1_3_2.json") == prereg_sha,
        "freeze_prereg_binding",
    )
    validate_package_closure(
        package_root,
        args.implementation_freeze,
        freeze_sha,
        freeze.get("package_file_allowlist", []),
        freeze.get("implementation_hashes", {}),
    )
    for relative, digest in freeze.get("implementation_hashes", {}).items():
        path = package_root / relative
        require(sha256_file(path) == digest, f"implementation_hash:{relative}")
    validate_preflight(preflight, freeze_sha=freeze_sha, prereg_sha=prereg_sha)
    require(approval.get("status") == APPROVAL_STATUS, "approval_status")
    require(approval.get("approved") is True, "approval_false")
    require(approval.get("implementation_freeze_sha256") == freeze_sha, "approval_freeze_binding")
    require(approval.get("preregistration_sha256") == prereg_sha, "approval_prereg_binding")
    require(approval.get("preflight_receipt_sha256") == preflight_sha, "approval_preflight_binding")
    template = package_root / "launchers/run_phase1_core_fold_pair_node1_v1_3_2.template.sh"
    template_sha = sha256_file(template)
    require(approval.get("training_template_sha256") == template_sha, "approval_template_binding")
    hashes = freeze["implementation_hashes"]
    replacements = {
        "__V220_FINALIZATION_STATE__": "FINALIZED_V220_V1_3_2",
        "__V220_PACKAGE_ROOT__": escaped_double_quoted(str(package_root)),
        "__V220_IMPLEMENTATION_FREEZE__": escaped_double_quoted(str(args.implementation_freeze.resolve())),
        "__V220_IMPLEMENTATION_FREEZE_SHA__": freeze_sha,
        "__V220_PREREGISTRATION__": escaped_double_quoted(str(args.preregistration.resolve())),
        "__V220_PREREGISTRATION_SHA__": prereg_sha,
        "__V220_PREFLIGHT_RECEIPT__": escaped_double_quoted(str(args.preflight_receipt.resolve())),
        "__V220_PREFLIGHT_RECEIPT_SHA__": preflight_sha,
        "__V220_APPROVAL_RECEIPT__": escaped_double_quoted(str(args.approval_receipt.resolve())),
        "__V220_APPROVAL_RECEIPT_SHA__": approval_sha,
        "__V220_HELPER_SHA__": hashes["launchers/run_shared_fold_materialization_once_v1_3_1.sh"],
        "__V220_MATERIALIZER_SHA__": hashes["src/materialize_v220_shared_fold_calibration_v1_3_1.py"],
        "__V220_ARM_RUNNER_SHA__": hashes["src/run_v220_contact_shared_fold_v1_3_1.py"],
    }
    rendered = read_regular(template).decode("utf-8")
    for marker, value in replacements.items():
        require(rendered.count(marker) >= 1, f"template_marker:{marker}")
        rendered = rendered.replace(marker, value)
    for marker in replacements:
        require(marker not in rendered, f"unresolved_template_marker:{marker}")
    require(not args.output_dir.exists(), "output_dir_exists")
    args.output_dir.mkdir(parents=False)
    launcher = args.output_dir / "run_phase1_core_fold_pair_node1_v1_3_2.sh"
    descriptor = os.open(launcher, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o500)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(rendered)
        handle.flush()
        os.fsync(handle.fileno())
    launcher_sha = sha256_file(launcher)
    authorization = {
        "schema_version": "pvrig.v220.v1_3_2_final_training_authorization.v1",
        "status": "FINAL_AUTHORIZED_V220_V1_3_2_TEN_FRESH_ARMS",
        "training_authorized": True,
        "training_started": False,
        "implementation_freeze_sha256": freeze_sha,
        "preregistration_sha256": prereg_sha,
        "preflight_receipt_sha256": preflight_sha,
        "approval_receipt_sha256": approval_sha,
        "training_template_sha256": template_sha,
        "training_launcher_sha256": launcher_sha,
        "all_ten_arms_fresh_required": True,
        "old_training_outputs_allowed": False,
        "method_data_split_gates_hyperparameters_unchanged": True,
        "finalizer_training_started": False,
        "finalizer_optimizer_created": False,
        "finalizer_backward_called": False,
    }
    auth_path = args.output_dir / "FINAL_TRAINING_AUTHORIZATION_V1_3_2.json"
    raw = (json.dumps(authorization, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    descriptor = os.open(auth_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    authorization["authorization_sha256"] = sha256_file(auth_path)
    return authorization


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--package-root", type=Path, required=True)
    value.add_argument("--implementation-freeze", type=Path, required=True)
    value.add_argument("--expected-implementation-freeze-sha256", required=True)
    value.add_argument("--preregistration", type=Path, required=True)
    value.add_argument("--expected-preregistration-sha256", required=True)
    value.add_argument("--preflight-receipt", type=Path, required=True)
    value.add_argument("--expected-preflight-receipt-sha256", required=True)
    value.add_argument("--approval-receipt", type=Path, required=True)
    value.add_argument("--expected-approval-receipt-sha256", required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    result = finalize(parser().parse_args(argv))
    print(json.dumps({"status": result["status"], "authorization_sha256": result["authorization_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
