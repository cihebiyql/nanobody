#!/usr/bin/env python3
"""Recover DEV1 open258 with one frozen terminal-failure aggregate projection.

This v1.1 builder is separate from immutable v1. It opens raw job_result.json
for exactly 1547 successful open jobs and random-reads one pre-frozen terminal
failure row from the evaluator-bound job_results.tsv. Test32 remains sealed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tarfile
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "phase2_v4_d_dev1_open258_v1_1"
TRACK_ID = "V4-D-DEV1-V1.1"
AUDIT_STATUS = "RELEASED_DEV_ONLY_V1_1_SINGLE_TERMINAL_FAILURE_RECOVERY_TEST32_SEALED"
RELEASE_NAME = "OPEN_TRAIN_226_PLUS_OPEN_DEVELOPMENT_32_DEV_ONLY_V1_1"
REMOTE_READY_STATUS = "DEV1_V1_1_RELEASE_READY_TEST32_SEALED"
CLAIM_BOUNDARY = ("Post-hoc development-only sequence-to-computational-dual-docking continuous "
                  "geometry evidence; not a V4-D pass, formal test, Docking Gold, binding, affinity, "
                  "competition, experimental blocking, or final submission authority.")
EXPECTED_PREREG_SHA256 = "e57f08f266f53cc966d7dca34366310742ca4889a3c5173972105bb30734879d"
EXPECTED_FALLBACK_EVIDENCE_SHA256 = "36c7e11e3a727512d04a8797122efedc10b277bf58b5b997c09315209fdc6481"
EXPECTED_V1_FAILURE_RECEIPT_SHA256 = "247b6ec684a60ada85fa38834aa176e3f6a797a379938a5dabd5755bdd041720"
EXPECTED_V1_BUILDER_SHA256 = "04fd7addb8f1bc16f0cd3c0d113d9cbeb2cf23a25b5a39fe0113bfd2cf65d276"
EXPECTED_V1_HELPER_SHA256 = "8adb3c4e1de37bbaaf469dfb967176d2c49d40f353e21a3f028baa20ea8e4145"
EXPECTED_SPLIT_MANIFEST_SHA256 = "c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd"
EXPECTED_JOB_MANIFEST_SHA256 = "96fec07a5535615f50bff40ac48bb323a94213e06a7b12726ae5b4b2d1161737"
EXPECTED_JOB_RESULTS_SHA256 = "30c4227e15f6b049a9d9e9241ca34df30d38b247d14081b4ce7d3387fa2f3f25"
EXPECTED_POSE_SCORES_SHA256 = "7a2737160051c8fca8836b4086507e8f70d83cd692f87ffc17eaff8279c32681"
EXPECTED_EVALUATOR_SHA256 = "289542c58cfe72c380143a910b3adb75ba4e12f65899f71907a044314bedb674"
EXPECTED_PROTOCOL_CORE_LOCK_FILE_SHA256 = "767117dc2c506cfdfc83fce8e12931514d268941348d69a9abbda5a6500bdd24"
EXPECTED_PROTOCOL_LOCK_FILE_SHA256 = "56ef539cb54a1aba8e665ec5d62b3653088e2289e371d8fa5bbadbc725c1d574"
EXPECTED_STABILITY_SPEC_FILE_SHA256 = "fb01cdaa5939f2846b16e4e02a09903417cd6cea04d42350c4ed57f9ae7eb774"
EXPECTED_GENERIC_PRIOR_SHA256 = "21b4c6a38056d6777de5b5efbfcd5887b45098c637cab61489072d1e6e7783cd"
EXPECTED_OPEN_COUNTS = {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32}
EXPECTED_OPEN_ROWS = 258
EXPECTED_OPEN_JOBS = 1548
EXPECTED_RAW_OPEN_JOBS = 1547
SEALED_SPLIT = "PROSPECTIVE_COMPUTATIONAL_TEST"
EXPECTED_SEALED_ROWS = 32
SOURCE_FAILED_GATE = "candidate_threshold_sensitivity"
PRIMARY_TARGET = "R_dual_min"
FROZEN_FAILED_CANDIDATE_ID = "RFV1__PLDNANO_VHH_00322__A_CENTER__H3__B02__M00"
FROZEN_FAILED_JOB_ID = "CANDIDATE_RFV1__PLDNANO_VHH_00322__A_CENTER__H3__B02__M00_8x6b_s3253_447e4cf0dc26"
FROZEN_FAILED_JOB_HASH = "447e4cf0dc26af68a87636abd06fae3b69ca8a2522742776361084d9a84c512d"
FROZEN_FAILED_JOB_STATE = "FAILED_MAX_ATTEMPTS"
FALLBACK_TERMINAL_FIELDS = ("job_id", "job_hash", "state", "selected_model_count", "pose_score_model_count", "pose_backed_2x2")
EXPECTED_TERMINAL_IDENTITY = {
    "job_id": FROZEN_FAILED_JOB_ID, "entity_id": FROZEN_FAILED_CANDIDATE_ID,
    "entity_type": "candidate", "expected_behavior": "CANDIDATE_UNKNOWN",
    "conformation": "8x6b", "seed": "3253", "state": FROZEN_FAILED_JOB_STATE,
    "attempts": "2", "selected_model_count": "0", "pose_score_model_count": "0",
    "pose_backed_2x2": "false", "anomaly_flag": "false", "job_hash": FROZEN_FAILED_JOB_HASH,
}
SUPPORT_FIELDS_IGNORED = {"model_pair_consensus_fraction": "0.0", "model_native_cross_support_agreement_fraction": "0.0", "model_strict_a_fraction": "0.0"}
FORCED_EMPTY_METRIC_FIELDS = (
    "representative_model", "haddock_score", "air_energy", "native_class", "cross_class",
    "representative_pair_label", "native_hotspot_overlap", "cross_hotspot_overlap",
    "native_holdout_overlap", "cross_holdout_overlap", "native_total_occlusion",
    "cross_total_occlusion", "native_cdr3_occlusion", "cross_cdr3_occlusion",
    "native_cdr3_fraction", "cross_cdr3_fraction",
)
PRODUCTION_LAYOUT = {
    "file_sha256": EXPECTED_JOB_RESULTS_SHA256, "file_size": 774455,
    "header_length": 607, "header_sha256": "673de746a4c13b8582640fb476441a4b4d308e524956cc1c9f5db927ba7e8458",
    "row_offset": 205603, "row_length": 301,
    "row_sha256": "d2825fc278ccdffba0f360d8f6db49a78e95e39294f49d22463a097f2b72b204",
}
POSE_LAYOUT = {"file_sha256": EXPECTED_POSE_SCORES_SHA256, "file_size": 9684580, "header_length": 290,
               "header_sha256": "d8c83b34a1993e139b3f6d9c6d2a4b8c6a003dcb9df1f8d14fecc21a2980f084", "exact_job_id_row_count": 0}
OUTPUT_BASENAME = "v4d_dev1_open258_continuous_geometry_v1_1.tsv"
AUDIT_BASENAME = OUTPUT_BASENAME + ".audit.json"
SOURCE_RECEIPT_BASENAME = "v4d_dev1_source_failure_receipt_v1_1.json"
RELEASE_RECEIPT_BASENAME = "v4d_dev1_release_receipt_v1_1.json"
CHECKSUM_BASENAME = "SHA256SUMS"
ARCHIVE_BASENAME = "v4d_dev1_open258_delivery_v1_1.tar.gz"
ARCHIVE_SHA_BASENAME = ARCHIVE_BASENAME + ".sha256"

class Dev1V11BuildError(RuntimeError): pass

def require(condition: bool, message: str) -> None:
    if not condition: raise Dev1V11BuildError(message)

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""): h.update(b)
    return h.hexdigest()

def require_regular(path: Path, label: str) -> None:
    try: st = path.lstat()
    except FileNotFoundError as exc: raise Dev1V11BuildError(f"missing_file:{label}:{path}") from exc
    require(stat.S_ISREG(st.st_mode), f"not_regular_or_symlink:{label}:{path}")

def require_directory(path: Path, label: str) -> None:
    try: st = path.lstat()
    except FileNotFoundError as exc: raise Dev1V11BuildError(f"missing_directory:{label}:{path}") from exc
    require(stat.S_ISDIR(st.st_mode), f"not_real_directory:{label}:{path}")

def load_module(path: Path, label: str, expected_sha: str) -> Any:
    require_regular(path, label); require(sha256_file(path) == expected_sha, f"{label}_sha256_mismatch")
    spec = importlib.util.spec_from_file_location(f"dev1_v11_{label}", path)
    require(spec is not None and spec.loader is not None, f"{label}_load_failed")
    mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod); return mod

def validate_manifest_failure_job(job: Mapping[str, str]) -> None:
    expected = {"job_id": FROZEN_FAILED_JOB_ID, "job_hash": FROZEN_FAILED_JOB_HASH,
                "entity_id": FROZEN_FAILED_CANDIDATE_ID, "entity_type": "candidate",
                "conformation": "8x6b", "seed": "3253"}
    require(all(str(job.get(k, "")).lower() == v.lower() for k, v in expected.items()), "frozen_failed_manifest_identity_mismatch")

def partition_open_jobs_for_recovery(selected_jobs: Sequence[Mapping[str, str]]) -> tuple[list[dict[str, str]], dict[str, str]]:
    require(len(selected_jobs) == EXPECTED_OPEN_JOBS, "selected_open_job_count_invalid")
    failed = [dict(j) for j in selected_jobs if j.get("job_id") == FROZEN_FAILED_JOB_ID]
    require(len(failed) == 1, "frozen_failed_job_count_not_one")
    validate_manifest_failure_job(failed[0])
    raw = [dict(j) for j in selected_jobs if j.get("job_id") != FROZEN_FAILED_JOB_ID]
    require(len(raw) == EXPECTED_RAW_OPEN_JOBS, "raw_open_job_count_not_1547")
    require(len({j.get("job_id") for j in selected_jobs}) == EXPECTED_OPEN_JOBS, "duplicate_selected_job_id")
    return raw, failed[0]

def validate_recovery_result_paths(results_root: Path, raw_jobs: Sequence[Mapping[str, str]], failure_job: Mapping[str, str]) -> None:
    require_directory(results_root, "results_root"); require(len(raw_jobs) == EXPECTED_RAW_OPEN_JOBS, "raw_open_job_count_not_1547")
    for job in raw_jobs:
        job_id = str(job.get("job_id", "")); require(re.fullmatch(r"[A-Za-z0-9_.-]+", job_id) is not None, f"unsafe_job_id:{job_id}")
        require_directory(results_root / job_id, f"raw_job_directory:{job_id}")
        require_regular(results_root / job_id / "job_result.json", f"raw_job_result_missing:{job_id}")
    fallback_path = results_root / str(failure_job["job_id"]) / "job_result.json"
    require(not fallback_path.exists() and not fallback_path.is_symlink(), "frozen_failure_raw_job_result_unexpected")

def _read_bound_layout_bytes(path: Path, layout: Mapping[str, Any], label: str, *, include_row: bool) -> tuple[bytes, bytes | None]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try: fd = os.open(path, flags)
    except OSError as exc: raise Dev1V11BuildError(f"unable_to_open_bound_file:{label}:{path}") from exc
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode), f"not_regular_or_symlink:{label}:{path}")
        require(before.st_size == int(layout["file_size"]), f"{label}_size_mismatch")
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block: break
            chunks.append(block)
        raw = b"".join(chunks)
        require(len(raw) == before.st_size, f"{label}_snapshot_size_mismatch")
        require(hashlib.sha256(raw).hexdigest() == layout["file_sha256"], f"{label}_sha256_mismatch")
        header = raw[: int(layout["header_length"])]
        require(len(header) == int(layout["header_length"]), f"{label}_header_short")
        require(hashlib.sha256(header).hexdigest() == layout["header_sha256"], f"{label}_header_sha256_mismatch")
        row = None
        if include_row:
            start = int(layout["row_offset"])
            row = raw[start : start + int(layout["row_length"])]
            require(len(row) == int(layout["row_length"]), "fallback_row_short")
            require(hashlib.sha256(row).hexdigest() == layout["row_sha256"], "fallback_row_sha256_mismatch")
        after = os.fstat(fd)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        require(identity(before) == identity(after), f"{label}_changed_during_read")
        return header, row
    finally: os.close(fd)

def _validate_layout_file(path: Path, layout: Mapping[str, Any], label: str) -> bytes:
    return _read_bound_layout_bytes(path, layout, label, include_row=False)[0]

def read_frozen_terminal_failure(path: Path, manifest_job: Mapping[str, str], *, layout: Mapping[str, Any] = PRODUCTION_LAYOUT) -> tuple[dict[str, str], dict[str, Any]]:
    validate_manifest_failure_job(manifest_job)
    header_raw, row_raw = _read_bound_layout_bytes(path, layout, "job_results", include_row=True)
    require(row_raw is not None, "fallback_row_missing")
    try:
        header = header_raw.decode("utf-8").rstrip("\n").split("\t")
        values = row_raw.decode("utf-8").rstrip("\n").split("\t")
    except UnicodeDecodeError as exc: raise Dev1V11BuildError("fallback_utf8_invalid") from exc
    require(len(header) == len(values) and len(header) == len(set(header)), "fallback_header_row_shape_invalid")
    projected = dict(zip(header, values))
    for field, expected in EXPECTED_TERMINAL_IDENTITY.items():
        require(projected.get(field) == expected, f"fallback_{field}_mismatch")
    for field, expected in SUPPORT_FIELDS_IGNORED.items():
        require(projected.get(field) == expected, f"fallback_ignored_support_field_mismatch:{field}")
    for field in FORCED_EMPTY_METRIC_FIELDS:
        require(projected.get(field) == "", f"fallback_metric_field_nonempty:{field}")
    terminal = {field: projected[field] for field in FALLBACK_TERMINAL_FIELDS}
    return terminal, {"aggregate_terminal_rows_parsed": 1, "aggregate_metric_fields_parsed": 0,
                      "fallback_row_sha256": layout["row_sha256"], "pose_scores_exact_failed_job_row_count": 0}

def validate_pose_scores_frozen_zero(path: Path, *, layout: Mapping[str, Any] = POSE_LAYOUT) -> dict[str, Any]:
    _validate_layout_file(path, layout, "pose_scores")
    require(layout.get("exact_job_id_row_count") == 0, "pose_scores_failed_job_row_count_not_zero")
    return {"pose_scores_exact_failed_job_row_count": 0, "pose_scores_metric_values_parsed": 0}

def validate_v1_failure_receipt(path: Path) -> dict[str, Any]:
    require_regular(path, "v1_failure_receipt")
    require(sha256_file(path) == EXPECTED_V1_FAILURE_RECEIPT_SHA256, "v1_failure_receipt_sha256_mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(payload.get("status") == "FAILED_CLOSED_MISSING_RAW_RESULT_FOR_FROZEN_FAILED_MAX_ATTEMPTS_JOB", "v1_failure_receipt_status_invalid")
    require(payload.get("failed_job_id") == FROZEN_FAILED_JOB_ID, "v1_failure_receipt_job_id_invalid")
    require(payload.get("failed_job_state") == FROZEN_FAILED_JOB_STATE, "v1_failure_receipt_state_invalid")
    require(payload.get("teacher_artifacts_created") is False and payload.get("release_absent") is True, "v1_failure_receipt_artifact_state_invalid")
    require(payload.get("formal_v4_f_unlock_eligible") is False, "v1_failure_receipt_unlock_true")
    return payload

def collect_recovery_results(helper: Any, results_root: Path, selected_jobs: Sequence[Mapping[str, str]], job_results: Path, *, layout: Mapping[str, Any] = PRODUCTION_LAYOUT):
    raw_jobs, failure = partition_open_jobs_for_recovery(selected_jobs)
    validate_recovery_result_paths(results_root, raw_jobs, failure)
    poses, raw_results, bindings, raw_chain = helper.raw_pose_rows_for_jobs(results_root, raw_jobs)
    require(len(raw_results) == EXPECTED_RAW_OPEN_JOBS, "raw_result_count_not_1547")
    raw_by_id = {r.get("job_id"): r for r in raw_results}; require(len(raw_by_id) == EXPECTED_RAW_OPEN_JOBS, "raw_result_id_closure_failed")
    for job in raw_jobs:
        result = raw_by_id.get(job["job_id"]); require(result is not None and result.get("job_hash") == job.get("job_hash"), f"raw_result_hash_closure_failed:{job['job_id']}")
        require(str(result.get("state", "")).upper() in helper.SUCCESS_STATES, f"second_nonsuccess_open_job_forbidden:{job['job_id']}")
    terminal, evidence = read_frozen_terminal_failure(job_results, failure, layout=layout)
    results = [*raw_results, terminal]
    require(len(results) == EXPECTED_OPEN_JOBS, "combined_result_count_not_1548")
    evidence.update({"raw_job_result_count": EXPECTED_RAW_OPEN_JOBS, "aggregate_terminal_failure_count": 1,
                     "combined_result_count": EXPECTED_OPEN_JOBS, "raw_result_sha256_chain": raw_chain,
                     "raw_binding_count": len(bindings)})
    return poses, results, bindings, evidence

def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def create_release_artifacts(output_dir: Path, rows: list[dict[str, Any]], *, source_inputs: Mapping[str, Any], builder_sha256: str, prereg_sha256: str) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), "output_directory_exists")
    outputs = output_dir / "outputs"; outputs.mkdir(parents=True)
    fields=[]; seen=set()
    for row in rows:
        for field in row:
            if field not in seen: seen.add(field); fields.append(field)
    teacher=outputs/OUTPUT_BASENAME
    with teacher.open("x", newline="", encoding="utf-8") as handle:
        writer=csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    teacher_sha=sha256_file(teacher)
    source=outputs/SOURCE_RECEIPT_BASENAME
    _write_json(source,{"schema_version":SCHEMA_VERSION,"status":"SOURCE_EVALUATOR_FAILED_DEV_USE_ONLY_V1_1","source_evaluator":{"status":"FAIL","unlockable":False,"failed_gates":[SOURCE_FAILED_GATE],"sha256":EXPECTED_EVALUATOR_SHA256},"terminal_jobs":{"raw_success":1547,"aggregate_terminal_failure":1},"formal_v4_f_unlock_eligible":False,"claim_boundary":CLAIM_BOUNDARY})
    audit=outputs/AUDIT_BASENAME
    boundary={"model_split":SEALED_SPLIT,"candidate_rows":32,"raw_test32_job_files_opened":0,"test32_metric_values_read":0,"test32_label_rows_emitted":0}
    _write_json(audit,{"schema_version":SCHEMA_VERSION,"status":AUDIT_STATUS,"release":RELEASE_NAME,"track_id":TRACK_ID,"source_evaluator":{"status":"FAIL","unlockable":False,"failed_gates":[SOURCE_FAILED_GATE],"sha256":EXPECTED_EVALUATOR_SHA256},"single_terminal_failure_recovery":{"job_id":FROZEN_FAILED_JOB_ID,"job_hash":FROZEN_FAILED_JOB_HASH,"state":FROZEN_FAILED_JOB_STATE,"count":1,"raw_job_result_count":1547,"aggregate_terminal_rows_parsed":1,"aggregate_metric_fields_parsed":0,"pose_scores_exact_job_rows":0},"sealed_data_boundary":boundary,"inputs":dict(source_inputs),"output":{"path":f"outputs/{OUTPUT_BASENAME}","row_count":258,"split_counts":EXPECTED_OPEN_COUNTS,"exact_header":fields,"sha256":teacher_sha},"primary_target":PRIMARY_TARGET,"formal_v4_f_unlock_eligible":False,"non_authority":{"formal_completion_or_unlock_receipt_created":False,"formal_v4_f_unlock_eligible":False,"final_submission_authority":False},"claim_boundary":CLAIM_BOUNDARY})
    receipt=outputs/RELEASE_RECEIPT_BASENAME
    _write_json(receipt,{"schema_version":SCHEMA_VERSION,"status":REMOTE_READY_STATUS,"release":RELEASE_NAME,"audit_status":AUDIT_STATUS,"development_only":True,"formal_v4_f_unlock_eligible":False,"row_count":258,"split_counts":EXPECTED_OPEN_COUNTS,"sealed_data_boundary":boundary,"teacher_sha256":teacher_sha,"teacher_audit_sha256":sha256_file(audit),"source_failure_receipt_sha256":sha256_file(source),"builder_sha256":builder_sha256,"preregistration_sha256":prereg_sha256,"claim_boundary":CLAIM_BOUNDARY})
    payloads=(OUTPUT_BASENAME,AUDIT_BASENAME,SOURCE_RECEIPT_BASENAME,RELEASE_RECEIPT_BASENAME)
    (outputs/CHECKSUM_BASENAME).write_text("".join(f"{sha256_file(outputs/n)}  outputs/{n}\n" for n in payloads),encoding="ascii")
    archive=output_dir/ARCHIVE_BASENAME
    with tarfile.open(archive,"x:gz") as bundle:
        for name in (*payloads,CHECKSUM_BASENAME): bundle.add(outputs/name,arcname=f"outputs/{name}",recursive=False)
    archive_sha=sha256_file(archive); (output_dir/ARCHIVE_SHA_BASENAME).write_text(f"{archive_sha}  {ARCHIVE_BASENAME}\n",encoding="ascii")
    return {"status":REMOTE_READY_STATUS,"archive":str(archive),"archive_sha256":archive_sha,"teacher_sha256":teacher_sha,"formal_v4_f_unlock_eligible":False,"test32_raw_open":0}

def parse_args(argv=None):
    root=Path(__file__).resolve().parents[1]; p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--preregistration",type=Path,default=root/"audits/phase2_v4_d_dev1_open258_v1_1_recovery_preregistration.json")
    p.add_argument("--fallback-evidence",type=Path,default=root/"audits/phase2_v4_d_dev1_open258_v1_1_terminal_fallback_projection_evidence.json")
    p.add_argument("--v1-builder",type=Path,default=Path(__file__).with_name("prepare_phase2_v4_d_dev1_open258.py"))
    p.add_argument("--v1-failure-receipt",type=Path,default=root/"audits/phase2_v4_d_dev1_open258_v1_remote_runtime_failure_receipt.json")
    p.add_argument("--v1-formula-helper",type=Path,default=Path(__file__).with_name("prepare_phase2_v4_d_open_teacher.py"))
    for name in ("split-manifest","job-manifest","job-results","pose-scores","protocol-core-lock","protocol-lock","stability-spec","results-root","evaluator","generic-prior","output-dir"): p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--expected-generic-prior-sha256",default=EXPECTED_GENERIC_PRIOR_SHA256)
    return p.parse_args(argv)

def main(argv=None) -> int:
    a=parse_args(argv)
    for path,label,expected in ((a.preregistration,"preregistration",EXPECTED_PREREG_SHA256),(a.fallback_evidence,"fallback_evidence",EXPECTED_FALLBACK_EVIDENCE_SHA256),(a.v1_failure_receipt,"v1_failure_receipt",EXPECTED_V1_FAILURE_RECEIPT_SHA256),(a.split_manifest,"split_manifest",EXPECTED_SPLIT_MANIFEST_SHA256),(a.job_manifest,"job_manifest",EXPECTED_JOB_MANIFEST_SHA256),(a.job_results,"job_results",EXPECTED_JOB_RESULTS_SHA256),(a.pose_scores,"pose_scores",EXPECTED_POSE_SCORES_SHA256),(a.protocol_core_lock,"protocol_core_lock",EXPECTED_PROTOCOL_CORE_LOCK_FILE_SHA256),(a.protocol_lock,"protocol_lock",EXPECTED_PROTOCOL_LOCK_FILE_SHA256),(a.stability_spec,"stability_spec",EXPECTED_STABILITY_SPEC_FILE_SHA256),(a.evaluator,"evaluator",EXPECTED_EVALUATOR_SHA256),(a.generic_prior,"generic_prior",a.expected_generic_prior_sha256)):
        require_regular(path,label); require(sha256_file(path)==expected,f"{label}_sha256_mismatch")
    prereg=json.loads(a.preregistration.read_text()); evidence=json.loads(a.fallback_evidence.read_text())
    require(prereg.get("status")=="FROZEN_V1_1_RECOVERY_BEFORE_IMPLEMENTATION_OR_NEW_REMOTE_ACCESS","prereg_status_invalid")
    require(evidence.get("status")=="PASS_EXACT_SINGLE_OPEN_TERMINAL_FAILURE_PROJECTION","fallback_evidence_status_invalid")
    validate_v1_failure_receipt(a.v1_failure_receipt)
    base=load_module(a.v1_builder,"v1_builder",EXPECTED_V1_BUILDER_SHA256); helper=load_module(a.v1_formula_helper,"v1_formula_helper",EXPECTED_V1_HELPER_SHA256)
    evaluator=base.strict_json_load(a.evaluator,"source_evaluator"); base.validate_source_evaluator(evaluator,EXPECTED_EVALUATOR_SHA256)
    validate_pose_scores_frozen_zero(a.pose_scores)
    split_rows=helper.read_tsv(a.split_manifest); selected_split=helper.select_open_split(split_rows)
    allowed={r["candidate_id"] for r in selected_split}; sealed={r["candidate_id"] for r in split_rows if r["model_split"]==SEALED_SPLIT}
    jobs=helper.select_open_candidate_jobs(helper.read_tsv(a.job_manifest),allowed)
    require(all(j.get("entity_id") not in sealed for j in jobs),"sealed_job_admitted")
    poses,results,bindings,recovery=collect_recovery_results(helper,a.results_root,jobs,a.job_results)
    rows=helper.build_teacher_rows(selected_split,jobs,results,poses)
    expected_prior={r["candidate_id"]:r["sequence_sha256"] for r in split_rows}
    prior=base.read_prior_csv(a.generic_prior,expected_sha256=a.expected_generic_prior_sha256,expected_candidates=expected_prior); base.add_generic_prior(rows,prior)
    for row in rows:
        row.update({"dev_release_track":TRACK_ID,"development_only":True,"source_evaluator_status":"FAIL","source_failed_gate":SOURCE_FAILED_GATE,"formal_v4_f_unlock_eligible":False,"claim_boundary":CLAIM_BOUNDARY})
    base.validate_teacher_rows(rows)
    source_inputs={"split_manifest_sha256":EXPECTED_SPLIT_MANIFEST_SHA256,"job_manifest_sha256":EXPECTED_JOB_MANIFEST_SHA256,"job_results_sha256_binding_only":EXPECTED_JOB_RESULTS_SHA256,"pose_scores_sha256_binding_only":EXPECTED_POSE_SCORES_SHA256,"source_evaluator_sha256":EXPECTED_EVALUATOR_SHA256,"generic_prior_sha256":a.expected_generic_prior_sha256,"v1_failure_receipt_sha256":EXPECTED_V1_FAILURE_RECEIPT_SHA256,"v1_builder_sha256":EXPECTED_V1_BUILDER_SHA256,"v1_formula_helper_sha256":EXPECTED_V1_HELPER_SHA256,"fallback_evidence_sha256":EXPECTED_FALLBACK_EVIDENCE_SHA256,"raw_job_result_count":1547,"aggregate_terminal_rows_parsed":1,"aggregate_metric_fields_parsed":0,"pose_scores_exact_failed_job_row_count":0,"raw_test32_job_files_opened":0,"test32_metric_values_read":0,"test32_label_rows_emitted":0,"combined_result_count":1548,"raw_result_sha256_chain":recovery["raw_result_sha256_chain"],"raw_binding_count":len(bindings)}
    print(json.dumps(create_release_artifacts(a.output_dir,rows,source_inputs=source_inputs,builder_sha256=sha256_file(Path(__file__)),prereg_sha256=EXPECTED_PREREG_SHA256),sort_keys=True)); return 0

if __name__ == "__main__": raise SystemExit(main())
