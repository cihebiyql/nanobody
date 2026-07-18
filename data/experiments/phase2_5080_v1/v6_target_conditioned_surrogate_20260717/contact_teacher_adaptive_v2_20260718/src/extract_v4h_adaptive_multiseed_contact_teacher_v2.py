#!/usr/bin/env python3
"""Extract a V4-H adaptive multi-seed contact teacher from paired dual-receptor seeds.

The frozen Stage-1 extractor remains unchanged.  This version imports its PDB
parser and pose-selection helpers, aggregates poses within a job first, and then
aggregates only the successful seed intersection shared by 8X6B and 9E6Y.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import io
import json
import math
import os
import stat
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

SCHEMA_VERSION = "pvrig_v6_v4h_adaptive_multiseed_contact_teacher_v2"
CLAIM_BOUNDARY = (
    "V4-H adaptive-seed computational residue-contact intermediates derived from "
    "frozen independent 8X6B/9E6Y docking poses; not binding, affinity, competition, "
    "experimental blocking, Docking Gold, or final submission evidence."
)
RECEPTORS = ("8x6b", "9e6y")
EXPECTED_SEEDS = (917, 1931, 3253)
CONTACT_CUTOFF = 4.5
TOP_K = 8
MINIMUM_POSES = 4
TIER_TO_COUNT = {"DUAL_1_SEED": 1, "DUAL_2_SEED": 2, "DUAL_3_SEED": 3}
TIER_TO_RELIABILITY = {"DUAL_1_SEED": "C", "DUAL_2_SEED": "B", "DUAL_3_SEED": "A"}
INCOMPLETE_TIER = "TECHNICAL_INCOMPLETE"
INCOMPLETE_STATE = "TECHNICAL_INCOMPLETE_NA"
BASE_EXTRACTOR_SHA256 = "baa82f9291d096b8d59ba222432fbfb7e4c20aba34040bbae91d19a0eec79022"

PAIR_OUTPUT = "v4h_adaptive_residue_pair_contact_teacher.tsv.gz"
RESIDUE_OUTPUT = "v4h_adaptive_vhh_residue_marginal_teacher.tsv.gz"
RECEPTOR_OUTPUT = "v4h_adaptive_receptor_state.tsv.gz"
CANDIDATE_OUTPUT = "v4h_adaptive_candidate_state.tsv.gz"
JOB_OUTPUT = "v4h_adaptive_selected_job_inventory.tsv.gz"
AUDIT_OUTPUT = "v4h_adaptive_contact_extraction_audit.json"
RECEIPT_OUTPUT = "RUN_RECEIPT.json"

MANIFEST_PATHS = {
    917: "manifests/stage1_all_seed917.tsv",
    1931: "manifests/stage2_selected_seed1931.tsv",
    3253: "manifests/stage3_selected_seed3253.tsv",
}
RANKING_PATH = "release/final_adaptive_seed_ranking.tsv"
UPSTREAM_RECEIPT_PATH = "release/ADAPTIVE_DOCKING_RECEIPT.json"
CANDIDATES_PATH = "inputs/candidates_290.tsv"
BASE_EXTRACTOR_RELATIVE = "../../contact_teacher/src/extract_v4h_stage1_contact_teacher_v1_1.py"

PAIR_FIELDS = [
    "schema_version", "teacher_state", "candidate_id", "sequence_sha256",
    "parent_framework_cluster", "development_reliability_tier", "receptor",
    "observed_seed_count", "observed_seed_ids", "vhh_sequence_index", "vhh_aa",
    "vhh_region", "pvrig_uniprot_position", "pvrig_aa", "contact_target_mean",
    "contact_target_variance", "contact_target_std", "contact_uncertainty_weight",
    "supporting_seed_count", "seed_contact_values", "claim_boundary",
]
RESIDUE_FIELDS = [
    "schema_version", "teacher_state", "candidate_id", "sequence_sha256",
    "parent_framework_cluster", "development_reliability_tier", "receptor",
    "observed_seed_count", "observed_seed_ids", "vhh_sequence_index", "vhh_aa",
    "vhh_region", "contact_marginal_mean", "contact_marginal_variance",
    "contact_marginal_std", "contact_marginal_uncertainty_weight",
    "supporting_seed_count", "seed_marginal_values", "claim_boundary",
]
RECEPTOR_NUMERIC_FIELDS = [
    "observed_seed_count", "excluded_unpaired_seed_count", "selected_pose_count_total",
    "pair_contact_mass_seed_mean", "pair_contact_mass_seed_variance",
    "residue_marginal_mass_seed_mean", "residue_marginal_mass_seed_variance",
    "haddock_score_seed_mean", "haddock_score_seed_variance",
]
RECEPTOR_FIELDS = [
    "schema_version", "teacher_state", "candidate_id", "sequence_sha256",
    "parent_framework_cluster", "target_patch_id", "design_mode",
    "development_reliability_tier", "docking_evidence_tier", "receptor",
    "observed_seed_ids", "declared_successful_seed_ids", "excluded_unpaired_seed_ids",
    "technical_reasons", *RECEPTOR_NUMERIC_FIELDS, "claim_boundary",
]
RANKING_NUMERIC_FIELDS = [
    "median_score_8X6B", "median_score_9E6Y", "R_dual_min", "seed_dispersion_max",
    "confidence_adjusted_score", "rank",
]
CANDIDATE_FIELDS = [
    "schema_version", "teacher_state", "candidate_id", "sequence_sha256",
    "parent_framework_cluster", "target_patch_id", "design_mode",
    "development_reliability_tier", "docking_evidence_tier", "paired_seed_ids",
    "receptor_seed_set_asymmetric", "technical_reasons", "paired_seed_count",
    *RANKING_NUMERIC_FIELDS, "claim_boundary",
]
JOB_FIELDS = [
    "schema_version", "candidate_id", "sequence_sha256", "receptor", "seed",
    "job_id", "job_hash", "job_result_sha256", "selected_pose_count",
    "selected_pose_score_min", "selected_pose_score_mean", "selected_pose_score_max",
    "claim_boundary",
]


class AdaptiveContactError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AdaptiveContactError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise AdaptiveContactError(f"missing_file:{label}:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"not_regular_or_symlink:{label}:{path}")


def load_json(path: Path, label: str) -> dict[str, Any]:
    require_regular_file(path, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AdaptiveContactError(f"invalid_json:{label}:{path}") from exc
    require(isinstance(payload, dict), f"json_not_object:{label}:{path}")
    return payload


def load_tsv(path: Path, label: str) -> tuple[list[str], list[dict[str, str]]]:
    require_regular_file(path, label)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    require(bool(fields), f"missing_tsv_header:{label}")
    return fields, rows


def canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_gzip_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="", write_through=True) as text:
                writer = csv.DictWriter(text, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow({field: row.get(field, "") for field in fields})
        raw.flush(); os.fsync(raw.fileno())
    os.replace(temporary, path)


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def load_base_extractor() -> Any:
    path = (Path(__file__).resolve().parent / BASE_EXTRACTOR_RELATIVE).resolve()
    require_regular_file(path, "base_stage1_extractor")
    require(sha256_file(path) == BASE_EXTRACTOR_SHA256, "base_stage1_extractor_sha256")
    name = "_pvrig_v4h_stage1_contact_teacher_frozen_v1_1"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "base_stage1_extractor_import_spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def parse_seed_ids(value: str) -> set[int]:
    if not value.strip():
        return set()
    try:
        seeds = {int(part) for part in value.split(",") if part.strip()}
    except ValueError as exc:
        raise AdaptiveContactError(f"invalid_seed_ids:{value}") from exc
    require(seeds <= set(EXPECTED_SEEDS), f"unexpected_seed_ids:{value}")
    return seeds


def population_variance(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def uncertainty_weight(variance: float) -> float:
    require(math.isfinite(variance) and variance >= 0.0, "invalid_variance")
    return 1.0 / (1.0 + 4.0 * variance)


def fmt(value: float) -> str:
    require(math.isfinite(value), "nonfinite_output")
    return f"{value:.9f}"


def teacher_state(tier: str) -> str:
    return f"VALID_{tier}_CONTACT"


def validate_contract(contract: Mapping[str, Any], root: Path, reconciliation: Mapping[str, Any]) -> None:
    require(contract.get("schema_version") == f"{SCHEMA_VERSION}_contract", "contract_schema")
    require(contract.get("status") == "FROZEN_PRE_EXTRACTION", "contract_not_frozen")
    require(Path(str(contract.get("canonical_raw_root"))).resolve() == root, "canonical_raw_root")
    implementation = contract.get("implementation") or {}
    require(implementation.get("adaptive_extractor_sha256") == sha256_file(Path(__file__)), "adaptive_extractor_sha256")
    require(implementation.get("base_stage1_extractor_sha256") == BASE_EXTRACTOR_SHA256, "contract_base_extractor_sha256")
    definition = contract.get("contact_definition") or {}
    require(float(definition.get("contact_cutoff_angstrom")) == CONTACT_CUTOFF, "contact_cutoff_changed")
    require(int(definition.get("top_k")) == TOP_K, "top_k_changed")
    require(int(definition.get("minimum_poses")) == MINIMUM_POSES, "minimum_poses_changed")
    require(tuple(definition.get("receptors") or []) == RECEPTORS, "receptors_changed")
    require(tuple(int(v) for v in definition.get("available_seeds") or []) == EXPECTED_SEEDS, "seeds_changed")
    aggregation = contract.get("aggregation") or {}
    require(aggregation.get("dual_seed_scope") == "intersection_of_ranking_declared_successful_seed_ids", "seed_scope_changed")
    require(aggregation.get("pose_rank_weight") == "normalized_1_over_log2_rank_plus_1", "pose_weight_changed")
    require(aggregation.get("seed_weighting") == "equal_over_paired_successful_seeds", "seed_weight_changed")
    require(aggregation.get("absent_union_pair") == "observed_zero_within_successful_paired_seed", "absent_pair_changed")
    require(aggregation.get("pair_variance") == "population", "variance_changed")
    require(aggregation.get("uncertainty_weight") == "1/(1+4*variance)", "uncertainty_changed")
    require(aggregation.get("residue_marginal") == "pose_weighted_any_pvrig_contact_then_equal_seed_mean", "marginal_changed")
    require(reconciliation.get("status") == "PASS_RECONCILED_V4H_ADAPTIVE_TERMINAL_CLOSURE", "reconciliation_not_pass")
    expected_reconciliation = str((contract.get("expected_sha256") or {}).get("reconciliation_receipt", ""))
    require(expected_reconciliation, "reconciliation_hash_missing")


def validate_inputs(root: Path, contract_path: Path, reconciliation_path: Path) -> dict[str, Any]:
    root = root.resolve(); contract_path = contract_path.resolve(); reconciliation_path = reconciliation_path.resolve()
    require(root.is_dir() and not root.is_symlink(), f"campaign_root_missing_or_symlink:{root}")
    contract = load_json(contract_path, "contract")
    reconciliation = load_json(reconciliation_path, "reconciliation_receipt")
    validate_contract(contract, root, reconciliation)
    expected_hashes = dict(contract.get("expected_sha256") or {})
    require(sha256_file(reconciliation_path) == expected_hashes["reconciliation_receipt"], "reconciliation_receipt_sha256")
    paths = {
        "raw_candidates": root / CANDIDATES_PATH,
        "final_ranking": root / RANKING_PATH,
        "upstream_receipt": root / UPSTREAM_RECEIPT_PATH,
        **{f"manifest_seed{seed}": root / rel for seed, rel in MANIFEST_PATHS.items()},
    }
    observed_hashes = {name: sha256_file(path) for name, path in paths.items()}
    for name, observed in observed_hashes.items():
        require(expected_hashes.get(name) == observed, f"input_sha256:{name}")
    require((reconciliation.get("actual_files") or {}).get(RANKING_PATH, {}).get("sha256") == observed_hashes["final_ranking"], "reconciliation_final_hash")
    require((reconciliation.get("upstream_receipt") or {}).get("sha256") == observed_hashes["upstream_receipt"], "reconciliation_upstream_hash")

    _candidate_fields, candidate_rows = load_tsv(paths["raw_candidates"], "candidates")
    _ranking_fields, ranking_rows = load_tsv(paths["final_ranking"], "final_ranking")
    candidates = {row["candidate_id"]: row for row in candidate_rows}
    rankings = {row["candidate_id"]: row for row in ranking_rows}
    require(len(candidates) == len(candidate_rows), "candidate_id_duplicate")
    require(len(rankings) == len(ranking_rows), "ranking_id_duplicate")
    require(set(candidates) == set(rankings), "candidate_ranking_closure")
    expected_counts = dict(contract.get("expected_counts") or {})
    require(len(candidates) == int(expected_counts["candidates"]), "candidate_count")
    for candidate_id, candidate in candidates.items():
        digest = hashlib.sha256(candidate["sequence"].encode("ascii")).hexdigest()
        require(digest == candidate["sequence_sha256"], f"candidate_sequence_sha256:{candidate_id}")
        ranking = rankings[candidate_id]
        require(ranking["sequence_sha256"] == digest, f"ranking_sequence_sha256:{candidate_id}")
        require(ranking["parent_framework_cluster"] == candidate["parent_framework_cluster"], f"ranking_parent:{candidate_id}")

    tier_counts = Counter(row["docking_evidence_tier"] for row in ranking_rows)
    require(dict(tier_counts) == dict(expected_counts["tier_counts"]), f"tier_counts:{dict(tier_counts)}")
    valid_ids = {row["candidate_id"] for row in ranking_rows if row["docking_evidence_tier"] in TIER_TO_COUNT}
    incomplete_ids = set(candidates) - valid_ids
    selected_seeds: dict[str, tuple[int, ...]] = {}
    declared_seeds: dict[tuple[str, str], tuple[int, ...]] = {}
    asymmetric_valid = set()
    for candidate_id, ranking in rankings.items():
        left = parse_seed_ids(ranking["successful_seed_ids_8X6B"])
        right = parse_seed_ids(ranking["successful_seed_ids_9E6Y"])
        require(int(ranking["successful_seed_count_8X6B"]) == len(left), f"declared_8x6b_seed_count:{candidate_id}")
        require(int(ranking["successful_seed_count_9E6Y"]) == len(right), f"declared_9e6y_seed_count:{candidate_id}")
        declared_seeds[(candidate_id, "8x6b")] = tuple(sorted(left))
        declared_seeds[(candidate_id, "9e6y")] = tuple(sorted(right))
        common = tuple(sorted(left & right))
        tier = ranking["docking_evidence_tier"]
        if tier in TIER_TO_COUNT:
            require(len(common) == TIER_TO_COUNT[tier], f"paired_seed_count:{candidate_id}")
            require(common == EXPECTED_SEEDS[:len(common)], f"paired_seed_order:{candidate_id}:{common}")
            selected_seeds[candidate_id] = common
            for field in RANKING_NUMERIC_FIELDS:
                try:
                    value = float(ranking[field])
                except ValueError as exc:
                    raise AdaptiveContactError(f"ranking_numeric_invalid:{candidate_id}:{field}") from exc
                require(math.isfinite(value), f"ranking_numeric_nonfinite:{candidate_id}:{field}")
            if left != right:
                asymmetric_valid.add(candidate_id)
        else:
            require(tier == INCOMPLETE_TIER, f"unknown_tier:{candidate_id}:{tier}")
            selected_seeds[candidate_id] = ()

    jobs_by_key: dict[tuple[str, str, int], dict[str, str]] = {}
    manifest_rows: dict[int, list[dict[str, str]]] = {}
    for seed, path in ((seed, paths[f"manifest_seed{seed}"]) for seed in EXPECTED_SEEDS):
        _fields, rows = load_tsv(path, f"manifest_seed{seed}")
        manifest_rows[seed] = rows
        require(len(rows) == int(expected_counts["manifest_rows"][str(seed)]), f"manifest_count:{seed}")
        for job in rows:
            require(job["entity_type"] == "candidate", f"non_candidate_job:{job['job_id']}")
            require(int(job["seed"]) == seed, f"manifest_seed:{job['job_id']}")
            require(job["conformation"] in RECEPTORS, f"manifest_receptor:{job['job_id']}")
            require(job["entity_id"] in candidates, f"manifest_candidate:{job['job_id']}")
            require(job["sequence_sha256"] == candidates[job["entity_id"]]["sequence_sha256"], f"job_sequence_sha256:{job['job_id']}")
            key = (job["entity_id"], job["conformation"], seed)
            require(key not in jobs_by_key, f"duplicate_job_key:{key}")
            jobs_by_key[key] = job

    selected_jobs = []
    for candidate_id in sorted(valid_ids):
        for seed in selected_seeds[candidate_id]:
            for receptor in RECEPTORS:
                key = (candidate_id, receptor, seed)
                require(key in jobs_by_key, f"selected_job_missing_manifest:{key}")
                selected_jobs.append(jobs_by_key[key])
    require(len(selected_jobs) == int(expected_counts["selected_paired_jobs"]), "selected_job_count")
    require(len(asymmetric_valid) == int(expected_counts["valid_receptor_seed_asymmetry_candidates"]), "asymmetry_count")
    return {
        "root": root, "contract": contract, "contract_path": contract_path,
        "reconciliation": reconciliation, "reconciliation_path": reconciliation_path,
        "observed_hashes": observed_hashes, "candidates": candidates, "rankings": rankings,
        "valid_ids": valid_ids, "incomplete_ids": incomplete_ids, "selected_seeds": selected_seeds,
        "declared_seeds": declared_seeds, "asymmetric_valid": asymmetric_valid,
        "jobs_by_key": jobs_by_key, "selected_jobs": sorted(selected_jobs, key=lambda row: row["job_id"]),
        "tier_counts": tier_counts,
    }


def validate_job_metadata(root: Path, job: Mapping[str, str], candidate: Mapping[str, str]) -> tuple[dict[str, Any], list[tuple[float, str, Path]], str]:
    base = load_base_extractor()
    result_path = root / "results" / job["job_id"] / "job_result.json"
    payload = load_json(result_path, "job_result")
    require(payload.get("state") == "SUCCESS", f"job_not_success:{job['job_id']}")
    require(payload.get("job_id") == job["job_id"], f"job_id_mismatch:{job['job_id']}")
    require(payload.get("job_hash") == job["job_hash"], f"job_hash_mismatch:{job['job_id']}")
    require(payload.get("entity_id") == candidate["candidate_id"], f"job_candidate_mismatch:{job['job_id']}")
    require(str(payload.get("dock_conformation")) == job["conformation"], f"job_receptor_mismatch:{job['job_id']}")
    require(int(payload.get("seed")) == int(job["seed"]), f"job_seed_mismatch:{job['job_id']}")
    selected = base.ranked_poses(root, payload, job["job_id"])
    return payload, selected, sha256_file(result_path)


def process_seed_job(task: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(str(task["root"])); job = dict(task["job"]); candidate = dict(task["candidate"])
    base = load_base_extractor()
    _payload, selected, result_sha = validate_job_metadata(root, job, candidate)
    raw_weights = np.asarray([1.0 / math.log2(rank + 1.0) for rank in range(1, len(selected) + 1)], dtype=np.float64)
    weights = raw_weights / raw_weights.sum()
    pair_values: defaultdict[tuple[int, int], float] = defaultdict(float)
    marginal_values: defaultdict[int, float] = defaultdict(float)
    target_names: dict[int, str] = {}
    for weight, (_score, _name, pose_path) in zip(weights, selected):
        pairs, names = base.contact_pairs_from_pose(
            pose_path, candidate["sequence"], job["vhh_chain"], job["receptor_chain"], CONTACT_CUTOFF
        )
        for pair in pairs:
            pair_values[pair] += float(weight)
        for index in {pair[0] for pair in pairs}:
            marginal_values[index] += float(weight)
        for position, name in names.items():
            previous = target_names.setdefault(int(position), str(name))
            require(previous == name, f"target_identity_conflict:{job['job_id']}:{position}")
    scores = [float(item[0]) for item in selected]
    return {
        "candidate_id": candidate["candidate_id"], "receptor": job["conformation"],
        "seed": int(job["seed"]), "job_id": job["job_id"], "job_hash": job["job_hash"],
        "job_result_sha256": result_sha, "pose_count": len(selected), "pose_scores": scores,
        "pair_values": dict(pair_values), "marginal_values": dict(marginal_values),
        "target_names": target_names,
    }


def aggregate_candidate_receptor(
    candidate: Mapping[str, str], ranking: Mapping[str, str], receptor: str,
    paired_seeds: Sequence[int], declared: Sequence[int], seed_results: Sequence[Mapping[str, Any]],
    ranges: Mapping[str, set[int]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    base = load_base_extractor()
    by_seed = {int(result["seed"]): result for result in seed_results}
    require(tuple(sorted(by_seed)) == tuple(paired_seeds), f"aggregate_seed_closure:{candidate['candidate_id']}:{receptor}")
    state = teacher_state(ranking["docking_evidence_tier"])
    reliability = TIER_TO_RELIABILITY[ranking["docking_evidence_tier"]]
    seed_text = ",".join(map(str, paired_seeds))
    target_names: dict[int, str] = {}
    for result in seed_results:
        for position, name in result["target_names"].items():
            previous = target_names.setdefault(int(position), str(name))
            require(previous == name, f"target_identity_across_seeds:{candidate['candidate_id']}:{receptor}:{position}")
    pair_keys = sorted({pair for result in seed_results for pair in result["pair_values"]})
    pair_rows = []
    for vhh_index, pvrig_position in pair_keys:
        values = [float(by_seed[seed]["pair_values"].get((vhh_index, pvrig_position), 0.0)) for seed in paired_seeds]
        mean = sum(values) / len(values); variance = population_variance(values)
        require(mean > 0.0, "union_pair_zero_mean")
        pair_rows.append({
            "schema_version": SCHEMA_VERSION, "teacher_state": state,
            "candidate_id": candidate["candidate_id"], "sequence_sha256": candidate["sequence_sha256"],
            "parent_framework_cluster": candidate["parent_framework_cluster"],
            "development_reliability_tier": reliability, "receptor": receptor,
            "observed_seed_count": len(paired_seeds), "observed_seed_ids": seed_text,
            "vhh_sequence_index": vhh_index, "vhh_aa": candidate["sequence"][vhh_index - 1],
            "vhh_region": base.region_for(vhh_index, ranges), "pvrig_uniprot_position": pvrig_position,
            "pvrig_aa": base.AA3_TO_1[target_names[pvrig_position]], "contact_target_mean": fmt(mean),
            "contact_target_variance": fmt(variance), "contact_target_std": fmt(math.sqrt(variance)),
            "contact_uncertainty_weight": fmt(uncertainty_weight(variance)),
            "supporting_seed_count": sum(value > 0 for value in values),
            "seed_contact_values": ";".join(f"{seed}:{fmt(value)}" for seed, value in zip(paired_seeds, values)),
            "claim_boundary": CLAIM_BOUNDARY,
        })
    residue_rows = []
    for index, aa in enumerate(candidate["sequence"], start=1):
        values = [float(by_seed[seed]["marginal_values"].get(index, 0.0)) for seed in paired_seeds]
        mean = sum(values) / len(values); variance = population_variance(values)
        residue_rows.append({
            "schema_version": SCHEMA_VERSION, "teacher_state": state,
            "candidate_id": candidate["candidate_id"], "sequence_sha256": candidate["sequence_sha256"],
            "parent_framework_cluster": candidate["parent_framework_cluster"],
            "development_reliability_tier": reliability, "receptor": receptor,
            "observed_seed_count": len(paired_seeds), "observed_seed_ids": seed_text,
            "vhh_sequence_index": index, "vhh_aa": aa, "vhh_region": base.region_for(index, ranges),
            "contact_marginal_mean": fmt(mean), "contact_marginal_variance": fmt(variance),
            "contact_marginal_std": fmt(math.sqrt(variance)),
            "contact_marginal_uncertainty_weight": fmt(uncertainty_weight(variance)),
            "supporting_seed_count": sum(value > 0 for value in values),
            "seed_marginal_values": ";".join(f"{seed}:{fmt(value)}" for seed, value in zip(paired_seeds, values)),
            "claim_boundary": CLAIM_BOUNDARY,
        })
    pair_mass = [sum(float(v) for v in by_seed[seed]["pair_values"].values()) for seed in paired_seeds]
    marginal_mass = [sum(float(v) for v in by_seed[seed]["marginal_values"].values()) for seed in paired_seeds]
    score_means = [sum(by_seed[seed]["pose_scores"]) / len(by_seed[seed]["pose_scores"]) for seed in paired_seeds]
    excluded = sorted(set(declared) - set(paired_seeds))
    receptor_row = {
        "schema_version": SCHEMA_VERSION, "teacher_state": state,
        "candidate_id": candidate["candidate_id"], "sequence_sha256": candidate["sequence_sha256"],
        "parent_framework_cluster": candidate["parent_framework_cluster"],
        "target_patch_id": ranking["target_patch_id"], "design_mode": ranking["design_mode"],
        "development_reliability_tier": reliability, "docking_evidence_tier": ranking["docking_evidence_tier"],
        "receptor": receptor, "observed_seed_ids": seed_text,
        "declared_successful_seed_ids": ",".join(map(str, declared)),
        "excluded_unpaired_seed_ids": ",".join(map(str, excluded)), "technical_reasons": ranking["technical_reasons"],
        "observed_seed_count": len(paired_seeds), "excluded_unpaired_seed_count": len(excluded),
        "selected_pose_count_total": sum(int(by_seed[seed]["pose_count"]) for seed in paired_seeds),
        "pair_contact_mass_seed_mean": fmt(sum(pair_mass) / len(pair_mass)),
        "pair_contact_mass_seed_variance": fmt(population_variance(pair_mass)),
        "residue_marginal_mass_seed_mean": fmt(sum(marginal_mass) / len(marginal_mass)),
        "residue_marginal_mass_seed_variance": fmt(population_variance(marginal_mass)),
        "haddock_score_seed_mean": fmt(sum(score_means) / len(score_means)),
        "haddock_score_seed_variance": fmt(population_variance(score_means)),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    return pair_rows, residue_rows, receptor_row


def na_receptor_row(candidate: Mapping[str, str], ranking: Mapping[str, str], receptor: str) -> dict[str, Any]:
    row = {
        "schema_version": SCHEMA_VERSION, "teacher_state": INCOMPLETE_STATE,
        "candidate_id": candidate["candidate_id"], "sequence_sha256": candidate["sequence_sha256"],
        "parent_framework_cluster": candidate["parent_framework_cluster"],
        "target_patch_id": ranking["target_patch_id"], "design_mode": ranking["design_mode"],
        "development_reliability_tier": "NA", "docking_evidence_tier": INCOMPLETE_TIER,
        "receptor": receptor, "observed_seed_ids": "", "declared_successful_seed_ids": "",
        "excluded_unpaired_seed_ids": "", "technical_reasons": ranking["technical_reasons"],
        "claim_boundary": CLAIM_BOUNDARY,
    }
    row.update({field: "" for field in RECEPTOR_NUMERIC_FIELDS})
    return row


def dry_run_validate(inputs: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(inputs["root"]); candidates = inputs["candidates"]
    for job in inputs["selected_jobs"]:
        validate_job_metadata(root, job, candidates[job["entity_id"]])
    return {
        "status": "PASS_ADAPTIVE_READ_ONLY_DRY_RUN", "analyzable_candidates": len(inputs["valid_ids"]),
        "technical_incomplete_candidates": len(inputs["incomplete_ids"]),
        "selected_paired_successful_jobs_validated": len(inputs["selected_jobs"]),
        "pose_coordinate_files_opened": 0, "source_mutation_operations": 0,
    }


def extract(root: Path, contract_path: Path, reconciliation_path: Path, output_dir: Path, *, workers: int = 1, dry_run: bool = False) -> dict[str, Any]:
    require(workers >= 1, "workers_must_be_positive")
    inputs = validate_inputs(root, contract_path, reconciliation_path)
    require(workers == int((inputs["contract"].get("execution") or {}).get("workers", -1)), "workers_contract_mismatch")
    root = Path(inputs["root"]); output_dir = output_dir.resolve()
    require(not path_is_within(output_dir, root), "output_inside_read_only_source")
    require(not output_dir.exists() and not output_dir.is_symlink(), "output_exists")
    if dry_run:
        return dry_run_validate(inputs)
    candidates = inputs["candidates"]
    tasks = [{"root": str(root), "job": job, "candidate": candidates[job["entity_id"]]} for job in inputs["selected_jobs"]]
    if workers == 1:
        results = [process_seed_job(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(process_seed_job, tasks, chunksize=1))
    require(len(results) == len(tasks), "processed_job_count")
    result_by_key = {(row["candidate_id"], row["receptor"], int(row["seed"])): row for row in results}
    require(len(result_by_key) == len(results), "processed_job_key_duplicate")

    pair_rows: list[dict[str, Any]] = []; residue_rows: list[dict[str, Any]] = []
    receptor_rows: list[dict[str, Any]] = []; candidate_rows: list[dict[str, Any]] = []
    base = load_base_extractor()
    for candidate_id in sorted(candidates):
        candidate = candidates[candidate_id]; ranking = inputs["rankings"][candidate_id]
        tier = ranking["docking_evidence_tier"]
        if tier == INCOMPLETE_TIER:
            receptor_rows.extend(na_receptor_row(candidate, ranking, receptor) for receptor in RECEPTORS)
            row = {
                "schema_version": SCHEMA_VERSION, "teacher_state": INCOMPLETE_STATE,
                "candidate_id": candidate_id, "sequence_sha256": candidate["sequence_sha256"],
                "parent_framework_cluster": candidate["parent_framework_cluster"],
                "target_patch_id": ranking["target_patch_id"], "design_mode": ranking["design_mode"],
                "development_reliability_tier": "NA", "docking_evidence_tier": tier,
                "paired_seed_ids": "", "receptor_seed_set_asymmetric": "",
                "technical_reasons": ranking["technical_reasons"], "paired_seed_count": "",
                "claim_boundary": CLAIM_BOUNDARY,
            }
            row.update({field: "" for field in RANKING_NUMERIC_FIELDS})
            candidate_rows.append(row); continue
        seeds = inputs["selected_seeds"][candidate_id]
        first_job = inputs["jobs_by_key"][(candidate_id, "8x6b", seeds[0])]
        ranges = {name: base.parse_range(first_job[f"{name}_range"]) for name in ("cdr1", "cdr2", "cdr3")}
        for receptor in RECEPTORS:
            seed_results = [result_by_key[(candidate_id, receptor, seed)] for seed in seeds]
            pairs, residues, receptor_row = aggregate_candidate_receptor(
                candidate, ranking, receptor, seeds, inputs["declared_seeds"][(candidate_id, receptor)], seed_results, ranges
            )
            pair_rows.extend(pairs); residue_rows.extend(residues); receptor_rows.append(receptor_row)
        candidate_rows.append({
            "schema_version": SCHEMA_VERSION, "teacher_state": teacher_state(tier),
            "candidate_id": candidate_id, "sequence_sha256": candidate["sequence_sha256"],
            "parent_framework_cluster": candidate["parent_framework_cluster"],
            "target_patch_id": ranking["target_patch_id"], "design_mode": ranking["design_mode"],
            "development_reliability_tier": TIER_TO_RELIABILITY[tier], "docking_evidence_tier": tier,
            "paired_seed_ids": ",".join(map(str, seeds)),
            "receptor_seed_set_asymmetric": int(candidate_id in inputs["asymmetric_valid"]),
            "technical_reasons": ranking["technical_reasons"], "paired_seed_count": len(seeds),
            **{field: ranking[field] for field in RANKING_NUMERIC_FIELDS}, "claim_boundary": CLAIM_BOUNDARY,
        })
    job_rows = []
    for result in sorted(results, key=lambda row: row["job_id"]):
        candidate = candidates[result["candidate_id"]]; scores = result["pose_scores"]
        job_rows.append({
            "schema_version": SCHEMA_VERSION, "candidate_id": result["candidate_id"],
            "sequence_sha256": candidate["sequence_sha256"], "receptor": result["receptor"],
            "seed": result["seed"], "job_id": result["job_id"], "job_hash": result["job_hash"],
            "job_result_sha256": result["job_result_sha256"], "selected_pose_count": result["pose_count"],
            "selected_pose_score_min": fmt(min(scores)), "selected_pose_score_mean": fmt(sum(scores) / len(scores)),
            "selected_pose_score_max": fmt(max(scores)), "claim_boundary": CLAIM_BOUNDARY,
        })
    expected = inputs["contract"]["expected_counts"]
    require(len(candidate_rows) == int(expected["candidates"]), "candidate_output_count")
    require(len(receptor_rows) == 2 * len(candidate_rows), "receptor_output_count")
    require(len(job_rows) == int(expected["selected_paired_jobs"]), "job_output_count")
    na_candidates = [row for row in candidate_rows if row["teacher_state"] == INCOMPLETE_STATE]
    require(len(na_candidates) == int(expected["tier_counts"][INCOMPLETE_TIER]), "na_output_count")
    require(all(row[field] == "" for row in na_candidates for field in ["paired_seed_count", *RANKING_NUMERIC_FIELDS]), "na_candidate_numeric_not_empty")
    na_receptors = [row for row in receptor_rows if row["teacher_state"] == INCOMPLETE_STATE]
    require(all(row[field] == "" for row in na_receptors for field in RECEPTOR_NUMERIC_FIELDS), "na_receptor_numeric_not_empty")

    output_dir.mkdir(parents=True)
    outputs = {
        PAIR_OUTPUT: (PAIR_FIELDS, pair_rows), RESIDUE_OUTPUT: (RESIDUE_FIELDS, residue_rows),
        RECEPTOR_OUTPUT: (RECEPTOR_FIELDS, receptor_rows), CANDIDATE_OUTPUT: (CANDIDATE_FIELDS, candidate_rows),
        JOB_OUTPUT: (JOB_FIELDS, job_rows),
    }
    for name, (fields, rows) in outputs.items(): write_gzip_tsv(output_dir / name, fields, rows)
    output_hashes = {name: sha256_file(output_dir / name) for name in outputs}
    audit = {
        "schema_version": f"{SCHEMA_VERSION}_audit", "status": "PASS_V4H_ADAPTIVE_MULTI_SEED_CONTACT_EXTRACTION",
        "claim_boundary": CLAIM_BOUNDARY,
        "configuration": {
            "receptors": list(RECEPTORS), "available_seeds": list(EXPECTED_SEEDS),
            "contact_cutoff_angstrom": CONTACT_CUTOFF, "top_k": TOP_K, "minimum_poses": MINIMUM_POSES,
            "dual_seed_scope": "intersection_of_ranking_declared_successful_seed_ids",
            "unmatched_receptor_successes": "excluded_without_opening_result_or_pose",
            "pose_rank_weight": "normalized_1_over_log2_rank_plus_1",
            "seed_weighting": "equal_over_paired_successful_seeds", "pair_variance": "population",
            "uncertainty_weight": "1/(1+4*variance)",
            "residue_marginal": "pose_weighted_any_pvrig_contact_then_equal_seed_mean", "workers": workers,
        },
        "inputs": {
            "contract_sha256": sha256_file(inputs["contract_path"]),
            "reconciliation_receipt_sha256": sha256_file(inputs["reconciliation_path"]),
            "implementation_sha256": sha256_file(Path(__file__)),
            "base_stage1_extractor_sha256": BASE_EXTRACTOR_SHA256,
            "raw_hashes": inputs["observed_hashes"],
        },
        "counts": {
            "candidates": len(candidate_rows), "analyzable_candidates": len(inputs["valid_ids"]),
            "technical_incomplete_candidates": len(inputs["incomplete_ids"]),
            "tier_counts": dict(sorted(inputs["tier_counts"].items())),
            "valid_receptor_seed_asymmetry_candidates": len(inputs["asymmetric_valid"]),
            "selected_paired_job_results_opened": len(results),
            "excluded_unpaired_or_technical_job_results_opened": 0,
            "selected_pose_coordinate_files_opened": sum(int(row["pose_count"]) for row in results),
            "pair_rows": len(pair_rows), "residue_rows": len(residue_rows),
            "receptor_rows": len(receptor_rows), "candidate_rows": len(candidate_rows), "job_rows": len(job_rows),
        },
        "outputs": {"hashes": output_hashes},
        "read_only_boundary": {"canonical_raw_root": str(root), "source_mutation_operations": 0,
            "technical_incomplete_job_results_opened": 0, "unpaired_success_job_results_opened": 0},
    }
    atomic_write(output_dir / AUDIT_OUTPUT, canonical_json(audit)); output_hashes[AUDIT_OUTPUT] = sha256_file(output_dir / AUDIT_OUTPUT)
    receipt = {
        "schema_version": f"{SCHEMA_VERSION}_receipt", "status": audit["status"], "claim_boundary": CLAIM_BOUNDARY,
        "contract_sha256": audit["inputs"]["contract_sha256"],
        "reconciliation_receipt_sha256": audit["inputs"]["reconciliation_receipt_sha256"],
        "implementation_sha256": audit["inputs"]["implementation_sha256"], "output_hashes": output_hashes,
        "candidate_rows": len(candidate_rows), "valid_candidate_rows": len(inputs["valid_ids"]),
        "technical_incomplete_candidate_rows": len(inputs["incomplete_ids"]), "pair_rows": len(pair_rows),
        "residue_rows": len(residue_rows), "selected_paired_job_rows": len(job_rows), "source_mutation_operations": 0,
    }
    atomic_write(output_dir / RECEIPT_OUTPUT, canonical_json(receipt))
    return {**{key: receipt[key] for key in ("status", "candidate_rows", "valid_candidate_rows", "technical_incomplete_candidate_rows", "pair_rows", "residue_rows", "selected_paired_job_rows")}, "receipt_sha256": sha256_file(output_dir / RECEIPT_OUTPUT)}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--campaign-root", type=Path, required=True)
    value.add_argument("--contract", type=Path, required=True)
    value.add_argument("--reconciliation-receipt", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--workers", type=int, default=1)
    value.add_argument("--dry-run", action="store_true")
    return value


def main() -> int:
    args = parser().parse_args()
    result = extract(args.campaign_root, args.contract, args.reconciliation_receipt, args.output_dir, workers=args.workers, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
