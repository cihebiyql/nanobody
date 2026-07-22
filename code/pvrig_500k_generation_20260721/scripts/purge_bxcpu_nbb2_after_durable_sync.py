#!/usr/bin/env python3
"""Remove redundant bxcpu NBB2 data after a durable Node1 copy is verified.

The caller must provide the local durable-archive acknowledgement produced by
the sync watcher.  Raw results are only removed after all remote archives and
their checksums have been validated and the NBB2/TNP chain is complete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def write_json_fsync(path: Path, payload: dict) -> None:
    with path.open("w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    fsync_directory(path.parent)


def atomic_commit_json(receipt: Path, payload: dict) -> None:
    commit = receipt.with_suffix(".json.commit")
    write_json_fsync(commit, payload)
    commit.replace(receipt)
    fsync_directory(receipt.parent)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--nbb2-job-id", required=True)
    parser.add_argument("--tnp-job-id", required=True)
    parser.add_argument("--expected-shards", type=int, required=True)
    parser.add_argument("--durable-node1-root", required=True)
    parser.add_argument("--durable-ack", type=Path, required=True)
    parser.add_argument("--node1-manifest-sha256", required=True)
    parser.add_argument("--revalidation-marker-sha256", required=True)
    args = parser.parse_args()

    campaign = args.campaign.resolve()
    status = campaign / "status"
    receipt = status / "REMOTE_PURGE_RECEIPT.json"
    partial = receipt.with_suffix(".json.partial")
    required = [
        args.durable_ack,
        status / "CHAIN_COMPLETE",
        campaign / f"aggregated_{args.nbb2_job_id}" / "COMPLETE.json",
        campaign / f"tnp_aggregated_{args.tnp_job_id}" / "READY.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"refusing purge; missing completion evidence: {missing}")

    try:
        durable_ack = json.loads(args.durable_ack.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"refusing purge; durable acknowledgement is not valid JSON: {exc}")
    expected_ack = {
        "status": "DURABLE_NODE1_REVALIDATED",
        "campaign": str(campaign),
        "durable_node1_root": args.durable_node1_root,
        "nbb2_job_id": args.nbb2_job_id,
        "tnp_job_id": args.tnp_job_id,
        "expected_shards": args.expected_shards,
        "node1_manifest_sha256": args.node1_manifest_sha256,
        "revalidation_marker_sha256": args.revalidation_marker_sha256,
    }
    mismatches = {
        key: {"expected": expected, "observed": durable_ack.get(key)}
        for key, expected in expected_ack.items()
        if durable_ack.get(key) != expected
    }
    if mismatches:
        raise SystemExit(f"refusing purge; durable acknowledgement is not bound to this sync: {mismatches}")
    if not isinstance(durable_ack.get("created_at_epoch"), (int, float)) or durable_ack["created_at_epoch"] <= 0:
        raise SystemExit("refusing purge; durable acknowledgement lacks a valid creation epoch")
    for label, digest in {
        "node1_manifest_sha256": args.node1_manifest_sha256,
        "revalidation_marker_sha256": args.revalidation_marker_sha256,
    }.items():
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.lower()):
            raise SystemExit(f"refusing purge; invalid {label}")

    durable_ack_sha256 = sha256(args.durable_ack)
    if receipt.is_file():
        payload = json.loads(receipt.read_text())
        idempotent_fields = {
            **{key: value for key, value in expected_ack.items() if key != "status"},
            "durable_ack_sha256": durable_ack_sha256,
        }
        if payload.get("status") == "PURGED_AFTER_DURABLE_NODE1_ACK" and all(
            payload.get(key) == value for key, value in idempotent_fields.items()
        ):
            partial.unlink(missing_ok=True)
            receipt.with_suffix(".json.commit").unlink(missing_ok=True)
            print(receipt)
            return 0
        raise SystemExit("refusing purge; existing receipt is not bound to the current acknowledgement")

    results = campaign / f"results_{args.nbb2_job_id}"
    archives = campaign / f"archives_{args.nbb2_job_id}"
    if partial.is_file():
        try:
            recovery = json.loads(partial.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            raise SystemExit(f"refusing purge recovery; invalid partial receipt: {exc}")
        recovery_expected = {
            **{key: value for key, value in expected_ack.items() if key != "status"},
            "durable_ack_sha256": durable_ack_sha256,
        }
        recovery_mismatches = {
            key: {"expected": value, "observed": recovery.get(key)}
            for key, value in recovery_expected.items()
            if recovery.get(key) != value
        }
        if recovery.get("status") not in {"PURGE_VALIDATED", "PURGED_AFTER_DURABLE_NODE1_ACK"} or recovery_mismatches:
            raise SystemExit(
                f"refusing purge recovery; partial receipt is not bound to this sync: {recovery_mismatches}"
            )
        if results.exists():
            shutil.rmtree(results)
        if archives.exists():
            shutil.rmtree(archives)
        if results.exists() or archives.exists():
            raise SystemExit("purge recovery did not remove both redundant directories")
        recovery["status"] = "PURGED_AFTER_DURABLE_NODE1_ACK"
        recovery["purged_at"] = datetime.now(timezone.utc).isoformat()
        recovery["recovered_from_partial_receipt"] = True
        atomic_commit_json(receipt, recovery)
        partial.unlink(missing_ok=True)
        print(receipt)
        return 0

    archive_records = []
    for shard in range(args.expected_shards):
        shard_id = f"{shard:03d}"
        archive = archives / f"node_{shard_id}.tar.gz"
        checksum = archives / f"node_{shard_id}.sha256"
        ready = archives / f"node_{shard_id}.READY.json"
        if not archive.is_file() or not checksum.is_file() or not ready.is_file():
            raise SystemExit(f"refusing purge; incomplete archive shard {shard_id}")
        expected_digest = checksum.read_text().split()[0]
        observed_digest = sha256(archive)
        if observed_digest != expected_digest:
            raise SystemExit(f"refusing purge; checksum mismatch for {archive}")
        archive_records.append(
            {
                "shard": shard_id,
                "archive": archive.name,
                "archive_bytes": archive.stat().st_size,
                "archive_sha256": observed_digest,
            }
        )

    payload = {
        "status": "PURGE_VALIDATED",
        "campaign": str(campaign),
        "nbb2_job_id": args.nbb2_job_id,
        "tnp_job_id": args.tnp_job_id,
        "expected_shards": args.expected_shards,
        "durable_node1_root": args.durable_node1_root,
        "durable_ack_sha256": durable_ack_sha256,
        "node1_manifest_sha256": args.node1_manifest_sha256,
        "revalidation_marker_sha256": args.revalidation_marker_sha256,
        "results_bytes_before_purge": tree_bytes(results),
        "archives_bytes_before_purge": tree_bytes(archives),
        "archives": archive_records,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json_fsync(partial, payload)

    if results.exists():
        shutil.rmtree(results)
    if archives.exists():
        shutil.rmtree(archives)
    if results.exists() or archives.exists():
        raise SystemExit("purge did not remove both redundant directories")

    payload["status"] = "PURGED_AFTER_DURABLE_NODE1_ACK"
    payload["purged_at"] = datetime.now(timezone.utc).isoformat()
    atomic_commit_json(receipt, payload)
    partial.unlink(missing_ok=True)
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
