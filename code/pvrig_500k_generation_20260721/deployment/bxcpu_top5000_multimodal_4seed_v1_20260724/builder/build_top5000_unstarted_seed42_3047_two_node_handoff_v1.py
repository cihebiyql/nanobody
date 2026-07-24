#!/usr/bin/env python3
"""Build a deterministic two-node recovery handoff from the frozen Top5000 package.

This builder is local-only.  It never submits jobs, contacts Node1/bxcpu, or
modifies the source package.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import uuid
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = "pvrig.top5000.unstarted_seed42_3047.two_node_handoff.v1"
PACKAGE_VERSION = "pvrig_top5000_unstarted_seed42_3047_two_node_handoff_v1_20260724"
SOURCE_CANDIDATES_RELATIVE = "inputs/top5000_candidates.tsv"
SOURCE_JOBS_RELATIVE = "manifests/docking_jobs.tsv"
SOURCE_SHARDS_RELATIVE = "manifests/shards_exact_8"
SOURCE_CFG_LOCK_RELATIVE = "config/FOUR_SEED_CFG_LOCK.json"
REQUIRED_PORTABLE_RESOURCE_RELATIVES = (
    "PROTOCOL_CORE_LOCK.json",
    "config/protocol_spec.json",
    "scripts/common.py",
    "scripts/run_job.py",
    "inputs/normalized/8x6b_pvrig_receptor.pdb",
    "inputs/normalized/9e6y_pvrig_receptor.pdb",
)

EXPECTED_SOURCE_CANDIDATES = 5_000
EXPECTED_SOURCE_JOBS = 40_000
EXPECTED_SOURCE_SHARDS = 8
EXPECTED_SOURCE_CANDIDATES_PER_SHARD = 625
EXPECTED_SOURCE_JOBS_PER_SHARD = 5_000
SELECTED_PER_SOURCE_SHARD = 250
EXPECTED_SELECTED_CANDIDATES = 2_000
EXPECTED_SELECTED_JOBS = 8_000
EXPECTED_NODES = 2
EXPECTED_CANDIDATES_PER_NODE = 1_000
EXPECTED_JOBS_PER_NODE = 4_000

SOURCE_SEEDS = {"42", "917", "1931", "3047"}
ACTIVE_SEEDS = {"42", "3047"}
CONFORMATIONS = {"8x6b", "9e6y"}
SAFE_ID = re.compile(r"[A-Za-z0-9_.-]+")
SHA256_RE = re.compile(r"[0-9a-f]{64}")

SELECTED_FIELDS = [
    "selection_order",
    "node_index",
    "source_shard",
    "source_shard_selection_rank",
    "release_rank",
    "candidate_id",
    "source_candidate_row_sha256",
    "source_eight_job_ids_sha256",
    "selected_four_job_ids_sha256",
]
EXCLUDED_FIELDS = [
    "source_shard",
    "release_rank",
    "candidate_id",
    "in_frozen_unstarted_candidates",
    "started_source_job_count",
    "started_source_job_ids",
    "eligible",
    "exclusion_reason",
]
SHARD_SUMMARY_FIELDS = [
    "source_shard",
    "source_candidates",
    "frozen_unstarted_candidates",
    "started_conflict_candidates",
    "fully_unstarted_eligible_candidates",
    "selected_candidates",
    "rank_cutoff",
    "node_index",
]


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_created_at(value: str) -> str:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("--created-at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("--created-at must include a timezone")
    return value


def safe_relative(value: str) -> pathlib.PurePosixPath:
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe package-relative path: {value!r}")
    return path


def require_regular(path: pathlib.Path, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} is missing, non-regular, or symlinked: {path}")


def read_tsv(path: pathlib.Path) -> tuple[list[str], list[dict[str, str]]]:
    require_regular(path, "TSV")
    if b"\r" in path.read_bytes():
        raise ValueError(f"CRLF is not allowed: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields:
        raise ValueError(f"TSV has no header: {path}")
    return fields, rows


def write_tsv(
    path: pathlib.Path, fields: Sequence[str], rows: Iterable[dict[str, Any]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fields),
            delimiter="\t",
            lineterminator="\n",
            extrasaction="raise",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def parse_sha256sums(root: pathlib.Path) -> dict[str, str]:
    path = root / "SHA256SUMS"
    require_regular(path, "source SHA256SUMS")
    observed: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        if "  " not in line:
            raise ValueError(f"invalid SHA256SUMS line {line_number}")
        digest, relative_text = line.split("  ", 1)
        if not SHA256_RE.fullmatch(digest):
            raise ValueError(f"invalid SHA256 on line {line_number}")
        relative = safe_relative(relative_text).as_posix()
        if relative == "SHA256SUMS" or relative in observed:
            raise ValueError(f"invalid duplicate/self SHA256SUMS entry: {relative}")
        source = root / relative
        require_regular(source, f"SHA256SUMS entry {relative}")
        actual = sha256_file(source)
        if actual != digest:
            raise ValueError(f"source SHA256SUMS mismatch: {relative}")
        observed[relative] = digest
    package_files: set[str] = set()
    for package_path in root.rglob("*"):
        if package_path.is_symlink():
            raise ValueError(f"symlink is forbidden in hash-closed package: {package_path}")
        if package_path.is_file() and package_path.name != "SHA256SUMS":
            package_files.add(package_path.relative_to(root).as_posix())
    if set(observed) != package_files:
        missing = sorted(package_files.difference(observed))
        stale = sorted(set(observed).difference(package_files))
        raise ValueError(
            "SHA256SUMS is not exact package file closure; "
            f"missing={missing[:10]}, stale={stale[:10]}"
        )
    return observed


def _ids_from_json(payload: Any, aliases: Sequence[str]) -> list[str]:
    if isinstance(payload, list):
        return [str(value) for value in payload]
    if isinstance(payload, dict):
        for alias in aliases:
            if alias in payload and isinstance(payload[alias], list):
                return [str(value) for value in payload[alias]]
    raise ValueError(f"JSON ID input must be a list or contain one of {aliases}")


def read_frozen_ids(
    path: pathlib.Path, aliases: Sequence[str], label: str
) -> tuple[list[str], bytes]:
    require_regular(path, label)
    raw = path.read_bytes()
    if path.suffix.lower() == ".json":
        values = _ids_from_json(json.loads(raw.decode("utf-8")), aliases)
    else:
        text = raw.decode("utf-8")
        lines = [
            line
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if not lines:
            values = []
        elif "\t" in lines[0] or "," in lines[0]:
            delimiter = "\t" if "\t" in lines[0] else ","
            reader = csv.DictReader(lines, delimiter=delimiter)
            field = next(
                (alias for alias in aliases if alias in (reader.fieldnames or [])),
                None,
            )
            if field is None:
                raise ValueError(f"{label} table lacks one of columns {aliases}")
            values = [str(row[field]) for row in reader]
        else:
            first = lines[0].strip()
            values = lines[1:] if first in aliases else lines
    normalized = [value.strip() for value in values]
    if any(not value or any(character.isspace() for character in value) for value in normalized):
        raise ValueError(f"{label} contains an empty or whitespace-bearing ID")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} contains duplicate IDs")
    return normalized, raw


def validate_expected_sha(path: pathlib.Path, expected: str | None, label: str) -> None:
    if expected is None:
        return
    if not SHA256_RE.fullmatch(expected):
        raise ValueError(f"{label} expected SHA256 is malformed")
    if sha256_file(path) != expected:
        raise ValueError(f"{label} SHA256 mismatch")


def validate_source_package(source_root: pathlib.Path) -> dict[str, Any]:
    sha256_entries = parse_sha256sums(source_root)
    required_sha256_entries = {
        "READY.json",
        "HANDOFF_RECEIPT.json",
        SOURCE_CANDIDATES_RELATIVE,
        SOURCE_JOBS_RELATIVE,
        SOURCE_CFG_LOCK_RELATIVE,
        *REQUIRED_PORTABLE_RESOURCE_RELATIVES,
        *{
            f"{SOURCE_SHARDS_RELATIVE}/shard_{shard_index:02d}.tsv"
            for shard_index in range(EXPECTED_SOURCE_SHARDS)
        },
    }
    missing_sha256_entries = sorted(required_sha256_entries.difference(sha256_entries))
    if missing_sha256_entries:
        raise ValueError(
            "source SHA256SUMS does not bind required package files: "
            + ", ".join(missing_sha256_entries)
        )
    ready_path = source_root / "READY.json"
    receipt_path = source_root / "HANDOFF_RECEIPT.json"
    require_regular(ready_path, "source READY")
    require_regular(receipt_path, "source HANDOFF_RECEIPT")
    ready = json.loads(ready_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if ready.get("status") != "READY_FOR_EXTERNAL_DOCKING_SUBMISSION":
        raise ValueError("source READY status is not submission-ready")
    if receipt.get("status") != "READY_FOR_EXTERNAL_DOCKING_SUBMISSION":
        raise ValueError("source HANDOFF_RECEIPT status is not submission-ready")
    if ready.get("docking_started") is not False or receipt.get("docking_started") is not False:
        raise ValueError("source handoff must declare docking_started=false")
    if ready.get("handoff_receipt_sha256") != sha256_file(receipt_path):
        raise ValueError("source READY does not bind HANDOFF_RECEIPT")
    for relative in REQUIRED_PORTABLE_RESOURCE_RELATIVES:
        require_regular(source_root / relative, f"source portable resource {relative}")

    protocol_lock = json.loads(
        (source_root / "PROTOCOL_CORE_LOCK.json").read_text(encoding="utf-8")
    )
    source_cfg_lock = json.loads(
        (source_root / SOURCE_CFG_LOCK_RELATIVE).read_text(encoding="utf-8")
    )
    if source_cfg_lock.get("status") != "LOCKED":
        raise ValueError("source four-seed cfg lock is not LOCKED")
    if {str(value) for value in source_cfg_lock.get("seeds", [])} != SOURCE_SEEDS:
        raise ValueError("source cfg lock seeds are not exact 917/1931/42/3047")
    if set(source_cfg_lock.get("conformations", [])) != CONFORMATIONS:
        raise ValueError("source cfg lock conformations are not exact dual receptors")
    if (
        source_cfg_lock.get("protocol_core_sha256")
        != protocol_lock.get("protocol_core_sha256")
    ):
        raise ValueError("source cfg lock does not bind protocol core")
    cfg_hashes = source_cfg_lock.get("cfg_hashes")
    cfg_payloads = source_cfg_lock.get("cfg_payloads")
    if not isinstance(cfg_hashes, dict) or not isinstance(cfg_payloads, dict):
        raise ValueError("source cfg lock lacks cfg hashes/payloads")
    for seed in SOURCE_SEEDS:
        if set(cfg_hashes.get(seed, {})) != CONFORMATIONS:
            raise ValueError(f"source cfg hash matrix mismatch for seed {seed}")
        if set(cfg_payloads.get(seed, {})) != CONFORMATIONS:
            raise ValueError(f"source cfg payload matrix mismatch for seed {seed}")

    candidate_path = source_root / SOURCE_CANDIDATES_RELATIVE
    jobs_path = source_root / SOURCE_JOBS_RELATIVE
    candidate_fields, candidate_rows = read_tsv(candidate_path)
    job_fields, job_rows = read_tsv(jobs_path)
    required_candidate_fields = {
        "release_rank",
        "candidate_id",
        "monomer_source",
        "monomer_sha256",
    }
    required_job_fields = {
        "job_id",
        "job_hash",
        "entity_id",
        "seed",
        "conformation",
        "monomer_source",
        "receptor_pdb",
        "cfg_hash",
    }
    if not required_candidate_fields.issubset(candidate_fields):
        raise ValueError("source candidate manifest lacks required fields")
    if not required_job_fields.issubset(job_fields):
        raise ValueError("source job manifest lacks required fields")
    if len(candidate_rows) != EXPECTED_SOURCE_CANDIDATES:
        raise ValueError("source candidate manifest is not exact 5000")
    if len(job_rows) != EXPECTED_SOURCE_JOBS:
        raise ValueError("source job manifest is not exact 40000")
    if ready.get("candidates") != EXPECTED_SOURCE_CANDIDATES:
        raise ValueError("source READY candidate count mismatch")
    if ready.get("jobs") != EXPECTED_SOURCE_JOBS:
        raise ValueError("source READY job count mismatch")
    if ready.get("shards") != EXPECTED_SOURCE_SHARDS:
        raise ValueError("source READY shard count mismatch")
    if ready.get("job_manifest_sha256") != sha256_file(jobs_path):
        raise ValueError("source READY job manifest SHA256 mismatch")

    candidates_by_id: dict[str, dict[str, str]] = {}
    ranks: set[int] = set()
    monomer_paths: set[str] = set()
    for row in candidate_rows:
        candidate_id = row["candidate_id"]
        if not SAFE_ID.fullmatch(candidate_id):
            raise ValueError(f"unsafe source candidate ID: {candidate_id!r}")
        if candidate_id in candidates_by_id:
            raise ValueError(f"duplicate source candidate ID: {candidate_id}")
        rank = int(row["release_rank"])
        if rank in ranks:
            raise ValueError(f"duplicate source release_rank: {rank}")
        ranks.add(rank)
        monomer_relative = safe_relative(row["monomer_source"]).as_posix()
        if monomer_relative in monomer_paths:
            raise ValueError(f"duplicate monomer_source: {monomer_relative}")
        monomer_paths.add(monomer_relative)
        monomer = source_root / monomer_relative
        require_regular(monomer, f"source monomer {candidate_id}")
        if sha256_file(monomer) != row["monomer_sha256"]:
            raise ValueError(f"source monomer SHA256 mismatch: {candidate_id}")
        if sha256_entries.get(monomer_relative) != row["monomer_sha256"]:
            raise ValueError(f"source SHA256SUMS does not bind monomer: {candidate_id}")
        candidates_by_id[candidate_id] = row
    if ranks != set(range(1, EXPECTED_SOURCE_CANDIDATES + 1)):
        raise ValueError("source release_rank values are not exact 1..5000")

    jobs_by_id: dict[str, dict[str, str]] = {}
    jobs_by_candidate: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    job_hashes: set[str] = set()
    source_job_index: dict[str, int] = {}
    for index, row in enumerate(job_rows):
        job_id = row["job_id"]
        if not SAFE_ID.fullmatch(job_id):
            raise ValueError(f"unsafe source job ID: {job_id!r}")
        if job_id in jobs_by_id:
            raise ValueError(f"duplicate source job ID: {job_id}")
        if not SHA256_RE.fullmatch(row["job_hash"]) or row["job_hash"] in job_hashes:
            raise ValueError(f"invalid or duplicate source job_hash: {job_id}")
        candidate_id = row["entity_id"]
        if candidate_id not in candidates_by_id:
            raise ValueError(f"job references unknown candidate: {job_id}")
        if row["monomer_source"] != candidates_by_id[candidate_id]["monomer_source"]:
            raise ValueError(f"job monomer_source mismatch: {job_id}")
        if row["seed"] not in SOURCE_SEEDS or row["conformation"] not in CONFORMATIONS:
            raise ValueError(f"job seed/conformation is outside source matrix: {job_id}")
        if row["cfg_hash"] != cfg_hashes[row["seed"]][row["conformation"]]:
            raise ValueError(f"job cfg_hash does not match source cfg lock: {job_id}")
        receptor_relative = safe_relative(row["receptor_pdb"]).as_posix()
        require_regular(source_root / receptor_relative, f"source receptor {job_id}")
        if receptor_relative not in sha256_entries:
            raise ValueError(f"source SHA256SUMS does not bind receptor: {job_id}")
        jobs_by_id[job_id] = row
        job_hashes.add(row["job_hash"])
        jobs_by_candidate[candidate_id].append(row)
        source_job_index[job_id] = index

    expected_matrix = {
        (seed, conformation)
        for seed in SOURCE_SEEDS
        for conformation in CONFORMATIONS
    }
    for candidate_id in candidates_by_id:
        rows = jobs_by_candidate[candidate_id]
        matrix = {(row["seed"], row["conformation"]) for row in rows}
        if len(rows) != 8 or matrix != expected_matrix:
            raise ValueError(f"source candidate lacks exact 4x2 matrix: {candidate_id}")

    source_shards: list[list[str]] = []
    observed_job_ids: set[str] = set()
    observed_candidates: set[str] = set()
    candidate_to_shard: dict[str, int] = {}
    for shard_index in range(EXPECTED_SOURCE_SHARDS):
        shard_path = (
            source_root
            / SOURCE_SHARDS_RELATIVE
            / f"shard_{shard_index:02d}.tsv"
        )
        _, shard_rows = read_tsv(shard_path)
        if len(shard_rows) != EXPECTED_SOURCE_JOBS_PER_SHARD:
            raise ValueError(f"source shard {shard_index} is not exact 5000 jobs")
        shard_job_ids = [row["job_id"] for row in shard_rows]
        if len(set(shard_job_ids)) != EXPECTED_SOURCE_JOBS_PER_SHARD:
            raise ValueError(f"source shard {shard_index} has duplicate jobs")
        shard_candidates = {jobs_by_id[job_id]["entity_id"] for job_id in shard_job_ids}
        if len(shard_candidates) != EXPECTED_SOURCE_CANDIDATES_PER_SHARD:
            raise ValueError(f"source shard {shard_index} is not exact 625 candidates")
        if observed_job_ids.intersection(shard_job_ids):
            raise ValueError("source jobs occur in multiple original shards")
        if observed_candidates.intersection(shard_candidates):
            raise ValueError("source candidate unit is split across original shards")
        for job_id, shard_row in zip(shard_job_ids, shard_rows):
            if shard_row.get("job_hash") != jobs_by_id[job_id]["job_hash"]:
                raise ValueError(f"source shard/master job mismatch: {job_id}")
        for candidate_id in shard_candidates:
            candidate_to_shard[candidate_id] = shard_index
        observed_job_ids.update(shard_job_ids)
        observed_candidates.update(shard_candidates)
        source_shards.append(sorted(shard_candidates))
    if observed_job_ids != set(jobs_by_id):
        raise ValueError("original shards are not exact job closure")
    if observed_candidates != set(candidates_by_id):
        raise ValueError("original shards are not exact candidate closure")
    return {
        "sha256_entries": sha256_entries,
        "ready": ready,
        "receipt": receipt,
        "candidate_fields": candidate_fields,
        "candidate_rows": candidate_rows,
        "candidates_by_id": candidates_by_id,
        "job_fields": job_fields,
        "job_rows": job_rows,
        "jobs_by_id": jobs_by_id,
        "jobs_by_candidate": jobs_by_candidate,
        "source_job_index": source_job_index,
        "source_shards": source_shards,
        "candidate_to_shard": candidate_to_shard,
    }


def select_candidates(
    source: dict[str, Any],
    unstarted_candidates: set[str],
    started_job_ids: set[str],
) -> dict[str, Any]:
    selected_rows: list[dict[str, str]] = []
    excluded_rows: list[dict[str, str]] = []
    summary_rows: list[dict[str, str]] = []
    selected_candidate_ids: list[str] = []
    selected_by_node: dict[int, list[str]] = {0: [], 1: []}
    candidates_by_id = source["candidates_by_id"]
    jobs_by_candidate = source["jobs_by_candidate"]

    selection_order = 0
    for shard_index, shard_candidate_ids in enumerate(source["source_shards"]):
        ranked = sorted(
            shard_candidate_ids,
            key=lambda candidate_id: (
                int(candidates_by_id[candidate_id]["release_rank"]),
                candidate_id,
            ),
        )
        eligible: list[str] = []
        started_conflicts: dict[str, list[str]] = {}
        frozen_unstarted_count = 0
        for candidate_id in ranked:
            if candidate_id in unstarted_candidates:
                frozen_unstarted_count += 1
            conflicts = sorted(
                row["job_id"]
                for row in jobs_by_candidate[candidate_id]
                if row["job_id"] in started_job_ids
            )
            if conflicts:
                started_conflicts[candidate_id] = conflicts
            if candidate_id in unstarted_candidates and not conflicts:
                eligible.append(candidate_id)
        if len(eligible) < SELECTED_PER_SOURCE_SHARD:
            raise ValueError(
                f"source shard {shard_index} has only {len(eligible)} fully "
                f"unstarted candidates; need {SELECTED_PER_SOURCE_SHARD}"
            )
        selected = eligible[:SELECTED_PER_SOURCE_SHARD]
        selected_set = set(selected)
        node_index = 0 if shard_index < 4 else 1
        rank_cutoff = candidates_by_id[selected[-1]]["release_rank"]
        for shard_selection_rank, candidate_id in enumerate(selected, 1):
            selection_order += 1
            candidate = candidates_by_id[candidate_id]
            source_jobs = sorted(
                jobs_by_candidate[candidate_id],
                key=lambda row: source["source_job_index"][row["job_id"]],
            )
            active_jobs = [
                row
                for row in source_jobs
                if row["seed"] in ACTIVE_SEEDS
                and row["conformation"] in CONFORMATIONS
            ]
            if len(active_jobs) != 4 or {
                (row["seed"], row["conformation"]) for row in active_jobs
            } != {
                (seed, conformation)
                for seed in ACTIVE_SEEDS
                for conformation in CONFORMATIONS
            }:
                raise ValueError(f"selected candidate active 2x2 matrix mismatch: {candidate_id}")
            selected_rows.append(
                {
                    "selection_order": str(selection_order),
                    "node_index": str(node_index),
                    "source_shard": str(shard_index),
                    "source_shard_selection_rank": str(shard_selection_rank),
                    "release_rank": candidate["release_rank"],
                    "candidate_id": candidate_id,
                    "source_candidate_row_sha256": sha256_text(
                        canonical_json(candidate)
                    ),
                    "source_eight_job_ids_sha256": sha256_text(
                        "".join(f"{row['job_id']}\n" for row in source_jobs)
                    ),
                    "selected_four_job_ids_sha256": sha256_text(
                        "".join(f"{row['job_id']}\n" for row in active_jobs)
                    ),
                }
            )
            selected_candidate_ids.append(candidate_id)
            selected_by_node[node_index].append(candidate_id)
        for candidate_id in ranked:
            if candidate_id in selected_set:
                continue
            candidate = candidates_by_id[candidate_id]
            conflicts = started_conflicts.get(candidate_id, [])
            reasons: list[str] = []
            if candidate_id not in unstarted_candidates:
                reasons.append("NOT_IN_FROZEN_UNSTARTED_CANDIDATES")
            if conflicts:
                reasons.append("HAS_STARTED_SOURCE_JOB")
            if not reasons:
                reasons.append("ELIGIBLE_AFTER_LOWEST_RELEASE_RANK_CUTOFF")
            excluded_rows.append(
                {
                    "source_shard": str(shard_index),
                    "release_rank": candidate["release_rank"],
                    "candidate_id": candidate_id,
                    "in_frozen_unstarted_candidates": (
                        "true" if candidate_id in unstarted_candidates else "false"
                    ),
                    "started_source_job_count": str(len(conflicts)),
                    "started_source_job_ids": ",".join(conflicts),
                    "eligible": (
                        "true"
                        if candidate_id in unstarted_candidates and not conflicts
                        else "false"
                    ),
                    "exclusion_reason": ";".join(reasons),
                }
            )
        summary_rows.append(
            {
                "source_shard": str(shard_index),
                "source_candidates": str(len(ranked)),
                "frozen_unstarted_candidates": str(frozen_unstarted_count),
                "started_conflict_candidates": str(len(started_conflicts)),
                "fully_unstarted_eligible_candidates": str(len(eligible)),
                "selected_candidates": str(len(selected)),
                "rank_cutoff": rank_cutoff,
                "node_index": str(node_index),
            }
        )

    if len(selected_candidate_ids) != EXPECTED_SELECTED_CANDIDATES:
        raise AssertionError("selection is not exact 2000 candidates")
    if len(set(selected_candidate_ids)) != EXPECTED_SELECTED_CANDIDATES:
        raise AssertionError("selected candidates are not unique")
    if len(excluded_rows) != EXPECTED_SOURCE_CANDIDATES - EXPECTED_SELECTED_CANDIDATES:
        raise AssertionError("exclusion ledger is not exact source-minus-selected closure")
    for node_index in range(EXPECTED_NODES):
        if len(selected_by_node[node_index]) != EXPECTED_CANDIDATES_PER_NODE:
            raise AssertionError(f"node {node_index} is not exact 1000 candidates")
    return {
        "selected_rows": selected_rows,
        "excluded_rows": excluded_rows,
        "summary_rows": summary_rows,
        "selected_candidate_ids": selected_candidate_ids,
        "selected_by_node": selected_by_node,
    }


def copy_regular_file(source: pathlib.Path, destination: pathlib.Path) -> None:
    require_regular(source, "portable source file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError(f"portable resource destination collision: {destination}")
    shutil.copyfile(source, destination)
    if sha256_file(source) != sha256_file(destination):
        raise ValueError(f"portable resource copy hash mismatch: {source}")


def copy_tree(source: pathlib.Path, destination: pathlib.Path) -> list[str]:
    copied: list[str] = []
    if not source.exists():
        return copied
    if not source.is_dir() or source.is_symlink():
        raise ValueError(f"portable resource tree is unsafe: {source}")
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink is forbidden in portable resources: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        target = destination / relative
        copy_regular_file(path, target)
        copied.append(relative.as_posix())
    return copied


def write_sha256sums(root: pathlib.Path) -> None:
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and path.name != "SHA256SUMS"
    )
    write_text(
        root / "SHA256SUMS",
        "".join(
            f"{sha256_file(path)}  {path.relative_to(root).as_posix()}\n"
            for path in files
        ),
    )


def readme_text() -> str:
    return """# Top5000 fully-unstarted seed42/3047 two-node handoff

This package is a deterministic subset of the frozen Top5000 dual-receptor
four-seed source handoff.

- Selection: the 250 lowest `release_rank` fully-unstarted candidates from each
  of the eight original source shards.
- Active jobs: source jobs for seeds 42 and 3047 across receptors 8x6b and
  9e6y; source `job_id`, `job_hash`, and every source job field are unchanged.
- Scale: 2,000 candidates, 8,000 jobs, two node manifests with exactly 1,000
  candidates and 4,000 jobs each.
- Node 0 receives original shards 0-3; Node 1 receives original shards 4-7.
- `selection/frozen_inputs/` preserves the exact authority files supplied to
  the builder.  Canonical normalized ID lists and selection/exclusion ledgers
  are adjacent.
- `selection/STARTED_JOB_OVERLAP.tsv` is header-only by contract.

This package only prepares a portable handoff.  It does not launch Docking,
contact Node1/bxcpu, or claim biological/experimental validation.
"""


def build_handoff(
    source_root: pathlib.Path,
    unstarted_path: pathlib.Path,
    started_path: pathlib.Path,
    output_root: pathlib.Path,
    created_at: str,
    *,
    expected_source_ready_sha256: str | None = None,
    expected_unstarted_sha256: str | None = None,
    expected_started_sha256: str | None = None,
) -> dict[str, Any]:
    source_root = source_root.resolve()
    unstarted_path = unstarted_path.resolve()
    started_path = started_path.resolve()
    output_root = output_root.resolve()
    validate_created_at(created_at)
    if not source_root.is_dir() or source_root.is_symlink():
        raise ValueError(f"source package root is missing or unsafe: {source_root}")
    if output_root == source_root or source_root in output_root.parents:
        raise ValueError("output root must not be inside the source package")
    if output_root.exists():
        raise ValueError(f"refusing to overwrite output root: {output_root}")
    validate_expected_sha(
        source_root / "READY.json",
        expected_source_ready_sha256,
        "source READY",
    )
    validate_expected_sha(
        unstarted_path, expected_unstarted_sha256, "UNSTARTED_CANDIDATES"
    )
    validate_expected_sha(
        started_path, expected_started_sha256, "STARTED_JOB_IDS"
    )

    unstarted_ordered, unstarted_raw = read_frozen_ids(
        unstarted_path,
        ("candidate_id", "entity_id", "unstarted_candidates", "candidate_ids"),
        "UNSTARTED_CANDIDATES",
    )
    started_ordered, started_raw = read_frozen_ids(
        started_path,
        ("job_id", "started_job_ids", "job_ids"),
        "STARTED_JOB_IDS",
    )
    unstarted_candidates = set(unstarted_ordered)
    started_job_ids = set(started_ordered)
    source = validate_source_package(source_root)
    selection = select_candidates(source, unstarted_candidates, started_job_ids)

    selected_set = set(selection["selected_candidate_ids"])
    selected_candidate_rows = [
        source["candidates_by_id"][candidate_id]
        for candidate_id in selection["selected_candidate_ids"]
    ]
    selected_jobs: list[dict[str, str]] = []
    jobs_by_node: dict[int, list[dict[str, str]]] = {0: [], 1: []}
    for node_index in range(EXPECTED_NODES):
        for candidate_id in selection["selected_by_node"][node_index]:
            rows = sorted(
                (
                    row
                    for row in source["jobs_by_candidate"][candidate_id]
                    if row["seed"] in ACTIVE_SEEDS
                    and row["conformation"] in CONFORMATIONS
                ),
                key=lambda row: source["source_job_index"][row["job_id"]],
            )
            jobs_by_node[node_index].extend(rows)
            selected_jobs.extend(rows)
    if len(selected_jobs) != EXPECTED_SELECTED_JOBS:
        raise AssertionError("selected manifest is not exact 8000 jobs")
    if len({row["job_id"] for row in selected_jobs}) != EXPECTED_SELECTED_JOBS:
        raise AssertionError("selected job IDs are not unique")
    if len({row["job_hash"] for row in selected_jobs}) != EXPECTED_SELECTED_JOBS:
        raise AssertionError("selected job hashes are not unique")
    selected_started_overlap = sorted(
        {row["job_id"] for row in selected_jobs}.intersection(started_job_ids)
    )
    if selected_started_overlap:
        raise AssertionError(
            f"selected jobs overlap STARTED_JOB_IDS: {selected_started_overlap[:10]}"
        )
    for node_index in range(EXPECTED_NODES):
        node_jobs = jobs_by_node[node_index]
        if len(node_jobs) != EXPECTED_JOBS_PER_NODE:
            raise AssertionError(f"node {node_index} is not exact 4000 jobs")
        if len({row["entity_id"] for row in node_jobs}) != EXPECTED_CANDIDATES_PER_NODE:
            raise AssertionError(f"node {node_index} is not exact 1000 candidates")

    staging_root = output_root.with_name(
        f".{output_root.name}.staging.{os.getpid()}.{uuid.uuid4().hex}"
    )
    staging_root.mkdir(parents=True)
    try:
        # Preserve complete runtime/protocol resources without modifying source files.
        copy_regular_file(
            source_root / "PROTOCOL_CORE_LOCK.json",
            staging_root / "PROTOCOL_CORE_LOCK.json",
        )
        copied_resources = {
            "config": copy_tree(source_root / "config", staging_root / "config"),
            "scripts": copy_tree(source_root / "scripts", staging_root / "scripts"),
            "inputs_normalized": copy_tree(
                source_root / "inputs/normalized",
                staging_root / "inputs/normalized",
            ),
            "inputs_source": copy_tree(
                source_root / "inputs/source",
                staging_root / "inputs/source",
            ),
        }
        copy_regular_file(
            source_root / "READY.json",
            staging_root / "source_provenance/SOURCE_READY.json",
        )
        copy_regular_file(
            source_root / "HANDOFF_RECEIPT.json",
            staging_root / "source_provenance/SOURCE_HANDOFF_RECEIPT.json",
        )
        copy_regular_file(
            source_root / "SHA256SUMS",
            staging_root / "source_provenance/SOURCE_SHA256SUMS",
        )

        for candidate in selected_candidate_rows:
            relative = safe_relative(candidate["monomer_source"])
            source_monomer = source_root / relative
            destination = staging_root / relative
            copy_regular_file(source_monomer, destination)
            if sha256_file(destination) != candidate["monomer_sha256"]:
                raise ValueError(
                    f"selected monomer hash mismatch: {candidate['candidate_id']}"
                )

        write_tsv(
            staging_root / "inputs/selected_candidates.tsv",
            source["candidate_fields"],
            selected_candidate_rows,
        )
        write_tsv(
            staging_root / "manifests/docking_jobs.tsv",
            source["job_fields"],
            selected_jobs,
        )
        for node_index in range(EXPECTED_NODES):
            write_tsv(
                staging_root
                / "manifests/nodes_exact_2"
                / f"node_{node_index:02d}.tsv",
                source["job_fields"],
                jobs_by_node[node_index],
            )

        frozen_root = staging_root / "selection/frozen_inputs"
        frozen_root.mkdir(parents=True)
        (frozen_root / "UNSTARTED_CANDIDATES.source").write_bytes(unstarted_raw)
        (frozen_root / "STARTED_JOB_IDS.source").write_bytes(started_raw)
        write_text(
            staging_root / "selection/UNSTARTED_CANDIDATES.normalized.txt",
            "".join(f"{value}\n" for value in sorted(unstarted_candidates)),
        )
        write_text(
            staging_root / "selection/STARTED_JOB_IDS.normalized.txt",
            "".join(f"{value}\n" for value in sorted(started_job_ids)),
        )
        write_tsv(
            staging_root / "selection/SELECTED_CANDIDATES.tsv",
            SELECTED_FIELDS,
            selection["selected_rows"],
        )
        write_tsv(
            staging_root / "selection/EXCLUDED_CANDIDATES.tsv",
            EXCLUDED_FIELDS,
            selection["excluded_rows"],
        )
        write_tsv(
            staging_root / "selection/SOURCE_SHARD_SELECTION_SUMMARY.tsv",
            SHARD_SUMMARY_FIELDS,
            selection["summary_rows"],
        )
        write_tsv(
            staging_root / "selection/STARTED_JOB_OVERLAP.tsv",
            ["job_id", "candidate_id", "source_shard", "node_index"],
            [],
        )

        source_cfg_lock_path = source_root / SOURCE_CFG_LOCK_RELATIVE
        require_regular(source_cfg_lock_path, "source four-seed cfg lock")
        source_cfg_lock = json.loads(source_cfg_lock_path.read_text(encoding="utf-8"))
        two_seed_cfg_lock = {
            "schema_version": "pvrig.two_seed_cfg_lock.v1",
            "status": "LOCKED",
            "source_four_seed_cfg_lock_sha256": sha256_file(source_cfg_lock_path),
            "protocol_core_sha256": source_cfg_lock.get("protocol_core_sha256"),
            "seeds": [42, 3047],
            "conformations": ["8x6b", "9e6y"],
            "cfg_hashes": {
                seed: source_cfg_lock["cfg_hashes"][seed]
                for seed in ("42", "3047")
            },
            "cfg_payloads": {
                seed: source_cfg_lock["cfg_payloads"][seed]
                for seed in ("42", "3047")
            },
        }
        write_json(staging_root / "config/TWO_SEED_CFG_LOCK.json", two_seed_cfg_lock)

        node_receipt = {
            "schema_version": "pvrig.top5000.two_node_exact_dispatch.v1",
            "status": "PASS_EXACT_2_NODE_CLOSURE",
            "nodes": [
                {
                    "node_index": node_index,
                    "source_shards": list(range(node_index * 4, node_index * 4 + 4)),
                    "candidates": EXPECTED_CANDIDATES_PER_NODE,
                    "jobs": EXPECTED_JOBS_PER_NODE,
                    "manifest": f"manifests/nodes_exact_2/node_{node_index:02d}.tsv",
                    "manifest_sha256": sha256_file(
                        staging_root
                        / "manifests/nodes_exact_2"
                        / f"node_{node_index:02d}.tsv"
                    ),
                }
                for node_index in range(EXPECTED_NODES)
            ],
            "total_candidates": EXPECTED_SELECTED_CANDIDATES,
            "total_jobs": EXPECTED_SELECTED_JOBS,
            "candidate_units_split_across_nodes": 0,
            "started_job_overlap": 0,
        }
        write_json(
            staging_root / "manifests/nodes_exact_2/NODE_RECEIPT.json",
            node_receipt,
        )

        docking_plan = {
            "schema_version": "pvrig.top5000.seed42_3047.two_node_plan.v1",
            "status": "READY_2_NODES_1000_CANDIDATES_4000_JOBS_EACH",
            "created_at": created_at,
            "docking_started": False,
            "seeds": [42, 3047],
            "conformations": ["8x6b", "9e6y"],
            "selection": {
                "source_shards": 8,
                "selected_per_source_shard": SELECTED_PER_SOURCE_SHARD,
                "ordering": "ascending release_rank then candidate_id",
                "eligibility": (
                    "candidate is in frozen UNSTARTED_CANDIDATES and none of "
                    "its eight source jobs is in frozen STARTED_JOB_IDS"
                ),
            },
            "dispatch": node_receipt["nodes"],
            "resource_intent": {
                "nodes": 2,
                "candidates_per_node": 1000,
                "jobs_per_node": 4000,
                "jobs_per_candidate": 4,
            },
            "preserve_source_job_id_and_job_hash": True,
            "started_job_overlap": 0,
        }
        write_json(staging_root / "DOCKING_PLAN.json", docking_plan)
        write_text(staging_root / "README.md", readme_text())

        selected_manifest_path = staging_root / "manifests/docking_jobs.tsv"
        selection_path = staging_root / "selection/SELECTED_CANDIDATES.tsv"
        exclusion_path = staging_root / "selection/EXCLUDED_CANDIDATES.tsv"
        plan_path = staging_root / "DOCKING_PLAN.json"
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "package_version": PACKAGE_VERSION,
            "status": "READY_FOR_EXTERNAL_DOCKING_SUBMISSION",
            "created_at": created_at,
            "docking_started": False,
            "claim_boundary": (
                "Portable computational docking handoff only; no remote mutation, "
                "biological validation, or experimental blocking claim."
            ),
            "source_package": {
                "ready_sha256": sha256_file(source_root / "READY.json"),
                "handoff_receipt_sha256": sha256_file(
                    source_root / "HANDOFF_RECEIPT.json"
                ),
                "sha256sums_sha256": sha256_file(source_root / "SHA256SUMS"),
                "candidate_manifest_sha256": sha256_file(
                    source_root / SOURCE_CANDIDATES_RELATIVE
                ),
                "job_manifest_sha256": sha256_file(
                    source_root / SOURCE_JOBS_RELATIVE
                ),
                "package_version": source["receipt"].get("package_version"),
            },
            "frozen_authorities": {
                "unstarted_candidates_source_sha256": sha256_bytes(unstarted_raw),
                "unstarted_candidates_normalized_sha256": sha256_file(
                    staging_root
                    / "selection/UNSTARTED_CANDIDATES.normalized.txt"
                ),
                "unstarted_candidates_count": len(unstarted_candidates),
                "started_job_ids_source_sha256": sha256_bytes(started_raw),
                "started_job_ids_normalized_sha256": sha256_file(
                    staging_root / "selection/STARTED_JOB_IDS.normalized.txt"
                ),
                "started_job_ids_count": len(started_job_ids),
            },
            "counts": {
                "source_candidates": EXPECTED_SOURCE_CANDIDATES,
                "source_jobs": EXPECTED_SOURCE_JOBS,
                "selected_candidates": EXPECTED_SELECTED_CANDIDATES,
                "selected_jobs": EXPECTED_SELECTED_JOBS,
                "source_shards": EXPECTED_SOURCE_SHARDS,
                "selected_per_source_shard": SELECTED_PER_SOURCE_SHARD,
                "nodes": EXPECTED_NODES,
                "candidates_per_node": EXPECTED_CANDIDATES_PER_NODE,
                "jobs_per_node": EXPECTED_JOBS_PER_NODE,
                "excluded_candidates": len(selection["excluded_rows"]),
                "started_job_overlap": 0,
            },
            "protocol": {
                "seeds": [42, 3047],
                "conformations": ["8x6b", "9e6y"],
                "source_job_id_preserved": True,
                "source_job_hash_preserved": True,
                "two_seed_cfg_lock_sha256": sha256_file(
                    staging_root / "config/TWO_SEED_CFG_LOCK.json"
                ),
            },
            "selection_by_source_shard": selection["summary_rows"],
            "portable_resources": {
                key: {"file_count": len(values)}
                for key, values in copied_resources.items()
            },
            "outputs": {
                "selected_candidate_manifest": {
                    "path": "inputs/selected_candidates.tsv",
                    "sha256": sha256_file(
                        staging_root / "inputs/selected_candidates.tsv"
                    ),
                    "rows": EXPECTED_SELECTED_CANDIDATES,
                },
                "job_manifest": {
                    "path": "manifests/docking_jobs.tsv",
                    "sha256": sha256_file(selected_manifest_path),
                    "rows": EXPECTED_SELECTED_JOBS,
                },
                "selection": {
                    "path": "selection/SELECTED_CANDIDATES.tsv",
                    "sha256": sha256_file(selection_path),
                    "rows": EXPECTED_SELECTED_CANDIDATES,
                },
                "exclusion": {
                    "path": "selection/EXCLUDED_CANDIDATES.tsv",
                    "sha256": sha256_file(exclusion_path),
                    "rows": len(selection["excluded_rows"]),
                },
                "docking_plan": {
                    "path": "DOCKING_PLAN.json",
                    "sha256": sha256_file(plan_path),
                },
                "node_receipt": {
                    "path": "manifests/nodes_exact_2/NODE_RECEIPT.json",
                    "sha256": sha256_file(
                        staging_root
                        / "manifests/nodes_exact_2/NODE_RECEIPT.json"
                    ),
                },
            },
            "invariants": {
                "selected_candidates_are_fully_unstarted": True,
                "selected_job_started_overlap_zero": True,
                "eight_source_shards_each_contribute_250": True,
                "lowest_release_rank_selection_is_deterministic": True,
                "source_job_id_and_job_hash_preserved": True,
                "two_nodes_exact_1000_candidates_4000_jobs_each": True,
                "source_package_unmodified": True,
            },
        }
        write_json(staging_root / "HANDOFF_RECEIPT.json", receipt)
        ready = {
            "schema_version": "pvrig.handoff.ready.v1",
            "package_version": PACKAGE_VERSION,
            "status": "READY_FOR_EXTERNAL_DOCKING_SUBMISSION",
            "created_at": created_at,
            "docking_started": False,
            "candidates": EXPECTED_SELECTED_CANDIDATES,
            "jobs": EXPECTED_SELECTED_JOBS,
            "nodes": EXPECTED_NODES,
            "candidates_per_node": EXPECTED_CANDIDATES_PER_NODE,
            "jobs_per_node": EXPECTED_JOBS_PER_NODE,
            "seeds": [42, 3047],
            "conformations": ["8x6b", "9e6y"],
            "started_job_overlap": 0,
            "handoff_receipt_sha256": sha256_file(
                staging_root / "HANDOFF_RECEIPT.json"
            ),
            "job_manifest_sha256": sha256_file(selected_manifest_path),
            "docking_plan_sha256": sha256_file(plan_path),
            "selection_sha256": sha256_file(selection_path),
            "node_receipt_sha256": sha256_file(
                staging_root / "manifests/nodes_exact_2/NODE_RECEIPT.json"
            ),
        }
        write_json(staging_root / "READY.json", ready)
        write_sha256sums(staging_root)

        # Re-read final manifests before atomic publish.
        final_candidate_fields, final_candidates = read_tsv(
            staging_root / "inputs/selected_candidates.tsv"
        )
        _, final_jobs = read_tsv(staging_root / "manifests/docking_jobs.tsv")
        if final_candidate_fields != source["candidate_fields"]:
            raise AssertionError("final candidate manifest fields changed")
        if final_candidates != selected_candidate_rows:
            raise AssertionError("final candidate rows changed from source")
        if {row["job_id"] for row in final_jobs}.intersection(started_job_ids):
            raise AssertionError("final package has started job overlap")
        if {row["entity_id"] for row in final_jobs} != selected_set:
            raise AssertionError("final job/candidate closure mismatch")
        if any(row != source["jobs_by_id"][row["job_id"]] for row in final_jobs):
            raise AssertionError("final source job row identity was not preserved")
        package_sha256_entries = parse_sha256sums(staging_root)
        package_regular_files = {
            path.relative_to(staging_root).as_posix()
            for path in staging_root.rglob("*")
            if path.is_file() and not path.is_symlink() and path.name != "SHA256SUMS"
        }
        if set(package_sha256_entries) != package_regular_files:
            raise AssertionError("final SHA256SUMS is not exact package file closure")
        staging_root.replace(output_root)
        return receipt
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-package-root", type=pathlib.Path, required=True)
    parser.add_argument("--unstarted-candidates", type=pathlib.Path, required=True)
    parser.add_argument("--started-job-ids", type=pathlib.Path, required=True)
    parser.add_argument("--output-root", type=pathlib.Path, required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--expected-source-ready-sha256")
    parser.add_argument("--expected-unstarted-sha256")
    parser.add_argument("--expected-started-sha256")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    receipt = build_handoff(
        args.source_package_root,
        args.unstarted_candidates,
        args.started_job_ids,
        args.output_root,
        args.created_at,
        expected_source_ready_sha256=args.expected_source_ready_sha256,
        expected_unstarted_sha256=args.expected_unstarted_sha256,
        expected_started_sha256=args.expected_started_sha256,
    )
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "package_version": receipt["package_version"],
                "output_root": str(args.output_root.resolve()),
                "selected_candidates": receipt["counts"]["selected_candidates"],
                "selected_jobs": receipt["counts"]["selected_jobs"],
                "started_job_overlap": receipt["counts"]["started_job_overlap"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
