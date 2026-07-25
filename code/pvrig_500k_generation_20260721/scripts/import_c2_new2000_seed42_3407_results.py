#!/usr/bin/env python3
"""Validate and merge the external C2-new2000 seed42/3407 results on Node1."""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import fcntl
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
from typing import Any


EXPECTED_CANDIDATES = 2_000
EXPECTED_JOBS_PER_PANEL = 8_000
EXPECTED_UNION_JOBS = 16_000
EXPECTED_PROTOCOL_CORE = (
    "8c55751f66ac2930ce115a9419321a2b2bed220b61af2e1671f7ac6e6a2e33b3"
)
CANONICAL_SEEDS = {"917", "1931"}
IMPORTED_SEEDS = {"42", "3407"}
EXPECTED_CONFORMATIONS = {"8x6b", "9e6y"}


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json_atomic(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    os.replace(temporary, path)


def read_tsv(path: pathlib.Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields:
        raise RuntimeError(f"missing TSV header: {path}")
    return fields, rows


def write_tsv_atomic(
    path: pathlib.Path, fields: list[str], rows: list[dict[str, str]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial.{os.getpid()}")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def candidate_map(rows: list[dict[str, str]]) -> dict[str, tuple[str, ...]]:
    output: dict[str, tuple[str, ...]] = {}
    for row in rows:
        candidate = row["entity_id"]
        metadata = (
            row["sequence_sha256"],
            row["monomer_sha256"],
            row["cdr1_range"],
            row["cdr2_range"],
            row["cdr3_range"],
            row["restraint_hash"],
        )
        previous = output.setdefault(candidate, metadata)
        if previous != metadata:
            raise RuntimeError(f"candidate metadata drift inside manifest: {candidate}")
    return output


def validate_manifest(
    rows: list[dict[str, str]], expected_seeds: set[str]
) -> None:
    if len(rows) != EXPECTED_JOBS_PER_PANEL:
        raise RuntimeError(f"expected 8000 rows, found {len(rows)}")
    if len({row["job_id"] for row in rows}) != len(rows):
        raise RuntimeError("job IDs are blank or duplicated")
    if {row["seed"] for row in rows} != expected_seeds:
        raise RuntimeError("seed set mismatch")
    if {row["conformation"] for row in rows} != EXPECTED_CONFORMATIONS:
        raise RuntimeError("receptor-conformation set mismatch")
    if {row["protocol_core_sha256"] for row in rows} != {
        EXPECTED_PROTOCOL_CORE
    }:
        raise RuntimeError("protocol core mismatch")
    candidates = candidate_map(rows)
    if len(candidates) != EXPECTED_CANDIDATES:
        raise RuntimeError(f"expected 2000 candidates, found {len(candidates)}")
    matrix = collections.Counter(
        (row["entity_id"], row["seed"], row["conformation"]) for row in rows
    )
    if len(matrix) != len(rows) or set(matrix.values()) != {1}:
        raise RuntimeError("candidate/seed/conformation matrix is not exact")
    if set(collections.Counter(row["entity_id"] for row in rows).values()) != {4}:
        raise RuntimeError("every candidate must have exactly four jobs")


def assert_no_collisions(
    source_results: pathlib.Path,
    target: pathlib.Path,
    imported_job_ids: set[str],
) -> None:
    for relative, suffix in (
        ("status/jobs", ".json"),
        ("results", ""),
        ("compressed_queue", ".tar.gz"),
        ("worker_logs", ".log"),
    ):
        source_dir = source_results / relative
        target_dir = target / relative
        target_dir.mkdir(parents=True, exist_ok=True)
        if relative == "results":
            source_names = {
                path.name for path in source_dir.iterdir() if path.is_dir()
            }
            target_names = {
                path.name for path in target_dir.iterdir() if path.is_dir()
            }
        else:
            source_names = {
                path.name[: -len(suffix)] if suffix else path.name
                for path in source_dir.glob(f"*{suffix}")
            }
            target_names = {
                path.name[: -len(suffix)] if suffix else path.name
                for path in target_dir.glob(f"*{suffix}")
            }
        unexpected = source_names - imported_job_ids
        if unexpected:
            raise RuntimeError(
                f"source {relative} contains non-manifest IDs: "
                f"{sorted(unexpected)[:3]}"
            )
        collisions = source_names & target_names
        if collisions:
            raise RuntimeError(
                f"refusing to overwrite {relative} collisions: "
                f"{sorted(collisions)[:3]}"
            )


def rsync_copy(source: pathlib.Path, target: pathlib.Path, log: pathlib.Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    command = [
        "rsync",
        "-a",
        "--ignore-existing",
        "--partial",
        "--human-readable",
        "--stats",
        "--log-file",
        str(log),
        str(source) + "/",
        str(target) + "/",
    ]
    subprocess.run(command, check=True)


def rsync_checksum_verify(source: pathlib.Path, target: pathlib.Path) -> None:
    result = subprocess.run(
        [
            "rsync",
            "-rcn",
            "--itemize-changes",
            str(source) + "/",
            str(target) + "/",
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.stdout.strip():
        raise RuntimeError(
            f"checksum parity failed for {source}: {result.stdout[:1000]}"
        )


def validate_imported_results(
    rows: list[dict[str, str]], target: pathlib.Path
) -> dict[str, Any]:
    states: collections.Counter[str] = collections.Counter()
    by_seed_receptor: collections.Counter[tuple[str, str, str]] = (
        collections.Counter()
    )
    missing: list[str] = []
    mismatches: list[str] = []
    for row in rows:
        job_id = row["job_id"]
        status_path = target / "status/jobs" / f"{job_id}.json"
        if not status_path.is_file():
            missing.append(f"status:{job_id}")
            continue
        status = read_json(status_path)
        state = str(status.get("status", ""))
        states[state] += 1
        by_seed_receptor[(state, row["seed"], row["conformation"])] += 1
        if status.get("job_id") not in (None, job_id):
            mismatches.append(f"status_job_id:{job_id}")
        if status.get("job_hash") not in (None, row["job_hash"]):
            mismatches.append(f"status_job_hash:{job_id}")
        if state == "SUCCESS":
            result_path = target / "results" / job_id / "job_result.json"
            compact_path = target / "compressed_queue" / f"{job_id}.tar.gz"
            if not result_path.is_file():
                missing.append(f"result:{job_id}")
                continue
            if not compact_path.is_file():
                missing.append(f"compact:{job_id}")
                continue
            result = read_json(result_path)
            if result.get("state") != "SUCCESS":
                mismatches.append(f"result_state:{job_id}")
            if result.get("job_id") not in (None, job_id):
                mismatches.append(f"result_job_id:{job_id}")
            if result.get("job_hash") != row["job_hash"]:
                mismatches.append(f"result_job_hash:{job_id}")
            if result.get("protocol_core_sha256") != EXPECTED_PROTOCOL_CORE:
                mismatches.append(f"result_protocol:{job_id}")
        elif state == "FAILED":
            if int(status.get("attempts", 0) or 0) < 2:
                mismatches.append(f"failure_attempts:{job_id}")
        else:
            mismatches.append(f"nonterminal_status:{job_id}:{state}")
    if missing or mismatches:
        raise RuntimeError(
            "import validation failed: "
            f"missing={missing[:5]} mismatches={mismatches[:5]}"
        )
    return {
        "states": dict(sorted(states.items())),
        "by_seed_receptor": {
            "|".join(key): value
            for key, value in sorted(by_seed_receptor.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=pathlib.Path,
        default=pathlib.Path(
            "/data/rli/PVRIG/"
            "pvrig_c2_new2000_seed42_3407_hpc_results_20260724"
        ),
    )
    parser.add_argument(
        "--canonical-package",
        type=pathlib.Path,
        default=pathlib.Path(
            "/data1/qlyu/projects/pvrig_top7500_c2_gap_recovery_v1_20260723/"
            "c2_new6220_split4220_2000_dualreceptor_2seed_handoffs_v2/"
            "c2_new2000_dualreceptor_2seed_handoff_v2"
        ),
    )
    parser.add_argument(
        "--target",
        type=pathlib.Path,
        default=pathlib.Path(
            "/data1/qlyu/projects/"
            "pvrig_c2_new6220_dualreceptor_2seed_docking_results_v1_20260723/"
            "c2_new2000"
        ),
    )
    args = parser.parse_args()

    lock_path = args.target / ".seed42_3407_import.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = lock_path.open("w")
    fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

    source_manifest = args.source / "project_v2/manifests/docking_jobs.tsv"
    canonical_manifest = args.canonical_package / "manifests/docking_jobs.tsv"
    canonical_fields, canonical_rows = read_tsv(canonical_manifest)
    imported_fields, imported_rows = read_tsv(source_manifest)
    if canonical_fields != imported_fields:
        raise RuntimeError("canonical/imported manifest headers differ")
    validate_manifest(canonical_rows, CANONICAL_SEEDS)
    validate_manifest(imported_rows, IMPORTED_SEEDS)
    if candidate_map(canonical_rows) != candidate_map(imported_rows):
        raise RuntimeError("the imported candidates are not the canonical new2000 set")

    imported_job_ids = {row["job_id"] for row in imported_rows}
    canonical_job_ids = {row["job_id"] for row in canonical_rows}
    if imported_job_ids & canonical_job_ids:
        raise RuntimeError("canonical and imported job IDs overlap")

    source_results = args.source / "results"
    assert_no_collisions(source_results, args.target, imported_job_ids)
    in_progress = {
        "schema_version": "pvrig.c2_new2000.seed42_3407.import_state.v1",
        "status": "IMPORT_IN_PROGRESS_NOT_FOR_AGGREGATION",
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": str(args.source),
        "source_manifest_sha256": sha256(source_manifest),
        "canonical_manifest_sha256": sha256(canonical_manifest),
    }
    write_json_atomic(args.target / "reports/SEED42_3407_IMPORT_STATE.json", in_progress)

    log_dir = args.target / "reports/seed42_3407_import_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    for relative in (
        "status/jobs",
        "results",
        "compressed_queue",
        "worker_logs",
    ):
        rsync_copy(
            source_results / relative,
            args.target / relative,
            log_dir / f"{relative.replace('/', '_')}.rsync.log",
        )

    import_metadata = args.target / "imports/seed42_3407_20260724"
    import_metadata.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.source / "LOCAL_IMPORT_AUDIT.json", import_metadata)
    shutil.copytree(
        args.source / "project_v2",
        import_metadata / "project_v2",
        dirs_exist_ok=True,
    )
    shutil.copytree(
        source_results / "markers",
        import_metadata / "markers",
        dirs_exist_ok=True,
    )

    for relative in ("status/jobs", "results", "compressed_queue", "worker_logs"):
        rsync_checksum_verify(source_results / relative, args.target / relative)

    result_summary = validate_imported_results(imported_rows, args.target)
    union_rows = canonical_rows + imported_rows
    if len(union_rows) != EXPECTED_UNION_JOBS:
        raise RuntimeError("union row count is not 16000")
    if len({row["job_id"] for row in union_rows}) != EXPECTED_UNION_JOBS:
        raise RuntimeError("union job IDs are not unique")
    if {row["seed"] for row in union_rows} != {
        "42",
        "917",
        "1931",
        "3407",
    }:
        raise RuntimeError("union seed set mismatch")
    if set(collections.Counter(row["entity_id"] for row in union_rows).values()) != {
        8
    }:
        raise RuntimeError("every union candidate must have exactly eight jobs")

    manifests = args.target / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    canonical_copy = manifests / "docking_jobs_seed917_1931.tsv"
    imported_copy = manifests / "docking_jobs_seed42_3407.tsv"
    union_path = manifests / "docking_jobs_union_917_1931_42_3407.tsv"
    shutil.copy2(canonical_manifest, canonical_copy)
    shutil.copy2(source_manifest, imported_copy)
    write_tsv_atomic(union_path, canonical_fields, union_rows)

    external_audit = read_json(args.source / "LOCAL_IMPORT_AUDIT.json")
    receipt = {
        "schema_version": "pvrig.c2_new2000.seed42_3407.merge_receipt.v1",
        "status": "PASS_SYNCED_AND_MERGED_AS_AUXILIARY_SEED_3407",
        "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "target": str(args.target),
        "candidate_identity": {
            "status": "PASS_EXACT_CANONICAL_NEW2000",
            "candidates": EXPECTED_CANDIDATES,
            "candidate_ids_equal": True,
            "sequence_monomer_cdr_restraint_metadata_equal": True,
        },
        "protocol": {
            "protocol_core_sha256": EXPECTED_PROTOCOL_CORE,
            "conformations": ["8x6b", "9e6y"],
            "canonical_seeds": [917, 1931],
            "imported_seeds": [42, 3407],
            "public_seed_3047_present": False,
            "warning": (
                "3407 is an auxiliary technical seed and MUST NOT be relabeled "
                "or treated as canonical public seed 3047."
            ),
        },
        "counts": {
            "union_jobs": EXPECTED_UNION_JOBS,
            "union_jobs_per_candidate": 8,
            "imported_jobs": EXPECTED_JOBS_PER_PANEL,
            "imported_success": result_summary["states"].get("SUCCESS", 0),
            "imported_technical_na": result_summary["states"].get("FAILED", 0),
            "remaining_public_seed3047_jobs": 4_000,
        },
        "imported_breakdown": result_summary["by_seed_receptor"],
        "hashes": {
            "canonical_manifest_sha256": sha256(canonical_copy),
            "imported_manifest_sha256": sha256(imported_copy),
            "union_manifest_sha256": sha256(union_path),
            "source_local_import_audit_sha256": sha256(
                args.source / "LOCAL_IMPORT_AUDIT.json"
            ),
        },
        "source_audit": external_audit,
        "copy_validation": (
            "PASS_RSYNC_CHECKSUM_PARITY_FOR_STATUS_RESULTS_ARCHIVES_AND_LOGS"
        ),
        "technical_failure_semantics": "NA_not_negative",
        "claim_boundary": (
            "Docking geometry evidence only; not binding, Kd, IC50, "
            "expression, purity, or experimental blocking."
        ),
    }
    receipt_path = args.target / "reports/SEED42_3407_MERGE_RECEIPT.json"
    write_json_atomic(receipt_path, receipt)
    write_json_atomic(
        args.target / "reports/SEED42_3407_IMPORT_STATE.json",
        {
            "schema_version": "pvrig.c2_new2000.seed42_3407.import_state.v1",
            "status": "COMPLETE_USE_MERGE_RECEIPT",
            "merge_receipt": str(receipt_path),
            "merge_receipt_sha256": sha256(receipt_path),
        },
    )
    print(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
