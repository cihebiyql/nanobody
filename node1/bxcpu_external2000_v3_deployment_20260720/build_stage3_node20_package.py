#!/usr/bin/env python3
"""Freeze the drained Node20 residual queue into a portable bxcpu Stage3 project."""

from __future__ import annotations

import csv
import datetime
import hashlib
import json
import os
import pathlib
import shutil
import subprocess


SOURCE = pathlib.Path("/data/qlyu/projects/pvrig_v29_docking25k_v1_20260720")
TEMPLATE = pathlib.Path("/data/qlyu/projects/pvrig_v29_bxcpu_stage2_10500_v1_20260720")
NAME = "pvrig_v29_bxcpu_stage3_node20_v1_20260720"
TARGET = SOURCE.parent / NAME
SOURCE_MANIFEST = SOURCE / "manifests/node20_acceleration_jobs.tsv"
FULL_MANIFEST = SOURCE / "manifests/docking_jobs.tsv"
STAGE2_MANIFEST = SOURCE / "manifests/bxcpu_stage2_10500_jobs.tsv"
FROZEN_MANIFEST = SOURCE / "manifests/bxcpu_stage3_node20_jobs.tsv"
FREEZE_RECEIPT = SOURCE / "status/BXCPU_STAGE3_NODE20_FREEZE.json"


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_rows(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_rows(path: pathlib.Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def atomic_json(path: pathlib.Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def terminal(payload: dict[str, object]) -> bool:
    state = payload.get("status")
    return state in {"SUCCESS", "FAILED_MAX_ATTEMPTS"} or (
        state == "FAILED" and int(payload.get("attempts", 0) or 0) >= 2
    )


def main() -> int:
    if TARGET.exists():
        raise SystemExit(f"refusing to overwrite existing target: {TARGET}")
    source_rows = read_rows(SOURCE_MANIFEST)
    full_rows = read_rows(FULL_MANIFEST)
    full_by_job = {row["job_id"]: row for row in full_rows}
    if len(full_by_job) != len(full_rows):
        raise SystemExit("full docking manifest has duplicate job IDs")
    missing_full = [row["job_id"] for row in source_rows if row["job_id"] not in full_by_job]
    if missing_full:
        raise SystemExit(f"{len(missing_full)} Node20 jobs are absent from the full docking manifest")
    stage2_ids = {row["job_id"] for row in read_rows(STAGE2_MANIFEST)}
    selected = []
    retry_statuses: dict[str, pathlib.Path] = {}
    running = []
    source_counts: dict[str, int] = {}
    for row in source_rows:
        status_path = SOURCE / "status/jobs" / f"{row['job_id']}.json"
        payload: dict[str, object] = {}
        state = "ABSENT"
        if status_path.exists():
            payload = json.loads(status_path.read_text())
            state = str(payload.get("status", "UNKNOWN"))
        source_counts[state] = source_counts.get(state, 0) + 1
        if state == "RUNNING":
            running.append(row["job_id"])
        if terminal(payload):
            continue
        full_row = full_by_job[row["job_id"]]
        if row.get("job_hash") and row["job_hash"] != full_row["job_hash"]:
            raise SystemExit(f"job hash mismatch for {row['job_id']}")
        selected.append(full_row)
        if status_path.exists() and state == "FAILED":
            retry_statuses[row["job_id"]] = status_path
    if running:
        raise SystemExit(f"cannot freeze while {len(running)} Node20 jobs remain RUNNING")
    if not selected:
        raise SystemExit("Node20 has no remaining jobs to migrate")
    selected_ids = {row["job_id"] for row in selected}
    if len(selected_ids) != len(selected):
        raise SystemExit("duplicate Stage3 job IDs")
    overlap = selected_ids & stage2_ids
    if overlap:
        raise SystemExit(f"Stage3 overlaps Stage2 by {len(overlap)} jobs")

    fields = list(full_rows[0])
    write_rows(FROZEN_MANIFEST, selected, fields)

    # The template is immutable. Hard links keep the portable inputs compact on
    # Node1; every Stage3-specific file below is replaced atomically.
    subprocess.run(["cp", "-al", str(TEMPLATE), str(TARGET)], check=True)
    for path in (TARGET / "manifests").glob("*.tsv"):
        path.unlink()
    write_rows(TARGET / "manifests/docking_jobs.tsv", selected, fields)
    write_rows(TARGET / "manifests/stage3_jobs.tsv", selected, fields)
    for path in (TARGET / "status").glob("*"):
        if path.is_file() or path.is_symlink():
            path.unlink()
        else:
            shutil.rmtree(path)
    (TARGET / "status/jobs").mkdir(parents=True, exist_ok=True)
    for job_id, path in retry_statuses.items():
        shutil.copy2(path, TARGET / "status/jobs" / f"{job_id}.json")
    for dirname in ("results", "runs", "logs", "failed_attempts"):
        path = TARGET / dirname
        if path.exists():
            shutil.rmtree(path)
        path.mkdir()

    protocol_hashes = {row["protocol_core_sha256"] for row in selected}
    if protocol_hashes != {"49fffc2c7087b1ff3a8e42463319168fad409687f502b619f3661c978fc6d666"}:
        raise SystemExit(f"unexpected protocol hashes: {protocol_hashes}")
    monomers = {row["monomer_source"] for row in selected}
    missing = [relative for relative in monomers if not (TARGET / relative).is_file()]
    missing_source = [relative for relative in missing if not (SOURCE / relative).is_file()]
    if missing_source:
        raise SystemExit(f"missing {len(missing_source)} monomers in source project")
    for relative in missing:
        destination = TARGET / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / relative, destination)

    manifest_hash = sha256(TARGET / "manifests/stage3_jobs.tsv")
    ready = {
        "schema_version": "pvrig_v29_bxcpu_stage3_node20_ready_v1",
        "state": "READY",
        "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "project_name": NAME,
        "job_count": len(selected),
        "unique_monomers": len(monomers),
        "monomers_added_to_template": len(missing),
        "source_manifest": str(SOURCE_MANIFEST.relative_to(SOURCE)),
        "source_manifest_sha256": sha256(SOURCE_MANIFEST),
        "stage3_manifest_sha256": manifest_hash,
        "protocol_core_sha256": next(iter(protocol_hashes)),
        "retry_status_count": len(retry_statuses),
        "stage2_overlap": 0,
        "claim_boundary": "Computational docking geometry only; not affinity, Kd, IC50 or experimental blocking.",
    }
    atomic_json(TARGET / "status/READY.json", ready)
    summary = {
        "job_count": len(selected),
        "unique_job_ids": len(selected_ids),
        "unique_entities": len({row["entity_id"] for row in selected}),
        "unique_monomers": len(monomers),
        "by_conformation_seed": dict(
            sorted(
                __import__("collections").Counter(
                    f"{row['conformation']}_s{row['seed']}" for row in selected
                ).items()
            )
        ),
    }
    atomic_json(TARGET / "reports/job_manifest_summary.json", summary)
    readme = TARGET / "README.md"
    if readme.exists():
        readme.unlink()
    readme.write_text(
        f"# {NAME}\n\n"
        f"Frozen Node20 residual migration for bxcpu. Jobs: {len(selected)}. "
        "This package preserves the frozen V29 docking protocol and contains no affinity, Kd, IC50, or experimental-blocking claim.\n"
    )
    sums = TARGET / "SHA256SUMS"
    if sums.exists():
        sums.unlink()
    files = sorted(path for path in TARGET.rglob("*") if path.is_file() and path != sums)
    sums.write_text("".join(f"{sha256(path)}  {path.relative_to(TARGET)}\n" for path in files))

    receipt = {
        **ready,
        "schema_version": "pvrig_v29_bxcpu_stage3_node20_freeze_v1",
        "state": "FROZEN_PACKAGE_PROJECT_READY",
        "source_status_counts_at_freeze": source_counts,
        "target_project": str(TARGET),
        "selected_manifest": str(FROZEN_MANIFEST.relative_to(SOURCE)),
        "selected_manifest_sha256": sha256(FROZEN_MANIFEST),
        "package_sha256sums": sha256(sums),
    }
    atomic_json(FREEZE_RECEIPT, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
