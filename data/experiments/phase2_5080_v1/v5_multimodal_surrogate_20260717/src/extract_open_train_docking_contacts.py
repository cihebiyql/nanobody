#!/usr/bin/env python3
"""Extract OPEN_TRAIN-only residue-contact teacher intermediates from V4-D poses."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import stat
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


SCHEMA_VERSION = "pvrig_v5_rc_open_train_docking_contacts_v1"
CLAIM_BOUNDARY = (
    "OPEN_TRAIN-only computational contact intermediates derived from independent "
    "dual-receptor HADDOCK poses; not binding, affinity, competition, experimental "
    "blocking, Docking Gold, or final submission evidence."
)
EXPECTED_CANDIDATES_SHA256 = "c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd"
EXPECTED_JOBS_SHA256 = "96fec07a5535615f50bff40ac48bb323a94213e06a7b12726ae5b4b2d1161737"
EXPECTED_HOTSPOTS_SHA256 = "7fa190ed91a1bbafcdcc21f6cd74f0345b43b3a3e6e8379c3bf3f1810abeb1c3"
OPEN_SPLIT = "OPEN_TRAIN"
FORBIDDEN_SPLITS = {"OPEN_DEVELOPMENT", "PROSPECTIVE_COMPUTATIONAL_TEST"}
RECEPTORS = ("8x6b", "9e6y")
EXPECTED_SEEDS = (917, 1931, 3253)
CONTACT_CUTOFF = 4.5
TOP_K = 8
MINIMUM_POSES = 4
MINIMUM_SEEDS = 2
PAIR_OUTPUT = "open_train226_contact_pairs.tsv.gz"
RECEPTOR_OUTPUT = "open_train226_receptor_contact_features.tsv"
CANDIDATE_OUTPUT = "open_train226_candidate_contact_features.tsv"
AUDIT_OUTPUT = "open_train226_contact_extraction_audit.json"
RECEIPT_OUTPUT = "RUN_RECEIPT.json"

AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


class ContactExtractionError(RuntimeError):
    """Fail-closed contact extraction error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContactExtractionError(message)


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
        raise ContactExtractionError(f"missing_file:{label}:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"not_regular_or_symlink:{label}:{path}")


def load_tsv(path: Path, label: str) -> tuple[list[str], list[dict[str, str]]]:
    require_regular_file(path, label)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    require(fields and rows, f"empty_tsv:{label}")
    return fields, rows


def load_json(path: Path, label: str) -> dict[str, Any]:
    require_regular_file(path, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContactExtractionError(f"invalid_json:{label}:{path}") from exc
    require(isinstance(payload, dict), f"json_not_object:{label}:{path}")
    return payload


def parse_range(spec: str) -> set[int]:
    values: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part[1:]:
            split = part[1:].index("-") + 1
            start, end = int(part[:split]), int(part[split + 1 :])
            if start > end:
                start, end = end, start
            values.update(range(start, end + 1))
        else:
            values.add(int(part))
    require(bool(values), f"empty_residue_range:{spec}")
    return values


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    atomic_write(path, buffer.getvalue().encode("utf-8"))


def write_gzip_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="", write_through=True) as text:
                writer = csv.DictWriter(text, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow({field: row.get(field, "") for field in fields})
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(temporary, path)


def _open_pose(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="ascii", errors="strict")
    return path.open("r", encoding="ascii", errors="strict")


def _heavy_atom(line: str) -> bool:
    atom_name = line[12:16].strip().upper()
    element = line[76:78].strip().upper() if len(line) >= 78 else ""
    if not element:
        element = "".join(char for char in atom_name if char.isalpha())[:1]
    return element not in {"H", "D"} and not atom_name.startswith(("H", "D"))


def contact_pairs_from_pose(
    pose_path: Path,
    expected_sequence: str,
    vhh_chain: str,
    pvrig_chain: str,
    cutoff: float,
) -> tuple[set[tuple[int, int]], dict[int, str]]:
    vhh_atom_coordinates: list[tuple[float, float, float]] = []
    vhh_atom_keys: list[tuple[int, str, str]] = []
    target_atom_coordinates: list[tuple[float, float, float]] = []
    target_atom_positions: list[int] = []
    target_residue_names: dict[int, str] = {}
    vhh_order: list[tuple[int, str, str]] = []
    vhh_seen: set[tuple[int, str, str]] = set()

    with _open_pose(pose_path) as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.startswith("ATOM  "):
                continue
            require(len(line) >= 54, f"short_atom_record:{pose_path}:{line_number}")
            residue_name = line[17:20].strip().upper()
            if residue_name not in AA3_TO_1 or not _heavy_atom(line):
                continue
            chain = line[21:22]
            try:
                residue_number = int(line[22:26])
                insertion_code = line[26:27]
                coordinate = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
            except ValueError as exc:
                raise ContactExtractionError(f"invalid_atom_record:{pose_path}:{line_number}") from exc
            key = (residue_number, insertion_code, residue_name)
            if chain == vhh_chain:
                if key not in vhh_seen:
                    vhh_seen.add(key)
                    vhh_order.append(key)
                vhh_atom_coordinates.append(coordinate)
                vhh_atom_keys.append(key)
            elif chain == pvrig_chain:
                target_atom_coordinates.append(coordinate)
                target_atom_positions.append(residue_number)
                previous = target_residue_names.setdefault(residue_number, residue_name)
                require(previous == residue_name, f"target_residue_identity_conflict:{pose_path}:{residue_number}")

    observed_sequence = "".join(AA3_TO_1[key[2]] for key in vhh_order)
    require(observed_sequence == expected_sequence, f"pose_vhh_sequence_mismatch:{pose_path}")
    require(vhh_atom_coordinates and target_atom_coordinates, f"pose_required_chains_missing:{pose_path}")
    index_by_key = {key: index + 1 for index, key in enumerate(vhh_order)}
    vhh_indices = np.asarray([index_by_key[key] for key in vhh_atom_keys], dtype=np.int32)
    target_positions = np.asarray(target_atom_positions, dtype=np.int32)
    vhh_xyz = np.asarray(vhh_atom_coordinates, dtype=np.float64)
    target_xyz = np.asarray(target_atom_coordinates, dtype=np.float64)
    cutoff_squared = cutoff * cutoff
    pairs: set[tuple[int, int]] = set()
    for start in range(0, len(vhh_xyz), 256):
        chunk = vhh_xyz[start : start + 256]
        distances_squared = np.sum((chunk[:, None, :] - target_xyz[None, :, :]) ** 2, axis=2)
        for left, right in np.argwhere(distances_squared <= cutoff_squared):
            pairs.add((int(vhh_indices[start + int(left)]), int(target_positions[int(right)])))
    return pairs, target_residue_names


def _safe_pose_path(root: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    require_regular_file(path, "pose")
    resolved_root = root.resolve()
    resolved = path.resolve()
    require(resolved.is_relative_to(resolved_root / "runs"), f"pose_outside_runs:{path}")
    return resolved


def process_job(task: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(str(task["root"]))
    job = dict(task["job"])
    candidate = dict(task["candidate"])
    result_path = root / "results" / job["job_id"] / "job_result.json"
    if not result_path.is_file():
        return {
            "status": "MISSING_OR_FAILED",
            "candidate_id": candidate["candidate_id"],
            "receptor": job["conformation"],
            "seed": int(job["seed"]),
            "job_id": job["job_id"],
        }
    payload = load_json(result_path, "job_result")
    require(payload.get("state") == "SUCCESS", f"job_not_success:{job['job_id']}")
    require(payload.get("job_id") == job["job_id"], f"job_id_mismatch:{job['job_id']}")
    require(payload.get("job_hash") == job["job_hash"], f"job_hash_mismatch:{job['job_id']}")
    require(payload.get("entity_id") == candidate["candidate_id"], f"job_candidate_mismatch:{job['job_id']}")
    require(str(payload.get("dock_conformation")) == job["conformation"], f"job_receptor_mismatch:{job['job_id']}")
    require(int(payload.get("seed")) == int(job["seed"]), f"job_seed_mismatch:{job['job_id']}")

    ranked: list[tuple[float, str, Mapping[str, Any]]] = []
    for pose in payload.get("pose_scores", []):
        if not isinstance(pose, dict):
            continue
        haddock = pose.get("haddock_io") or {}
        try:
            score = float(haddock.get("score"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(score):
            continue
        pose_name = Path(str(pose.get("pose", ""))).name
        ranked.append((score, pose_name, pose))
    ranked.sort(key=lambda item: (item[0], item[1]))
    selected = ranked[: int(task["top_k"])]
    require(len(selected) >= int(task["minimum_poses"]), f"too_few_ranked_poses:{job['job_id']}:{len(selected)}")
    raw_weights = np.asarray([1.0 / math.log2(rank + 1.0) for rank in range(1, len(selected) + 1)], dtype=np.float64)
    weights = raw_weights / raw_weights.sum()
    pair_frequency: defaultdict[tuple[int, int], float] = defaultdict(float)
    target_names: dict[int, str] = {}
    pose_names: list[str] = []
    pose_scores: list[float] = []
    for weight, (score, pose_name, pose) in zip(weights, selected):
        pose_path = _safe_pose_path(root, str(pose.get("pose", "")))
        pairs, names = contact_pairs_from_pose(
            pose_path,
            candidate["sequence"],
            job["vhh_chain"],
            job["receptor_chain"],
            float(task["contact_cutoff"]),
        )
        for pair in pairs:
            pair_frequency[pair] += float(weight)
        for position, name in names.items():
            previous = target_names.setdefault(position, name)
            require(previous == name, f"target_identity_conflict:{job['job_id']}:{position}")
        pose_names.append(pose_name)
        pose_scores.append(score)
    return {
        "status": "SUCCESS",
        "candidate_id": candidate["candidate_id"],
        "receptor": job["conformation"],
        "seed": int(job["seed"]),
        "job_id": job["job_id"],
        "pose_count": len(selected),
        "pose_names": pose_names,
        "pose_scores": pose_scores,
        "pair_frequency": dict(pair_frequency),
        "target_names": target_names,
    }


def region_for(index: int, ranges: Mapping[str, set[int]]) -> str:
    for name in ("cdr1", "cdr2", "cdr3"):
        if index in ranges[name]:
            return name
    return "framework"


def normalized_entropy(values: Sequence[float]) -> float:
    positive = np.asarray([value for value in values if value > 0.0], dtype=np.float64)
    if len(positive) <= 1:
        return 0.0
    probabilities = positive / positive.sum()
    return float(-np.sum(probabilities * np.log(probabilities)) / math.log(len(probabilities)))


def receptor_features(
    candidate: Mapping[str, str],
    receptor: str,
    results: Sequence[Mapping[str, Any]],
    ranges: Mapping[str, set[int]],
    hotspots: Mapping[str, set[int]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[int, float]]:
    successful = [row for row in results if row["status"] == "SUCCESS"]
    require(len(successful) >= MINIMUM_SEEDS, f"too_few_successful_seeds:{candidate['candidate_id']}:{receptor}")
    require(len({int(row["seed"]) for row in successful}) == len(successful), f"duplicate_seed:{candidate['candidate_id']}:{receptor}")
    union_pairs = sorted({pair for row in successful for pair in row["pair_frequency"]})
    target_names: dict[int, str] = {}
    for row in successful:
        for position, name in row["target_names"].items():
            position = int(position)
            previous = target_names.setdefault(position, str(name))
            require(previous == str(name), f"target_identity_conflict:{candidate['candidate_id']}:{receptor}:{position}")
    pair_rows: list[dict[str, Any]] = []
    robust_pairs: dict[tuple[int, int], float] = {}
    pair_standard_deviations: list[float] = []
    for vhh_index, target_position in union_pairs:
        values = np.asarray([float(row["pair_frequency"].get((vhh_index, target_position), 0.0)) for row in successful])
        median = float(np.median(values))
        mean = float(np.mean(values))
        standard_deviation = float(np.std(values, ddof=0))
        pair_standard_deviations.append(standard_deviation)
        if median > 0.0:
            robust_pairs[(vhh_index, target_position)] = median
        pair_rows.append({
            "schema_version": SCHEMA_VERSION,
            "candidate_id": candidate["candidate_id"],
            "parent_framework_cluster": candidate["parent_framework_cluster"],
            "receptor": receptor,
            "vhh_sequence_index": vhh_index,
            "vhh_aa": candidate["sequence"][vhh_index - 1],
            "vhh_region": region_for(vhh_index, ranges),
            "pvrig_uniprot_position": target_position,
            "pvrig_aa": AA3_TO_1[target_names[target_position]],
            "contact_frequency_seed_median": median,
            "contact_frequency_seed_mean": mean,
            "contact_frequency_seed_std": standard_deviation,
            "supporting_seed_count": int(np.count_nonzero(values > 0.0)),
            "successful_seed_count": len(successful),
        })

    target_profile: dict[int, float] = defaultdict(float)
    for (vhh_index, target_position), frequency in robust_pairs.items():
        target_profile[target_position] = max(target_profile[target_position], frequency)
    region_mass = {name: 0.0 for name in ("cdr1", "cdr2", "cdr3", "framework")}
    for (vhh_index, _target_position), frequency in robust_pairs.items():
        region_mass[region_for(vhh_index, ranges)] += frequency
    pair_mass = float(sum(robust_pairs.values()))
    target_soft = float(sum(target_profile.values()))
    full = float(sum(value for position, value in target_profile.items() if position in hotspots["full"]))
    anchor = float(sum(value for position, value in target_profile.items() if position in hotspots["anchor"]))
    holdout = float(sum(value for position, value in target_profile.items() if position in hotspots["holdout"]))
    off_interface = float(sum(value for position, value in target_profile.items() if position not in hotspots["full"]))
    features: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": candidate["candidate_id"],
        "sequence_sha256": candidate["sequence_sha256"],
        "parent_framework_cluster": candidate["parent_framework_cluster"],
        "receptor": receptor,
        "successful_seed_count": len(successful),
        "mean_selected_pose_count": float(np.mean([row["pose_count"] for row in successful])),
        "pair_contact_mass": pair_mass,
        "pvrig_soft_coverage": target_soft,
        "pvrig_hard50_coverage": sum(value >= 0.5 for value in target_profile.values()),
        "full_hotspot_soft_coverage": full,
        "anchor_hotspot_soft_coverage": anchor,
        "holdout_hotspot_soft_coverage": holdout,
        "off_interface_soft_coverage": off_interface,
        "interface_specificity": full / max(full + off_interface, 1e-12),
        "cdr1_contact_mass": region_mass["cdr1"],
        "cdr2_contact_mass": region_mass["cdr2"],
        "cdr3_contact_mass": region_mass["cdr3"],
        "framework_contact_mass": region_mass["framework"],
        "cdr1_contact_fraction": region_mass["cdr1"] / max(pair_mass, 1e-12),
        "cdr2_contact_fraction": region_mass["cdr2"] / max(pair_mass, 1e-12),
        "cdr3_contact_fraction": region_mass["cdr3"] / max(pair_mass, 1e-12),
        "framework_contact_fraction": region_mass["framework"] / max(pair_mass, 1e-12),
        "pvrig_profile_entropy": normalized_entropy(list(target_profile.values())),
        "mean_pair_seed_std": float(np.mean(pair_standard_deviations)) if pair_standard_deviations else 0.0,
        "robust_pair_count": len(robust_pairs),
        "observed_union_pair_count": len(union_pairs),
    }
    return pair_rows, features, dict(target_profile)


def jensen_shannon(left: Mapping[int, float], right: Mapping[int, float]) -> float:
    positions = sorted(set(left) | set(right))
    if not positions:
        return 0.0
    p = np.asarray([float(left.get(position, 0.0)) for position in positions], dtype=np.float64)
    q = np.asarray([float(right.get(position, 0.0)) for position in positions], dtype=np.float64)
    if p.sum() <= 0.0 or q.sum() <= 0.0:
        return 1.0
    p /= p.sum()
    q /= q.sum()
    midpoint = 0.5 * (p + q)
    def divergence(values: np.ndarray) -> float:
        selected = values > 0.0
        return float(np.sum(values[selected] * np.log2(values[selected] / midpoint[selected])))
    return 0.5 * (divergence(p) + divergence(q))


def extract(
    root: Path,
    contract: Path,
    output_dir: Path,
    *,
    workers: int,
    expected_candidates: int = 226,
    enforce_production_hashes: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    require(root.is_dir(), f"campaign_root_missing:{root}")
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_exists:{output_dir}")
    require_regular_file(contract, "contract")
    candidates_path = root / "inputs/candidates_290.tsv"
    jobs_path = root / "manifests/docking_jobs.tsv"
    hotspots_path = root / "reports/reference_normalization_summary.json"
    input_hashes = {
        "candidates_290": sha256_file(candidates_path),
        "docking_jobs": sha256_file(jobs_path),
        "reference_normalization_summary": sha256_file(hotspots_path),
        "contract": sha256_file(contract),
        "implementation": sha256_file(Path(__file__)),
    }
    if enforce_production_hashes:
        require(input_hashes["candidates_290"] == EXPECTED_CANDIDATES_SHA256, "candidates_sha256_mismatch")
        require(input_hashes["docking_jobs"] == EXPECTED_JOBS_SHA256, "jobs_sha256_mismatch")
        require(input_hashes["reference_normalization_summary"] == EXPECTED_HOTSPOTS_SHA256, "hotspots_sha256_mismatch")
    _candidate_fields, all_candidates = load_tsv(candidates_path, "candidates")
    split_counts = Counter(row["model_split"] for row in all_candidates)
    candidates = [row for row in all_candidates if row["model_split"] == OPEN_SPLIT]
    require(len(candidates) == expected_candidates, f"open_train_candidate_count_invalid:{len(candidates)}")
    require(len({row["candidate_id"] for row in candidates}) == len(candidates), "candidate_id_not_unique")
    require(len({row["sequence_sha256"] for row in candidates}) == len(candidates), "sequence_sha256_not_unique")
    candidate_by_id = {row["candidate_id"]: row for row in candidates}
    _job_fields, all_jobs = load_tsv(jobs_path, "docking_jobs")
    jobs = [row for row in all_jobs if row.get("entity_type") == "candidate" and row.get("entity_id") in candidate_by_id]
    require(len(jobs) == expected_candidates * len(RECEPTORS) * len(EXPECTED_SEEDS), f"open_train_job_count_invalid:{len(jobs)}")
    jobs_by_candidate: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for job in jobs:
        jobs_by_candidate[job["entity_id"]].append(job)
        require(job["conformation"] in RECEPTORS, f"unexpected_receptor:{job['job_id']}")
        require(int(job["seed"]) in EXPECTED_SEEDS, f"unexpected_seed:{job['job_id']}")
        require(job["sequence_sha256"] == candidate_by_id[job["entity_id"]]["sequence_sha256"], f"job_sequence_mismatch:{job['job_id']}")
    require(set(jobs_by_candidate) == set(candidate_by_id), "candidate_job_closure_failed")
    for candidate_id, rows in jobs_by_candidate.items():
        require(len(rows) == 6, f"candidate_job_count_invalid:{candidate_id}:{len(rows)}")
        require(len({(row["conformation"], row["seed"]) for row in rows}) == 6, f"candidate_job_matrix_invalid:{candidate_id}")

    hotspot_payload = load_json(hotspots_path, "reference_normalization_summary")
    source = hotspot_payload.get("hotspots") or {}
    hotspots = {
        "full": {int(value) for value in source.get("all_uniprot_positions", [])},
        "anchor": {int(value) for value in source.get("air_anchor_uniprot_positions", [])},
        "holdout": {int(value) for value in source.get("holdout_uniprot_positions", [])},
    }
    require(tuple(map(len, (hotspots["full"], hotspots["anchor"], hotspots["holdout"]))) == (23, 12, 11), "hotspot_partition_invalid")

    tasks = [{
        "root": str(root),
        "job": job,
        "candidate": candidate_by_id[job["entity_id"]],
        "top_k": TOP_K,
        "minimum_poses": MINIMUM_POSES,
        "contact_cutoff": CONTACT_CUTOFF,
    } for job in sorted(jobs, key=lambda row: row["job_id"])]
    if workers <= 1:
        job_results = [process_job(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            job_results = list(pool.map(process_job, tasks, chunksize=1))
    results_by_key: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in job_results:
        results_by_key[(row["candidate_id"], row["receptor"])].append(row)

    pair_rows: list[dict[str, Any]] = []
    receptor_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    profiles: dict[tuple[str, str], dict[int, float]] = {}
    receptor_feature_names: list[str] | None = None
    metadata = {"schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster", "receptor"}
    ranges_by_candidate: dict[str, dict[str, set[int]]] = {}
    for candidate_id in sorted(candidate_by_id):
        invariant = jobs_by_candidate[candidate_id][0]
        ranges = {
            "cdr1": parse_range(invariant["cdr1_range"]),
            "cdr2": parse_range(invariant["cdr2_range"]),
            "cdr3": parse_range(invariant["cdr3_range"]),
        }
        ranges_by_candidate[candidate_id] = ranges
        for receptor in RECEPTORS:
            pairs, features, profile = receptor_features(
                candidate_by_id[candidate_id], receptor, results_by_key[(candidate_id, receptor)], ranges, hotspots
            )
            pair_rows.extend(pairs)
            receptor_rows.append(features)
            profiles[(candidate_id, receptor)] = profile
            numeric_names = [name for name in features if name not in metadata]
            if receptor_feature_names is None:
                receptor_feature_names = numeric_names
            else:
                require(numeric_names == receptor_feature_names, "receptor_feature_schema_drift")
    require(receptor_feature_names is not None, "receptor_feature_schema_missing")
    receptor_by_key = {(row["candidate_id"], row["receptor"]): row for row in receptor_rows}
    for candidate_id in sorted(candidate_by_id):
        candidate = candidate_by_id[candidate_id]
        left = receptor_by_key[(candidate_id, "8x6b")]
        right = receptor_by_key[(candidate_id, "9e6y")]
        row: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": candidate_id,
            "sequence_sha256": candidate["sequence_sha256"],
            "parent_framework_cluster": candidate["parent_framework_cluster"],
        }
        for receptor, values in (("8x6b", left), ("9e6y", right)):
            for name in receptor_feature_names:
                row[f"{receptor}_{name}"] = values[name]
        for name in receptor_feature_names:
            lvalue, rvalue = float(left[name]), float(right[name])
            row[f"dual_mean_{name}"] = 0.5 * (lvalue + rvalue)
            row[f"dual_min_{name}"] = min(lvalue, rvalue)
            row[f"dual_abs_gap_{name}"] = abs(lvalue - rvalue)
        row["dual_pvrig_profile_jsd"] = jensen_shannon(profiles[(candidate_id, "8x6b")], profiles[(candidate_id, "9e6y")])
        candidate_rows.append(row)

    require(len(candidate_rows) == expected_candidates, "candidate_feature_row_count_invalid")
    require(all(math.isfinite(float(value)) for row in candidate_rows for name, value in row.items() if name not in {"schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster"}), "candidate_features_nonfinite")
    output_dir.mkdir(parents=True)
    pair_fields = [
        "schema_version", "candidate_id", "parent_framework_cluster", "receptor",
        "vhh_sequence_index", "vhh_aa", "vhh_region", "pvrig_uniprot_position", "pvrig_aa",
        "contact_frequency_seed_median", "contact_frequency_seed_mean", "contact_frequency_seed_std",
        "supporting_seed_count", "successful_seed_count",
    ]
    receptor_fields = ["schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster", "receptor", *receptor_feature_names]
    candidate_fields = list(candidate_rows[0])
    write_gzip_tsv(output_dir / PAIR_OUTPUT, pair_fields, pair_rows)
    write_tsv(output_dir / RECEPTOR_OUTPUT, receptor_fields, receptor_rows)
    write_tsv(output_dir / CANDIDATE_OUTPUT, candidate_fields, candidate_rows)
    output_hashes = {
        PAIR_OUTPUT: sha256_file(output_dir / PAIR_OUTPUT),
        RECEPTOR_OUTPUT: sha256_file(output_dir / RECEPTOR_OUTPUT),
        CANDIDATE_OUTPUT: sha256_file(output_dir / CANDIDATE_OUTPUT),
    }
    status_counts = Counter(row["status"] for row in job_results)
    successful_pose_count = sum(int(row.get("pose_count", 0)) for row in job_results if row["status"] == "SUCCESS")
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "COMPLETE_OPEN_TRAIN226_CONTACT_TEACHER_EXTRACTION",
        "claim_boundary": CLAIM_BOUNDARY,
        "configuration": {
            "contact_cutoff_angstrom": CONTACT_CUTOFF,
            "top_k": TOP_K,
            "minimum_poses_per_successful_job": MINIMUM_POSES,
            "minimum_successful_seeds_per_candidate_receptor": MINIMUM_SEEDS,
            "pose_rank_weight": "normalized_1_over_log2_rank_plus_1",
            "seed_aggregation_primary": "median_with_absent_pair_zero_over_observed_successful_seeds",
            "workers": workers,
        },
        "inputs": input_hashes,
        "input_counts": {
            "all_candidate_split_counts": dict(sorted(split_counts.items())),
            "open_train_candidates": len(candidates),
            "open_train_parent_clusters": len({row["parent_framework_cluster"] for row in candidates}),
            "open_train_jobs_scheduled": len(tasks),
        },
        "job_results": {
            "status_counts": dict(sorted(status_counts.items())),
            "successful_pose_files_opened": successful_pose_count,
            "successful_pose_count_distribution": dict(sorted(Counter(str(row.get("pose_count", 0)) for row in job_results if row["status"] == "SUCCESS").items())),
        },
        "outputs": {
            "pair_rows": len(pair_rows),
            "receptor_rows": len(receptor_rows),
            "candidate_rows": len(candidate_rows),
            "candidate_numeric_feature_count": len(candidate_fields) - 4,
            "hashes": output_hashes,
        },
        "sealed_boundary": {
            "allowed_model_split": OPEN_SPLIT,
            "forbidden_model_splits": sorted(FORBIDDEN_SPLITS),
            "forbidden_candidate_job_results_opened": 0,
            "forbidden_candidate_pose_files_opened": 0,
            "control_job_results_opened": 0,
            "control_pose_files_opened": 0,
            "prospective_test_contact_labels_emitted": 0,
        },
    }
    atomic_write(output_dir / AUDIT_OUTPUT, canonical_json(audit))
    output_hashes[AUDIT_OUTPUT] = sha256_file(output_dir / AUDIT_OUTPUT)
    receipt = {
        "schema_version": f"{SCHEMA_VERSION}_receipt",
        "status": "COMPLETE_OPEN_TRAIN226_CONTACT_TEACHER_EXTRACTION",
        "claim_boundary": CLAIM_BOUNDARY,
        "input_hashes": input_hashes,
        "output_hashes": output_hashes,
        "candidate_rows": len(candidate_rows),
        "receptor_rows": len(receptor_rows),
        "pair_rows": len(pair_rows),
        "forbidden_candidate_pose_files_opened": 0,
    }
    atomic_write(output_dir / RECEIPT_OUTPUT, canonical_json(receipt))
    return {
        "status": receipt["status"],
        "candidate_rows": len(candidate_rows),
        "receptor_rows": len(receptor_rows),
        "pair_rows": len(pair_rows),
        "job_status_counts": dict(sorted(status_counts.items())),
        "candidate_feature_sha256": output_hashes[CANDIDATE_OUTPUT],
        "receipt_sha256": sha256_file(output_dir / RECEIPT_OUTPUT),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--expected-candidates", type=int, default=226)
    parser.add_argument("--no-production-hash-enforcement", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    require(args.workers >= 1, "workers_must_be_positive")
    result = extract(
        args.campaign_root,
        args.contract,
        args.output_dir,
        workers=args.workers,
        expected_candidates=args.expected_candidates,
        enforce_production_hashes=not args.no_production_hash_enforcement,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
