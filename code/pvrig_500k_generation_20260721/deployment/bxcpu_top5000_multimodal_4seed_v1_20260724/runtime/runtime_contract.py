#!/usr/bin/env python3
"""Shared fail-closed contract checks for the top5000 multimodal 4-seed campaign."""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import os
import pathlib
import tarfile
from typing import Any, Iterable


EXPECTED_CANDIDATES = 5_000
EXPECTED_JOBS = 40_000
EXPECTED_SHARDS = 8
EXPECTED_JOBS_PER_SHARD = 5_000
EXPECTED_SEEDS = 4
EXPECTED_SEED_VALUES = {"42", "917", "1931", "3047"}
EXPECTED_CONFORMATIONS = {"8x6b", "9e6y"}
EXPECTED_CPUS_PER_JOB = 4
TERMINAL_FAILURES = {"FAILED_MAX_ATTEMPTS"}
CANDIDATE_FIELDS = (
    "candidate_id",
    "entity_id",
    "candidate",
    "design_id",
    "sequence_id",
)


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial.{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def read_tsv(path: pathlib.Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"missing or unsafe TSV: {path}")
    if b"\r" in path.read_bytes():
        raise RuntimeError(f"CRLF is not allowed in TSV: {path}")
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields:
        raise RuntimeError(f"TSV header is missing: {path}")
    return fields, rows


def _candidate_field(fields: Iterable[str]) -> str:
    available = set(fields)
    for name in CANDIDATE_FIELDS:
        if name in available:
            return name
    raise RuntimeError(
        "manifest must contain one candidate identity field: "
        + ", ".join(CANDIDATE_FIELDS)
    )


def validate_manifest_rows(
    fields: list[str], rows: list[dict[str, str]]
) -> dict[str, Any]:
    required = {"job_id", "seed", "conformation"}
    missing = sorted(required - set(fields))
    if missing:
        raise RuntimeError(f"manifest fields missing: {missing}")
    candidate_field = _candidate_field(fields)
    if len(rows) != EXPECTED_JOBS:
        raise RuntimeError(f"expected {EXPECTED_JOBS} jobs, found {len(rows)}")

    job_ids = [row["job_id"].strip() for row in rows]
    if any(not job_id for job_id in job_ids):
        raise RuntimeError("manifest contains an empty job_id")
    if len(set(job_ids)) != EXPECTED_JOBS:
        raise RuntimeError("job_id values are not unique")

    candidates = [row[candidate_field].strip() for row in rows]
    if any(not candidate for candidate in candidates):
        raise RuntimeError(f"manifest contains an empty {candidate_field}")
    if len(set(candidates)) != EXPECTED_CANDIDATES:
        raise RuntimeError(
            f"expected {EXPECTED_CANDIDATES} candidates, "
            f"found {len(set(candidates))}"
        )

    seeds = {row["seed"].strip() for row in rows}
    if seeds != EXPECTED_SEED_VALUES:
        raise RuntimeError(
            f"expected seeds {sorted(EXPECTED_SEED_VALUES)}, found {sorted(seeds)}"
        )
    conformations = {row["conformation"].strip() for row in rows}
    if conformations != EXPECTED_CONFORMATIONS:
        raise RuntimeError(
            "expected conformations "
            f"{sorted(EXPECTED_CONFORMATIONS)}, found {sorted(conformations)}"
        )

    jobs_per_candidate = collections.Counter(candidates)
    if set(jobs_per_candidate.values()) != {EXPECTED_JOBS // EXPECTED_CANDIDATES}:
        raise RuntimeError("every candidate must have exactly eight jobs")

    jobs_per_candidate_seed = collections.Counter(
        (row[candidate_field].strip(), row["seed"].strip()) for row in rows
    )
    expected_per_candidate_seed = (
        EXPECTED_JOBS // EXPECTED_CANDIDATES // EXPECTED_SEEDS
    )
    if set(jobs_per_candidate_seed.values()) != {expected_per_candidate_seed}:
        raise RuntimeError("every candidate/seed pair must have exactly two jobs")
    matrix = collections.Counter(
        (
            row[candidate_field].strip(),
            row["seed"].strip(),
            row["conformation"].strip(),
        )
        for row in rows
    )
    if set(matrix.values()) != {1}:
        raise RuntimeError(
            "every candidate/seed/conformation tuple must occur exactly once"
        )

    return {
        "candidate_field": candidate_field,
        "candidates": EXPECTED_CANDIDATES,
        "jobs": EXPECTED_JOBS,
        "seeds": sorted(seeds),
        "conformations": sorted(conformations),
    }


def _nested(mapping: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        value: Any = mapping
        for key in path:
            if not isinstance(value, dict) or key not in value:
                break
            value = value[key]
        else:
            return value
    return None


def _require_count(payload: dict[str, Any], name: str, expected: int) -> None:
    aliases = {
        "shards": ("shard_count",),
        "jobs_per_shard": ("shard_jobs",),
    }
    paths = [
        (name,),
        ("counts", name),
        ("counts", f"total_{name}"),
        (f"expected_{name}",),
    ]
    for alias in aliases.get(name, ()):
        paths.extend(((alias,), ("counts", alias), (f"expected_{alias}",)))
    value = _nested(payload, *paths)
    if value != expected:
        raise RuntimeError(f"receipt {name}={value!r}, expected {expected}")


def validate_ready(
    ready_path: pathlib.Path,
    expected_sha256: str,
    expected_status: str,
    archive_sha256: str,
    manifest_sha256: str,
    receipt_sha256: str,
) -> dict[str, Any]:
    if sha256(ready_path) != expected_sha256:
        raise RuntimeError("READY SHA256 mismatch")
    payload = json.loads(ready_path.read_text())
    if payload.get("status") != expected_status:
        raise RuntimeError(
            f"READY status={payload.get('status')!r}, expected {expected_status!r}"
        )
    _require_count(payload, "candidates", EXPECTED_CANDIDATES)
    _require_count(payload, "jobs", EXPECTED_JOBS)
    _require_count(payload, "shards", EXPECTED_SHARDS)
    jobs_per_shard = _nested(
        payload,
        ("jobs_per_shard",),
        ("counts", "jobs_per_shard"),
        ("expected_jobs_per_shard",),
    )
    if jobs_per_shard is not None and jobs_per_shard not in (
        EXPECTED_JOBS_PER_SHARD,
        [EXPECTED_JOBS_PER_SHARD] * EXPECTED_SHARDS,
    ):
        raise RuntimeError("READY jobs_per_shard is not 8x5000")
    anchors = {
        "archive": _nested(
            payload, ("archive_sha256",), ("sha256", "archive"), ("anchors", "archive_sha256")
        ),
        "manifest": _nested(
            payload,
            ("manifest_sha256",),
            ("job_manifest_sha256",),
            ("sha256", "manifest"),
            ("anchors", "manifest_sha256"),
        ),
        "receipt": _nested(
            payload,
            ("receipt_sha256",),
            ("bundle_receipt_sha256",),
            ("handoff_receipt_sha256",),
            ("sha256", "receipt"),
            ("anchors", "receipt_sha256"),
        ),
    }
    expected = {
        "archive": archive_sha256,
        "manifest": manifest_sha256,
        "receipt": receipt_sha256,
    }
    for name, digest in expected.items():
        if name == "archive" and anchors[name] is None:
            # Builder READY predates archive sealing; the independently required
            # archive SHA still gates the archive itself.
            continue
        if anchors[name] != digest:
            raise RuntimeError(f"READY {name} SHA256 anchor mismatch")
    return payload


def validate_receipt(
    receipt_path: pathlib.Path,
    expected_sha256: str,
    expected_status: str,
    manifest_seeds: list[str],
) -> dict[str, Any]:
    if sha256(receipt_path) != expected_sha256:
        raise RuntimeError("internal receipt SHA256 mismatch")
    payload = json.loads(receipt_path.read_text())
    if payload.get("status") != expected_status:
        raise RuntimeError(
            f"receipt status={payload.get('status')!r}, expected {expected_status!r}"
        )
    _require_count(payload, "candidates", EXPECTED_CANDIDATES)
    _require_count(payload, "jobs", EXPECTED_JOBS)
    if payload.get("docking_started") is not False:
        raise RuntimeError("receipt must state docking_started=false")
    seeds = _nested(payload, ("seeds",), ("protocol", "seeds"))
    if seeds is not None and sorted(str(seed) for seed in seeds) != manifest_seeds:
        raise RuntimeError("receipt seeds do not match the manifest")
    return payload


def validate_inputs(
    archive: pathlib.Path,
    archive_sha256: str,
    manifest: pathlib.Path,
    manifest_sha256: str,
    ready: pathlib.Path,
    ready_sha256: str,
    ready_status: str,
    receipt_sha256: str,
) -> dict[str, Any]:
    if not archive.is_file() or archive.is_symlink():
        raise RuntimeError(f"missing or unsafe archive: {archive}")
    if sha256(archive) != archive_sha256:
        raise RuntimeError("archive SHA256 mismatch")
    if sha256(manifest) != manifest_sha256:
        raise RuntimeError("external manifest SHA256 mismatch")
    fields, rows = read_tsv(manifest)
    summary = validate_manifest_rows(fields, rows)
    validate_ready(
        ready,
        ready_sha256,
        ready_status,
        archive_sha256,
        manifest_sha256,
        receipt_sha256,
    )
    return summary


def validate_project(
    project_root: pathlib.Path,
    manifest_relative: str,
    manifest_sha256: str,
    receipt_relative: str,
    receipt_sha256: str,
    receipt_status: str,
    shard_dir_relative: str,
) -> dict[str, Any]:
    manifest = project_root / manifest_relative
    if sha256(manifest) != manifest_sha256:
        raise RuntimeError("internal manifest SHA256 mismatch")
    fields, rows = read_tsv(manifest)
    summary = validate_manifest_rows(fields, rows)
    master_job_ids = {row["job_id"].strip() for row in rows}

    shard_dir = project_root / shard_dir_relative
    observed: set[str] = set()
    shard_hashes: dict[str, str] = {}
    for index in range(EXPECTED_SHARDS):
        shard = shard_dir / f"shard_{index:02d}.tsv"
        shard_fields, shard_rows = read_tsv(shard)
        if "job_id" not in shard_fields:
            raise RuntimeError(f"shard missing job_id: {shard}")
        if len(shard_rows) != EXPECTED_JOBS_PER_SHARD:
            raise RuntimeError(
                f"{shard.name} has {len(shard_rows)} jobs, "
                f"expected {EXPECTED_JOBS_PER_SHARD}"
            )
        job_ids = [row["job_id"].strip() for row in shard_rows]
        if len(set(job_ids)) != EXPECTED_JOBS_PER_SHARD:
            raise RuntimeError(f"duplicate job_id in {shard.name}")
        overlap = observed.intersection(job_ids)
        if overlap:
            raise RuntimeError(f"jobs occur in multiple shards: {sorted(overlap)[:3]}")
        observed.update(job_ids)
        shard_hashes[shard.name] = sha256(shard)
    if observed != master_job_ids:
        raise RuntimeError("eight shards are not an exact partition of the master manifest")

    validate_receipt(
        project_root / receipt_relative,
        receipt_sha256,
        receipt_status,
        summary["seeds"],
    )
    cfg_lock_path = project_root / "config/FOUR_SEED_CFG_LOCK.json"
    cfg_lock = json.loads(cfg_lock_path.read_text())
    if cfg_lock.get("status") != "LOCKED":
        raise RuntimeError("FOUR_SEED_CFG_LOCK status is not LOCKED")
    if {str(seed) for seed in cfg_lock.get("seeds", [])} != EXPECTED_SEED_VALUES:
        raise RuntimeError("FOUR_SEED_CFG_LOCK seeds mismatch")
    if set(cfg_lock.get("conformations", [])) != EXPECTED_CONFORMATIONS:
        raise RuntimeError("FOUR_SEED_CFG_LOCK conformations mismatch")
    payloads = cfg_lock.get("cfg_payloads", {})
    observed_pairs = set()
    for seed, by_conformation in payloads.items():
        for conformation, cfg in by_conformation.items():
            observed_pairs.add((str(seed), str(conformation)))
            if int(cfg.get("ncores", 0)) != EXPECTED_CPUS_PER_JOB:
                raise RuntimeError("every HADDOCK cfg must use exactly four cores")
    expected_pairs = {
        (seed, conformation)
        for seed in EXPECTED_SEED_VALUES
        for conformation in EXPECTED_CONFORMATIONS
    }
    if observed_pairs != expected_pairs:
        raise RuntimeError("FOUR_SEED_CFG_LOCK does not contain the exact 4x2 matrix")
    return {**summary, "shards": EXPECTED_SHARDS, "shard_sha256": shard_hashes}


def check_smoke(
    status_path: pathlib.Path,
    result_path: pathlib.Path,
    compact_path: pathlib.Path,
    job_id: str,
) -> dict[str, Any]:
    status = json.loads(status_path.read_text())
    result = json.loads(result_path.read_text())
    if status.get("status") != "SUCCESS":
        raise RuntimeError("smoke status is not SUCCESS")
    if result.get("state") != "SUCCESS":
        raise RuntimeError("smoke job_result is not SUCCESS")
    for payload in (status, result):
        if payload.get("job_id") not in (None, job_id):
            raise RuntimeError("smoke job identity mismatch")
    with tarfile.open(compact_path, "r:gz") as archive:
        names = set(archive.getnames())
    required = {
        f"runs/{job_id}/COMPACT_EVIDENCE.json",
        f"results/{job_id}/job_result.json",
    }
    if not required.issubset(names):
        raise RuntimeError("smoke compressed_queue evidence is incomplete")
    return {
        "job_id": job_id,
        "status": "SUCCESS",
        "compact_bytes": compact_path.stat().st_size,
    }


def _terminal_state(status: dict[str, Any]) -> bool:
    state = status.get("status")
    return state == "SUCCESS" or state in TERMINAL_FAILURES or (
        state == "FAILED" and int(status.get("attempts", 0) or 0) >= 2
    )


def audit_results(
    result_root: pathlib.Path,
    manifest: pathlib.Path,
    manifest_sha256: str,
    output: pathlib.Path,
) -> dict[str, Any]:
    if sha256(manifest) != manifest_sha256:
        raise RuntimeError("audit manifest SHA256 mismatch")
    fields, rows = read_tsv(manifest)
    validate_manifest_rows(fields, rows)

    counts: collections.Counter[str] = collections.Counter()
    terminal_jobs = 0
    success_evidence_jobs = 0
    invalid_examples: list[dict[str, str]] = []
    for row in rows:
        job_id = row["job_id"].strip()
        status_path = result_root / "status/jobs" / f"{job_id}.json"
        if not status_path.is_file():
            counts["MISSING"] += 1
            continue
        try:
            status = json.loads(status_path.read_text())
            state = str(status.get("status", "UNKNOWN"))
        except Exception as exc:
            counts["INVALID_STATUS_JSON"] += 1
            if len(invalid_examples) < 20:
                invalid_examples.append({"job_id": job_id, "error": repr(exc)})
            continue
        if status.get("job_id") not in (None, job_id):
            counts["STATUS_JOB_ID_MISMATCH"] += 1
            continue
        counts[state] += 1
        if not _terminal_state(status):
            continue
        terminal_jobs += 1
        if state != "SUCCESS":
            continue
        result_path = result_root / "results" / job_id / "job_result.json"
        compact_path = result_root / "compressed_queue" / f"{job_id}.tar.gz"
        try:
            result = json.loads(result_path.read_text())
            if result.get("state") != "SUCCESS":
                raise RuntimeError("job_result state is not SUCCESS")
            if result.get("job_id") not in (None, job_id):
                raise RuntimeError("job_result identity mismatch")
            if not (
                (compact_path.is_file() and compact_path.stat().st_size > 0)
                or result.get("offloaded_to_node1") is True
            ):
                raise RuntimeError("no compressed_queue evidence or verified offload stub")
            success_evidence_jobs += 1
        except Exception as exc:
            counts["SUCCESS_EVIDENCE_INVALID"] += 1
            if len(invalid_examples) < 20:
                invalid_examples.append({"job_id": job_id, "error": repr(exc)})

    marker_count = sum(
        1
        for index in range(1, EXPECTED_SHARDS + 1)
        if (result_root / "markers" / f"top5000_multimodal_shard_{index}.done").is_file()
    )
    complete = (
        terminal_jobs == EXPECTED_JOBS
        and success_evidence_jobs == counts["SUCCESS"]
        and counts["SUCCESS_EVIDENCE_INVALID"] == 0
        and marker_count == EXPECTED_SHARDS
    )
    payload = {
        "schema_version": "pvrig.top5000_multimodal_4seed.technical_audit.v1",
        "status": "COMPLETE" if complete else "INCOMPLETE",
        "expected_candidates": EXPECTED_CANDIDATES,
        "expected_jobs": EXPECTED_JOBS,
        "expected_shards": EXPECTED_SHARDS,
        "expected_jobs_per_shard": EXPECTED_JOBS_PER_SHARD,
        "terminal_jobs": terminal_jobs,
        "success_evidence_jobs": success_evidence_jobs,
        "shard_markers": marker_count,
        "state_counts": dict(sorted(counts.items())),
        "invalid_examples": invalid_examples,
        "manifest_sha256": manifest_sha256,
        "updated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "claim_boundary": (
            "Technical HADDOCK completion and evidence transport only; "
            "not biological or experimental validation."
        ),
    }
    atomic_json(output, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    inputs = subparsers.add_parser("validate-inputs")
    inputs.add_argument("--archive", type=pathlib.Path, required=True)
    inputs.add_argument("--archive-sha256", required=True)
    inputs.add_argument("--manifest", type=pathlib.Path, required=True)
    inputs.add_argument("--manifest-sha256", required=True)
    inputs.add_argument("--ready", type=pathlib.Path, required=True)
    inputs.add_argument("--ready-sha256", required=True)
    inputs.add_argument("--ready-status", required=True)
    inputs.add_argument("--receipt-sha256", required=True)

    ready = subparsers.add_parser("validate-ready")
    ready.add_argument("--ready", type=pathlib.Path, required=True)
    ready.add_argument("--ready-sha256", required=True)
    ready.add_argument("--ready-status", required=True)
    ready.add_argument("--archive-sha256", required=True)
    ready.add_argument("--manifest-sha256", required=True)
    ready.add_argument("--receipt-sha256", required=True)

    project = subparsers.add_parser("validate-project")
    project.add_argument("--project-root", type=pathlib.Path, required=True)
    project.add_argument("--manifest-relative", required=True)
    project.add_argument("--manifest-sha256", required=True)
    project.add_argument("--receipt-relative", required=True)
    project.add_argument("--receipt-sha256", required=True)
    project.add_argument("--receipt-status", required=True)
    project.add_argument("--shard-dir-relative", required=True)

    smoke = subparsers.add_parser("check-smoke")
    smoke.add_argument("--status", type=pathlib.Path, required=True)
    smoke.add_argument("--result", type=pathlib.Path, required=True)
    smoke.add_argument("--compact", type=pathlib.Path, required=True)
    smoke.add_argument("--job-id", required=True)

    audit = subparsers.add_parser("audit")
    audit.add_argument("--result-root", type=pathlib.Path, required=True)
    audit.add_argument("--manifest", type=pathlib.Path, required=True)
    audit.add_argument("--manifest-sha256", required=True)
    audit.add_argument("--output", type=pathlib.Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "validate-inputs":
        payload = validate_inputs(
            args.archive,
            args.archive_sha256,
            args.manifest,
            args.manifest_sha256,
            args.ready,
            args.ready_sha256,
            args.ready_status,
            args.receipt_sha256,
        )
    elif args.command == "validate-ready":
        payload = validate_ready(
            args.ready,
            args.ready_sha256,
            args.ready_status,
            args.archive_sha256,
            args.manifest_sha256,
            args.receipt_sha256,
        )
    elif args.command == "validate-project":
        payload = validate_project(
            args.project_root,
            args.manifest_relative,
            args.manifest_sha256,
            args.receipt_relative,
            args.receipt_sha256,
            args.receipt_status,
            args.shard_dir_relative,
        )
    elif args.command == "check-smoke":
        payload = check_smoke(args.status, args.result, args.compact, args.job_id)
    else:
        payload = audit_results(
            args.result_root, args.manifest, args.manifest_sha256, args.output
        )
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload["status"] == "COMPLETE" else 2
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
