#!/usr/bin/env python3
"""Validate and content-address the V4-D-DEV1 development-only open258 bundle.

The candidate implementation freeze permits offline archive verification only.
Remote access is fail-closed until a separate launch-authorized freeze and launch
receipt are created after independent review.
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
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Mapping, Sequence


SCHEMA_VERSION = "phase2_v4_d_dev1_open258_delivery_v1"
AUDIT_STATUS = "RELEASED_DEV_ONLY_FROM_FAILED_V4D_EVALUATOR_TEST32_SEALED"
RELEASE_NAME = "OPEN_TRAIN_226_PLUS_OPEN_DEVELOPMENT_32_DEV_ONLY"
REMOTE_READY_STATUS = "DEV1_RELEASE_READY_TEST32_SEALED"
CLAIM_BOUNDARY = (
    "Post-hoc development-only computational dual-docking geometry transport; "
    "not a V4-D pass, formal test, Docking Gold, binding, affinity, competition, "
    "experimental blocking, or final submission authority."
)
CANONICAL_EXP_DIR = Path("/mnt/d/work/抗体/data/experiments/phase2_5080_v1")
CANONICAL_SCRIPT = CANONICAL_EXP_DIR / "src/deliver_phase2_v4_d_dev1_open258_from_node23.py"
CANONICAL_PREREG = CANONICAL_EXP_DIR / "audits/phase2_v4_d_dev1_open258_preregistration.json"
CANONICAL_SPLIT_MANIFEST = CANONICAL_EXP_DIR / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv"
CANONICAL_GENERIC_PRIOR = CANONICAL_EXP_DIR / "prepared/pvrig_v4_d_dev1_open258_v1/generic_prior_v1/v4d_dev1_fullqc290_label_free_generic_prior_v1.csv"
CANONICAL_FREEZE_CANDIDATE = CANONICAL_EXP_DIR / "audits/phase2_v4_d_dev1_open258_implementation_freeze_candidate.json"
CANONICAL_LAUNCH_FREEZE = CANONICAL_EXP_DIR / "audits/phase2_v4_d_dev1_open258_launch_authorized_freeze.json"
CANONICAL_DELIVERY_ROOT = CANONICAL_EXP_DIR / "prepared/pvrig_v4_d_dev1_open258_v1/delivery_dev1"
CANONICAL_SSH = Path("/mnt/c/Windows/System32/OpenSSH/ssh.exe")
REMOTE_HOST = "node23"
REMOTE_ROOT = Path("/data/qlyu/projects/pvrig_v4_d_dev1_open258_v1_20260717")
REMOTE_STATUS = "status/dev1_release_status.json"
REMOTE_ARCHIVE = "release/v4d_dev1_open258_delivery_v1.tar.gz"
REMOTE_ARCHIVE_SHA = REMOTE_ARCHIVE + ".sha256"
EXPECTED_PREREG_SHA256 = "ee2c1076b0fd58b5bcb991f7646321c6fd03204746ff926f2d93940fec5ffe55"
EXPECTED_EVALUATOR_SHA256 = "289542c58cfe72c380143a910b3adb75ba4e12f65899f71907a044314bedb674"
EXPECTED_SPLIT_MANIFEST_SHA256 = "c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd"
EXPECTED_JOB_MANIFEST_SHA256 = "96fec07a5535615f50bff40ac48bb323a94213e06a7b12726ae5b4b2d1161737"
EXPECTED_JOB_RESULTS_SHA256 = "30c4227e15f6b049a9d9e9241ca34df30d38b247d14081b4ce7d3387fa2f3f25"
EXPECTED_POSE_SCORES_SHA256 = "7a2737160051c8fca8836b4086507e8f70d83cd692f87ffc17eaff8279c32681"
EXPECTED_PROTOCOL_CORE_LOCK_FILE_SHA256 = "767117dc2c506cfdfc83fce8e12931514d268941348d69a9abbda5a6500bdd24"
EXPECTED_PROTOCOL_LOCK_FILE_SHA256 = "56ef539cb54a1aba8e665ec5d62b3653088e2289e371d8fa5bbadbc725c1d574"
EXPECTED_STABILITY_SPEC_FILE_SHA256 = "fb01cdaa5939f2846b16e4e02a09903417cd6cea04d42350c4ed57f9ae7eb774"
EXPECTED_EVALUATOR_PROTOCOL_CORE_PAYLOAD_SHA256 = "91d75291ff832c1e94cbc0bf6f1cdd75de6a8bb74611230cdcd1716466f37cb7"
EXPECTED_EVALUATOR_PROTOCOL_LOCK_PAYLOAD_SHA256 = "a24eaf37730bc569067d64cdc1a43a763b70878d13d50e804bf3000ce43f5e84"
EXPECTED_V1_FORMULA_HELPER_SHA256 = "8adb3c4e1de37bbaaf469dfb967176d2c49d40f353e21a3f028baa20ea8e4145"
EXPECTED_GENERIC_PRIOR_SHA256 = "21b4c6a38056d6777de5b5efbfcd5887b45098c637cab61489072d1e6e7783cd"
EXPECTED_OPEN_COUNTS = {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32}
EXPECTED_OPEN_ROWS = 258
SEALED_SPLIT = "PROSPECTIVE_COMPUTATIONAL_TEST"
EXPECTED_SEALED_ROWS = 32
SOURCE_FAILED_GATE = "candidate_threshold_sensitivity"
PRIMARY_TARGET = "R_dual_min"
OUTPUT_BASENAME = "v4d_dev1_open258_continuous_geometry.tsv"
AUDIT_BASENAME = OUTPUT_BASENAME + ".audit.json"
SOURCE_RECEIPT_BASENAME = "v4d_dev1_source_failure_receipt.json"
RELEASE_RECEIPT_BASENAME = "v4d_dev1_release_receipt.json"
CHECKSUM_BASENAME = "SHA256SUMS"
ARCHIVE_BASENAME = "v4d_dev1_open258_delivery_v1.tar.gz"
ARCHIVE_SHA_BASENAME = ARCHIVE_BASENAME + ".sha256"
EXPECTED_ARCHIVE_MEMBERS = frozenset(
    {
        f"outputs/{OUTPUT_BASENAME}",
        f"outputs/{AUDIT_BASENAME}",
        f"outputs/{SOURCE_RECEIPT_BASENAME}",
        f"outputs/{RELEASE_RECEIPT_BASENAME}",
        f"outputs/{CHECKSUM_BASENAME}",
    }
)
EXPECTED_CHECKSUM_MEMBERS = frozenset(
    EXPECTED_ARCHIVE_MEMBERS - {f"outputs/{CHECKSUM_BASENAME}"}
)
REQUIRED_TRAINER_FIELDS = frozenset(
    {
        "candidate_id",
        "model_split",
        "parent_framework_cluster",
        "sequence_sha256",
        "sequence",
        "design_method",
        "design_mode",
        "target_patch_id",
        "cdr1",
        "cdr2",
        "cdr3",
        "generic_binding_prior",
        PRIMARY_TARGET,
    }
)
EXPECTED_GENERIC_PRIOR_FIELDS = (
    "candidate_id",
    "sequence_sha256",
    "generic_binding_prior",
    "model_uncertainty",
    "model_disagreement",
    "generic_binding_prior_seed_43",
    "generic_binding_prior_seed_53",
    "generic_binding_prior_seed_67",
    "generic_binding_model",
    "generic_binding_train_summary_sha256",
    "target_sequence_sha256",
    "model_claim_boundary",
)
FORBIDDEN_FORMAL_STRINGS = frozenset(
    {
        "PASS_OPEN258_TEACHER_READY_TEST32_SEALED",
        "PASS_V4_D_SURROGATE_V3_COMPLETE_TEST32_SEALED",
        "COMPLETE_V4_D_SURROGATE_TRAINING_TEST32_SEALED",
        "COMPLETE_V4_F_96_PREDICTIONS_FROZEN",
    }
)
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
REMOTE_WAIT_STATES = frozenset({"WAITING_DEV1_BUILD", "MISSING"})
REMOTE_FAILURE_STATES = frozenset({"FAILED", "BLOCKED"})


class DeliveryError(RuntimeError):
    """A fail-closed delivery error."""


class DeliveryWaiting(RuntimeError):
    """The remote DEV1 bundle is not ready."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DeliveryError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise DeliveryError(f"missing_file:{label}:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"not_regular_or_is_symlink:{label}:{path}")


def strict_json_load_bytes(raw: bytes, label: str) -> Any:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in output, f"duplicate_json_key:{label}:{key}")
            output[key] = value
        return output

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
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


def safe_relative_member(name: str) -> None:
    path = PurePosixPath(name)
    require(not path.is_absolute(), f"absolute_archive_member:{name}")
    require(name == path.as_posix(), f"noncanonical_archive_member:{name}")
    require(".." not in path.parts and "." not in path.parts, f"archive_path_traversal:{name}")


def load_freeze(path: Path, *, launch_authorized: bool) -> dict[str, Any]:
    payload = strict_json_load(path, "implementation_freeze")
    require(isinstance(payload, Mapping), "implementation_freeze_not_object")
    expected_status = (
        "FROZEN_FOR_DEV1_REMOTE_EXECUTION"
        if launch_authorized
        else "CANDIDATE_FREEZE_BEFORE_REMOTE_OR_LABEL_ACCESS"
    )
    require(payload.get("status") == expected_status, f"implementation_freeze_status_not_{expected_status}")
    require(payload.get("test32_raw_job_files_opened") == 0, "freeze_test32_raw_open_nonzero")
    require(payload.get("remote_execution_started") is False, "freeze_remote_execution_started")
    require(
        payload.get("remote_execution_authorized") is launch_authorized,
        "freeze_remote_execution_authorization_mismatch",
    )
    require(payload.get("formal_v4_f_unlock_eligible") is False, "freeze_formal_v4f_unlock_true")
    files = payload.get("files")
    require(isinstance(files, Mapping), "implementation_freeze_files_missing")
    return dict(payload)


def freeze_file_hash(freeze: Mapping[str, Any], key: str) -> str:
    files = freeze.get("files") or {}
    entry = files.get(key) if isinstance(files, Mapping) else None
    require(isinstance(entry, Mapping), f"freeze_file_missing:{key}")
    value = entry.get("sha256")
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None, f"freeze_file_hash_invalid:{key}")
    return value


def parse_sha256sums(outputs: Path) -> dict[str, str]:
    checksum = outputs / CHECKSUM_BASENAME
    require_regular_file(checksum, "checksums")
    result: dict[str, str] = {}
    for line in checksum.read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (outputs/[A-Za-z0-9_.-]+)", line)
        require(match is not None, f"invalid_checksum_line:{line}")
        digest, name = match.groups()
        require(name not in result, f"duplicate_checksum_member:{name}")
        result[name] = digest
    require(set(result) == set(EXPECTED_CHECKSUM_MEMBERS), "checksum_member_set_mismatch")
    for name, expected in result.items():
        path = outputs.parent / name
        require_regular_file(path, name)
        require(sha256_file(path) == expected, f"payload_sha256_mismatch:{name}")
    return result


def canonical_id_hash(values: Sequence[str]) -> str:
    raw = json.dumps(sorted(values), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_frozen_teacher_reference(
    split_manifest: Path,
    generic_prior: Path,
    *,
    expected_split_sha256: str,
    expected_generic_prior_sha256: str,
) -> tuple[dict[str, dict[str, str]], set[str]]:
    require_regular_file(split_manifest, "frozen_split_manifest")
    require_regular_file(generic_prior, "frozen_generic_prior")
    require(sha256_file(split_manifest) == expected_split_sha256, "frozen_split_manifest_sha256_mismatch")
    require(sha256_file(generic_prior) == expected_generic_prior_sha256, "frozen_generic_prior_sha256_mismatch")
    with split_manifest.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(
            {"candidate_id", "model_split", "sequence_sha256", "sequence"} <= set(reader.fieldnames or ()),
            "frozen_split_header_invalid",
        )
        split_rows = list(reader)
    require(len(split_rows) == EXPECTED_OPEN_ROWS + EXPECTED_SEALED_ROWS, "frozen_split_row_count_invalid")
    split_by_id: dict[str, dict[str, str]] = {}
    split_counts = {name: 0 for name in (*EXPECTED_OPEN_COUNTS, SEALED_SPLIT)}
    for row in split_rows:
        candidate_id = row.get("candidate_id", "")
        require(candidate_id and candidate_id not in split_by_id, f"frozen_split_candidate_invalid:{candidate_id}")
        split = row.get("model_split", "")
        require(split in split_counts, f"frozen_split_role_invalid:{candidate_id}:{split}")
        split_counts[split] += 1
        require(re.fullmatch(r"[0-9a-f]{64}", row.get("sequence_sha256", "")) is not None, f"frozen_split_sequence_sha_invalid:{candidate_id}")
        require(bool(row.get("sequence", "")), f"frozen_split_sequence_empty:{candidate_id}")
        split_by_id[candidate_id] = dict(row)
    require(
        split_counts == {**EXPECTED_OPEN_COUNTS, SEALED_SPLIT: EXPECTED_SEALED_ROWS},
        f"frozen_split_counts_invalid:{split_counts}",
    )
    with generic_prior.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        require(tuple(reader.fieldnames or ()) == EXPECTED_GENERIC_PRIOR_FIELDS, "frozen_generic_prior_header_invalid")
        prior_rows = list(reader)
    require(len(prior_rows) == len(split_rows), "frozen_generic_prior_row_count_invalid")
    prior_by_id: dict[str, dict[str, str]] = {}
    for row in prior_rows:
        candidate_id = row.get("candidate_id", "")
        require(candidate_id and candidate_id not in prior_by_id, f"frozen_generic_prior_candidate_invalid:{candidate_id}")
        require(candidate_id in split_by_id, f"frozen_generic_prior_unknown_candidate:{candidate_id}")
        require(row.get("sequence_sha256") == split_by_id[candidate_id]["sequence_sha256"], f"frozen_generic_prior_sequence_sha_mismatch:{candidate_id}")
        try:
            prior = float(row.get("generic_binding_prior", ""))
        except (TypeError, ValueError) as exc:
            raise DeliveryError(f"frozen_generic_prior_numeric_invalid:{candidate_id}") from exc
        require(math.isfinite(prior) and 0.0 <= prior <= 1.0, f"frozen_generic_prior_out_of_range:{candidate_id}")
        prior_by_id[candidate_id] = dict(row)
    require(set(prior_by_id) == set(split_by_id), "frozen_generic_prior_candidate_closure_failed")
    open_reference: dict[str, dict[str, str]] = {}
    sealed_ids: set[str] = set()
    for candidate_id, split_row in split_by_id.items():
        if split_row["model_split"] == SEALED_SPLIT:
            sealed_ids.add(candidate_id)
            continue
        open_reference[candidate_id] = {
            "model_split": split_row["model_split"],
            "sequence_sha256": split_row["sequence_sha256"],
            "sequence": split_row["sequence"],
            "generic_binding_prior": prior_by_id[candidate_id]["generic_binding_prior"],
        }
    require(len(open_reference) == EXPECTED_OPEN_ROWS and len(sealed_ids) == EXPECTED_SEALED_ROWS, "frozen_reference_closure_failed")
    return open_reference, sealed_ids


def validate_teacher(
    path: Path,
    expected_open: Mapping[str, Mapping[str, str]],
) -> tuple[list[str], dict[str, int]]:
    require_regular_file(path, "teacher")
    counts = {split: 0 for split in EXPECTED_OPEN_COUNTS}
    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        header = list(reader.fieldnames or [])
        require(header and len(header) == len(set(header)), "teacher_header_invalid")
        require(REQUIRED_TRAINER_FIELDS <= set(header), "teacher_required_header_missing")
        rows = 0
        for row in reader:
            rows += 1
            candidate_id = row.get("candidate_id", "")
            require(candidate_id and candidate_id not in seen, f"teacher_candidate_id_invalid:{candidate_id}")
            seen.add(candidate_id)
            require(candidate_id in expected_open, f"teacher_candidate_not_in_frozen_open_split:{candidate_id}")
            expected = expected_open[candidate_id]
            split = row.get("model_split", "")
            require(split in counts, f"teacher_forbidden_split:{split}")
            counts[split] += 1
            require(split != SEALED_SPLIT, "teacher_contains_sealed_split")
            require(split == expected["model_split"], f"teacher_model_split_mismatch:{candidate_id}")
            require(row.get("sequence_sha256") == expected["sequence_sha256"], f"teacher_sequence_sha_mismatch:{candidate_id}")
            require(row.get("sequence") == expected["sequence"], f"teacher_sequence_mismatch:{candidate_id}")
            require(row.get("source_evaluator_status") == "FAIL", "teacher_source_status_not_FAIL")
            require(row.get("source_failed_gate") == SOURCE_FAILED_GATE, "teacher_source_failed_gate_mismatch")
            require(row.get("formal_v4_f_unlock_eligible", "").lower() == "false", "teacher_formal_v4f_unlock_true")
            try:
                target = float(row.get(PRIMARY_TARGET, ""))
                prior = float(row.get("generic_binding_prior", ""))
            except (TypeError, ValueError) as exc:
                raise DeliveryError(f"teacher_numeric_invalid:{candidate_id}") from exc
            require(math.isfinite(target), f"teacher_target_nonfinite:{candidate_id}")
            require(math.isfinite(prior) and 0.0 <= prior <= 1.0, f"teacher_prior_invalid:{candidate_id}")
            require(prior == round(float(expected["generic_binding_prior"]), 9), f"teacher_generic_prior_mismatch:{candidate_id}")
    require(rows == EXPECTED_OPEN_ROWS, f"teacher_row_count_invalid:{rows}")
    require(counts == EXPECTED_OPEN_COUNTS, f"teacher_split_counts_invalid:{counts}")
    require(seen == set(expected_open), "teacher_frozen_open_candidate_closure_failed")
    return header, counts


def require_zero_sealed_boundary(payload: Mapping[str, Any], label: str) -> None:
    boundary = payload.get("sealed_data_boundary")
    require(isinstance(boundary, Mapping), f"{label}_sealed_boundary_missing")
    for field in (
        "raw_test32_job_files_opened",
        "test32_metric_values_read",
        "test32_label_rows_emitted",
    ):
        require(boundary.get(field) == 0, f"{label}_{field}_nonzero")


def validate_release_outputs(
    root: Path,
    freeze: Mapping[str, Any],
    *,
    split_manifest: Path = CANONICAL_SPLIT_MANIFEST,
    generic_prior: Path = CANONICAL_GENERIC_PRIOR,
    expected_split_sha256: str = EXPECTED_SPLIT_MANIFEST_SHA256,
    expected_generic_prior_sha256: str = EXPECTED_GENERIC_PRIOR_SHA256,
) -> dict[str, Any]:
    outputs = root / "outputs"
    require(outputs.is_dir() and not outputs.is_symlink(), "outputs_directory_invalid")
    actual = {path.name for path in outputs.iterdir()}
    expected = {PurePosixPath(name).name for name in EXPECTED_ARCHIVE_MEMBERS}
    require(actual == expected, f"outputs_member_set_mismatch:{sorted(actual)}")
    parse_sha256sums(outputs)
    expected_open, sealed_ids = load_frozen_teacher_reference(
        split_manifest,
        generic_prior,
        expected_split_sha256=expected_split_sha256,
        expected_generic_prior_sha256=expected_generic_prior_sha256,
    )
    teacher = outputs / OUTPUT_BASENAME
    header, counts = validate_teacher(teacher, expected_open)
    audit_path = outputs / AUDIT_BASENAME
    source_path = outputs / SOURCE_RECEIPT_BASENAME
    receipt_path = outputs / RELEASE_RECEIPT_BASENAME
    audit = strict_json_load(audit_path, "audit")
    source = strict_json_load(source_path, "source_failure_receipt")
    receipt = strict_json_load(receipt_path, "release_receipt")
    for label, payload in (("audit", audit), ("source", source), ("receipt", receipt)):
        require(isinstance(payload, Mapping), f"{label}_not_object")
        raw = json.dumps(payload, sort_keys=True)
        for forbidden in FORBIDDEN_FORMAL_STRINGS:
            require(forbidden not in raw, f"{label}_contains_forbidden_formal_status")
    require(audit.get("status") == AUDIT_STATUS, "audit_status_invalid")
    require(audit.get("release") == RELEASE_NAME, "audit_release_invalid")
    require(audit.get("formal_v4_f_unlock_eligible") is False, "audit_formal_v4f_unlock_true")
    non_authority = audit.get("non_authority") or {}
    require(
        non_authority.get("formal_completion_or_unlock_receipt_created") is False,
        "audit_formal_completion_receipt_created",
    )
    require(
        non_authority.get("formal_v4_f_unlock_eligible") is False,
        "audit_non_authority_v4f_unlock_true",
    )
    require(
        non_authority.get("final_submission_authority") is False,
        "audit_final_submission_authority_true",
    )
    require_zero_sealed_boundary(audit, "audit")
    source_eval = audit.get("source_evaluator") or {}
    require(source_eval.get("status") == "FAIL", "audit_source_status_not_FAIL")
    require(source_eval.get("unlockable") is False, "audit_source_unlockable_true")
    require(source_eval.get("failed_gates") == [SOURCE_FAILED_GATE], "audit_source_failed_gate_mismatch")
    require(source_eval.get("sha256") == EXPECTED_EVALUATOR_SHA256, "audit_source_evaluator_hash_mismatch")
    audit_input = audit.get("inputs") or {}
    expected_inputs = {
        "split_manifest_sha256": expected_split_sha256,
        "job_manifest_sha256": EXPECTED_JOB_MANIFEST_SHA256,
        "job_results_sha256_binding_only": EXPECTED_JOB_RESULTS_SHA256,
        "pose_scores_sha256_binding_only": EXPECTED_POSE_SCORES_SHA256,
        "source_evaluator_sha256": EXPECTED_EVALUATOR_SHA256,
        "protocol_core_lock_file_sha256": EXPECTED_PROTOCOL_CORE_LOCK_FILE_SHA256,
        "protocol_lock_file_sha256": EXPECTED_PROTOCOL_LOCK_FILE_SHA256,
        "stability_spec_file_sha256": EXPECTED_STABILITY_SPEC_FILE_SHA256,
        "evaluator_protocol_core_payload_sha256": EXPECTED_EVALUATOR_PROTOCOL_CORE_PAYLOAD_SHA256,
        "evaluator_protocol_lock_payload_sha256": EXPECTED_EVALUATOR_PROTOCOL_LOCK_PAYLOAD_SHA256,
        "v1_formula_helper_sha256": EXPECTED_V1_FORMULA_HELPER_SHA256,
        "generic_prior_sha256": expected_generic_prior_sha256,
        "open_candidate_id_sha256": canonical_id_hash(list(expected_open)),
        "sealed_forbidden_candidate_id_sha256": canonical_id_hash(list(sealed_ids)),
    }
    for field, expected_value in expected_inputs.items():
        require(audit_input.get(field) == expected_value, f"audit_input_hash_mismatch:{field}")
    for field in (
        "raw_test32_job_files_opened",
        "test32_metric_values_read",
        "test32_label_rows_emitted",
        "full_aggregate_value_rows_parsed",
    ):
        require(audit_input.get(field) == 0, f"audit_input_{field}_nonzero")
    output = audit.get("output") or {}
    require(output.get("row_count") == EXPECTED_OPEN_ROWS, "audit_output_row_count_invalid")
    require(output.get("split_counts") == EXPECTED_OPEN_COUNTS, "audit_output_split_counts_invalid")
    require(output.get("exact_header") == header, "audit_output_header_mismatch")
    require(output.get("sha256") == sha256_file(teacher), "audit_output_hash_mismatch")
    require(source.get("status") == "SOURCE_EVALUATOR_FAILED_DEV_USE_ONLY", "source_receipt_status_invalid")
    require(source.get("formal_v4_f_unlock_eligible") is False, "source_receipt_formal_v4f_unlock_true")
    source_meta = source.get("source_evaluator") or {}
    require(source_meta.get("status") == "FAIL" and source_meta.get("unlockable") is False, "source_receipt_evaluator_state_invalid")
    require(source_meta.get("failed_gates") == [SOURCE_FAILED_GATE], "source_receipt_failed_gate_invalid")
    require(source_meta.get("sha256") == EXPECTED_EVALUATOR_SHA256, "source_receipt_evaluator_hash_invalid")
    require(receipt.get("status") == REMOTE_READY_STATUS, "release_receipt_status_invalid")
    require(receipt.get("audit_status") == AUDIT_STATUS, "release_receipt_audit_status_invalid")
    require(receipt.get("release") == RELEASE_NAME, "release_receipt_release_invalid")
    require(receipt.get("development_only") is True, "release_receipt_not_development_only")
    require(receipt.get("formal_v4_f_unlock_eligible") is False, "release_receipt_formal_v4f_unlock_true")
    require_zero_sealed_boundary(receipt, "receipt")
    require(receipt.get("row_count") == EXPECTED_OPEN_ROWS, "release_receipt_row_count_invalid")
    require(receipt.get("split_counts") == counts, "release_receipt_split_counts_invalid")
    require(receipt.get("source_evaluator_status") == "FAIL", "release_receipt_source_status_invalid")
    require(receipt.get("source_evaluator_unlockable") is False, "release_receipt_source_unlockable_true")
    require(receipt.get("source_failed_gates") == [SOURCE_FAILED_GATE], "release_receipt_failed_gate_invalid")
    require(receipt.get("teacher_sha256") == sha256_file(teacher), "release_receipt_teacher_hash_mismatch")
    require(receipt.get("teacher_audit_sha256") == sha256_file(audit_path), "release_receipt_audit_hash_mismatch")
    require(receipt.get("source_failure_receipt_sha256") == sha256_file(source_path), "release_receipt_source_hash_mismatch")
    require(receipt.get("preregistration_sha256") == EXPECTED_PREREG_SHA256, "release_receipt_prereg_hash_mismatch")
    require(receipt.get("builder_sha256") == freeze_file_hash(freeze, "builder"), "release_receipt_builder_hash_mismatch")
    return {
        "status": "VALIDATED_DEV1_BUNDLE_TEST32_SEALED",
        "teacher_sha256": sha256_file(teacher),
        "teacher_audit_sha256": sha256_file(audit_path),
        "release_receipt_sha256": sha256_file(receipt_path),
        "row_count": EXPECTED_OPEN_ROWS,
        "split_counts": counts,
        "test32_raw_open": 0,
        "formal_v4_f_unlock_eligible": False,
    }


def extract_validated_archive(archive: Path, destination: Path) -> None:
    require_regular_file(archive, "archive")
    require(archive.stat().st_size <= MAX_ARCHIVE_BYTES, "archive_too_large")
    require(not destination.exists(), "archive_destination_exists")
    destination.mkdir(parents=True)
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            names = [member.name for member in members]
            require(len(names) == len(set(names)), "duplicate_archive_member")
            require(set(names) == set(EXPECTED_ARCHIVE_MEMBERS), "archive_member_set_mismatch")
            total = 0
            for member in members:
                safe_relative_member(member.name)
                require(member.isfile(), f"archive_member_not_regular:{member.name}")
                require(0 <= member.size <= MAX_MEMBER_BYTES, f"archive_member_size_invalid:{member.name}")
                total += member.size
            require(total <= MAX_UNCOMPRESSED_BYTES, "archive_uncompressed_size_too_large")
            for member in members:
                source: BinaryIO | None = bundle.extractfile(member)
                require(source is not None, f"archive_member_unreadable:{member.name}")
                target = destination / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                with source, target.open("xb") as handle:
                    shutil.copyfileobj(source, handle, length=1024 * 1024)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def publish_content_addressed(
    delivery_root: Path,
    extracted: Path,
    archive_sha256: str,
    validation: Mapping[str, Any],
) -> Path:
    require(re.fullmatch(r"[0-9a-f]{64}", archive_sha256) is not None, "archive_sha_invalid")
    by_sha = delivery_root / "by_sha256"
    by_sha.mkdir(parents=True, exist_ok=True)
    destination = by_sha / archive_sha256
    current = delivery_root / "current_dev1"
    target = f"by_sha256/{archive_sha256}"
    if current.is_symlink():
        require(os.readlink(current) == target, "different_existing_current_dev1_refused")
    elif current.exists():
        raise DeliveryError("current_dev1_exists_not_symlink")
    if destination.exists():
        require(destination.is_dir() and not destination.is_symlink(), "existing_release_invalid")
        require(
            validate_release_outputs(
                destination,
                validation["freeze"],
                split_manifest=validation.get("split_manifest", CANONICAL_SPLIT_MANIFEST),
                generic_prior=validation.get("generic_prior", CANONICAL_GENERIC_PRIOR),
                expected_split_sha256=validation.get("expected_split_sha256", EXPECTED_SPLIT_MANIFEST_SHA256),
                expected_generic_prior_sha256=validation.get("expected_generic_prior_sha256", EXPECTED_GENERIC_PRIOR_SHA256),
            )
            == validation["bundle"],
            "existing_release_differs",
        )
        shutil.rmtree(extracted)
    else:
        os.replace(extracted, destination)
    if not current.is_symlink():
        temporary = delivery_root / f".current_dev1.{os.getpid()}"
        os.symlink(target, temporary)
        os.replace(temporary, current)
    return destination


@dataclass(frozen=True)
class Config:
    delivery_root: Path
    ssh_exe: Path
    remote_host: str
    remote_root: Path
    poll_seconds: float
    production: bool
    freeze_path: Path


class RemoteClient:
    def __init__(self, ssh_exe: Path, host: str) -> None:
        self.ssh_exe = ssh_exe
        self.host = host

    def _argv(self, command: str) -> list[str]:
        return [os.fspath(self.ssh_exe), "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", self.host, command]

    def read_file(self, remote_path: Path, *, max_bytes: int) -> bytes:
        process = subprocess.run(
            self._argv(f"test -f '{remote_path}' && test ! -L '{remote_path}' && cat -- '{remote_path}'"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        require(process.returncode == 0, f"remote_read_failed:{remote_path}")
        require(len(process.stdout) <= max_bytes, f"remote_file_too_large:{remote_path}")
        return process.stdout

    def stream_file(self, remote_path: Path, destination: Path, *, max_bytes: int) -> int:
        process = subprocess.Popen(
            self._argv(f"test -f '{remote_path}' && test ! -L '{remote_path}' && cat -- '{remote_path}'"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        require(process.stdout is not None, "remote_stream_stdout_missing")
        total = 0
        with destination.open("xb") as handle:
            while True:
                block = process.stdout.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > max_bytes:
                    process.kill()
                    raise DeliveryError("remote_archive_too_large")
                handle.write(block)
        stderr = process.stderr.read() if process.stderr is not None else b""
        rc = process.wait()
        require(rc == 0, f"remote_stream_failed:{remote_path}:{stderr[:200]!r}")
        return total


def parse_remote_archive_checksum(raw: bytes) -> str:
    try:
        line = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise DeliveryError("remote_archive_checksum_not_ascii") from exc
    match = re.fullmatch(rf"([0-9a-f]{{64}})  {re.escape(ARCHIVE_BASENAME)}", line)
    require(match is not None, "remote_archive_checksum_invalid")
    return match.group(1)


def one_remote_attempt(
    config: Config,
    remote: Any,
    freeze: Mapping[str, Any],
    *,
    split_manifest: Path = CANONICAL_SPLIT_MANIFEST,
    generic_prior: Path = CANONICAL_GENERIC_PRIOR,
    expected_split_sha256: str = EXPECTED_SPLIT_MANIFEST_SHA256,
    expected_generic_prior_sha256: str = EXPECTED_GENERIC_PRIOR_SHA256,
) -> str:
    status_raw = remote.read_file(config.remote_root / REMOTE_STATUS, max_bytes=64 * 1024)
    status = strict_json_load_bytes(status_raw, "remote_status")
    state = status.get("status", "MISSING") if isinstance(status, Mapping) else "MISSING"
    if state in REMOTE_WAIT_STATES:
        raise DeliveryWaiting(f"remote_status:{state}")
    if state in REMOTE_FAILURE_STATES:
        raise DeliveryError(f"remote_terminal_failure:{state}")
    require(state == REMOTE_READY_STATUS, f"remote_status_invalid:{state}")
    checksum = parse_remote_archive_checksum(
        remote.read_file(config.remote_root / REMOTE_ARCHIVE_SHA, max_bytes=4096)
    )
    staging_root = config.delivery_root / "staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    archive = staging_root / f"{checksum}.tar.gz"
    extracted = staging_root / f"{checksum}.extracted"
    archive.unlink(missing_ok=True)
    if extracted.exists():
        require(extracted.is_dir() and not extracted.is_symlink(), "stale_extracted_path_invalid")
        shutil.rmtree(extracted)
    try:
        remote.stream_file(config.remote_root / REMOTE_ARCHIVE, archive, max_bytes=MAX_ARCHIVE_BYTES)
        require(sha256_file(archive) == checksum, "downloaded_archive_sha256_mismatch")
        extract_validated_archive(archive, extracted)
        bundle = validate_release_outputs(
            extracted,
            freeze,
            split_manifest=split_manifest,
            generic_prior=generic_prior,
            expected_split_sha256=expected_split_sha256,
            expected_generic_prior_sha256=expected_generic_prior_sha256,
        )
        publish_content_addressed(
            config.delivery_root,
            extracted,
            checksum,
            {
                "freeze": freeze,
                "bundle": bundle,
                "split_manifest": split_manifest,
                "generic_prior": generic_prior,
                "expected_split_sha256": expected_split_sha256,
                "expected_generic_prior_sha256": expected_generic_prior_sha256,
            },
        )
        return checksum
    finally:
        archive.unlink(missing_ok=True)
        if extracted.exists():
            require(extracted.is_dir() and not extracted.is_symlink(), "staging_extracted_cleanup_path_invalid")
            shutil.rmtree(extracted)


def verify_offline_archive(
    archive: Path,
    freeze_path: Path,
    *,
    split_manifest: Path = CANONICAL_SPLIT_MANIFEST,
    generic_prior: Path = CANONICAL_GENERIC_PRIOR,
    expected_split_sha256: str = EXPECTED_SPLIT_MANIFEST_SHA256,
    expected_generic_prior_sha256: str = EXPECTED_GENERIC_PRIOR_SHA256,
) -> dict[str, Any]:
    freeze = load_freeze(freeze_path, launch_authorized=False)
    require(sha256_file(CANONICAL_PREREG) == EXPECTED_PREREG_SHA256, "canonical_prereg_hash_mismatch")
    require(freeze_file_hash(freeze, "delivery") == sha256_file(Path(__file__)), "delivery_script_hash_mismatch")
    with tempfile.TemporaryDirectory(prefix="pvrig-v4d-dev1-offline-") as directory:
        extracted = Path(directory) / "release"
        extract_validated_archive(archive, extracted)
        result = validate_release_outputs(
            extracted,
            freeze,
            split_manifest=split_manifest,
            generic_prior=generic_prior,
            expected_split_sha256=expected_split_sha256,
            expected_generic_prior_sha256=expected_generic_prior_sha256,
        )
    return {**result, "archive_sha256": sha256_file(archive), "offline_only": True}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify-offline-archive", type=Path)
    mode.add_argument("--watch", action="store_true")
    parser.add_argument("--freeze", type=Path, default=CANONICAL_FREEZE_CANDIDATE)
    parser.add_argument("--delivery-root", type=Path, default=CANONICAL_DELIVERY_ROOT)
    parser.add_argument("--ssh-exe", type=Path, default=CANONICAL_SSH)
    parser.add_argument("--remote-host", default=REMOTE_HOST)
    parser.add_argument("--remote-root", type=Path, default=REMOTE_ROOT)
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--production", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.verify_offline_archive is not None:
        print(json.dumps(verify_offline_archive(args.verify_offline_archive, args.freeze), sort_keys=True))
        return 0
    require(args.production, "remote_watch_requires_production")
    require(Path(__file__).resolve() == CANONICAL_SCRIPT, "noncanonical_delivery_script")
    require(args.freeze == CANONICAL_LAUNCH_FREEZE, "candidate_freeze_cannot_authorize_remote_access")
    require(args.delivery_root == CANONICAL_DELIVERY_ROOT, "noncanonical_delivery_root")
    require(args.ssh_exe == CANONICAL_SSH, "noncanonical_ssh")
    require(args.remote_host == REMOTE_HOST and args.remote_root == REMOTE_ROOT, "noncanonical_remote")
    freeze = load_freeze(args.freeze, launch_authorized=True)
    require(freeze_file_hash(freeze, "delivery") == sha256_file(Path(__file__)), "delivery_script_hash_mismatch")
    args.delivery_root.mkdir(parents=True, exist_ok=True)
    lock = args.delivery_root / "delivery_dev1.lock"
    with lock.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = Config(
            delivery_root=args.delivery_root,
            ssh_exe=args.ssh_exe,
            remote_host=args.remote_host,
            remote_root=args.remote_root,
            poll_seconds=args.poll_seconds,
            production=True,
            freeze_path=args.freeze,
        )
        remote = RemoteClient(args.ssh_exe, args.remote_host)
        while True:
            try:
                archive_sha = one_remote_attempt(config, remote, freeze)
            except DeliveryWaiting:
                time.sleep(args.poll_seconds)
                continue
            print(json.dumps({"status": "DELIVERED_DEV1_TEST32_SEALED", "archive_sha256": archive_sha}, sort_keys=True))
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
