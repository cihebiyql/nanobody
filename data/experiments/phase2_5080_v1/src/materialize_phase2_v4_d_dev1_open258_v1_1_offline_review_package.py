#!/usr/bin/env python3
"""Materialize the V4-D-DEV1 V1.1 local-only implementation review package.

This command consumes only lightweight governance, code, frozen split, and
label-free prior artifacts.  It never opens SSH, raw Docking results, teacher
labels, or test32 geometry values and cannot authorize remote execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

EXP_DIR = Path("/mnt/d/work/抗体/data/experiments/phase2_5080_v1")
DEFAULT_FREEZE = EXP_DIR / "audits/phase2_v4_d_dev1_open258_v1_1_implementation_freeze_candidate.json"
DEFAULT_OUTPUT = EXP_DIR / "prepared/pvrig_v4_d_dev1_open258_v1_1/offline_review_package_v1"
FILES = {
    "preregistration": EXP_DIR / "audits/phase2_v4_d_dev1_open258_v1_1_recovery_preregistration.json",
    "fallback_evidence": EXP_DIR / "audits/phase2_v4_d_dev1_open258_v1_1_terminal_fallback_projection_evidence.json",
    "builder": EXP_DIR / "src/prepare_phase2_v4_d_dev1_open258_v1_1.py",
    "builder_tests": EXP_DIR / "src/test_prepare_phase2_v4_d_dev1_open258_v1_1.py",
    "node23_launcher": EXP_DIR / "src/run_phase2_v4_d_dev1_open258_v1_1_node23.sh",
    "v1_failure_receipt": EXP_DIR / "audits/phase2_v4_d_dev1_open258_v1_remote_runtime_failure_receipt.json",
    "v1_builder": EXP_DIR / "src/prepare_phase2_v4_d_dev1_open258.py",
    "v1_formula_helper": EXP_DIR / "src/prepare_phase2_v4_d_open_teacher.py",
    "upstream_tests_log": EXP_DIR / "audits/phase2_v4_d_dev1_open258_v1_1_recovery_tests.log",
    "delivery": EXP_DIR / "src/deliver_phase2_v4_d_dev1_open258_v1_1_from_node23.py",
    "delivery_tests": EXP_DIR / "src/test_deliver_phase2_v4_d_dev1_open258_v1_1_from_node23.py",
    "delivery_launcher": EXP_DIR / "src/launch_phase2_v4_d_dev1_open258_v1_1_delivery.sh",
    "delivery_tests_log": EXP_DIR / "audits/phase2_v4_d_dev1_open258_v1_1_delivery_tests.log",
    "materializer": EXP_DIR / "src/materialize_phase2_v4_d_dev1_open258_v1_1_offline_review_package.py",
    "materializer_tests": EXP_DIR / "src/test_materialize_phase2_v4_d_dev1_open258_v1_1_offline_review_package.py",
    "split_manifest": EXP_DIR / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv",
    "generic_prior_extract": EXP_DIR / "prepared/pvrig_v4_d_dev1_open258_v1/generic_prior_v1/v4d_dev1_fullqc290_label_free_generic_prior_v1.csv",
    "generic_prior_audit": EXP_DIR / "prepared/pvrig_v4_d_dev1_open258_v1/generic_prior_v1/v4d_dev1_fullqc290_label_free_generic_prior_v1.audit.json",
}
CANDIDATE_STATUS = "CANDIDATE_FREEZE_V1_1_BEFORE_REMOTE_OR_RAW_ACCESS"
PACKAGE_STATUS = "READY_FOR_INDEPENDENT_LOCAL_REVIEW_NOT_LAUNCH_AUTHORIZED_V1_1"
CLAIM_BOUNDARY = (
    "Local V4-D-DEV1 V1.1 implementation review package only. It contains no raw "
    "Docking results, teacher labels, test32 geometry values, model weights, launch "
    "authorization, formal V4-F unlock, binding, affinity, experimental blocking, "
    "Docking Gold, or final submission authority."
)


class PackageError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PackageError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_regular(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise PackageError(f"missing_file:{label}:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"not_regular_or_is_symlink:{label}:{path}")


def canonical_closure(entries: Mapping[str, Mapping[str, Any]]) -> str:
    raw = json.dumps(entries, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_candidate_freeze(freeze: Mapping[str, Any], files: Mapping[str, Path]) -> Mapping[str, Any]:
    require(freeze.get("status") == CANDIDATE_STATUS, "freeze_not_v1_1_candidate")
    require(freeze.get("remote_execution_started") is False, "freeze_remote_execution_started")
    require(freeze.get("remote_execution_authorized") is False, "freeze_remote_execution_authorized")
    for field in ("test32_raw_job_files_opened", "test32_metric_values_read", "test32_label_rows_emitted"):
        require(freeze.get(field) == 0, f"freeze_{field}_nonzero")
    require(freeze.get("source_evaluator_status") == "FAIL", "freeze_source_evaluator_status_not_FAIL")
    require(freeze.get("source_evaluator_unlockable") is False, "freeze_source_evaluator_unlockable_true")
    require(freeze.get("formal_v4_f_unlock_eligible") is False, "freeze_formal_v4f_unlock_true")
    require(freeze.get("final_submission_authority") is False, "freeze_final_submission_authority_true")
    recovery = freeze.get("single_terminal_failure_fallback") or {}
    expected_recovery = {
        "count": 1,
        "raw_success_count": 1547,
        "aggregate_terminal_rows_parsed": 1,
        "aggregate_metric_fields_parsed": 0,
        "pose_scores_exact_job_rows": 0,
        "state": "FAILED_MAX_ATTEMPTS",
    }
    for field, expected in expected_recovery.items():
        require(recovery.get(field) == expected, f"freeze_terminal_recovery_mismatch:{field}")
    frozen_files = freeze.get("files")
    require(isinstance(frozen_files, Mapping), "freeze_files_missing")
    require(set(frozen_files) == set(files), "freeze_file_key_set_mismatch")
    return frozen_files


def materialize(
    freeze_path: Path,
    output: Path,
    *,
    files: Mapping[str, Path] = FILES,
) -> dict[str, Any]:
    require_regular(freeze_path, "freeze")
    try:
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PackageError(f"freeze_invalid_json:{exc}") from exc
    require(isinstance(freeze, Mapping), "freeze_not_object")
    frozen_files = validate_candidate_freeze(freeze, files)
    require(not output.exists() and not output.is_symlink(), "output_already_exists")
    basenames = [path.name for path in files.values()]
    require(len(basenames) == len(set(basenames)), "source_basename_collision")
    output.mkdir(parents=True)
    copied: dict[str, dict[str, Any]] = {}
    try:
        for key, source in files.items():
            require_regular(source, key)
            entry = frozen_files.get(key) or {}
            require(isinstance(entry, Mapping), f"freeze_file_entry_invalid:{key}")
            expected_hash = entry.get("sha256")
            expected_size = entry.get("size")
            require(expected_hash == sha256_file(source), f"freeze_hash_mismatch:{key}")
            require(expected_size == source.stat().st_size, f"freeze_size_mismatch:{key}")
            target = output / source.name
            shutil.copyfile(source, target)
            require_regular(target, f"copied_{key}")
            require(sha256_file(target) == expected_hash, f"copied_hash_mismatch:{key}")
            copied[key] = {
                "filename": target.name,
                "sha256": expected_hash,
                "size": target.stat().st_size,
            }
        freeze_target = output / freeze_path.name
        shutil.copyfile(freeze_path, freeze_target)
        require_regular(freeze_target, "copied_freeze")
        copied["implementation_freeze_candidate"] = {
            "filename": freeze_target.name,
            "sha256": sha256_file(freeze_target),
            "size": freeze_target.stat().st_size,
        }
        readme = output / "README_DEV1_V1_1_OFFLINE_REVIEW.md"
        readme.write_text(
            "# V4-D-DEV1 V1.1 offline implementation review package\n\n"
            + CLAIM_BOUNDARY
            + "\n\nThe package binds the frozen 290-row split and label-free generic prior so "
              "the delivery validator can independently close every future 258-row teacher "
              "identity, sequence, provenance, prior, and prior-uncertainty field. The source "
              "V4-D evaluator remains FAIL/unlockable=false. V1.1 permits exactly 1547 raw "
              "successful open jobs plus one frozen terminal-failure projection with zero "
              "aggregate metric fields parsed.\n",
            encoding="utf-8",
        )
        copied["readme"] = {
            "filename": readme.name,
            "sha256": sha256_file(readme),
            "size": readme.stat().st_size,
        }
        receipt = {
            "schema_version": "phase2_v4_d_dev1_open258_v1_1_offline_review_package_v1",
            "status": PACKAGE_STATUS,
            "source_evaluator_status": "FAIL",
            "source_evaluator_unlockable": False,
            "source_failed_gates": ["candidate_threshold_sensitivity"],
            "single_terminal_failure_recovery": {
                "raw_success_count": 1547,
                "aggregate_terminal_failure_count": 1,
                "aggregate_metric_fields_parsed": 0,
            },
            "test32_raw_job_files_opened": 0,
            "test32_metric_values_read": 0,
            "test32_label_rows_included": 0,
            "test32_label_free_prior_rows_included": 32,
            "remote_execution_started": False,
            "remote_execution_authorized": False,
            "formal_v4_f_unlock_eligible": False,
            "final_submission_authority": False,
            "files": copied,
            "file_closure_sha256": canonical_closure(copied),
            "claim_boundary": CLAIM_BOUNDARY,
        }
        receipt_path = output / "PACKAGE_RECEIPT.json"
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        checksum_paths = sorted(
            (path for path in output.iterdir() if path.name != "SHA256SUMS"),
            key=lambda path: path.name,
        )
        require(all(stat.S_ISREG(path.lstat().st_mode) for path in checksum_paths), "package_nonregular_member")
        (output / "SHA256SUMS").write_text(
            "".join(f"{sha256_file(path)}  {path.name}\n" for path in checksum_paths),
            encoding="ascii",
        )
        return {
            **receipt,
            "package_path": str(output),
            "package_receipt_sha256": sha256_file(receipt_path),
        }
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    print(json.dumps(materialize(args.freeze, args.output), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
