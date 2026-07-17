#!/usr/bin/env python3
"""Build the frozen DEV1 V1.2 open258 computational-geometry teacher.

V1.2 preserves the V1.1 single terminal-failure projection and drops a
complete two-reference (job_id, model) pair when its job-native reference has
overlay.t_ca_rmsd_a > 1.0.  Filtering occurs before the unchanged V1 helper
classifies, sorts, weights, or aggregates poses.  Formal test32 stays sealed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import stat
import statistics
import sys
import tarfile
import types
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "phase2_v4_d_dev1_open258_v1_2"
TRACK_ID = "V4-D-DEV1-V1.2"
AUDIT_STATUS = "RELEASED_DEV_ONLY_V1_2_POSE_VALIDITY_FILTER_TEST32_SEALED"
RELEASE_NAME = "OPEN_TRAIN_226_PLUS_OPEN_DEVELOPMENT_32_DEV_ONLY_V1_2"
REMOTE_READY_STATUS = "DEV1_V1_2_RELEASE_READY_TEST32_SEALED"
REMOTE_ROOT = "/data/qlyu/projects/pvrig_v4_d_dev1_open258_v1_2_20260717"
CLAIM_BOUNDARY = (
    "Post-hoc development-only sequence-to-independent-dual-docking continuous "
    "computational geometry evidence; not a V4-D pass, formal test, Docking Gold, "
    "binding, affinity, competition, experimental blocking, or final submission authority."
)

EXPECTED_PREREG_SHA256 = "cbc70313d47ff5f0fc99476a5a0b108abc0e94e4ecaf05d53663e1b06adf62a1"
EXPECTED_DIAGNOSTIC_SHA256 = "ef31a254de83dec7aa0f073154c8a7176eaa43c406df0aec8c9fd65df448aead"
EXPECTED_DIAGNOSTIC_RECEIPT_SHA256 = "1a99a0a498bb44c7d64b379a553a1d117b4ad9212e6d204fa73fb0f943c58f2f"
EXPECTED_CANONICAL_CLARIFICATION_SHA256 = "1fb8f1bdfdf8f8869cc1c80a477a1e1f4f74246c555925be4fa1c1ebc380b918"
EXPECTED_INVALID_IDENTITY_SHA256 = "941d5010190c6576ee0961681227d5b9b1ce9a719cc63ae5c25a45b0f8de9c1f"
EXPECTED_FALLBACK_EVIDENCE_SHA256 = "36c7e11e3a727512d04a8797122efedc10b277bf58b5b997c09315209fdc6481"
EXPECTED_V1_FAILURE_RECEIPT_SHA256 = "247b6ec684a60ada85fa38834aa176e3f6a797a379938a5dabd5755bdd041720"
EXPECTED_V1_1_FAILURE_RECEIPT_SHA256 = "7dbf808d31985cd7555ebadec0c294583b95fc32cb76b26d63b6b06adc74bea7"
EXPECTED_V1_BUILDER_SHA256 = "04fd7addb8f1bc16f0cd3c0d113d9cbeb2cf23a25b5a39fe0113bfd2cf65d276"
EXPECTED_V1_1_BUILDER_SHA256 = "cadc38165b272fde783f6afcf936f3c2c14cd3f57c43a6cb16148cc7413a9e82"
EXPECTED_V1_HELPER_SHA256 = "8adb3c4e1de37bbaaf469dfb967176d2c49d40f353e21a3f028baa20ea8e4145"
EXPECTED_SPLIT_MANIFEST_SHA256 = "c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd"
EXPECTED_JOB_MANIFEST_SHA256 = "96fec07a5535615f50bff40ac48bb323a94213e06a7b12726ae5b4b2d1161737"
EXPECTED_JOB_RESULTS_SHA256 = "30c4227e15f6b049a9d9e9241ca34df30d38b247d14081b4ce7d3387fa2f3f25"
EXPECTED_POSE_SCORES_SHA256 = "7a2737160051c8fca8836b4086507e8f70d83cd692f87ffc17eaff8279c32681"
EXPECTED_EVALUATOR_SHA256 = "289542c58cfe72c380143a910b3adb75ba4e12f65899f71907a044314bedb674"
EXPECTED_PROTOCOL_CORE_LOCK_SHA256 = "767117dc2c506cfdfc83fce8e12931514d268941348d69a9abbda5a6500bdd24"
EXPECTED_PROTOCOL_LOCK_SHA256 = "56ef539cb54a1aba8e665ec5d62b3653088e2289e371d8fa5bbadbc725c1d574"
EXPECTED_STABILITY_SPEC_SHA256 = "fb01cdaa5939f2846b16e4e02a09903417cd6cea04d42350c4ed57f9ae7eb774"
EXPECTED_GENERIC_PRIOR_SHA256 = "21b4c6a38056d6777de5b5efbfcd5887b45098c637cab61489072d1e6e7783cd"

EXPECTED_OPEN_COUNTS = {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32}
EXPECTED_OPEN_ROWS = 258
EXPECTED_OPEN_JOBS = 1548
EXPECTED_RAW_OPEN_JOBS = 1547
EXPECTED_COMPLETE_PAIR_COUNT = 14490
EXPECTED_FILTERED_COMPLETE_PAIR_COUNT = 14391
EXPECTED_INVALID_PAIR_COUNT = 99
EXPECTED_AFFECTED_JOB_COUNT = 98
EXPECTED_AFFECTED_CANDIDATE_COUNT = 83
EXPECTED_INVALID_BY_CONFORMATION = {"8x6b": 89, "9e6y": 10}
EXPECTED_MIN_AFFECTED_RETAINED_PAIRS = 5
MIN_RETAINED_COMPLETE_PAIRS = 4
OVERLAY_RMSD_LIMIT_A = 1.0
EXPECTED_RAW_RESULT_SHA256_CHAIN = "202d06e1ee689167427abdebcb85705e20ee867aacda31bef5211a35d44d9301"
CONFORMATIONS = ("8x6b", "9e6y")
SEALED_SPLIT = "PROSPECTIVE_COMPUTATIONAL_TEST"
EXPECTED_SEALED_ROWS = 32
SOURCE_FAILED_GATE = "candidate_threshold_sensitivity"
PRIMARY_TARGET = "R_dual_min"
FROZEN_FAILED_JOB_ID = "CANDIDATE_RFV1__PLDNANO_VHH_00322__A_CENTER__H3__B02__M00_8x6b_s3253_447e4cf0dc26"

OUTPUT_BASENAME = "v4d_dev1_open258_continuous_geometry_v1_2.tsv"
AUDIT_BASENAME = OUTPUT_BASENAME + ".audit.json"
SOURCE_RECEIPT_BASENAME = "v4d_dev1_source_failure_receipt_v1_2.json"
RELEASE_RECEIPT_BASENAME = "v4d_dev1_release_receipt_v1_2.json"
CHECKSUM_BASENAME = "SHA256SUMS"
ARCHIVE_BASENAME = "v4d_dev1_open258_delivery_v1_2.tar.gz"
ARCHIVE_SHA_BASENAME = ARCHIVE_BASENAME + ".sha256"


class Dev1V12BuildError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Dev1V12BuildError(message)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_bound_bytes(path: Path, label: str, expected_sha256: str) -> bytes:
    """Read one immutable regular-file snapshot; symlinks and read-time drift fail."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise Dev1V12BuildError(f"unable_to_open_bound_file:{label}:{path}") from exc
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode), f"not_regular_or_symlink:{label}:{path}")
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
        require(identity(before) == identity(after), f"bound_file_changed_during_read:{label}")
        require(len(raw) == before.st_size, f"bound_file_size_changed_during_read:{label}")
        require(sha256_bytes(raw) == expected_sha256, f"{label}_sha256_mismatch")
        return raw
    finally:
        os.close(fd)


def strict_json_bytes(raw: bytes, label: str) -> Any:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in output, f"duplicate_json_key:{label}:{key}")
            output[key] = value
        return output

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Dev1V12BuildError(f"invalid_json:{label}:{exc}") from exc


def read_bound_json(path: Path, label: str, expected_sha256: str) -> Any:
    return strict_json_bytes(read_bound_bytes(path, label, expected_sha256), label)


def read_bound_table(
    path: Path, label: str, expected_sha256: str, *, delimiter: str
) -> list[dict[str, str]]:
    raw = read_bound_bytes(path, label, expected_sha256)
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter=delimiter)
        require(reader.fieldnames is not None, f"{label}_header_missing")
        require(len(reader.fieldnames) == len(set(reader.fieldnames)), f"{label}_duplicate_header")
        return list(reader)
    except UnicodeDecodeError as exc:
        raise Dev1V12BuildError(f"{label}_utf8_invalid") from exc


def load_bound_module(path: Path, label: str, expected_sha256: str) -> Any:
    raw = read_bound_bytes(path, label, expected_sha256)
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Dev1V12BuildError(f"{label}_utf8_invalid") from exc
    name = f"dev1_v12_{label}"
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def _read_fd_snapshot(fd: int, label: str) -> bytes:
    before = os.fstat(fd)
    require(stat.S_ISREG(before.st_mode), f"not_regular_or_symlink:{label}")
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
    require(identity(before) == identity(after), f"raw_file_changed_during_read:{label}")
    require(len(raw) == before.st_size, f"raw_file_size_changed_during_read:{label}")
    return raw


def collect_recovery_results_secure(
    helper: Any,
    v11: Any,
    results_root: Path,
    selected_jobs: Sequence[Mapping[str, str]],
    job_results: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    """Open exactly 1547 preselected raw results through O_NOFOLLOW dirfds."""
    raw_jobs, failure = v11.partition_open_jobs_for_recovery(selected_jobs)
    require(len(raw_jobs) == EXPECTED_RAW_OPEN_JOBS, "raw_open_job_count_not_1547")
    root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        root_fd = os.open(results_root, root_flags)
    except OSError as exc:
        raise Dev1V12BuildError(f"unable_to_open_results_root:{results_root}") from exc
    pose_rows: list[dict[str, str]] = []
    raw_results: list[dict[str, str]] = []
    bindings: list[dict[str, str]] = []
    try:
        require(stat.S_ISDIR(os.fstat(root_fd).st_mode), "results_root_not_directory")
        for job in raw_jobs:
            job_id = str(job.get("job_id", ""))
            require(re.fullmatch(r"[A-Za-z0-9_.-]+", job_id) is not None, f"unsafe_job_id:{job_id}")
            try:
                job_fd = os.open(job_id, root_flags, dir_fd=root_fd)
            except OSError as exc:
                raise Dev1V12BuildError(f"raw_job_directory_unavailable:{job_id}") from exc
            try:
                file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                try:
                    result_fd = os.open("job_result.json", file_flags, dir_fd=job_fd)
                except OSError as exc:
                    raise Dev1V12BuildError(f"raw_job_result_unavailable:{job_id}") from exc
                try:
                    raw = _read_fd_snapshot(result_fd, f"job_result:{job_id}")
                finally:
                    os.close(result_fd)
            finally:
                os.close(job_fd)
            bindings.append({"job_id": job_id, "sha256": sha256_bytes(raw)})
            evidence = strict_json_bytes(raw, f"job_result:{job_id}")
            require(evidence.get("job_id") == job_id, f"raw_job_identity_mismatch:{job_id}")
            require(evidence.get("job_hash") == job.get("job_hash"), f"raw_job_hash_mismatch:{job_id}")
            require(evidence.get("protocol_core_sha256") == helper.EXPECTED_PROTOCOL_CORE_SHA256, f"raw_job_protocol_core_mismatch:{job_id}")
            expected_identity = {
                "entity_type": job.get("entity_type"),
                "entity_id": job.get("entity_id"),
                "dock_conformation": job.get("conformation"),
                "seed": job.get("seed"),
            }
            for field, expected in expected_identity.items():
                require(str(evidence.get(field, "")).lower() == str(expected).lower(), f"raw_job_{field}_mismatch:{job_id}")
            state = str(evidence.get("state", "")).upper()
            require(state in helper.SUCCESS_STATES, f"second_nonsuccess_open_job_forbidden:{job_id}")
            pose_scores = evidence.get("pose_scores")
            require(isinstance(pose_scores, list) and bool(pose_scores), f"successful_job_pose_scores_missing:{job_id}")
            raw_results.append(
                {
                    "job_id": job_id,
                    "job_hash": str(evidence.get("job_hash", "")),
                    "state": state,
                    "pose_backed_2x2": "True",
                    "selected_model_count": str(evidence.get("selected_model_count", "")),
                }
            )
            for pose in pose_scores:
                model = Path(str(pose.get("pose", ""))).name
                require(model != "", f"raw_pose_model_missing:{job_id}")
                haddock = pose.get("haddock_io") or {}
                scores = pose.get("scores")
                require(isinstance(scores, list), f"raw_pose_scores_invalid:{job_id}:{model}")
                for score in scores:
                    reference = str(score.get("reference_id", "")).lower()
                    require(reference in CONFORMATIONS, f"raw_pose_reference_invalid:{job_id}:{reference}")
                    clashes = helper.nested_metric(score, "clashes_2p5a")
                    pose_rows.append(
                        {
                            "job_id": job_id,
                            "model": model,
                            "scoring_reference": reference,
                            "haddock_score": str(haddock.get("score", "")),
                            "air_energy": str(haddock.get("unw_energies.air", "")),
                            "hotspot_overlap": str(helper.nested_metric(score, "hotspot_overlap", "full", "count")),
                            "anchor_overlap": str(helper.nested_metric(score, "hotspot_overlap", "anchor", "count")),
                            "holdout_overlap": str(helper.nested_metric(score, "hotspot_overlap", "holdout", "count")),
                            "total_occlusion": str(helper.nested_metric(score, "vhh_pvrl2_occlusion", "residue_pair_count")),
                            "cdr3_occlusion": str(helper.nested_metric(score, "vhh_pvrl2_occlusion", "by_vhh_region_pair_count", "cdr3")),
                            "cdr3_fraction": str(helper.nested_metric(score, "vhh_pvrl2_occlusion", "cdr3_fraction")),
                            "vhh_pvrig_clash_residue_pairs": str(helper.nested_metric(clashes, "vhh_pvrig", "residue_pair_count")),
                            "vhh_pvrl2_clash_residue_pairs": str(helper.nested_metric(clashes, "vhh_pvrl2", "residue_pair_count")),
                            "overlay_rmsd_a": str(helper.nested_metric(score, "overlay", "t_ca_rmsd_a")),
                            "clash_atom_pairs": str(helper.nested_metric(clashes, "atom_pair_count")),
                            "clash_residue_pairs": str(helper.nested_metric(clashes, "residue_pair_count")),
                        }
                    )

        failure_id = str(failure["job_id"])
        try:
            failure_dir_fd = os.open(failure_id, root_flags, dir_fd=root_fd)
        except FileNotFoundError:
            failure_dir_fd = None
        except OSError as exc:
            raise Dev1V12BuildError(f"frozen_failure_directory_invalid:{failure_id}") from exc
        if failure_dir_fd is not None:
            try:
                try:
                    unexpected_fd = os.open("job_result.json", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=failure_dir_fd)
                except FileNotFoundError:
                    unexpected_fd = None
                if unexpected_fd is not None:
                    os.close(unexpected_fd)
                    raise Dev1V12BuildError("frozen_failure_raw_job_result_unexpected")
            finally:
                os.close(failure_dir_fd)
    finally:
        os.close(root_fd)

    require(len(raw_results) == EXPECTED_RAW_OPEN_JOBS, "raw_result_count_not_1547")
    bindings.sort(key=lambda row: row["job_id"])
    binding_payload = json.dumps(bindings, separators=(",", ":"), sort_keys=True).encode("utf-8")
    raw_chain = sha256_bytes(binding_payload)
    require(raw_chain == EXPECTED_RAW_RESULT_SHA256_CHAIN, "raw_result_sha256_chain_mismatch")
    terminal, terminal_evidence = v11.read_frozen_terminal_failure(job_results, failure)
    results = [*raw_results, terminal]
    require(len(results) == EXPECTED_OPEN_JOBS, "combined_result_count_not_1548")
    evidence = {
        **terminal_evidence,
        "raw_job_result_count": EXPECTED_RAW_OPEN_JOBS,
        "aggregate_terminal_failure_count": 1,
        "combined_result_count": EXPECTED_OPEN_JOBS,
        "raw_result_sha256_chain": raw_chain,
        "raw_binding_count": len(bindings),
    }
    return pose_rows, results, bindings, evidence


def parse_prior_csv_snapshot(
    base: Any, raw: bytes, expected_candidates: Mapping[str, str]
) -> dict[str, dict[str, str]]:
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    except UnicodeDecodeError as exc:
        raise Dev1V12BuildError("generic_prior_utf8_invalid") from exc
    require(tuple(reader.fieldnames or ()) == base.GENERIC_PRIOR_FIELDS, "generic_prior_header_invalid")
    rows = list(reader)
    require(bool(rows), "generic_prior_empty")
    by_id: dict[str, dict[str, str]] = {}
    for row in rows:
        candidate_id = row.get("candidate_id", "")
        require(candidate_id and candidate_id not in by_id, f"generic_prior_duplicate_or_empty_id:{candidate_id}")
        require(re.fullmatch(r"[0-9a-f]{64}", row.get("sequence_sha256", "")) is not None, f"generic_prior_sequence_sha_invalid:{candidate_id}")
        by_id[candidate_id] = row
    require(set(by_id) == set(expected_candidates), "generic_prior_candidate_id_closure_failed")
    for candidate_id, expected_sequence_sha256 in expected_candidates.items():
        require(by_id[candidate_id]["sequence_sha256"] == expected_sequence_sha256, f"generic_prior_sequence_sha_mismatch:{candidate_id}")
    return by_id


def validate_exact_open_job_grid(
    selected_jobs: Sequence[Mapping[str, str]], allowed_candidates: set[str]
) -> None:
    require(len(selected_jobs) == EXPECTED_OPEN_JOBS, "selected_open_job_count_invalid")
    job_ids = [str(job.get("job_id", "")) for job in selected_jobs]
    require(len(set(job_ids)) == EXPECTED_OPEN_JOBS, "selected_open_job_id_not_unique")
    expected_grid = {
        (conformation, seed)
        for conformation in CONFORMATIONS
        for seed in (917, 1931, 3253)
    }
    by_candidate: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for job in selected_jobs:
        require(job.get("entity_type") == "candidate", "non_candidate_job_in_open_grid")
        candidate_id = str(job.get("entity_id", ""))
        require(candidate_id in allowed_candidates, f"forbidden_candidate_in_open_grid:{candidate_id}")
        conformation = str(job.get("conformation", "")).lower()
        try:
            seed = int(job.get("seed", ""))
        except (TypeError, ValueError) as exc:
            raise Dev1V12BuildError(f"invalid_seed_in_open_grid:{candidate_id}") from exc
        key = (conformation, seed)
        require(key not in by_candidate[candidate_id], f"duplicate_candidate_conformation_seed:{candidate_id}:{conformation}:{seed}")
        by_candidate[candidate_id].add(key)
    require(set(by_candidate) == allowed_candidates, "open_job_candidate_grid_closure_failed")
    for candidate_id, observed in by_candidate.items():
        require(observed == expected_grid, f"open_job_grid_invalid:{candidate_id}:{sorted(observed)}")


def canonical_invalid_identity(rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """Frozen clarification encoding; this exact byte contract yields 941d... ."""
    projected = [
        {
            "job_id": str(row["job_id"]),
            "model": str(row["model"]),
            "conformation": str(row["conformation"]),
            "seed": int(row["seed"]),
            "t_ca_rmsd_a": float(row["t_ca_rmsd_a"]),
        }
        for row in rows
    ]
    projected.sort(key=lambda row: (row["job_id"], row["model"], row["conformation"], row["seed"]))
    canonical = json.dumps(projected, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return projected, sha256_bytes(canonical)


def validate_frozen_governance(
    prereg: Mapping[str, Any],
    diagnostic: Mapping[str, Any],
    diagnostic_receipt: Mapping[str, Any],
    clarification: Mapping[str, Any],
    v1_1_failure: Mapping[str, Any],
) -> list[dict[str, Any]]:
    require(
        prereg.get("status")
        == "FROZEN_POSTHOC_V1_2_METHOD_AFTER_OPEN_DIAGNOSTIC_BEFORE_V1_2_IMPLEMENTATION_OR_TEACHER_MATERIALIZATION",
        "prereg_status_invalid",
    )
    outputs = prereg.get("outputs") or {}
    require(outputs.get("remote_root") == REMOTE_ROOT, "prereg_remote_root_invalid")
    require(outputs.get("release_directory") == "release_v1_2", "prereg_release_directory_invalid")
    require(outputs.get("release_name") == RELEASE_NAME, "prereg_release_name_invalid")
    require(outputs.get("teacher_basename") == OUTPUT_BASENAME, "prereg_teacher_basename_invalid")
    require(outputs.get("teacher_audit_status") == AUDIT_STATUS, "prereg_audit_status_invalid")
    require(outputs.get("teacher_or_release_exists_at_freeze") is False, "prereg_preexisting_output_true")
    gates = prereg.get("hard_release_gates") or {}
    require(gates.get("exact_invalid_pair_count") == EXPECTED_INVALID_PAIR_COUNT, "prereg_invalid_pair_count_invalid")
    require(gates.get("exact_affected_job_count") == EXPECTED_AFFECTED_JOB_COUNT, "prereg_affected_job_count_invalid")
    require(gates.get("minimum_retained_complete_pairs_per_success_job") == MIN_RETAINED_COMPLETE_PAIRS, "prereg_min_pairs_invalid")
    require(gates.get("test32_raw_job_files_opened") == 0, "prereg_test32_open_nonzero")
    require(gates.get("test32_metric_values_read") == 0, "prereg_test32_metric_nonzero")
    require(gates.get("formal_v4_f_unlock_eligible") is False, "prereg_unlock_true")
    rule = prereg.get("pose_validity_rule") or {}
    require(rule.get("threshold_a") == OVERLAY_RMSD_LIMIT_A, "prereg_threshold_invalid")
    require(rule.get("pair_key") == ["job_id", "model"], "prereg_pair_key_invalid")
    require(rule.get("drop_only_one_reference_forbidden") is True, "prereg_single_ref_drop_allowed")
    require(rule.get("invalid_pair_count_may_be_surrogate_input") is False, "prereg_invalid_count_feature_allowed")

    require(diagnostic.get("status") == "PASS_OPEN_ONLY_DIAGNOSTIC_COMPLETED", "diagnostic_status_invalid")
    require(diagnostic.get("frozen_limit_a") == OVERLAY_RMSD_LIMIT_A, "diagnostic_threshold_invalid")
    access = diagnostic.get("physical_access") or {}
    require(access.get("test32_raw_job_files_opened") == 0, "diagnostic_test32_raw_nonzero")
    require(access.get("test32_metric_values_read") == 0, "diagnostic_test32_metric_nonzero")
    diagnostic_rows, diagnostic_hash = canonical_invalid_identity(
        diagnostic.get("invalid_native_overlay_rows") or []
    )
    require(len(diagnostic_rows) == EXPECTED_INVALID_PAIR_COUNT, "diagnostic_invalid_pair_count_invalid")
    require(diagnostic_hash == EXPECTED_INVALID_IDENTITY_SHA256, "diagnostic_invalid_identity_sha256_mismatch")

    require(
        diagnostic_receipt.get("status") == "PASS_OPEN_ONLY_READ_ONLY_DIAGNOSTIC_AND_LOCAL_DELIVERY",
        "diagnostic_receipt_status_invalid",
    )
    receipt_boundary = diagnostic_receipt.get("sealed_boundary") or {}
    require(receipt_boundary.get("test32_raw_job_files_opened") == 0, "diagnostic_receipt_test32_raw_nonzero")
    require(receipt_boundary.get("test32_metric_values_read") == 0, "diagnostic_receipt_test32_metric_nonzero")

    require(
        clarification.get("status") == "POST_FREEZE_SERIALIZATION_CLARIFICATION_NO_METHOD_CHANGE",
        "canonical_clarification_status_invalid",
    )
    require(clarification.get("method_or_threshold_changed") is False, "canonical_clarification_changed_method")
    require(clarification.get("canonical_sha256") == EXPECTED_INVALID_IDENTITY_SHA256, "canonical_clarification_sha_invalid")
    require(clarification.get("row_count") == EXPECTED_INVALID_PAIR_COUNT, "canonical_clarification_count_invalid")

    require(v1_1_failure.get("status") == "FAILED_CLOSED_NATIVE_OVERLAY_RMSD_ABOVE_1A", "v1_1_failure_status_invalid")
    require((v1_1_failure.get("artifact_closure") or {}).get("teacher_artifacts_created") is False, "v1_1_teacher_created")
    require((v1_1_failure.get("artifact_closure") or {}).get("release_v1_1_absent") is True, "v1_1_release_not_absent")
    require(v1_1_failure.get("formal_v4_f_unlock_eligible") is False, "v1_1_unlock_true")
    v11_boundary = v1_1_failure.get("sealed_test32_boundary") or {}
    require(v11_boundary.get("test32_raw_job_files_opened") == 0, "v1_1_test32_raw_nonzero")
    require(v11_boundary.get("test32_metric_values_read") == 0, "v1_1_test32_metric_nonzero")
    return diagnostic_rows


def filter_invalid_native_overlay_pairs(
    helper: Any,
    pose_rows: Sequence[Mapping[str, str]],
    selected_jobs: Sequence[Mapping[str, str]],
    selected_split: Sequence[Mapping[str, str]],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Validate exact 2-reference pairs and drop invalid native pairs pre-weighting."""
    jobs_by_id = {str(job.get("job_id", "")): dict(job) for job in selected_jobs}
    require(len(jobs_by_id) == len(selected_jobs), "duplicate_selected_job_id_for_filter")
    split_by_candidate = {str(row.get("candidate_id", "")): dict(row) for row in selected_split}
    require(len(split_by_candidate) == EXPECTED_OPEN_ROWS, "filter_split_candidate_closure_invalid")
    by_pair: dict[tuple[str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for input_row in pose_rows:
        row = dict(input_row)
        job_id = str(row.get("job_id", ""))
        model = str(row.get("model", ""))
        reference = str(row.get("scoring_reference", "")).lower()
        require(job_id in jobs_by_id, f"pose_job_not_selected:{job_id}")
        require(model != "", f"pose_model_empty:{job_id}")
        require(reference in CONFORMATIONS, f"pose_reference_invalid:{job_id}:{model}:{reference}")
        key = (job_id, model)
        require(reference not in by_pair[key], f"duplicate_pair_reference:{job_id}:{model}:{reference}")
        by_pair[key][reference] = row

    # Pair count is established only after every discovered pair independently proves
    # exact two-reference completeness; it is not inferred from the diagnostic count.
    for (job_id, model), refs in by_pair.items():
        require(set(refs) == set(CONFORMATIONS), f"pair_not_exact_two_reference:{job_id}:{model}")
    complete_pair_count = len(by_pair)
    require(complete_pair_count == EXPECTED_COMPLETE_PAIR_COUNT, f"complete_pair_count_not_14490:{complete_pair_count}")

    invalid_keys: set[tuple[str, str]] = set()
    identities: list[dict[str, Any]] = []
    before_by_job: Counter[str] = Counter()
    rank_by_pair: dict[tuple[str, str], int] = {}
    pairs_by_job: dict[str, list[tuple[str, Mapping[str, Mapping[str, str]]]]] = defaultdict(list)
    for (job_id, model), refs in by_pair.items():
        pairs_by_job[job_id].append((model, refs))
    for job_id, models in pairs_by_job.items():
        conformation = str(jobs_by_id[job_id].get("conformation", "")).lower()
        require(conformation in CONFORMATIONS, f"job_conformation_invalid:{job_id}")
        models.sort(
            key=lambda item: (
                helper.as_float(item[1][conformation].get("haddock_score"), field="haddock_score"),
                item[0],
            )
        )
        for rank, (model, _refs) in enumerate(models, start=1):
            rank_by_pair[(job_id, model)] = rank
    for (job_id, model), refs in by_pair.items():
        manifest = jobs_by_id[job_id]
        conformation = str(manifest.get("conformation", "")).lower()
        require(conformation in CONFORMATIONS, f"job_conformation_invalid:{job_id}")
        native = refs[conformation]
        rmsd = helper.as_float(native.get("overlay_rmsd_a"), field="overlay_rmsd_a")
        before_by_job[job_id] += 1
        if rmsd > OVERLAY_RMSD_LIMIT_A:
            invalid_keys.add((job_id, model))
            identities.append(
                {
                    "job_id": job_id,
                    "model": model,
                    "conformation": conformation,
                    "seed": int(manifest.get("seed", "")),
                    "t_ca_rmsd_a": rmsd,
                }
            )

    canonical_rows, identity_sha = canonical_invalid_identity(identities)
    affected_jobs = {job_id for job_id, _model in invalid_keys}
    affected_candidates = {str(jobs_by_id[job_id].get("entity_id", "")) for job_id in affected_jobs}
    by_conformation = Counter(row["conformation"] for row in canonical_rows)
    require(len(invalid_keys) == EXPECTED_INVALID_PAIR_COUNT, f"invalid_pair_count_not_99:{len(invalid_keys)}")
    require(len(affected_jobs) == EXPECTED_AFFECTED_JOB_COUNT, f"affected_job_count_not_98:{len(affected_jobs)}")
    require(len(affected_candidates) == EXPECTED_AFFECTED_CANDIDATE_COUNT, f"affected_candidate_count_not_83:{len(affected_candidates)}")
    require(dict(sorted(by_conformation.items())) == EXPECTED_INVALID_BY_CONFORMATION, "invalid_by_conformation_mismatch")
    require(identity_sha == EXPECTED_INVALID_IDENTITY_SHA256, "raw_invalid_identity_sha256_mismatch")

    filtered = [dict(row) for row in pose_rows if (str(row["job_id"]), str(row["model"])) not in invalid_keys]
    require(len(filtered) == 2 * (complete_pair_count - EXPECTED_INVALID_PAIR_COUNT), "filtered_pose_row_count_invalid")
    require(complete_pair_count - len(invalid_keys) == EXPECTED_FILTERED_COMPLETE_PAIR_COUNT, "filtered_complete_pair_count_not_14391")
    retained_by_job = Counter(str(row["job_id"]) for row in filtered)
    for job_id in list(retained_by_job):
        require(retained_by_job[job_id] % 2 == 0, f"retained_reference_parity_invalid:{job_id}")
        retained_by_job[job_id] //= 2
    expected_success_jobs = {
        str(job.get("job_id", ""))
        for job in selected_jobs
        if str(job.get("job_id", "")) != FROZEN_FAILED_JOB_ID
    }
    require(len(expected_success_jobs) == EXPECTED_RAW_OPEN_JOBS, "selected_success_job_count_not_1547")
    require(set(before_by_job) == expected_success_jobs, "pose_pair_success_job_closure_failed")
    require(set(retained_by_job) == expected_success_jobs, "retained_success_job_closure_failed")
    minimum_all = min(retained_by_job.values())
    minimum_affected = min(retained_by_job[job_id] for job_id in affected_jobs)
    require(minimum_all >= MIN_RETAINED_COMPLETE_PAIRS, f"success_job_retained_pairs_below_4:{minimum_all}")
    require(minimum_affected == EXPECTED_MIN_AFFECTED_RETAINED_PAIRS, "affected_min_retained_pairs_not_5")

    categorical_counts: dict[str, Counter[str]] = {
        "conformation": Counter(),
        "seed": Counter(),
        "helper_haddock_score_rank": Counter(),
        "parent_id": Counter(),
        "target_patch_id": Counter(),
        "design_mode": Counter(),
        "model_split": Counter(),
    }
    for identity in canonical_rows:
        manifest = jobs_by_id[identity["job_id"]]
        candidate_id = str(manifest["entity_id"])
        split = split_by_candidate[candidate_id]
        categorical_counts["conformation"][identity["conformation"]] += 1
        categorical_counts["seed"][str(identity["seed"])] += 1
        categorical_counts["helper_haddock_score_rank"][str(rank_by_pair[(identity["job_id"], identity["model"])])] += 1
        for field in ("parent_id", "target_patch_id", "design_mode", "model_split"):
            categorical_counts[field][str(split[field])] += 1
    retained_distribution = Counter(retained_by_job[job_id] for job_id in affected_jobs)
    audit = {
        "rule": "drop complete pair iff job-native overlay.t_ca_rmsd_a > 1.0",
        "threshold_a": OVERLAY_RMSD_LIMIT_A,
        "filter_stage": "before_geometry_classification_sorting_rank_weights_utility_and_candidate_aggregation",
        "complete_pair_count_before_filter": complete_pair_count,
        "invalid_complete_pair_count": len(invalid_keys),
        "complete_pair_count_after_filter": complete_pair_count - len(invalid_keys),
        "affected_job_count": len(affected_jobs),
        "affected_candidate_count": len(affected_candidates),
        "invalid_by_conformation": dict(sorted(by_conformation.items())),
        "invalid_pair_identity_value_list_canonical_sha256": identity_sha,
        "minimum_retained_complete_pairs_all_success_jobs": minimum_all,
        "minimum_retained_complete_pairs_affected_jobs": minimum_affected,
        "invalid_pair_counts_by": {
            field: dict(sorted(counts.items())) for field, counts in categorical_counts.items()
        },
        "affected_job_retained_complete_pair_count_distribution": {
            str(count): frequency for count, frequency in sorted(retained_distribution.items())
        },
        "affected_candidate_ids": sorted(affected_candidates),
        "pair_reference_completeness_validated": True,
        "rank_weights_renormalized_by_unchanged_helper_after_filter": True,
        "invalid_pair_count_exposed_as_teacher_feature": False,
    }
    return filtered, audit


def _distribution(values: Sequence[float]) -> dict[str, Any]:
    require(bool(values), "descriptive_distribution_empty")
    numeric = [float(value) for value in values]
    return {
        "count": len(numeric),
        "minimum": min(numeric),
        "maximum": max(numeric),
        "mean": statistics.fmean(numeric),
        "median": statistics.median(numeric),
    }


def build_descriptive_sensitivity_report(
    rows: Sequence[Mapping[str, Any]], pose_filter_audit: Mapping[str, Any]
) -> dict[str, Any]:
    affected = set(pose_filter_audit.get("affected_candidate_ids") or [])

    def group(field: str) -> dict[str, Any]:
        values: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            values[str(row[field])].append(row)
        return {
            key: {
                "R_dual_min": _distribution([float(row["R_dual_min"]) for row in subset]),
                "teacher_uncertainty": _distribution([float(row["teacher_uncertainty"]) for row in subset]),
            }
            for key, subset in sorted(values.items())
        }

    by_exposure: dict[str, list[Mapping[str, Any]]] = {"affected": [], "unaffected": []}
    for row in rows:
        key = "affected" if str(row["candidate_id"]) in affected else "unaffected"
        by_exposure[key].append(row)
    receptor = {
        "8x6b": {
            "receptor_score": _distribution([float(row["R_8X6B"]) for row in rows]),
            "teacher_uncertainty": _distribution([float(row["teacher_uncertainty"]) for row in rows]),
        },
        "9e6y": {
            "receptor_score": _distribution([float(row["R_9E6Y"]) for row in rows]),
            "teacher_uncertainty": _distribution([float(row["teacher_uncertainty"]) for row in rows]),
        },
    }
    return {
        "invalid_pair_categorical_and_rank_counts": pose_filter_audit["invalid_pair_counts_by"],
        "affected_job_retained_pair_count_distribution": pose_filter_audit[
            "affected_job_retained_complete_pair_count_distribution"
        ],
        "continuous_distributions": {
            "by_model_split": group("model_split"),
            "by_parent_id": group("parent_id"),
            "by_invalid_pair_exposure": {
                key: {
                    "R_dual_min": _distribution([float(row["R_dual_min"]) for row in subset]),
                    "teacher_uncertainty": _distribution([float(row["teacher_uncertainty"]) for row in subset]),
                }
                for key, subset in by_exposure.items()
            },
            "by_receptor_conformation": receptor,
        },
        "root_cause_corroborative_only": {
            "statement": "Selected severe 8X6B examples and the huge-RMSD 8X6B class are consistent with flexref displacement around the disconnected T-chain segment. This is not established for all 99 pairs, especially mild or 9E6Y cases.",
            "full_root_cause_artifact_postdates_preregistration": True,
            "full_root_cause_artifact_is_separate_corroborative_evidence": True,
            "builder_reads_root_cause_path_or_hash": False,
            "used_as_filter_or_teacher_computational_input": False,
            "used_to_change_threshold": False,
        },
    }


def validate_all_numeric_teacher_targets_finite(rows: Sequence[Mapping[str, Any]]) -> None:
    exact_fields = {
        "R_8X6B", "R_9E6Y", "R_dual_mean", "R_dual_min", "R_dual_gap",
        "seed_sd_8X6B", "seed_sd_9E6Y", "successful_seed_count_8X6B",
        "successful_seed_count_9E6Y", "native_cross_support_agreement_mean",
        "model_pair_consensus_fraction_mean", "model_strict_a_fraction_mean",
        "model_count_reliability_mean", "agreement_reliability_mean",
        "missing_seed_fraction", "teacher_uncertainty", "generic_binding_prior",
    }
    for row in rows:
        candidate_id = str(row.get("candidate_id", ""))
        numeric_fields = [
            field for field in row
            if field in exact_fields or field.endswith("_median_8X6B") or field.endswith("_median_9E6Y")
        ]
        optional_uncertainty = row.get("generic_binding_model_uncertainty", "")
        if optional_uncertainty != "":
            numeric_fields.append("generic_binding_model_uncertainty")
        for field in numeric_fields:
            try:
                value = float(row[field])
            except (TypeError, ValueError) as exc:
                raise Dev1V12BuildError(f"teacher_numeric_target_invalid:{candidate_id}:{field}") from exc
            require(math.isfinite(value), f"teacher_numeric_target_nonfinite:{candidate_id}:{field}")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _create_release_in_directory(
    output_dir: Path,
    rows: list[dict[str, Any]],
    *,
    source_inputs: Mapping[str, Any],
    pose_filter_audit: Mapping[str, Any],
    descriptive_sensitivity: Mapping[str, Any],
    builder_sha256: str,
) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), "output_directory_exists")
    outputs = output_dir / "outputs"
    outputs.mkdir(parents=True)
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for field in row:
            if field not in seen:
                seen.add(field)
                fields.append(field)
    forbidden = [field for field in fields if "invalid_pair" in field or "excluded_pair" in field]
    require(not forbidden, "invalid_pair_evidence_exposed_as_teacher_feature:" + ",".join(forbidden))
    teacher = outputs / OUTPUT_BASENAME
    with teacher.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    teacher_sha = sha256_file(teacher)
    boundary = {
        "model_split": SEALED_SPLIT,
        "candidate_rows": EXPECTED_SEALED_ROWS,
        "raw_test32_job_files_opened": 0,
        "test32_metric_values_read": 0,
        "test32_label_rows_emitted": 0,
    }
    source_receipt = outputs / SOURCE_RECEIPT_BASENAME
    _write_json(
        source_receipt,
        {
            "schema_version": SCHEMA_VERSION,
            "status": "SOURCE_EVALUATOR_FAILED_DEV_USE_ONLY_V1_2",
            "source_evaluator": {"status": "FAIL", "unlockable": False, "failed_gates": [SOURCE_FAILED_GATE]},
            "v1_status": "FAILED_CLOSED_MISSING_RAW_RESULT_FOR_FROZEN_FAILED_MAX_ATTEMPTS_JOB",
            "v1_1_status": "FAILED_CLOSED_NATIVE_OVERLAY_RMSD_ABOVE_1A",
            "formal_v4_f_unlock_eligible": False,
            "claim_boundary": CLAIM_BOUNDARY,
        },
    )
    audit = outputs / AUDIT_BASENAME
    _write_json(
        audit,
        {
            "schema_version": SCHEMA_VERSION,
            "status": AUDIT_STATUS,
            "release": RELEASE_NAME,
            "track_id": TRACK_ID,
            "primary_target": PRIMARY_TARGET,
            "source_evaluator": {"status": "FAIL", "unlockable": False, "failed_gates": [SOURCE_FAILED_GATE]},
            "single_terminal_failure_recovery": {
                "count": 1,
                "raw_job_result_count": EXPECTED_RAW_OPEN_JOBS,
                "aggregate_terminal_rows_parsed": 1,
                "aggregate_metric_fields_parsed": 0,
            },
            "pose_validity_filter": dict(pose_filter_audit),
            "required_descriptive_sensitivity_reports": dict(descriptive_sensitivity),
            "sealed_data_boundary": boundary,
            "inputs": dict(source_inputs),
            "output": {
                "path": f"outputs/{OUTPUT_BASENAME}",
                "row_count": EXPECTED_OPEN_ROWS,
                "split_counts": EXPECTED_OPEN_COUNTS,
                "exact_header": fields,
                "sha256": teacher_sha,
            },
            "formal_v4_f_unlock_eligible": False,
            "claim_boundary": CLAIM_BOUNDARY,
        },
    )
    release_receipt = outputs / RELEASE_RECEIPT_BASENAME
    _write_json(
        release_receipt,
        {
            "schema_version": SCHEMA_VERSION,
            "status": REMOTE_READY_STATUS,
            "release": RELEASE_NAME,
            "audit_status": AUDIT_STATUS,
            "development_only": True,
            "formal_v4_f_unlock_eligible": False,
            "row_count": EXPECTED_OPEN_ROWS,
            "split_counts": EXPECTED_OPEN_COUNTS,
            "sealed_data_boundary": boundary,
            "teacher_sha256": teacher_sha,
            "teacher_audit_sha256": sha256_file(audit),
            "source_failure_receipt_sha256": sha256_file(source_receipt),
            "builder_sha256": builder_sha256,
            "preregistration_sha256": EXPECTED_PREREG_SHA256,
            "claim_boundary": CLAIM_BOUNDARY,
        },
    )
    payloads = (OUTPUT_BASENAME, AUDIT_BASENAME, SOURCE_RECEIPT_BASENAME, RELEASE_RECEIPT_BASENAME)
    (outputs / CHECKSUM_BASENAME).write_text(
        "".join(f"{sha256_file(outputs / name)}  outputs/{name}\n" for name in payloads),
        encoding="ascii",
    )
    archive = output_dir / ARCHIVE_BASENAME
    with tarfile.open(archive, "x:gz") as bundle:
        for name in (*payloads, CHECKSUM_BASENAME):
            bundle.add(outputs / name, arcname=f"outputs/{name}", recursive=False)
    archive_sha = sha256_file(archive)
    (output_dir / ARCHIVE_SHA_BASENAME).write_text(f"{archive_sha}  {ARCHIVE_BASENAME}\n", encoding="ascii")
    return {
        "status": REMOTE_READY_STATUS,
        "archive": str(archive),
        "archive_sha256": archive_sha,
        "teacher_sha256": teacher_sha,
        "formal_v4_f_unlock_eligible": False,
        "test32_raw_open": 0,
    }


def _fsync_release_tree(root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    directories = sorted((path for path in root.rglob("*") if path.is_dir()), reverse=True)
    for directory in [*directories, root]:
        fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def create_release_artifacts(
    output_dir: Path,
    rows: list[dict[str, Any]],
    *,
    source_inputs: Mapping[str, Any],
    pose_filter_audit: Mapping[str, Any],
    descriptive_sensitivity: Mapping[str, Any],
    builder_sha256: str,
) -> dict[str, Any]:
    """Publish only a completely materialized, fsynced sibling staging tree."""
    require(not output_dir.exists() and not output_dir.is_symlink(), "output_directory_exists")
    parent = output_dir.parent
    try:
        parent_stat = parent.lstat()
    except FileNotFoundError as exc:
        raise Dev1V12BuildError(f"output_parent_missing:{parent}") from exc
    require(stat.S_ISDIR(parent_stat.st_mode), "output_parent_not_real_directory")
    staging = parent / f".{output_dir.name}.v1_2_staging_{os.getpid()}"
    require(not staging.exists() and not staging.is_symlink(), "staging_directory_exists")
    try:
        receipt = _create_release_in_directory(
            staging,
            rows,
            source_inputs=source_inputs,
            pose_filter_audit=pose_filter_audit,
            descriptive_sensitivity=descriptive_sensitivity,
            builder_sha256=builder_sha256,
        )
        _fsync_release_tree(staging)
        require(not output_dir.exists() and not output_dir.is_symlink(), "output_directory_appeared_before_publish")
        os.replace(staging, output_dir)
        parent_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        receipt["archive"] = str(output_dir / ARCHIVE_BASENAME)
        return receipt
    except Exception:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preregistration", type=Path, default=root / "audits/phase2_v4_d_dev1_open258_v1_2_pose_validity_recovery_preregistration.json")
    parser.add_argument("--diagnostic", type=Path, default=root / "audits/phase2_v4_d_dev1_open_overlay_rmsd_diagnostic_v2.json")
    parser.add_argument("--diagnostic-receipt", type=Path, default=root / "audits/phase2_v4_d_dev1_open_overlay_rmsd_diagnostic_v2_run_receipt.json")
    parser.add_argument("--canonical-clarification", type=Path, default=root / "audits/phase2_v4_d_dev1_open258_v1_2_invalid_pair_canonicalization_clarification.json")
    parser.add_argument("--fallback-evidence", type=Path, default=root / "audits/phase2_v4_d_dev1_open258_v1_1_terminal_fallback_projection_evidence.json")
    parser.add_argument("--v1-failure-receipt", type=Path, default=root / "audits/phase2_v4_d_dev1_open258_v1_remote_runtime_failure_receipt.json")
    parser.add_argument("--v1-1-failure-receipt", type=Path, default=root / "audits/phase2_v4_d_dev1_open258_v1_1_remote_runtime_failure_receipt.json")
    parser.add_argument("--v1-builder", type=Path, default=Path(__file__).with_name("prepare_phase2_v4_d_dev1_open258.py"))
    parser.add_argument("--v1-1-builder", type=Path, default=Path(__file__).with_name("prepare_phase2_v4_d_dev1_open258_v1_1.py"))
    parser.add_argument("--v1-formula-helper", type=Path, default=Path(__file__).with_name("prepare_phase2_v4_d_open_teacher.py"))
    for name in (
        "split-manifest", "job-manifest", "job-results", "pose-scores", "protocol-core-lock",
        "protocol-lock", "stability-spec", "results-root", "evaluator", "generic-prior", "output-dir",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-generic-prior-sha256", default=EXPECTED_GENERIC_PRIOR_SHA256)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    prereg = read_bound_json(args.preregistration, "preregistration", EXPECTED_PREREG_SHA256)
    diagnostic = read_bound_json(args.diagnostic, "diagnostic", EXPECTED_DIAGNOSTIC_SHA256)
    diagnostic_receipt = read_bound_json(args.diagnostic_receipt, "diagnostic_receipt", EXPECTED_DIAGNOSTIC_RECEIPT_SHA256)
    clarification = read_bound_json(args.canonical_clarification, "canonical_clarification", EXPECTED_CANONICAL_CLARIFICATION_SHA256)
    fallback = read_bound_json(args.fallback_evidence, "fallback_evidence", EXPECTED_FALLBACK_EVIDENCE_SHA256)
    v1_failure = read_bound_json(args.v1_failure_receipt, "v1_failure_receipt", EXPECTED_V1_FAILURE_RECEIPT_SHA256)
    v1_1_failure = read_bound_json(args.v1_1_failure_receipt, "v1_1_failure_receipt", EXPECTED_V1_1_FAILURE_RECEIPT_SHA256)
    validate_frozen_governance(prereg, diagnostic, diagnostic_receipt, clarification, v1_1_failure)
    require(fallback.get("status") == "PASS_EXACT_SINGLE_OPEN_TERMINAL_FAILURE_PROJECTION", "fallback_evidence_status_invalid")
    require(v1_failure.get("status") == "FAILED_CLOSED_MISSING_RAW_RESULT_FOR_FROZEN_FAILED_MAX_ATTEMPTS_JOB", "v1_failure_status_invalid")
    require(v1_failure.get("teacher_artifacts_created") is False, "v1_failure_teacher_created")
    require(v1_failure.get("release_absent") is True, "v1_failure_release_not_absent")
    require(v1_failure.get("formal_v4_f_unlock_eligible") is False, "v1_failure_unlock_true")
    require(v1_failure.get("test32_raw_job_files_opened") == 0, "v1_failure_test32_raw_nonzero")
    require(v1_failure.get("test32_metric_values_read") == 0, "v1_failure_test32_metric_nonzero")

    base = load_bound_module(args.v1_builder, "v1_builder", EXPECTED_V1_BUILDER_SHA256)
    v11 = load_bound_module(args.v1_1_builder, "v1_1_builder", EXPECTED_V1_1_BUILDER_SHA256)
    helper = load_bound_module(args.v1_formula_helper, "v1_formula_helper", EXPECTED_V1_HELPER_SHA256)
    evaluator = read_bound_json(args.evaluator, "source_evaluator", EXPECTED_EVALUATOR_SHA256)
    base.validate_source_evaluator(evaluator, EXPECTED_EVALUATOR_SHA256)
    read_bound_bytes(args.protocol_core_lock, "protocol_core_lock", EXPECTED_PROTOCOL_CORE_LOCK_SHA256)
    read_bound_bytes(args.protocol_lock, "protocol_lock", EXPECTED_PROTOCOL_LOCK_SHA256)
    read_bound_bytes(args.stability_spec, "stability_spec", EXPECTED_STABILITY_SPEC_SHA256)
    v11.validate_pose_scores_frozen_zero(args.pose_scores)

    split_rows = read_bound_table(args.split_manifest, "split_manifest", EXPECTED_SPLIT_MANIFEST_SHA256, delimiter="\t")
    selected_split = helper.select_open_split(split_rows)
    allowed = {row["candidate_id"] for row in selected_split}
    sealed = {row["candidate_id"] for row in split_rows if row["model_split"] == SEALED_SPLIT}
    job_rows = read_bound_table(args.job_manifest, "job_manifest", EXPECTED_JOB_MANIFEST_SHA256, delimiter="\t")
    jobs = helper.select_open_candidate_jobs(job_rows, allowed)
    require(all(job.get("entity_id") not in sealed for job in jobs), "sealed_job_admitted")
    validate_exact_open_job_grid(jobs, allowed)
    expected_prior = {row["candidate_id"]: row["sequence_sha256"] for row in split_rows}
    # Bind and parse the label-free prior snapshot before constructing or opening
    # any selected raw-result path.
    prior_raw = read_bound_bytes(
        args.generic_prior, "generic_prior", args.expected_generic_prior_sha256
    )
    prior = parse_prior_csv_snapshot(base, prior_raw, expected_prior)
    poses, results, bindings, recovery = collect_recovery_results_secure(
        helper, v11, args.results_root, jobs, args.job_results
    )
    filtered_poses, filter_audit = filter_invalid_native_overlay_pairs(
        helper, poses, jobs, selected_split
    )
    rows = helper.build_teacher_rows(selected_split, jobs, results, filtered_poses)
    base.add_generic_prior(rows, prior)
    for row in rows:
        row.update(
            {
                "dev_release_track": TRACK_ID,
                "development_only": True,
                "source_evaluator_status": "FAIL",
                "source_failed_gate": SOURCE_FAILED_GATE,
                "formal_v4_f_unlock_eligible": False,
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )
    base.validate_teacher_rows(rows)
    validate_all_numeric_teacher_targets_finite(rows)
    descriptive_sensitivity = build_descriptive_sensitivity_report(rows, filter_audit)
    source_inputs = {
        "preregistration_sha256": EXPECTED_PREREG_SHA256,
        "diagnostic_sha256": EXPECTED_DIAGNOSTIC_SHA256,
        "diagnostic_receipt_sha256": EXPECTED_DIAGNOSTIC_RECEIPT_SHA256,
        "canonical_clarification_sha256": EXPECTED_CANONICAL_CLARIFICATION_SHA256,
        "split_manifest_sha256": EXPECTED_SPLIT_MANIFEST_SHA256,
        "job_manifest_sha256": EXPECTED_JOB_MANIFEST_SHA256,
        "job_results_sha256_binding_only": EXPECTED_JOB_RESULTS_SHA256,
        "pose_scores_sha256_binding_only": EXPECTED_POSE_SCORES_SHA256,
        "source_evaluator_sha256": EXPECTED_EVALUATOR_SHA256,
        "generic_prior_sha256": args.expected_generic_prior_sha256,
        "v1_failure_receipt_sha256": EXPECTED_V1_FAILURE_RECEIPT_SHA256,
        "v1_1_failure_receipt_sha256": EXPECTED_V1_1_FAILURE_RECEIPT_SHA256,
        "v1_builder_sha256": EXPECTED_V1_BUILDER_SHA256,
        "v1_1_builder_sha256": EXPECTED_V1_1_BUILDER_SHA256,
        "v1_formula_helper_sha256": EXPECTED_V1_HELPER_SHA256,
        "fallback_evidence_sha256": EXPECTED_FALLBACK_EVIDENCE_SHA256,
        "raw_job_result_count": EXPECTED_RAW_OPEN_JOBS,
        "aggregate_terminal_rows_parsed": 1,
        "aggregate_metric_fields_parsed": 0,
        "raw_test32_job_files_opened": 0,
        "test32_metric_values_read": 0,
        "test32_label_rows_emitted": 0,
        "raw_result_sha256_chain": recovery["raw_result_sha256_chain"],
        "raw_binding_count": len(bindings),
    }
    receipt = create_release_artifacts(
        args.output_dir,
        rows,
        source_inputs=source_inputs,
        pose_filter_audit=filter_audit,
        descriptive_sensitivity=descriptive_sensitivity,
        builder_sha256=sha256_file(Path(__file__)),
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
