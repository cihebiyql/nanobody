#!/usr/bin/env python3
"""Materialize the local-only V4-D-DEV1 implementation review package."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence


EXP_DIR = Path("/mnt/d/work/抗体/data/experiments/phase2_5080_v1")
DEFAULT_FREEZE = EXP_DIR / "audits/phase2_v4_d_dev1_open258_implementation_freeze_candidate.json"
DEFAULT_OUTPUT = EXP_DIR / "prepared/pvrig_v4_d_dev1_open258_v1/offline_review_package_v1"
FILES = {
    "preregistration": EXP_DIR / "audits/phase2_v4_d_dev1_open258_preregistration.json",
    "builder": EXP_DIR / "src/prepare_phase2_v4_d_dev1_open258.py",
    "v1_formula_helper": EXP_DIR / "src/prepare_phase2_v4_d_open_teacher.py",
    "delivery": EXP_DIR / "src/deliver_phase2_v4_d_dev1_open258_from_node23.py",
    "node23_launcher": EXP_DIR / "src/run_phase2_v4_d_dev1_open258_node23.sh",
    "delivery_launcher": EXP_DIR / "src/launch_phase2_v4_d_dev1_delivery_v1.sh",
    "builder_tests": EXP_DIR / "src/test_prepare_phase2_v4_d_dev1_open258.py",
    "delivery_tests": EXP_DIR / "src/test_deliver_phase2_v4_d_dev1_open258_from_node23.py",
    "freeze_tests": EXP_DIR / "src/test_phase2_v4_d_dev1_open258_freeze_contract.py",
    "generic_prior_materializer": EXP_DIR / "src/materialize_phase2_v4_d_dev1_generic_prior.py",
    "generic_prior_tests": EXP_DIR / "src/test_materialize_phase2_v4_d_dev1_generic_prior.py",
    "generic_prior_extract": EXP_DIR / "prepared/pvrig_v4_d_dev1_open258_v1/generic_prior_v1/v4d_dev1_fullqc290_label_free_generic_prior_v1.csv",
    "generic_prior_audit": EXP_DIR / "prepared/pvrig_v4_d_dev1_open258_v1/generic_prior_v1/v4d_dev1_fullqc290_label_free_generic_prior_v1.audit.json",
    "materializer": EXP_DIR / "src/materialize_phase2_v4_d_dev1_offline_review_package.py",
}
CLAIM_BOUNDARY = (
    "Local implementation-review package only. It contains no candidate labels, test32 "
    "Docking or geometry values, model weights, Docking results, launch authorization, or "
    "formal V4-F unlock. It includes a 290-row label-free generic-model prior input."
)


class PackageError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PackageError(message)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def require_regular(path: Path, label: str) -> None:
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode), f"not_regular:{label}:{path}")


def canonical_closure(entries: Mapping[str, Mapping[str, Any]]) -> str:
    raw = json.dumps(entries, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def materialize(freeze_path: Path, output: Path) -> dict[str, Any]:
    require_regular(freeze_path, "freeze")
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    require(
        freeze.get("status") == "CANDIDATE_FREEZE_BEFORE_REMOTE_OR_LABEL_ACCESS",
        "freeze_not_candidate",
    )
    require(freeze.get("remote_execution_started") is False, "remote_execution_started")
    require(freeze.get("test32_raw_job_files_opened") == 0, "test32_raw_open_nonzero")
    require(freeze.get("formal_v4_f_unlock_eligible") is False, "formal_v4f_unlock_true")
    frozen_files = freeze.get("files")
    require(isinstance(frozen_files, Mapping), "freeze_files_missing")
    require(not output.exists() and not output.is_symlink(), "output_already_exists")
    output.mkdir(parents=True)
    copied: dict[str, dict[str, Any]] = {}
    try:
        for key, source in FILES.items():
            require_regular(source, key)
            expected = (frozen_files.get(key) or {}).get("sha256")
            require(expected == digest(source), f"freeze_hash_mismatch:{key}")
            target = output / source.name
            shutil.copyfile(source, target)
            require_regular(target, f"copied_{key}")
            copied[key] = {
                "filename": target.name,
                "sha256": digest(target),
                "size": target.stat().st_size,
            }
        freeze_target = output / freeze_path.name
        shutil.copyfile(freeze_path, freeze_target)
        copied["implementation_freeze_candidate"] = {
            "filename": freeze_target.name,
            "sha256": digest(freeze_target),
            "size": freeze_target.stat().st_size,
        }
        readme = output / "README_DEV1_OFFLINE_REVIEW.md"
        readme.write_text(
            "# V4-D-DEV1 offline implementation review package\n\n"
            + CLAIM_BOUNDARY
            + "\n\nThe package includes the reviewed 290-row label-free generic-prior extract "
              "and its audit; those values are model inputs, not Docking labels. "
              "The source V4-D evaluator remains FAIL/unlockable=false because "
              "candidate_threshold_sensitivity failed. This package does not authorize SSH, "
              "raw-label extraction, model training, or formal V4-F publication.\n",
            encoding="utf-8",
        )
        copied["readme"] = {
            "filename": readme.name,
            "sha256": digest(readme),
            "size": readme.stat().st_size,
        }
        receipt = {
            "schema_version": "phase2_v4_d_dev1_offline_review_package_v1",
            "status": "READY_FOR_INDEPENDENT_LOCAL_REVIEW_NOT_LAUNCH_AUTHORIZED",
            "source_evaluator_status": "FAIL",
            "source_evaluator_unlockable": False,
            "source_failed_gates": ["candidate_threshold_sensitivity"],
            "test32_raw_job_files_opened": 0,
            "test32_metric_values_read": 0,
            "test32_label_free_generic_prior_rows_included": 32,
            "remote_execution_started": False,
            "formal_v4_f_unlock_eligible": False,
            "files": copied,
            "file_closure_sha256": canonical_closure(copied),
            "claim_boundary": CLAIM_BOUNDARY,
        }
        receipt_path = output / "PACKAGE_RECEIPT.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        checksum_paths = sorted(
            [path for path in output.iterdir() if path.name != "SHA256SUMS"],
            key=lambda path: path.name,
        )
        (output / "SHA256SUMS").write_text(
            "".join(f"{digest(path)}  {path.name}\n" for path in checksum_paths),
            encoding="ascii",
        )
        return {**receipt, "package_path": str(output), "package_receipt_sha256": digest(receipt_path)}
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    print(json.dumps(materialize(args.freeze, args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
