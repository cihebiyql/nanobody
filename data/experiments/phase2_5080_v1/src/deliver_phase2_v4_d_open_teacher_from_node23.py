#!/usr/bin/env python3
"""Fail-closed, content-addressed Node23 -> WSL delivery for the V4-D open teacher.

This process transports only the already released OPEN_TRAIN/OPEN_DEVELOPMENT
teacher bundle.  It never requests or opens prospective-test or V4-F labels.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Callable, Iterable, Mapping, Sequence


SCHEMA_VERSION = "phase2_v4_d_open_teacher_delivery_v1"
CLAIM_BOUNDARY = (
    "Read-only transport of a computational dual-conformation geometry teacher; "
    "not binding, affinity, competition, experimental blocking, or Docking Gold."
)
CANONICAL_EXP_DIR = Path("/mnt/d/work/抗体/data/experiments/phase2_5080_v1")
CANONICAL_SCRIPT = CANONICAL_EXP_DIR / "src/deliver_phase2_v4_d_open_teacher_from_node23.py"
CANONICAL_PREREG = (
    CANONICAL_EXP_DIR
    / "audits/phase2_v4_d_open_teacher_delivery_v1_preregistration.json"
)
CANONICAL_FREEZE = (
    CANONICAL_EXP_DIR
    / "audits/phase2_v4_d_open_teacher_delivery_v1_implementation_freeze.json"
)
CANONICAL_DELIVERY_ROOT = (
    CANONICAL_EXP_DIR
    / "prepared/pvrig_v4_d_open_teacher_v1/remote_delivery_v1"
)
CANONICAL_SSH = Path("/mnt/c/Windows/System32/OpenSSH/ssh.exe")
REMOTE_HOST = "node23"
REMOTE_ROOT = Path("/data/qlyu/projects/pvrig_v4_d_open_teacher_postprocess_v1_20260716")
REMOTE_STATUS = "status/postprocess_status.json"
REMOTE_ARCHIVE = "outputs/v4d_open_teacher_delivery_v1.tar.gz"
REMOTE_ARCHIVE_SHA = "outputs/v4d_open_teacher_delivery_v1.tar.gz.sha256"
EXPECTED_BUILDER_SHA256 = "8adb3c4e1de37bbaaf469dfb967176d2c49d40f353e21a3f028baa20ea8e4145"
EXPECTED_JOB_MANIFEST_SHA256 = "96fec07a5535615f50bff40ac48bb323a94213e06a7b12726ae5b4b2d1161737"
EXPECTED_SPLIT_MANIFEST_SHA256 = "c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd"
EXPECTED_PROTOCOL_CORE_SHA256 = "91d75291ff832c1e94cbc0bf6f1cdd75de6a8bb74611230cdcd1716466f37cb7"
EXPECTED_PROTOCOL_LOCK_SHA256 = "a24eaf37730bc569067d64cdc1a43a763b70878d13d50e804bf3000ce43f5e84"
EXPECTED_STABILITY_SPEC_SHA256 = "fb01cdaa5939f2846b16e4e02a09903417cd6cea04d42350c4ed57f9ae7eb774"
EXPECTED_OPEN_COUNTS = {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32}
SEALED_SPLIT = "PROSPECTIVE_COMPUTATIONAL_TEST"
EXPECTED_SEALED_COUNT = 32
EXPECTED_TOTAL_JOBS = 2022
EXPECTED_OPEN_JOB_COUNT = 1548
EXPECTED_ARCHIVE_MEMBERS = frozenset(
    {
        "outputs/v4d_open_teacher.tsv",
        "outputs/v4d_open_teacher.tsv.audit.json",
        "outputs/EVALUATOR_STABLE.json",
        "outputs/open_teacher_postprocess_receipt.json",
        "outputs/SHA256SUMS",
    }
)
EXPECTED_CHECKSUM_MEMBERS = frozenset(EXPECTED_ARCHIVE_MEMBERS - {"outputs/SHA256SUMS"})
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
REMOTE_WAIT_STATES = frozenset({"WAITING_V4D", "BUILDING_OPEN_TEACHER", "MISSING"})
REMOTE_FAILURE_STATES = frozenset({"FAILED", "BLOCKED"})


class DeliveryError(RuntimeError):
    """A fail-closed validation or publication failure."""


class DeliveryWaiting(RuntimeError):
    """The immutable remote release is not ready yet."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def strict_json_load_bytes(raw: bytes, label: str) -> Any:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DeliveryError(f"duplicate_json_key:{label}:{key}")
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
    except DeliveryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeliveryError(f"invalid_json:{label}:{exc}") from exc


def strict_json_load(path: Path, label: str) -> Any:
    require_regular_file(path, label)
    return strict_json_load_bytes(path.read_bytes(), label)


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DeliveryError(message)


def require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise DeliveryError(f"missing_file:{label}:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"not_regular_file:{label}:{path}")


def require_exact_path(actual: Path, expected: Path, label: str) -> None:
    require(
        os.path.abspath(os.fspath(actual)) == os.fspath(expected),
        f"noncanonical_path:{label}:{actual}:expected={expected}",
    )


def safe_relative_member(name: str) -> None:
    path = PurePosixPath(name)
    require(not path.is_absolute(), f"absolute_archive_member:{name}")
    require(name == path.as_posix(), f"noncanonical_archive_member:{name}")
    require(".." not in path.parts and "." not in path.parts, f"archive_path_traversal:{name}")


@dataclass(frozen=True)
class Config:
    delivery_root: Path
    ssh_exe: Path
    remote_host: str
    remote_root: Path
    poll_seconds: float
    production: bool
    preregistration: Path | None = None
    implementation_freeze: Path | None = None
    expected_script_sha256: str | None = None
    expected_preregistration_sha256: str | None = None
    expected_implementation_freeze_sha256: str | None = None


class RemoteClient:
    def __init__(self, ssh_exe: Path, host: str) -> None:
        self.ssh_exe = ssh_exe
        self.host = host

    def _argv(self, command: str) -> list[str]:
        return [
            os.fspath(self.ssh_exe),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=20",
            self.host,
            command,
        ]

    def read_file(self, remote_path: Path, *, max_bytes: int) -> bytes:
        require(str(remote_path).startswith("/"), "remote_path_must_be_absolute")
        command = f"test -f '{remote_path}' && test ! -L '{remote_path}' && cat -- '{remote_path}'"
        process = subprocess.Popen(
            self._argv(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        require(
            process.stdout is not None and process.stderr is not None,
            "ssh_pipe_initialization_failed",
        )
        chunks: list[bytes] = []
        total = 0
        try:
            while True:
                block = process.stdout.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > max_bytes:
                    process.kill()
                    raise DeliveryError(f"remote_file_exceeds_limit:{remote_path}:{total}")
                chunks.append(block)
            stderr = process.stderr.read()
            rc = process.wait(timeout=30)
        except BaseException:
            process.kill()
            process.wait()
            raise
        if rc != 0:
            raise DeliveryError(
                f"remote_read_failed:{remote_path}:rc={rc}:stderr={stderr.decode('utf-8', 'replace')[:1000]}"
            )
        return b"".join(chunks)

    def stream_file(self, remote_path: Path, destination: Path, *, max_bytes: int) -> int:
        require(str(remote_path).startswith("/"), "remote_path_must_be_absolute")
        command = f"test -f '{remote_path}' && test ! -L '{remote_path}' && cat -- '{remote_path}'"
        process = subprocess.Popen(
            self._argv(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        require(
            process.stdout is not None and process.stderr is not None,
            "ssh_pipe_initialization_failed",
        )
        total = 0
        try:
            with destination.open("xb") as handle:
                while True:
                    block = process.stdout.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > max_bytes:
                        process.kill()
                        raise DeliveryError(f"remote_file_exceeds_limit:{remote_path}:{total}")
                    handle.write(block)
                handle.flush()
                os.fsync(handle.fileno())
            stderr = process.stderr.read()
            rc = process.wait(timeout=30)
        except BaseException:
            process.kill()
            process.wait()
            destination.unlink(missing_ok=True)
            raise
        if rc != 0:
            destination.unlink(missing_ok=True)
            raise DeliveryError(
                f"remote_stream_failed:{remote_path}:rc={rc}:stderr={stderr.decode('utf-8', 'replace')[:1000]}"
            )
        return total


def validate_production_config(config: Config) -> dict[str, str]:
    require(config.production, "production_validation_requires_production_mode")
    require(os.environ.get("PYTHONOPTIMIZE", "") in {"", "0"}, "pythonoptimize_forbidden")
    require_exact_path(Path(__file__).resolve(), CANONICAL_SCRIPT, "script")
    require_exact_path(config.delivery_root, CANONICAL_DELIVERY_ROOT, "delivery_root")
    require_exact_path(config.ssh_exe, CANONICAL_SSH, "ssh_exe")
    require(config.remote_host == REMOTE_HOST, "noncanonical_remote_host")
    require_exact_path(config.remote_root, REMOTE_ROOT, "remote_root")
    require(config.preregistration is not None, "production_preregistration_missing")
    require(config.implementation_freeze is not None, "production_freeze_missing")
    require_exact_path(config.preregistration, CANONICAL_PREREG, "preregistration")
    require_exact_path(config.implementation_freeze, CANONICAL_FREEZE, "implementation_freeze")
    for path, label in (
        (CANONICAL_SCRIPT, "script"),
        (CANONICAL_PREREG, "preregistration"),
        (CANONICAL_FREEZE, "implementation_freeze"),
        (CANONICAL_SSH, "ssh_exe"),
    ):
        require_regular_file(path, label)
    hashes = {
        "script_sha256": sha256_file(CANONICAL_SCRIPT),
        "preregistration_sha256": sha256_file(CANONICAL_PREREG),
        "implementation_freeze_sha256": sha256_file(CANONICAL_FREEZE),
    }
    require(
        hashes["script_sha256"] == config.expected_script_sha256,
        "production_script_hash_mismatch",
    )
    require(
        hashes["preregistration_sha256"] == config.expected_preregistration_sha256,
        "production_preregistration_hash_mismatch",
    )
    require(
        hashes["implementation_freeze_sha256"]
        == config.expected_implementation_freeze_sha256,
        "production_implementation_freeze_hash_mismatch",
    )
    freeze = strict_json_load(CANONICAL_FREEZE, "implementation_freeze")
    require(
        freeze.get("schema_version")
        == "phase2_v4_d_open_teacher_delivery_v1_implementation_freeze",
        "implementation_freeze_schema_invalid",
    )
    require(freeze.get("status") == "PASS_IMPLEMENTATION_FROZEN", "implementation_not_frozen")
    frozen_hashes = freeze.get("sha256") or {}
    require(frozen_hashes.get("delivery_script") == hashes["script_sha256"], "freeze_script_hash_mismatch")
    require(
        frozen_hashes.get("preregistration") == hashes["preregistration_sha256"],
        "freeze_preregistration_hash_mismatch",
    )
    require(freeze.get("tests", {}).get("status") == "PASS", "freeze_tests_not_pass")
    return hashes


def parse_remote_archive_checksum(raw: bytes) -> str:
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise DeliveryError("remote_archive_checksum_not_ascii") from exc
    lines = text.splitlines()
    require(len(lines) == 1, "remote_archive_checksum_line_count_invalid")
    match = re.fullmatch(
        r"([0-9a-f]{64})  outputs/v4d_open_teacher_delivery_v1\.tar\.gz", lines[0]
    )
    require(match is not None, "remote_archive_checksum_format_invalid")
    return match.group(1)


def extract_validated_archive(archive: Path, extraction_root: Path) -> None:
    require_regular_file(archive, "downloaded_archive")
    extraction_root.mkdir(parents=True, exist_ok=False)
    try:
        with tarfile.open(archive, mode="r:gz") as bundle:
            members = bundle.getmembers()
            names = [member.name for member in members]
            require(len(names) == len(set(names)), "duplicate_archive_member")
            require(frozenset(names) == EXPECTED_ARCHIVE_MEMBERS, "archive_member_set_mismatch")
            total_size = 0
            for member in members:
                safe_relative_member(member.name)
                require(member.isfile(), f"archive_member_not_regular:{member.name}:{member.type!r}")
                require(member.linkname in {"", None}, f"archive_member_linkname_present:{member.name}")
                require(0 <= member.size <= MAX_MEMBER_BYTES, f"archive_member_size_invalid:{member.name}")
                total_size += member.size
            require(total_size <= MAX_UNCOMPRESSED_BYTES, "archive_uncompressed_size_limit_exceeded")
            for member in members:
                source = bundle.extractfile(member)
                require(source is not None, f"archive_member_unreadable:{member.name}")
                destination = extraction_root / member.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with destination.open("xb") as handle:
                    while True:
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        written += len(block)
                        require(written <= member.size, f"archive_member_expanded_past_header:{member.name}")
                        handle.write(block)
                require(written == member.size, f"archive_member_size_mismatch:{member.name}")
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise DeliveryError(f"archive_validation_failed:{exc}") from exc


def parse_and_validate_sha256sums(release_root: Path) -> dict[str, str]:
    checksum_path = release_root / "outputs/SHA256SUMS"
    require_regular_file(checksum_path, "payload_sha256sums")
    try:
        lines = checksum_path.read_text(encoding="ascii").splitlines()
    except (UnicodeDecodeError, OSError) as exc:
        raise DeliveryError(f"invalid_payload_sha256sums:{exc}") from exc
    require(len(lines) == len(EXPECTED_CHECKSUM_MEMBERS), "payload_sha256sums_line_count_invalid")
    observed: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  (outputs/[A-Za-z0-9_.-]+)", line)
        require(match is not None, f"payload_sha256sums_format_invalid:{line}")
        digest, name = match.groups()
        safe_relative_member(name)
        require(name not in observed, f"payload_sha256sums_duplicate:{name}")
        observed[name] = digest
    require(frozenset(observed) == EXPECTED_CHECKSUM_MEMBERS, "payload_sha256sums_member_set_mismatch")
    for name, expected in observed.items():
        path = release_root / name
        require_regular_file(path, f"payload:{name}")
        require(sha256_file(path) == expected, f"payload_sha256_mismatch:{name}")
    return observed


def validate_teacher(path: Path) -> tuple[int, dict[str, int]]:
    require_regular_file(path, "teacher")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = set(reader.fieldnames or [])
        require(
            {"candidate_id", "model_split", "R_dual_min", "sequence_sha256"} <= fields,
            "teacher_required_fields_missing",
        )
        rows = list(reader)
    require(len(rows) == 258, f"teacher_row_count_invalid:{len(rows)}")
    candidate_ids: set[str] = set()
    counts: dict[str, int] = {}
    for row in rows:
        candidate_id = row.get("candidate_id", "")
        require(candidate_id and candidate_id not in candidate_ids, f"teacher_candidate_invalid:{candidate_id}")
        candidate_ids.add(candidate_id)
        split = row.get("model_split", "")
        require(split in EXPECTED_OPEN_COUNTS, f"teacher_nonopen_split:{split}")
        counts[split] = counts.get(split, 0) + 1
        try:
            target = float(row.get("R_dual_min", ""))
        except ValueError as exc:
            raise DeliveryError(f"teacher_target_invalid:{candidate_id}") from exc
        require(math.isfinite(target), f"teacher_target_nonfinite:{candidate_id}")
    require(counts == EXPECTED_OPEN_COUNTS, f"teacher_split_counts_invalid:{counts}")
    return len(rows), counts


def gate_passed(value: Any) -> bool:
    if isinstance(value, Mapping):
        return value.get("status") == "PASS" or value.get("passed") is True
    if isinstance(value, bool):
        return value
    return value == "PASS"


def validate_release_outputs(release_root: Path) -> dict[str, Any]:
    outputs = release_root / "outputs"
    require(outputs.is_dir() and not outputs.is_symlink(), "outputs_directory_invalid")
    expected_names = {PurePosixPath(name).name for name in EXPECTED_ARCHIVE_MEMBERS}
    actual_names = {path.name for path in outputs.iterdir()}
    require(actual_names == expected_names, f"outputs_member_set_mismatch:{sorted(actual_names)}")
    checksums = parse_and_validate_sha256sums(release_root)
    teacher = outputs / "v4d_open_teacher.tsv"
    audit_path = outputs / "v4d_open_teacher.tsv.audit.json"
    evaluator_path = outputs / "EVALUATOR_STABLE.json"
    receipt_path = outputs / "open_teacher_postprocess_receipt.json"
    row_count, split_counts = validate_teacher(teacher)
    audit = strict_json_load(audit_path, "teacher_audit")
    evaluator = strict_json_load(evaluator_path, "evaluator")
    receipt = strict_json_load(receipt_path, "postprocess_receipt")

    require(audit.get("status") == "PASS_V4_D_OPEN_CONTINUOUS_TEACHER_RELEASE", "teacher_audit_status_invalid")
    require(audit.get("release") == "open_train_and_open_development_only", "teacher_audit_release_invalid")
    require(int(audit.get("row_count", -1)) == row_count, "teacher_audit_count_mismatch")
    require(audit.get("output", {}).get("sha256") == sha256_file(teacher), "teacher_audit_output_hash_mismatch")
    sealed = audit.get("sealed_data_boundary") or {}
    require(sealed.get("model_split") == SEALED_SPLIT, "audit_sealed_split_invalid")
    require(int(sealed.get("row_count", -1)) == EXPECTED_SEALED_COUNT, "audit_sealed_count_invalid")
    require(int(sealed.get("raw_job_results_opened", -1)) == 0, "audit_sealed_raw_results_opened")
    require(sealed.get("sealed_metrics_used_for_teacher_or_ranking") is False, "audit_sealed_metrics_used")
    audit_inputs = audit.get("inputs") or {}
    require(audit_inputs.get("split_manifest_sha256") == EXPECTED_SPLIT_MANIFEST_SHA256, "audit_split_hash_mismatch")
    require(audit_inputs.get("job_manifest_sha256") == EXPECTED_JOB_MANIFEST_SHA256, "audit_job_manifest_hash_mismatch")
    closure = audit_inputs.get("raw_aggregate_closure") or {}
    require(closure.get("status") == "PASS_RAW_OPEN_RESULTS_MATCH_EVALUATOR_BOUND_AGGREGATES", "audit_raw_closure_invalid")
    require(int(closure.get("job_count", -1)) == EXPECTED_OPEN_JOB_COUNT, "audit_raw_closure_count_invalid")

    evaluator_sha = sha256_file(evaluator_path)
    require(evaluator.get("status") == "PASS", "evaluator_status_invalid")
    require(evaluator.get("unlockable") is True, "evaluator_not_unlockable")
    require(evaluator.get("evidence_mode") == "production_pose_backed", "evaluator_mode_invalid")
    require(int(evaluator.get("job_count", -1)) == EXPECTED_TOTAL_JOBS, "evaluator_job_count_invalid")
    require(evaluator.get("job_manifest_sha256") == EXPECTED_JOB_MANIFEST_SHA256, "evaluator_job_manifest_hash_mismatch")
    require(evaluator.get("protocol_core_sha256") == EXPECTED_PROTOCOL_CORE_SHA256, "evaluator_protocol_core_hash_mismatch")
    require(evaluator.get("protocol_lock_sha256") == EXPECTED_PROTOCOL_LOCK_SHA256, "evaluator_protocol_lock_hash_mismatch")
    require(evaluator.get("candidates_sha256") == EXPECTED_SPLIT_MANIFEST_SHA256, "evaluator_candidates_hash_mismatch")
    require(evaluator.get("stability_gate_spec_sha256") == EXPECTED_STABILITY_SPEC_SHA256, "evaluator_stability_hash_mismatch")
    gates = evaluator.get("gates")
    require(isinstance(gates, Mapping) and bool(gates), "evaluator_gates_missing")
    failed = sorted(str(name) for name, value in gates.items() if not gate_passed(value))
    require(not failed, "evaluator_nonpass_gates:" + ",".join(failed))

    require(receipt.get("schema_version") == "pvrig_v4_d_open_teacher_postprocess_receipt_v2", "receipt_schema_invalid")
    require(receipt.get("status") == "PASS_OPEN258_TEACHER_READY_TEST32_SEALED", "receipt_status_invalid")
    require(int(receipt.get("row_count", -1)) == row_count, "receipt_row_count_invalid")
    require(receipt.get("split_counts") == split_counts, "receipt_split_counts_invalid")
    require(int(receipt.get("sealed_test_raw_job_results_opened", -1)) == 0, "receipt_sealed_results_opened")
    require(receipt.get("sealed_metrics_used_for_teacher_or_ranking") is False, "receipt_sealed_metrics_used")
    require(receipt.get("full_aggregate_streamed_only_for_open_row_closure") is True, "receipt_aggregate_boundary_invalid")
    require(receipt.get("teacher_sha256") == sha256_file(teacher), "receipt_teacher_hash_mismatch")
    require(receipt.get("teacher_audit_sha256") == sha256_file(audit_path), "receipt_audit_hash_mismatch")
    require(receipt.get("evaluator_sha256") == evaluator_sha, "receipt_evaluator_hash_mismatch")
    require(receipt.get("builder_sha256") == EXPECTED_BUILDER_SHA256, "receipt_builder_hash_mismatch")
    require(receipt.get("job_manifest_sha256") == EXPECTED_JOB_MANIFEST_SHA256, "receipt_job_manifest_hash_mismatch")
    require(receipt.get("raw_aggregate_closure_sha256") == closure.get("closure_sha256"), "receipt_raw_closure_mismatch")
    for field in ("job_manifest_sha256", "job_results_sha256", "pose_scores_sha256"):
        require(receipt.get(field) == evaluator.get(field), f"receipt_evaluator_binding_mismatch:{field}")
    require(audit_inputs.get("evaluator_sha256") == evaluator_sha, "audit_evaluator_hash_mismatch")
    require(audit_inputs.get("job_results_sha256_for_evaluator_binding_only") == receipt.get("job_results_sha256"), "audit_job_results_binding_mismatch")
    require(audit_inputs.get("pose_scores_sha256_for_evaluator_binding_only") == receipt.get("pose_scores_sha256"), "audit_pose_scores_binding_mismatch")
    return {
        "row_count": row_count,
        "split_counts": split_counts,
        "teacher_sha256": sha256_file(teacher),
        "teacher_audit_sha256": sha256_file(audit_path),
        "evaluator_sha256": evaluator_sha,
        "postprocess_receipt_sha256": sha256_file(receipt_path),
        "payload_sha256sums_sha256": sha256_file(outputs / "SHA256SUMS"),
        "payload_hashes": checksums,
        "builder_sha256": receipt.get("builder_sha256"),
        "raw_aggregate_closure_sha256": closure.get("closure_sha256"),
    }


def ensure_no_symlinks_or_special_files(root: Path) -> None:
    for path in root.rglob("*"):
        metadata = path.lstat()
        require(not stat.S_ISLNK(metadata.st_mode), f"published_tree_symlink_forbidden:{path}")
        require(
            stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode),
            f"published_tree_special_file_forbidden:{path}",
        )


def validate_existing_content_addressed_release(path: Path, archive_sha: str) -> dict[str, Any]:
    require(path.is_dir() and not path.is_symlink(), "content_addressed_release_not_directory")
    require(path.name == archive_sha, "content_addressed_directory_hash_name_mismatch")
    archive = path / "source/v4d_open_teacher_delivery_v1.tar.gz"
    archive_sha_file = path / "source/v4d_open_teacher_delivery_v1.tar.gz.sha256"
    delivery_receipt_path = path / "delivery_receipt.json"
    require_regular_file(archive, "published_source_archive")
    require_regular_file(archive_sha_file, "published_source_archive_sha")
    require_regular_file(delivery_receipt_path, "delivery_receipt")
    require(sha256_file(archive) == archive_sha, "published_source_archive_hash_mismatch")
    require(parse_remote_archive_checksum(archive_sha_file.read_bytes()) == archive_sha, "published_source_checksum_mismatch")
    ensure_no_symlinks_or_special_files(path)
    validation = validate_release_outputs(path)
    receipt = strict_json_load(delivery_receipt_path, "delivery_receipt")
    require(receipt.get("status") == "PASS_CONTENT_ADDRESSED_OPEN258_DELIVERY", "delivery_receipt_status_invalid")
    require(receipt.get("archive_sha256") == archive_sha, "delivery_receipt_archive_hash_mismatch")
    require(receipt.get("validation") == validation, "delivery_receipt_validation_mismatch")
    require(receipt.get("test32_labels_read") is False, "delivery_receipt_test_label_boundary_invalid")
    require(receipt.get("v4f_labels_read") is False, "delivery_receipt_v4f_label_boundary_invalid")
    return validation


def inspect_current(delivery_root: Path) -> tuple[str | None, dict[str, Any] | None]:
    current = delivery_root / "current"
    try:
        metadata = current.lstat()
    except FileNotFoundError:
        return None, None
    require(stat.S_ISLNK(metadata.st_mode), "existing_current_is_not_symlink")
    target = os.readlink(current)
    target_path = PurePosixPath(target)
    require(
        len(target_path.parts) == 2
        and target_path.parts[0] == "by_sha256"
        and re.fullmatch(r"[0-9a-f]{64}", target_path.parts[1]) is not None,
        f"existing_current_target_invalid:{target}",
    )
    archive_sha = target_path.parts[1]
    release = delivery_root / target
    validation = validate_existing_content_addressed_release(release, archive_sha)
    return archive_sha, validation


def write_status(delivery_root: Path, status: str, reason: str, **extra: Any) -> None:
    atomic_write_json(
        delivery_root / "status/delivery_status.json",
        {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "reason": reason,
            "updated_at": utc_now(),
            "claim_boundary": CLAIM_BOUNDARY,
            "test32_labels_read": False,
            "v4f_labels_read": False,
            "label_paths_opened": 0,
            **extra,
        },
    )


def publish_release(
    config: Config,
    staging: Path,
    archive_sha: str,
    validation: dict[str, Any],
    implementation_hashes: Mapping[str, str],
) -> Path:
    current_sha, _ = inspect_current(config.delivery_root)
    if current_sha is not None:
        require(
            current_sha == archive_sha,
            f"different_existing_current_refused:{current_sha}:{archive_sha}",
        )
    by_sha_root = config.delivery_root / "by_sha256"
    by_sha_root.mkdir(parents=True, exist_ok=True)
    destination = by_sha_root / archive_sha
    if destination.exists() or destination.is_symlink():
        existing = validate_existing_content_addressed_release(destination, archive_sha)
        require(existing == validation, "existing_content_addressed_release_differs")
        shutil.rmtree(staging)
    else:
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_CONTENT_ADDRESSED_OPEN258_DELIVERY",
            "published_at_utc": utc_now(),
            "archive_sha256": archive_sha,
            "remote": {
                "host": config.remote_host,
                "root": str(config.remote_root),
                "archive": REMOTE_ARCHIVE,
                "archive_sha256": REMOTE_ARCHIVE_SHA,
                "terminal_status": "COMPLETE",
            },
            "validation": validation,
            "implementation_hashes": dict(implementation_hashes),
            "test32_labels_read": False,
            "v4f_labels_read": False,
            "label_paths_opened": 0,
            "claim_boundary": CLAIM_BOUNDARY,
        }
        atomic_write_json(staging / "delivery_receipt.json", receipt)
        ensure_no_symlinks_or_special_files(staging)
        os.rename(staging, destination)
        validate_existing_content_addressed_release(destination, archive_sha)

    if current_sha is not None:
        require(current_sha == archive_sha, "current_changed_during_publication")
    else:
        os.symlink(f"by_sha256/{archive_sha}", config.delivery_root / "current")
    atomic_write_json(
        config.delivery_root / "status/delivery_receipt.json",
        strict_json_load(destination / "delivery_receipt.json", "delivery_receipt"),
    )
    return destination


def one_delivery_attempt(
    config: Config,
    client: RemoteClient,
    implementation_hashes: Mapping[str, str],
) -> str:
    current_sha, current_validation = inspect_current(config.delivery_root)
    if current_sha is not None:
        write_status(
            config.delivery_root,
            "COMPLETE",
            "existing content-addressed current release revalidated",
            archive_sha256=current_sha,
            validation=current_validation,
        )
        return current_sha

    try:
        status_raw = client.read_file(config.remote_root / REMOTE_STATUS, max_bytes=1024 * 1024)
    except DeliveryError as exc:
        write_status(config.delivery_root, "WAITING_REMOTE_UNREACHABLE", str(exc))
        raise DeliveryWaiting(str(exc)) from exc
    status_payload = strict_json_load_bytes(status_raw, "remote_postprocess_status")
    require(isinstance(status_payload, Mapping), "remote_status_not_object")
    remote_status = str(status_payload.get("status", "MISSING"))
    if remote_status in REMOTE_FAILURE_STATES:
        raise DeliveryError(f"remote_postprocess_terminal_failure:{remote_status}:{status_payload.get('reason', '')}")
    if remote_status != "COMPLETE":
        require(remote_status in REMOTE_WAIT_STATES, f"remote_status_unrecognized:{remote_status}")
        write_status(
            config.delivery_root,
            "WAITING_REMOTE",
            f"remote postprocess status={remote_status}",
            remote_status=remote_status,
        )
        raise DeliveryWaiting(remote_status)

    write_status(config.delivery_root, "DOWNLOADING", "remote COMPLETE; staging checksum and archive")
    try:
        checksum_raw = client.read_file(config.remote_root / REMOTE_ARCHIVE_SHA, max_bytes=4096)
    except DeliveryError as exc:
        write_status(config.delivery_root, "WAITING_REMOTE_ARTIFACTS", str(exc), remote_status="COMPLETE")
        raise DeliveryWaiting(str(exc)) from exc
    expected_archive_sha = parse_remote_archive_checksum(checksum_raw)

    staging_parent = config.delivery_root / ".staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="open_teacher.", dir=staging_parent))
    try:
        source = staging / "source"
        source.mkdir()
        checksum_path = source / "v4d_open_teacher_delivery_v1.tar.gz.sha256"
        checksum_path.write_bytes(checksum_raw)
        archive_path = source / "v4d_open_teacher_delivery_v1.tar.gz"
        try:
            client.stream_file(
                config.remote_root / REMOTE_ARCHIVE,
                archive_path,
                max_bytes=MAX_ARCHIVE_BYTES,
            )
        except DeliveryError as exc:
            write_status(config.delivery_root, "WAITING_REMOTE_ARTIFACTS", str(exc), remote_status="COMPLETE")
            raise DeliveryWaiting(str(exc)) from exc
        observed_archive_sha = sha256_file(archive_path)
        require(
            observed_archive_sha == expected_archive_sha,
            f"downloaded_archive_sha256_mismatch:{observed_archive_sha}:{expected_archive_sha}",
        )
        write_status(
            config.delivery_root,
            "VERIFYING",
            "archive hash verified; validating exact members and release closure",
            archive_sha256=expected_archive_sha,
        )
        extraction = staging / ".extraction"
        extract_validated_archive(archive_path, extraction)
        for child in extraction.iterdir():
            os.rename(child, staging / child.name)
        extraction.rmdir()
        validation = validate_release_outputs(staging)
        destination = publish_release(
            config,
            staging,
            expected_archive_sha,
            validation,
            implementation_hashes,
        )
        write_status(
            config.delivery_root,
            "COMPLETE",
            "open258 teacher published content-addressed; test32 and V4-F labels unopened",
            archive_sha256=expected_archive_sha,
            published_path=str(destination),
            current_target=f"by_sha256/{expected_archive_sha}",
            validation=validation,
        )
        return expected_archive_sha
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def acquire_lock(delivery_root: Path) -> BinaryIO:
    status_dir = delivery_root / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    lock = (status_dir / "delivery.lock").open("a+b")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock.close()
        raise DeliveryError("delivery_watcher_lock_busy") from exc
    return lock


def run(config: Config, *, once: bool) -> int:
    config.delivery_root.mkdir(parents=True, exist_ok=True)
    implementation_hashes = (
        validate_production_config(config)
        if config.production
        else {"script_sha256": sha256_file(Path(__file__).resolve())}
    )
    client = RemoteClient(config.ssh_exe, config.remote_host)
    lock = acquire_lock(config.delivery_root)
    try:
        while True:
            try:
                one_delivery_attempt(config, client, implementation_hashes)
                return 0
            except DeliveryWaiting:
                if once:
                    return 10
                time.sleep(config.poll_seconds)
            except DeliveryError as exc:
                write_status(config.delivery_root, "FAILED", str(exc))
                return 2
    finally:
        lock.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--watch", action="store_true")
    parser.add_argument("--delivery-root", type=Path, required=True)
    parser.add_argument("--ssh-exe", type=Path, required=True)
    parser.add_argument("--remote-host", required=True)
    parser.add_argument("--remote-root", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--preregistration", type=Path)
    parser.add_argument("--implementation-freeze", type=Path)
    parser.add_argument("--expected-script-sha256")
    parser.add_argument("--expected-preregistration-sha256")
    parser.add_argument("--expected-implementation-freeze-sha256")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    require(args.poll_seconds > 0, "poll_seconds_must_be_positive")
    config = Config(
        delivery_root=args.delivery_root,
        ssh_exe=args.ssh_exe,
        remote_host=args.remote_host,
        remote_root=args.remote_root,
        poll_seconds=args.poll_seconds,
        production=args.production,
        preregistration=args.preregistration,
        implementation_freeze=args.implementation_freeze,
        expected_script_sha256=args.expected_script_sha256,
        expected_preregistration_sha256=args.expected_preregistration_sha256,
        expected_implementation_freeze_sha256=args.expected_implementation_freeze_sha256,
    )
    return run(config, once=args.once)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DeliveryError as error:
        print(f"delivery_error:{error}", file=sys.stderr)
        raise SystemExit(2)
