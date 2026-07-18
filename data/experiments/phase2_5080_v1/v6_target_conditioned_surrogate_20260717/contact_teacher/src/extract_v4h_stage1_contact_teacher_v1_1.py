#!/usr/bin/env python3
"""Extract the frozen V4-H Stage-1 residue-contact teacher without mutating raw data."""

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


SCHEMA_VERSION = "pvrig_v6_v4h_stage1_contact_teacher_v1"
CLAIM_BOUNDARY = (
    "V4-H Stage-1 single-seed computational residue-contact intermediates derived "
    "from frozen independent 8X6B/9E6Y docking poses; not binding, affinity, "
    "competition, experimental blocking, Docking Gold, or final submission evidence."
)
RECEPTORS = ("8x6b", "9e6y")
EXPECTED_SEED = 917
CONTACT_CUTOFF = 4.5
TOP_K = 8
MINIMUM_POSES = 4
VALID_TIER = "DUAL_1_SEED"
INCOMPLETE_TIER = "TECHNICAL_INCOMPLETE"
VALID_STATE = "VALID_DUAL_1_SEED_CONTACT"
INCOMPLETE_STATE = "TECHNICAL_INCOMPLETE_NA"

PAIR_OUTPUT = "v4h_stage1_residue_pair_contact_teacher.tsv.gz"
RECEPTOR_OUTPUT = "v4h_stage1_receptor_contact_teacher.tsv.gz"
CANDIDATE_OUTPUT = "v4h_stage1_candidate_contact_teacher.tsv.gz"
AUDIT_OUTPUT = "v4h_stage1_contact_extraction_audit.json"
RECEIPT_OUTPUT = "RUN_RECEIPT.json"

PACKAGE_FILES = (
    "stage1_all_seed917.tsv",
    "stage1_all_seed917.terminal.json",
    "stage1_seed917_ranking.tsv",
    "stage1_failures.tsv",
    "stage1_local_package_receipt.json",
    "SHA256SUMS",
)

AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}

PAIR_FIELDS = [
    "schema_version", "teacher_state", "candidate_id", "sequence_sha256",
    "parent_framework_cluster", "receptor", "seed", "vhh_sequence_index",
    "vhh_aa", "vhh_region", "pvrig_uniprot_position", "pvrig_aa",
    "contact_frequency_pose_weighted", "contact_frequency_pose_unweighted",
    "supporting_pose_count", "selected_pose_count",
]

RECEPTOR_NUMERIC_FIELDS = [
    "selected_pose_count", "haddock_score_min", "haddock_score_mean",
    "haddock_score_max", "pair_contact_mass", "pvrig_soft_coverage",
    "pvrig_hard50_coverage", "full_hotspot_soft_coverage",
    "anchor_hotspot_soft_coverage", "holdout_hotspot_soft_coverage",
    "off_interface_soft_coverage", "interface_specificity", "cdr1_contact_mass",
    "cdr2_contact_mass", "cdr3_contact_mass", "framework_contact_mass",
    "cdr1_contact_fraction", "cdr2_contact_fraction", "cdr3_contact_fraction",
    "framework_contact_fraction", "pvrig_profile_entropy", "weighted_pair_count",
    "observed_pair_count",
]

RECEPTOR_FIELDS = [
    "schema_version", "teacher_state", "candidate_id", "sequence_sha256",
    "parent_framework_cluster", "target_patch_id", "design_mode", "receptor",
    "seed", "technical_reasons", *RECEPTOR_NUMERIC_FIELDS,
]

RANKING_LABEL_FIELDS = [
    "median_score_8X6B", "median_score_9E6Y", "R_dual_min",
    "seed_dispersion_max", "confidence_adjusted_score", "rank",
]


class ContactExtractionError(RuntimeError):
    """Fail-closed extraction error."""


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


def load_json(path: Path, label: str) -> dict[str, Any]:
    require_regular_file(path, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContactExtractionError(f"invalid_json:{label}:{path}") from exc
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


def parse_sha256sums(path: Path) -> dict[str, str]:
    require_regular_file(path, "SHA256SUMS")
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        parts = raw.split(maxsplit=1)
        require(len(parts) == 2 and len(parts[0]) == 64, f"invalid_sha256sums_line:{number}")
        name = parts[1].lstrip("* ")
        require(Path(name).name == name and name not in values, f"invalid_sha256sums_name:{number}:{name}")
        values[name] = parts[0]
    require(bool(values), "empty_SHA256SUMS")
    return values


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


def canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
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
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(temporary, path)


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


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
    vhh_xyz: list[tuple[float, float, float]] = []
    vhh_atom_keys: list[tuple[int, str, str]] = []
    target_xyz: list[tuple[float, float, float]] = []
    target_positions: list[int] = []
    target_names: dict[int, str] = {}
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
                vhh_xyz.append(coordinate)
                vhh_atom_keys.append(key)
            elif chain == pvrig_chain:
                target_xyz.append(coordinate)
                target_positions.append(residue_number)
                previous = target_names.setdefault(residue_number, residue_name)
                require(previous == residue_name, f"target_residue_identity_conflict:{pose_path}:{residue_number}")
    observed_sequence = "".join(AA3_TO_1[key[2]] for key in vhh_order)
    require(observed_sequence == expected_sequence, f"pose_vhh_sequence_mismatch:{pose_path}")
    require(bool(vhh_xyz) and bool(target_xyz), f"pose_required_chains_missing:{pose_path}")
    index_by_key = {key: index + 1 for index, key in enumerate(vhh_order)}
    vhh_indices = np.asarray([index_by_key[key] for key in vhh_atom_keys], dtype=np.int32)
    target_index = np.asarray(target_positions, dtype=np.int32)
    left_xyz = np.asarray(vhh_xyz, dtype=np.float64)
    right_xyz = np.asarray(target_xyz, dtype=np.float64)
    cutoff_squared = cutoff * cutoff
    pairs: set[tuple[int, int]] = set()
    for start in range(0, len(left_xyz), 256):
        chunk = left_xyz[start : start + 256]
        distances_squared = np.sum((chunk[:, None, :] - right_xyz[None, :, :]) ** 2, axis=2)
        for left, right in np.argwhere(distances_squared <= cutoff_squared):
            pairs.add((int(vhh_indices[start + int(left)]), int(target_index[int(right)])))
    return pairs, target_names


def _safe_pose_path(root: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    require_regular_file(path, "pose")
    resolved = path.resolve()
    require(path_is_within(resolved, (root / "runs").resolve()), f"pose_outside_runs:{path}")
    return resolved


def ranked_poses(root: Path, payload: Mapping[str, Any], job_id: str) -> list[tuple[float, str, Path]]:
    # The frozen Node23 result contains canonical relative selected_models plus scorer
    # provenance whose `pose` field may retain an inaccessible local-offload path.
    # Canonical coordinates are therefore resolved only from selected_models; the
    # scorer path contributes its basename for a fail-closed one-to-one join.
    selected_models = payload.get("selected_models", [])
    require(isinstance(selected_models, list), f"selected_models_not_list:{job_id}")
    canonical_by_name: dict[str, Path] = {}
    for value in selected_models:
        path = _safe_pose_path(root, str(value))
        require(path.name not in canonical_by_name, f"duplicate_selected_model_basename:{job_id}:{path.name}")
        canonical_by_name[path.name] = path
    if canonical_by_name:
        require(len(canonical_by_name) >= MINIMUM_POSES, f"too_few_selected_models:{job_id}:{len(canonical_by_name)}")

    ranked: list[tuple[float, str, Path]] = []
    seen_names: set[str] = set()
    for pose in payload.get("pose_scores", []):
        if not isinstance(pose, dict):
            continue
        try:
            score = float((pose.get("haddock_io") or {}).get("score"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(score):
            continue
        pose_value = str(pose.get("pose", ""))
        pose_name = Path(pose_value).name
        if canonical_by_name:
            require(pose_name in canonical_by_name, f"scored_pose_not_in_selected_models:{job_id}:{pose_name}")
            pose_path = canonical_by_name[pose_name]
        else:
            # Backward-compatible path for canonical results that predate selected_models.
            # _safe_pose_path still rejects any path outside the frozen campaign runs tree.
            pose_path = _safe_pose_path(root, pose_value)
        require(pose_name not in seen_names, f"duplicate_scored_pose:{job_id}:{pose_name}")
        seen_names.add(pose_name)
        ranked.append((score, pose_name, pose_path))
    if canonical_by_name:
        require(seen_names == set(canonical_by_name), f"selected_model_score_closure:{job_id}")
    ranked.sort(key=lambda item: (item[0], item[1]))
    selected = ranked[:TOP_K]
    require(len(selected) >= MINIMUM_POSES, f"too_few_ranked_poses:{job_id}:{len(selected)}")
    return selected


def validate_job_result(root: Path, job: Mapping[str, str], candidate: Mapping[str, str]) -> tuple[dict[str, Any], list[tuple[float, str, Path]]]:
    result_path = root / "results" / job["job_id"] / "job_result.json"
    payload = load_json(result_path, "job_result")
    require(payload.get("state") == "SUCCESS", f"job_not_success:{job['job_id']}")
    require(payload.get("job_id") == job["job_id"], f"job_id_mismatch:{job['job_id']}")
    require(payload.get("job_hash") == job["job_hash"], f"job_hash_mismatch:{job['job_id']}")
    require(payload.get("entity_id") == candidate["candidate_id"], f"job_candidate_mismatch:{job['job_id']}")
    require(str(payload.get("dock_conformation")) == job["conformation"], f"job_receptor_mismatch:{job['job_id']}")
    require(int(payload.get("seed")) == EXPECTED_SEED, f"job_seed_mismatch:{job['job_id']}")
    return payload, ranked_poses(root, payload, job["job_id"])


def process_job(task: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(str(task["root"]))
    job = dict(task["job"])
    candidate = dict(task["candidate"])
    payload, selected = validate_job_result(root, job, candidate)
    raw_weights = np.asarray([1.0 / math.log2(rank + 1.0) for rank in range(1, len(selected) + 1)], dtype=np.float64)
    weights = raw_weights / raw_weights.sum()
    pair_weight: defaultdict[tuple[int, int], float] = defaultdict(float)
    pair_support: Counter[tuple[int, int]] = Counter()
    target_names: dict[int, str] = {}
    for weight, (_score, _name, pose_path) in zip(weights, selected):
        pairs, names = contact_pairs_from_pose(
            pose_path, candidate["sequence"], job["vhh_chain"], job["receptor_chain"], CONTACT_CUTOFF
        )
        for pair in pairs:
            pair_weight[pair] += float(weight)
            pair_support[pair] += 1
        for position, name in names.items():
            previous = target_names.setdefault(position, name)
            require(previous == name, f"target_identity_conflict:{job['job_id']}:{position}")
    return {
        "candidate_id": candidate["candidate_id"],
        "receptor": job["conformation"],
        "job_id": job["job_id"],
        "seed": EXPECTED_SEED,
        "pose_count": len(selected),
        "pose_scores": [score for score, _name, _path in selected],
        "pair_weight": dict(pair_weight),
        "pair_support": dict(pair_support),
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
    ranking: Mapping[str, str],
    receptor: str,
    result: Mapping[str, Any],
    ranges: Mapping[str, set[int]],
    hotspots: Mapping[str, set[int]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[int, float]]:
    pose_count = int(result["pose_count"])
    pair_rows: list[dict[str, Any]] = []
    target_names = {int(key): str(value) for key, value in result["target_names"].items()}
    target_profile: dict[int, float] = defaultdict(float)
    region_mass = {name: 0.0 for name in ("cdr1", "cdr2", "cdr3", "framework")}
    for vhh_index, target_position in sorted(result["pair_weight"]):
        weight = float(result["pair_weight"][(vhh_index, target_position)])
        support = int(result["pair_support"][(vhh_index, target_position)])
        region = region_for(vhh_index, ranges)
        target_profile[target_position] = max(target_profile[target_position], weight)
        region_mass[region] += weight
        pair_rows.append({
            "schema_version": SCHEMA_VERSION,
            "teacher_state": VALID_STATE,
            "candidate_id": candidate["candidate_id"],
            "sequence_sha256": candidate["sequence_sha256"],
            "parent_framework_cluster": candidate["parent_framework_cluster"],
            "receptor": receptor,
            "seed": EXPECTED_SEED,
            "vhh_sequence_index": vhh_index,
            "vhh_aa": candidate["sequence"][vhh_index - 1],
            "vhh_region": region,
            "pvrig_uniprot_position": target_position,
            "pvrig_aa": AA3_TO_1[target_names[target_position]],
            "contact_frequency_pose_weighted": weight,
            "contact_frequency_pose_unweighted": support / pose_count,
            "supporting_pose_count": support,
            "selected_pose_count": pose_count,
        })
    pair_mass = float(sum(result["pair_weight"].values()))
    target_soft = float(sum(target_profile.values()))
    full = float(sum(value for position, value in target_profile.items() if position in hotspots["full"]))
    anchor = float(sum(value for position, value in target_profile.items() if position in hotspots["anchor"]))
    holdout = float(sum(value for position, value in target_profile.items() if position in hotspots["holdout"]))
    off_interface = float(sum(value for position, value in target_profile.items() if position not in hotspots["full"]))
    scores = np.asarray(result["pose_scores"], dtype=np.float64)
    features: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "teacher_state": VALID_STATE,
        "candidate_id": candidate["candidate_id"],
        "sequence_sha256": candidate["sequence_sha256"],
        "parent_framework_cluster": candidate["parent_framework_cluster"],
        "target_patch_id": ranking["target_patch_id"],
        "design_mode": ranking["design_mode"],
        "receptor": receptor,
        "seed": EXPECTED_SEED,
        "technical_reasons": "",
        "selected_pose_count": pose_count,
        "haddock_score_min": float(scores.min()),
        "haddock_score_mean": float(scores.mean()),
        "haddock_score_max": float(scores.max()),
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
        "weighted_pair_count": sum(weight >= 0.5 for weight in result["pair_weight"].values()),
        "observed_pair_count": len(result["pair_weight"]),
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


def validate_contract(contract: Mapping[str, Any], root: Path) -> None:
    require(contract.get("schema_version") == f"{SCHEMA_VERSION}_contract", "contract_schema_invalid")
    require(contract.get("status") == "FROZEN_PRE_EXTRACTION", "contract_not_frozen")
    config = contract.get("contact_definition") or {}
    require(float(config.get("contact_cutoff_angstrom")) == CONTACT_CUTOFF, "contact_cutoff_contract_changed")
    require(int(config.get("top_k")) == TOP_K, "top_k_contract_changed")
    require(int(config.get("minimum_poses")) == MINIMUM_POSES, "minimum_poses_contract_changed")
    require(int(config.get("seed")) == EXPECTED_SEED, "seed_contract_changed")
    require(tuple(config.get("receptors") or []) == RECEPTORS, "receptor_contract_changed")
    expected_root = str(contract.get("canonical_raw_root", ""))
    if expected_root:
        require(root == Path(expected_root).resolve(), f"canonical_raw_root_mismatch:{root}")


def validate_inputs(root: Path, package: Path, contract_path: Path) -> dict[str, Any]:
    root = root.resolve()
    package = package.resolve()
    require(root.is_dir(), f"campaign_root_missing:{root}")
    require(package.is_dir(), f"terminal_package_missing:{package}")
    for name in PACKAGE_FILES:
        require_regular_file(package / name, f"terminal_package:{name}")
    contract = load_json(contract_path, "contract")
    validate_contract(contract, root)
    expected_hashes = dict(contract.get("expected_sha256") or {})
    expected_counts = dict(contract.get("expected_counts") or {})

    package_hashes = {name: sha256_file(package / name) for name in PACKAGE_FILES}
    sums = parse_sha256sums(package / "SHA256SUMS")
    package_receipt = load_json(package / "stage1_local_package_receipt.json", "terminal_package_receipt")
    for name in ("stage1_all_seed917.tsv", "stage1_all_seed917.terminal.json", "stage1_seed917_ranking.tsv", "stage1_failures.tsv"):
        require(sums.get(name) == package_hashes[name], f"package_SHA256SUMS_mismatch:{name}")
        require((package_receipt.get("file_sha256") or {}).get(name) == package_hashes[name], f"package_receipt_hash_mismatch:{name}")
        pinned = expected_hashes.get(name)
        if pinned:
            require(pinned == package_hashes[name], f"contract_package_hash_mismatch:{name}")

    raw_paths = {
        "raw_candidates": root / "inputs/candidates_290.tsv",
        "raw_stage1_manifest": root / "manifests/stage1_all_seed917.tsv",
        "raw_stage1_ranking": root / "release/stage1_seed917_ranking.tsv",
        "raw_hotspots": root / "reports/reference_normalization_summary.json",
    }
    raw_hashes = {name: sha256_file(path) for name, path in raw_paths.items()}
    for name, digest in raw_hashes.items():
        pinned = expected_hashes.get(name)
        if pinned:
            require(pinned == digest, f"contract_raw_hash_mismatch:{name}")
    require(raw_hashes["raw_stage1_manifest"] == package_hashes["stage1_all_seed917.tsv"], "raw_package_manifest_drift")
    require(raw_hashes["raw_stage1_ranking"] == package_hashes["stage1_seed917_ranking.tsv"], "raw_package_ranking_drift")

    _candidate_fields, candidates = load_tsv(raw_paths["raw_candidates"], "raw_candidates")
    _job_fields, jobs = load_tsv(package / "stage1_all_seed917.tsv", "package_jobs")
    _ranking_fields, rankings = load_tsv(package / "stage1_seed917_ranking.tsv", "package_ranking")
    _failure_fields, failures = load_tsv(package / "stage1_failures.tsv", "package_failures")
    terminal = load_json(package / "stage1_all_seed917.terminal.json", "package_terminal")

    require(len(candidates) == int(expected_counts["candidates"]), f"candidate_count_invalid:{len(candidates)}")
    require(len(jobs) == int(expected_counts["stage1_jobs"]), f"stage1_job_count_invalid:{len(jobs)}")
    require(len(rankings) == int(expected_counts["ranking_rows"]), f"ranking_count_invalid:{len(rankings)}")
    require(len(failures) == int(expected_counts["failed_jobs"]), f"failure_count_invalid:{len(failures)}")
    require(int(terminal.get("job_count", -1)) == len(jobs), "terminal_job_count_mismatch")
    terminal_counts = {str(key): int(value) for key, value in (terminal.get("terminal_counts") or {}).items()}
    require(terminal_counts == {"FAILED_MAX_ATTEMPTS": int(expected_counts["failed_jobs"]), "SUCCESS": int(expected_counts["successful_jobs"])}, "terminal_counts_mismatch")
    require(package_receipt.get("terminal_counts") == terminal.get("terminal_counts"), "terminal_receipt_counts_mismatch")

    candidate_by_id = {row["candidate_id"]: row for row in candidates}
    ranking_by_id = {row["candidate_id"]: row for row in rankings}
    require(len(candidate_by_id) == len(candidates), "candidate_id_not_unique")
    require(len(ranking_by_id) == len(rankings), "ranking_candidate_id_not_unique")
    require(set(candidate_by_id) == set(ranking_by_id), "candidate_ranking_closure_failed")
    for candidate_id, candidate in candidate_by_id.items():
        require(hashlib.sha256(candidate["sequence"].encode("ascii")).hexdigest() == candidate["sequence_sha256"], f"candidate_sequence_hash_mismatch:{candidate_id}")
        ranking = ranking_by_id[candidate_id]
        require(ranking["sequence_sha256"] == candidate["sequence_sha256"], f"ranking_sequence_hash_mismatch:{candidate_id}")
        require(ranking["parent_framework_cluster"] == candidate["parent_framework_cluster"], f"ranking_parent_mismatch:{candidate_id}")

    tier_counts = Counter(row["docking_evidence_tier"] for row in rankings)
    require(tier_counts == {VALID_TIER: int(expected_counts["analyzable_candidates"]), INCOMPLETE_TIER: int(expected_counts["technical_incomplete_candidates"])}, f"ranking_tier_counts_invalid:{dict(tier_counts)}")
    valid_ids = {row["candidate_id"] for row in rankings if row["docking_evidence_tier"] == VALID_TIER}
    incomplete_ids = set(candidate_by_id) - valid_ids
    for candidate_id in valid_ids:
        row = ranking_by_id[candidate_id]
        require(row["successful_seed_count_8X6B"] == "1" and row["successful_seed_ids_8X6B"] == str(EXPECTED_SEED), f"valid_8x6b_seed_invalid:{candidate_id}")
        require(row["successful_seed_count_9E6Y"] == "1" and row["successful_seed_ids_9E6Y"] == str(EXPECTED_SEED), f"valid_9e6y_seed_invalid:{candidate_id}")
        require(not row["technical_reasons"], f"valid_candidate_has_technical_reason:{candidate_id}")
    for candidate_id in incomplete_ids:
        require(bool(ranking_by_id[candidate_id]["technical_reasons"]), f"incomplete_candidate_missing_reason:{candidate_id}")

    jobs_by_candidate: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    job_by_id: dict[str, dict[str, str]] = {}
    for job in jobs:
        require(job["entity_type"] == "candidate", f"non_candidate_stage1_job:{job['job_id']}")
        require(job["entity_id"] in candidate_by_id, f"unknown_stage1_candidate:{job['job_id']}")
        require(job["conformation"] in RECEPTORS, f"unexpected_receptor:{job['job_id']}")
        require(int(job["seed"]) == EXPECTED_SEED, f"unexpected_seed:{job['job_id']}")
        require(job["sequence_sha256"] == candidate_by_id[job["entity_id"]]["sequence_sha256"], f"job_sequence_hash_mismatch:{job['job_id']}")
        require(job["job_id"] not in job_by_id, f"duplicate_job_id:{job['job_id']}")
        job_by_id[job["job_id"]] = job
        jobs_by_candidate[job["entity_id"]].append(job)
    require(set(jobs_by_candidate) == set(candidate_by_id), "candidate_job_closure_failed")
    for candidate_id, rows in jobs_by_candidate.items():
        require(len(rows) == 2, f"candidate_job_count_invalid:{candidate_id}:{len(rows)}")
        require({row["conformation"] for row in rows} == set(RECEPTORS), f"candidate_receptor_matrix_invalid:{candidate_id}")

    failure_job_ids = set()
    for row in failures:
        require(row["job_id"] in job_by_id, f"failure_unknown_job:{row['job_id']}")
        require(row["entity_id"] in incomplete_ids, f"failure_candidate_not_incomplete:{row['job_id']}")
        require(row["status"] == "FAILED_MAX_ATTEMPTS", f"failure_status_invalid:{row['job_id']}")
        failure_job_ids.add(row["job_id"])
    require(len(failure_job_ids) == len(failures), "failure_job_id_not_unique")

    hotspot_payload = load_json(raw_paths["raw_hotspots"], "raw_hotspots")
    source = hotspot_payload.get("hotspots") or {}
    hotspots = {
        "full": {int(value) for value in source.get("all_uniprot_positions", [])},
        "anchor": {int(value) for value in source.get("air_anchor_uniprot_positions", [])},
        "holdout": {int(value) for value in source.get("holdout_uniprot_positions", [])},
    }
    require(tuple(map(len, (hotspots["full"], hotspots["anchor"], hotspots["holdout"]))) == (23, 12, 11), "hotspot_partition_invalid")

    selected_jobs = sorted((job for candidate_id in valid_ids for job in jobs_by_candidate[candidate_id]), key=lambda row: row["job_id"])
    require(len(selected_jobs) == 2 * len(valid_ids), "selected_job_count_invalid")
    technical_reason_categories = Counter(
        "FAILED_MAX_ATTEMPTS" if "FAILED_MAX_ATTEMPTS" in ranking_by_id[candidate_id]["technical_reasons"]
        else "NATIVE_OVERLAY_RMSD_ABOVE_1A"
        for candidate_id in incomplete_ids
    )
    require(sum(technical_reason_categories.values()) == len(incomplete_ids), "technical_reason_category_count_invalid")
    return {
        "root": root,
        "package": package,
        "contract_path": contract_path.resolve(),
        "contract": contract,
        "package_hashes": package_hashes,
        "raw_hashes": raw_hashes,
        "terminal_counts": terminal_counts,
        "candidates": candidates,
        "candidate_by_id": candidate_by_id,
        "rankings": rankings,
        "ranking_by_id": ranking_by_id,
        "jobs": jobs,
        "jobs_by_candidate": jobs_by_candidate,
        "selected_jobs": selected_jobs,
        "valid_ids": valid_ids,
        "incomplete_ids": incomplete_ids,
        "failure_job_ids": failure_job_ids,
        "hotspots": hotspots,
        "technical_reason_categories": technical_reason_categories,
    }


def dry_run_validate(inputs: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(inputs["root"])
    candidate_by_id = inputs["candidate_by_id"]
    for job in inputs["selected_jobs"]:
        validate_job_result(root, job, candidate_by_id[job["entity_id"]])
    return {
        "status": "PASS_READ_ONLY_DRY_RUN",
        "analyzable_candidates": len(inputs["valid_ids"]),
        "technical_incomplete_candidates": len(inputs["incomplete_ids"]),
        "selected_successful_jobs_validated": len(inputs["selected_jobs"]),
        "raw_success_jobs_declared": inputs["terminal_counts"]["SUCCESS"],
        "raw_failed_jobs_declared": inputs["terminal_counts"]["FAILED_MAX_ATTEMPTS"],
        "excluded_candidate_job_results_opened": 0,
        "pose_coordinate_files_opened": 0,
        "source_mutation_operations": 0,
    }


def na_receptor_row(candidate: Mapping[str, str], ranking: Mapping[str, str], receptor: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "teacher_state": INCOMPLETE_STATE,
        "candidate_id": candidate["candidate_id"],
        "sequence_sha256": candidate["sequence_sha256"],
        "parent_framework_cluster": candidate["parent_framework_cluster"],
        "target_patch_id": ranking["target_patch_id"],
        "design_mode": ranking["design_mode"],
        "receptor": receptor,
        "seed": EXPECTED_SEED,
        "technical_reasons": ranking["technical_reasons"],
        **{field: "" for field in RECEPTOR_NUMERIC_FIELDS},
    }


def extract(root: Path, terminal_package: Path, contract_path: Path, output_dir: Path, *, workers: int, dry_run: bool = False) -> dict[str, Any]:
    require(workers >= 1, "workers_must_be_positive")
    inputs = validate_inputs(root, terminal_package, contract_path)
    root = Path(inputs["root"])
    output_resolved = output_dir.resolve()
    require(not path_is_within(output_resolved, root), f"output_inside_read_only_source:{output_dir}")
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_exists:{output_dir}")
    if dry_run:
        return dry_run_validate(inputs)

    candidate_by_id = inputs["candidate_by_id"]
    tasks = [{"root": str(root), "job": job, "candidate": candidate_by_id[job["entity_id"]]} for job in inputs["selected_jobs"]]
    if workers == 1:
        job_results = [process_job(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            job_results = list(pool.map(process_job, tasks, chunksize=1))
    require(len(job_results) == len(tasks), "processed_job_count_invalid")
    result_by_key = {(row["candidate_id"], row["receptor"]): row for row in job_results}
    require(len(result_by_key) == len(job_results), "processed_job_key_not_unique")

    pair_rows: list[dict[str, Any]] = []
    receptor_rows: list[dict[str, Any]] = []
    profiles: dict[tuple[str, str], dict[int, float]] = {}
    receptor_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    ranking_by_id = inputs["ranking_by_id"]
    for candidate_id in sorted(candidate_by_id):
        candidate = candidate_by_id[candidate_id]
        ranking = ranking_by_id[candidate_id]
        if candidate_id in inputs["incomplete_ids"]:
            for receptor in RECEPTORS:
                row = na_receptor_row(candidate, ranking, receptor)
                receptor_rows.append(row)
                receptor_by_key[(candidate_id, receptor)] = row
            continue
        jobs = inputs["jobs_by_candidate"][candidate_id]
        invariant = jobs[0]
        ranges = {name: parse_range(invariant[f"{name}_range"]) for name in ("cdr1", "cdr2", "cdr3")}
        for receptor in RECEPTORS:
            rows, features, profile = receptor_features(
                candidate, ranking, receptor, result_by_key[(candidate_id, receptor)], ranges, inputs["hotspots"]
            )
            pair_rows.extend(rows)
            receptor_rows.append(features)
            receptor_by_key[(candidate_id, receptor)] = features
            profiles[(candidate_id, receptor)] = profile

    candidate_fields = [
        "schema_version", "teacher_state", "candidate_id", "sequence_sha256",
        "parent_framework_cluster", "target_patch_id", "design_mode", "technical_reasons",
        *RANKING_LABEL_FIELDS,
    ]
    for receptor in RECEPTORS:
        candidate_fields.extend(f"{receptor}_{field}" for field in RECEPTOR_NUMERIC_FIELDS)
    for prefix in ("dual_mean", "dual_min", "dual_abs_gap"):
        candidate_fields.extend(f"{prefix}_{field}" for field in RECEPTOR_NUMERIC_FIELDS)
    candidate_fields.append("dual_pvrig_profile_jsd")

    candidate_rows: list[dict[str, Any]] = []
    for candidate_id in sorted(candidate_by_id):
        candidate = candidate_by_id[candidate_id]
        ranking = ranking_by_id[candidate_id]
        base: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "teacher_state": VALID_STATE if candidate_id in inputs["valid_ids"] else INCOMPLETE_STATE,
            "candidate_id": candidate_id,
            "sequence_sha256": candidate["sequence_sha256"],
            "parent_framework_cluster": candidate["parent_framework_cluster"],
            "target_patch_id": ranking["target_patch_id"],
            "design_mode": ranking["design_mode"],
            "technical_reasons": ranking["technical_reasons"],
        }
        if candidate_id in inputs["incomplete_ids"]:
            for field in RANKING_LABEL_FIELDS:
                base[field] = ""
            for field in candidate_fields:
                base.setdefault(field, "")
            candidate_rows.append(base)
            continue
        for field in RANKING_LABEL_FIELDS:
            base[field] = ranking[field]
        left = receptor_by_key[(candidate_id, "8x6b")]
        right = receptor_by_key[(candidate_id, "9e6y")]
        for receptor, values in (("8x6b", left), ("9e6y", right)):
            for field in RECEPTOR_NUMERIC_FIELDS:
                base[f"{receptor}_{field}"] = values[field]
        for field in RECEPTOR_NUMERIC_FIELDS:
            lvalue, rvalue = float(left[field]), float(right[field])
            base[f"dual_mean_{field}"] = 0.5 * (lvalue + rvalue)
            base[f"dual_min_{field}"] = min(lvalue, rvalue)
            base[f"dual_abs_gap_{field}"] = abs(lvalue - rvalue)
        base["dual_pvrig_profile_jsd"] = jensen_shannon(profiles[(candidate_id, "8x6b")], profiles[(candidate_id, "9e6y")])
        candidate_rows.append(base)

    expected_counts = inputs["contract"]["expected_counts"]
    require(len(candidate_rows) == int(expected_counts["candidates"]), "candidate_output_count_invalid")
    require(len(receptor_rows) == 2 * len(candidate_rows), "receptor_output_count_invalid")
    valid_candidate_rows = [row for row in candidate_rows if row["teacher_state"] == VALID_STATE]
    require(len(valid_candidate_rows) == int(expected_counts["analyzable_candidates"]), "valid_candidate_output_count_invalid")
    require(all(math.isfinite(float(row[field])) for row in valid_candidate_rows for field in candidate_fields if field not in {"schema_version", "teacher_state", "candidate_id", "sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode", "technical_reasons"}), "valid_candidate_nonfinite")
    incomplete_rows = [row for row in candidate_rows if row["teacher_state"] == INCOMPLETE_STATE]
    numeric_candidate_fields = [field for field in candidate_fields if field not in {"schema_version", "teacher_state", "candidate_id", "sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode", "technical_reasons"}]
    require(all(row.get(field, "") == "" for row in incomplete_rows for field in numeric_candidate_fields), "incomplete_candidate_numeric_not_empty")

    output_dir.mkdir(parents=True)
    write_gzip_tsv(output_dir / PAIR_OUTPUT, PAIR_FIELDS, pair_rows)
    write_gzip_tsv(output_dir / RECEPTOR_OUTPUT, RECEPTOR_FIELDS, receptor_rows)
    write_gzip_tsv(output_dir / CANDIDATE_OUTPUT, candidate_fields, candidate_rows)
    output_hashes = {
        PAIR_OUTPUT: sha256_file(output_dir / PAIR_OUTPUT),
        RECEPTOR_OUTPUT: sha256_file(output_dir / RECEPTOR_OUTPUT),
        CANDIDATE_OUTPUT: sha256_file(output_dir / CANDIDATE_OUTPUT),
    }
    pose_files_opened = sum(int(row["pose_count"]) for row in job_results)
    excluded_job_count = 2 * len(inputs["incomplete_ids"])
    excluded_raw_success = excluded_job_count - len(inputs["failure_job_ids"])
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "COMPLETE_V4H_STAGE1_CONTACT_TEACHER_EXTRACTION",
        "claim_boundary": CLAIM_BOUNDARY,
        "configuration": {
            "contact_cutoff_angstrom": CONTACT_CUTOFF,
            "top_k": TOP_K,
            "minimum_poses_per_job": MINIMUM_POSES,
            "seed": EXPECTED_SEED,
            "receptors": list(RECEPTORS),
            "pose_rank_weight": "normalized_1_over_log2_rank_plus_1",
            "single_seed_semantics": "pose-frequency soft label; no artificial seed replication",
            "technical_incomplete_semantics": "candidate and both receptor rows retained with empty numeric values; no result or pose opened",
            "workers": workers,
        },
        "inputs": {
            "contract_sha256": sha256_file(Path(inputs["contract_path"])),
            "implementation_sha256": sha256_file(Path(__file__)),
            "terminal_package_hashes": inputs["package_hashes"],
            "canonical_raw_hashes": inputs["raw_hashes"],
        },
        "counts": {
            "stage1_jobs_declared": len(inputs["jobs"]),
            "raw_terminal_counts": inputs["terminal_counts"],
            "candidates": len(candidate_rows),
            "analyzable_candidates": len(valid_candidate_rows),
            "technical_incomplete_candidates": len(incomplete_rows),
            "technical_reason_categories": dict(sorted(inputs["technical_reason_categories"].items())),
            "selected_successful_job_results_opened": len(job_results),
            "excluded_candidate_jobs": excluded_job_count,
            "excluded_raw_success_job_results_not_opened": excluded_raw_success,
            "excluded_failed_job_results_not_opened": len(inputs["failure_job_ids"]),
            "selected_pose_coordinate_files_opened": pose_files_opened,
            "pair_rows": len(pair_rows),
            "receptor_rows": len(receptor_rows),
            "candidate_rows": len(candidate_rows),
        },
        "outputs": {"hashes": output_hashes},
        "read_only_boundary": {
            "canonical_raw_root": str(root),
            "output_outside_canonical_raw_root": True,
            "source_mutation_operations": 0,
            "technical_incomplete_job_results_opened": 0,
            "technical_incomplete_pose_files_opened": 0,
            "native_overlay_rmsd_threshold_changed": False,
            "rescoring_thresholds_changed": False,
        },
    }
    atomic_write(output_dir / AUDIT_OUTPUT, canonical_json(audit))
    output_hashes[AUDIT_OUTPUT] = sha256_file(output_dir / AUDIT_OUTPUT)
    receipt = {
        "schema_version": f"{SCHEMA_VERSION}_receipt",
        "status": audit["status"],
        "claim_boundary": CLAIM_BOUNDARY,
        "contract_sha256": audit["inputs"]["contract_sha256"],
        "implementation_sha256": audit["inputs"]["implementation_sha256"],
        "input_hashes": {**inputs["package_hashes"], **inputs["raw_hashes"]},
        "output_hashes": output_hashes,
        "candidate_rows": len(candidate_rows),
        "valid_candidate_rows": len(valid_candidate_rows),
        "technical_incomplete_candidate_rows": len(incomplete_rows),
        "receptor_rows": len(receptor_rows),
        "pair_rows": len(pair_rows),
        "source_mutation_operations": 0,
        "technical_incomplete_pose_files_opened": 0,
    }
    atomic_write(output_dir / RECEIPT_OUTPUT, canonical_json(receipt))
    return {
        "status": receipt["status"],
        "candidate_rows": len(candidate_rows),
        "valid_candidate_rows": len(valid_candidate_rows),
        "technical_incomplete_candidate_rows": len(incomplete_rows),
        "receptor_rows": len(receptor_rows),
        "pair_rows": len(pair_rows),
        "receipt_sha256": sha256_file(output_dir / RECEIPT_OUTPUT),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--terminal-package", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = extract(
        args.campaign_root,
        args.terminal_package,
        args.contract,
        args.output_dir,
        workers=args.workers,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
