#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STAGE = Path("/mnt/d/work/抗体/node1/pvrig_c2_new6220_bxcpu_stage_20260723")
ARCHIVE_NAME = "pvrig_c2_new6220_dualreceptor_2seed_handoffs_v2_20260723.tar.gz"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    archive = STAGE / ARCHIVE_NAME
    deployment_files = [
        "bxcpu_c2_new6220_dualseed_eight_node_worker.sh",
        "compact_run_evidence.py",
        "run_slurm_preflight.sh",
        "run_terminal_audit.sh",
        "start_results_sync_sharded.sh",
        "sync_c2_new6220_results_incremental.py",
        "technical_audit_c2_new6220.py",
        "submit_after_top7500.sh",
        "inputs/ROOT_RECEIPT.json",
        "inputs/c2_new4220_HANDOFF_RECEIPT.json",
        "inputs/c2_new2000_HANDOFF_RECEIPT.json",
        "inputs/c2_new4220_docking_jobs.tsv",
        "inputs/c2_new2000_docking_jobs.tsv",
        "dispatch_shards/DISPATCH_RECEIPT.json",
        *[f"dispatch_shards/shard_{index:02d}.tsv" for index in range(8)],
    ]
    root_receipt = json.loads((ROOT / "inputs/ROOT_RECEIPT.json").read_text())
    assert root_receipt["status"] == "READY_TWO_INDEPENDENT_HANDOFFS"
    assert root_receipt["counts"]["total_jobs"] == 24880
    assert set(root_receipt["seeds"]) == {917, 1931}
    assert set(root_receipt["conformations"]) == {"8x6b", "9e6y"}

    payload = {
        "schema_version": "pvrig.c2_new6220.bxcpu_frozen_inputs.v1",
        "status": "FROZEN_READY_FOR_DEPENDENT_SUBMISSION",
        "archive_name": ARCHIVE_NAME,
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": sha256(archive),
        "root_receipt_sha256": sha256(ROOT / "inputs/ROOT_RECEIPT.json"),
        "manifest_4220_sha256": sha256(
            ROOT / "inputs/c2_new4220_docking_jobs.tsv"
        ),
        "manifest_2000_sha256": sha256(
            ROOT / "inputs/c2_new2000_docking_jobs.tsv"
        ),
        "handoff_receipt_4220_sha256": sha256(
            ROOT / "inputs/c2_new4220_HANDOFF_RECEIPT.json"
        ),
        "handoff_receipt_2000_sha256": sha256(
            ROOT / "inputs/c2_new2000_HANDOFF_RECEIPT.json"
        ),
        "protocol_core_sha256": (
            "8c55751f66ac2930ce115a9419321a2b2bed220b61af2e1671f7ac6e6a2e33b3"
        ),
        "candidates": 6220,
        "expected_jobs": 24880,
        "seeds": [917, 1931],
        "conformations": ["8x6b", "9e6y"],
        "shards": 8,
        "jobs_per_shard": 3110,
        "node_concurrency": 16,
        "cores_per_docking_job": 4,
        "predecessor_array_job_id": "11942310",
        "technical_failure_semantics": "NA_not_negative",
        "deployment_file_sha256": {
            relative: sha256(ROOT / relative) for relative in deployment_files
        },
    }
    (ROOT / "FROZEN_INPUT_ANCHORS.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
