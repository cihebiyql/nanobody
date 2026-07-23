#!/usr/bin/env python3
"""Create the one-time frozen bxcpu input anchor from a sealed Node1 bundle."""
from __future__ import annotations

import argparse
import json
import pathlib

import deployment_contract_v1 as contract


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=pathlib.Path, required=True)
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    parser.add_argument("--bundle-receipt", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--created-at", required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("frozen input anchor already exists; refusing overwrite")
    for path in (args.archive, args.manifest, args.bundle_receipt):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"input missing/non-regular/symlinked: {path}")
    receipt = contract.read_json(args.bundle_receipt)
    if receipt.get("status") != "SEALED_FOR_BXCPU_UPLOAD_NOT_SUBMITTED":
        raise ValueError("deployment bundle receipt is not sealed")
    if receipt.get("project") != contract.PROJECT:
        raise ValueError("deployment bundle project mismatch")
    if int(receipt.get("candidates", -1)) != contract.EXPECTED_CANDIDATES:
        raise ValueError("deployment bundle candidate count mismatch")
    if int(receipt.get("jobs", -1)) != contract.EXPECTED_JOBS:
        raise ValueError("deployment bundle job count mismatch")
    if receipt.get("shard_sizes") != list(contract.EXPECTED_SHARD_SIZES):
        raise ValueError("deployment bundle shard sizes mismatch")
    if receipt.get("docking_started") is not False or receipt.get("overlap1280_reuse_authorized") is not False:
        raise ValueError("deployment bundle violates execution/reuse boundary")
    manifest_sha = contract.sha256_file(args.manifest)
    if receipt.get("external_manifest", {}).get("sha256") != manifest_sha:
        raise ValueError("external manifest not bound by deployment receipt")
    source_receipt_sha = contract.require_hex64(
        receipt.get("source_handoff_receipt_sha256"), "source_handoff_receipt_sha256"
    )
    payload = {
        "schema_version": "pvrig.c2_missing6220.bxcpu_input_anchors.v1",
        "status": "SEALED_NODE1_HANDOFF_PASS_READY_FOR_BXCPU_PREFLIGHT",
        "created_at": args.created_at,
        "project": contract.PROJECT,
        "required_candidates": contract.EXPECTED_CANDIDATES,
        "required_jobs": contract.EXPECTED_JOBS,
        "archive_sha256": contract.sha256_file(args.archive),
        "archive_bytes": args.archive.stat().st_size,
        "handoff_receipt_sha256": source_receipt_sha,
        "job_manifest_sha256": manifest_sha,
        "deployment_bundle_receipt_sha256": contract.sha256_file(args.bundle_receipt),
        "docking_started": False,
        "overlap1280_reuse_authorized": False,
        "claim_boundary": (
            "Content anchors for a C2-only independent dual-receptor Docking input bundle; "
            "not a launch receipt and not biological evidence."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    contract.load_frozen_anchors(args.output)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
