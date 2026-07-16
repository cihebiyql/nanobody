#!/usr/bin/env python3
"""Materialize the preregistered label-free V4-D Support V3 analysis.

This runner accepts no docking, V4-F, or experimental-label arguments.  It
uses only the inputs frozen in the Support V3 preregistration plus the exact
label-free ESM2/contact dependencies already bound by those inputs.  The
implementation and its tests must be frozen before any production feature or
null calculation starts.  A production support table is published only when
every preregistered nested-validation, deployment, and null-control gate
passes; failures remain research diagnostics in the ext4 runtime directory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
EXPERIMENT_ROOT = SCRIPT_DIR.parent
REPO_ROOT = EXPERIMENT_ROOT.parents[1]
CORE_PATH = SCRIPT_DIR / "build_phase2_v4_d_sequence_support_v3.py"
TEST_PATH = SCRIPT_DIR / "test_materialize_phase2_v4_d_sequence_support_v3.py"
ESM2_BUILDER_PATH = SCRIPT_DIR / "prepare_esm2_embeddings_v2_3.py"
CONTACT_EXTRACTOR_PATH = SCRIPT_DIR / "extract_pvrig_v2_3_residue_contact_features.py"

DEFAULT_PREREGISTRATION = (
    EXPERIMENT_ROOT / "audits/phase2_v4_d_sequence_support_v3_preregistration.json"
)
DEFAULT_FREEZE = (
    EXPERIMENT_ROOT / "audits/phase2_v4_d_sequence_support_v3_implementation_freeze_v2.json"
)
DEFAULT_FREEZE_RECEIPT = DEFAULT_FREEZE.with_suffix(".receipt.json")
DEFAULT_TEST_LOG = (
    EXPERIMENT_ROOT / "audits/phase2_v4_d_sequence_support_v3_production_tests_v2.log"
)
DEFAULT_SUPERSESSION_RECORD = (
    EXPERIMENT_ROOT
    / "audits/phase2_v4_d_sequence_support_v3_implementation_freeze_v1_superseded_preproduction.json"
)
DEFAULT_RUNTIME_ROOT = Path(
    "/root/pvrig_v4_d_sequence_support_v3_runtime_v2_72dc6adc1e34"
)
DEFAULT_PUBLISH_DIR = (
    EXPERIMENT_ROOT / "prepared/pvrig_v4_d_sequence_support_v3"
)

FREEZE_SCHEMA = "phase2_v4_d_sequence_support_v3_implementation_freeze_v2"
FREEZE_STATUS = "PASS_V2_FROZEN_BEFORE_FIRST_PRODUCTION_MATERIALIZATION"
FREEZE_RECEIPT_SCHEMA = "phase2_v4_d_sequence_support_v3_implementation_freeze_receipt_v2"
RUNTIME_SCHEMA = "phase2_v4_d_sequence_support_v3_runtime_audit_v1"
PUBLICATION_SCHEMA = "phase2_v4_d_sequence_support_v3_publication_v1"
PUBLICATION_RECEIPT_SCHEMA = "phase2_v4_d_sequence_support_v3_publication_receipt_v1"
TEST_PASS_SENTINEL = "SUPPORT_V3_PRODUCTION_TESTS_PASS"
EXPECTED_FROZEN_TEST_COUNT = 20
FROZEN_TEST_MODULES = (
    "experiments/phase2_5080_v1/src/test_build_phase2_v4_d_sequence_support_v3.py",
    "experiments/phase2_5080_v1/src/test_materialize_phase2_v4_d_sequence_support_v3.py",
)

EXPECTED_CORE_SHA256 = ""  # Filled by the implementation freeze, never trusted from source alone.
EXPECTED_CONTACT_EXTRACTOR_SHA256 = (
    "adbe462302df37239434e8a580ab50ae99cf2fc2107bed19a7e31512c44115c6"
)
EXPECTED_CONTACT_CHECKPOINT_SHA256 = {
    43: "27d2c3c9c89a0e4fd3d725cc64e433933aa1717ae19e7246b599ef8931db7c97",
    53: "2876155dffdedf0d4bee41daddd25a1c9e67aeba1101950fe508e2fd4df3260b",
    67: "f717a68056b2569d5a5d4b59fd49e08ee659b33f7dacc23e21cc737b3030cfe9",
}
EXPECTED_TARGET_SHA256 = "4113f40833627aaede888e5ee9e9e1a99bdceced4f856fa08e02bc666da15c50"
EXPECTED_HOTSPOT_SHA256 = "9e5e82ad1f8193efbbb72865a632528c6b6a08d8a686c5b3e8ac74d2fd1564dd"
EXPECTED_NULL_RECOMPUTE_COUNT = 3000
EXPECTED_CHANNEL_SPLICE_COUNT = 1000
EXPECTED_TEST_LABEL_PATHS_OPENED = 0
FORBIDDEN_RUNTIME_PATH_TOKENS = (
    "docking",
    "v4_f",
    "experimental",
    "gold",
    "sealed_test",
)


class MaterializationError(RuntimeError):
    """Raised when a frozen input, label-free boundary, or gate is violated."""


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise MaterializationError(f"cannot_load_module:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CORE = _load_module("phase2_v4_d_sequence_support_v3_core", CORE_PATH)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(payload: Any) -> str:
    return sha256_bytes(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
    )


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_write_csv(
    path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]
) -> None:
    if not rows:
        raise MaterializationError(f"cannot_write_empty_csv:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def fsync_file_and_parent(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def verify_exact_regular_file_set(directory: Path, expected_names: set[str]) -> None:
    entries = list(directory.iterdir())
    observed = {entry.name for entry in entries}
    if observed != expected_names:
        raise MaterializationError(
            f"publication_exact_output_set_mismatch:{sorted(observed)}:{sorted(expected_names)}"
        )
    invalid = [
        entry.name
        for entry in entries
        if entry.is_symlink() or not entry.is_file()
    ]
    if invalid:
        raise MaterializationError(
            "publication_nonregular_or_symlink_output:" + ",".join(sorted(invalid))
        )


def read_csv(path: Path, delimiter: str = ",") -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    if not fields:
        raise MaterializationError(f"empty_table_header:{path}")
    return rows, fields


def snapshot_file(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise MaterializationError(f"snapshot_file_missing:{resolved}")
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def snapshot_for_destination(actual_path: Path, destination_path: Path) -> dict[str, Any]:
    record = snapshot_file(actual_path)
    record["path"] = str(destination_path.resolve())
    return record


def verify_snapshot(record: Mapping[str, Any], label: str) -> Path:
    path = Path(str(record.get("path", "")))
    if not path.is_file():
        raise MaterializationError(f"snapshot_missing:{label}:{path}")
    if path.stat().st_size != int(record.get("size_bytes", -1)):
        raise MaterializationError(f"snapshot_size_mismatch:{label}:{path}")
    observed = sha256_file(path)
    if observed != record.get("sha256"):
        raise MaterializationError(
            f"snapshot_sha256_mismatch:{label}:{observed}:{record.get('sha256')}"
        )
    return path


def require_path_within(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise MaterializationError(f"path_escapes_runtime:{label}:{resolved}") from exc
    return resolved


def require_ext4_runtime(path: Path) -> str:
    lowered = str(path.resolve()).lower()
    forbidden = [token for token in FORBIDDEN_RUNTIME_PATH_TOKENS if token in lowered]
    if forbidden:
        raise MaterializationError(
            f"label_like_runtime_path_forbidden:{path}:{','.join(forbidden)}"
        )
    path.mkdir(parents=True, exist_ok=True)
    filesystem = subprocess.check_output(
        ["stat", "-f", "-c", "%T", str(path)], text=True
    ).strip()
    if filesystem != "ext2/ext3":
        raise MaterializationError(
            f"runtime_must_be_wsl_ext4_not_9p_or_v9fs:{path}:{filesystem}"
        )
    return filesystem


def compute_tree_sha256(path: Path) -> str:
    if not path.exists():
        raise MaterializationError(f"tree_missing:{path}")
    digest = hashlib.sha256()
    files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    for item in files:
        relative = item.name if path.is_file() else str(item.relative_to(path))
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with item.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def runtime_environment_snapshot() -> dict[str, Any]:
    import platform
    import torch

    if not torch.cuda.is_available():
        raise MaterializationError("frozen_runtime_requires_cuda")
    properties = torch.cuda.get_device_properties(0)
    return {
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": platform.python_version(),
        "torch_version": str(torch.__version__),
        "torch_cuda_version": str(torch.version.cuda),
        "cuda_available": True,
        "cuda_device_count": int(torch.cuda.device_count()),
        "cuda_device_0_name": torch.cuda.get_device_name(0),
        "cuda_device_0_total_memory": int(properties.total_memory),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
    }


def verify_runtime_environment(expected: Mapping[str, Any]) -> dict[str, Any]:
    observed = runtime_environment_snapshot()
    exact_fields = (
        "python_executable",
        "python_version",
        "torch_version",
        "torch_cuda_version",
        "cuda_device_0_name",
        "cuda_device_0_total_memory",
    )
    mismatches = {
        field: {"expected": expected.get(field), "observed": observed.get(field)}
        for field in exact_fields
        if expected.get(field) != observed.get(field)
    }
    if mismatches:
        raise MaterializationError(
            "frozen_runtime_environment_mismatch:" + json.dumps(mismatches, sort_keys=True)
        )
    return observed


def frozen_input_paths(lock: Mapping[str, Any]) -> dict[str, Path]:
    return {
        label: CORE.resolve_locked_path(REPO_ROOT, str(record["path"]))
        for label, record in lock["frozen_inputs"].items()
    }


def dependency_snapshot(lock: Mapping[str, Any]) -> dict[str, Any]:
    inputs = frozen_input_paths(lock)
    contact_receipt = json.loads(
        inputs["contact_feature_release_receipt"].read_text(encoding="utf-8")
    )
    contact_snapshot = contact_receipt.get("input_snapshot", {})
    required_labels = {
        "target_fasta",
        "hotspots",
        "checkpoint_seed43",
        "checkpoint_seed53",
        "checkpoint_seed67",
    }
    if not required_labels <= set(contact_snapshot):
        raise MaterializationError("contact_receipt_dependency_snapshot_incomplete")
    resolved = {
        label: snapshot_file(CORE.resolve_recorded_path(REPO_ROOT, str(row["path"])))
        for label, row in sorted(contact_snapshot.items())
        if label in required_labels
    }
    if resolved["target_fasta"]["sha256"] != EXPECTED_TARGET_SHA256:
        raise MaterializationError("target_fasta_hash_mismatch")
    if resolved["hotspots"]["sha256"] != EXPECTED_HOTSPOT_SHA256:
        raise MaterializationError("hotspot_hash_mismatch")
    for seed, expected in EXPECTED_CONTACT_CHECKPOINT_SHA256.items():
        if resolved[f"checkpoint_seed{seed}"]["sha256"] != expected:
            raise MaterializationError(f"checkpoint_hash_mismatch:{seed}")

    manifest_rows, _ = read_csv(inputs["esm2_residue_cache_manifest"])
    if not manifest_rows:
        raise MaterializationError("empty_esm2_manifest")
    model_path = Path(manifest_rows[0]["model_path"])
    if not model_path.is_absolute():
        model_path = (REPO_ROOT / model_path).resolve()
    model_sha256 = compute_tree_sha256(model_path)
    expected_model = lock["frozen_inputs"]["esm2_residue_cache_manifest"][
        "model_weights_sha256"
    ]
    if model_sha256 != expected_model:
        raise MaterializationError(
            f"esm2_model_hash_mismatch:{model_sha256}:{expected_model}"
        )
    return {
        "materializer": snapshot_file(SCRIPT_PATH),
        "materializer_tests": snapshot_file(TEST_PATH),
        "support_core": snapshot_file(CORE_PATH),
        "esm2_cache_builder": snapshot_file(ESM2_BUILDER_PATH),
        "contact_extractor": snapshot_file(CONTACT_EXTRACTOR_PATH),
        "esm2_model": {
            "path": str(model_path),
            "sha256": model_sha256,
        },
        **resolved,
    }


def _frozen_test_command() -> list[str]:
    return [sys.executable, "-m", "unittest", "-v", *FROZEN_TEST_MODULES]


def validate_frozen_test_log(
    text: str,
    *,
    expected_command: Sequence[str],
    expected_count: int,
) -> dict[str, Any]:
    lines = text.splitlines()
    prefix = "SUPPORT_V3_FROZEN_TEST_COMMAND_JSON="
    command_lines = [line for line in lines if line.startswith(prefix)]
    if len(command_lines) != 1:
        raise MaterializationError("frozen_test_log_command_record_missing_or_duplicate")
    try:
        observed_command = json.loads(command_lines[0][len(prefix) :])
    except json.JSONDecodeError as exc:
        raise MaterializationError("frozen_test_log_command_record_invalid") from exc
    if observed_command != list(expected_command):
        raise MaterializationError("frozen_test_log_command_mismatch")
    matches = re.findall(r"^Ran (\d+) tests? in [^\n]+$", text, flags=re.MULTILINE)
    if matches != [str(expected_count)]:
        raise MaterializationError(
            f"frozen_test_log_count_mismatch:{matches}:{expected_count}"
        )
    if not re.search(r"^OK$", text, flags=re.MULTILINE):
        raise MaterializationError("frozen_test_log_missing_unittest_ok")
    if lines[-1:] != [TEST_PASS_SENTINEL]:
        raise MaterializationError("frozen_test_log_missing_terminal_pass_sentinel")
    if "FAILED (" in text or "Traceback (most recent call last)" in text:
        raise MaterializationError("frozen_test_log_contains_failure")
    return {
        "command": list(expected_command),
        "modules": list(FROZEN_TEST_MODULES),
        "parsed_test_count": int(matches[0]),
        "unittest_status": "OK",
        "terminal_sentinel": TEST_PASS_SENTINEL,
    }


def run_frozen_test_suite(test_log: Path) -> dict[str, Any]:
    command = _frozen_test_command()
    environment = dict(os.environ)
    environment["PYTHONWARNINGS"] = "error"
    test_result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    compile_command = [
        sys.executable,
        "-m",
        "py_compile",
        str(CORE_PATH),
        str(SCRIPT_PATH),
        str(TEST_PATH),
    ]
    compile_result = subprocess.run(
        compile_command,
        cwd=REPO_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    log_text = (
        "SUPPORT_V3_FROZEN_TEST_COMMAND_JSON="
        + json.dumps(command, separators=(",", ":"), ensure_ascii=True)
        + "\n"
        + test_result.stdout
        + "SUPPORT_V3_FROZEN_PYCOMPILE_COMMAND_JSON="
        + json.dumps(compile_command, separators=(",", ":"), ensure_ascii=True)
        + "\n"
        + compile_result.stdout
    )
    if test_result.returncode == 0 and compile_result.returncode == 0:
        log_text += TEST_PASS_SENTINEL + "\n"
    test_log.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=test_log.parent, delete=False
    ) as handle:
        handle.write(log_text)
        temporary = Path(handle.name)
    os.replace(temporary, test_log)
    if test_result.returncode != 0 or compile_result.returncode != 0:
        raise MaterializationError(
            f"frozen_test_execution_failed:unittest={test_result.returncode}:"
            f"pycompile={compile_result.returncode}"
        )
    evidence = validate_frozen_test_log(
        log_text,
        expected_command=command,
        expected_count=EXPECTED_FROZEN_TEST_COUNT,
    )
    return {
        **evidence,
        "unittest_return_code": test_result.returncode,
        "pycompile_command": compile_command,
        "pycompile_return_code": compile_result.returncode,
        "test_log": snapshot_file(test_log),
    }


def create_implementation_freeze(
    *,
    preregistration: Path,
    test_log: Path,
    output: Path,
    receipt_output: Path,
    supersession_record: Path = DEFAULT_SUPERSESSION_RECORD,
) -> dict[str, Any]:
    canonical_paths = {
        "preregistration": (preregistration, DEFAULT_PREREGISTRATION),
        "test_log": (test_log, DEFAULT_TEST_LOG),
        "output": (output, DEFAULT_FREEZE),
        "receipt_output": (receipt_output, DEFAULT_FREEZE_RECEIPT),
        "supersession_record": (supersession_record, DEFAULT_SUPERSESSION_RECORD),
    }
    noncanonical = [
        label
        for label, (observed, expected) in canonical_paths.items()
        if observed.resolve() != expected.resolve()
    ]
    if noncanonical:
        raise MaterializationError(
            "noncanonical_v2_freeze_path_forbidden:" + ",".join(noncanonical)
        )
    before_tests = {
        label: snapshot_file(path)
        for label, path in {
            "materializer": SCRIPT_PATH,
            "materializer_tests": TEST_PATH,
            "support_core": CORE_PATH,
            "preregistration": preregistration,
        }.items()
    }
    test_execution = run_frozen_test_suite(test_log)
    after_tests = {
        label: snapshot_file(Path(record["path"]))
        for label, record in before_tests.items()
    }
    if before_tests != after_tests:
        raise MaterializationError("implementation_or_preregistration_changed_during_tests")
    lock = CORE.load_preregistration(preregistration)
    closure = CORE.validate_frozen_inputs(lock, REPO_ROOT)
    if closure.get("docking_or_experimental_label_paths_opened") != 0:
        raise MaterializationError("input_closure_opened_label_paths")
    dependencies = dependency_snapshot(lock)
    if dependencies["contact_extractor"]["sha256"] != EXPECTED_CONTACT_EXTRACTOR_SHA256:
        raise MaterializationError("contact_extractor_hash_mismatch")
    payload: dict[str, Any] = {
        "schema_version": FREEZE_SCHEMA,
        "status": FREEZE_STATUS,
        "frozen_at": utc_now(),
        "claim_boundary": lock["claim_boundary"],
        "preregistration": snapshot_file(preregistration),
        "test_log": snapshot_file(test_log),
        "test_execution": test_execution,
        "supersedes_preproduction_v1": snapshot_file(supersession_record),
        "dependencies": dependencies,
        "runtime_environment": runtime_environment_snapshot(),
        "frozen_input_sha256": closure["input_sha256"],
        "frozen_input_counts": {
            key: closure[key]
            for key in (
                "candidate_count",
                "split_count",
                "open_train_count",
                "open_train_parent_count",
                "cdr_mask_count",
                "esm2_vhh_cache_count",
                "contact_feature_count",
                "stable_contact_feature_count",
            )
        },
        "label_access": {
            "docking_or_experimental_label_paths_opened": 0,
            "v4_f_label_paths_opened": 0,
        },
        "production_rules": {
            "runtime_filesystem": "WSL ext4 only",
            "null_recompute_sequences": EXPECTED_NULL_RECOMPUTE_COUNT,
            "channel_splice_rows": EXPECTED_CHANNEL_SPLICE_COUNT,
            "publish_only_if_all_gates_pass": True,
            "required_output_set": sorted(
                lock["publication_contract"]["required_outputs"]
            ),
        },
    }
    payload["payload_sha256"] = sha256_json(payload)
    atomic_write_json(output, payload)
    receipt = {
        "schema_version": FREEZE_RECEIPT_SCHEMA,
        "status": "PASS_COMPLETE_HASH_CLOSURE",
        "created_at": utc_now(),
        "implementation_freeze": snapshot_file(output),
        "payload_sha256": payload["payload_sha256"],
        "materializer_sha256": dependencies["materializer"]["sha256"],
        "materializer_tests_sha256": dependencies["materializer_tests"]["sha256"],
        "test_log_sha256": test_execution["test_log"]["sha256"],
        "parsed_test_count": test_execution["parsed_test_count"],
        "preregistration_sha256": payload["preregistration"]["sha256"],
        "docking_or_experimental_label_paths_opened": 0,
    }
    atomic_write_json(receipt_output, receipt)
    return receipt


def verify_implementation_freeze(
    freeze_path: Path, receipt_path: Path, preregistration: Path
) -> dict[str, Any]:
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if freeze.get("schema_version") != FREEZE_SCHEMA or freeze.get("status") != FREEZE_STATUS:
        raise MaterializationError("implementation_freeze_schema_or_status_mismatch")
    claimed = freeze.pop("payload_sha256", None)
    observed_payload = sha256_json(freeze)
    freeze["payload_sha256"] = claimed
    if claimed != observed_payload:
        raise MaterializationError("implementation_freeze_payload_hash_mismatch")
    for label, record in freeze["dependencies"].items():
        if label == "esm2_model":
            if compute_tree_sha256(Path(record["path"])) != record["sha256"]:
                raise MaterializationError("frozen_esm2_model_changed")
        else:
            verify_snapshot(record, f"dependency:{label}")
    verify_snapshot(freeze["preregistration"], "preregistration")
    if freeze["preregistration"]["path"] != str(preregistration.resolve()):
        raise MaterializationError("implementation_freeze_preregistration_path_mismatch")
    verify_snapshot(freeze["test_log"], "test_log")
    test_text = Path(freeze["test_log"]["path"]).read_text(encoding="utf-8")
    parsed_test_evidence = validate_frozen_test_log(
        test_text,
        expected_command=freeze["test_execution"]["command"],
        expected_count=EXPECTED_FROZEN_TEST_COUNT,
    )
    if parsed_test_evidence["parsed_test_count"] != freeze["test_execution"]["parsed_test_count"]:
        raise MaterializationError("implementation_freeze_test_evidence_mismatch")
    verify_snapshot(freeze["supersedes_preproduction_v1"], "supersession_record")
    verify_runtime_environment(freeze["runtime_environment"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (
        receipt.get("schema_version") != FREEZE_RECEIPT_SCHEMA
        or receipt.get("status") != "PASS_COMPLETE_HASH_CLOSURE"
    ):
        raise MaterializationError("implementation_freeze_receipt_invalid")
    if receipt.get("implementation_freeze", {}).get("sha256") != sha256_file(freeze_path):
        raise MaterializationError("implementation_freeze_receipt_hash_mismatch")
    if receipt.get("payload_sha256") != claimed:
        raise MaterializationError("implementation_freeze_receipt_payload_mismatch")
    if int(receipt.get("docking_or_experimental_label_paths_opened", -1)) != 0:
        raise MaterializationError("implementation_freeze_receipt_label_access_nonzero")
    return freeze


def l2_normalize(values: Any, label: str) -> Any:
    import numpy as np

    array = np.asarray(values, dtype=np.float64).reshape(-1)
    if array.size == 0 or not np.isfinite(array).all():
        raise MaterializationError(f"invalid_vector:{label}")
    norm = float(np.linalg.norm(array))
    if norm <= 0.0:
        raise MaterializationError(f"zero_norm_vector:{label}")
    return (array / norm).astype(np.float32)


def summarize_embedding_array(embedding: Any, cdr_mask: Sequence[int]) -> tuple[Any, Any]:
    import numpy as np

    array = np.asarray(embedding, dtype=np.float32)
    mask = np.asarray(cdr_mask, dtype=np.int8)
    if array.ndim != 2 or array.shape[0] != mask.shape[0]:
        raise MaterializationError("embedding_mask_shape_mismatch")
    full = l2_normalize(
        np.concatenate((array.mean(axis=0), array.std(axis=0, ddof=0))),
        "full_esm",
    )
    pieces: list[Any] = []
    for cdr_type in (1, 2, 3):
        selected = array[mask == cdr_type]
        if selected.shape[0] == 0:
            raise MaterializationError(f"empty_cdr_embedding:{cdr_type}")
        pieces.extend((selected.mean(axis=0), selected.std(axis=0, ddof=0)))
    cdr = l2_normalize(np.concatenate(pieces), "cdr_esm")
    return full, cdr


def load_embedding_summaries(
    manifest_path: Path,
    mask_by_sha: Mapping[str, Mapping[str, str]],
    required_hashes: set[str],
) -> dict[str, tuple[Any, Any]]:
    import torch

    rows, fields = read_csv(manifest_path)
    required_fields = {"sequence_sha256", "shard_path", "shard_key", "cached_length"}
    if not required_fields <= set(fields):
        raise MaterializationError("esm2_manifest_schema_mismatch")
    selected = {row["sequence_sha256"]: row for row in rows if row["sequence_sha256"] in required_hashes}
    if set(selected) != required_hashes:
        raise MaterializationError("esm2_manifest_required_sequence_set_mismatch")
    by_shard: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in selected.values():
        by_shard[row["shard_path"]].append(row)
    output: dict[str, tuple[Any, Any]] = {}
    for shard_name, shard_rows in sorted(by_shard.items()):
        shard_path = manifest_path.parent / shard_name
        payload = torch.load(shard_path, map_location="cpu", weights_only=True)
        if not isinstance(payload, dict):
            raise MaterializationError(f"esm2_shard_payload_invalid:{shard_name}")
        for row in shard_rows:
            digest = row["sequence_sha256"]
            tensor = payload.get(row.get("shard_key") or digest)
            if tensor is None or tensor.ndim != 2:
                raise MaterializationError(f"esm2_tensor_missing_or_invalid:{digest}")
            expected_length = int(row["cached_length"])
            mask_row = mask_by_sha.get(digest)
            if mask_row is None:
                raise MaterializationError(f"cdr_mask_missing_for_embedding:{digest}")
            mask = [int(value) for value in json.loads(mask_row["cdr_mask_json"])]
            if tensor.shape[0] != expected_length or len(mask) != expected_length:
                raise MaterializationError(f"esm2_tensor_mask_length_mismatch:{digest}")
            output[digest] = summarize_embedding_array(tensor.float().numpy(), mask)
        del payload
    return output


@dataclass(frozen=True)
class MaterializedRecord:
    candidate_id: str
    sequence_sha256: str
    declared_parent: str
    sequence: str
    full_esm: Any
    cdr_esm: Any
    cdr1: str
    cdr2: str
    cdr3: str
    contact: Any


@dataclass(frozen=True)
class DomainResult:
    label: str
    neighbor_id: str
    neighbor_parent: str
    distances: Mapping[str, float]


@dataclass(frozen=True)
class NullSequence:
    kind: str
    record_index: int
    candidate_id: str
    sequence_sha256: str
    declared_parent: str
    sequence: str
    cdr1: str
    cdr2: str
    cdr3: str
    spans: Mapping[str, tuple[int, int]]
    source_ids: tuple[str, ...]
    source_parents: tuple[str, ...]


def robust_scale(
    values_by_id: Mapping[str, Sequence[float]], reference_ids: Sequence[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    import numpy as np

    reference = np.asarray([values_by_id[candidate_id] for candidate_id in reference_ids], dtype=np.float64)
    if reference.ndim != 2 or not np.isfinite(reference).all():
        raise MaterializationError("invalid_reference_contact_matrix")
    q1, median, q3 = np.quantile(
        reference, [0.25, 0.5, 0.75], axis=0, method="linear"
    )
    iqr = q3 - q1
    if np.any(iqr <= 1e-12):
        raise MaterializationError("zero_or_near_zero_reference_contact_iqr")
    scaled = {
        candidate_id: ((np.asarray(values, dtype=np.float64) - median) / iqr).astype(np.float32)
        for candidate_id, values in values_by_id.items()
    }
    return scaled, {
        "median": median.tolist(),
        "q1": q1.tolist(),
        "q3": q3.tolist(),
        "iqr": iqr.tolist(),
        "fit_row_count": len(reference_ids),
        "fit_candidate_ids_sha256": sha256_bytes(
            "\n".join(reference_ids).encode("utf-8")
        ),
        "fit_policy": "OPEN_TRAIN_only_numpy_quantile_linear",
    }


def weighted_linear_quantile(
    values: Sequence[float], groups: Sequence[str], quantile: float
) -> float:
    """Weighted linear quantile with equal total mass per parent group."""

    if len(values) != len(groups) or not values or not 0.0 <= quantile <= 1.0:
        raise MaterializationError("invalid_weighted_quantile_input")
    counts = Counter(groups)
    rows = sorted(
        (float(value), str(group), 1.0 / counts[str(group)])
        for value, group in zip(values, groups)
    )
    mass_by_value: dict[float, float] = defaultdict(float)
    for value, _group, weight in rows:
        mass_by_value[value] += weight
    collapsed = sorted(mass_by_value.items())
    total = sum(weight for _value, weight in collapsed)
    positions: list[float] = []
    ordered: list[float] = []
    cumulative = 0.0
    for value, weight in collapsed:
        positions.append((cumulative + 0.5 * weight) / total)
        ordered.append(value)
        cumulative += weight
    if quantile <= positions[0]:
        return ordered[0]
    if quantile >= positions[-1]:
        return ordered[-1]
    for index in range(1, len(positions)):
        if quantile <= positions[index]:
            left_position, right_position = positions[index - 1], positions[index]
            fraction = (quantile - left_position) / (right_position - left_position)
            return ordered[index - 1] + fraction * (ordered[index] - ordered[index - 1])
    raise MaterializationError("weighted_quantile_interpolation_failed")


def _kmer_counts(cdrs: Sequence[str], k: int) -> Counter[str]:
    counts: Counter[str] = Counter()
    for region, sequence in enumerate(cdrs, start=1):
        for index in range(max(0, len(sequence) - k + 1)):
            counts[f"{region}:{sequence[index:index + k]}"] += 1
    return counts


@lru_cache(maxsize=50000)
def _cached_kmer_counts(cdr1: str, cdr2: str, cdr3: str, k: int) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(_kmer_counts((cdr1, cdr2, cdr3), k).items()))


@lru_cache(maxsize=2_000_000)
def _cached_edit(left: str, right: str) -> float:
    return CORE.normalized_levenshtein(left, right)


def _sparse_cosine(left: Mapping[str, int], right: Mapping[str, int]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm <= 0.0 or right_norm <= 0.0:
        raise MaterializationError("null_kmer_norm")
    dot = sum(left[key] * right[key] for key in set(left) & set(right))
    return max(0.0, min(1.0, 1.0 - dot / (left_norm * right_norm)))


def channel_distances(query: MaterializedRecord, reference: MaterializedRecord) -> dict[str, float]:
    import numpy as np

    full = float(1.0 - np.dot(query.full_esm, reference.full_esm))
    cdr = float(1.0 - np.dot(query.cdr_esm, reference.cdr_esm))
    contact = float(
        np.sqrt(np.mean((np.asarray(query.contact) - np.asarray(reference.contact)) ** 2))
    )
    return {
        "full_esm_cosine": max(0.0, min(2.0, full)),
        "cdr_esm_cosine": max(0.0, min(2.0, cdr)),
        "cdr1_edit": _cached_edit(query.cdr1, reference.cdr1),
        "cdr2_edit": _cached_edit(query.cdr2, reference.cdr2),
        "cdr3_edit": _cached_edit(query.cdr3, reference.cdr3),
        "cdr_2mer_cosine": _sparse_cosine(
            dict(_cached_kmer_counts(query.cdr1, query.cdr2, query.cdr3, 2)),
            dict(_cached_kmer_counts(reference.cdr1, reference.cdr2, reference.cdr3, 2)),
        ),
        "cdr_3mer_cosine": _sparse_cosine(
            dict(_cached_kmer_counts(query.cdr1, query.cdr2, query.cdr3, 3)),
            dict(_cached_kmer_counts(reference.cdr1, reference.cdr2, reference.cdr3, 3)),
        ),
        "contact_euclidean": contact,
    }


def calibrate_thresholds(
    references: Sequence[MaterializedRecord], quantile: float
) -> tuple[dict[str, float], dict[str, float], dict[str, Any]]:
    if not references:
        raise MaterializationError("empty_calibration_reference")
    by_parent: dict[str, list[MaterializedRecord]] = defaultdict(list)
    for row in references:
        by_parent[row.declared_parent].append(row)
    if min(map(len, by_parent.values())) < 2:
        raise MaterializationError("calibration_parent_has_fewer_than_two_rows")
    same_values = {channel: [] for channel in CORE.REQUIRED_CHANNELS}
    global_values = {channel: [] for channel in CORE.REQUIRED_CHANNELS}
    groups: list[str] = []
    for query in references:
        same = [
            row
            for row in by_parent[query.declared_parent]
            if row.candidate_id != query.candidate_id
            and row.sequence_sha256 != query.sequence_sha256
        ]
        cross = [row for row in references if row.declared_parent != query.declared_parent]
        if not same or not cross:
            raise MaterializationError("calibration_neighbor_set_empty")
        same_distances = [channel_distances(query, row) for row in same]
        cross_distances = [channel_distances(query, row) for row in cross]
        for channel in CORE.REQUIRED_CHANNELS:
            same_values[channel].append(min(row[channel] for row in same_distances))
            global_values[channel].append(min(row[channel] for row in cross_distances))
        groups.append(query.declared_parent)
    same_thresholds = {
        channel: weighted_linear_quantile(values, groups, quantile)
        for channel, values in same_values.items()
    }
    global_thresholds = {
        channel: weighted_linear_quantile(values, groups, quantile)
        for channel, values in global_values.items()
    }
    summary = {
        "quantile": quantile,
        "quantile_method": "equal-parent-mass midpoint-CDF linear interpolation",
        "row_count": len(references),
        "parent_count": len(by_parent),
        "same_parent_thresholds": same_thresholds,
        "global_cross_parent_thresholds": global_thresholds,
        "channel_nearest_summaries": {
            scope: {
                channel: {
                    "minimum": min(values[channel]),
                    "maximum": max(values[channel]),
                    "mean": sum(values[channel]) / len(values[channel]),
                }
                for channel in CORE.REQUIRED_CHANNELS
            }
            for scope, values in (("same_parent", same_values), ("cross_parent", global_values))
        },
    }
    return same_thresholds, global_thresholds, summary


def _passing_neighbor(
    query: MaterializedRecord,
    references: Sequence[MaterializedRecord],
    thresholds: Mapping[str, float],
) -> tuple[MaterializedRecord, dict[str, float]] | None:
    passing: list[tuple[float, str, MaterializedRecord, dict[str, float]]] = []
    for reference in references:
        distances = channel_distances(query, reference)
        if all(distances[channel] <= float(thresholds[channel]) for channel in CORE.REQUIRED_CHANNELS):
            ratios = [
                0.0
                if float(thresholds[channel]) == 0.0
                else distances[channel] / float(thresholds[channel])
                for channel in CORE.REQUIRED_CHANNELS
            ]
            passing.append((max(ratios), reference.candidate_id, reference, distances))
    if not passing:
        return None
    _ratio, _candidate_id, reference, distances = min(passing, key=lambda item: (item[0], item[1]))
    return reference, distances


def classify_record(
    query: MaterializedRecord,
    references: Sequence[MaterializedRecord],
    same_thresholds: Mapping[str, float],
    global_thresholds: Mapping[str, float],
    *,
    excluded_ids: Iterable[str] = (),
    excluded_parents: Iterable[str] = (),
) -> DomainResult:
    excluded_id_set = set(excluded_ids)
    excluded_parent_set = set(excluded_parents)
    available = [
        row
        for row in references
        if row.candidate_id not in excluded_id_set
        and row.declared_parent not in excluded_parent_set
    ]
    exact = [
        row
        for row in available
        if row.candidate_id == query.candidate_id
        or row.sequence_sha256 == query.sequence_sha256
    ]
    if exact:
        reference = min(exact, key=lambda row: row.candidate_id)
        return DomainResult("TRAIN_REFERENCE", reference.candidate_id, reference.declared_parent, {})
    same = [row for row in available if row.declared_parent == query.declared_parent]
    matched = _passing_neighbor(query, same, same_thresholds)
    if matched is not None:
        reference, distances = matched
        return DomainResult("IN_DOMAIN", reference.candidate_id, reference.declared_parent, distances)
    cross = [row for row in available if row.declared_parent != query.declared_parent]
    matched = _passing_neighbor(query, cross, global_thresholds)
    if matched is not None:
        reference, distances = matched
        return DomainResult("NEAR_DOMAIN", reference.candidate_id, reference.declared_parent, distances)
    return DomainResult("OUT_OF_DOMAIN", "", "", {})


def deterministic_fold(candidate_hash: str, folds: int, seed: int) -> int:
    digest = hashlib.sha256(f"{seed}:{candidate_hash}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big") % folds


def nested_validation(
    references: Sequence[MaterializedRecord], lock: Mapping[str, Any]
) -> dict[str, Any]:
    contract = lock["calibration"]["nested_validation"]
    folds = int(contract["folds"])
    seed = int(contract["seed"])
    minimum_parent_rows = int(contract["minimum_parent_rows"])
    by_parent = Counter(row.declared_parent for row in references)
    if min(by_parent.values()) < minimum_parent_rows:
        raise MaterializationError("nested_validation_parent_below_minimum_rows")
    totals = Counter()
    parent_totals: dict[str, Counter[str]] = defaultdict(Counter)
    fold_rows: list[dict[str, Any]] = []
    for fold in range(folds):
        validation = [
            row
            for row in references
            if deterministic_fold(row.sequence_sha256, folds, seed) == fold
        ]
        calibration = [
            row
            for row in references
            if deterministic_fold(row.sequence_sha256, folds, seed) != fold
        ]
        if not validation:
            raise MaterializationError(f"nested_validation_empty_fold:{fold}")
        same_thresholds, global_thresholds, threshold_audit = calibrate_thresholds(
            calibration, float(lock["calibration"]["threshold_quantile"])
        )
        fold_counts = Counter()
        for query in validation:
            decision = classify_record(
                query, calibration, same_thresholds, global_thresholds
            )
            fold_counts["rows"] += 1
            fold_counts["in_domain"] += int(decision.label == "IN_DOMAIN")
            parent_totals[query.declared_parent]["rows"] += 1
            parent_totals[query.declared_parent]["in_domain"] += int(
                decision.label == "IN_DOMAIN"
            )
        totals.update(fold_counts)
        fold_rows.append(
            {
                "fold": fold,
                "calibration_rows": len(calibration),
                "validation_rows": len(validation),
                "validation_in_domain_fraction": fold_counts["in_domain"] / fold_counts["rows"],
                "thresholds": threshold_audit,
            }
        )
    parent_fractions = {
        parent: counts["in_domain"] / counts["rows"]
        for parent, counts in sorted(parent_totals.items())
    }
    return {
        "policy": contract["policy"],
        "fold_count": folds,
        "seed": seed,
        "row_count": totals["rows"],
        "in_domain_fraction": totals["in_domain"] / totals["rows"],
        "parent_fractions": parent_fractions,
        "folds": fold_rows,
    }


def _rng(seed: int, kind: str, index: int, attempt: int) -> random.Random:
    digest = hashlib.sha256(f"{seed}:{kind}:{index}:{attempt}".encode("ascii")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _shuffle_text(value: str, rng: random.Random) -> str:
    letters = list(value)
    rng.shuffle(letters)
    return "".join(letters)


def _replace_cdrs(
    framework: MaterializedRecord,
    donor: MaterializedRecord,
    framework_spans: Mapping[str, tuple[int, int]],
) -> tuple[str, dict[str, tuple[int, int]]]:
    pieces: list[str] = []
    spans: dict[str, tuple[int, int]] = {}
    cursor = 0
    output_length = 0
    for name, donor_cdr in (("cdr1", donor.cdr1), ("cdr2", donor.cdr2), ("cdr3", donor.cdr3)):
        start, end = framework_spans[name]
        framework_piece = framework.sequence[cursor:start]
        pieces.append(framework_piece)
        output_length += len(framework_piece)
        new_start = output_length
        pieces.append(donor_cdr)
        output_length += len(donor_cdr)
        spans[name] = (new_start, output_length)
        cursor = end
    pieces.append(framework.sequence[cursor:])
    return "".join(pieces), spans


def generate_null_sequences(
    references: Sequence[MaterializedRecord],
    spans_by_sha: Mapping[str, Mapping[str, tuple[int, int]]],
    *,
    replicates_each: int,
    seed: int,
    forbidden_sequence_hashes: Iterable[str] = (),
) -> list[NullSequence]:
    by_parent: dict[str, list[MaterializedRecord]] = defaultdict(list)
    for row in references:
        by_parent[row.declared_parent].append(row)
    parents = sorted(by_parent)
    if len(parents) < 3:
        raise MaterializationError("null_generation_requires_three_parents")
    used_sequences = {
        *(row.sequence_sha256 for row in references),
        *map(str, forbidden_sequence_hashes),
    }
    output: list[NullSequence] = []

    def choose_source(parent: str, rng: random.Random) -> MaterializedRecord:
        rows = sorted(by_parent[parent], key=lambda row: row.candidate_id)
        return rows[rng.randrange(len(rows))]

    for kind in ("cdr_composition_shuffle", "cross_parent_cdr_graft", "unseen_parent_chimera"):
        for index in range(replicates_each):
            created: NullSequence | None = None
            for attempt in range(1000):
                rng = _rng(seed, kind, index, attempt)
                parent_a = parents[index % len(parents)]
                source_a = choose_source(parent_a, rng)
                spans_a = spans_by_sha[source_a.sequence_sha256]
                if kind == "cdr_composition_shuffle":
                    shuffled = {
                        name: _shuffle_text(getattr(source_a, name), rng)
                        for name in ("cdr1", "cdr2", "cdr3")
                    }
                    donor = MaterializedRecord(
                        candidate_id="shuffle_donor",
                        sequence_sha256="0" * 64,
                        declared_parent=parent_a,
                        sequence="",
                        full_esm=source_a.full_esm,
                        cdr_esm=source_a.cdr_esm,
                        cdr1=shuffled["cdr1"],
                        cdr2=shuffled["cdr2"],
                        cdr3=shuffled["cdr3"],
                        contact=source_a.contact,
                    )
                    sequence, spans = _replace_cdrs(source_a, donor, spans_a)
                    source_ids = (source_a.candidate_id,)
                    source_parents = (parent_a,)
                    declared_parent = parent_a
                    cdrs = (donor.cdr1, donor.cdr2, donor.cdr3)
                else:
                    offset = 1 + rng.randrange(len(parents) - 1)
                    parent_b = parents[(parents.index(parent_a) + offset) % len(parents)]
                    source_b = choose_source(parent_b, rng)
                    sequence, spans = _replace_cdrs(source_a, source_b, spans_a)
                    source_ids = (source_a.candidate_id, source_b.candidate_id)
                    source_parents = (parent_a, parent_b)
                    declared_parent = (
                        parent_a
                        if kind == "cross_parent_cdr_graft"
                        else f"UNSEEN_CHIMERA_{index:04d}"
                    )
                    cdrs = (source_b.cdr1, source_b.cdr2, source_b.cdr3)
                digest = sha256_bytes(sequence.encode("ascii"))
                if digest in used_sequences:
                    continue
                used_sequences.add(digest)
                candidate_id = {
                    "cdr_composition_shuffle": "NULL_SHUFFLE",
                    "cross_parent_cdr_graft": "NULL_GRAFT",
                    "unseen_parent_chimera": "NULL_UNSEEN",
                }[kind] + f"_{index:04d}"
                created = NullSequence(
                    kind=kind,
                    record_index=index,
                    candidate_id=candidate_id,
                    sequence_sha256=digest,
                    declared_parent=declared_parent,
                    sequence=sequence,
                    cdr1=cdrs[0],
                    cdr2=cdrs[1],
                    cdr3=cdrs[2],
                    spans=spans,
                    source_ids=source_ids,
                    source_parents=source_parents,
                )
                break
            if created is None:
                raise MaterializationError(f"null_generation_exhausted:{kind}:{index}")
            output.append(created)
    if len(output) != 3 * replicates_each:
        raise MaterializationError("null_sequence_count_mismatch")
    if len({row.sequence_sha256 for row in output}) != len(output):
        raise MaterializationError("null_sequences_not_unique")
    return output


def write_null_adapter(
    rows: Sequence[NullSequence], adapter_path: Path, mask_path: Path, provenance_path: Path
) -> None:
    adapter_rows: list[dict[str, str]] = []
    mask_rows: list[dict[str, str]] = []
    provenance_rows: list[dict[str, Any]] = []
    for row in rows:
        mask = [0] * len(row.sequence)
        spans_payload: dict[str, list[int]] = {}
        for cdr_type, name in enumerate(("cdr1", "cdr2", "cdr3"), start=1):
            start, end = row.spans[name]
            value = getattr(row, name)
            if row.sequence[start:end] != value:
                raise MaterializationError(f"null_cdr_span_mismatch:{row.candidate_id}:{name}")
            mask[start:end] = [cdr_type] * (end - start)
            spans_payload[name] = [start, end]
        adapter_rows.append(
            {
                "candidate_id": row.candidate_id,
                "sequence_sha256": row.sequence_sha256,
                "vhh_seq": row.sequence,
                "cdr1": row.cdr1,
                "cdr2": row.cdr2,
                "cdr3": row.cdr3,
                "cdr1_span_0based": f"{row.spans['cdr1'][0]}-{row.spans['cdr1'][1]}",
                "cdr2_span_0based": f"{row.spans['cdr2'][0]}-{row.spans['cdr2'][1]}",
                "cdr3_span_0based": f"{row.spans['cdr3'][0]}-{row.spans['cdr3'][1]}",
                "parent_framework_cluster": row.declared_parent,
                "design_method": "SupportV3_label_free_null",
                "design_mode": row.kind,
                "target_patch_id": "LABEL_FREE_NULL",
            }
        )
        mask_rows.append(
            {
                "sequence_hash": row.sequence_sha256,
                "vhh_seq": row.sequence,
                "vhh_len": str(len(row.sequence)),
                "cdr_mask_json": json.dumps(mask, separators=(",", ":")),
                "spans_json": json.dumps(spans_payload, separators=(",", ":"), sort_keys=True),
                "cdr1_seq": row.cdr1,
                "cdr2_seq": row.cdr2,
                "cdr3_seq": row.cdr3,
                "annotation_source": "phase2_v4_d_sequence_support_v3_null_adapter_v1",
                "status": "exact_annotation",
                "fallback_reason": "",
                "manifest_sources_json": '["support_v3_label_free_null"]',
            }
        )
        provenance_rows.append(
            {
                "kind": row.kind,
                "record_index": row.record_index,
                "candidate_id": row.candidate_id,
                "sequence_sha256": row.sequence_sha256,
                "declared_parent": row.declared_parent,
                "source_ids": list(row.source_ids),
                "source_parents": list(row.source_parents),
            }
        )
    atomic_write_csv(adapter_path, adapter_rows, list(adapter_rows[0]))
    atomic_write_csv(mask_path, mask_rows, list(mask_rows[0]))
    atomic_write_json(
        provenance_path,
        {
            "schema_version": "phase2_v4_d_sequence_support_v3_null_provenance_v1",
            "status": "PASS_LABEL_FREE_NULL_PANEL_FROZEN",
            "row_count": len(rows),
            "adapter_sha256": sha256_file(adapter_path),
            "mask_sha256": sha256_file(mask_path),
            "docking_or_experimental_label_paths_opened": 0,
            "rows": provenance_rows,
        },
    )


def validate_null_adapter_boundary(adapter_path: Path, expected_count: int) -> None:
    rows, fields = read_csv(adapter_path)
    expected_fields = [
        "candidate_id",
        "sequence_sha256",
        "vhh_seq",
        "cdr1",
        "cdr2",
        "cdr3",
        "cdr1_span_0based",
        "cdr2_span_0based",
        "cdr3_span_0based",
        "parent_framework_cluster",
        "design_method",
        "design_mode",
        "target_patch_id",
    ]
    forbidden_tokens = (
        "docking",
        "haddock",
        "teacher_label",
        "experimental",
        "blocking_label",
        "geometry",
        "v4_f",
    )
    bad = sorted(
        field for field in fields if any(token in field.lower() for token in forbidden_tokens)
    )
    if bad:
        raise MaterializationError(
            "null_adapter_label_like_columns_forbidden:" + ",".join(bad)
        )
    if fields != expected_fields or len(rows) != expected_count:
        raise MaterializationError("null_adapter_schema_or_count_mismatch")
    for row in rows:
        digest = sha256_bytes(row["vhh_seq"].encode("ascii"))
        if digest != row["sequence_sha256"]:
            raise MaterializationError(
                f"null_adapter_sequence_hash_mismatch:{row['candidate_id']}"
            )


def ordered_null_identity(rows: Sequence[NullSequence]) -> tuple[list[dict[str, Any]], str]:
    identity = [
        {
            "kind": row.kind,
            "record_index": row.record_index,
            "candidate_id": row.candidate_id,
            "sequence_sha256": row.sequence_sha256,
            "declared_parent": row.declared_parent,
            "cdr1": row.cdr1,
            "cdr2": row.cdr2,
            "cdr3": row.cdr3,
            "spans": {name: list(row.spans[name]) for name in ("cdr1", "cdr2", "cdr3")},
            "source_ids": list(row.source_ids),
            "source_parents": list(row.source_parents),
        }
        for row in rows
    ]
    return identity, sha256_json(identity)


def manifest_identity_sha256(rows: Sequence[Mapping[str, str]]) -> str:
    fields = (
        "model_sha256",
        "sequence_sha256",
        "sequence_length",
        "cached_length",
        "truncation_policy",
        "chain_type",
        "shard_path",
        "shard_key",
    )
    return sha256_json(
        [
            {field: row.get(field, "") for field in fields}
            for row in sorted(rows, key=lambda row: row["sequence_sha256"])
        ]
    )


def shard_payload_key_closure(manifest_path: Path, rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    import torch

    expected_by_shard: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        expected_by_shard[row["shard_path"]].add(row.get("shard_key") or row["sequence_sha256"])
    observed_all: list[str] = []
    for shard_name, expected in sorted(expected_by_shard.items()):
        payload = torch.load(
            manifest_path.parent / shard_name,
            map_location="cpu",
            weights_only=True,
        )
        if not isinstance(payload, dict) or set(payload) != expected:
            raise MaterializationError(f"null_cache_shard_key_set_mismatch:{shard_name}")
        observed_all.extend(sorted(payload))
        del payload
    return {
        "shard_count": len(expected_by_shard),
        "shard_key_count": len(observed_all),
        "shard_payload_keys_sha256": sha256_bytes(
            "\n".join(sorted(observed_all)).encode("ascii")
        ),
    }


def validate_null_cache_state(
    cache_dir: Path,
    receipt_path: Path,
    expected_panel_sha256: str,
    *,
    expected_ordered_identity_sha256: str | None = None,
    adapter_path: Path | None = None,
    mask_path: Path | None = None,
    provenance_path: Path | None = None,
    expected_model_sha256: str | None = None,
    expected_builder_sha256: str | None = None,
    target_path: Path | None = None,
    expected_target_sha256: str | None = None,
    expected_null_rows: Sequence[NullSequence] | None = None,
) -> dict[str, Any] | None:
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (
            receipt.get("schema_version")
            != "phase2_v4_d_sequence_support_v3_null_esm2_cache_receipt_v2"
            or receipt.get("status") != "PASS_COMPLETE_LABEL_FREE_CACHE_CLOSURE"
        ):
            raise MaterializationError("existing_null_cache_receipt_schema_or_status_mismatch")
        if receipt.get("null_panel_sha256") != expected_panel_sha256:
            raise MaterializationError("existing_null_cache_panel_hash_mismatch")
        required = {
            "adapter",
            "masks",
            "provenance",
            "target_fasta",
            "manifest",
        }
        if not required <= set(receipt):
            raise MaterializationError("existing_null_cache_receipt_binding_set_incomplete")
        if None in (
            expected_ordered_identity_sha256,
            adapter_path,
            mask_path,
            provenance_path,
            expected_model_sha256,
            expected_builder_sha256,
            target_path,
            expected_target_sha256,
        ) or expected_null_rows is None:
            raise MaterializationError("null_cache_reuse_expected_bindings_missing")
        if receipt.get("ordered_identity_sha256") != expected_ordered_identity_sha256:
            raise MaterializationError("existing_null_cache_ordered_identity_mismatch")
        if receipt.get("model_sha256") != expected_model_sha256:
            raise MaterializationError("existing_null_cache_model_hash_mismatch")
        if receipt.get("esm2_builder_sha256") != expected_builder_sha256:
            raise MaterializationError("existing_null_cache_builder_hash_mismatch")
        current_bindings = {
            "adapter": snapshot_file(adapter_path),
            "masks": snapshot_file(mask_path),
            "provenance": snapshot_file(provenance_path),
            "target_fasta": snapshot_file(target_path),
        }
        if current_bindings != {label: receipt[label] for label in current_bindings}:
            raise MaterializationError("existing_null_cache_current_input_binding_mismatch")
        if current_bindings["target_fasta"]["sha256"] != expected_target_sha256:
            raise MaterializationError("existing_null_cache_target_hash_mismatch")
        for label, record in receipt.get("artifacts", {}).items():
            artifact_path = verify_snapshot(record, f"null_cache:{label}")
            require_path_within(artifact_path, cache_dir, f"null_cache:{label}")
        manifest_path = verify_snapshot(receipt["manifest"], "null_cache:manifest")
        require_path_within(manifest_path, cache_dir, "null_cache:manifest")
        manifest_rows, _ = read_csv(manifest_path)
        expected_artifact_labels = {
            f"shard:{shard_name}"
            for shard_name in {row["shard_path"] for row in manifest_rows}
        }
        if set(receipt.get("artifacts", {})) != expected_artifact_labels:
            raise MaterializationError("existing_null_cache_exact_artifact_set_mismatch")
        expected_null_by_hash = {
            row.sequence_sha256: row for row in expected_null_rows
        }
        target_sequence = "".join(
            line.strip()
            for line in target_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith(">")
        )
        target_digest = sha256_bytes(target_sequence.encode("utf-8"))
        if {row["sequence_sha256"] for row in manifest_rows} != {
            *expected_null_by_hash,
            target_digest,
        }:
            raise MaterializationError("existing_null_cache_manifest_sequence_set_mismatch")
        for row in manifest_rows:
            digest = row["sequence_sha256"]
            if row["model_sha256"] != expected_model_sha256 or row["shard_key"] != digest:
                raise MaterializationError("existing_null_cache_manifest_model_or_key_mismatch")
            if digest in expected_null_by_hash:
                expected_row = expected_null_by_hash[digest]
                if int(row["sequence_length"]) != len(expected_row.sequence):
                    raise MaterializationError("existing_null_cache_manifest_length_mismatch")
        if manifest_identity_sha256(manifest_rows) != receipt.get("manifest_identity_sha256"):
            raise MaterializationError("existing_null_cache_manifest_identity_mismatch")
        payload_closure = shard_payload_key_closure(manifest_path, manifest_rows)
        if payload_closure != receipt.get("shard_payload_closure"):
            raise MaterializationError("existing_null_cache_shard_payload_closure_mismatch")
        return receipt
    if cache_dir.exists() and any(cache_dir.iterdir()):
        raise MaterializationError("partial_null_cache_without_receipt_fail_closed")
    return None


def materialize_null_features(
    *,
    null_rows: Sequence[NullSequence],
    adapter_path: Path,
    mask_path: Path,
    provenance_path: Path,
    runtime_root: Path,
    lock: Mapping[str, Any],
    freeze: Mapping[str, Any],
) -> tuple[Path, Path, dict[str, Any]]:
    cache_dir = runtime_root / "null_esm2_cache"
    contact_dir = runtime_root / "null_contact_features"
    contact_dir.mkdir(parents=True, exist_ok=True)
    ordered_identity, ordered_identity_sha = ordered_null_identity(null_rows)
    null_panel_hash = sha256_json(
        [(row.candidate_id, row.sequence_sha256, row.kind) for row in null_rows]
    )
    cache_receipt_path = cache_dir / "support_v3_null_cache.receipt.json"
    contact_receipt_path = contact_dir / "support_v3_null_contact.receipt.json"

    dependencies = freeze["dependencies"]
    model_path = Path(dependencies["esm2_model"]["path"])
    target_path = Path(dependencies["target_fasta"]["path"])
    hotspot_path = Path(dependencies["hotspots"]["path"])
    checkpoints = [Path(dependencies[f"checkpoint_seed{seed}"]["path"]) for seed in (43, 53, 67)]

    cache_receipt = validate_null_cache_state(
        cache_dir,
        cache_receipt_path,
        null_panel_hash,
        expected_ordered_identity_sha256=ordered_identity_sha,
        adapter_path=adapter_path,
        mask_path=mask_path,
        provenance_path=provenance_path,
        expected_model_sha256=dependencies["esm2_model"]["sha256"],
        expected_builder_sha256=dependencies["esm2_cache_builder"]["sha256"],
        target_path=target_path,
        expected_target_sha256=dependencies["target_fasta"]["sha256"],
        expected_null_rows=null_rows,
    )
    if cache_receipt is None:
        esm2_builder = _load_module("support_v3_esm2_builder", ESM2_BUILDER_PATH)
        absent = runtime_root / "intentionally_absent_inputs"
        summary = esm2_builder.build_cache(
            model_path=model_path,
            output_dir=cache_dir,
            site_manifest=absent / "site.csv",
            pair_manifest=absent / "pair.csv",
            ranking_manifest=absent / "ranking.csv",
            contact_maps=absent / "contact.jsonl",
            inference_candidates=adapter_path,
            target_fasta=target_path,
            batch_size=64,
            attention_budget=1_500_000,
            shard_size=512,
            max_residues=1024,
            device_name="cuda",
            generic_binding_csv=None,
        )
        manifest = Path(str(summary["manifest"]))
        manifest_rows, _ = read_csv(manifest)
        required_hashes = {row.sequence_sha256 for row in null_rows}
        target_sequence = "".join(
            line.strip()
            for line in target_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith(">")
        )
        required_hashes.add(sha256_bytes(target_sequence.encode("utf-8")))
        if {row["sequence_sha256"] for row in manifest_rows} != required_hashes:
            raise MaterializationError("null_cache_sequence_set_mismatch")
        if any(
            row["model_sha256"] != lock["frozen_inputs"]["esm2_residue_cache_manifest"]["model_weights_sha256"]
            for row in manifest_rows
        ):
            raise MaterializationError("null_cache_model_hash_mismatch")
        artifacts: dict[str, Any] = {}
        for shard in sorted({row["shard_path"] for row in manifest_rows}):
            artifacts[f"shard:{shard}"] = snapshot_file(manifest.parent / shard)
        payload_closure = shard_payload_key_closure(manifest, manifest_rows)
        cache_receipt = {
            "schema_version": "phase2_v4_d_sequence_support_v3_null_esm2_cache_receipt_v2",
            "status": "PASS_COMPLETE_LABEL_FREE_CACHE_CLOSURE",
            "created_at": utc_now(),
            "null_panel_sha256": null_panel_hash,
            "ordered_identity_sha256": ordered_identity_sha,
            "ordered_identity_row_count": len(ordered_identity),
            "row_count": len(null_rows),
            "model_sha256": dependencies["esm2_model"]["sha256"],
            "esm2_builder_sha256": dependencies["esm2_cache_builder"]["sha256"],
            "adapter": snapshot_file(adapter_path),
            "masks": snapshot_file(mask_path),
            "provenance": snapshot_file(provenance_path),
            "target_fasta": snapshot_file(target_path),
            "manifest": snapshot_file(manifest),
            "manifest_identity_sha256": manifest_identity_sha256(manifest_rows),
            "shard_payload_closure": payload_closure,
            "artifacts": artifacts,
            "docking_or_experimental_label_paths_opened": 0,
        }
        atomic_write_json(cache_receipt_path, cache_receipt)
        validate_null_cache_state(
            cache_dir,
            cache_receipt_path,
            null_panel_hash,
            expected_ordered_identity_sha256=ordered_identity_sha,
            adapter_path=adapter_path,
            mask_path=mask_path,
            provenance_path=provenance_path,
            expected_model_sha256=dependencies["esm2_model"]["sha256"],
            expected_builder_sha256=dependencies["esm2_cache_builder"]["sha256"],
            target_path=target_path,
            expected_target_sha256=dependencies["target_fasta"]["sha256"],
            expected_null_rows=null_rows,
        )

    manifest_path = Path(cache_receipt["manifest"]["path"])
    contact_output = contact_dir / "support_v3_null_contact_features.csv"
    contact_audit = contact_dir / "support_v3_null_contact_features.audit.json"
    contact_verification = contact_dir / "support_v3_null_contact.verification.json"
    contact_closure_receipt_path = contact_dir / "support_v3_null_contact_closure.receipt.json"
    if contact_receipt_path.is_file() and not contact_closure_receipt_path.is_file():
        raise MaterializationError("partial_null_contact_without_closure_receipt_fail_closed")
    if contact_closure_receipt_path.is_file():
        contact_extractor = _load_module("support_v3_contact_extractor_verify", CONTACT_EXTRACTOR_PATH)
        verification = contact_extractor.verify_release_receipt(contact_receipt_path)
        if verification.get("row_count") != len(null_rows):
            raise MaterializationError("existing_null_contact_row_count_mismatch")
        contact_closure = json.loads(
            contact_closure_receipt_path.read_text(encoding="utf-8")
        )
        if (
            contact_closure.get("schema_version")
            != "phase2_v4_d_sequence_support_v3_null_contact_closure_receipt_v1"
            or contact_closure.get("status") != "PASS_COMPLETE_LABEL_FREE_CONTACT_CLOSURE"
            or contact_closure.get("null_panel_sha256") != null_panel_hash
            or contact_closure.get("ordered_identity_sha256") != ordered_identity_sha
            or contact_closure.get("model_sha256") != dependencies["esm2_model"]["sha256"]
            or contact_closure.get("contact_extractor_sha256")
            != dependencies["contact_extractor"]["sha256"]
            or contact_closure.get("checkpoint_sha256")
            != {
                str(seed): dependencies[f"checkpoint_seed{seed}"]["sha256"]
                for seed in (43, 53, 67)
            }
            or contact_closure.get("target_fasta_sha256")
            != dependencies["target_fasta"]["sha256"]
            or contact_closure.get("hotspots_sha256")
            != dependencies["hotspots"]["sha256"]
        ):
            raise MaterializationError("existing_null_contact_closure_identity_mismatch")
        current_contact_bindings = {
            "adapter": snapshot_file(adapter_path),
            "masks": snapshot_file(mask_path),
            "provenance": snapshot_file(provenance_path),
            "cache_receipt": snapshot_file(cache_receipt_path),
            "extractor_receipt": snapshot_file(contact_receipt_path),
            "contact_output": snapshot_file(contact_output),
            "contact_verification": snapshot_file(contact_verification),
        }
        if current_contact_bindings != {
            label: contact_closure[label] for label in current_contact_bindings
        }:
            raise MaterializationError("existing_null_contact_current_binding_mismatch")
    else:
        if any(path.exists() for path in (contact_output, contact_audit, contact_verification)):
            raise MaterializationError("partial_null_contact_output_without_receipt_fail_closed")
        contact_extractor = _load_module("support_v3_contact_extractor", CONTACT_EXTRACTOR_PATH)
        report = contact_extractor.run_extraction(
            candidates_path=adapter_path,
            cache_manifest_path=manifest_path,
            mask_path=mask_path,
            target_path=target_path,
            hotspot_path=hotspot_path,
            checkpoint_paths=checkpoints,
            output_path=contact_output,
            audit_path=contact_audit,
            receipt_path=contact_receipt_path,
            verification_path=contact_verification,
            superseded_output_paths=(),
            expected_count=len(null_rows),
            expected_seeds={43, 53, 67},
            target_uniprot_start=39,
            expected_hotspots=23,
            batch_size=32,
            device_name="cuda",
            use_amp=True,
            test_only_allow_unfrozen_input_hashes=True,
        )
        if report.get("status") != "PASS" or report.get("output_row_count") != len(null_rows):
            raise MaterializationError("null_contact_extraction_not_pass")
        contract = report.get("label_free_contract", {})
        if any(
            int(contract.get(field, -1)) != 0
            for field in ("docking_label_inputs_read", "v4d_raw_results_read", "v4d_job_state_read")
        ):
            raise MaterializationError("null_contact_extractor_label_access_nonzero")
        contact_closure = {
            "schema_version": "phase2_v4_d_sequence_support_v3_null_contact_closure_receipt_v1",
            "status": "PASS_COMPLETE_LABEL_FREE_CONTACT_CLOSURE",
            "created_at": utc_now(),
            "null_panel_sha256": null_panel_hash,
            "ordered_identity_sha256": ordered_identity_sha,
            "row_count": len(null_rows),
            "model_sha256": dependencies["esm2_model"]["sha256"],
            "contact_extractor_sha256": dependencies["contact_extractor"]["sha256"],
            "checkpoint_sha256": {
                str(seed): dependencies[f"checkpoint_seed{seed}"]["sha256"]
                for seed in (43, 53, 67)
            },
            "target_fasta_sha256": dependencies["target_fasta"]["sha256"],
            "hotspots_sha256": dependencies["hotspots"]["sha256"],
            "adapter": snapshot_file(adapter_path),
            "masks": snapshot_file(mask_path),
            "provenance": snapshot_file(provenance_path),
            "cache_receipt": snapshot_file(cache_receipt_path),
            "extractor_receipt": snapshot_file(contact_receipt_path),
            "contact_output": snapshot_file(contact_output),
            "contact_verification": snapshot_file(contact_verification),
            "docking_or_experimental_label_paths_opened": 0,
        }
        atomic_write_json(contact_closure_receipt_path, contact_closure)
    receipt = json.loads(contact_receipt_path.read_text(encoding="utf-8"))
    if receipt.get("output_sha256") != sha256_file(contact_output):
        raise MaterializationError("null_contact_output_receipt_mismatch")
    return manifest_path, contact_output, {
        "null_panel_sha256": null_panel_hash,
        "cache_receipt": snapshot_file(cache_receipt_path),
        "contact_receipt": snapshot_file(contact_receipt_path),
        "contact_closure_receipt": snapshot_file(contact_closure_receipt_path),
        "contact_verification": snapshot_file(contact_verification),
    }


def _mask_inventory(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, tuple[int, int]]]]:
    rows, fields = read_csv(path)
    required = {"sequence_hash", "cdr_mask_json", "spans_json", "status"}
    if not required <= set(fields):
        raise MaterializationError("cdr_mask_inventory_schema_mismatch")
    by_sha: dict[str, dict[str, str]] = {}
    spans: dict[str, dict[str, tuple[int, int]]] = {}
    for row in rows:
        digest = row["sequence_hash"]
        if digest in by_sha or row["status"] != "exact_annotation":
            raise MaterializationError(f"cdr_mask_duplicate_or_nonexact:{digest}")
        payload = json.loads(row["spans_json"])
        spans[digest] = {
            name: (int(payload[name][0]), int(payload[name][1]))
            for name in ("cdr1", "cdr2", "cdr3")
        }
        by_sha[digest] = row
    return by_sha, spans


def _load_contact_values(
    contact_csv: Path,
    selected_features: Sequence[str],
    expected_sequence_sha256_by_id: Mapping[str, str],
) -> dict[str, list[float]]:
    rows, fields = read_csv(contact_csv)
    columns = [f"{feature}_seed_mean" for feature in selected_features]
    if not {"candidate_id", "sequence_sha256", *columns} <= set(fields):
        raise MaterializationError("contact_feature_columns_missing")
    output: dict[str, list[float]] = {}
    for row in rows:
        candidate_id = row["candidate_id"]
        if candidate_id in output:
            raise MaterializationError(f"duplicate_contact_candidate:{candidate_id}")
        expected_digest = expected_sequence_sha256_by_id.get(candidate_id)
        if expected_digest is None or row["sequence_sha256"] != expected_digest:
            raise MaterializationError(
                f"contact_candidate_sequence_identity_mismatch:{candidate_id}"
            )
        values = [float(row[column]) for column in columns]
        if any(not math.isfinite(value) for value in values):
            raise MaterializationError(f"nonfinite_contact_feature:{candidate_id}")
        output[candidate_id] = values
    if set(output) != set(expected_sequence_sha256_by_id):
        raise MaterializationError("contact_candidate_id_set_mismatch")
    return output


def _candidate_inventory(
    candidate_path: Path, split_path: Path
) -> tuple[list[dict[str, str]], list[str]]:
    rows, fields = read_csv(candidate_path)
    required = set(CORE.CONSUMED_CANDIDATE_FIELDS)
    if not required <= set(fields):
        raise MaterializationError("candidate_inventory_missing_fields")
    projected = [{field: row[field] for field in sorted(required)} for row in rows]
    split_rows, _ = read_csv(split_path, "\t")
    reference_ids = sorted(
        row["candidate_id"] for row in split_rows if row["model_split"] == "OPEN_TRAIN"
    )
    return projected, reference_ids


def _build_records(
    candidates: Sequence[Mapping[str, str]],
    embeddings: Mapping[str, tuple[Any, Any]],
    scaled_contact: Mapping[str, Any],
) -> list[MaterializedRecord]:
    output: list[MaterializedRecord] = []
    for row in candidates:
        digest = row["sequence_sha256"]
        candidate_id = row["candidate_id"]
        full, cdr = embeddings[digest]
        output.append(
            MaterializedRecord(
                candidate_id=candidate_id,
                sequence_sha256=digest,
                declared_parent=row["parent_framework_cluster"],
                sequence=row["vhh_sequence"],
                full_esm=full,
                cdr_esm=cdr,
                cdr1=row["cdr1_after"],
                cdr2=row["cdr2_after"],
                cdr3=row["cdr3_after"],
                contact=scaled_contact[candidate_id],
            )
        )
    return output


def generate_channel_splices(
    references: Sequence[MaterializedRecord], *, count: int, seed: int
) -> list[tuple[MaterializedRecord, tuple[str, str, str]]]:
    by_parent: dict[str, list[MaterializedRecord]] = defaultdict(list)
    for row in references:
        by_parent[row.declared_parent].append(row)
    parents = sorted(by_parent)
    output: list[tuple[MaterializedRecord, tuple[str, str, str]]] = []
    for index in range(count):
        rng = _rng(seed, "channel_splice", index, 0)
        selected_parents = rng.sample(parents, 3)
        sources = [
            rng.choice(sorted(by_parent[parent], key=lambda row: row.candidate_id))
            for parent in selected_parents
        ]
        full_source, cdr_source, contact_source = sources
        candidate_id = f"NULL_SPLICE_{index:04d}"
        output.append(
            (
                MaterializedRecord(
                    candidate_id=candidate_id,
                    sequence_sha256=sha256_bytes(
                        f"{candidate_id}:{':'.join(row.candidate_id for row in sources)}".encode("utf-8")
                    ),
                    declared_parent=full_source.declared_parent,
                    sequence=full_source.sequence,
                    full_esm=full_source.full_esm,
                    cdr_esm=cdr_source.cdr_esm,
                    cdr1=cdr_source.cdr1,
                    cdr2=cdr_source.cdr2,
                    cdr3=cdr_source.cdr3,
                    contact=contact_source.contact,
                ),
                tuple(row.candidate_id for row in sources),
            )
        )
    return output


def write_channel_splice_manifest(
    splices: Sequence[tuple[MaterializedRecord, tuple[str, str, str]]],
    references: Sequence[MaterializedRecord],
    path: Path,
) -> dict[str, Any]:
    import numpy as np

    by_id = {row.candidate_id: row for row in references}
    rows: list[dict[str, Any]] = []
    for query, source_ids in splices:
        if len(source_ids) != 3 or any(source_id not in by_id for source_id in source_ids):
            raise MaterializationError("channel_splice_source_identity_invalid")
        source_parents = [by_id[source_id].declared_parent for source_id in source_ids]
        if len(set(source_parents)) != 3:
            raise MaterializationError("channel_splice_sources_not_cross_parent")
        rows.append(
            {
                "candidate_id": query.candidate_id,
                "sequence_sha256": query.sequence_sha256,
                "declared_parent": query.declared_parent,
                "full_esm_source_id": source_ids[0],
                "cdr_order_source_id": source_ids[1],
                "contact_source_id": source_ids[2],
                "source_parents": source_parents,
                "full_esm_sha256": sha256_bytes(
                    np.asarray(query.full_esm, dtype=np.float32).tobytes()
                ),
                "cdr_esm_sha256": sha256_bytes(
                    np.asarray(query.cdr_esm, dtype=np.float32).tobytes()
                ),
                "contact_sha256": sha256_bytes(
                    np.asarray(query.contact, dtype=np.float32).tobytes()
                ),
                "cdr_order_sha256": sha256_json(
                    [query.cdr1, query.cdr2, query.cdr3]
                ),
            }
        )
    payload = {
        "schema_version": "phase2_v4_d_sequence_support_v3_channel_splice_manifest_v1",
        "status": "PASS_LABEL_FREE_PRECOMPUTED_CHANNEL_SPLICE_CLOSURE",
        "row_count": len(rows),
        "docking_or_experimental_label_paths_opened": 0,
        "rows": rows,
    }
    payload["payload_sha256"] = sha256_json(payload)
    atomic_write_json(path, payload)
    return payload


def _null_result(
    kind: str,
    labels: Sequence[str],
    lock: Mapping[str, Any],
) -> dict[str, Any]:
    target_label, gate_name = CORE.NULL_GATE_TARGETS[kind]
    observed = sum(label == target_label for label in labels) / len(labels)
    maximum = float(lock["hard_gates"][kind][gate_name])
    return {
        "kind": kind,
        "row_count": len(labels),
        "target_label": target_label,
        "observed_fraction": observed,
        "maximum": maximum,
        "passed": observed <= maximum,
        "label_counts": dict(sorted(Counter(labels).items())),
    }


def format_output_row(
    record: MaterializedRecord,
    decision: DomainResult,
    same_thresholds: Mapping[str, float],
    global_thresholds: Mapping[str, float],
    claim_boundary: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema_version": PUBLICATION_SCHEMA,
        "candidate_id": record.candidate_id,
        "sequence_sha256": record.sequence_sha256,
        "parent_framework_cluster": record.declared_parent,
        "support_domain": decision.label,
        "support_neighbor_candidate_id": decision.neighbor_id,
        "support_neighbor_parent_cluster": decision.neighbor_parent,
        "claim_boundary": claim_boundary,
    }
    for channel in CORE.REQUIRED_CHANNELS:
        row[f"distance_{channel}"] = (
            "" if channel not in decision.distances else format(float(decision.distances[channel]), ".10g")
        )
        row[f"same_parent_threshold_{channel}"] = format(float(same_thresholds[channel]), ".10g")
        row[f"global_threshold_{channel}"] = format(float(global_thresholds[channel]), ".10g")
    return row


def publish_passed_outputs(
    *,
    publish_dir: Path,
    table_rows: Sequence[Mapping[str, Any]],
    audit: dict[str, Any],
    freeze_path: Path,
    lock: Mapping[str, Any],
) -> dict[str, Any]:
    required = set(lock["publication_contract"]["required_outputs"])
    if publish_dir.exists() and any(publish_dir.iterdir()):
        raise MaterializationError("publish_directory_not_empty")
    publish_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=publish_dir.name + ".tmp.", dir=publish_dir.parent)
    )
    table = temporary / "candidate7087_sequence_support_v3.csv"
    audit_path = temporary / "candidate7087_sequence_support_v3.audit.json"
    receipt_path = temporary / "candidate7087_sequence_support_v3.receipt.json"
    atomic_write_csv(table, table_rows, list(table_rows[0]))
    final_table = publish_dir / table.name
    final_audit = publish_dir / audit_path.name
    audit["outputs"] = {
        "support_table": snapshot_for_destination(table, final_table)
    }
    audit["audit_payload_sha256"] = sha256_json(audit)
    atomic_write_json(audit_path, audit)
    receipt = {
        "schema_version": PUBLICATION_RECEIPT_SCHEMA,
        "status": lock["decision_policy"]["pass"],
        "created_at": utc_now(),
        "support_table": snapshot_for_destination(table, final_table),
        "audit": snapshot_for_destination(audit_path, final_audit),
        "implementation_freeze": snapshot_file(freeze_path),
        "output_set": sorted(required),
        "docking_or_experimental_label_paths_opened": 0,
        "claim_boundary": lock["claim_boundary"],
    }
    atomic_write_json(receipt_path, receipt)  # Receipt is always published last.
    verify_exact_regular_file_set(temporary, required)
    for path in (table, audit_path, receipt_path):
        fsync_file_and_parent(path)
    os.replace(temporary, publish_dir)
    verify_exact_regular_file_set(publish_dir, required)
    final_receipt = json.loads(
        (publish_dir / "candidate7087_sequence_support_v3.receipt.json").read_text(
            encoding="utf-8"
        )
    )
    verify_snapshot(final_receipt["support_table"], "final_support_table")
    verify_snapshot(final_receipt["audit"], "final_support_audit")
    verify_snapshot(final_receipt["implementation_freeze"], "final_implementation_freeze")
    fsync_file_and_parent(
        publish_dir / "candidate7087_sequence_support_v3.receipt.json"
    )
    return receipt


def run_production(
    *,
    preregistration: Path,
    freeze_path: Path,
    freeze_receipt: Path,
    runtime_root: Path,
    publish_dir: Path,
) -> dict[str, Any]:
    canonical_paths = {
        "preregistration": (preregistration, DEFAULT_PREREGISTRATION),
        "freeze": (freeze_path, DEFAULT_FREEZE),
        "freeze_receipt": (freeze_receipt, DEFAULT_FREEZE_RECEIPT),
        "runtime_root": (runtime_root, DEFAULT_RUNTIME_ROOT),
        "publish_dir": (publish_dir, DEFAULT_PUBLISH_DIR),
    }
    noncanonical = [
        label
        for label, (observed, expected) in canonical_paths.items()
        if observed.resolve() != expected.resolve()
    ]
    if noncanonical:
        raise MaterializationError(
            "noncanonical_production_path_forbidden:" + ",".join(noncanonical)
        )
    filesystem = require_ext4_runtime(runtime_root)
    publish_lowered = str(publish_dir.resolve()).lower()
    forbidden_publish_tokens = [
        token for token in FORBIDDEN_RUNTIME_PATH_TOKENS if token in publish_lowered
    ]
    if forbidden_publish_tokens:
        raise MaterializationError(
            "label_like_publish_path_forbidden:"
            + ",".join(forbidden_publish_tokens)
        )
    if publish_dir.exists():
        raise MaterializationError("publish_directory_must_not_exist_before_production")
    freeze = verify_implementation_freeze(freeze_path, freeze_receipt, preregistration)
    lock = CORE.load_preregistration(preregistration)
    closure_before = CORE.validate_frozen_inputs(lock, REPO_ROOT)
    if closure_before["docking_or_experimental_label_paths_opened"] != 0:
        raise MaterializationError("production_input_closure_label_access_nonzero")
    inputs = frozen_input_paths(lock)
    candidates, reference_ids = _candidate_inventory(
        inputs["candidate_pool"], inputs["v4_d_split_manifest"]
    )
    candidate_by_id = {row["candidate_id"]: row for row in candidates}
    mask_by_sha, spans_by_sha = _mask_inventory(inputs["cdr_masks"])
    embeddings = load_embedding_summaries(
        inputs["esm2_residue_cache_manifest"],
        mask_by_sha,
        {row["sequence_sha256"] for row in candidates},
    )
    schema = json.loads(inputs["contact_feature_schema"].read_text(encoding="utf-8"))
    selected_features = list(schema["selected_features"])
    contact_receipt = json.loads(
        inputs["contact_feature_release_receipt"].read_text(encoding="utf-8")
    )
    contact_csv = CORE.resolve_recorded_path(REPO_ROOT, contact_receipt["output"])
    contact_values = _load_contact_values(
        contact_csv,
        selected_features,
        {row["candidate_id"]: row["sequence_sha256"] for row in candidates},
    )
    scaled_contact, contact_scaler = robust_scale(contact_values, reference_ids)
    records = _build_records(candidates, embeddings, scaled_contact)
    records_by_id = {row.candidate_id: row for row in records}
    references = [records_by_id[candidate_id] for candidate_id in reference_ids]

    nested = nested_validation(references, lock)
    same_thresholds, global_thresholds, final_calibration = calibrate_thresholds(
        references, float(lock["calibration"]["threshold_quantile"])
    )
    deployment_results = {
        row.candidate_id: classify_record(
            row, references, same_thresholds, global_thresholds
        )
        for row in records
    }
    deployment_rows = [row for row in records if row.candidate_id not in set(reference_ids)]
    deployment_labels = [deployment_results[row.candidate_id].label for row in deployment_rows]

    null_count = int(lock["null_controls"]["replicates_each"])
    null_seed = int(lock["null_controls"]["seed"])
    null_sequences = generate_null_sequences(
        references,
        spans_by_sha,
        replicates_each=null_count,
        seed=null_seed,
        forbidden_sequence_hashes=(row.sequence_sha256 for row in records),
    )
    if len(null_sequences) != EXPECTED_NULL_RECOMPUTE_COUNT:
        raise MaterializationError("production_null_sequence_count_mismatch")
    null_adapter = runtime_root / "null_panel" / "null_sequences_adapter.csv"
    null_masks = runtime_root / "null_panel" / "null_sequences_masks.csv"
    null_provenance = runtime_root / "null_panel" / "null_sequences_provenance.json"
    write_null_adapter(null_sequences, null_adapter, null_masks, null_provenance)
    validate_null_adapter_boundary(null_adapter, len(null_sequences))
    null_manifest, null_contact_csv, null_receipts = materialize_null_features(
        null_rows=null_sequences,
        adapter_path=null_adapter,
        mask_path=null_masks,
        provenance_path=null_provenance,
        runtime_root=runtime_root,
        lock=lock,
        freeze=freeze,
    )
    null_mask_by_sha, _null_spans = _mask_inventory(null_masks)
    null_embeddings = load_embedding_summaries(
        null_manifest,
        null_mask_by_sha,
        {row.sequence_sha256 for row in null_sequences},
    )
    null_contact_values = _load_contact_values(
        null_contact_csv,
        selected_features,
        {row.candidate_id: row.sequence_sha256 for row in null_sequences},
    )
    import numpy as np

    median = np.asarray(contact_scaler["median"], dtype=np.float64)
    iqr = np.asarray(contact_scaler["iqr"], dtype=np.float64)
    null_scaled_contact = {
        candidate_id: ((np.asarray(values, dtype=np.float64) - median) / iqr).astype(np.float32)
        for candidate_id, values in null_contact_values.items()
    }
    null_records: dict[str, MaterializedRecord] = {}
    for row in null_sequences:
        full, cdr = null_embeddings[row.sequence_sha256]
        null_records[row.candidate_id] = MaterializedRecord(
            candidate_id=row.candidate_id,
            sequence_sha256=row.sequence_sha256,
            declared_parent=row.declared_parent,
            sequence=row.sequence,
            full_esm=full,
            cdr_esm=cdr,
            cdr1=row.cdr1,
            cdr2=row.cdr2,
            cdr3=row.cdr3,
            contact=null_scaled_contact[row.candidate_id],
        )

    labels_by_kind: dict[str, list[str]] = defaultdict(list)
    for row in null_sequences:
        query = null_records[row.candidate_id]
        if row.kind == "unseen_parent_chimera":
            decision = classify_record(
                query,
                references,
                same_thresholds,
                global_thresholds,
                excluded_parents=row.source_parents,
            )
        else:
            decision = classify_record(
                query,
                references,
                same_thresholds,
                global_thresholds,
                excluded_ids=row.source_ids,
            )
        labels_by_kind[row.kind].append(decision.label)

    splices = generate_channel_splices(references, count=null_count, seed=null_seed)
    splice_manifest_path = runtime_root / "null_panel" / "channel_splice_manifest.json"
    splice_manifest = write_channel_splice_manifest(
        splices, references, splice_manifest_path
    )
    if splice_manifest["row_count"] != EXPECTED_CHANNEL_SPLICE_COUNT:
        raise MaterializationError("channel_splice_manifest_count_mismatch")
    for query, _source_ids in splices:
        labels_by_kind["channel_splice"].append(
            classify_record(
                query, references, same_thresholds, global_thresholds
            ).label
        )
    null_results = {
        kind: _null_result(kind, labels_by_kind[kind], lock)
        for kind in CORE.NULL_GATE_TARGETS
    }
    gate_bundle = CORE.evaluate_gate_bundle(
        lock,
        nested_in_domain_fraction=nested["in_domain_fraction"],
        nested_parent_fractions=nested["parent_fractions"],
        deployment_labels=deployment_labels,
        null_results=null_results,
    )
    closure_after = CORE.validate_frozen_inputs(lock, REPO_ROOT)
    if closure_after != closure_before:
        raise MaterializationError("frozen_input_closure_changed_during_run")
    verify_implementation_freeze(freeze_path, freeze_receipt, preregistration)
    replay_manifest, replay_contact, replay_receipts = materialize_null_features(
        null_rows=null_sequences,
        adapter_path=null_adapter,
        mask_path=null_masks,
        provenance_path=null_provenance,
        runtime_root=runtime_root,
        lock=lock,
        freeze=freeze,
    )
    if (
        replay_manifest.resolve() != null_manifest.resolve()
        or replay_contact.resolve() != null_contact_csv.resolve()
        or replay_receipts != null_receipts
    ):
        raise MaterializationError("null_artifact_replay_closure_mismatch")

    runtime_audit: dict[str, Any] = {
        "schema_version": RUNTIME_SCHEMA,
        "status": gate_bundle["status"],
        "completed_at": utc_now(),
        "claim_boundary": lock["claim_boundary"],
        "runtime": {
            "path": str(runtime_root.resolve()),
            "filesystem": filesystem,
            "python": sys.executable,
        },
        "implementation_freeze": snapshot_file(freeze_path),
        "input_closure": closure_after,
        "selected_contact_features": selected_features,
        "contact_scaler": contact_scaler,
        "calibration": final_calibration,
        "nested_validation": nested,
        "deployment": {
            "denominator": len(deployment_labels),
            "label_counts": dict(sorted(Counter(deployment_labels).items())),
        },
        "null_controls": null_results,
        "null_artifacts": {
            "adapter": snapshot_file(null_adapter),
            "masks": snapshot_file(null_masks),
            "provenance": snapshot_file(null_provenance),
            "channel_splice_manifest": snapshot_file(splice_manifest_path),
            **null_receipts,
        },
        "gates": gate_bundle,
        "label_access": {
            "docking_or_experimental_label_paths_opened": 0,
            "v4_f_label_paths_opened": 0,
        },
        "publication_attempted": bool(gate_bundle["all_gates_passed"]),
    }
    runtime_audit_path = runtime_root / "support_v3_runtime_audit.json"
    atomic_write_json(runtime_audit_path, runtime_audit)
    if not gate_bundle["all_gates_passed"]:
        failure = {
            "status": lock["decision_policy"]["fail"],
            "runtime_audit": snapshot_file(runtime_audit_path),
            "production_support_table_published": False,
            "publish_dir_exists": publish_dir.exists(),
            "failure_response": lock["decision_policy"]["failure_response"],
        }
        atomic_write_json(runtime_root / "FAIL_CLOSED_DECISION.json", failure)
        return failure

    table_rows = [
        format_output_row(
            row,
            deployment_results[row.candidate_id],
            same_thresholds,
            global_thresholds,
            lock["claim_boundary"],
        )
        for row in records
    ]
    publication_audit = dict(runtime_audit)
    publication_audit["production_support_table_published"] = True
    receipt = publish_passed_outputs(
        publish_dir=publish_dir,
        table_rows=table_rows,
        audit=publication_audit,
        freeze_path=freeze_path,
        lock=lock,
    )
    return {
        "status": lock["decision_policy"]["pass"],
        "production_support_table_published": True,
        "publish_dir": str(publish_dir.resolve()),
        "receipt_sha256": sha256_json(receipt),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze", help="Freeze implementation only after tests pass")
    freeze.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    freeze.add_argument("--test-log", type=Path, default=DEFAULT_TEST_LOG)
    freeze.add_argument("--output", type=Path, default=DEFAULT_FREEZE)
    freeze.add_argument("--receipt-output", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    freeze.add_argument(
        "--supersession-record", type=Path, default=DEFAULT_SUPERSESSION_RECORD
    )

    verify = subparsers.add_parser("verify-freeze")
    verify.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    verify.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    verify.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)

    production = subparsers.add_parser("production")
    production.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    production.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    production.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    production.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    production.add_argument("--publish-dir", type=Path, default=DEFAULT_PUBLISH_DIR)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "freeze":
        result = create_implementation_freeze(
            preregistration=args.preregistration,
            test_log=args.test_log,
            output=args.output,
            receipt_output=args.receipt_output,
            supersession_record=args.supersession_record,
        )
    elif args.command == "verify-freeze":
        result = verify_implementation_freeze(
            args.freeze, args.freeze_receipt, args.preregistration
        )
    else:
        result = run_production(
            preregistration=args.preregistration,
            freeze_path=args.freeze,
            freeze_receipt=args.freeze_receipt,
            runtime_root=args.runtime_root,
            publish_dir=args.publish_dir,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not str(result.get("status", "")).startswith("FAIL") else 2


if __name__ == "__main__":
    raise SystemExit(main())
