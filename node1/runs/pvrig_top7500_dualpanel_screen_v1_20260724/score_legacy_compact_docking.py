#!/usr/bin/env python3
"""Post-score legacy compact HADDOCK results without rerunning docking.

The first Top7500 campaign compacted the selected HADDOCK models and ``io.json``
but did not preserve the derived native/cross ``pose_scores`` JSON.  This tool
recomputes only those deterministic geometry features from the frozen selected
models, validates manifest lineage, and emits the same V3-compatible job-level
summary used by the newer C2 campaign.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import sys
import tarfile
import tempfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import ModuleType
from typing import Any


_SCORE: ModuleType | None = None
_AGGREGATE: ModuleType | None = None
_REFERENCE_ATOMS: dict[str, Any] = {}
_HOTSPOTS: dict[str, Any] = {}
_REFERENCE_ROOT: Path | None = None


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def archive_job_id(path: Path) -> str:
    name = path.name
    for suffix in (".tar.gz", ".tgz", ".tar"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def index_archives(root: Path) -> dict[str, Path]:
    archives: dict[str, Path] = {}
    for pattern in ("*.tar.gz", "*.tgz", "*.tar"):
        for path in root.rglob(pattern):
            job_id = archive_job_id(path)
            previous = archives.get(job_id)
            if previous is not None and previous != path:
                raise RuntimeError(
                    f"duplicate archive for {job_id}: {previous} and {path}"
                )
            archives[job_id] = path
    return archives


def index_status(root: Path) -> dict[str, dict[str, Any]]:
    statuses: dict[str, dict[str, Any]] = {}
    for path in root.rglob("job_result.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        job_id = str(payload.get("job_id") or path.parent.name)
        statuses[job_id] = payload
    return statuses


def metric(row: dict[str, Any], key: str) -> Any:
    return row.get(key, "") if row else ""


def technical_row(
    job: dict[str, str],
    archive_path: Path | None,
    reason: str,
) -> dict[str, Any]:
    return {
        "campaign": "old_priority_postscore",
        "job_id": job["job_id"],
        "entity_id": job["entity_id"],
        "candidate_id": job["entity_id"],
        "entity_type": job.get("entity_type", ""),
        "conformation": job["conformation"].lower(),
        "seed": job["seed"],
        "state": "TECHNICAL_NA",
        "technical_na_reason": reason,
        "selected_model_count": 0,
        "pose_score_model_count": 0,
        "pose_backed_2x2": "false",
        "job_hash": job["job_hash"],
        "protocol_core_sha256": job["protocol_core_sha256"],
        "archive_path": str(archive_path or ""),
    }


def summarize_success(
    job: dict[str, str],
    evidence: dict[str, Any],
    archive_path: Path,
) -> dict[str, Any]:
    assert _AGGREGATE is not None
    pose_rows = _AGGREGATE.pose_rows_for_job(job, evidence)
    representative = _AGGREGATE.representative_pose_rows(
        pose_rows, job["conformation"]
    )
    if representative is None:
        raise RuntimeError(f"{job['job_id']}: incomplete native/cross pose matrix")
    native, cross = representative
    robustness = _AGGREGATE.model_robustness(pose_rows, job["conformation"])
    return {
        "campaign": "old_priority_postscore",
        "job_id": job["job_id"],
        "entity_id": job["entity_id"],
        "candidate_id": job["entity_id"],
        "entity_type": job.get("entity_type", ""),
        "conformation": job["conformation"].lower(),
        "seed": job["seed"],
        "state": "SUCCESS",
        "technical_na_reason": "",
        "selected_model_count": evidence["selected_model_count"],
        "pose_score_model_count": robustness["complete_model_count"],
        "pose_backed_2x2": "true",
        "representative_model": metric(native, "model"),
        "haddock_score": metric(native, "haddock_score"),
        "air_energy": metric(native, "air_energy"),
        "native_class": metric(native, "geometry_class"),
        "cross_class": metric(cross, "geometry_class"),
        "representative_pair_label": _AGGREGATE.pair_label(
            str(metric(native, "geometry_class")),
            str(metric(cross, "geometry_class")),
        ),
        "model_pair_consensus_fraction": round(
            float(robustness["pair_consensus_fraction"]), 6
        ),
        "model_native_cross_support_agreement_fraction": round(
            float(robustness["native_cross_support_agreement_fraction"]), 6
        ),
        "model_strict_a_fraction": round(
            float(robustness["strict_a_fraction"]), 6
        ),
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


def init_worker(
    score_script: str,
    aggregate_script: str,
    reference_root: str,
) -> None:
    global _SCORE, _AGGREGATE, _REFERENCE_ATOMS, _HOTSPOTS, _REFERENCE_ROOT
    score_path = Path(score_script)
    scripts_dir = score_path.parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    _SCORE = load_module("legacy_score_pose", score_path)
    _AGGREGATE = load_module("legacy_aggregate_results", Path(aggregate_script))
    _REFERENCE_ROOT = Path(reference_root)
    summary = json.loads(
        (_REFERENCE_ROOT / "reports/reference_normalization_summary.json").read_text(
            encoding="utf-8"
        )
    )
    _HOTSPOTS = summary["hotspots"]
    _REFERENCE_ATOMS = {
        reference_id: _SCORE.parse_pdb(
            _REFERENCE_ROOT
            / "inputs"
            / "normalized"
            / f"{reference_id}_TL_reference.pdb"
        )
        for reference_id in ("8x6b", "9e6y")
    }


def find_members(
    archive: tarfile.TarFile,
) -> tuple[list[tarfile.TarInfo], tarfile.TarInfo]:
    members = archive.getmembers()
    models = sorted(
        (
            member
            for member in members
            if member.isfile()
            and "/6_seletopclusts/cluster_" in member.name
            and ("_model_" in member.name)
            and (member.name.endswith(".pdb") or member.name.endswith(".pdb.gz"))
        ),
        key=lambda member: Path(member.name).name,
    )
    io_members = [
        member
        for member in members
        if member.isfile() and member.name.endswith("/6_seletopclusts/io.json")
    ]
    if not models:
        raise RuntimeError("selected HADDOCK models missing from archive")
    if len(io_members) != 1:
        raise RuntimeError(f"expected one 6_seletopclusts/io.json, got {len(io_members)}")
    return models, io_members[0]


def extract_member(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    destination: Path,
) -> Path:
    handle = archive.extractfile(member)
    if handle is None:
        raise RuntimeError(f"cannot read archive member {member.name}")
    destination.write_bytes(handle.read())
    return destination


def process_one(item: tuple[dict[str, str], str | None, bool]) -> dict[str, Any]:
    job, archive_value, status_success = item
    archive_path = Path(archive_value) if archive_value else None
    if archive_path is None:
        return technical_row(job, None, "compact_archive_missing")
    if not status_success:
        return technical_row(job, archive_path, "source_status_not_success")
    assert _SCORE is not None
    try:
        with tempfile.TemporaryDirectory(prefix="pvrig_legacy_postscore_") as tmp:
            tmp_path = Path(tmp)
            with tarfile.open(archive_path, mode="r:*") as archive:
                model_members, io_member = find_members(archive)
                io_path = extract_member(archive, io_member, tmp_path / "io.json")
                pose_scores: list[dict[str, Any]] = []
                cdr_ranges = {
                    "cdr1": _SCORE.parse_residue_range(job["cdr1_range"]),
                    "cdr2": _SCORE.parse_residue_range(job["cdr2_range"]),
                    "cdr3": _SCORE.parse_residue_range(job["cdr3_range"]),
                }
                for member in model_members:
                    model_path = extract_member(
                        archive, member, tmp_path / Path(member.name).name
                    )
                    pose_atoms = _SCORE.parse_pdb(model_path)
                    scores = [
                        _SCORE.score_against_reference(
                            pose_atoms,
                            _REFERENCE_ATOMS[reference_id],
                            reference_id,
                            _HOTSPOTS,
                            job["vhh_chain"],
                            cdr_ranges,
                        )
                        for reference_id in ("8x6b", "9e6y")
                    ]
                    haddock_io = _SCORE.parse_haddock_io(io_path, model_path)
                    if (
                        not haddock_io
                        or not haddock_io.get("matched_model")
                        or haddock_io.get("score") is None
                    ):
                        raise RuntimeError(
                            f"{job['job_id']}: no HADDOCK score for {model_path.name}"
                        )
                    pose_scores.append(
                        {
                            "schema_version": 1,
                            "pose": str(model_path),
                            "atom_filter": "standard_amino_acid_ATOM_only",
                            "vhh_chain": job["vhh_chain"],
                            "cdr_ranges": {
                                key: sorted(value) for key, value in cdr_ranges.items()
                            },
                            "haddock_io": haddock_io,
                            "scores": scores,
                        }
                    )
        evidence = {
            "job_id": job["job_id"],
            "job_hash": job["job_hash"],
            "protocol_core_sha256": job["protocol_core_sha256"],
            "entity_id": job["entity_id"],
            "dock_conformation": job["conformation"],
            "seed": int(job["seed"]),
            "state": "SUCCESS",
            "selected_model_count": len(pose_scores),
            "pose_scores": pose_scores,
        }
        return summarize_success(job, evidence, archive_path)
    except Exception as exc:  # Preserve a full row and explicit technical semantics.
        return technical_row(job, archive_path, f"postscore_error:{type(exc).__name__}:{exc}")


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--score-script", type=Path, required=True)
    parser.add_argument("--aggregate-script", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    jobs = read_tsv(args.manifest)
    archives = index_archives(args.results_root)
    statuses = index_status(args.results_root)
    if args.limit is not None:
        jobs = jobs[: args.limit]
    tasks = [
        (
            job,
            str(archives[job["job_id"]]) if job["job_id"] in archives else None,
            str(statuses.get(job["job_id"], {}).get("state", "")).upper()
            == "SUCCESS",
        )
        for job in jobs
    ]
    with ProcessPoolExecutor(
        max_workers=args.workers,
        initializer=init_worker,
        initargs=(
            str(args.score_script),
            str(args.aggregate_script),
            str(args.reference_root),
        ),
    ) as pool:
        rows = list(pool.map(process_one, tasks, chunksize=1))
    rows.sort(key=lambda row: row["job_id"])
    write_tsv(args.out, rows)
    state_counts = Counter(str(row["state"]) for row in rows)
    reason_counts = Counter(
        str(row.get("technical_na_reason", ""))
        for row in rows
        if row["state"] != "SUCCESS"
    )
    receipt = {
        "schema_version": "pvrig.legacy_compact_docking_postscore.v1",
        "status": "PASS_LEGACY_POSTSCORE",
        "manifest": str(args.manifest),
        "manifest_jobs": len(read_tsv(args.manifest)),
        "processed_rows": len(rows),
        "indexed_archives": len(archives),
        "indexed_status_rows": len(statuses),
        "workers": args.workers,
        "limit": args.limit,
        "state_counts": dict(sorted(state_counts.items())),
        "technical_na_reason_counts": dict(sorted(reason_counts.items())),
        "output": str(args.out),
        "output_sha256": sha256_file(args.out),
        "claim_boundary": (
            "Deterministic post-score of frozen selected HADDOCK models only; "
            "no docking rerun and no experimental binder/blocker claim."
        ),
    }
    receipt_path = args.out.with_suffix(args.out.suffix + ".receipt.json")
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
