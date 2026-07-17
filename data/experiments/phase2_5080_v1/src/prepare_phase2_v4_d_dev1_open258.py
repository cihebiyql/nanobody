#!/usr/bin/env python3
"""Build the post-hoc V4-D-DEV1 open258 continuous-geometry release.

The builder is deliberately separate from the frozen V4-D/V1 release.  It
admits only OPEN_TRAIN and OPEN_DEVELOPMENT candidate IDs before any raw result
is opened, preserves the source evaluator FAIL, and cannot emit a formal V4-F
unlock receipt.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import stat
import sys
import tarfile
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "phase2_v4_d_dev1_open258_v1"
TRACK_ID = "V4-D-DEV1"
AUDIT_STATUS = "RELEASED_DEV_ONLY_FROM_FAILED_V4D_EVALUATOR_TEST32_SEALED"
RELEASE_NAME = "OPEN_TRAIN_226_PLUS_OPEN_DEVELOPMENT_32_DEV_ONLY"
REMOTE_READY_STATUS = "DEV1_RELEASE_READY_TEST32_SEALED"
CLAIM_BOUNDARY = (
    "Post-hoc development-only sequence-to-computational-dual-docking continuous "
    "geometry evidence; not a V4-D pass, formal test, Docking Gold, binding, affinity, "
    "competition, experimental blocking, or final submission authority."
)

EXPECTED_PREREG_SHA256 = "ee2c1076b0fd58b5bcb991f7646321c6fd03204746ff926f2d93940fec5ffe55"
EXPECTED_V1_HELPER_SHA256 = "8adb3c4e1de37bbaaf469dfb967176d2c49d40f353e21a3f028baa20ea8e4145"
EXPECTED_EVALUATOR_SHA256 = "289542c58cfe72c380143a910b3adb75ba4e12f65899f71907a044314bedb674"
EXPECTED_SPLIT_MANIFEST_SHA256 = "c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd"
EXPECTED_JOB_MANIFEST_SHA256 = "96fec07a5535615f50bff40ac48bb323a94213e06a7b12726ae5b4b2d1161737"
EXPECTED_JOB_RESULTS_SHA256 = "30c4227e15f6b049a9d9e9241ca34df30d38b247d14081b4ce7d3387fa2f3f25"
EXPECTED_POSE_SCORES_SHA256 = "7a2737160051c8fca8836b4086507e8f70d83cd692f87ffc17eaff8279c32681"
EXPECTED_PROTOCOL_CORE_SHA256 = "91d75291ff832c1e94cbc0bf6f1cdd75de6a8bb74611230cdcd1716466f37cb7"
EXPECTED_PROTOCOL_LOCK_SHA256 = "a24eaf37730bc569067d64cdc1a43a763b70878d13d50e804bf3000ce43f5e84"
EXPECTED_STABILITY_SPEC_SHA256 = "fb01cdaa5939f2846b16e4e02a09903417cd6cea04d42350c4ed57f9ae7eb774"
EXPECTED_PROTOCOL_CORE_LOCK_FILE_SHA256 = "767117dc2c506cfdfc83fce8e12931514d268941348d69a9abbda5a6500bdd24"
EXPECTED_PROTOCOL_LOCK_FILE_SHA256 = "56ef539cb54a1aba8e665ec5d62b3653088e2289e371d8fa5bbadbc725c1d574"
EXPECTED_STABILITY_SPEC_FILE_SHA256 = EXPECTED_STABILITY_SPEC_SHA256
EXPECTED_TOTAL_JOBS = 2022
EXPECTED_COMPLETED_POSE_BACKED_JOBS = 2021
EXPECTED_OPEN_COUNTS = {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32}
EXPECTED_OPEN_ROWS = 258
EXPECTED_OPEN_JOBS = 1548
SEALED_SPLIT = "PROSPECTIVE_COMPUTATIONAL_TEST"
EXPECTED_SEALED_ROWS = 32
SOURCE_FAILED_GATE = "candidate_threshold_sensitivity"
EXPECTED_GATE_NAMES = frozenset(
    {
        "all_jobs_terminal",
        "all_successful_jobs_have_minimum_pose_models",
        "candidate_threshold_sensitivity",
        "complete_2x2_scoring",
        "control_model_robustness",
        "control_native_cross_support_agreement",
        "control_seed_class_reproducibility",
        "controls_47_same_protocol",
        "destructive_control_strict_a_retention",
        "manifest_bound_pose_evidence",
        "minimum_completed_seeds_per_entity_conformation",
        "positive_control_robust_support",
        "protocol_validation",
        "row_artifacts_present",
    }
)
REQUIRED_TRAINER_FIELDS = (
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
)
GENERIC_PRIOR_FIELDS = (
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
PRIMARY_TARGET = "R_dual_min"
OUTPUT_BASENAME = "v4d_dev1_open258_continuous_geometry.tsv"
AUDIT_BASENAME = OUTPUT_BASENAME + ".audit.json"
SOURCE_RECEIPT_BASENAME = "v4d_dev1_source_failure_receipt.json"
RELEASE_RECEIPT_BASENAME = "v4d_dev1_release_receipt.json"
CHECKSUM_BASENAME = "SHA256SUMS"
ARCHIVE_BASENAME = "v4d_dev1_open258_delivery_v1.tar.gz"
ARCHIVE_SHA_BASENAME = ARCHIVE_BASENAME + ".sha256"
PAYLOAD_BASENAMES = (
    OUTPUT_BASENAME,
    AUDIT_BASENAME,
    SOURCE_RECEIPT_BASENAME,
    RELEASE_RECEIPT_BASENAME,
)
FORBIDDEN_FORMAL_STATUS_STRINGS = frozenset(
    {
        "PASS_OPEN258_TEACHER_READY_TEST32_SEALED",
        "PASS_V4_D_SURROGATE_V3_COMPLETE_TEST32_SEALED",
        "COMPLETE_V4_D_SURROGATE_TRAINING_TEST32_SEALED",
        "COMPLETE_V4_F_96_PREDICTIONS_FROZEN",
    }
)
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class Dev1BuildError(RuntimeError):
    """A fail-closed DEV1 build error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Dev1BuildError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def strict_json_load(path: Path, label: str) -> Any:
    require_regular_file(path, label)

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in output, f"duplicate_json_key:{label}:{key}")
            output[key] = value
        return output

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Dev1BuildError(f"invalid_json:{label}:{exc}") from exc


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise Dev1BuildError(f"missing_file:{label}:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"not_regular_or_is_symlink:{label}:{path}")


def require_real_directory(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise Dev1BuildError(f"missing_directory:{label}:{path}") from exc
    require(stat.S_ISDIR(metadata.st_mode), f"not_real_directory:{label}:{path}")


def load_v1_helper(path: Path) -> Any:
    require_regular_file(path, "v1_formula_helper")
    require(sha256_file(path) == EXPECTED_V1_HELPER_SHA256, "v1_formula_helper_sha256_mismatch")
    spec = importlib.util.spec_from_file_location("phase2_v4_d_dev1_v1_formula_helper", path)
    require(spec is not None and spec.loader is not None, "unable_to_load_v1_formula_helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def gate_status(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return "INVALID"
    value = payload.get("status")
    if isinstance(value, str):
        return value
    passed = payload.get("passed")
    if passed is True:
        return "PASS"
    if passed is False:
        return "FAIL"
    return "MISSING"


def validate_source_evaluator(evaluator: Mapping[str, Any], evaluator_sha256: str) -> None:
    failures: list[str] = []
    if evaluator_sha256 != EXPECTED_EVALUATOR_SHA256:
        failures.append("evaluator_file_sha256_mismatch")
    if evaluator.get("status") != "FAIL":
        failures.append("source_evaluator_status_not_FAIL")
    if evaluator.get("unlockable") is not False:
        failures.append("source_evaluator_unlockable_not_false")
    if evaluator.get("evidence_mode") != "production_pose_backed":
        failures.append("source_evaluator_not_production_pose_backed")
    integer_expectations = {
        "job_count": EXPECTED_TOTAL_JOBS,
        "result_count": EXPECTED_TOTAL_JOBS,
        "completed_pose_backed_jobs": EXPECTED_COMPLETED_POSE_BACKED_JOBS,
    }
    for field, expected in integer_expectations.items():
        try:
            observed = int(evaluator.get(field, -1))
        except (TypeError, ValueError):
            observed = -1
        if observed != expected:
            failures.append(f"source_evaluator_{field}_mismatch")
    hash_expectations = {
        "job_manifest_sha256": EXPECTED_JOB_MANIFEST_SHA256,
        "job_results_sha256": EXPECTED_JOB_RESULTS_SHA256,
        "pose_scores_sha256": EXPECTED_POSE_SCORES_SHA256,
        "protocol_core_sha256": EXPECTED_PROTOCOL_CORE_SHA256,
        "protocol_lock_sha256": EXPECTED_PROTOCOL_LOCK_SHA256,
        "candidates_sha256": EXPECTED_SPLIT_MANIFEST_SHA256,
        "stability_gate_spec_sha256": EXPECTED_STABILITY_SPEC_SHA256,
    }
    for field, expected in hash_expectations.items():
        if evaluator.get(field) != expected:
            failures.append(f"source_evaluator_{field}_mismatch")
    gates = evaluator.get("gates")
    if not isinstance(gates, Mapping) or set(gates) != set(EXPECTED_GATE_NAMES):
        failures.append("source_evaluator_gate_set_mismatch")
        gates = {}
    failed = sorted(name for name, payload in gates.items() if gate_status(payload) != "PASS")
    if failed != [SOURCE_FAILED_GATE]:
        failures.append("source_evaluator_failed_gate_set_mismatch:" + ",".join(failed))
    if failures:
        raise Dev1BuildError("dev1_source_gate_failed:" + ",".join(failures))


def read_prior_csv(
    path: Path,
    *,
    expected_sha256: str,
    expected_candidates: Mapping[str, str],
) -> dict[str, dict[str, str]]:
    require_regular_file(path, "generic_prior")
    require(re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None, "generic_prior_expected_sha_invalid")
    require(sha256_file(path) == expected_sha256, "generic_prior_sha256_mismatch")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        require(tuple(reader.fieldnames or ()) == GENERIC_PRIOR_FIELDS, "generic_prior_header_invalid")
        rows = list(reader)
    require(bool(rows), "generic_prior_empty")
    by_id: dict[str, dict[str, str]] = {}
    for row in rows:
        candidate_id = row.get("candidate_id", "")
        require(candidate_id and candidate_id not in by_id, f"generic_prior_duplicate_or_empty_id:{candidate_id}")
        require(
            re.fullmatch(r"[0-9a-f]{64}", row.get("sequence_sha256", "")) is not None,
            f"generic_prior_sequence_sha_invalid:{candidate_id}",
        )
        by_id[candidate_id] = row
    require(set(by_id) == set(expected_candidates), "generic_prior_candidate_id_closure_failed")
    for candidate_id, expected_sequence_sha256 in expected_candidates.items():
        require(
            by_id[candidate_id]["sequence_sha256"] == expected_sequence_sha256,
            f"generic_prior_sequence_sha_mismatch:{candidate_id}",
        )
    return by_id


def add_generic_prior(
    rows: list[dict[str, Any]], by_id: Mapping[str, Mapping[str, str]]
) -> None:
    for row in rows:
        source = by_id[str(row["candidate_id"])]
        try:
            value = float(source.get("generic_binding_prior", ""))
        except (TypeError, ValueError) as exc:
            raise Dev1BuildError(f"generic_prior_invalid:{row['candidate_id']}") from exc
        require(math.isfinite(value) and 0.0 <= value <= 1.0, f"generic_prior_out_of_range:{row['candidate_id']}")
        row["generic_binding_prior"] = round(value, 9)
        row["generic_binding_model_uncertainty"] = ""
        if source.get("model_uncertainty", "") != "":
            try:
                uncertainty = float(source["model_uncertainty"])
            except (TypeError, ValueError) as exc:
                raise Dev1BuildError(f"generic_prior_uncertainty_invalid:{row['candidate_id']}") from exc
            require(math.isfinite(uncertainty) and uncertainty >= 0.0, f"generic_prior_uncertainty_out_of_range:{row['candidate_id']}")
            row["generic_binding_model_uncertainty"] = round(uncertainty, 9)


def canonical_id_hash(values: Sequence[str]) -> str:
    raw = json.dumps(sorted(values), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_selected_result_paths(results_root: Path, selected_jobs: Sequence[Mapping[str, str]]) -> None:
    require_real_directory(results_root, "results_root")
    require(len(selected_jobs) == EXPECTED_OPEN_JOBS, "selected_open_job_count_invalid")
    seen: set[str] = set()
    for job in selected_jobs:
        job_id = job.get("job_id", "")
        require(JOB_ID_RE.fullmatch(job_id) is not None, f"unsafe_job_id:{job_id}")
        require(job_id not in seen, f"duplicate_selected_job_id:{job_id}")
        seen.add(job_id)
        directory = results_root / job_id
        require_real_directory(directory, f"selected_job_directory:{job_id}")
        require_regular_file(directory / "job_result.json", f"selected_job_result:{job_id}")


def exact_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle, delimiter="\t")
        try:
            header = next(reader)
        except StopIteration as exc:
            raise Dev1BuildError("teacher_tsv_empty") from exc
    require(len(header) == len(set(header)), "teacher_duplicate_header")
    return header


def validate_teacher_rows(rows: list[dict[str, Any]]) -> None:
    require(len(rows) == EXPECTED_OPEN_ROWS, "teacher_row_count_not_258")
    ids = [str(row.get("candidate_id", "")) for row in rows]
    require(len(set(ids)) == EXPECTED_OPEN_ROWS and all(ids), "teacher_candidate_id_closure_failed")
    counts = {split: 0 for split in EXPECTED_OPEN_COUNTS}
    for row in rows:
        split = str(row.get("model_split", ""))
        require(split in counts, f"teacher_forbidden_split:{split}")
        counts[split] += 1
        for field in REQUIRED_TRAINER_FIELDS:
            require(field in row and str(row[field]) != "", f"teacher_required_field_missing:{field}")
        try:
            target = float(row.get(PRIMARY_TARGET, ""))
        except (TypeError, ValueError) as exc:
            raise Dev1BuildError(f"teacher_target_invalid:{row.get('candidate_id')}") from exc
        require(math.isfinite(target), f"teacher_target_nonfinite:{row.get('candidate_id')}")
    require(counts == EXPECTED_OPEN_COUNTS, f"teacher_split_counts_invalid:{counts}")


def create_release_artifacts(
    output_dir: Path,
    rows: list[dict[str, Any]],
    *,
    source_inputs: Mapping[str, Any],
    builder_sha256: str,
    prereg_sha256: str,
) -> dict[str, Any]:
    require(not output_dir.exists(), f"output_directory_already_exists:{output_dir}")
    outputs = output_dir / "outputs"
    outputs.mkdir(parents=True)
    teacher = outputs / OUTPUT_BASENAME
    helper_fields: list[str] = []
    seen_fields: set[str] = set()
    for row in rows:
        for field in row:
            if field not in seen_fields:
                seen_fields.add(field)
                helper_fields.append(field)
    with teacher.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=helper_fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    header = exact_header(teacher)
    require(set(REQUIRED_TRAINER_FIELDS) <= set(header), "teacher_header_missing_trainer_fields")
    require(PRIMARY_TARGET in header, "teacher_header_missing_primary_target")
    teacher_sha = sha256_file(teacher)
    source_receipt = outputs / SOURCE_RECEIPT_BASENAME
    write_json(
        source_receipt,
        {
            "schema_version": SCHEMA_VERSION,
            "status": "SOURCE_EVALUATOR_FAILED_DEV_USE_ONLY",
            "source_evaluator": {
                "status": "FAIL",
                "unlockable": False,
                "failed_gates": [SOURCE_FAILED_GATE],
                "sha256": EXPECTED_EVALUATOR_SHA256,
            },
            "source_terminal_jobs": {
                "total": EXPECTED_TOTAL_JOBS,
                "successful": EXPECTED_COMPLETED_POSE_BACKED_JOBS,
                "failed_max_attempts": 1,
            },
            "formal_v4_f_unlock_eligible": False,
            "claim_boundary": CLAIM_BOUNDARY,
        },
    )
    audit = outputs / AUDIT_BASENAME
    audit_payload = {
        "schema_version": SCHEMA_VERSION,
        "status": AUDIT_STATUS,
        "release": RELEASE_NAME,
        "track_id": TRACK_ID,
        "source_evaluator": {
            "status": "FAIL",
            "unlockable": False,
            "failed_gates": [SOURCE_FAILED_GATE],
            "sha256": EXPECTED_EVALUATOR_SHA256,
        },
        "sealed_data_boundary": {
            "model_split": SEALED_SPLIT,
            "candidate_rows": EXPECTED_SEALED_ROWS,
            "raw_test32_job_files_opened": 0,
            "test32_metric_values_read": 0,
            "test32_label_rows_emitted": 0,
            "v4_f_labels_read": False,
        },
        "inputs": dict(source_inputs),
        "output": {
            "path": f"outputs/{OUTPUT_BASENAME}",
            "row_count": EXPECTED_OPEN_ROWS,
            "split_counts": EXPECTED_OPEN_COUNTS,
            "exact_header": header,
            "sha256": teacher_sha,
        },
        "primary_target": PRIMARY_TARGET,
        "formal_v4_f_unlock_eligible": False,
        "non_authority": {
            "formal_completion_or_unlock_receipt_created": False,
            "formal_v4_f_unlock_eligible": False,
            "final_submission_authority": False,
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json(audit, audit_payload)
    release_receipt = outputs / RELEASE_RECEIPT_BASENAME
    receipt_payload = {
        "schema_version": SCHEMA_VERSION,
        "status": REMOTE_READY_STATUS,
        "release": RELEASE_NAME,
        "audit_status": AUDIT_STATUS,
        "development_only": True,
        "formal_v4_f_unlock_eligible": False,
        "row_count": EXPECTED_OPEN_ROWS,
        "split_counts": EXPECTED_OPEN_COUNTS,
        "sealed_data_boundary": audit_payload["sealed_data_boundary"],
        "source_evaluator_status": "FAIL",
        "source_evaluator_unlockable": False,
        "source_failed_gates": [SOURCE_FAILED_GATE],
        "teacher_sha256": teacher_sha,
        "teacher_audit_sha256": sha256_file(audit),
        "source_failure_receipt_sha256": sha256_file(source_receipt),
        "builder_sha256": builder_sha256,
        "preregistration_sha256": prereg_sha256,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json(release_receipt, receipt_payload)
    checksum = outputs / CHECKSUM_BASENAME
    checksum.write_text(
        "".join(
            f"{sha256_file(outputs / name)}  outputs/{name}\n" for name in PAYLOAD_BASENAMES
        ),
        encoding="ascii",
    )
    archive = output_dir / ARCHIVE_BASENAME
    with tarfile.open(archive, "x:gz") as bundle:
        for name in (*PAYLOAD_BASENAMES, CHECKSUM_BASENAME):
            bundle.add(outputs / name, arcname=f"outputs/{name}", recursive=False)
    archive_sha = sha256_file(archive)
    (output_dir / ARCHIVE_SHA_BASENAME).write_text(
        f"{archive_sha}  {ARCHIVE_BASENAME}\n", encoding="ascii"
    )
    return {
        "status": REMOTE_READY_STATUS,
        "archive": str(archive),
        "archive_sha256": archive_sha,
        "teacher_sha256": teacher_sha,
        "audit_sha256": sha256_file(audit),
        "release_receipt_sha256": sha256_file(release_receipt),
        "formal_v4_f_unlock_eligible": False,
        "test32_raw_open": 0,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preregistration", type=Path, default=root / "audits/phase2_v4_d_dev1_open258_preregistration.json")
    parser.add_argument("--v1-formula-helper", type=Path, default=Path(__file__).with_name("prepare_phase2_v4_d_open_teacher.py"))
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--job-manifest", type=Path, required=True)
    parser.add_argument("--job-results", type=Path, required=True)
    parser.add_argument("--pose-scores", type=Path, required=True)
    parser.add_argument("--protocol-core-lock", type=Path, required=True)
    parser.add_argument("--protocol-lock", type=Path, required=True)
    parser.add_argument("--stability-spec", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--evaluator", type=Path, required=True)
    parser.add_argument("--generic-prior", type=Path, required=True)
    parser.add_argument("--expected-generic-prior-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    require_regular_file(args.preregistration, "preregistration")
    prereg_sha = sha256_file(args.preregistration)
    require(prereg_sha == EXPECTED_PREREG_SHA256, "preregistration_sha256_mismatch")
    prereg = strict_json_load(args.preregistration, "preregistration")
    require(
        prereg.get("status") == "FROZEN_POSTHOC_BEFORE_DEV1_RAW_OPEN_EXTRACTION_OR_REMOTE_EXECUTION",
        "preregistration_status_invalid",
    )
    helper = load_v1_helper(args.v1_formula_helper)
    for path, label, expected in (
        (args.split_manifest, "split_manifest", EXPECTED_SPLIT_MANIFEST_SHA256),
        (args.job_manifest, "job_manifest", EXPECTED_JOB_MANIFEST_SHA256),
        (args.job_results, "job_results_binding_only", EXPECTED_JOB_RESULTS_SHA256),
        (args.pose_scores, "pose_scores_binding_only", EXPECTED_POSE_SCORES_SHA256),
        (args.evaluator, "source_evaluator", EXPECTED_EVALUATOR_SHA256),
        (
            args.protocol_core_lock,
            "protocol_core_lock_file",
            EXPECTED_PROTOCOL_CORE_LOCK_FILE_SHA256,
        ),
        (args.protocol_lock, "protocol_lock_file", EXPECTED_PROTOCOL_LOCK_FILE_SHA256),
        (args.stability_spec, "stability_spec_file", EXPECTED_STABILITY_SPEC_FILE_SHA256),
    ):
        require_regular_file(path, label)
        require(sha256_file(path) == expected, f"{label}_sha256_mismatch")
    evaluator = strict_json_load(args.evaluator, "source_evaluator")
    require(isinstance(evaluator, Mapping), "source_evaluator_not_object")
    validate_source_evaluator(evaluator, EXPECTED_EVALUATOR_SHA256)

    split_rows = helper.read_tsv(args.split_manifest)
    selected_split = helper.select_open_split(split_rows)
    allowed_ids = {row["candidate_id"] for row in selected_split}
    sealed_ids = {row["candidate_id"] for row in split_rows if row["model_split"] == SEALED_SPLIT}
    require(len(allowed_ids) == EXPECTED_OPEN_ROWS, "open_candidate_id_count_invalid")
    require(len(sealed_ids) == EXPECTED_SEALED_ROWS and not (allowed_ids & sealed_ids), "sealed_candidate_id_closure_failed")
    all_jobs = helper.read_tsv(args.job_manifest)
    selected_jobs = helper.select_open_candidate_jobs(all_jobs, allowed_ids)
    require(all(job.get("entity_id") not in sealed_ids for job in selected_jobs), "sealed_job_admitted")
    validate_selected_result_paths(args.results_root, selected_jobs)
    raw_pose_rows, selected_results, raw_bindings, raw_evidence_hash_chain = helper.raw_pose_rows_for_jobs(
        args.results_root, selected_jobs
    )
    require(len(selected_results) == EXPECTED_OPEN_JOBS, "selected_raw_result_count_invalid")
    teacher_rows = helper.build_teacher_rows(
        selected_split, selected_jobs, selected_results, raw_pose_rows
    )
    expected_prior_candidates: dict[str, str] = {}
    for row in split_rows:
        candidate_id = str(row.get("candidate_id", ""))
        sequence_sha256 = str(row.get("sequence_sha256", ""))
        require(candidate_id and candidate_id not in expected_prior_candidates, "split_candidate_id_closure_failed")
        require(re.fullmatch(r"[0-9a-f]{64}", sequence_sha256) is not None, f"split_sequence_sha_invalid:{candidate_id}")
        expected_prior_candidates[candidate_id] = sequence_sha256
    require(len(expected_prior_candidates) == EXPECTED_OPEN_ROWS + EXPECTED_SEALED_ROWS, "split_candidate_count_invalid")
    prior = read_prior_csv(
        args.generic_prior,
        expected_sha256=args.expected_generic_prior_sha256,
        expected_candidates=expected_prior_candidates,
    )
    add_generic_prior(teacher_rows, prior)
    for row in teacher_rows:
        row["dev_release_track"] = TRACK_ID
        row["development_only"] = True
        row["source_evaluator_status"] = "FAIL"
        row["source_failed_gate"] = SOURCE_FAILED_GATE
        row["formal_v4_f_unlock_eligible"] = False
        row["claim_boundary"] = CLAIM_BOUNDARY
    validate_teacher_rows(teacher_rows)

    builder_sha = sha256_file(Path(__file__))
    source_inputs = {
        "split_manifest_sha256": EXPECTED_SPLIT_MANIFEST_SHA256,
        "job_manifest_sha256": EXPECTED_JOB_MANIFEST_SHA256,
        "job_results_sha256_binding_only": EXPECTED_JOB_RESULTS_SHA256,
        "pose_scores_sha256_binding_only": EXPECTED_POSE_SCORES_SHA256,
        "source_evaluator_sha256": EXPECTED_EVALUATOR_SHA256,
        "protocol_core_lock_file_sha256": EXPECTED_PROTOCOL_CORE_LOCK_FILE_SHA256,
        "protocol_lock_file_sha256": EXPECTED_PROTOCOL_LOCK_FILE_SHA256,
        "stability_spec_file_sha256": EXPECTED_STABILITY_SPEC_FILE_SHA256,
        "evaluator_protocol_core_payload_sha256": EXPECTED_PROTOCOL_CORE_SHA256,
        "evaluator_protocol_lock_payload_sha256": EXPECTED_PROTOCOL_LOCK_SHA256,
        "v1_formula_helper_sha256": EXPECTED_V1_HELPER_SHA256,
        "generic_prior_sha256": args.expected_generic_prior_sha256,
        "open_candidate_id_sha256": canonical_id_hash(list(allowed_ids)),
        "sealed_forbidden_candidate_id_sha256": canonical_id_hash(list(sealed_ids)),
        "selected_open_job_count": len(selected_jobs),
        "selected_raw_result_count": len(selected_results),
        "selected_successful_job_count": sum(
            str(row.get("state", "")).upper() in helper.SUCCESS_STATES for row in selected_results
        ),
        "selected_raw_result_sha256_chain": raw_evidence_hash_chain,
        "selected_raw_result_binding_count": len(raw_bindings),
        "raw_test32_job_files_opened": 0,
        "test32_metric_values_read": 0,
        "test32_label_rows_emitted": 0,
        "full_aggregate_value_rows_parsed": 0,
    }
    result = create_release_artifacts(
        args.output_dir,
        teacher_rows,
        source_inputs=source_inputs,
        builder_sha256=builder_sha,
        prereg_sha256=prereg_sha,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
