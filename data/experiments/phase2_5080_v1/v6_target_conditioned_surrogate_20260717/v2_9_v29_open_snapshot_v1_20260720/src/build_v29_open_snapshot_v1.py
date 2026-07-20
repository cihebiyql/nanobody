#!/usr/bin/env python3
"""Freeze a strict same-seed V29 open Docking teacher snapshot.

The builder intentionally emits labels only for ``train`` and ``development``.
``frozen_test`` is inspected only far enough to count successful same-seed dual
receptor pairs; no frozen candidate identifier, sequence, parent or score is
written to any output artifact.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "pvrig_v29_open_same_seed_snapshot_v1"
CLAIM_BOUNDARY = (
    "Active-campaign open computational Docking geometry snapshot only; not terminal teacher, "
    "binding, affinity, competition, experimental blocking, Docking Gold, or formal validation."
)
CONFORMATIONS = ("8x6b", "9e6y")
OPEN_SPLITS = ("train", "development")
ALL_SPLITS = (*OPEN_SPLITS, "frozen_test")
SUCCESS_STATES = {"SUCCESS", "PASS", "PASSED", "COMPLETE", "COMPLETED", "DONE"}
EXPECTED_FIXED_COMPONENT_SHA256 = {
    "scripts/common.py": "479cff3f2215f45952009d54869462cd90937cca56e15ddaf6af54a418f16d4a",
    "scripts/score_pose.py": "979f9c48ce0be744f9b1ab53b854d43b3444d576755a7b293c2c11553b30d6b9",
    "scripts/run_job.py": "9957e6dc80db2345737576d65606601064725c09b654518b1df76427e48a3d0a",
    "config/blocker_judgment_rules_v2.json": "60424c514d0e1c4f32bfec28631b969ed511c89babb4a73dcecf504e1e6a16a5",
    "inputs/normalized/8x6b_TL_reference.pdb": "80c9e36c63ba9fa8f28f606ad5864d9eb8c50b9b228424e1db5cdfc1bc6725b0",
    "inputs/normalized/9e6y_TL_reference.pdb": "01f13b5899624cb8c0450c458fbe055cae706804a78a0f7997940b787e6f2744",
    "inputs/normalized/8x6b_pvrig_receptor.pdb": "31b530edf01fe9b8f354935cc6140d863ba78faf50f93cf5303d0223c2a94e5a",
    "inputs/normalized/9e6y_pvrig_receptor.pdb": "c850363e92aa0ed00266b0f49ecea364bc661a768b2ac3ebe90cc8946b6f64c6",
    "inputs/normalized/interface_hotspots_uniprot.tsv": "dacb4f3fbf8aeaea17885ebfe0a548857a52f5ac863429e648af55ea196a7d44",
    "inputs/source/8X6B.pdb": "b9a930e44f61ee2ba35b4f8f739bc9431eb1944dad2e2344bd9c9a7ad13bb868",
    "inputs/source/9E6Y.pdb": "fb05ec77e439b8e1f43bfa12d7eb60f05f2c53e2099f06442f6c9ced32d98316",
    "inputs/source/PVRIG_hotspot_set_v1.csv": "9e5e82ad1f8193efbbb72865a632528c6b6a08d8a686c5b3e8ac74d2fd1564dd",
}
TEACHER_FIELDS = [
    "schema_version", "candidate_id", "sequence", "sequence_sha256", "cdr1", "cdr2", "cdr3",
    "parent_framework_cluster", "model_split", "source_campaign", "teacher_source",
    "teacher_reliability", "sample_weight", "docking_evidence_tier",
    "successful_seed_count_8X6B", "successful_seed_ids_8X6B",
    "successful_seed_count_9E6Y", "successful_seed_ids_9E6Y",
    "paired_successful_seed_count", "paired_successful_seed_ids", "R_8X6B", "R_9E6Y",
    "R_dual_min", "seed_dispersion_max", "teacher_uncertainty", "protocol_core_sha256",
    "ranking_release", "claim_boundary",
]
MANIFEST_FIELDS = [
    "schema_version", "job_id", "candidate_id", "model_split", "conformation", "seed",
    "sequence_sha256", "job_hash", "protocol_core_sha256", "status_sha256",
    "job_result_sha256", "fixed_top8_score", "claim_boundary",
]
SPLIT_MANIFEST_FIELDS = [
    "schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster",
    "model_split", "paired_successful_seed_count", "teacher_reliability", "claim_boundary",
]


class SnapshotError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SnapshotError(message)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(sequence.encode()).hexdigest()


def stable_read(path: Path) -> tuple[bytes, str]:
    before = path.stat()
    payload = path.read_bytes()
    after = path.stat()
    signature_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    signature_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    require(signature_before == signature_after, f"source_changed_during_read:{path}")
    return payload, sha256_bytes(payload)


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def parse_tsv_bytes(payload: bytes, label: str) -> tuple[list[str], list[dict[str, str]]]:
    text = payload.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    fields = list(reader.fieldnames or [])
    require(bool(fields), f"empty_header:{label}")
    return fields, [dict(row) for row in reader]


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    atomic_write(path, buffer.getvalue().encode())


def write_json(path: Path, payload: Any) -> None:
    atomic_write(path, (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())


def as_float(value: Any, field: str) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError) as error:
        raise SnapshotError(f"invalid_float:{field}") from error
    require(math.isfinite(output), f"nonfinite:{field}")
    return output


def soft(value: float, threshold: float) -> float:
    return value / (value + threshold)


def utility(score: Mapping[str, Any]) -> float:
    hotspot = as_float(score["hotspot_overlap"]["full"]["count"], "hotspot")
    holdout = as_float(score["hotspot_overlap"]["holdout"]["count"], "holdout")
    occlusion = score["vhh_pvrl2_occlusion"]
    total = as_float(occlusion["residue_pair_count"], "total")
    cdr3 = as_float(occlusion["by_vhh_region_pair_count"]["cdr3"], "cdr3")
    fraction = as_float(occlusion["cdr3_fraction"], "fraction")
    rmsd = as_float(score["overlay"]["t_ca_rmsd_a"], "rmsd")
    require(rmsd <= 1.0, f"native_overlay_rmsd_above_1A:{rmsd}")
    clashes = as_float(score["clashes_2p5a"]["vhh_pvrig"]["residue_pair_count"], "clashes")
    base = (
        0.15 * min(max(hotspot / 23, 0), 1)
        + 0.25 * min(max(holdout / 11, 0), 1)
        + 0.25 * soft(total, 500)
        + 0.20 * soft(cdr3, 100)
        + 0.15 * soft(fraction, 0.15)
    )
    return base / (1 + clashes / 5)


def geometry_class(score: Mapping[str, Any]) -> str:
    hotspot = float(score["hotspot_overlap"]["full"]["count"])
    occlusion = score["vhh_pvrl2_occlusion"]
    total = float(occlusion["residue_pair_count"])
    cdr3 = float(occlusion["by_vhh_region_pair_count"]["cdr3"])
    fraction = float(occlusion["cdr3_fraction"])
    if hotspot >= 14 and total >= 500 and cdr3 >= 100 and fraction >= 0.15:
        return "A"
    if hotspot >= 14 and total < 50:
        return "C"
    if hotspot >= 10 and total >= 100 and cdr3 >= 20 and fraction >= 0.10:
        return "B"
    return "E"


def summarize_job_fixed_top8(result: Mapping[str, Any], conformation: str) -> float:
    complete: list[tuple[float, str, dict[str, Mapping[str, Any]]]] = []
    for pose in result.get("pose_scores", []):
        scores = {str(item["reference_id"]).lower(): item for item in pose.get("scores", [])}
        if set(scores) == set(CONFORMATIONS):
            complete.append((as_float((pose.get("haddock_io") or {})["score"], "haddock_score"), str(pose.get("pose", "")), scores))
    require(len(complete) >= 4, "fewer_than_4_complete_top8_models")
    complete.sort(key=lambda item: (item[0], item[1]))
    complete = complete[:8]
    raw_weights = [1 / math.log2(rank + 1) for rank in range(1, len(complete) + 1)]
    weights = [value / sum(raw_weights) for value in raw_weights]
    score = sum(weight * utility(item[2][conformation]) for weight, item in zip(weights, complete))
    reliability = 0.5 + 0.5 * min(len(complete) / 8, 1)
    other = "9e6y" if conformation == "8x6b" else "8x6b"
    pairs = [(geometry_class(item[2][conformation]), geometry_class(item[2][other])) for item in complete]
    support = [(left in {"A", "B"}) == (right in {"A", "B"}) for left, right in pairs]
    labels = [
        "STRICT_A" if left == right == "A" else
        "SUPPORTED_AB" if left in {"A", "B"} and right in {"A", "B"} else
        "OTHER"
        for left, right in pairs
    ]
    agreement = sum(support) / len(support)
    consensus = max(labels.count(label) for label in set(labels)) / len(labels)
    return score * reliability * (0.5 + 0.25 * agreement + 0.25 * consensus)


def reliability_fields(seed_count: int) -> tuple[str, str]:
    if seed_count <= 1:
        return "DUAL_1_SEED", "0.65"
    if seed_count == 2:
        return "DUAL_2_SEED", "0.8"
    if seed_count == 3:
        return "DUAL_3_SEED", "1"
    return "DUAL_4PLUS_SEED", "1"


def validate_result(result: Mapping[str, Any], job: Mapping[str, str], protocol_core: str) -> None:
    job_id = job["job_id"]
    require(str(result.get("state", "")).upper() in SUCCESS_STATES, f"result_state_invalid:{job_id}")
    require(result.get("job_id") == job_id, f"result_job_id_mismatch:{job_id}")
    require(result.get("job_hash") == job["job_hash"], f"result_job_hash_mismatch:{job_id}")
    require(result.get("entity_id") == job["entity_id"], f"result_entity_mismatch:{job_id}")
    require(str(result.get("entity_type", "")).lower() == "candidate", f"result_entity_type_mismatch:{job_id}")
    require(str(result.get("dock_conformation", "")).lower() == job["conformation"], f"result_conformation_mismatch:{job_id}")
    require(int(result.get("seed")) == int(job["seed"]), f"result_seed_mismatch:{job_id}")
    require(result.get("protocol_core_sha256") == protocol_core, f"result_protocol_core_mismatch:{job_id}")


def component_audit(root: Path, strict: bool) -> dict[str, Any]:
    observed: dict[str, str] = {}
    for relative, expected in EXPECTED_FIXED_COMPONENT_SHA256.items():
        path = root / relative
        if not path.is_file():
            require(not strict, f"fixed_component_missing:{relative}")
            continue
        observed[relative] = sha256_file(path)
        require(observed[relative] == expected, f"fixed_component_sha_mismatch:{relative}")
    if strict:
        require(set(observed) == set(EXPECTED_FIXED_COMPONENT_SHA256), "fixed_component_set_incomplete")
    return {
        "status": "PASS_BYTE_IDENTICAL_TO_V4H_V4I_FIXED_SCORING_COMPONENTS" if strict else "NOT_REQUIRED_IN_UNIT_FIXTURE",
        "observed_sha256": observed,
        "expected_sha256": EXPECTED_FIXED_COMPONENT_SHA256 if strict else {},
    }


def build_snapshot(
    campaign_root: Path,
    output_dir: Path,
    *,
    strict_component_audit: bool = False,
    implementation_sha256: str = "",
    preregistration_sha256: str = "",
    test_sha256: str = "",
) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_exists:{output_dir}")
    candidates_path = campaign_root / "inputs" / "candidates_128.tsv"
    jobs_path = campaign_root / "manifests" / "docking_jobs.tsv"
    core_lock_path = campaign_root / "PROTOCOL_CORE_LOCK.json"
    final_lock_path = campaign_root / "PROTOCOL_LOCK.json"
    for path in (candidates_path, jobs_path, core_lock_path, final_lock_path):
        require(path.is_file(), f"source_missing:{path}")

    candidates_bytes, candidates_sha = stable_read(candidates_path)
    jobs_bytes, jobs_sha = stable_read(jobs_path)
    core_bytes, core_lock_sha = stable_read(core_lock_path)
    final_bytes, final_lock_sha = stable_read(final_lock_path)
    core_lock = json.loads(core_bytes)
    final_lock = json.loads(final_bytes)
    require(core_lock.get("status") == "CORE_LOCKED", "protocol_core_not_locked")
    require(final_lock.get("status") == "LOCKED", "protocol_not_locked")
    protocol_core = str(core_lock.get("protocol_core_sha256", ""))
    require(len(protocol_core) == 64, "protocol_core_sha_invalid")
    require(final_lock.get("protocol_core_sha256") == protocol_core, "protocol_lock_core_mismatch")

    candidate_fields, candidates = parse_tsv_bytes(candidates_bytes, "candidates")
    required_candidate = {
        "candidate_id", "sequence", "sequence_sha256", "cdr1", "cdr2", "cdr3",
        "parent_framework_cluster", "model_split",
    }
    require(required_candidate <= set(candidate_fields), "candidate_fields_missing")
    candidate_by_id: dict[str, dict[str, str]] = {}
    sequence_hashes: set[str] = set()
    split_counts: Counter[str] = Counter()
    for row in candidates:
        candidate_id = row["candidate_id"]
        require(bool(candidate_id) and candidate_id not in candidate_by_id, f"candidate_id_blank_or_duplicate:{candidate_id}")
        require(row["model_split"] in ALL_SPLITS, f"model_split_invalid:{candidate_id}:{row['model_split']}")
        require(bool(row["parent_framework_cluster"]), f"parent_framework_cluster_blank:{candidate_id}")
        require(sequence_sha256(row["sequence"]) == row["sequence_sha256"], f"sequence_sha256_mismatch:{candidate_id}")
        require(row["sequence_sha256"] not in sequence_hashes, f"sequence_sha256_duplicate:{row['sequence_sha256']}")
        sequence_hashes.add(row["sequence_sha256"])
        candidate_by_id[candidate_id] = row
        split_counts[row["model_split"]] += 1
    require(bool(candidate_by_id), "candidate_table_empty")

    job_fields, jobs = parse_tsv_bytes(jobs_bytes, "jobs")
    required_job = {
        "job_id", "entity_type", "entity_id", "conformation", "seed", "sequence_sha256",
        "protocol_core_sha256", "job_hash",
    }
    require(required_job <= set(job_fields), "job_fields_missing")
    candidate_jobs: list[dict[str, str]] = []
    job_ids: set[str] = set()
    for row in jobs:
        require(bool(row["job_id"]) and row["job_id"] not in job_ids, f"job_id_blank_or_duplicate:{row['job_id']}")
        job_ids.add(row["job_id"])
        if row["entity_type"].lower() != "candidate":
            continue
        require(row["entity_id"] in candidate_by_id, f"job_unknown_candidate:{row['job_id']}")
        candidate = candidate_by_id[row["entity_id"]]
        require(row["sequence_sha256"] == candidate["sequence_sha256"], f"job_sequence_sha_mismatch:{row['job_id']}")
        row["conformation"] = row["conformation"].lower()
        require(row["conformation"] in CONFORMATIONS, f"job_conformation_invalid:{row['job_id']}")
        require(row["protocol_core_sha256"] == protocol_core, f"job_protocol_core_mismatch:{row['job_id']}")
        int(row["seed"])
        candidate_jobs.append(row)

    compatibility = component_audit(campaign_root, strict_component_audit)
    # Freeze the result-directory set before reading any result payload.  This
    # prevents jobs that finish during the (potentially long) scoring pass from
    # entering the same snapshot merely because their manifest row was visited
    # later.  Result directories are immutable completion artifacts.
    result_root = campaign_root / "results"
    require(result_root.is_dir(), "results_directory_missing")
    result_set_frozen_at_utc = datetime.now(timezone.utc).isoformat()
    frozen_result_job_ids = {
        entry.name
        for entry in os.scandir(result_root)
        if entry.is_dir(follow_symlinks=False) and (Path(entry.path) / "job_result.json").is_file()
    }
    score_by_candidate: dict[str, dict[int, dict[str, tuple[float, dict[str, str]]]]] = defaultdict(lambda: defaultdict(dict))
    success_job_count = 0
    status_success_missing_result = 0
    open_scoring_invalid = 0
    frozen_success_keys: dict[str, set[tuple[int, str]]] = defaultdict(set)
    for job in candidate_jobs:
        if job["job_id"] not in frozen_result_job_ids:
            continue
        status_path = campaign_root / "status" / "jobs" / f"{job['job_id']}.json"
        if not status_path.is_file():
            continue
        status_bytes, status_sha = stable_read(status_path)
        status = json.loads(status_bytes)
        if str(status.get("status", "")).upper() != "SUCCESS":
            continue
        result_path = campaign_root / "results" / job["job_id"] / "job_result.json"
        if not result_path.is_file():
            status_success_missing_result += 1
            continue
        result_bytes, result_sha = stable_read(result_path)
        result = json.loads(result_bytes)
        validate_result(result, job, protocol_core)
        success_job_count += 1
        candidate = candidate_by_id[job["entity_id"]]
        seed = int(job["seed"])
        if candidate["model_split"] == "frozen_test":
            frozen_success_keys[job["entity_id"]].add((seed, job["conformation"]))
            continue
        try:
            score = summarize_job_fixed_top8(result, job["conformation"])
        except (KeyError, IndexError, TypeError, ValueError, SnapshotError):
            open_scoring_invalid += 1
            continue
        provenance = {
            "schema_version": SCHEMA_VERSION,
            "job_id": job["job_id"],
            "candidate_id": job["entity_id"],
            "model_split": candidate["model_split"],
            "conformation": job["conformation"],
            "seed": str(seed),
            "sequence_sha256": candidate["sequence_sha256"],
            "job_hash": job["job_hash"],
            "protocol_core_sha256": protocol_core,
            "status_sha256": status_sha,
            "job_result_sha256": result_sha,
            "fixed_top8_score": f"{score:.12g}",
            "claim_boundary": CLAIM_BOUNDARY,
        }
        score_by_candidate[job["entity_id"]][seed][job["conformation"]] = (score, provenance)

    teacher_by_split: dict[str, list[dict[str, Any]]] = {split: [] for split in OPEN_SPLITS}
    paired_manifest: list[dict[str, Any]] = []
    paired_counts: Counter[str] = Counter()
    tier_counts: Counter[str] = Counter()
    for candidate_id in sorted(score_by_candidate):
        candidate = candidate_by_id[candidate_id]
        paired_seeds = sorted(seed for seed, by_conf in score_by_candidate[candidate_id].items() if set(by_conf) == set(CONFORMATIONS))
        if not paired_seeds:
            continue
        split = candidate["model_split"]
        require(split in OPEN_SPLITS, f"internal_frozen_label_exposure:{candidate_id}")
        values = {
            conformation: [score_by_candidate[candidate_id][seed][conformation][0] for seed in paired_seeds]
            for conformation in CONFORMATIONS
        }
        medians = {conformation: statistics.median(items) for conformation, items in values.items()}
        rdual = min(medians.values())
        dispersion = max((statistics.pstdev(items) if len(items) >= 2 else 0.0 for items in values.values()))
        tier, weight = reliability_fields(len(paired_seeds))
        teacher_by_split[split].append(
            {
                "schema_version": SCHEMA_VERSION,
                "candidate_id": candidate_id,
                "sequence": candidate["sequence"],
                "sequence_sha256": candidate["sequence_sha256"],
                "cdr1": candidate["cdr1"],
                "cdr2": candidate["cdr2"],
                "cdr3": candidate["cdr3"],
                "parent_framework_cluster": candidate["parent_framework_cluster"],
                "model_split": split,
                "source_campaign": "V29",
                "teacher_source": "V29_ACTIVE_OPEN_SAME_SEED_SNAPSHOT",
                "teacher_reliability": tier,
                "sample_weight": weight,
                "docking_evidence_tier": tier,
                "successful_seed_count_8X6B": str(len(paired_seeds)),
                "successful_seed_ids_8X6B": ",".join(map(str, paired_seeds)),
                "successful_seed_count_9E6Y": str(len(paired_seeds)),
                "successful_seed_ids_9E6Y": ",".join(map(str, paired_seeds)),
                "paired_successful_seed_count": str(len(paired_seeds)),
                "paired_successful_seed_ids": ",".join(map(str, paired_seeds)),
                "R_8X6B": f"{medians['8x6b']:.12g}",
                "R_9E6Y": f"{medians['9e6y']:.12g}",
                "R_dual_min": f"{rdual:.12g}",
                "seed_dispersion_max": f"{dispersion:.12g}",
                "teacher_uncertainty": f"{dispersion:.12g}",
                "protocol_core_sha256": protocol_core,
                "ranking_release": "v29_active_open_same_seed_snapshot_v1",
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )
        for seed in paired_seeds:
            for conformation in CONFORMATIONS:
                paired_manifest.append(score_by_candidate[candidate_id][seed][conformation][1])
        paired_counts[split] += 1
        tier_counts[tier] += 1

    frozen_paired_count = 0
    frozen_tier_counts: Counter[str] = Counter()
    for success_keys in frozen_success_keys.values():
        paired_seeds = {seed for seed, conformation in success_keys if (seed, "8x6b") in success_keys and (seed, "9e6y") in success_keys}
        if paired_seeds:
            frozen_paired_count += 1
            frozen_tier_counts[reliability_fields(len(paired_seeds))[0]] += 1
    paired_counts["frozen_test"] = frozen_paired_count

    output_dir.mkdir(parents=True)
    train_path = output_dir / "v29_open_train.tsv"
    development_path = output_dir / "v29_open_development.tsv"
    combined_path = output_dir / "v29_open_train_development.tsv"
    manifest_path = output_dir / "v29_open_paired_job_manifest.tsv"
    split_manifest_path = output_dir / "v29_open_candidate_split_manifest.tsv"
    frozen_path = output_dir / "V29_FROZEN_TEST_COUNT_ONLY.json"
    readme_path = output_dir / "README_ZH.md"
    receipt_path = output_dir / "V29_OPEN_SNAPSHOT_RECEIPT.json"
    sums_path = output_dir / "SHA256SUMS"

    write_tsv(train_path, teacher_by_split["train"], TEACHER_FIELDS)
    write_tsv(development_path, teacher_by_split["development"], TEACHER_FIELDS)
    combined = sorted(teacher_by_split["train"] + teacher_by_split["development"], key=lambda row: (row["model_split"], row["candidate_id"]))
    write_tsv(combined_path, combined, TEACHER_FIELDS)
    write_tsv(manifest_path, sorted(paired_manifest, key=lambda row: row["job_id"]), MANIFEST_FIELDS)
    split_manifest_rows = [
        {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": row["candidate_id"],
            "sequence_sha256": row["sequence_sha256"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "model_split": row["model_split"],
            "paired_successful_seed_count": row["paired_successful_seed_count"],
            "teacher_reliability": row["teacher_reliability"],
            "claim_boundary": CLAIM_BOUNDARY,
        }
        for row in combined
    ]
    write_tsv(split_manifest_path, split_manifest_rows, SPLIT_MANIFEST_FIELDS)
    frozen_count_only = {
        "schema_version": "pvrig_v29_frozen_test_count_only_v1",
        "model_split": "frozen_test",
        "candidate_count": split_counts["frozen_test"],
        "strict_paired_candidate_count": frozen_paired_count,
        "paired_seed_tier_counts": dict(sorted(frozen_tier_counts.items())),
        "labels_emitted": 0,
        "candidate_identifiers_emitted": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json(frozen_path, frozen_count_only)
    readme = f"""# V29 active open same-seed snapshot\n\n- train labels: {len(teacher_by_split['train'])}\n- development labels: {len(teacher_by_split['development'])}\n- frozen_test: count only, {frozen_paired_count} strict paired candidates; no identifiers or labels emitted\n- inclusion: the same seed must succeed for independent 8X6B and 9E6Y jobs\n- aggregation: receptor median over paired seeds; `R_dual_min = min(R_8X6B, R_9E6Y)`\n- source campaign is active; this is not a terminal teacher\n- boundary: {CLAIM_BOUNDARY}\n"""
    atomic_write(readme_path, readme.encode())

    source_hashes_after = {
        "candidates_128.tsv": sha256_file(candidates_path),
        "docking_jobs.tsv": sha256_file(jobs_path),
        "PROTOCOL_CORE_LOCK.json": sha256_file(core_lock_path),
        "PROTOCOL_LOCK.json": sha256_file(final_lock_path),
    }
    source_hashes_before = {
        "candidates_128.tsv": candidates_sha,
        "docking_jobs.tsv": jobs_sha,
        "PROTOCOL_CORE_LOCK.json": core_lock_sha,
        "PROTOCOL_LOCK.json": final_lock_sha,
    }
    require(source_hashes_before == source_hashes_after, "frozen_source_manifest_changed_during_snapshot")
    nonreceipt_outputs = [
        train_path, development_path, combined_path, manifest_path, split_manifest_path,
        frozen_path, readme_path,
    ]
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_V29_ACTIVE_OPEN_SAME_SEED_SNAPSHOT",
        "campaign_terminal": False,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "result_set_frozen_at_utc": result_set_frozen_at_utc,
        "source_campaign_root": str(campaign_root),
        "source_campaign": "V29",
        "protocol_core_sha256": protocol_core,
        "source_sha256": source_hashes_before,
        "implementation_sha256": implementation_sha256,
        "preregistration_sha256": preregistration_sha256,
        "test_sha256": test_sha256,
        "component_compatibility": compatibility,
        "counts": {
            "candidate_rows": len(candidates),
            "candidate_split_rows": dict(sorted(split_counts.items())),
            "candidate_job_rows": len(candidate_jobs),
            "result_directories_frozen_at_selection": len(frozen_result_job_ids),
            "success_jobs_validated": success_job_count,
            "status_success_missing_result": status_success_missing_result,
            "open_scoring_invalid_jobs": open_scoring_invalid,
            "strict_paired_candidates": {split: paired_counts[split] for split in ALL_SPLITS},
            "open_output_rows": len(combined),
            "open_paired_job_manifest_rows": len(paired_manifest),
            "open_teacher_tier_counts": dict(sorted(tier_counts.items())),
        },
        "invariants": {
            "same_seed_dual_receptor_required": True,
            "candidate_is_statistical_unit": True,
            "R_dual_exact_min": all(abs(float(row["R_dual_min"]) - min(float(row["R_8X6B"]), float(row["R_9E6Y"]))) <= 1e-12 for row in combined),
            "frozen_test_label_rows_emitted": 0,
            "frozen_test_identifiers_emitted": 0,
            "D0_rows_sharing_any_V29_frozen_test_parent_must_be_excluded_from_fit": True,
            "V29_frozen_parent_identifiers_are_not_emitted_by_this_snapshot": True,
            "technical_failures_imputed": False,
            "campaign_terminal": False,
        },
        "output_sha256": {path.name: sha256_file(path) for path in nonreceipt_outputs},
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json(receipt_path, receipt)
    sum_paths = [*nonreceipt_outputs, receipt_path]
    sums = "".join(f"{sha256_file(path)}  {path.name}\n" for path in sorted(sum_paths, key=lambda item: item.name))
    atomic_write(sums_path, sums.encode())
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--strict-component-audit", action="store_true")
    parser.add_argument("--implementation-sha256", default="")
    parser.add_argument("--preregistration-sha256", default="")
    parser.add_argument("--test-sha256", default="")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = build_snapshot(
        args.campaign_root,
        args.output_dir,
        strict_component_audit=args.strict_component_audit,
        implementation_sha256=args.implementation_sha256,
        preregistration_sha256=args.preregistration_sha256,
        test_sha256=args.test_sha256,
    )
    if not args.quiet:
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
