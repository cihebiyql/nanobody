#!/usr/bin/env python3
"""Seal a validated Node1 C2 handoff into an eight-shard bxcpu bundle; never launch."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import uuid
from datetime import datetime, timezone

import deployment_contract_v1 as contract


def write_hashes(root: pathlib.Path, output: pathlib.Path) -> None:
    paths = sorted(
        path for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and path != output
    )
    with output.open("w", encoding="utf-8", newline="") as handle:
        for path in paths:
            handle.write(f"{contract.sha256_file(path)}  {path.relative_to(root).as_posix()}\n")


def prepare(
    handoff_root: pathlib.Path, output_root: pathlib.Path, created_at: str, *,
    expected_candidates: int = contract.EXPECTED_CANDIDATES,
    expected_jobs: int = contract.EXPECTED_JOBS,
    shard_count: int = contract.SHARD_COUNT,
) -> dict[str, object]:
    handoff_root = handoff_root.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        raise ValueError(f"output root already exists: {output_root}")
    receipt_path = handoff_root / "HANDOFF_RECEIPT.json"
    sums_path = handoff_root / "SHA256SUMS"
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise ValueError("HANDOFF_RECEIPT.json missing/non-regular/symlinked")
    if not sums_path.is_file() or sums_path.is_symlink():
        raise ValueError("SHA256SUMS missing/non-regular/symlinked")
    receipt = contract.read_json(receipt_path)
    contract.validate_handoff_receipt(
        receipt, expected_candidates=expected_candidates, expected_jobs=expected_jobs
    )
    verified_files = contract.verify_sha256_manifest(handoff_root, sums_path)
    manifest_rel = contract.safe_relative(receipt["outputs"]["job_manifest"]["path"])
    manifest_path = handoff_root.joinpath(*manifest_rel.parts)
    if contract.sha256_file(manifest_path) != receipt["outputs"]["job_manifest"]["sha256"]:
        raise ValueError("job manifest is not hash-bound by handoff receipt")
    fields, rows = contract.read_tsv(manifest_path)
    contract.validate_manifest_rows(
        rows, expected_candidates=expected_candidates, expected_jobs=expected_jobs
    )

    staging = output_root.with_name(f".{output_root.name}.staging.{os.getpid()}.{uuid.uuid4().hex}")
    try:
        shutil.copytree(handoff_root, staging, symlinks=False)
        shard_root = staging / "manifests/shards_recommended_8"
        shard_root.mkdir(parents=True)
        shards = contract.split_contiguous(rows, shard_count=shard_count)
        for index, shard_rows in enumerate(shards):
            contract.write_tsv(shard_root / f"shard_{index:02d}.tsv", fields, shard_rows)
        external_manifest = staging / f"{contract.PROJECT}.manifest.tsv"
        shutil.copyfile(manifest_path, external_manifest)

        bundle_receipt: dict[str, object] = {
            "schema_version": "pvrig.c2_missing6220.bxcpu_bundle.v1",
            "status": "SEALED_FOR_BXCPU_UPLOAD_NOT_SUBMITTED",
            "project": contract.PROJECT,
            "created_at": created_at,
            "candidates": expected_candidates,
            "jobs": expected_jobs,
            "shard_count": shard_count,
            "shard_sizes": [len(shard) for shard in shards],
            "seed": int(contract.SEED),
            "conformations": sorted(contract.CONFORMATIONS),
            "protocol_core_sha256": contract.PROTOCOL_CORE,
            "source_handoff_receipt_sha256": contract.sha256_file(receipt_path),
            "source_handoff_sha256_files_verified": verified_files,
            "job_manifest": {
                "path": manifest_rel.as_posix(),
                "sha256": contract.sha256_file(manifest_path),
            },
            "external_manifest": {
                "path": external_manifest.name,
                "sha256": contract.sha256_file(external_manifest),
            },
            "docking_started": False,
            "overlap1280_reuse_authorized": False,
            "claim_boundary": (
                "Sealed independent seed917 dual-receptor C2-only Docking inputs; "
                "no execution, binding, Kd, IC50, or experimental blocking claim."
            ),
        }
        bundle_receipt_path = staging / "DEPLOYMENT_BUNDLE_RECEIPT.json"
        bundle_receipt_path.write_text(json.dumps(bundle_receipt, indent=2, sort_keys=True) + "\n")
        write_hashes(staging, staging / "DEPLOYMENT_SHA256SUMS")
        staging.replace(output_root)
        return bundle_receipt
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-root", type=pathlib.Path, required=True)
    parser.add_argument("--output-root", type=pathlib.Path, required=True)
    parser.add_argument("--created-at", required=True)
    args = parser.parse_args()
    prepare(args.handoff_root, args.output_root, args.created_at)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
