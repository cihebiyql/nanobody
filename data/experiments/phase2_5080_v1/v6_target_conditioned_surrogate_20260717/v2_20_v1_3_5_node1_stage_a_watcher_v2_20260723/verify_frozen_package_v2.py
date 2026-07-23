#!/usr/bin/env python3
"""Read-only verification for the frozen V1.3.5 Stage-A package."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


FREEZE_NAME = "IMPLEMENTATION_FREEZE_PHASE1_TECHNICAL_RECOVERY_V1_3_5.json"
FREEZE_STATUS = "FROZEN_V1_3_5_IMPLEMENTATION_PENDING_INDEPENDENT_REVIEW_AND_NODE1_PREFLIGHT"
APPROVAL_STATUS = "PASS_V1_3_5_INDEPENDENT_REVIEW_STAGE_A_PREFLIGHT_ONLY_AUTHORIZED"


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def read_regular(path: Path) -> bytes:
    require(path.is_file() and not path.is_symlink(), f"not_regular:{path}")
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    identity = lambda value: (
        value.st_dev, value.st_ino, value.st_mode, value.st_size,
        value.st_mtime_ns, value.st_ctime_ns,
    )
    require(raw and identity(before) == identity(after), f"unstable_or_empty:{path}")
    return raw


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_mapping(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except Exception as error:
        raise VerificationError(f"invalid_json:{label}") from error
    require(isinstance(value, dict), f"not_mapping:{label}")
    return value


def verify_package(root: Path, expected_freeze_sha: str) -> dict[str, Any]:
    require(len(expected_freeze_sha) == 64, "expected_freeze_sha")
    require(root.is_dir() and not root.is_symlink(), f"package_not_directory:{root}")
    freeze_path = root / FREEZE_NAME
    freeze_raw = read_regular(freeze_path)
    require(sha(freeze_raw) == expected_freeze_sha, "freeze_hash")
    freeze = load_mapping(freeze_raw, "freeze")
    require(freeze.get("status") == FREEZE_STATUS, "freeze_status")
    require(freeze.get("training_authorized") is False, "freeze_training_authorized")
    require(freeze.get("training_started") is False, "freeze_training_started")

    allowlist_value = freeze.get("package_file_allowlist")
    require(isinstance(allowlist_value, list), "allowlist_type")
    require(len(allowlist_value) == len(set(allowlist_value)), "allowlist_duplicates")
    expected = set(allowlist_value)
    observed: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        require(not path.is_symlink(), f"symlink:{relative}")
        require(path.name != "__pycache__" and path.suffix != ".pyc", f"cache:{relative}")
        if path.is_file():
            observed.add(relative)
    require(observed == expected, f"allowlist_mismatch:{sorted(observed - expected)}:{sorted(expected - observed)}")

    sidecar_name = f"{FREEZE_NAME}.sha256"
    expected_implementation = expected - {FREEZE_NAME, sidecar_name}
    implementation = freeze.get("implementation_hashes")
    require(isinstance(implementation, dict), "implementation_hashes_type")
    require(set(implementation) == expected_implementation, "implementation_hash_keys")
    for relative, digest in implementation.items():
        require(sha(read_regular(root / relative)) == digest, f"implementation_hash:{relative}")
    require(
        read_regular(root / sidecar_name) == f"{expected_freeze_sha}  {FREEZE_NAME}\n".encode(),
        "freeze_sidecar",
    )
    return {
        "status": "PASS_EXACT_FROZEN_V1_3_5_PACKAGE",
        "implementation_freeze_sha256": expected_freeze_sha,
        "file_count": len(expected),
        "training_authorized": False,
        "training_started": False,
    }


def verify_approval(path: Path, expected_sha: str, expected_freeze_sha: str, expected_prereg_sha: str) -> dict[str, Any]:
    raw = read_regular(path)
    require(sha(raw) == expected_sha, "approval_hash")
    value = load_mapping(raw, "approval")
    require(value.get("status") == APPROVAL_STATUS, "approval_status")
    require(value.get("implementation_freeze_sha256") == expected_freeze_sha, "approval_freeze")
    require(value.get("preregistration_sha256") == expected_prereg_sha, "approval_prereg")
    authorization = value.get("authorization", {})
    require(authorization.get("independent_review_passed") is True, "approval_independent_review")
    require(authorization.get("node1_stage_a_preflight_execution_authorized") is True, "approval_stage_a")
    require(authorization.get("stage_a_only_package_deployment_authorized") is True, "approval_deployment")
    require(authorization.get("training_authorized") is False, "approval_training_authorized")
    require(authorization.get("training_started") is False, "approval_training_started")
    return {
        "status": "PASS_EXACT_STAGE_A_ONLY_APPROVAL",
        "approval_sha256": expected_sha,
        "training_authorized": False,
        "training_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--expected-freeze-sha256", required=True)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--expected-approval-sha256")
    parser.add_argument("--expected-preregistration-sha256")
    args = parser.parse_args()
    payload = {"package": verify_package(args.package_root, args.expected_freeze_sha256)}
    if args.approval is not None:
        require(args.expected_approval_sha256 is not None, "missing_expected_approval_sha")
        require(args.expected_preregistration_sha256 is not None, "missing_expected_prereg_sha")
        payload["approval"] = verify_approval(
            args.approval,
            args.expected_approval_sha256,
            args.expected_freeze_sha256,
            args.expected_preregistration_sha256,
        )
    payload["status"] = "PASS_STAGE_A_LOCAL_OR_REMOTE_IDENTITY_GATE"
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
