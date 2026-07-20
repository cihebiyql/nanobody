#!/usr/bin/env python3
"""Run the frozen V29 snapshot builder on node23 and atomically publish locally."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


BASE = Path(__file__).resolve().parents[1]
BUILDER = BASE / "src" / "build_v29_open_snapshot_v1.py"
TEST = BASE / "tests" / "test_build_v29_open_snapshot_v1.py"
PREREG = BASE / "PREREGISTRATION.json"
TEST_FREEZE = BASE / "TEST_FREEZE.json"
OUTPUT = BASE / "prepared"
REMOTE_ROOT = "/data/qlyu/projects/pvrig_v29_docking25k_v1_20260720"
EXPECTED_PREREG_SHA256 = "07945d8d5a7d3f084949eb2b4f143486a22949f43b4095b9f836d08f6bcc1a23"
EXPECTED_TEST_SHA256 = "cfa76fa417a63a671a8e64a7c6dd398520dbcf96125501ba639f581593bde526"
EXPECTED_FILES = {
    "README_ZH.md",
    "SHA256SUMS",
    "V29_FROZEN_TEST_COUNT_ONLY.json",
    "V29_OPEN_SNAPSHOT_RECEIPT.json",
    "v29_open_candidate_split_manifest.tsv",
    "v29_open_development.tsv",
    "v29_open_paired_job_manifest.tsv",
    "v29_open_train.tsv",
    "v29_open_train_development.tsv",
}


class MaterializationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MaterializationError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def validate_archive_members(archive: tarfile.TarFile) -> None:
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        require(not path.is_absolute() and ".." not in path.parts, f"unsafe_archive_member:{member.name}")
        require(member.isfile() or member.isdir(), f"nonregular_archive_member:{member.name}")


def validate_delivery(staging: Path, builder_sha: str) -> dict[str, object]:
    files = {path.name for path in staging.iterdir() if path.is_file()}
    require(files == EXPECTED_FILES, f"output_file_set_mismatch:{sorted(files)}")
    sums: dict[str, str] = {}
    for line in (staging / "SHA256SUMS").read_text().splitlines():
        digest, filename = line.split("  ", 1)
        sums[filename] = digest
        require(sha256_file(staging / filename) == digest, f"output_sha_mismatch:{filename}")
    require(set(sums) == EXPECTED_FILES - {"SHA256SUMS"}, "sha256sum_file_set_mismatch")
    receipt = json.loads((staging / "V29_OPEN_SNAPSHOT_RECEIPT.json").read_text())
    require(receipt["status"] == "PASS_V29_ACTIVE_OPEN_SAME_SEED_SNAPSHOT", "receipt_status_invalid")
    require(receipt["implementation_sha256"] == builder_sha, "receipt_builder_sha_mismatch")
    require(receipt["preregistration_sha256"] == EXPECTED_PREREG_SHA256, "receipt_prereg_sha_mismatch")
    require(receipt["test_sha256"] == EXPECTED_TEST_SHA256, "receipt_test_sha_mismatch")
    require(receipt["campaign_terminal"] is False, "active_snapshot_marked_terminal")
    invariants = receipt["invariants"]
    require(invariants["same_seed_dual_receptor_required"] is True, "same_seed_gate_not_bound")
    require(invariants["R_dual_exact_min"] is True, "exact_min_gate_failed")
    require(invariants["frozen_test_label_rows_emitted"] == 0, "frozen_labels_emitted")
    require(invariants["frozen_test_identifiers_emitted"] == 0, "frozen_identifiers_emitted")
    require(receipt["component_compatibility"]["status"] == "PASS_BYTE_IDENTICAL_TO_V4H_V4I_FIXED_SCORING_COMPONENTS", "component_compatibility_failed")
    frozen = json.loads((staging / "V29_FROZEN_TEST_COUNT_ONLY.json").read_text())
    require(frozen["labels_emitted"] == 0 and frozen["candidate_identifiers_emitted"] == 0, "frozen_count_only_contract_failed")
    require("candidate_ids" not in frozen, "frozen_candidate_ids_present")
    combined = read_tsv(staging / "v29_open_train_development.tsv")
    split_manifest = read_tsv(staging / "v29_open_candidate_split_manifest.tsv")
    paired_jobs = read_tsv(staging / "v29_open_paired_job_manifest.tsv")
    require(len(combined) == receipt["counts"]["open_output_rows"], "combined_row_count_mismatch")
    require(len(split_manifest) == len(combined), "split_manifest_row_count_mismatch")
    require(len(paired_jobs) == receipt["counts"]["open_paired_job_manifest_rows"], "job_manifest_row_count_mismatch")
    require(all(row["model_split"] in {"train", "development"} for row in combined), "nonopen_split_in_teacher")
    require(all(row["model_split"] in {"train", "development"} for row in split_manifest), "nonopen_split_in_split_manifest")
    require(all(row["model_split"] in {"train", "development"} for row in paired_jobs), "nonopen_split_in_job_manifest")
    for row in combined:
        require(abs(float(row["R_dual_min"]) - min(float(row["R_8X6B"]), float(row["R_9E6Y"]))) <= 1e-12, f"row_exact_min_failed:{row['candidate_id']}")
        seeds8 = set(filter(None, row["successful_seed_ids_8X6B"].split(",")))
        seeds9 = set(filter(None, row["successful_seed_ids_9E6Y"].split(",")))
        paired = set(filter(None, row["paired_successful_seed_ids"].split(",")))
        require(seeds8 == seeds9 == paired, f"row_same_seed_failed:{row['candidate_id']}")
    return receipt


def main() -> int:
    require(not OUTPUT.exists() and not OUTPUT.is_symlink(), f"output_exists:{OUTPUT}")
    require(sha256_file(PREREG) == EXPECTED_PREREG_SHA256, "preregistration_hash_drift")
    require(sha256_file(TEST) == EXPECTED_TEST_SHA256, "test_hash_drift")
    freeze = json.loads(TEST_FREEZE.read_text())
    require(freeze["preregistration_sha256"] == EXPECTED_PREREG_SHA256, "test_freeze_prereg_mismatch")
    require(freeze["test_sha256"] == EXPECTED_TEST_SHA256, "test_freeze_test_mismatch")
    test_run = subprocess.run(
        ["python3", "-m", "unittest", str(TEST), "-v"],
        cwd=BASE.parents[3],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    require(test_run.returncode == 0 and "Ran 6 tests" in test_run.stdout and "OK" in test_run.stdout, "frozen_tests_failed")
    builder_sha = sha256_file(BUILDER)
    remote_command = (
        "set -euo pipefail; "
        "tmp=$(mktemp -d /tmp/pvrig-v29-open-snapshot.XXXXXX); "
        "trap 'rm -rf \"$tmp\"' EXIT; "
        f"python3 - --campaign-root {REMOTE_ROOT} --output-dir \"$tmp/out\" "
        f"--strict-component-audit --implementation-sha256 {builder_sha} "
        f"--preregistration-sha256 {EXPECTED_PREREG_SHA256} --test-sha256 {EXPECTED_TEST_SHA256} --quiet; "
        "tar -C \"$tmp/out\" -cf - ."
    )
    archive_path = BASE / f".v29_open_snapshot.{os.getpid()}.tar"
    try:
        with archive_path.open("xb") as archive_handle:
            process = subprocess.Popen(
                ["ssh.exe", "node23", remote_command],
                stdin=subprocess.PIPE,
                stdout=archive_handle,
                stderr=subprocess.PIPE,
            )
            _stdout, stderr = process.communicate(BUILDER.read_bytes())
        require(process.returncode == 0, f"remote_materialization_failed:{stderr.decode(errors='replace')[-4000:]}")
        with tempfile.TemporaryDirectory(prefix="v29-open-snapshot-", dir=BASE) as temporary:
            staging = Path(temporary) / "prepared"
            staging.mkdir()
            with tarfile.open(archive_path, "r:") as archive:
                validate_archive_members(archive)
                archive.extractall(staging)
            receipt = validate_delivery(staging, builder_sha)
            os.replace(staging, OUTPUT)
        deployment = {
            "schema_version": "pvrig_v29_open_snapshot_node23_materialization_v1",
            "status": "PASS_LOCAL_IMMUTABLE_DELIVERY",
            "remote_host": "node23",
            "remote_root": REMOTE_ROOT,
            "builder_sha256": builder_sha,
            "preregistration_sha256": EXPECTED_PREREG_SHA256,
            "test_sha256": EXPECTED_TEST_SHA256,
            "frozen_test_labels_emitted": 0,
            "prepared_receipt_sha256": sha256_file(OUTPUT / "V29_OPEN_SNAPSHOT_RECEIPT.json"),
            "prepared_sha256s_sha256": sha256_file(OUTPUT / "SHA256SUMS"),
            "counts": receipt["counts"],
        }
        deployment_path = BASE / "MATERIALIZATION_RECEIPT.json"
        temporary_path = deployment_path.with_name(f".{deployment_path.name}.{os.getpid()}.tmp")
        temporary_path.write_text(json.dumps(deployment, indent=2, sort_keys=True) + "\n")
        os.replace(temporary_path, deployment_path)
        print(json.dumps(deployment, sort_keys=True))
    finally:
        archive_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
