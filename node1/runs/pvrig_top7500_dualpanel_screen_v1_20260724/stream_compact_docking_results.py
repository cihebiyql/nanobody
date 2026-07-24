#!/usr/bin/env python3
"""Stream compact Docking archives into a V3-compatible job-results TSV.

The compact transfer keeps the full pose-scored ``job_result.json`` inside each
archive while the sidecar JSON contains only technical status.  This script
reads the archived JSON directly, validates lineage against the frozen job
manifest, and emits job-level geometry summaries without extracting pose PDBs.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import tarfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


SUCCESS_STATES = {"SUCCESS", "PASS", "COMPLETE", "COMPLETED"}
TECHNICAL_NA_STATES = {
    "FAILED",
    "FAIL",
    "FAILED_MAX",
    "FAILED_MAX_ATTEMPTS",
    "TECHNICAL_NA",
    "CANCELLED",
    "TIMEOUT",
}


@dataclass(frozen=True)
class Campaign:
    name: str
    manifest: Path
    results_root: Path


def load_legacy(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("pvrig_aggregate_results", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import aggregate script: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for field in row:
            if field not in seen:
                seen.add(field)
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields or ["job_id"], delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def archive_job_id(path: Path) -> str:
    name = path.name
    for suffix in (".tar.zst", ".tar.gz", ".tgz", ".tar"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def index_archives(root: Path) -> dict[str, Path]:
    archives: dict[str, Path] = {}
    for pattern in ("*.tar.gz", "*.tgz", "*.tar", "*.tar.zst"):
        for path in root.rglob(pattern):
            job_id = archive_job_id(path)
            previous = archives.get(job_id)
            if previous is not None and previous != path:
                raise RuntimeError(f"duplicate archive for {job_id}: {previous} and {path}")
            archives[job_id] = path
    return archives


def index_status(root: Path) -> dict[str, dict[str, Any]]:
    statuses: dict[str, dict[str, Any]] = {}
    for status_dir in root.rglob("status/jobs"):
        for path in status_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            job_id = str(payload.get("job_id") or path.stem)
            statuses[job_id] = payload
    return statuses


def read_archived_job_result(path: Path, job_id: str) -> dict[str, Any] | None:
    if path.name.endswith(".tar.zst"):
        raise RuntimeError(f"tar.zst is not supported by stdlib tarfile: {path}")
    with tarfile.open(path, mode="r:*") as archive:
        candidates = [
            member
            for member in archive.getmembers()
            if member.isfile() and member.name.endswith("/job_result.json")
        ]
        exact = [
            member
            for member in candidates
            if member.name.endswith(f"/results/{job_id}/job_result.json")
            or member.name == f"results/{job_id}/job_result.json"
        ]
        selected = exact or candidates
        if not selected:
            return None
        if len(selected) != 1:
            raise RuntimeError(f"{job_id}: expected one archived job_result, got {len(selected)}")
        handle = archive.extractfile(selected[0])
        if handle is None:
            raise RuntimeError(f"{job_id}: cannot read {selected[0].name}")
        return json.load(handle)


def metric(row: dict[str, Any], key: str) -> Any:
    return row.get(key, "") if row else ""


def summarize_success(
    legacy: ModuleType,
    campaign: str,
    job: dict[str, str],
    evidence: dict[str, Any],
    archive_path: Path,
) -> dict[str, Any]:
    job_id = job["job_id"]
    required_equal = {
        "job_id": job_id,
        "job_hash": job["job_hash"],
        "protocol_core_sha256": job["protocol_core_sha256"],
        "entity_id": job["entity_id"],
        "seed": str(job["seed"]),
    }
    observed = {
        "job_id": str(evidence.get("job_id", "")),
        "job_hash": str(evidence.get("job_hash", "")),
        "protocol_core_sha256": str(evidence.get("protocol_core_sha256", "")),
        "entity_id": str(evidence.get("entity_id", "")),
        "seed": str(evidence.get("seed", "")),
    }
    for field, expected in required_equal.items():
        if observed[field] != str(expected):
            raise RuntimeError(
                f"{job_id}: lineage mismatch {field}: {observed[field]!r} != {expected!r}"
            )
    dock_conformation = str(
        evidence.get("dock_conformation") or evidence.get("conformation") or ""
    ).lower()
    if dock_conformation != job["conformation"].lower():
        raise RuntimeError(
            f"{job_id}: conformation mismatch {dock_conformation!r} != {job['conformation']!r}"
        )
    state = str(evidence.get("state", "")).upper()
    if state not in SUCCESS_STATES:
        raise RuntimeError(f"{job_id}: archived job_result is not successful: {state}")

    pose_rows = legacy.pose_rows_for_job(job, evidence)
    representative = legacy.representative_pose_rows(pose_rows, job["conformation"])
    if representative is None:
        raise RuntimeError(f"{job_id}: no complete native/cross representative pose")
    native, cross = representative
    robustness = legacy.model_robustness(pose_rows, job["conformation"])
    return {
        "campaign": campaign,
        "job_id": job_id,
        "entity_id": job["entity_id"],
        "candidate_id": job["entity_id"],
        "entity_type": job.get("entity_type", ""),
        "conformation": job["conformation"].lower(),
        "seed": job["seed"],
        "state": "SUCCESS",
        "technical_na_reason": "",
        "selected_model_count": evidence.get("selected_model_count", 0),
        "pose_score_model_count": robustness["complete_model_count"],
        "pose_backed_2x2": "true",
        "representative_model": metric(native, "model"),
        "haddock_score": metric(native, "haddock_score"),
        "air_energy": metric(native, "air_energy"),
        "native_class": metric(native, "geometry_class"),
        "cross_class": metric(cross, "geometry_class"),
        "representative_pair_label": legacy.pair_label(
            str(metric(native, "geometry_class")),
            str(metric(cross, "geometry_class")),
        ),
        "model_pair_consensus_fraction": round(
            float(robustness["pair_consensus_fraction"]), 6
        ),
        "model_native_cross_support_agreement_fraction": round(
            float(robustness["native_cross_support_agreement_fraction"]), 6
        ),
        "model_strict_a_fraction": round(float(robustness["strict_a_fraction"]), 6),
        "native_hotspot_overlap": metric(native, "hotspot_overlap"),
        "cross_hotspot_overlap": metric(cross, "hotspot_overlap"),
        "native_holdout_overlap": metric(native, "holdout_overlap"),
        "cross_holdout_overlap": metric(cross, "holdout_overlap"),
        "native_total_occlusion": metric(native, "total_occlusion"),
        "cross_total_occlusion": metric(cross, "total_occlusion"),
        "native_cdr3_occlusion": metric(native, "cdr3_occlusion"),
        "cross_cdr3_occlusion": metric(cross, "cdr3_occlusion"),
        "native_cdr3_fraction": metric(native, "cdr3_fraction"),
        "cross_cdr3_fraction": metric(cross, "cdr3_fraction"),
        "native_clash_atom_pairs": metric(native, "clash_atom_pairs"),
        "cross_clash_atom_pairs": metric(cross, "clash_atom_pairs"),
        "native_clash_residue_pairs": metric(native, "clash_residue_pairs"),
        "cross_clash_residue_pairs": metric(cross, "clash_residue_pairs"),
        "native_overlay_rmsd_a": metric(native, "overlay_rmsd_a"),
        "cross_overlay_rmsd_a": metric(cross, "overlay_rmsd_a"),
        "job_hash": job["job_hash"],
        "protocol_core_sha256": job["protocol_core_sha256"],
        "archive_path": str(archive_path),
    }


def technical_row(
    campaign: str,
    job: dict[str, str],
    status: dict[str, Any],
    archive_path: Path | None,
    reason: str,
) -> dict[str, Any]:
    state = str(status.get("status") or status.get("state") or "TECHNICAL_NA").upper()
    if state not in TECHNICAL_NA_STATES:
        state = "TECHNICAL_NA"
    return {
        "campaign": campaign,
        "job_id": job["job_id"],
        "entity_id": job["entity_id"],
        "candidate_id": job["entity_id"],
        "entity_type": job.get("entity_type", ""),
        "conformation": job["conformation"].lower(),
        "seed": job["seed"],
        "state": state,
        "technical_na_reason": reason or str(status.get("error", "")),
        "selected_model_count": status.get("selected_model_count", 0),
        "pose_score_model_count": 0,
        "pose_backed_2x2": "false",
        "job_hash": job["job_hash"],
        "protocol_core_sha256": job["protocol_core_sha256"],
        "archive_path": str(archive_path or ""),
    }


def parse_campaign(value: str) -> Campaign:
    parts = value.split("::")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            "campaign must be NAME::MANIFEST_TSV::RESULTS_ROOT"
        )
    return Campaign(parts[0], Path(parts[1]), Path(parts[2]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", action="append", type=parse_campaign, required=True)
    parser.add_argument("--aggregate-script", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if args.workers < 1 or args.limit < 0:
        parser.error("workers must be >=1 and limit must be >=0")

    legacy = load_legacy(args.aggregate_script)
    tasks: list[
        tuple[str, dict[str, str], dict[str, Path], dict[str, dict[str, Any]]]
    ] = []
    campaign_receipts: dict[str, Any] = {}
    seen_job_ids: set[str] = set()
    for campaign in args.campaign:
        jobs = read_tsv(campaign.manifest)
        archives = index_archives(campaign.results_root)
        statuses = index_status(campaign.results_root)
        duplicate = seen_job_ids & {row["job_id"] for row in jobs}
        if duplicate:
            raise RuntimeError(
                f"job IDs overlap across campaigns, examples: {sorted(duplicate)[:3]}"
            )
        seen_job_ids.update(row["job_id"] for row in jobs)
        for job in jobs:
            tasks.append((campaign.name, job, archives, statuses))
        campaign_receipts[campaign.name] = {
            "manifest": str(campaign.manifest),
            "results_root": str(campaign.results_root),
            "manifest_jobs": len(jobs),
            "indexed_archives": len(archives),
            "indexed_status_rows": len(statuses),
        }
    if args.limit:
        tasks = tasks[: args.limit]

    def process(
        item: tuple[str, dict[str, str], dict[str, Path], dict[str, dict[str, Any]]]
    ) -> dict[str, Any]:
        campaign_name, job, archives, statuses = item
        job_id = job["job_id"]
        archive_path = archives.get(job_id)
        status = statuses.get(job_id, {})
        if archive_path is None:
            return technical_row(
                campaign_name, job, status, None, "compact_archive_missing"
            )
        evidence = read_archived_job_result(archive_path, job_id)
        if evidence is None:
            return technical_row(
                campaign_name, job, status, archive_path, "archived_job_result_missing"
            )
        return summarize_success(
            legacy, campaign_name, job, evidence, archive_path
        )

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        rows = list(executor.map(process, tasks))
    rows.sort(key=lambda row: (row["campaign"], row["job_id"]))
    write_tsv(args.out, rows)
    state_counts = Counter(str(row["state"]).upper() for row in rows)
    receipt = {
        "schema_version": "pvrig.compact_docking_stream_aggregate.v1",
        "status": (
            "PASS_PILOT_STREAM_AGGREGATE"
            if args.limit
            else "PASS_FULL_STREAM_AGGREGATE"
        ),
        "claim_boundary": (
            "Pose-backed computational Docking geometry only; technical failures are NA, "
            "not biological negatives; no binding, Kd, IC50 or experimental blocking claim."
        ),
        "campaigns": campaign_receipts,
        "rows": len(rows),
        "limit": args.limit,
        "state_counts": dict(sorted(state_counts.items())),
        "pose_backed_success_rows": sum(
            row.get("pose_backed_2x2") == "true" for row in rows
        ),
        "output": str(args.out),
    }
    receipt_path = args.out.with_suffix(args.out.suffix + ".receipt.json")
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
