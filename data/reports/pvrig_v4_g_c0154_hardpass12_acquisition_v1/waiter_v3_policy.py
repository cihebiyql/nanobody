#!/usr/bin/env python3
"""Security policy for the V4-G12 acquisition waiter V3.

The policy verifies the complete acquisition lock, immutable runtime identity,
and the label-free launch gates.  It never opens docking result rows or the
open-teacher TSV.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_RECEPTORS = {"8x6b", "9e6y"}
EXPECTED_SEEDS = {917, 1931, 3253}
REQUIRED_LOCKED_FILES = {
    "scripts/run_controller.py",
    "scripts/run_job.py",
    "manifests/docking_jobs.tsv",
    "inputs/candidates_12.tsv",
    "inputs/candidate_monomers_manifest.tsv",
}


class GateError(RuntimeError):
    """A fail-closed trust, closure, or runtime-identity violation."""


@dataclass(frozen=True)
class RuntimeIdentity:
    package_root: Path
    source_v4d_root: Path
    open_teacher_root: Path
    python_requested: Path
    python_resolved: Path
    max_load1: float
    poll_seconds: int
    runtime_path: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise GateError(f"unreadable_json:{path}:{type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise GateError(f"json_root_not_object:{path}")
    return payload


def require_regular_file(path: Path, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise GateError(f"missing:{label}:{path}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise GateError(f"symlink_rejected:{label}:{path}")
    if not stat.S_ISREG(metadata.st_mode):
        raise GateError(f"nonregular_rejected:{label}:{path}")
    return metadata


def verify_expected_artifact(path: Path, expected_sha256: str, label: str) -> str:
    if not SHA256_RE.fullmatch(expected_sha256):
        raise GateError(f"invalid_expected_sha256:{label}")
    require_regular_file(path, label)
    observed = sha256_file(path)
    if observed != expected_sha256:
        raise GateError(f"sha256_mismatch:{label}:{observed}")
    return observed


def canonical_relative_path(raw: Any) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise GateError(f"invalid_locked_path:{raw!r}")
    candidate = PurePosixPath(raw)
    if candidate.is_absolute():
        raise GateError(f"absolute_locked_path_rejected:{raw}")
    if raw != candidate.as_posix():
        raise GateError(f"noncanonical_locked_path_rejected:{raw}")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise GateError(f"path_traversal_rejected:{raw}")
    return candidate


def resolve_locked_regular_file(root: Path, relative: PurePosixPath) -> Path:
    try:
        root_meta = root.lstat()
    except FileNotFoundError as exc:
        raise GateError(f"package_root_missing:{root}") from exc
    if stat.S_ISLNK(root_meta.st_mode) or not stat.S_ISDIR(root_meta.st_mode):
        raise GateError(f"package_root_not_real_directory:{root}")
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise GateError(f"locked_file_missing:{relative.as_posix()}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise GateError(f"locked_path_symlink_rejected:{relative.as_posix()}:{index}")
        if index < len(relative.parts) - 1:
            if not stat.S_ISDIR(metadata.st_mode):
                raise GateError(f"locked_parent_non_directory:{relative.as_posix()}:{index}")
        elif not stat.S_ISREG(metadata.st_mode):
            raise GateError(f"locked_file_nonregular:{relative.as_posix()}")
    try:
        current.relative_to(root)
    except ValueError as exc:
        raise GateError(f"locked_path_escaped_root:{relative.as_posix()}") from exc
    return current


def verify_job_manifest(manifest_path: Path, locked_paths: set[str]) -> dict[str, Any]:
    try:
        with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
    except (OSError, csv.Error) as exc:
        raise GateError(f"job_manifest_unreadable:{type(exc).__name__}") from exc
    required_columns = {"job_id", "entity_type", "entity_id", "conformation", "seed", "monomer_source"}
    if not rows or not required_columns.issubset(rows[0]):
        raise GateError("job_manifest_columns_or_rows_invalid")
    if len(rows) != 72:
        raise GateError(f"job_manifest_row_count_mismatch:{len(rows)}")
    job_ids = [row["job_id"] for row in rows]
    if len(set(job_ids)) != 72:
        raise GateError("job_manifest_duplicate_job_id")
    if any(row["entity_type"] != "candidate" for row in rows):
        raise GateError("job_manifest_non_candidate_entity")
    candidates = sorted({row["entity_id"] for row in rows})
    if len(candidates) != 12:
        raise GateError(f"job_manifest_candidate_count_mismatch:{len(candidates)}")
    expected_pairs = {(receptor, seed) for receptor in EXPECTED_RECEPTORS for seed in EXPECTED_SEEDS}
    for candidate in candidates:
        candidate_rows = [row for row in rows if row["entity_id"] == candidate]
        try:
            observed_pairs = {(row["conformation"], int(row["seed"])) for row in candidate_rows}
        except ValueError as exc:
            raise GateError(f"job_manifest_seed_invalid:{candidate}") from exc
        if len(candidate_rows) != 6 or observed_pairs != expected_pairs:
            raise GateError(f"job_manifest_matrix_mismatch:{candidate}")
        for row in candidate_rows:
            monomer = canonical_relative_path(row["monomer_source"]).as_posix()
            if monomer not in locked_paths or not monomer.startswith("inputs/candidate_monomers/"):
                raise GateError(f"job_manifest_unlocked_monomer:{candidate}:{monomer}")
    return {
        "job_count": len(rows),
        "candidate_count": len(candidates),
        "receptors": sorted(EXPECTED_RECEPTORS),
        "seeds": sorted(EXPECTED_SEEDS),
    }


def verify_protocol_lock(
    package_root: Path,
    lock_path: Path,
    expected_lock_sha256: str,
) -> dict[str, Any]:
    verify_expected_artifact(lock_path, expected_lock_sha256, "acquisition_protocol_lock")
    lock = load_object(lock_path)
    if lock.get("status") != "LOCKED_ACQUISITION_ONLY_72_JOBS":
        raise GateError("acquisition_protocol_lock_status_invalid")
    if int(lock.get("candidate_count", 0) or 0) != 12 or int(lock.get("job_count", 0) or 0) != 72:
        raise GateError("acquisition_protocol_lock_counts_invalid")
    entries = lock.get("files")
    if not isinstance(entries, list) or not entries:
        raise GateError("acquisition_protocol_lock_files_missing")

    verified: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise GateError(f"locked_file_entry_not_object:{index}")
        relative = canonical_relative_path(entry.get("path"))
        name = relative.as_posix()
        if name in verified:
            raise GateError(f"duplicate_locked_path:{name}")
        expected_sha = entry.get("sha256")
        expected_bytes = entry.get("bytes")
        if not isinstance(expected_sha, str) or not SHA256_RE.fullmatch(expected_sha):
            raise GateError(f"locked_file_sha_invalid:{name}")
        if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool) or expected_bytes < 0:
            raise GateError(f"locked_file_size_invalid:{name}")
        path = resolve_locked_regular_file(package_root, relative)
        metadata = path.lstat()
        if metadata.st_size != expected_bytes:
            raise GateError(f"locked_file_size_mismatch:{name}:{metadata.st_size}")
        observed_sha = sha256_file(path)
        if observed_sha != expected_sha:
            raise GateError(f"locked_file_sha_mismatch:{name}:{observed_sha}")
        verified[name] = {"bytes": metadata.st_size, "sha256": observed_sha}

    names = set(verified)
    missing_required = sorted(REQUIRED_LOCKED_FILES - names)
    if missing_required:
        raise GateError("required_locked_files_missing:" + ",".join(missing_required))
    monomer_pdbs = sorted(
        name for name in names if name.startswith("inputs/candidate_monomers/") and name.endswith(".pdb")
    )
    if len(monomer_pdbs) != 12:
        raise GateError(f"locked_candidate_pdb_count_mismatch:{len(monomer_pdbs)}")
    manifest_summary = verify_job_manifest(package_root / "manifests/docking_jobs.tsv", names)
    if lock.get("job_manifest_sha256") != verified["manifests/docking_jobs.tsv"]["sha256"]:
        raise GateError("lock_job_manifest_binding_mismatch")
    if lock.get("candidate_manifest_sha256") != verified["inputs/candidates_12.tsv"]["sha256"]:
        raise GateError("lock_candidate_manifest_binding_mismatch")
    if lock.get("monomer_manifest_sha256") != verified["inputs/candidate_monomers_manifest.tsv"]["sha256"]:
        raise GateError("lock_monomer_manifest_binding_mismatch")
    return {
        "status": "PASS_COMPLETE_ACQUISITION_LOCK_CLOSURE",
        "verified_file_count": len(verified),
        "verified_total_bytes": sum(item["bytes"] for item in verified.values()),
        "candidate_pdb_count": len(monomer_pdbs),
        **manifest_summary,
    }


def _resolved_directory(requested: str, expected_requested: str, expected_resolved: str, label: str) -> Path:
    if requested != expected_requested:
        raise GateError(f"runtime_override_drift:{label}:requested")
    path = Path(requested)
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise GateError(f"runtime_path_unavailable:{label}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise GateError(f"runtime_directory_not_real:{label}")
    if str(resolved) != expected_resolved:
        raise GateError(f"runtime_override_drift:{label}:resolved")
    return resolved


def verify_runtime_identity(anchor: Mapping[str, Any], environ: Mapping[str, str]) -> RuntimeIdentity:
    runtime = anchor.get("runtime_identity")
    if not isinstance(runtime, Mapping):
        raise GateError("runtime_identity_missing_from_anchor")

    def env_or_expected(key: str, expected: str) -> str:
        return environ.get(key, expected)

    package_root = _resolved_directory(
        env_or_expected("PVRIG_V4G12_ROOT", runtime["package_root_requested"]),
        runtime["package_root_requested"], runtime["package_root_resolved"], "package_root",
    )
    source = _resolved_directory(
        env_or_expected("PVRIG_V4D_SOURCE", runtime["source_v4d_requested"]),
        runtime["source_v4d_requested"], runtime["source_v4d_resolved"], "source_v4d",
    )
    open_teacher = _resolved_directory(
        env_or_expected("PVRIG_V4D_OPEN_TEACHER_ROOT", runtime["open_teacher_requested"]),
        runtime["open_teacher_requested"], runtime["open_teacher_resolved"], "open_teacher",
    )

    python_requested_text = env_or_expected("PVRIG_V4G12_PYTHON", runtime["python_requested"])
    if python_requested_text != runtime["python_requested"]:
        raise GateError("runtime_override_drift:python:requested")
    python_requested = Path(python_requested_text)
    try:
        python_resolved = python_requested.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise GateError("runtime_python_unavailable") from exc
    require_regular_file(python_resolved, "runtime_python_resolved")
    if str(python_resolved) != runtime["python_resolved"]:
        raise GateError("runtime_override_drift:python:resolved")
    if sha256_file(python_resolved) != runtime["python_resolved_sha256"]:
        raise GateError("runtime_python_sha256_mismatch")

    max_load_text = env_or_expected("PVRIG_V4G12_MAX_LOAD1", str(runtime["max_load1"]))
    try:
        max_load = float(max_load_text)
    except ValueError as exc:
        raise GateError("runtime_max_load_invalid") from exc
    if max_load != float(runtime["max_load1"]) or max_load != 16.0:
        raise GateError("runtime_override_drift:max_load1")

    poll_text = env_or_expected("PVRIG_V4G12_POLL_SECONDS", str(runtime["poll_seconds"]))
    try:
        poll_seconds = int(poll_text)
    except ValueError as exc:
        raise GateError("runtime_poll_invalid") from exc
    if poll_seconds != int(runtime["poll_seconds"]):
        raise GateError("runtime_override_drift:poll_seconds")

    runtime_path = environ.get("PATH", runtime["path"])
    if runtime_path != runtime["path"]:
        raise GateError("runtime_override_drift:PATH")
    project_root = environ.get("PVRIG_PROJECT_ROOT", runtime["package_root_requested"])
    if project_root != runtime["package_root_requested"]:
        raise GateError("runtime_override_drift:PVRIG_PROJECT_ROOT")
    for key, expected in runtime.get("required_environment", {}).items():
        if environ.get(key, expected) != expected:
            raise GateError(f"runtime_override_drift:{key}")
    for forbidden in runtime.get("forbidden_environment", []):
        if forbidden in environ:
            raise GateError(f"forbidden_runtime_environment:{forbidden}")

    return RuntimeIdentity(
        package_root=package_root,
        source_v4d_root=source,
        open_teacher_root=open_teacher,
        python_requested=python_requested,
        python_resolved=python_resolved,
        max_load1=max_load,
        poll_seconds=poll_seconds,
        runtime_path=runtime_path,
    )


def zero_acquisition_state(package_root: Path) -> dict[str, Any]:
    controller = package_root / "status/controller.json"
    if controller.exists() or controller.is_symlink():
        raise GateError("acquisition_controller_state_already_exists")
    counts: dict[str, int] = {}
    for label, path in (
        ("status_job_files", package_root / "status/jobs"),
        ("runs_entries", package_root / "runs"),
        ("results_entries", package_root / "results"),
    ):
        if path.is_symlink():
            raise GateError(f"acquisition_state_symlink_rejected:{label}")
        if path.exists() and not path.is_dir():
            raise GateError(f"acquisition_state_non_directory:{label}")
        if label == "status_job_files":
            counts[label] = sum(1 for item in path.rglob("*") if item.is_file()) if path.exists() else 0
        else:
            counts[label] = sum(1 for _ in path.iterdir()) if path.exists() else 0
    if any(counts.values()):
        raise GateError(f"acquisition_state_not_zero:{counts}")
    return {"controller_exists": False, **counts}


def assess_external_gate(
    anchor: Mapping[str, Any],
    runtime: RuntimeIdentity,
    release_verifier: Path,
) -> dict[str, Any]:
    controller_path = runtime.source_v4d_root / "status/controller.json"
    require_regular_file(controller_path, "source_v4d_controller")
    controller = load_object(controller_path)
    counts = controller.get("counts") or controller.get("counts_before") or {}
    if not isinstance(counts, dict):
        raise GateError("source_v4d_counts_invalid")
    expected_jobs = int(anchor["source_v4d_expected_job_count"])
    terminal = controller.get("status") in {"COMPLETE", "COMPLETE_WITH_FAILURES"}
    closed = int(counts.get("SUCCESS", 0)) + int(counts.get("FAILED_MAX_ATTEMPTS", 0)) == expected_jobs
    no_active = all(int(counts.get(key, 0)) == 0 for key in ("RUNNING", "PENDING", "QUEUED"))

    postprocess_path = runtime.open_teacher_root / "status/postprocess_status.json"
    require_regular_file(postprocess_path, "open_teacher_postprocess_status")
    postprocess = load_object(postprocess_path)
    process = subprocess.run(
        [str(runtime.python_resolved), str(release_verifier), "--root", str(runtime.open_teacher_root)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        env={
            "HOME": anchor["runtime_identity"]["home"],
            "LANG": anchor["runtime_identity"]["lang"],
            "PATH": runtime.runtime_path,
        },
    )
    try:
        release_gate = json.loads(process.stdout)
    except (ValueError, json.JSONDecodeError):
        release_gate = {"status": "BLOCKED", "reasons": ["release_verifier_output_unreadable"]}
    release_ready = (
        process.returncode == 0
        and postprocess.get("status") == "COMPLETE"
        and release_gate.get("status") == "READY"
        and release_gate.get("test32_sealed") is True
    )
    load1 = os.getloadavg()[0]
    ready = terminal and closed and no_active and release_ready and load1 <= runtime.max_load1
    return {
        "source_status": controller.get("status"),
        "counts": counts,
        "terminal": terminal,
        "closed": closed,
        "no_active": no_active,
        "open_teacher_postprocess_status": postprocess.get("status"),
        "open_teacher_release_gate": release_gate,
        "open_teacher_ready_test32_sealed": release_ready,
        "load1": load1,
        "max_load1": runtime.max_load1,
        "ready": ready,
    }


def build_controller_environment(anchor: Mapping[str, Any], runtime: RuntimeIdentity) -> dict[str, str]:
    frozen = anchor["runtime_identity"]
    environment = {
        "PATH": frozen["path"],
        "PVRIG_PROJECT_ROOT": frozen["package_root_requested"],
    }
    environment.update(frozen.get("required_environment", {}))
    return environment
