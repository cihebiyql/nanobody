#!/usr/bin/env python3
"""Freeze a control-only cross-campaign dual-docking bridge.

The bridge physically filters both job manifests to controls before constructing
any result path. It never reads candidate result JSON files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import random
import shutil
import stat
import statistics
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import prepare_phase2_v4_d_open_teacher as teacher  # noqa: E402


DATA_ROOT = SCRIPT_DIR.parents[2]
SCHEMA_VERSION = "phase2_v4_d_cross_campaign_control_bridge_v1"
TEST_SCHEMA_VERSION = "phase2_v4_d_cross_campaign_control_bridge_test_fixture_v1"
STATUS = "PASS_V4_D_CROSS_CAMPAIGN_CONTROL_BRIDGE_FROZEN"
TEST_STATUS = "PASS_V4_D_CROSS_CAMPAIGN_CONTROL_BRIDGE_TEST_FIXTURE_ONLY"
VERIFIED_STATUS = "PASS_V4_D_CROSS_CAMPAIGN_CONTROL_BRIDGE_RECEIPT_VERIFIED"
TEST_VERIFIED_STATUS = (
    "PASS_V4_D_CROSS_CAMPAIGN_CONTROL_BRIDGE_TEST_FIXTURE_RECEIPT_VERIFIED"
)
EXPECTED_CONTROL_COUNT = 47
EXPECTED_JOB_COUNT = 282
CANONICAL_PRODUCTION_OUTPUT_ROOT = Path(
    "/data/qlyu/projects/pvrig_v4_d_cross_campaign_control_bridge_v1"
)
DEFAULT_PREREGISTRATION = (
    SCRIPT_DIR.parent
    / "audits/phase2_v4_d_cross_campaign_control_bridge_preregistration.json"
)
TEST_IMPLEMENTATION = SCRIPT_DIR / "test_build_phase2_v4_d_cross_campaign_control_bridge.py"
DEFAULT_IMPLEMENTATION_FREEZE = (
    DATA_ROOT
    / "reports/pvrig_v4_d_cross_campaign_control_bridge_deployment_v1"
    / "phase2_v4_d_cross_campaign_control_bridge_implementation_freeze.json"
)
DEFAULT_IMPLEMENTATION_FREEZE_SHA256_RECORD = DEFAULT_IMPLEMENTATION_FREEZE.with_suffix(
    ".sha256"
)
DEFAULT_DEPLOYMENT_TRUST_ROOT = (
    DATA_ROOT
    / "reports/pvrig_v4_d_cross_campaign_control_bridge_deployment_v1/SHA256SUMS"
)
DEPLOYMENT_TRUST_ROOT_ENV = "PVRIG_V4_D_CONTROL_BRIDGE_TRUST_ROOT_SHA256"
DEPLOYMENT_TRUST_ROOT_BINDINGS = (
    "reports/pvrig_v4_d_cross_campaign_control_bridge_deployment_v1/phase2_v4_d_cross_campaign_control_bridge_implementation_freeze.json",
    "experiments/phase2_5080_v1/audits/phase2_v4_d_cross_campaign_control_bridge_preregistration.json",
    "experiments/phase2_5080_v1/src/build_phase2_v4_d_cross_campaign_control_bridge.py",
    "experiments/phase2_5080_v1/src/test_build_phase2_v4_d_cross_campaign_control_bridge.py",
    "experiments/phase2_5080_v1/src/prepare_phase2_v4_d_open_teacher.py",
)
EXPECTED_PREREGISTRATION_SHA256 = (
    "ddc1b7f8694b2d489dad009031b2594ab80036bb1e95ba30c2e13efbfe902683"
)
PREREGISTRATION_SCHEMA_VERSION = (
    "phase2_v4_d_cross_campaign_control_bridge_preregistration_v5_pre_extraction_openat_and_repository_trust_closure"
)
IMPLEMENTATION_FREEZE_SCHEMA_VERSION = (
    "phase2_v4_d_cross_campaign_control_bridge_implementation_freeze_v1"
)
IMPLEMENTATION_FREEZE_STATUS = "FROZEN_BEFORE_PAIRED_CONTROL_SCORE_EXTRACTION"
CONFORMATIONS = ("8x6b", "9e6y")
SEEDS = (917, 1931, 3253)
OUTPUT_FILENAMES = (
    "cross_campaign_control_bridge_282.tsv",
    "cross_campaign_control_bridge_entities_47.tsv",
    "cross_campaign_control_bridge_audit.json",
    "cross_campaign_control_bridge_receipt.json",
)
MANIFEST_RELATIVE_PATH = Path("manifests/docking_jobs.tsv")
RESULTS_RELATIVE_PATH = Path("results")
RUNS_RELATIVE_PATH = Path("runs")
HADDOCK_CONFIG_RELATIVE_PATH = Path("haddock3.cfg")
AIR_RESTRAINT_RELATIVE_PATH = Path("data/air.tbl")
PROTOCOL_CORE_LOCK_RELATIVE_PATH = Path("PROTOCOL_CORE_LOCK.json")
PROTOCOL_SPEC_RELATIVE_PATH = Path("config/protocol_spec.json")
CONTROL_MANIFEST_RELATIVE_PATH = Path("inputs/calibration_controls_47.tsv")
SCORE_POSE_RELATIVE_PATH = Path("scripts/score_pose.py")
CLAIM_BOUNDARY = (
    "Control-only cross-campaign computational dual-docking geometry bridge; "
    "not candidate evidence, binding, affinity, competition, Docking Gold, or "
    "experimental blocking truth."
)

REQUIRED_MANIFEST_FIELDS = {
    "job_id",
    "job_hash",
    "entity_type",
    "entity_id",
    "conformation",
    "seed",
    "sequence_sha256",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "cdr_residues",
    "receptor_pdb",
    "receptor_chain",
    "control_class",
    "expected_behavior",
    "ligand_chain",
    "vhh_chain",
    "numbering",
    "cfg_hash",
    "restraint_hash",
    "protocol_core_sha256",
    "protocol_hash",
}
PREREG_IDENTITY_FIELDS = (
    "entity_id",
    "control_class",
    "expected_behavior",
    "conformation",
    "seed",
    "sequence_sha256",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "cdr_residues",
    "receptor_chain",
    "ligand_chain",
    "vhh_chain",
    "numbering",
)
MATCHED_IDENTITY_FIELDS = PREREG_IDENTITY_FIELDS
SUMMARY_FIELDS = (
    "complete_model_count",
    "job_utility_raw",
    "job_utility",
    "model_count_reliability",
    "agreement_reliability",
    "native_cross_support_agreement",
    "model_pair_consensus_fraction",
    "model_strict_a_fraction",
    "hotspot_overlap",
    "anchor_overlap",
    "holdout_overlap",
    "total_occlusion",
    "cdr3_occlusion",
    "cdr3_fraction",
    "vhh_pvrig_clash_residue_pairs",
    "vhh_pvrl2_clash_residue_pairs",
    "overlay_rmsd_a",
)


class BridgeError(RuntimeError):
    """Raised when the frozen control-only contract cannot be satisfied."""


@dataclass(frozen=True)
class FileSnapshot:
    path: Path
    payload: bytes
    sha256: str


@dataclass(frozen=True)
class ImplementationFreeze:
    manifest: FileSnapshot
    sha256_record: FileSnapshot
    payload: dict[str, Any]


@dataclass(frozen=True)
class DeploymentTrustRoot:
    manifest: FileSnapshot
    bindings: dict[Path, FileSnapshot]


@dataclass(frozen=True)
class Campaign:
    label: str
    root: Path
    manifest: FileSnapshot
    protocol_lock: FileSnapshot
    protocol_spec: FileSnapshot
    control_manifest: FileSnapshot
    score_pose: FileSnapshot
    protocol_core_sha256: str
    protocol_semantics_sha256: str
    manifest_row_count: int
    excluded_candidate_row_count: int
    controls_by_key: dict[tuple[str, str, int], dict[str, str]]
    receptors: dict[Path, FileSnapshot]
    configs: dict[tuple[str, str, int], FileSnapshot]
    restraints: dict[tuple[str, str, int], FileSnapshot]
    canonical_config_sha256: dict[tuple[str, str, int], str]
    canonical_restraint_sha256: dict[tuple[str, str, int], str]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BridgeError(message)


def output_identity(test_only: bool) -> tuple[str, str, str]:
    if test_only:
        return TEST_SCHEMA_VERSION, TEST_STATUS, TEST_VERIFIED_STATUS
    return SCHEMA_VERSION, STATUS, VERIFIED_STATUS


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def require_sha256(value: Any, label: str) -> str:
    digest = str(value).strip().lower()
    require(
        len(digest) == 64 and all(character in "0123456789abcdef" for character in digest),
        f"sha256_missing_or_invalid:{label}",
    )
    return digest


def lexical_absolute(path: Path) -> Path:
    """Return an absolute normalized path without following the final symlink."""
    expanded = path.expanduser()
    return Path(os.path.abspath(os.fspath(expanded)))


def _safe_relative_path(relative_path: Path, label: str) -> Path:
    relative = Path(relative_path)
    require(
        bool(relative.parts)
        and not relative.is_absolute()
        and all(part not in {"", ".", ".."} for part in relative.parts),
        f"unsafe_relative_path:{label}:{relative}",
    )
    return relative


def snapshot_file_at(root: Path, relative_path: Path, label: str) -> FileSnapshot:
    """Read a file through a held no-follow directory-FD chain."""
    base = lexical_absolute(root)
    relative = _safe_relative_path(relative_path, label)
    absolute = lexical_absolute(base / relative)
    require(
        absolute.is_relative_to(base),
        f"file_path_outside_root:{label}:{absolute}",
    )
    directory_parts = list(base.parts[1:]) + list(relative.parts[:-1])
    final_name = relative.parts[-1]
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
        os, "O_NOFOLLOW", 0
    )
    directory_descriptors: list[int] = []
    directory_links: list[tuple[int, str, tuple[int, int]]] = []
    descriptor: int | None = None
    try:
        try:
            current = os.open(os.path.sep, directory_flags)
        except OSError as exc:
            raise BridgeError(f"cannot_open_root_directory:{label}") from exc
        directory_descriptors.append(current)
        for part in directory_parts:
            try:
                before = os.stat(part, dir_fd=current, follow_symlinks=False)
            except OSError as exc:
                raise BridgeError(
                    f"cannot_lstat_directory_component:{label}:{part}"
                ) from exc
            require(
                stat.S_ISDIR(before.st_mode),
                f"directory_symlink_or_non_directory_forbidden:{label}:{part}",
            )
            try:
                child = os.open(part, directory_flags, dir_fd=current)
            except OSError as exc:
                raise BridgeError(
                    f"cannot_open_directory_component_nofollow:{label}:{part}"
                ) from exc
            opened_directory = os.fstat(child)
            require(
                stat.S_ISDIR(opened_directory.st_mode),
                f"opened_component_not_directory:{label}:{part}",
            )
            require(
                (before.st_dev, before.st_ino)
                == (opened_directory.st_dev, opened_directory.st_ino),
                f"directory_replaced_before_open:{label}:{part}",
            )
            directory_links.append(
                (
                    current,
                    part,
                    (opened_directory.st_dev, opened_directory.st_ino),
                )
            )
            directory_descriptors.append(child)
            current = child
        try:
            before_file = os.stat(
                final_name, dir_fd=current, follow_symlinks=False
            )
        except OSError as exc:
            raise BridgeError(f"cannot_lstat:{label}:{absolute}") from exc
        require(
            stat.S_ISREG(before_file.st_mode),
            f"not_regular_file_or_symlink_forbidden:{label}:{absolute}",
        )
        try:
            descriptor = os.open(final_name, file_flags, dir_fd=current)
        except OSError as exc:
            raise BridgeError(f"cannot_open_nofollow:{label}:{absolute}") from exc
        opened = os.fstat(descriptor)
        require(
            stat.S_ISREG(opened.st_mode),
            f"opened_file_not_regular:{label}:{absolute}",
        )
        require(
            (before_file.st_dev, before_file.st_ino)
            == (opened.st_dev, opened.st_ino),
            f"file_replaced_before_open:{label}:{absolute}",
        )
        chunks: list[bytes] = []
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        after = os.fstat(descriptor)
        require(
            (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            )
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
            f"file_changed_while_reading:{label}:{absolute}",
        )
        try:
            linked_file = os.stat(
                final_name, dir_fd=current, follow_symlinks=False
            )
        except OSError as exc:
            raise BridgeError(f"file_unlinked_while_reading:{label}:{absolute}") from exc
        require(
            stat.S_ISREG(linked_file.st_mode)
            and (linked_file.st_dev, linked_file.st_ino)
            == (opened.st_dev, opened.st_ino),
            f"file_entry_replaced_during_read:{label}:{absolute}",
        )
        for parent_fd, part, expected_identity in directory_links:
            try:
                linked_directory = os.stat(
                    part, dir_fd=parent_fd, follow_symlinks=False
                )
            except OSError as exc:
                raise BridgeError(
                    f"directory_unlinked_while_reading:{label}:{part}"
                ) from exc
            require(
                stat.S_ISDIR(linked_directory.st_mode)
                and (linked_directory.st_dev, linked_directory.st_ino)
                == expected_identity,
                f"directory_entry_replaced_during_read:{label}:{part}",
            )
    finally:
        if descriptor is not None:
            os.close(descriptor)
        for directory_descriptor in reversed(directory_descriptors):
            os.close(directory_descriptor)
    payload = b"".join(chunks)
    require(bool(payload), f"empty_file:{label}:{absolute}")
    return FileSnapshot(absolute, payload, sha256_bytes(payload))


def snapshot_file(path: Path, label: str) -> FileSnapshot:
    absolute = lexical_absolute(path)
    return snapshot_file_at(absolute.parent, Path(absolute.name), label)


def parse_tsv(snapshot: FileSnapshot, label: str) -> tuple[list[dict[str, str]], list[str]]:
    try:
        text = snapshot.payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BridgeError(f"invalid_utf8:{label}:{snapshot.path}") from exc
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    fields = list(reader.fieldnames or [])
    require(bool(fields), f"missing_header:{label}:{snapshot.path}")
    return list(reader), fields


def parse_json(snapshot: FileSnapshot, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(snapshot.payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeError(f"invalid_json:{label}:{snapshot.path}") from exc
    require(isinstance(payload, dict), f"json_not_object:{label}:{snapshot.path}")
    return payload


def protocol_core_sha256(payload: Mapping[str, Any], label: str) -> str:
    candidates = [
        payload.get("protocol_core_sha256"),
        payload.get("core_payload_sha256"),
        (payload.get("protocol_core") or {}).get("sha256")
        if isinstance(payload.get("protocol_core"), Mapping)
        else None,
    ]
    value = next((str(item).lower() for item in candidates if item), "")
    require(
        len(value) == 64 and all(character in "0123456789abcdef" for character in value),
        f"protocol_core_sha256_missing_or_invalid:{label}",
    )
    return value


def load_preregistration(
    path: Path = DEFAULT_PREREGISTRATION,
    *,
    production: bool,
) -> tuple[FileSnapshot, dict[str, Any]]:
    snapshot = snapshot_file(path, "bridge_preregistration")
    if production:
        require(
            snapshot.path == DEFAULT_PREREGISTRATION.resolve(),
            "production_preregistration_path_override_forbidden",
        )
        require(
            snapshot.sha256 == EXPECTED_PREREGISTRATION_SHA256,
            "production_preregistration_sha256_mismatch",
        )
    payload = parse_json(snapshot, "bridge_preregistration")
    require(
        payload.get("schema_version") == PREREGISTRATION_SCHEMA_VERSION,
        "preregistration_schema_invalid",
    )
    require(
        payload.get("status") == "FROZEN_BEFORE_PAIRED_CONTROL_SCORE_EXTRACTION",
        "preregistration_status_invalid",
    )
    contract = payload.get("data_access_contract") or {}
    require(contract.get("pair_key") == ["entity_id", "conformation", "seed"], "preregistration_pair_key_invalid")
    require(int(contract.get("expected_entities", -1)) == EXPECTED_CONTROL_COUNT, "preregistration_control_count_invalid")
    require(int(contract.get("expected_paired_jobs", -1)) == EXPECTED_JOB_COUNT, "preregistration_job_count_invalid")
    require(tuple(contract.get("expected_receptors") or ()) == CONFORMATIONS, "preregistration_conformations_invalid")
    require(tuple(int(value) for value in contract.get("expected_seeds") or ()) == SEEDS, "preregistration_seeds_invalid")
    require(
        tuple(contract.get("identity_fields_required_equal") or ())
        == PREREG_IDENTITY_FIELDS,
        "preregistration_identity_fields_invalid",
    )
    publication = payload.get("publication_contract") or {}
    require(
        tuple(publication.get("required_outputs") or ()) == OUTPUT_FILENAMES,
        "preregistration_output_contract_invalid",
    )
    require(
        publication.get("output_set_policy")
        == "exactly the four required regular files; no extras and no symlinks",
        "preregistration_exact_output_set_policy_invalid",
    )
    freeze_contract = payload.get("implementation_freeze_contract") or {}
    require(
        freeze_contract.get("schema_version") == IMPLEMENTATION_FREEZE_SCHEMA_VERSION,
        "preregistration_implementation_freeze_schema_invalid",
    )
    require(
        freeze_contract.get("canonical_path")
        == "reports/pvrig_v4_d_cross_campaign_control_bridge_deployment_v1/phase2_v4_d_cross_campaign_control_bridge_implementation_freeze.json",
        "preregistration_implementation_freeze_path_invalid",
    )
    require(
        freeze_contract.get("sha256_record_path")
        == "reports/pvrig_v4_d_cross_campaign_control_bridge_deployment_v1/phase2_v4_d_cross_campaign_control_bridge_implementation_freeze.sha256",
        "preregistration_implementation_freeze_record_path_invalid",
    )
    require(
        tuple(freeze_contract.get("required_bindings") or ())
        == ("preregistration", "builder", "tests", "teacher_utility"),
        "preregistration_implementation_freeze_bindings_invalid",
    )
    require(
        freeze_contract.get("production_validation_required") is True,
        "preregistration_implementation_freeze_validation_invalid",
    )
    trust_contract = payload.get("deployment_trust_root_contract") or {}
    require(
        trust_contract.get("canonical_path")
        == "reports/pvrig_v4_d_cross_campaign_control_bridge_deployment_v1/SHA256SUMS",
        "preregistration_deployment_trust_root_path_invalid",
    )
    require(
        tuple(trust_contract.get("required_bindings") or ())
        == DEPLOYMENT_TRUST_ROOT_BINDINGS,
        "preregistration_deployment_trust_root_bindings_invalid",
    )
    require(
        trust_contract.get("launcher_path")
        == "reports/pvrig_v4_d_cross_campaign_control_bridge_deployment_v1/run_production_bridge.sh",
        "preregistration_deployment_launcher_path_invalid",
    )
    require(
        trust_contract.get("builder_environment_binding") == DEPLOYMENT_TRUST_ROOT_ENV,
        "preregistration_deployment_trust_root_environment_invalid",
    )
    require(
        trust_contract.get("launcher_hardcodes_sha256sum_digest") is True
        and trust_contract.get("production_builder_validation_required") is True,
        "preregistration_deployment_trust_root_validation_invalid",
    )
    bootstrap = payload.get("bootstrap") or {}
    require(int(bootstrap.get("replicates", -1)) == 10000, "preregistration_bootstrap_replicates_invalid")
    require(int(bootstrap.get("seed", -1)) == 20260716, "preregistration_bootstrap_seed_invalid")
    gates = payload.get("hard_gates") or {}
    require(
        set(gates)
        == {
            "identity",
            "overall_spearman",
            "per_receptor_spearman",
            "overall_lin_concordance_correlation",
            "absolute_error",
            "signed_bias",
        },
        "preregistration_hard_gate_set_invalid",
    )
    decision = payload.get("decision_policy") or {}
    require(bool(decision.get("pass")) and bool(decision.get("fail")), "preregistration_decision_policy_invalid")
    return snapshot, payload


def reject_production_paths_in_test_mode(
    left_root: Path,
    right_root: Path,
    output_root: Path,
    preregistration: Mapping[str, Any],
) -> None:
    campaign_specs = preregistration.get("campaigns") or {}
    forbidden_campaign_roots = {
        lexical_absolute(Path(str(spec.get("root", ""))))
        for spec in campaign_specs.values()
        if isinstance(spec, Mapping) and str(spec.get("root", "")).strip()
    }
    for label, root in (("left", left_root), ("right", right_root)):
        require(
            lexical_absolute(root) not in forbidden_campaign_roots,
            f"test_mode_production_campaign_root_forbidden:{label}",
        )
    require(
        lexical_absolute(output_root)
        != lexical_absolute(CANONICAL_PRODUCTION_OUTPUT_ROOT),
        "test_mode_production_output_root_forbidden",
    )


def implementation_binding_paths() -> dict[str, Path]:
    return {
        "preregistration": DEFAULT_PREREGISTRATION,
        "builder": Path(__file__),
        "tests": TEST_IMPLEMENTATION,
        "teacher_utility": Path(teacher.__file__),
    }


def load_implementation_freeze(
    preregistration_snapshot: FileSnapshot,
    preregistration: Mapping[str, Any],
    *,
    production: bool,
    freeze_path: Path = DEFAULT_IMPLEMENTATION_FREEZE,
    sha256_record_path: Path = DEFAULT_IMPLEMENTATION_FREEZE_SHA256_RECORD,
) -> ImplementationFreeze:
    contract = preregistration["implementation_freeze_contract"]
    freeze_absolute = lexical_absolute(freeze_path)
    record_absolute = lexical_absolute(sha256_record_path)
    if production:
        require(
            freeze_absolute == lexical_absolute(DEFAULT_IMPLEMENTATION_FREEZE),
            "production_implementation_freeze_path_override_forbidden",
        )
        require(
            record_absolute
            == lexical_absolute(DEFAULT_IMPLEMENTATION_FREEZE_SHA256_RECORD),
            "production_implementation_freeze_record_override_forbidden",
        )
    freeze_snapshot = snapshot_file(freeze_absolute, "bridge_implementation_freeze")
    record_snapshot = snapshot_file(
        record_absolute, "bridge_implementation_freeze_sha256_record"
    )
    payload = parse_json(freeze_snapshot, "bridge_implementation_freeze")
    require(
        payload.get("schema_version") == IMPLEMENTATION_FREEZE_SCHEMA_VERSION,
        "implementation_freeze_schema_invalid",
    )
    require(
        payload.get("status") == IMPLEMENTATION_FREEZE_STATUS,
        "implementation_freeze_status_invalid",
    )
    require(
        payload.get("paired_control_values_extracted_before_freeze") is False,
        "implementation_freeze_timing_invalid",
    )
    require(
        payload.get("production_validation_required") is True,
        "implementation_freeze_production_validation_invalid",
    )
    try:
        record_text = record_snapshot.payload.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise BridgeError("implementation_freeze_sha256_record_not_ascii") from exc
    record_parts = record_text.split()
    require(
        len(record_parts) == 2
        and record_parts[0] == freeze_snapshot.sha256
        and record_parts[1] == freeze_snapshot.path.name,
        "implementation_freeze_sha256_record_invalid",
    )
    bindings = payload.get("bindings")
    require(isinstance(bindings, Mapping), "implementation_freeze_bindings_missing")
    required_labels = tuple(contract["required_bindings"])
    require(set(bindings) == set(required_labels), "implementation_freeze_binding_set_invalid")
    root = DATA_ROOT
    expected_paths = implementation_binding_paths()
    for label in required_labels:
        binding = bindings.get(label)
        require(isinstance(binding, Mapping), f"implementation_freeze_binding_invalid:{label}")
        relative = Path(str(binding.get("path", "")))
        require(
            bool(str(relative)) and not relative.is_absolute() and ".." not in relative.parts,
            f"implementation_freeze_binding_path_invalid:{label}",
        )
        bound_path = lexical_absolute(root / relative)
        expected_path = lexical_absolute(expected_paths[label])
        require(
            bound_path == expected_path,
            f"implementation_freeze_binding_path_mismatch:{label}",
        )
        current = (
            preregistration_snapshot
            if label == "preregistration"
            else snapshot_file(expected_path, f"implementation_freeze_{label}")
        )
        require(
            str(binding.get("sha256", "")).lower() == current.sha256,
            f"implementation_freeze_binding_hash_mismatch:{label}",
        )
    require(
        str(payload.get("preregistration_sha256", "")).lower()
        == preregistration_snapshot.sha256,
        "implementation_freeze_preregistration_hash_invalid",
    )
    return ImplementationFreeze(freeze_snapshot, record_snapshot, payload)


def load_deployment_trust_root(
    preregistration: Mapping[str, Any],
    *,
    production: bool,
    trust_root_path: Path = DEFAULT_DEPLOYMENT_TRUST_ROOT,
) -> DeploymentTrustRoot:
    absolute = lexical_absolute(trust_root_path)
    if production:
        require(
            absolute == lexical_absolute(DEFAULT_DEPLOYMENT_TRUST_ROOT),
            "production_deployment_trust_root_path_override_forbidden",
        )
    manifest = snapshot_file(absolute, "bridge_deployment_trust_root")
    if production:
        exported = require_sha256(
            os.environ.get(DEPLOYMENT_TRUST_ROOT_ENV, ""),
            "deployment_trust_root_environment",
        )
        require(
            exported == manifest.sha256,
            "deployment_trust_root_environment_hash_mismatch",
        )
    try:
        lines = manifest.payload.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise BridgeError("deployment_trust_root_not_ascii") from exc
    declared: dict[str, str] = {}
    for line in lines:
        require(bool(line.strip()), "deployment_trust_root_blank_line")
        parts = line.split(None, 1)
        require(len(parts) == 2, "deployment_trust_root_row_invalid")
        digest = require_sha256(parts[0], "deployment_trust_root_row")
        relative = parts[1].strip()
        require(
            relative in DEPLOYMENT_TRUST_ROOT_BINDINGS and relative not in declared,
            f"deployment_trust_root_path_invalid_or_duplicate:{relative}",
        )
        declared[relative] = digest
    require(
        tuple(declared) == DEPLOYMENT_TRUST_ROOT_BINDINGS,
        "deployment_trust_root_binding_order_or_set_invalid",
    )
    contract = preregistration["deployment_trust_root_contract"]
    require(
        tuple(contract["required_bindings"]) == DEPLOYMENT_TRUST_ROOT_BINDINGS,
        "deployment_trust_root_preregistration_binding_mismatch",
    )
    experiment_root = DATA_ROOT
    bindings: dict[Path, FileSnapshot] = {}
    for relative in DEPLOYMENT_TRUST_ROOT_BINDINGS:
        path = lexical_absolute(experiment_root / relative)
        require(
            path.is_relative_to(experiment_root),
            f"deployment_trust_root_path_outside_experiment:{relative}",
        )
        snapshot = snapshot_file(path, f"deployment_trust_root_binding:{relative}")
        require(
            snapshot.sha256 == declared[relative],
            f"deployment_trust_root_binding_hash_mismatch:{relative}",
        )
        bindings[path] = snapshot
    return DeploymentTrustRoot(manifest=manifest, bindings=bindings)


def semantic_subset(value: Any) -> Any:
    """Remove paths and publication identity while retaining protocol behavior."""
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("path", "sha256", "hash", "protocol_id", "panel_id")):
                continue
            if lowered in {"status", "schema_version", "publication", "runtime_provenance"}:
                continue
            output[str(key)] = semantic_subset(item)
        return output
    if isinstance(value, list):
        return [semantic_subset(item) for item in value]
    return value


def protocol_semantics(payload: Mapping[str, Any]) -> dict[str, Any]:
    docking = payload.get("docking") or {}
    docking_fields = (
        "engine",
        "validated_engine_version",
        "sampling",
        "npart",
        "randremoval",
        "module_seed_fields",
        "rigidbody_tolerance",
        "flexref_tolerance",
        "seeds",
        "seletop_select",
        "seletopclusts_top_models",
    )
    references = payload.get("references") or {}
    conformations = references.get("conformations") or {}
    reference_semantics = {
        "receptor_chain": references.get("receptor_chain"),
        "ligand_chain": references.get("ligand_chain"),
        "numbering": references.get("numbering"),
        "conformations": {
            name: semantic_subset(conformations.get(name) or {}) for name in CONFORMATIONS
        },
    }
    return {
        "docking": {field: semantic_subset(docking.get(field)) for field in docking_fields},
        "scoring": semantic_subset(payload.get("scoring") or {}),
        "interface": semantic_subset(payload.get("interface") or {}),
        "references": reference_semantics,
    }


def validate_receptor_snapshot(snapshot: FileSnapshot, label: str) -> None:
    try:
        text = snapshot.payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BridgeError(f"receptor_not_utf8:{label}") from exc
    lines = text.splitlines()
    require(any(line.startswith("ATOM  ") for line in lines), f"receptor_atom_records_missing:{label}")
    require(not any(line.startswith("HETATM") for line in lines), f"receptor_contains_hetatm:{label}")


def canonical_protocol_annotated_sha256(
    snapshot: FileSnapshot,
    *,
    expected_protocol_core_sha256: str,
    comment_marker: bytes,
    expected_annotation_index: int,
    label: str,
) -> str:
    core = require_sha256(expected_protocol_core_sha256, f"{label}_protocol_core")
    prefix = comment_marker + b" protocol_core_sha256="
    lines = snapshot.payload.splitlines(keepends=True)
    matching = [
        index
        for index, line in enumerate(lines)
        if line.rstrip(b"\r\n").startswith(prefix)
    ]
    require(len(matching) == 1, f"protocol_core_annotation_count:{label}:{len(matching)}")
    annotation_index = matching[0]
    require(
        annotation_index == expected_annotation_index,
        f"protocol_core_annotation_position_mismatch:{label}:{annotation_index}",
    )
    require(
        lines[annotation_index] == prefix + core.encode("ascii") + b"\n",
        f"protocol_core_annotation_mismatch:{label}",
    )
    require(
        not any(
            b"protocol_core_sha256" in line
            for index, line in enumerate(lines)
            if index != annotation_index
        ),
        f"unexpected_protocol_core_annotation:{label}",
    )
    canonical = b"".join(
        line for index, line in enumerate(lines) if index != annotation_index
    )
    require(bool(canonical), f"empty_canonical_protocol_input:{label}")
    return sha256_bytes(canonical)


def safe_job_id(value: str) -> str:
    require(
        bool(value) and value not in {".", ".."} and "/" not in value and "\\" not in value,
        f"unsafe_job_id:{value!r}",
    )
    return value


def require_real_directory(path: Path, label: str) -> Path:
    absolute = lexical_absolute(path)
    try:
        metadata = os.lstat(absolute)
    except OSError as exc:
        raise BridgeError(f"cannot_lstat_directory:{label}:{absolute}") from exc
    require(
        stat.S_ISDIR(metadata.st_mode),
        f"directory_symlink_or_non_directory_forbidden:{label}:{absolute}",
    )
    return absolute


def control_run_relative_path(
    row: Mapping[str, str], relative_path: Path
) -> Path:
    job_id = safe_job_id(str(row["job_id"]))
    relative = _safe_relative_path(
        RUNS_RELATIVE_PATH / job_id / relative_path,
        f"control_run:{job_id}",
    )
    require(
        relative.parts[:2] == (RUNS_RELATIVE_PATH.name, job_id),
        f"control_run_path_outside_root:{job_id}",
    )
    return relative


def campaign_key(row: Mapping[str, str]) -> tuple[str, str, int]:
    entity_id = str(row.get("entity_id", "")).strip()
    conformation = str(row.get("conformation", "")).strip().lower()
    try:
        seed = int(str(row.get("seed", "")).strip())
    except ValueError as exc:
        raise BridgeError(f"invalid_seed:{entity_id}:{row.get('seed')}") from exc
    require(bool(entity_id), "control_entity_id_missing")
    require(conformation in CONFORMATIONS, f"invalid_conformation:{entity_id}:{conformation}")
    require(seed in SEEDS, f"unexpected_seed:{entity_id}:{conformation}:{seed}")
    return entity_id, conformation, seed


def receptor_relative_path(root: Path, row: Mapping[str, str]) -> Path:
    raw = Path(str(row.get("receptor_pdb", "")))
    require(bool(str(raw)), f"receptor_path_missing:{row.get('job_id')}")
    absolute_root = lexical_absolute(root)
    if raw.is_absolute():
        absolute = lexical_absolute(raw)
        require(
            absolute.is_relative_to(absolute_root),
            f"receptor_path_outside_campaign:{row.get('job_id')}",
        )
        relative = absolute.relative_to(absolute_root)
    else:
        relative = raw
    return _safe_relative_path(relative, f"receptor:{row.get('job_id')}")


def receptor_path(root: Path, row: Mapping[str, str]) -> Path:
    return lexical_absolute(root / receptor_relative_path(root, row))


def load_campaign(
    root: Path,
    label: str,
    *,
    expected_control_count: int,
    expected_job_count: int,
    production_spec: Mapping[str, Any] | None = None,
) -> Campaign:
    resolved_root = lexical_absolute(root)
    manifest = snapshot_file_at(
        resolved_root, MANIFEST_RELATIVE_PATH, f"{label}_manifest"
    )
    lock = snapshot_file_at(
        resolved_root, PROTOCOL_CORE_LOCK_RELATIVE_PATH, f"{label}_protocol_core_lock"
    )
    protocol_spec = snapshot_file_at(
        resolved_root, PROTOCOL_SPEC_RELATIVE_PATH, f"{label}_protocol_spec"
    )
    control_manifest = snapshot_file_at(
        resolved_root, CONTROL_MANIFEST_RELATIVE_PATH, f"{label}_control_manifest"
    )
    score_pose = snapshot_file_at(
        resolved_root, SCORE_POSE_RELATIVE_PATH, f"{label}_score_pose"
    )
    lock_payload = parse_json(lock, f"{label}_protocol_core_lock")
    core = protocol_core_sha256(lock_payload, label)
    semantics = protocol_semantics(parse_json(protocol_spec, f"{label}_protocol_spec"))
    semantics_sha256 = sha256_json(semantics)
    if production_spec is not None:
        expected_root = lexical_absolute(Path(str(production_spec.get("root", ""))))
        require(resolved_root == expected_root, f"production_campaign_root_mismatch:{label}")
        expected_hashes = {
            "docking_jobs_sha256": manifest.sha256,
            "control_manifest_sha256": control_manifest.sha256,
            "protocol_spec_sha256": protocol_spec.sha256,
            "protocol_core_lock_file_sha256": lock.sha256,
            "score_pose_sha256": score_pose.sha256,
        }
        for field, observed in expected_hashes.items():
            require(
                str(production_spec.get(field, "")).lower() == observed,
                f"production_campaign_hash_mismatch:{label}:{field}",
            )
        require(
            str(production_spec.get("protocol_core_sha256", "")).lower() == core,
            f"production_protocol_core_mismatch:{label}",
        )
    rows, fields = parse_tsv(manifest, f"{label}_manifest")
    missing = sorted(REQUIRED_MANIFEST_FIELDS - set(fields))
    require(not missing, f"manifest_fields_missing:{label}:{','.join(missing)}")
    control_rows = [
        row for row in rows if str(row.get("entity_type", "")).strip().lower() == "control"
    ]
    candidate_count = sum(
        str(row.get("entity_type", "")).strip().lower() == "candidate" for row in rows
    )
    require(len(control_rows) == expected_job_count, f"control_job_count:{label}:{len(control_rows)}")
    controls: dict[tuple[str, str, int], dict[str, str]] = {}
    receptors: dict[Path, FileSnapshot] = {}
    configs: dict[tuple[str, str, int], FileSnapshot] = {}
    restraints: dict[tuple[str, str, int], FileSnapshot] = {}
    canonical_configs: dict[tuple[str, str, int], str] = {}
    canonical_restraints: dict[tuple[str, str, int], str] = {}
    for row in control_rows:
        safe_job_id(str(row["job_id"]))
        key = campaign_key(row)
        require(key not in controls, f"duplicate_control_key:{label}:{key}")
        manifest_core = require_sha256(
            row["protocol_core_sha256"], f"{label}:{row['job_id']}:protocol_core_sha256"
        )
        protocol_hash = require_sha256(
            row["protocol_hash"], f"{label}:{row['job_id']}:protocol_hash"
        )
        require(
            manifest_core == core,
            f"manifest_protocol_core_mismatch:{label}:{row['job_id']}",
        )
        require(
            protocol_hash == core,
            f"manifest_protocol_hash_lock_mismatch:{label}:{row['job_id']}",
        )
        cfg_expected = require_sha256(
            row["cfg_hash"], f"{label}:{row['job_id']}:cfg_hash"
        )
        restraint_expected = require_sha256(
            row["restraint_hash"], f"{label}:{row['job_id']}:restraint_hash"
        )
        cfg_snapshot = snapshot_file_at(
            resolved_root,
            control_run_relative_path(row, HADDOCK_CONFIG_RELATIVE_PATH),
            f"{label}_control_haddock_config",
        )
        restraint_snapshot = snapshot_file_at(
            resolved_root,
            control_run_relative_path(row, AIR_RESTRAINT_RELATIVE_PATH),
            f"{label}_control_air_restraint",
        )
        require(
            cfg_snapshot.sha256 == cfg_expected,
            f"manifest_cfg_hash_mismatch:{label}:{row['job_id']}",
        )
        require(
            restraint_snapshot.sha256 == restraint_expected,
            f"manifest_restraint_hash_mismatch:{label}:{row['job_id']}",
        )
        configs[key] = cfg_snapshot
        restraints[key] = restraint_snapshot
        canonical_configs[key] = canonical_protocol_annotated_sha256(
            cfg_snapshot,
            expected_protocol_core_sha256=core,
            comment_marker=b"#",
            expected_annotation_index=1,
            label=f"{label}:{row['job_id']}:haddock3.cfg",
        )
        canonical_restraints[key] = canonical_protocol_annotated_sha256(
            restraint_snapshot,
            expected_protocol_core_sha256=core,
            comment_marker=b"!",
            expected_annotation_index=0,
            label=f"{label}:{row['job_id']}:air.tbl",
        )
        receptor_absolute = receptor_path(resolved_root, row)
        if receptor_absolute not in receptors:
            receptors[receptor_absolute] = snapshot_file_at(
                resolved_root,
                receptor_relative_path(resolved_root, row),
                f"{label}_receptor",
            )
            validate_receptor_snapshot(
                receptors[receptor_absolute], f"{label}:{receptor_absolute.name}"
            )
        controls[key] = row
    entities = {key[0] for key in controls}
    require(len(entities) == expected_control_count, f"control_entity_count:{label}:{len(entities)}")
    expected_matrix = {
        (entity_id, conformation, seed)
        for entity_id in entities
        for conformation in CONFORMATIONS
        for seed in SEEDS
    }
    require(set(controls) == expected_matrix, f"control_matrix_incomplete:{label}")
    return Campaign(
        label=label,
        root=resolved_root,
        manifest=manifest,
        protocol_lock=lock,
        protocol_spec=protocol_spec,
        control_manifest=control_manifest,
        score_pose=score_pose,
        protocol_core_sha256=core,
        protocol_semantics_sha256=semantics_sha256,
        manifest_row_count=len(rows),
        excluded_candidate_row_count=candidate_count,
        controls_by_key=controls,
        receptors=receptors,
        configs=configs,
        restraints=restraints,
        canonical_config_sha256=canonical_configs,
        canonical_restraint_sha256=canonical_restraints,
    )


def result_relative_path(row: Mapping[str, str]) -> Path:
    job_id = safe_job_id(str(row["job_id"]))
    return _safe_relative_path(
        RESULTS_RELATIVE_PATH / job_id / "job_result.json", f"control_result:{job_id}"
    )


def result_path(campaign: Campaign, row: Mapping[str, str]) -> Path:
    path = lexical_absolute(campaign.root / result_relative_path(row))
    require(
        path.is_relative_to(lexical_absolute(campaign.root / RESULTS_RELATIVE_PATH)),
        f"result_path_outside_root:{campaign.label}:{row.get('job_id')}",
    )
    return path


def nested(payload: Mapping[str, Any], *path: str) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            raise BridgeError(f"raw_pose_metric_missing:{'.'.join(path)}")
        value = value[key]
    return value


def pose_rows_from_result(job_id: str, evidence: Mapping[str, Any]) -> list[dict[str, str]]:
    poses = evidence.get("pose_scores")
    require(isinstance(poses, list) and poses, f"pose_scores_missing:{job_id}")
    output: list[dict[str, str]] = []
    for pose in poses:
        require(isinstance(pose, Mapping), f"pose_payload_invalid:{job_id}")
        model = Path(str(pose.get("pose", ""))).name
        require(bool(model), f"pose_model_missing:{job_id}")
        haddock = pose.get("haddock_io") or {}
        scores = pose.get("scores")
        require(isinstance(scores, list), f"pose_scores_invalid:{job_id}:{model}")
        references = {str(score.get("reference_id", "")).lower() for score in scores}
        require(references == set(CONFORMATIONS), f"pose_reference_set_invalid:{job_id}:{model}")
        for score in scores:
            require(isinstance(score, Mapping), f"score_payload_invalid:{job_id}:{model}")
            reference = str(score.get("reference_id", "")).lower()
            clashes = nested(score, "clashes_2p5a")
            output.append(
                {
                    "job_id": job_id,
                    "model": model,
                    "scoring_reference": reference,
                    "haddock_score": str(haddock.get("score", "")),
                    "air_energy": str(haddock.get("unw_energies.air", "")),
                    "hotspot_overlap": str(nested(score, "hotspot_overlap", "full", "count")),
                    "anchor_overlap": str(nested(score, "hotspot_overlap", "anchor", "count")),
                    "holdout_overlap": str(nested(score, "hotspot_overlap", "holdout", "count")),
                    "total_occlusion": str(
                        nested(score, "vhh_pvrl2_occlusion", "residue_pair_count")
                    ),
                    "cdr3_occlusion": str(
                        nested(
                            score,
                            "vhh_pvrl2_occlusion",
                            "by_vhh_region_pair_count",
                            "cdr3",
                        )
                    ),
                    "cdr3_fraction": str(
                        nested(score, "vhh_pvrl2_occlusion", "cdr3_fraction")
                    ),
                    "vhh_pvrig_clash_residue_pairs": str(
                        nested(clashes, "vhh_pvrig", "residue_pair_count")
                    ),
                    "vhh_pvrl2_clash_residue_pairs": str(
                        nested(clashes, "vhh_pvrl2", "residue_pair_count")
                    ),
                    "overlay_rmsd_a": str(nested(score, "overlay", "t_ca_rmsd_a")),
                }
            )
    return output


def validate_and_summarize_result(
    campaign: Campaign,
    row: Mapping[str, str],
    snapshot: FileSnapshot,
) -> dict[str, Any]:
    job_id = str(row["job_id"])
    evidence = parse_json(snapshot, f"{campaign.label}_control_result")
    expected = {
        "job_id": job_id,
        "job_hash": row["job_hash"],
        "entity_type": "control",
        "entity_id": row["entity_id"],
        "dock_conformation": row["conformation"],
        "seed": row["seed"],
        "protocol_core_sha256": campaign.protocol_core_sha256,
    }
    for field, value in expected.items():
        require(
            str(evidence.get(field, "")).lower() == str(value).lower(),
            f"result_identity_mismatch:{campaign.label}:{job_id}:{field}",
        )
    require(str(evidence.get("state", "")).upper() == "SUCCESS", f"control_result_not_success:{campaign.label}:{job_id}")
    try:
        selected_model_count = int(evidence.get("selected_model_count", 0))
    except (TypeError, ValueError) as exc:
        raise BridgeError(f"selected_model_count_invalid:{campaign.label}:{job_id}") from exc
    poses = evidence.get("pose_scores")
    require(
        isinstance(poses, list) and selected_model_count == len(poses),
        f"selected_model_count_mismatch:{campaign.label}:{job_id}",
    )
    try:
        summary = teacher.job_summary(
            job_id, str(row["conformation"]).lower(), pose_rows_from_result(job_id, evidence)
        )
    except teacher.TeacherBuildError as exc:
        raise BridgeError(f"job_summary_failed:{campaign.label}:{job_id}:{exc}") from exc
    return summary


def same_control_identity(
    left: Campaign,
    right: Campaign,
    key: tuple[str, str, int],
) -> tuple[dict[str, str], dict[str, str], str]:
    left_row = left.controls_by_key[key]
    right_row = right.controls_by_key[key]
    for field in MATCHED_IDENTITY_FIELDS:
        require(
            str(left_row[field]) == str(right_row[field]),
            f"cross_campaign_identity_mismatch:{key}:{field}",
        )
    left_receptor = left.receptors[receptor_path(left.root, left_row)]
    right_receptor = right.receptors[receptor_path(right.root, right_row)]
    require(
        left_receptor.sha256 == right_receptor.sha256,
        f"cross_campaign_receptor_mismatch:{key}",
    )
    require(
        left.canonical_config_sha256[key] == right.canonical_config_sha256[key],
        f"cross_campaign_canonical_cfg_mismatch:{key}",
    )
    require(
        left.canonical_restraint_sha256[key]
        == right.canonical_restraint_sha256[key],
        f"cross_campaign_canonical_restraint_mismatch:{key}",
    )
    return left_row, right_row, left_receptor.sha256


def validate_campaign_semantics(left: Campaign, right: Campaign) -> dict[str, Any]:
    require(
        left.control_manifest.sha256 == right.control_manifest.sha256,
        "cross_campaign_control_manifest_mismatch",
    )
    require(
        left.score_pose.sha256 == right.score_pose.sha256,
        "cross_campaign_score_pose_mismatch",
    )
    require(
        left.protocol_semantics_sha256 == right.protocol_semantics_sha256,
        "cross_campaign_protocol_semantics_mismatch",
    )
    require(set(left.controls_by_key) == set(right.controls_by_key), "semantic_control_key_set_mismatch")
    pair_bindings: list[dict[str, Any]] = []
    for entity_id, conformation, seed in sorted(left.controls_by_key):
        key = (entity_id, conformation, seed)
        require(
            left.canonical_config_sha256[key] == right.canonical_config_sha256[key],
            f"cross_campaign_canonical_cfg_mismatch:{key}",
        )
        require(
            left.canonical_restraint_sha256[key]
            == right.canonical_restraint_sha256[key],
            f"cross_campaign_canonical_restraint_mismatch:{key}",
        )
        pair_bindings.append(
            {
                "entity_id": entity_id,
                "conformation": conformation,
                "seed": seed,
                "canonical_cfg_sha256": left.canonical_config_sha256[key],
                "canonical_restraint_sha256": left.canonical_restraint_sha256[key],
            }
        )
    return {
        "status": "PASS_CONTROL_CFG_RESTRAINT_PROTOCOL_SEMANTIC_CLOSURE",
        "paired_control_jobs": len(pair_bindings),
        "raw_cfg_hashes_verified": len(left.configs) + len(right.configs),
        "raw_restraint_hashes_verified": len(left.restraints) + len(right.restraints),
        "protocol_hash_lock_bindings_verified": len(pair_bindings) * 2,
        "canonical_cfg_pairs_equal": len(pair_bindings),
        "canonical_restraint_pairs_equal": len(pair_bindings),
        "canonicalization_policy": "remove_exactly_one_matching_protocol_core_sha256_comment_line_only",
        "pair_binding_sha256": sha256_json(pair_bindings),
    }


def finite_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise BridgeError(f"numeric_value_invalid:{label}:{value!r}") from exc
    require(math.isfinite(number), f"numeric_value_nonfinite:{label}")
    return number


def format_number(value: Any) -> str:
    return format(finite_number(value, "output"), ".12g")


def build_job_row(
    key: tuple[str, str, int],
    left: Campaign,
    right: Campaign,
    left_row: Mapping[str, str],
    right_row: Mapping[str, str],
    receptor_sha256: str,
    left_result: FileSnapshot,
    right_result: FileSnapshot,
    left_summary: Mapping[str, Any],
    right_summary: Mapping[str, Any],
    *,
    schema_version: str,
) -> dict[str, Any]:
    entity_id, conformation, seed = key
    output: dict[str, Any] = {
        "schema_version": schema_version,
        "entity_id": entity_id,
        "conformation": conformation,
        "seed": seed,
        "sequence_sha256": left_row["sequence_sha256"],
        "cdr1_range": left_row["cdr1_range"],
        "cdr2_range": left_row["cdr2_range"],
        "cdr3_range": left_row["cdr3_range"],
        "cdr_residues": left_row["cdr_residues"],
        "receptor_sha256": receptor_sha256,
        "left_campaign": left.label,
        "right_campaign": right.label,
        "left_job_id": left_row["job_id"],
        "right_job_id": right_row["job_id"],
        "left_protocol_core_sha256": left.protocol_core_sha256,
        "right_protocol_core_sha256": right.protocol_core_sha256,
        "left_result_sha256": left_result.sha256,
        "right_result_sha256": right_result.sha256,
        "left_cfg_sha256": left.configs[key].sha256,
        "right_cfg_sha256": right.configs[key].sha256,
        "canonical_cfg_sha256": left.canonical_config_sha256[key],
        "left_restraint_sha256": left.restraints[key].sha256,
        "right_restraint_sha256": right.restraints[key].sha256,
        "canonical_restraint_sha256": left.canonical_restraint_sha256[key],
        "left_protocol_hash": left_row["protocol_hash"],
        "right_protocol_hash": right_row["protocol_hash"],
    }
    for field in SUMMARY_FIELDS:
        left_value = finite_number(left_summary[field], f"left_{field}")
        right_value = finite_number(right_summary[field], f"right_{field}")
        output[f"left_{field}"] = format_number(left_value)
        output[f"right_{field}"] = format_number(right_value)
        output[f"delta_{field}"] = format_number(right_value - left_value)
    output["absolute_delta_job_utility"] = format_number(
        abs(finite_number(right_summary["job_utility"], "right_job_utility") - finite_number(left_summary["job_utility"], "left_job_utility"))
    )
    return output


def replay_job_rows(
    left: Campaign,
    right: Campaign,
    snapshots: Mapping[Path, FileSnapshot],
    *,
    schema_version: str,
) -> list[dict[str, Any]]:
    conformation_order = {value: index for index, value in enumerate(CONFORMATIONS)}
    keys = sorted(
        left.controls_by_key,
        key=lambda key: (key[0], conformation_order[key[1]], key[2]),
    )
    output: list[dict[str, Any]] = []
    for key in keys:
        left_row, right_row, receptor_sha256 = same_control_identity(left, right, key)
        left_result = snapshots[result_path(left, left_row)]
        right_result = snapshots[result_path(right, right_row)]
        left_summary = validate_and_summarize_result(left, left_row, left_result)
        right_summary = validate_and_summarize_result(right, right_row, right_result)
        output.append(
            build_job_row(
                key,
                left,
                right,
                left_row,
                right_row,
                receptor_sha256,
                left_result,
                right_result,
                left_summary,
                right_summary,
                schema_version=schema_version,
            )
        )
    return output


def table_rows_equal(
    observed: Sequence[Mapping[str, Any]], expected: Sequence[Mapping[str, Any]]
) -> bool:
    return [
        {str(key): str(value) for key, value in row.items()} for row in observed
    ] == [{str(key): str(value) for key, value in row.items()} for row in expected]


def median(values: Iterable[float]) -> float:
    materialized = list(values)
    require(bool(materialized), "median_requires_values")
    return float(statistics.median(materialized))


def campaign_entity_summary(rows: list[dict[str, Any]], prefix: str) -> dict[str, float]:
    utilities = {
        conformation: [finite_number(row[f"{prefix}_job_utility"], f"{prefix}_job_utility") for row in rows if row["conformation"] == conformation]
        for conformation in CONFORMATIONS
    }
    require(all(len(values) == len(SEEDS) for values in utilities.values()), "aggregate_seed_matrix_invalid")
    r8 = median(utilities["8x6b"])
    r9 = median(utilities["9e6y"])
    return {
        "R_8X6B": r8,
        "R_9E6Y": r9,
        "R_dual_mean": (r8 + r9) / 2.0,
        "R_dual_min": min(r8, r9),
        "R_dual_gap": abs(r8 - r9),
        "seed_sd_8X6B": statistics.pstdev(utilities["8x6b"]),
        "seed_sd_9E6Y": statistics.pstdev(utilities["9e6y"]),
    }


def build_aggregate_rows(job_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    require(bool(job_rows), "aggregate_rows_empty")
    schema_version = str(job_rows[0].get("schema_version", ""))
    require(
        schema_version in {SCHEMA_VERSION, TEST_SCHEMA_VERSION}
        and all(str(row.get("schema_version", "")) == schema_version for row in job_rows),
        "aggregate_schema_version_invalid_or_mixed",
    )
    by_entity: dict[str, list[dict[str, Any]]] = {}
    for row in job_rows:
        by_entity.setdefault(str(row["entity_id"]), []).append(row)
    output: list[dict[str, Any]] = []
    for entity_id, rows in sorted(by_entity.items()):
        require(len(rows) == len(CONFORMATIONS) * len(SEEDS), f"aggregate_job_count:{entity_id}:{len(rows)}")
        left = campaign_entity_summary(rows, "left")
        right = campaign_entity_summary(rows, "right")
        signed = [finite_number(row["delta_job_utility"], "delta_job_utility") for row in rows]
        absolute = [abs(value) for value in signed]
        aggregate: dict[str, Any] = {
            "schema_version": schema_version,
            "entity_id": entity_id,
            "sequence_sha256": rows[0]["sequence_sha256"],
            "paired_job_count": len(rows),
            "left_campaign": rows[0]["left_campaign"],
            "right_campaign": rows[0]["right_campaign"],
        }
        for field in left:
            aggregate[f"left_{field}"] = format_number(left[field])
            aggregate[f"right_{field}"] = format_number(right[field])
            aggregate[f"delta_{field}"] = format_number(right[field] - left[field])
        aggregate.update(
            mean_signed_job_utility_delta=format_number(statistics.mean(signed)),
            median_signed_job_utility_delta=format_number(statistics.median(signed)),
            mean_absolute_job_utility_delta=format_number(statistics.mean(absolute)),
            maximum_absolute_job_utility_delta=format_number(max(absolute)),
        )
        output.append(aggregate)
    return output


def numeric_pair(
    left: Sequence[float], right: Sequence[float], label: str
) -> tuple[list[float], list[float]]:
    x = [finite_number(value, f"{label}_left") for value in left]
    y = [finite_number(value, f"{label}_right") for value in right]
    require(len(x) == len(y) and len(x) > 1, f"{label}_input_invalid")
    return x, y


def average_ranks(values: Sequence[float]) -> list[float]:
    array = [finite_number(value, "rank") for value in values]
    require(len(array) > 1, "rank_input_invalid")
    order = sorted(range(len(array)), key=lambda index: (array[index], index))
    ranks = [0.0] * len(array)
    start = 0
    while start < len(array):
        end = start + 1
        while end < len(array) and array[order[end]] == array[order[start]]:
            end += 1
        average = (start + 1 + end) / 2.0
        for index in order[start:end]:
            ranks[index] = average
        start = end
    return ranks


def pearson(left: Sequence[float], right: Sequence[float]) -> float:
    x, y = numeric_pair(left, right, "correlation")
    mean_x = statistics.fmean(x)
    mean_y = statistics.fmean(y)
    x_centered = [value - mean_x for value in x]
    y_centered = [value - mean_y for value in y]
    denominator = math.sqrt(
        sum(value * value for value in x_centered)
        * sum(value * value for value in y_centered)
    )
    if denominator == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(x_centered, y_centered)) / denominator


def spearman(left: Sequence[float], right: Sequence[float]) -> float:
    return pearson(average_ranks(left), average_ranks(right))


def lin_concordance_correlation(left: Sequence[float], right: Sequence[float]) -> float:
    x, y = numeric_pair(left, right, "ccc")
    mean_x = statistics.fmean(x)
    mean_y = statistics.fmean(y)
    variance_x = statistics.fmean((value - mean_x) ** 2 for value in x)
    variance_y = statistics.fmean((value - mean_y) ** 2 for value in y)
    covariance = statistics.fmean(
        (a - mean_x) * (b - mean_y) for a, b in zip(x, y)
    )
    denominator = variance_x + variance_y + (mean_x - mean_y) ** 2
    if denominator == 0.0:
        return 0.0
    return 2.0 * covariance / denominator


def percentile(values: Sequence[float], fraction: float) -> float:
    materialized = sorted(finite_number(value, "percentile") for value in values)
    require(bool(materialized) and 0.0 <= fraction <= 1.0, "percentile_input_invalid")
    position = (len(materialized) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return materialized[lower]
    weight = position - lower
    return materialized[lower] * (1.0 - weight) + materialized[upper] * weight


def linear_fit(left: Sequence[float], right: Sequence[float]) -> tuple[float, float]:
    x, y = numeric_pair(left, right, "linear_fit")
    mean_x = statistics.fmean(x)
    mean_y = statistics.fmean(y)
    denominator = sum((value - mean_x) ** 2 for value in x)
    if denominator == 0.0:
        return 0.0, mean_y
    slope = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y)) / denominator
    return slope, mean_y - slope * mean_x


def paired_utilities(
    rows: Sequence[Mapping[str, Any]], conformation: str | None = None
) -> tuple[list[float], list[float]]:
    selected = [
        row for row in rows if conformation is None or row["conformation"] == conformation
    ]
    return (
        [finite_number(row["left_job_utility"], "left_job_utility") for row in selected],
        [finite_number(row["right_job_utility"], "right_job_utility") for row in selected],
    )


def percentile_interval(values: Sequence[float]) -> list[float]:
    require(bool(values), "bootstrap_distribution_empty")
    return [round(percentile(values, 0.025), 9), round(percentile(values, 0.975), 9)]


def evaluate_bridge_metrics(
    rows: list[dict[str, Any]],
    preregistration: Mapping[str, Any],
    *,
    bootstrap_replicates: int,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    bootstrap_spec = preregistration["bootstrap"]
    require(bootstrap_replicates > 0, "bootstrap_replicates_must_be_positive")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["entity_id"]), []).append(row)
    require(len(grouped) == EXPECTED_CONTROL_COUNT or bootstrap_replicates < int(bootstrap_spec["replicates"]), "metric_control_entity_count_invalid")
    require(
        all(len(group) == len(CONFORMATIONS) * len(SEEDS) for group in grouped.values()),
        "metric_cluster_size_invalid",
    )
    left_all, right_all = paired_utilities(rows)
    point_spearman = spearman(left_all, right_all)
    point_ccc = lin_concordance_correlation(left_all, right_all)
    receptor_points = {
        conformation: spearman(*paired_utilities(rows, conformation))
        for conformation in CONFORMATIONS
    }
    rng = random.Random(int(bootstrap_spec["seed"]))
    entities = sorted(grouped)
    bootstrap_spearman: list[float] = []
    bootstrap_ccc: list[float] = []
    bootstrap_receptor: dict[str, list[float]] = {name: [] for name in CONFORMATIONS}
    for _ in range(bootstrap_replicates):
        sampled = rng.choices(entities, k=len(entities))
        replicate = [row for entity_id in sampled for row in grouped[entity_id]]
        left, right = paired_utilities(replicate)
        bootstrap_spearman.append(spearman(left, right))
        bootstrap_ccc.append(lin_concordance_correlation(left, right))
        for conformation in CONFORMATIONS:
            bootstrap_receptor[conformation].append(
                spearman(*paired_utilities(replicate, conformation))
            )
    signed_errors = [right - left for left, right in zip(left_all, right_all)]
    absolute_errors = [abs(value) for value in signed_errors]
    slope, intercept = linear_fit(left_all, right_all)
    mean_difference = statistics.fmean(signed_errors)
    difference_sd = statistics.stdev(signed_errors)
    metrics = {
        "overall_spearman": {
            "point": round(point_spearman, 9),
            "bootstrap_95ci": percentile_interval(bootstrap_spearman),
        },
        "per_receptor_spearman": {
            conformation: {
                "point": round(receptor_points[conformation], 9),
                "bootstrap_95ci": percentile_interval(bootstrap_receptor[conformation]),
            }
            for conformation in CONFORMATIONS
        },
        "overall_lin_concordance_correlation": {
            "point": round(point_ccc, 9),
            "bootstrap_95ci": percentile_interval(bootstrap_ccc),
        },
        "absolute_error": {
            "median": round(statistics.median(absolute_errors), 9),
            "p90": round(percentile(absolute_errors, 0.90), 9),
        },
        "signed_bias": {
            "median": round(statistics.median(signed_errors), 9),
            "absolute_median": round(abs(statistics.median(signed_errors)), 9),
        },
        "report_only": {
            "overall_pearson": round(pearson(left_all, right_all), 9),
            "rmse": round(
                math.sqrt(statistics.fmean(value * value for value in signed_errors)),
                9,
            ),
            "linear_regression_right_on_left": {
                "slope": round(slope, 9),
                "intercept": round(intercept, 9),
            },
            "bland_altman_right_minus_left": {
                "mean_difference": round(mean_difference, 9),
                "sample_sd_difference": round(difference_sd, 9),
                "lower_95_limit": round(mean_difference - 1.96 * difference_sd, 9),
                "upper_95_limit": round(mean_difference + 1.96 * difference_sd, 9),
            },
        },
        "bootstrap": {
            "replicates": bootstrap_replicates,
            "seed": int(bootstrap_spec["seed"]),
            "unit": "entity_id_cluster",
        },
    }
    thresholds = preregistration["hard_gates"]
    overall_spec = thresholds["overall_spearman"]
    receptor_spec = thresholds["per_receptor_spearman"]
    ccc_spec = thresholds["overall_lin_concordance_correlation"]
    error_spec = thresholds["absolute_error"]
    bias_spec = thresholds["signed_bias"]
    gates = {
        "identity": {
            "status": "PASS",
            "paired_jobs": len(rows),
            "duplicate_keys": 0,
            "missing_keys": 0,
            "unexpected_candidate_paths": 0,
            "identity_mismatches": 0,
            "semantic_protocol_mismatches": 0,
        },
        "overall_spearman": {
            "status": "PASS"
            if metrics["overall_spearman"]["point"] >= float(overall_spec["point_minimum"])
            and metrics["overall_spearman"]["bootstrap_95ci"][0]
            >= float(overall_spec["bootstrap_95ci_lower_minimum"])
            else "FAIL",
            "observed": metrics["overall_spearman"],
            "required": overall_spec,
        },
        "per_receptor_spearman": {
            "status": "PASS"
            if all(
                metrics["per_receptor_spearman"][name]["point"]
                >= float(receptor_spec["point_minimum"])
                and metrics["per_receptor_spearman"][name]["bootstrap_95ci"][0]
                >= float(receptor_spec["bootstrap_95ci_lower_minimum"])
                for name in CONFORMATIONS
            )
            else "FAIL",
            "observed": metrics["per_receptor_spearman"],
            "required": receptor_spec,
        },
        "overall_lin_concordance_correlation": {
            "status": "PASS"
            if metrics["overall_lin_concordance_correlation"]["point"]
            >= float(ccc_spec["point_minimum"])
            and metrics["overall_lin_concordance_correlation"]["bootstrap_95ci"][0]
            >= float(ccc_spec["bootstrap_95ci_lower_minimum"])
            else "FAIL",
            "observed": metrics["overall_lin_concordance_correlation"],
            "required": ccc_spec,
        },
        "absolute_error": {
            "status": "PASS"
            if metrics["absolute_error"]["median"] <= float(error_spec["median_maximum"])
            and metrics["absolute_error"]["p90"] <= float(error_spec["p90_maximum"])
            else "FAIL",
            "observed": metrics["absolute_error"],
            "required": error_spec,
        },
        "signed_bias": {
            "status": "PASS"
            if metrics["signed_bias"]["absolute_median"]
            <= float(bias_spec["absolute_median_maximum"])
            else "FAIL",
            "observed": metrics["signed_bias"],
            "required": bias_spec,
        },
    }
    passed = all(payload["status"] == "PASS" for payload in gates.values())
    decision_policy = preregistration["decision_policy"]
    decision = str(decision_policy["pass"] if passed else decision_policy["fail"])
    return metrics, gates, decision


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    require(bool(rows), f"cannot_write_empty_tsv:{path.name}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def current_hashes(snapshots: Mapping[Path, FileSnapshot]) -> dict[str, str]:
    output: dict[str, str] = {}
    for path, snapshot in sorted(snapshots.items(), key=lambda item: str(item[0])):
        current = snapshot_file(path, "frozen_bridge_input")
        require(
            current.sha256 == snapshot.sha256,
            f"snapshot_changed_since_capture:{path}",
        )
        output[str(path)] = snapshot.sha256
    return output


def validate_output_set(out_dir: Path, *, exact: bool) -> set[str]:
    absolute = lexical_absolute(out_dir)
    if not os.path.lexists(absolute):
        require(not exact, f"output_directory_missing:{absolute}")
        return set()
    require_real_directory(absolute, "bridge_output_directory")
    with os.scandir(absolute) as iterator:
        entries = list(iterator)
    names = {entry.name for entry in entries}
    expected = set(OUTPUT_FILENAMES)
    unexpected = sorted(names - expected)
    require(not unexpected, f"unexpected_output_files:{','.join(unexpected)}")
    if exact:
        missing = sorted(expected - names)
        require(not missing, f"required_output_files_missing:{','.join(missing)}")
    for entry in entries:
        require(
            entry.is_file(follow_symlinks=False),
            f"output_not_regular_or_symlink_forbidden:{entry.name}",
        )
    return names


@contextmanager
def publication_lock(out_dir: Path):
    import fcntl

    out_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = out_dir.parent / f".{out_dir.name}.control-bridge.lock"
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BridgeError("control_bridge_already_running") from exc
        yield


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def expected_input_snapshots(
    left: Campaign,
    right: Campaign,
    preregistration: FileSnapshot,
    implementation_freeze: ImplementationFreeze,
    deployment_trust_root: DeploymentTrustRoot | None,
) -> dict[Path, FileSnapshot]:
    snapshots = {
        preregistration.path: preregistration,
        implementation_freeze.manifest.path: implementation_freeze.manifest,
        implementation_freeze.sha256_record.path: implementation_freeze.sha256_record,
        left.manifest.path: left.manifest,
        left.protocol_lock.path: left.protocol_lock,
        left.protocol_spec.path: left.protocol_spec,
        left.control_manifest.path: left.control_manifest,
        left.score_pose.path: left.score_pose,
        right.manifest.path: right.manifest,
        right.protocol_lock.path: right.protocol_lock,
        right.protocol_spec.path: right.protocol_spec,
        right.control_manifest.path: right.control_manifest,
        right.score_pose.path: right.score_pose,
        Path(__file__).resolve(): snapshot_file(Path(__file__), "bridge_implementation"),
        TEST_IMPLEMENTATION.resolve(): snapshot_file(
            TEST_IMPLEMENTATION, "bridge_test_implementation"
        ),
        Path(teacher.__file__).resolve(): snapshot_file(Path(teacher.__file__), "teacher_utility_implementation"),
    }
    snapshots.update(left.receptors)
    snapshots.update(right.receptors)
    snapshots.update({snapshot.path: snapshot for snapshot in left.configs.values()})
    snapshots.update({snapshot.path: snapshot for snapshot in right.configs.values()})
    snapshots.update({snapshot.path: snapshot for snapshot in left.restraints.values()})
    snapshots.update({snapshot.path: snapshot for snapshot in right.restraints.values()})
    if deployment_trust_root is not None:
        snapshots[deployment_trust_root.manifest.path] = deployment_trust_root.manifest
        snapshots.update(deployment_trust_root.bindings)
    for campaign in (left, right):
        for row in campaign.controls_by_key.values():
            snapshot = snapshot_file_at(
                campaign.root,
                result_relative_path(row),
                f"{campaign.label}_control_result",
            )
            snapshots[snapshot.path] = snapshot
    return snapshots


def read_output_tsv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    return parse_tsv(snapshot_file(path, "bridge_output"), "bridge_output")


def verify_receipt(
    receipt_path: Path,
    left_root: Path,
    right_root: Path,
    *,
    left_label: str,
    right_label: str,
    expected_control_count: int,
    expected_job_count: int,
    test_only: bool,
    preregistration_path: Path = DEFAULT_PREREGISTRATION,
) -> dict[str, Any]:
    if not test_only:
        require(expected_control_count == EXPECTED_CONTROL_COUNT, "production_control_count_override_forbidden")
        require(expected_job_count == EXPECTED_JOB_COUNT, "production_job_count_override_forbidden")
    root = lexical_absolute(receipt_path).parent
    validate_output_set(root, exact=True)
    receipt_snapshot = snapshot_file(receipt_path, "bridge_receipt")
    require(
        receipt_snapshot.path == root / OUTPUT_FILENAMES[-1],
        "receipt_filename_or_location_invalid",
    )
    receipt = parse_json(receipt_snapshot, "bridge_receipt")
    schema_version, status, verified_status = output_identity(test_only)
    require(
        receipt.get("schema_version") == schema_version, "receipt_schema_invalid"
    )
    require(receipt.get("status") == status, "receipt_status_invalid")
    expected_mode = "test_fixture" if test_only else "production"
    require(receipt.get("execution_mode") == expected_mode, "receipt_execution_mode_invalid")
    require(int(receipt.get("job_row_count", -1)) == expected_job_count, "receipt_job_count_invalid")
    require(
        int(receipt.get("control_row_count", -1)) == expected_control_count,
        "receipt_control_count_invalid",
    )
    require(receipt.get("candidate_result_paths_opened") == 0, "receipt_candidate_path_contract_invalid")
    preregistration_snapshot, preregistration = load_preregistration(
        preregistration_path, production=not test_only
    )
    if test_only:
        reject_production_paths_in_test_mode(
            left_root, right_root, root, preregistration
        )
    deployment_trust_root = (
        None
        if test_only
        else load_deployment_trust_root(preregistration, production=True)
    )
    implementation_freeze = load_implementation_freeze(
        preregistration_snapshot, preregistration, production=not test_only
    )
    require(
        receipt.get("preregistration_sha256") == preregistration_snapshot.sha256,
        "receipt_preregistration_hash_invalid",
    )
    require(
        receipt.get("implementation_freeze_sha256")
        == implementation_freeze.manifest.sha256,
        "receipt_implementation_freeze_hash_invalid",
    )
    expected_trust_root_sha256 = (
        "" if deployment_trust_root is None else deployment_trust_root.manifest.sha256
    )
    require(
        receipt.get("deployment_trust_root_sha256") == expected_trust_root_sha256,
        "receipt_deployment_trust_root_hash_invalid",
    )
    if not test_only:
        require(left_label == "legacy_v4_c", "production_left_campaign_label_invalid")
        require(right_label == "primary_v4_d", "production_right_campaign_label_invalid")
    campaign_specs = preregistration.get("campaigns") or {}
    left = load_campaign(
        left_root,
        left_label,
        expected_control_count=expected_control_count,
        expected_job_count=expected_job_count,
        production_spec=campaign_specs.get(left_label) if not test_only else None,
    )
    right = load_campaign(
        right_root,
        right_label,
        expected_control_count=expected_control_count,
        expected_job_count=expected_job_count,
        production_spec=campaign_specs.get(right_label) if not test_only else None,
    )
    require(set(left.controls_by_key) == set(right.controls_by_key), "receipt_control_key_set_mismatch")
    semantic_closure = validate_campaign_semantics(left, right)
    snapshots = expected_input_snapshots(
        left,
        right,
        preregistration_snapshot,
        implementation_freeze,
        deployment_trust_root,
    )
    observed_hashes = {str(path): snapshot.sha256 for path, snapshot in snapshots.items()}
    require(receipt.get("input_hashes") == observed_hashes, "receipt_input_hash_set_or_value_mismatch")
    outputs = receipt.get("outputs")
    require(isinstance(outputs, Mapping), "receipt_outputs_missing")
    expected_paths = {
        "job_bridge": root / OUTPUT_FILENAMES[0],
        "control_aggregate": root / OUTPUT_FILENAMES[1],
        "audit": root / OUTPUT_FILENAMES[2],
    }
    require(set(outputs) == set(expected_paths), "receipt_output_set_invalid")
    output_snapshots: dict[Path, FileSnapshot] = {}
    for name, path in expected_paths.items():
        payload = outputs.get(name)
        require(isinstance(payload, Mapping), f"receipt_output_invalid:{name}")
        require(
            lexical_absolute(Path(str(payload.get("path", "")))) == path,
            f"receipt_output_path_invalid:{name}",
        )
        output_snapshot = snapshot_file(path, name)
        require(
            output_snapshot.sha256 == payload.get("sha256"),
            f"receipt_output_hash_invalid:{name}",
        )
        output_snapshots[path] = output_snapshot
    job_rows, _ = parse_tsv(
        output_snapshots[expected_paths["job_bridge"]], "bridge_output"
    )
    aggregate_rows, _ = parse_tsv(
        output_snapshots[expected_paths["control_aggregate"]], "bridge_output"
    )
    require(len(job_rows) == expected_job_count, "verified_job_count_invalid")
    require(len(aggregate_rows) == expected_control_count, "verified_control_count_invalid")
    require(
        all(row.get("schema_version") == schema_version for row in job_rows),
        "verified_job_schema_invalid",
    )
    require(
        all(row.get("schema_version") == schema_version for row in aggregate_rows),
        "verified_control_schema_invalid",
    )
    require(
        {(row["entity_id"], row["conformation"], int(row["seed"])) for row in job_rows}
        == set(left.controls_by_key),
        "verified_job_keys_invalid",
    )
    audit = parse_json(output_snapshots[expected_paths["audit"]], "bridge_audit")
    require(audit.get("schema_version") == schema_version, "audit_schema_invalid")
    require(audit.get("status") == status, "audit_status_invalid")
    require(audit.get("candidate_result_paths_opened") == 0, "audit_candidate_path_contract_invalid")
    require(
        audit.get("semantic_closure") == semantic_closure,
        "audit_semantic_closure_replay_mismatch",
    )
    require(
        receipt.get("semantic_closure_sha256") == sha256_json(semantic_closure),
        "receipt_semantic_closure_hash_invalid",
    )
    replayed_job_rows = replay_job_rows(
        left, right, snapshots, schema_version=schema_version
    )
    require(table_rows_equal(job_rows, replayed_job_rows), "verified_job_bridge_replay_mismatch")
    replayed_aggregate_rows = build_aggregate_rows(replayed_job_rows)
    require(
        table_rows_equal(aggregate_rows, replayed_aggregate_rows),
        "verified_control_aggregate_replay_mismatch",
    )
    try:
        audit_replicates = int((audit.get("metrics") or {})["bootstrap"]["replicates"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BridgeError("audit_bootstrap_replicates_invalid") from exc
    if not test_only:
        require(
            audit_replicates == int(preregistration["bootstrap"]["replicates"]),
            "production_audit_bootstrap_replicates_invalid",
        )
    replayed_metrics, replayed_gates, replayed_decision = evaluate_bridge_metrics(
        replayed_job_rows,
        preregistration,
        bootstrap_replicates=audit_replicates,
    )
    require(audit.get("metrics") == replayed_metrics, "audit_metrics_replay_mismatch")
    require(audit.get("hard_gates") == replayed_gates, "audit_hard_gates_replay_mismatch")
    require(audit.get("decision") == replayed_decision, "audit_decision_replay_mismatch")
    decision_policy = preregistration["decision_policy"]
    require(
        audit.get("decision") in {decision_policy["pass"], decision_policy["fail"]},
        "audit_decision_invalid",
    )
    require(receipt.get("decision") == audit.get("decision"), "receipt_audit_decision_mismatch")
    require(
        receipt.get("metrics_sha256") == sha256_json(audit.get("metrics")),
        "receipt_metrics_hash_invalid",
    )
    require(
        receipt.get("hard_gates_sha256") == sha256_json(audit.get("hard_gates")),
        "receipt_hard_gates_hash_invalid",
    )
    gate_statuses = {
        str(name): str(payload.get("status"))
        for name, payload in (audit.get("hard_gates") or {}).items()
        if isinstance(payload, Mapping)
    }
    require(set(gate_statuses) == set(preregistration["hard_gates"]), "audit_hard_gate_set_invalid")
    expected_decision = (
        decision_policy["pass"]
        if all(status == "PASS" for status in gate_statuses.values())
        else decision_policy["fail"]
    )
    require(audit.get("decision") == expected_decision, "audit_hard_gate_decision_mismatch")
    current_hashes(snapshots)
    current_hashes(output_snapshots)
    validate_output_set(root, exact=True)
    final_receipt_snapshot = snapshot_file(receipt_snapshot.path, "bridge_receipt_final")
    require(
        final_receipt_snapshot.sha256 == receipt_snapshot.sha256,
        "receipt_changed_during_verification",
    )
    return {
        "schema_version": schema_version,
        "status": verified_status,
        "job_row_count": len(job_rows),
        "control_row_count": len(aggregate_rows),
        "receipt_sha256": receipt_snapshot.sha256,
        "candidate_result_paths_opened": 0,
        "decision": audit["decision"],
    }


def build_bridge(
    left_root: Path,
    right_root: Path,
    out_dir: Path,
    *,
    left_label: str = "legacy_v4_c",
    right_label: str = "primary_v4_d",
    expected_control_count: int = EXPECTED_CONTROL_COUNT,
    expected_job_count: int = EXPECTED_JOB_COUNT,
    test_only: bool = False,
    preregistration_path: Path = DEFAULT_PREREGISTRATION,
    bootstrap_replicates: int | None = None,
) -> dict[str, Any]:
    if not test_only:
        require(expected_control_count == EXPECTED_CONTROL_COUNT, "production_control_count_override_forbidden")
        require(expected_job_count == EXPECTED_JOB_COUNT, "production_job_count_override_forbidden")
        require(left_label == "legacy_v4_c", "production_left_campaign_label_invalid")
        require(right_label == "primary_v4_d", "production_right_campaign_label_invalid")
    require(left_label != right_label, "campaign_labels_must_differ")
    preregistration_snapshot, preregistration = load_preregistration(
        preregistration_path, production=not test_only
    )
    if test_only:
        reject_production_paths_in_test_mode(
            left_root, right_root, out_dir, preregistration
        )
    schema_version, status, _verified_status = output_identity(test_only)
    deployment_trust_root = (
        None
        if test_only
        else load_deployment_trust_root(preregistration, production=True)
    )
    implementation_freeze = load_implementation_freeze(
        preregistration_snapshot, preregistration, production=not test_only
    )
    preregistered_replicates = int(preregistration["bootstrap"]["replicates"])
    if bootstrap_replicates is None:
        bootstrap_replicates = preregistered_replicates
    if not test_only:
        require(
            bootstrap_replicates == preregistered_replicates,
            "production_bootstrap_replicates_override_forbidden",
        )
    campaign_specs = preregistration.get("campaigns") or {}
    resolved_out = lexical_absolute(out_dir)
    final_paths = {name: resolved_out / name for name in OUTPUT_FILENAMES}
    with publication_lock(resolved_out):
        validate_output_set(resolved_out, exact=False)
        if os.path.lexists(final_paths[OUTPUT_FILENAMES[-1]]):
            validate_output_set(resolved_out, exact=True)
            return verify_receipt(
                final_paths[OUTPUT_FILENAMES[-1]],
                left_root,
                right_root,
                left_label=left_label,
                right_label=right_label,
                expected_control_count=expected_control_count,
                expected_job_count=expected_job_count,
                test_only=test_only,
                preregistration_path=preregistration_path,
            )
        left = load_campaign(
            left_root,
            left_label,
            expected_control_count=expected_control_count,
            expected_job_count=expected_job_count,
            production_spec=campaign_specs.get(left_label) if not test_only else None,
        )
        right = load_campaign(
            right_root,
            right_label,
            expected_control_count=expected_control_count,
            expected_job_count=expected_job_count,
            production_spec=campaign_specs.get(right_label) if not test_only else None,
        )
        require(set(left.controls_by_key) == set(right.controls_by_key), "control_key_set_mismatch")
        semantic_closure = validate_campaign_semantics(left, right)
        snapshots = expected_input_snapshots(
            left,
            right,
            preregistration_snapshot,
            implementation_freeze,
            deployment_trust_root,
        )
        job_rows = replay_job_rows(
            left, right, snapshots, schema_version=schema_version
        )
        require(len(job_rows) == expected_job_count, "built_job_row_count_invalid")
        aggregate_rows = build_aggregate_rows(job_rows)
        require(len(aggregate_rows) == expected_control_count, "built_control_row_count_invalid")
        metrics, hard_gates, decision = evaluate_bridge_metrics(
            job_rows,
            preregistration,
            bootstrap_replicates=bootstrap_replicates,
        )
        input_hashes = current_hashes(snapshots)
        resolved_out.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{resolved_out.name}.stage.", dir=resolved_out.parent)
        )
        try:
            job_path = staging / OUTPUT_FILENAMES[0]
            aggregate_path = staging / OUTPUT_FILENAMES[1]
            audit_path = staging / OUTPUT_FILENAMES[2]
            receipt_path = staging / OUTPUT_FILENAMES[3]
            write_tsv(job_path, job_rows)
            write_tsv(aggregate_path, aggregate_rows)
            audit = {
                "schema_version": schema_version,
                "status": status,
                "execution_mode": "test_fixture" if test_only else "production",
                "job_row_count": len(job_rows),
                "control_row_count": len(aggregate_rows),
                "preregistration": {
                    "path": str(preregistration_snapshot.path),
                    "sha256": preregistration_snapshot.sha256,
                    "schema_version": preregistration["schema_version"],
                },
                "implementation_freeze": {
                    "path": str(implementation_freeze.manifest.path),
                    "sha256": implementation_freeze.manifest.sha256,
                    "sha256_record_path": str(
                        implementation_freeze.sha256_record.path
                    ),
                    "sha256_record_sha256": implementation_freeze.sha256_record.sha256,
                    "schema_version": implementation_freeze.payload["schema_version"],
                },
                "deployment_trust_root": {
                    "required": not test_only,
                    "path": ""
                    if deployment_trust_root is None
                    else str(deployment_trust_root.manifest.path),
                    "sha256": ""
                    if deployment_trust_root is None
                    else deployment_trust_root.manifest.sha256,
                    "binding_count": 0
                    if deployment_trust_root is None
                    else len(deployment_trust_root.bindings),
                },
                "campaigns": {
                    "left": {
                        "label": left.label,
                        "root": str(left.root),
                        "manifest_row_count": left.manifest_row_count,
                        "control_job_count": len(left.controls_by_key),
                        "candidate_manifest_rows_excluded_before_result_paths": left.excluded_candidate_row_count,
                        "protocol_core_sha256": left.protocol_core_sha256,
                        "protocol_semantics_sha256": left.protocol_semantics_sha256,
                        "score_pose_sha256": left.score_pose.sha256,
                    },
                    "right": {
                        "label": right.label,
                        "root": str(right.root),
                        "manifest_row_count": right.manifest_row_count,
                        "control_job_count": len(right.controls_by_key),
                        "candidate_manifest_rows_excluded_before_result_paths": right.excluded_candidate_row_count,
                        "protocol_core_sha256": right.protocol_core_sha256,
                        "protocol_semantics_sha256": right.protocol_semantics_sha256,
                        "score_pose_sha256": right.score_pose.sha256,
                    },
                },
                "pairing": {
                    "key": ["entity_id", "conformation", "seed"],
                    "conformations": list(CONFORMATIONS),
                    "seeds": list(SEEDS),
                    "matched_identity_fields": list(MATCHED_IDENTITY_FIELDS),
                    "receptor_validation": "resolved_file_sha256_equality",
                    "semantic_protocol_validation": "protocol_spec_subset_plus_raw_cfg_restraint_manifest_hashes_protocol_lock_binding_and_cross_campaign_canonical_equality",
                },
                "semantic_closure": semantic_closure,
                "utility": {
                    "implementation": str(Path(teacher.__file__).resolve()),
                    "implementation_sha256": snapshots[Path(teacher.__file__).resolve()].sha256,
                    "function": "prepare_phase2_v4_d_open_teacher.job_summary",
                    "thresholds_added_or_tuned": 0,
                },
                "metrics": metrics,
                "hard_gates": hard_gates,
                "decision": decision,
                "implementation": {
                    "path": str(Path(__file__).resolve()),
                    "sha256": snapshots[Path(__file__).resolve()].sha256,
                    "test_path": str(TEST_IMPLEMENTATION.resolve()),
                    "test_sha256": snapshots[TEST_IMPLEMENTATION.resolve()].sha256,
                },
                "input_hashes_sha256": sha256_json(input_hashes),
                "control_result_paths_opened": expected_job_count * 2,
                "candidate_result_paths_opened": 0,
                "outputs": {
                    "job_bridge_sha256": snapshot_file(job_path, "job_bridge").sha256,
                    "control_aggregate_sha256": snapshot_file(
                        aggregate_path, "control_aggregate"
                    ).sha256,
                },
                "claim_boundary": CLAIM_BOUNDARY,
            }
            write_json(audit_path, audit)
            current_hashes(snapshots)
            receipt = {
                "schema_version": schema_version,
                "status": status,
                "execution_mode": "test_fixture" if test_only else "production",
                "job_row_count": len(job_rows),
                "control_row_count": len(aggregate_rows),
                "candidate_result_paths_opened": 0,
                "preregistration_sha256": preregistration_snapshot.sha256,
                "implementation_freeze_sha256": implementation_freeze.manifest.sha256,
                "deployment_trust_root_sha256": ""
                if deployment_trust_root is None
                else deployment_trust_root.manifest.sha256,
                "semantic_closure_sha256": sha256_json(semantic_closure),
                "metrics_sha256": sha256_json(metrics),
                "hard_gates_sha256": sha256_json(hard_gates),
                "decision": decision,
                "input_hashes": input_hashes,
                "outputs": {
                    "job_bridge": {
                        "path": str(final_paths[OUTPUT_FILENAMES[0]]),
                        "sha256": snapshot_file(job_path, "job_bridge").sha256,
                    },
                    "control_aggregate": {
                        "path": str(final_paths[OUTPUT_FILENAMES[1]]),
                        "sha256": snapshot_file(aggregate_path, "control_aggregate").sha256,
                    },
                    "audit": {
                        "path": str(final_paths[OUTPUT_FILENAMES[2]]),
                        "sha256": snapshot_file(audit_path, "bridge_audit").sha256,
                    },
                },
                "publication": {
                    "policy": "stage_then_atomic_replace_receipt_last",
                    "receipt_published_last": True,
                },
                "claim_boundary": CLAIM_BOUNDARY,
            }
            write_json(receipt_path, receipt)
            validate_output_set(staging, exact=True)
            current_hashes(snapshots)
            resolved_out.mkdir(parents=True, exist_ok=True)
            require_real_directory(resolved_out, "bridge_output_directory")
            final_paths[OUTPUT_FILENAMES[-1]].unlink(missing_ok=True)
            for name in OUTPUT_FILENAMES[:-1]:
                os.replace(staging / name, final_paths[name])
            os.replace(receipt_path, final_paths[OUTPUT_FILENAMES[-1]])
            validate_output_set(resolved_out, exact=True)
            fsync_directory(resolved_out)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return verify_receipt(
        final_paths[OUTPUT_FILENAMES[-1]],
        left_root,
        right_root,
        left_label=left_label,
        right_label=right_label,
        expected_control_count=expected_control_count,
        expected_job_count=expected_job_count,
        test_only=test_only,
        preregistration_path=preregistration_path,
    )


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--left-root", type=Path, required=True)
    parser.add_argument("--right-root", type=Path, required=True)
    parser.add_argument("--left-label", default="legacy_v4_c")
    parser.add_argument("--right-label", default="primary_v4_d")
    parser.add_argument("--expected-controls", type=int, default=EXPECTED_CONTROL_COUNT)
    parser.add_argument("--expected-jobs", type=int, default=EXPECTED_JOB_COUNT)
    parser.add_argument(
        "--preregistration", type=Path, default=DEFAULT_PREREGISTRATION
    )
    parser.add_argument("--test-only-allow-small-fixture", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    verify = commands.add_parser("verify-receipt")
    add_common_arguments(build)
    add_common_arguments(verify)
    build.add_argument("--out-dir", type=Path, required=True)
    build.add_argument("--test-only-bootstrap-replicates", type=int)
    verify.add_argument("--receipt", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_bridge(
                args.left_root,
                args.right_root,
                args.out_dir,
                left_label=args.left_label,
                right_label=args.right_label,
                expected_control_count=args.expected_controls,
                expected_job_count=args.expected_jobs,
                test_only=args.test_only_allow_small_fixture,
                preregistration_path=args.preregistration,
                bootstrap_replicates=args.test_only_bootstrap_replicates,
            )
        else:
            result = verify_receipt(
                args.receipt,
                args.left_root,
                args.right_root,
                left_label=args.left_label,
                right_label=args.right_label,
                expected_control_count=args.expected_controls,
                expected_job_count=args.expected_jobs,
                test_only=args.test_only_allow_small_fixture,
                preregistration_path=args.preregistration,
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (BridgeError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAILED_V4_D_CROSS_CAMPAIGN_CONTROL_BRIDGE", "reason": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
