#!/usr/bin/env python3
"""Consume one V1.2 launch authorization exactly once, then exec the inner launcher.

This is an execution-safety wrapper only.  It does not change the scientific
method, inspect docking results, construct sealed-result paths, or authorize a
launch by itself.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

PRODUCTION_ROOT = Path("/data/qlyu/projects/pvrig_v4_d_dev1_open258_v1_2_20260717")
FREEZE_BASENAME = "phase2_v4_d_dev1_open258_v1_2_launch_authorized_freeze.json"
SELF_BASENAME = "run_phase2_v4_d_dev1_open258_v1_2_once.py"
INNER_BASENAME = "run_phase2_v4_d_dev1_open258_v1_2_node23.sh"
MARKER_RELATIVE_PATH = Path("attempts/v1_2_attempt_001_consumed.json")
EXPECTED_FREEZE_STATUS = "FROZEN_FOR_DEV1_V1_2_REMOTE_EXECUTION"
EXPECTED_INNER_SHA256 = "2fb5c83ef3758ffaf5b6fa3a7e08db3a8656f66a79d88464c38aa2b13a8f77ae"
EXPECTED_CANDIDATE_FREEZE_SHA256 = "443df675d107d7d8e7de93e72c37f98c5bb4c7fe16462e0aed2276c892a03039"
EXPECTED_IMPLEMENTATION_REVIEW_SHA256 = "d6c71796b4b10ecb255a5348b2aeac715af8fc79aad9d4201a5dd2d5dfeab4d1"


class OneShotLaunchError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OneShotLaunchError(message)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_snapshot(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise OneShotLaunchError(f"unable_to_open_snapshot:{label}:{path}") from exc
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode), f"snapshot_not_regular:{label}")
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        identity = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        require(identity(before) == identity(after), f"snapshot_changed_during_read:{label}")
        require(len(raw) == before.st_size, f"snapshot_size_changed_during_read:{label}")
        return raw
    finally:
        os.close(fd)


def strict_json(raw: bytes, label: str) -> Mapping[str, Any]:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in output, f"duplicate_json_key:{label}:{key}")
            output[key] = value
        return output

    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OneShotLaunchError(f"invalid_json:{label}") from exc
    require(isinstance(payload, Mapping), f"json_not_object:{label}")
    return payload


def create_sealed_exec_snapshot(raw: bytes) -> tuple[int, str]:
    """Return an inheritable, write-sealed memfd containing exact launcher bytes."""
    require(hasattr(os, "memfd_create"), "memfd_create_unavailable")
    allow_sealing = getattr(os, "MFD_ALLOW_SEALING", None)
    require(isinstance(allow_sealing, int), "memfd_sealing_unavailable")
    required_names = (
        "F_ADD_SEALS",
        "F_GET_SEALS",
        "F_SEAL_SEAL",
        "F_SEAL_SHRINK",
        "F_SEAL_GROW",
        "F_SEAL_WRITE",
    )
    require(all(hasattr(fcntl, name) for name in required_names), "fcntl_sealing_unavailable")
    try:
        fd = os.memfd_create("pvrig_v4d_dev1_v1_2_inner", allow_sealing)
    except OSError as exc:
        raise OneShotLaunchError("unable_to_create_inner_exec_snapshot") from exc
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            require(written > 0, "inner_exec_snapshot_short_write")
            offset += written
        os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        seals = (
            fcntl.F_SEAL_SEAL
            | fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_WRITE
        )
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, seals)
        applied = fcntl.fcntl(fd, fcntl.F_GET_SEALS)
        require(applied & seals == seals, "inner_exec_snapshot_not_fully_sealed")
        os.set_inheritable(fd, True)
        require(os.get_inheritable(fd), "inner_exec_snapshot_not_inheritable")
        return fd, f"/proc/self/fd/{fd}"
    except Exception:
        os.close(fd)
        raise


def expected_paths(root: Path) -> dict[str, Path]:
    return {
        "freeze": root / "governance" / FREEZE_BASENAME,
        "one_shot_launcher": root / "scripts" / SELF_BASENAME,
        "launcher": root / "scripts" / INNER_BASENAME,
        "marker": root / MARKER_RELATIVE_PATH,
    }


def validate_authorization(
    freeze: Mapping[str, Any],
    *,
    freeze_sha256: str,
    expected_freeze_sha256: str,
    self_sha256: str,
    inner_sha256: str,
    paths: Mapping[str, Path],
) -> None:
    require(re.fullmatch(r"[0-9a-f]{64}", expected_freeze_sha256) is not None, "expected_freeze_sha256_invalid")
    require(freeze_sha256 == expected_freeze_sha256, "freeze_sha256_mismatch")
    require(freeze.get("status") == EXPECTED_FREEZE_STATUS, "freeze_status_invalid")
    require(freeze.get("remote_execution_authorized") is True, "remote_execution_not_authorized")
    require(
        type(freeze.get("attempt_limit")) is int and freeze.get("attempt_limit") == 1,
        "attempt_limit_not_one",
    )
    require(freeze.get("retry_authorized") is False, "retry_authorized_not_false")
    require(freeze.get("teacher_materialization_authorized") is True, "teacher_materialization_not_authorized")
    require(freeze.get("teacher_release_requires_runtime_gates") is True, "runtime_gates_not_required")
    require(freeze.get("formal_v4_f_unlock_eligible") is False, "formal_unlock_true")
    require(freeze.get("source_evaluator_status") == "FAIL", "source_evaluator_status_not_fail")
    require(freeze.get("source_evaluator_unlockable") is False, "source_evaluator_unlockable_not_false")
    for field in (
        "test32_raw_job_files_opened",
        "test32_metric_values_read",
        "test32_label_rows_emitted",
    ):
        require(
            type(freeze.get(field)) is int and freeze.get(field) == 0,
            f"sealed_boundary_nonzero:{field}",
        )
    require(freeze.get("attempt_marker_path") == str(paths["marker"]), "attempt_marker_path_invalid")
    require(freeze.get("candidate_implementation_freeze_sha256") == EXPECTED_CANDIDATE_FREEZE_SHA256, "candidate_freeze_binding_invalid")
    require(freeze.get("independent_implementation_review_sha256") == EXPECTED_IMPLEMENTATION_REVIEW_SHA256, "implementation_review_binding_invalid")
    files = freeze.get("files")
    require(isinstance(files, Mapping), "freeze_files_missing")
    for key, path, digest in (
        ("one_shot_launcher", paths["one_shot_launcher"], self_sha256),
        ("launcher", paths["launcher"], inner_sha256),
    ):
        binding = files.get(key)
        require(isinstance(binding, Mapping), f"freeze_file_binding_missing:{key}")
        require(binding.get("path") == str(path), f"freeze_file_path_invalid:{key}")
        require(binding.get("sha256") == digest, f"freeze_file_sha256_invalid:{key}")
    require(inner_sha256 == EXPECTED_INNER_SHA256, "inner_launcher_not_frozen_v1_2_bytecode")


def consume_attempt_marker(
    root: Path,
    *,
    freeze_sha256: str,
    self_sha256: str,
    inner_sha256: str,
) -> Path:
    root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        root_fd = os.open(root, root_flags)
    except OSError as exc:
        raise OneShotLaunchError(f"unable_to_open_production_root:{root}") from exc
    try:
        require(stat.S_ISDIR(os.fstat(root_fd).st_mode), "production_root_not_directory")
        try:
            os.mkdir("attempts", mode=0o750, dir_fd=root_fd)
            os.fsync(root_fd)
        except FileExistsError:
            pass
        try:
            attempts_fd = os.open("attempts", root_flags, dir_fd=root_fd)
        except OSError as exc:
            raise OneShotLaunchError("unable_to_open_attempts_directory") from exc
        try:
            marker_name = MARKER_RELATIVE_PATH.name
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                marker_fd = os.open(marker_name, flags, 0o600, dir_fd=attempts_fd)
            except FileExistsError as exc:
                raise OneShotLaunchError("one_shot_attempt_already_consumed") from exc
            except OSError as exc:
                raise OneShotLaunchError("unable_to_create_attempt_marker") from exc
            try:
                marker = {
                    "schema_version": "phase2_v4_d_dev1_open258_v1_2_attempt_marker_v1",
                    "status": "V1_2_ATTEMPT_001_CONSUMED_BEFORE_INNER_EXEC",
                    "attempt": 1,
                    "consumed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "freeze_sha256": freeze_sha256,
                    "one_shot_launcher_sha256": self_sha256,
                    "inner_launcher_sha256": inner_sha256,
                    "retry_authorized": False,
                    "formal_v4_f_unlock_eligible": False,
                }
                raw = (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode("utf-8")
                offset = 0
                while offset < len(raw):
                    written = os.write(marker_fd, raw[offset:])
                    require(written > 0, "attempt_marker_short_write")
                    offset += written
                os.fsync(marker_fd)
            finally:
                os.close(marker_fd)
            os.fsync(attempts_fd)
        finally:
            os.close(attempts_fd)
        os.fsync(root_fd)
    finally:
        os.close(root_fd)
    return root / MARKER_RELATIVE_PATH


def execute_once(
    freeze_path: Path,
    expected_freeze_sha256: str,
    *,
    root: Path = PRODUCTION_ROOT,
    self_path: Path | None = None,
    execve: Callable[[str, list[str], dict[str, str]], Any] = os.execve,
    environ: Mapping[str, str] | None = None,
) -> None:
    paths = expected_paths(root)
    self_path = Path(__file__) if self_path is None else self_path
    require(freeze_path == paths["freeze"], "freeze_path_not_canonical")
    require(self_path == paths["one_shot_launcher"], "one_shot_launcher_path_not_canonical")

    # All authority-bearing files are snapshotted before validation and before
    # the irreversible attempt marker is created.
    freeze_raw = read_snapshot(freeze_path, "freeze")
    self_raw = read_snapshot(self_path, "one_shot_launcher")
    inner_raw = read_snapshot(paths["launcher"], "inner_launcher")
    freeze_sha = sha256_bytes(freeze_raw)
    self_sha = sha256_bytes(self_raw)
    inner_sha = sha256_bytes(inner_raw)
    freeze = strict_json(freeze_raw, "freeze")
    validate_authorization(
        freeze,
        freeze_sha256=freeze_sha,
        expected_freeze_sha256=expected_freeze_sha256,
        self_sha256=self_sha,
        inner_sha256=inner_sha,
        paths=paths,
    )
    inner_exec_fd, inner_exec_path = create_sealed_exec_snapshot(inner_raw)
    try:
        consume_attempt_marker(
            root,
            freeze_sha256=freeze_sha,
            self_sha256=self_sha,
            inner_sha256=inner_sha,
        )
        environment = dict(os.environ if environ is None else environ)
        environment["PVRIG_V4D_DEV1_V12_ROOT"] = str(root)
        environment["PVRIG_V4D_DEV1_V12_LAUNCH_FREEZE"] = str(freeze_path)
        execve("/bin/bash", ["/bin/bash", inner_exec_path], environment)
        raise OneShotLaunchError("inner_execve_returned_unexpectedly")
    finally:
        os.close(inner_exec_fd)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", required=True, type=Path)
    parser.add_argument("--expected-freeze-sha", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    execute_once(args.freeze, args.expected_freeze_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
