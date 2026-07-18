#!/usr/bin/env python3
"""Extract the preregistered V4-D OPEN_TRAIN multi-seed contact teacher.

Only OPEN_TRAIN job-result JSON and selected pose coordinates are opened.  Shared
aggregate pose/result reports are deliberately not inputs because they also contain
sealed-split contact evidence.  The extractor is read-only with respect to the raw
campaign and writes deterministic, content-addressable outputs to a new directory.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import re
import stat
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


SCHEMA_VERSION = "pvrig_v6_v4d_open226_multi_seed_contact_teacher_v2"
CONTRACT_SCHEMA_VERSION = f"{SCHEMA_VERSION}_contract"
CLAIM_BOUNDARY = (
    "Multi-seed residue-contact supervision derived from frozen independent 8X6B/9E6Y "
    "computational Docking poses; not binding probability, affinity, experimental "
    "competition or blocking, Docking Gold, or final submission evidence."
)
RECEPTORS = ("8x6b", "9e6y")
EXPECTED_SEEDS = (917, 1931, 3253)
ALLOWED_SPLIT = "OPEN_TRAIN"
SEALED_SPLITS = frozenset({"OPEN_DEVELOPMENT", "PROSPECTIVE_COMPUTATIONAL_TEST"})
OVERLAY_RMSD_LIMIT_A = 1.0
TOP_K = 8
MINIMUM_VALID_POSES = 4
CONTACT_CUTOFF_A = 4.5

VALID_STATE = "VALID_DUAL_MULTI_SEED_CONTACT"
PARTIAL_STATE = "VALID_DUAL_MULTI_SEED_PARTIAL_TECHNICAL_REPEAT"

PAIR_OUTPUT = "v4d_open226_multi_seed_pair_contact_teacher_v2.tsv.gz"
RESIDUE_OUTPUT = "v4d_open226_multi_seed_residue_marginal_teacher_v2.tsv.gz"
POSE_INVENTORY_OUTPUT = "v4d_open226_top8_pose_inventory_v2.tsv.gz"
AUDIT_OUTPUT = "EXTRACTION_AUDIT.json"
RECEIPT_OUTPUT = "RUN_RECEIPT.json"

PAIR_FIELDS = (
    "schema_version", "teacher_state", "candidate_id", "sequence_sha256",
    "parent_framework_cluster", "receptor", "vhh_sequence_index", "vhh_aa",
    "pvrig_uniprot_position", "pvrig_aa", "contact_target_mean",
    "contact_target_variance", "contact_uncertainty_weight", "supporting_seed_count",
    "observed_seed_count", "expected_seed_count", "seed_contact_values", "claim_boundary",
)
RESIDUE_FIELDS = (
    "schema_version", "teacher_state", "candidate_id", "sequence_sha256",
    "parent_framework_cluster", "receptor", "vhh_sequence_index", "vhh_aa",
    "contact_marginal_mean", "contact_marginal_variance",
    "contact_marginal_uncertainty_weight", "supporting_seed_count",
    "observed_seed_count", "expected_seed_count", "seed_marginal_values", "claim_boundary",
)
POSE_INVENTORY_FIELDS = (
    "schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster",
    "receptor", "seed", "job_id", "model", "valid_pose_rank", "haddock_score",
    "native_overlay_rmsd_a", "pose_weight", "pose_relative_path", "pose_sha256",
    "size_bytes", "claim_boundary",
)

AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


class ContactTeacherError(RuntimeError):
    """Fail-closed V4-D contact-teacher error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContactTeacherError(message)


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_regular_snapshot(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ContactTeacherError(f"unable_to_open_regular_file:{label}:{path}") from exc
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode), f"not_regular_or_symlink:{label}:{path}")
        blocks: list[bytes] = []
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            blocks.append(block)
        after = os.fstat(descriptor)
        identity = lambda value: (
            value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns
        )
        require(identity(before) == identity(after), f"file_changed_during_read:{label}:{path}")
        raw = b"".join(blocks)
        require(len(raw) == before.st_size, f"file_size_changed_during_read:{label}:{path}")
        return raw
    finally:
        os.close(descriptor)


def strict_json(raw: bytes, label: str) -> dict[str, Any]:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, f"duplicate_json_key:{label}:{key}")
            result[key] = value
        return result

    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContactTeacherError(f"invalid_json:{label}") from exc
    require(isinstance(payload, dict), f"json_not_object:{label}")
    return payload


def read_tsv(raw: bytes, label: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter="\t")
        fields = list(reader.fieldnames or [])
        require(fields and len(fields) == len(set(fields)), f"invalid_tsv_header:{label}")
        rows = [dict(row) for row in reader]
    except UnicodeDecodeError as exc:
        raise ContactTeacherError(f"invalid_utf8_tsv:{label}") from exc
    return fields, rows


def write_gzip_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
                writer.writeheader()
                writer.writerows({field: row.get(field, "") for field in fields} for row in rows)
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(temporary, path)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(canonical_json_bytes(payload))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def path_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    value: Any = mapping
    for key in keys:
        require(isinstance(value, Mapping) and key in value, f"missing_nested_metric:{'.'.join(keys)}")
        value = value[key]
    return value


def finite_float(value: Any, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ContactTeacherError(f"invalid_float:{field}:{value}") from exc
    require(math.isfinite(parsed), f"nonfinite_float:{field}")
    return parsed


def format_float(value: float) -> str:
    require(math.isfinite(value), "attempted_to_format_nonfinite_float")
    return format(value, ".12g")


def population_variance(values: Sequence[float]) -> float:
    require(bool(values), "variance_of_empty_values")
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def uncertainty_weight(variance: float) -> float:
    return 1.0 / (1.0 + 4.0 * variance)


def validate_contract(payload: Mapping[str, Any], root: Path) -> None:
    require(payload.get("schema_version") == CONTRACT_SCHEMA_VERSION, "contract_schema_changed")
    require(payload.get("status") == "FROZEN_PRE_EXTRACTION", "contract_not_frozen_pre_extraction")
    require(Path(str(payload.get("canonical_raw_root", ""))).resolve() == root, "canonical_raw_root_changed")
    require(payload.get("allowed_model_split") == ALLOWED_SPLIT, "allowed_model_split_changed")
    require(set(payload.get("sealed_model_splits") or []) == set(SEALED_SPLITS), "sealed_model_splits_changed")
    definition = payload.get("contact_definition") or {}
    require(tuple(definition.get("receptors") or []) == RECEPTORS, "receptors_changed")
    require(tuple(int(value) for value in definition.get("expected_seeds") or []) == EXPECTED_SEEDS, "expected_seeds_changed")
    require(float(definition.get("native_overlay_max_rmsd_angstrom")) == OVERLAY_RMSD_LIMIT_A, "native_overlay_threshold_changed")
    require(int(definition.get("top_k_after_pose_validity_filter")) == TOP_K, "top_k_changed")
    require(int(definition.get("minimum_valid_poses_per_successful_job")) == MINIMUM_VALID_POSES, "minimum_valid_poses_changed")
    require(float(definition.get("contact_cutoff_angstrom")) == CONTACT_CUTOFF_A, "contact_cutoff_changed")
    require(definition.get("pose_rank_weight") == "normalized_1_over_log2_rank_plus_1", "pose_rank_weight_changed")
    require(definition.get("seed_weighting") == "equal_over_observed_successful_seeds", "seed_weighting_changed")
    require(definition.get("pair_variance") == "population", "pair_variance_changed")
    require(definition.get("uncertainty_weight") == "1/(1+4*variance)", "uncertainty_formula_changed")
    require(
        definition.get("residue_marginal") == "pose_weighted_any_pvrig_contact_then_equal_seed_mean",
        "residue_marginal_definition_changed",
    )
    outputs = payload.get("output_files") or {}
    expected_outputs = {
        "pair": PAIR_OUTPUT, "residue_marginal": RESIDUE_OUTPUT,
        "pose_inventory": POSE_INVENTORY_OUTPUT, "audit": AUDIT_OUTPUT,
        "receipt": RECEIPT_OUTPUT,
    }
    require(dict(outputs) == expected_outputs, "output_file_contract_changed")


def decode_pose_bytes(raw: bytes, path: Path) -> str:
    try:
        content = gzip.decompress(raw) if path.suffix == ".gz" else raw
        return content.decode("ascii", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise ContactTeacherError(f"invalid_pose_encoding:{path}") from exc


def heavy_atom(line: str) -> bool:
    atom_name = line[12:16].strip().upper()
    element = line[76:78].strip().upper() if len(line) >= 78 else ""
    if not element:
        element = "".join(char for char in atom_name if char.isalpha())[:1]
    return element not in {"H", "D"} and not atom_name.startswith(("H", "D"))


def contact_pairs_from_pose_bytes(
    raw: bytes,
    pose_path: Path,
    expected_sequence: str,
    vhh_chain: str,
    pvrig_chain: str,
) -> tuple[set[tuple[int, int]], dict[int, str]]:
    vhh_xyz: list[tuple[float, float, float]] = []
    vhh_atom_keys: list[tuple[int, str, str]] = []
    pvrig_xyz: list[tuple[float, float, float]] = []
    pvrig_positions: list[int] = []
    pvrig_names: dict[int, str] = {}
    vhh_order: list[tuple[int, str, str]] = []
    seen_vhh: set[tuple[int, str, str]] = set()
    for line_number, line in enumerate(decode_pose_bytes(raw, pose_path).splitlines(), start=1):
        if not line.startswith("ATOM  "):
            continue
        require(len(line) >= 54, f"short_atom_record:{pose_path}:{line_number}")
        residue_name = line[17:20].strip().upper()
        if residue_name not in AA3_TO_1 or not heavy_atom(line):
            continue
        chain = line[21:22]
        try:
            residue_number = int(line[22:26])
            insertion_code = line[26:27]
            coordinate = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
        except ValueError as exc:
            raise ContactTeacherError(f"invalid_atom_record:{pose_path}:{line_number}") from exc
        key = (residue_number, insertion_code, residue_name)
        if chain == vhh_chain:
            if key not in seen_vhh:
                seen_vhh.add(key)
                vhh_order.append(key)
            vhh_xyz.append(coordinate)
            vhh_atom_keys.append(key)
        elif chain == pvrig_chain:
            previous = pvrig_names.setdefault(residue_number, residue_name)
            require(previous == residue_name, f"pvrig_residue_identity_conflict:{pose_path}:{residue_number}")
            pvrig_xyz.append(coordinate)
            pvrig_positions.append(residue_number)
    observed_sequence = "".join(AA3_TO_1[key[2]] for key in vhh_order)
    require(observed_sequence == expected_sequence, f"pose_vhh_sequence_mismatch:{pose_path}")
    require(vhh_xyz and pvrig_xyz, f"required_pose_chains_missing:{pose_path}")
    sequence_index = {key: index + 1 for index, key in enumerate(vhh_order)}
    vhh_indices = np.asarray([sequence_index[key] for key in vhh_atom_keys], dtype=np.int32)
    target_indices = np.asarray(pvrig_positions, dtype=np.int32)
    left = np.asarray(vhh_xyz, dtype=np.float64)
    right = np.asarray(pvrig_xyz, dtype=np.float64)
    cutoff_squared = CONTACT_CUTOFF_A * CONTACT_CUTOFF_A
    pairs: set[tuple[int, int]] = set()
    for start in range(0, len(left), 256):
        distances = np.sum((left[start : start + 256, None, :] - right[None, :, :]) ** 2, axis=2)
        for left_index, right_index in np.argwhere(distances <= cutoff_squared):
            pairs.add((int(vhh_indices[start + int(left_index)]), int(target_indices[int(right_index)])))
    return pairs, pvrig_names


def canonical_selected_pose(root: Path, job_id: str, value: Any) -> Path:
    path = Path(str(value))
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    allowed = (root / "runs" / job_id / "haddock_run" / "6_seletopclusts").resolve()
    require(path_within(resolved, allowed), f"selected_pose_outside_job_tree:{job_id}:{path}")
    return resolved


def native_score(scores: Any, receptor: str, job_id: str, model: str) -> Mapping[str, Any]:
    require(isinstance(scores, list), f"pose_reference_scores_not_list:{job_id}:{model}")
    by_reference: dict[str, Mapping[str, Any]] = {}
    for score in scores:
        require(isinstance(score, Mapping), f"pose_reference_score_not_object:{job_id}:{model}")
        reference = str(score.get("reference_id", "")).lower()
        require(reference in RECEPTORS, f"invalid_scoring_reference:{job_id}:{model}:{reference}")
        require(reference not in by_reference, f"duplicate_scoring_reference:{job_id}:{model}:{reference}")
        by_reference[reference] = score
    require(set(by_reference) == set(RECEPTORS), f"pose_not_exact_two_reference:{job_id}:{model}")
    return by_reference[receptor]


def process_job(task: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(str(task["root"])).resolve()
    job = dict(task["job"])
    candidate = dict(task["candidate"])
    job_id = job["job_id"]
    result_path = root / "results" / job_id / "job_result.json"
    result_raw = read_regular_snapshot(result_path, f"open_train_job_result:{job_id}")
    payload = strict_json(result_raw, f"open_train_job_result:{job_id}")
    require(payload.get("state") == "SUCCESS", f"open_train_job_not_success:{job_id}")
    identities = {
        "job_id": job_id,
        "job_hash": job["job_hash"],
        "entity_type": "candidate",
        "entity_id": candidate["candidate_id"],
        "dock_conformation": job["conformation"],
        "seed": int(job["seed"]),
        "protocol_core_sha256": job["protocol_core_sha256"],
    }
    for field, expected in identities.items():
        observed = payload.get(field)
        if field == "seed":
            try:
                observed = int(observed)
            except (TypeError, ValueError) as exc:
                raise ContactTeacherError(f"job_result_seed_invalid:{job_id}") from exc
        require(observed == expected, f"job_result_identity_mismatch:{job_id}:{field}")

    selected_models = payload.get("selected_models")
    require(isinstance(selected_models, list), f"selected_models_not_list:{job_id}")
    canonical_by_name: dict[str, Path] = {}
    for value in selected_models:
        path = canonical_selected_pose(root, job_id, value)
        require(path.name not in canonical_by_name, f"duplicate_selected_model:{job_id}:{path.name}")
        canonical_by_name[path.name] = path
    require(len(canonical_by_name) >= MINIMUM_VALID_POSES, f"too_few_selected_models:{job_id}")
    require(int(payload.get("selected_model_count")) == len(canonical_by_name), f"selected_model_count_mismatch:{job_id}")

    scored: list[tuple[float, str, float, Path]] = []
    seen_scores: set[str] = set()
    invalid_count = 0
    for pose in payload.get("pose_scores") or []:
        require(isinstance(pose, Mapping), f"pose_score_not_object:{job_id}")
        model = Path(str(pose.get("pose", ""))).name
        require(model in canonical_by_name, f"scored_model_not_selected:{job_id}:{model}")
        require(model not in seen_scores, f"duplicate_scored_model:{job_id}:{model}")
        seen_scores.add(model)
        haddock_score = finite_float(nested(pose, "haddock_io", "score"), "haddock_score")
        native = native_score(pose.get("scores"), job["conformation"], job_id, model)
        overlay = finite_float(nested(native, "overlay", "t_ca_rmsd_a"), "native_overlay_rmsd_a")
        if overlay > OVERLAY_RMSD_LIMIT_A:
            invalid_count += 1
            continue
        scored.append((haddock_score, model, overlay, canonical_by_name[model]))
    require(seen_scores == set(canonical_by_name), f"selected_model_score_closure_failed:{job_id}")
    scored.sort(key=lambda item: (item[0], item[1]))
    valid_after_filter = len(scored)
    require(valid_after_filter >= MINIMUM_VALID_POSES, f"valid_poses_below_minimum:{job_id}:{valid_after_filter}")
    selected = scored[:TOP_K]
    raw_weights = [1.0 / math.log2(rank + 1.0) for rank in range(1, len(selected) + 1)]
    total_weight = sum(raw_weights)
    weights = [value / total_weight for value in raw_weights]

    pair_values: defaultdict[tuple[int, int], float] = defaultdict(float)
    marginal_values: defaultdict[int, float] = defaultdict(float)
    pvrig_names: dict[int, str] = {}
    inventory: list[dict[str, Any]] = []
    for rank, (weight, (score, model, overlay, pose_path)) in enumerate(zip(weights, selected), start=1):
        pose_raw = read_regular_snapshot(pose_path, f"open_train_pose:{job_id}:{model}")
        pairs, names = contact_pairs_from_pose_bytes(
            pose_raw, pose_path, candidate["sequence"], job["vhh_chain"], job["receptor_chain"]
        )
        for pair in pairs:
            pair_values[pair] += weight
        for residue_index in {pair[0] for pair in pairs}:
            marginal_values[residue_index] += weight
        for position, name in names.items():
            previous = pvrig_names.setdefault(position, name)
            require(previous == name, f"pvrig_identity_conflict_across_poses:{job_id}:{position}")
        inventory.append({
            "schema_version": SCHEMA_VERSION,
            "candidate_id": candidate["candidate_id"],
            "sequence_sha256": candidate["sequence_sha256"],
            "parent_framework_cluster": candidate["parent_framework_cluster"],
            "receptor": job["conformation"],
            "seed": int(job["seed"]),
            "job_id": job_id,
            "model": model,
            "valid_pose_rank": rank,
            "haddock_score": format_float(score),
            "native_overlay_rmsd_a": format_float(overlay),
            "pose_weight": format_float(weight),
            "pose_relative_path": str(pose_path.relative_to(root)),
            "pose_sha256": sha256_bytes(pose_raw),
            "size_bytes": len(pose_raw),
            "claim_boundary": CLAIM_BOUNDARY,
        })
    return {
        "candidate_id": candidate["candidate_id"],
        "receptor": job["conformation"],
        "seed": int(job["seed"]),
        "job_id": job_id,
        "job_result_sha256": sha256_bytes(result_raw),
        "selected_before_filter": len(canonical_by_name),
        "invalid_native_overlay": invalid_count,
        "valid_after_filter": valid_after_filter,
        "top_k_used": len(selected),
        "pair_values": dict(pair_values),
        "marginal_values": dict(marginal_values),
        "pvrig_names": pvrig_names,
        "inventory": inventory,
    }


def aggregate_candidate_receptor(
    candidate: Mapping[str, str], receptor: str, seed_results: Sequence[Mapping[str, Any]], state: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_seed = {int(result["seed"]): result for result in seed_results}
    require(len(by_seed) == len(seed_results), f"duplicate_seed_result:{candidate['candidate_id']}:{receptor}")
    observed_seeds = sorted(by_seed)
    require(set(observed_seeds) <= set(EXPECTED_SEEDS), f"unexpected_observed_seed:{candidate['candidate_id']}:{receptor}")
    require(len(observed_seeds) >= 2, f"fewer_than_two_observed_seeds:{candidate['candidate_id']}:{receptor}")
    pvrig_names: dict[int, str] = {}
    for result in seed_results:
        for position, name in result["pvrig_names"].items():
            position = int(position)
            previous = pvrig_names.setdefault(position, str(name))
            require(previous == name, f"pvrig_identity_conflict_across_seeds:{candidate['candidate_id']}:{receptor}:{position}")

    pair_keys = sorted({tuple(pair) for result in seed_results for pair in result["pair_values"]})
    pair_rows: list[dict[str, Any]] = []
    for vhh_index, pvrig_position in pair_keys:
        values = [float(by_seed[seed]["pair_values"].get((vhh_index, pvrig_position), 0.0)) for seed in observed_seeds]
        mean = sum(values) / len(values)
        variance = population_variance(values)
        require(mean > 0.0, "union_pair_has_zero_mean")
        pair_rows.append({
            "schema_version": SCHEMA_VERSION,
            "teacher_state": state,
            "candidate_id": candidate["candidate_id"],
            "sequence_sha256": candidate["sequence_sha256"],
            "parent_framework_cluster": candidate["parent_framework_cluster"],
            "receptor": receptor,
            "vhh_sequence_index": vhh_index,
            "vhh_aa": candidate["sequence"][vhh_index - 1],
            "pvrig_uniprot_position": pvrig_position,
            "pvrig_aa": AA3_TO_1[pvrig_names[pvrig_position]],
            "contact_target_mean": format_float(mean),
            "contact_target_variance": format_float(variance),
            "contact_uncertainty_weight": format_float(uncertainty_weight(variance)),
            "supporting_seed_count": sum(value > 0.0 for value in values),
            "observed_seed_count": len(observed_seeds),
            "expected_seed_count": len(EXPECTED_SEEDS),
            "seed_contact_values": ";".join(f"{seed}:{format_float(value)}" for seed, value in zip(observed_seeds, values)),
            "claim_boundary": CLAIM_BOUNDARY,
        })

    residue_rows: list[dict[str, Any]] = []
    for vhh_index, aa in enumerate(candidate["sequence"], start=1):
        values = [float(by_seed[seed]["marginal_values"].get(vhh_index, 0.0)) for seed in observed_seeds]
        mean = sum(values) / len(values)
        variance = population_variance(values)
        residue_rows.append({
            "schema_version": SCHEMA_VERSION,
            "teacher_state": state,
            "candidate_id": candidate["candidate_id"],
            "sequence_sha256": candidate["sequence_sha256"],
            "parent_framework_cluster": candidate["parent_framework_cluster"],
            "receptor": receptor,
            "vhh_sequence_index": vhh_index,
            "vhh_aa": aa,
            "contact_marginal_mean": format_float(mean),
            "contact_marginal_variance": format_float(variance),
            "contact_marginal_uncertainty_weight": format_float(uncertainty_weight(variance)),
            "supporting_seed_count": sum(value > 0.0 for value in values),
            "observed_seed_count": len(observed_seeds),
            "expected_seed_count": len(EXPECTED_SEEDS),
            "seed_marginal_values": ";".join(f"{seed}:{format_float(value)}" for seed, value in zip(observed_seeds, values)),
            "claim_boundary": CLAIM_BOUNDARY,
        })
    return pair_rows, residue_rows


def extract(root: Path, contract_path: Path, output_dir: Path, *, workers: int = 1) -> dict[str, Any]:
    root = root.resolve()
    contract_path = contract_path.resolve()
    output_dir = output_dir.resolve()
    require(workers >= 1, "workers_must_be_positive")
    require(root.is_dir() and not root.is_symlink(), f"canonical_raw_root_missing_or_symlink:{root}")
    require(not output_dir.exists(), f"output_dir_already_exists:{output_dir}")
    contract_raw = read_regular_snapshot(contract_path, "contract")
    contract = strict_json(contract_raw, "contract")
    validate_contract(contract, root)

    candidates_path = root / "inputs/candidates_290.tsv"
    jobs_path = root / "manifests/docking_jobs.tsv"
    protocol_core_lock_path = root / "PROTOCOL_CORE_LOCK.json"
    protocol_lock_path = root / "PROTOCOL_LOCK.json"
    candidates_raw = read_regular_snapshot(candidates_path, "candidates")
    jobs_raw = read_regular_snapshot(jobs_path, "docking_jobs")
    protocol_core_lock_raw = read_regular_snapshot(protocol_core_lock_path, "protocol_core_lock")
    protocol_lock_raw = read_regular_snapshot(protocol_lock_path, "protocol_lock")
    expected_hashes = contract.get("expected_sha256") or {}
    require(sha256_bytes(candidates_raw) == expected_hashes.get("candidates"), "candidates_sha256_mismatch")
    require(sha256_bytes(jobs_raw) == expected_hashes.get("docking_jobs"), "docking_jobs_sha256_mismatch")
    require(
        sha256_bytes(protocol_core_lock_raw) == expected_hashes.get("protocol_core_lock"),
        "protocol_core_lock_sha256_mismatch",
    )
    require(sha256_bytes(protocol_lock_raw) == expected_hashes.get("protocol_lock"), "protocol_lock_sha256_mismatch")
    candidate_fields, candidate_rows = read_tsv(candidates_raw, "candidates")
    job_fields, job_rows = read_tsv(jobs_raw, "docking_jobs")
    candidate_required = {"candidate_id", "sequence_sha256", "sequence", "parent_framework_cluster", "model_split"}
    job_required = {
        "job_id", "entity_type", "entity_id", "conformation", "seed", "sequence_sha256",
        "vhh_chain", "receptor_chain", "protocol_core_sha256", "job_hash",
    }
    require(candidate_required <= set(candidate_fields), "candidate_fields_missing")
    require(job_required <= set(job_fields), "job_fields_missing")

    candidates: dict[str, dict[str, str]] = {}
    sealed_candidate_ids: set[str] = set()
    for row in candidate_rows:
        split = row["model_split"]
        if split in SEALED_SPLITS:
            sealed_candidate_ids.add(row["candidate_id"])
            continue
        if split != ALLOWED_SPLIT:
            continue
        candidate_id = row["candidate_id"]
        require(candidate_id and candidate_id not in candidates, f"duplicate_open_train_candidate:{candidate_id}")
        sequence = row["sequence"].strip().upper()
        require(sequence and all(aa in set(AA3_TO_1.values()) for aa in sequence), f"invalid_candidate_sequence:{candidate_id}")
        require(sha256_bytes(sequence.encode("ascii")) == row["sequence_sha256"], f"candidate_sequence_hash_mismatch:{candidate_id}")
        copied = dict(row)
        copied["sequence"] = sequence
        candidates[candidate_id] = copied

    expected_counts = contract.get("expected_counts") or {}
    require(len(candidates) == int(expected_counts.get("open_train_candidates")), "open_train_candidate_count_mismatch")
    require(
        len({row["parent_framework_cluster"] for row in candidates.values()}) == int(expected_counts.get("open_train_parent_clusters")),
        "open_train_parent_cluster_count_mismatch",
    )

    jobs: dict[str, dict[str, str]] = {}
    grid: dict[tuple[str, str, int], str] = {}
    for row in job_rows:
        if row["entity_type"] != "candidate" or row["entity_id"] not in candidates:
            continue
        job_id = row["job_id"]
        require(job_id and re.fullmatch(r"[A-Za-z0-9_.-]+", job_id), f"unsafe_open_train_job_id:{job_id}")
        require(job_id not in jobs, f"duplicate_open_train_job_id:{job_id}")
        receptor = row["conformation"].lower()
        require(receptor in RECEPTORS, f"invalid_open_train_receptor:{job_id}:{receptor}")
        try:
            seed = int(row["seed"])
        except ValueError as exc:
            raise ContactTeacherError(f"invalid_open_train_seed:{job_id}") from exc
        require(seed in EXPECTED_SEEDS, f"unexpected_open_train_seed:{job_id}:{seed}")
        key = (row["entity_id"], receptor, seed)
        require(key not in grid, f"duplicate_candidate_receptor_seed:{key}")
        candidate = candidates[row["entity_id"]]
        require(row["sequence_sha256"] == candidate["sequence_sha256"], f"job_sequence_hash_mismatch:{job_id}")
        require(row["vhh_chain"] == "A" and row["receptor_chain"] == "T", f"job_chain_contract_mismatch:{job_id}")
        copied = dict(row)
        copied["conformation"] = receptor
        jobs[job_id] = copied
        grid[key] = job_id
    require(len(jobs) == int(expected_counts.get("scheduled_open_train_jobs")), "scheduled_open_train_job_count_mismatch")
    for candidate_id in candidates:
        for receptor in RECEPTORS:
            for seed in EXPECTED_SEEDS:
                require((candidate_id, receptor, seed) in grid, f"open_train_grid_incomplete:{candidate_id}:{receptor}:{seed}")

    failed_job_ids = set(contract.get("expected_failed_job_ids") or [])
    require(len(failed_job_ids) == int(expected_counts.get("failed_open_train_jobs")), "failed_job_id_count_mismatch")
    require(failed_job_ids <= set(jobs), "failed_job_not_in_open_train_grid")
    for failed_job_id in failed_job_ids:
        require(not (root / "results" / failed_job_id / "job_result.json").is_file(), f"frozen_failed_job_unexpectedly_has_result:{failed_job_id}")

    tasks = [
        {"root": str(root), "job": jobs[job_id], "candidate": candidates[jobs[job_id]["entity_id"]]}
        for job_id in sorted(set(jobs) - failed_job_ids)
    ]
    require(len(tasks) == int(expected_counts.get("successful_open_train_jobs")), "successful_task_count_mismatch")
    if workers == 1:
        results = [process_job(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(process_job, tasks, chunksize=1))

    result_by_candidate_receptor: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    inventory_rows: list[dict[str, Any]] = []
    result_inventory: list[tuple[str, str]] = []
    selected_before = invalid_count = valid_after = top_k_used = 0
    for result in results:
        result_by_candidate_receptor[(result["candidate_id"], result["receptor"])].append(result)
        inventory_rows.extend(result["inventory"])
        result_inventory.append((result["job_id"], result["job_result_sha256"]))
        selected_before += int(result["selected_before_filter"])
        invalid_count += int(result["invalid_native_overlay"])
        valid_after += int(result["valid_after_filter"])
        top_k_used += int(result["top_k_used"])
    require(selected_before == int(expected_counts.get("selected_native_poses_before_filter")), "selected_pose_count_before_filter_mismatch")
    require(invalid_count == int(expected_counts.get("invalid_native_overlay_poses")), "invalid_native_overlay_pose_count_mismatch")
    require(valid_after == int(expected_counts.get("valid_native_poses_after_filter")), "valid_pose_count_after_filter_mismatch")
    require(top_k_used == int(expected_counts.get("top_k_pose_inventory_rows")), "top_k_pose_inventory_count_mismatch")

    complete_candidates: set[str] = set()
    partial_candidates: set[str] = set()
    observed_seed_counts: dict[tuple[str, str], int] = {}
    for candidate_id in candidates:
        counts = []
        for receptor in RECEPTORS:
            observed = len(result_by_candidate_receptor[(candidate_id, receptor)])
            require(2 <= observed <= len(EXPECTED_SEEDS), f"observed_seed_count_out_of_contract:{candidate_id}:{receptor}:{observed}")
            counts.append(observed)
            observed_seed_counts[(candidate_id, receptor)] = observed
        if counts == [3, 3]:
            complete_candidates.add(candidate_id)
        else:
            partial_candidates.add(candidate_id)
    require(len(complete_candidates) == int(expected_counts.get("complete_three_seed_candidates")), "complete_candidate_count_mismatch")
    require(len(partial_candidates) == int(expected_counts.get("partial_seed_candidates")), "partial_candidate_count_mismatch")
    expected_partial = contract.get("expected_partial_candidate") or {}
    if partial_candidates:
        require(
            partial_candidates == {str(expected_partial.get("candidate_id", ""))},
            "partial_candidate_identity_mismatch",
        )
        partial_id = next(iter(partial_candidates))
        for receptor in RECEPTORS:
            observed = sorted(
                int(result["seed"])
                for result in result_by_candidate_receptor[(partial_id, receptor)]
            )
            require(
                observed == [int(value) for value in expected_partial.get(f"observed_seeds_{receptor}", [])],
                f"partial_candidate_seed_identity_mismatch:{receptor}",
            )

    pair_rows: list[dict[str, Any]] = []
    residue_rows: list[dict[str, Any]] = []
    for candidate_id in sorted(candidates):
        candidate = candidates[candidate_id]
        state = PARTIAL_STATE if candidate_id in partial_candidates else VALID_STATE
        for receptor in RECEPTORS:
            pairs, residues = aggregate_candidate_receptor(
                candidate, receptor, result_by_candidate_receptor[(candidate_id, receptor)], state
            )
            pair_rows.extend(pairs)
            residue_rows.extend(residues)
    pair_rows.sort(key=lambda row: (
        row["candidate_id"], RECEPTORS.index(row["receptor"]), int(row["vhh_sequence_index"]), int(row["pvrig_uniprot_position"])
    ))
    residue_rows.sort(key=lambda row: (
        row["candidate_id"], RECEPTORS.index(row["receptor"]), int(row["vhh_sequence_index"])
    ))
    inventory_rows.sort(key=lambda row: (
        row["candidate_id"], RECEPTORS.index(row["receptor"]), int(row["seed"]), int(row["valid_pose_rank"]), row["model"]
    ))
    require(
        len(residue_rows) == int(expected_counts.get("residue_marginal_rows")),
        "residue_marginal_row_count_mismatch",
    )
    max_pair_by_residue: defaultdict[tuple[str, str, int], float] = defaultdict(float)
    for row in pair_rows:
        key = (str(row["candidate_id"]), str(row["receptor"]), int(row["vhh_sequence_index"]))
        max_pair_by_residue[key] = max(max_pair_by_residue[key], float(row["contact_target_mean"]))
    for row in residue_rows:
        key = (str(row["candidate_id"]), str(row["receptor"]), int(row["vhh_sequence_index"]))
        require(
            float(row["contact_marginal_mean"]) + 1e-10 >= max_pair_by_residue[key],
            f"any_contact_marginal_below_pair_target:{key}",
        )

    output_dir.mkdir(parents=True, exist_ok=False)
    write_gzip_tsv(output_dir / PAIR_OUTPUT, PAIR_FIELDS, pair_rows)
    write_gzip_tsv(output_dir / RESIDUE_OUTPUT, RESIDUE_FIELDS, residue_rows)
    write_gzip_tsv(output_dir / POSE_INVENTORY_OUTPUT, POSE_INVENTORY_FIELDS, inventory_rows)
    output_hashes = {
        "pair_sha256": sha256_bytes(read_regular_snapshot(output_dir / PAIR_OUTPUT, "pair_output")),
        "residue_marginal_sha256": sha256_bytes(read_regular_snapshot(output_dir / RESIDUE_OUTPUT, "residue_output")),
        "pose_inventory_sha256": sha256_bytes(read_regular_snapshot(output_dir / POSE_INVENTORY_OUTPUT, "pose_inventory_output")),
    }
    job_result_inventory_payload = "".join(f"{sha}  {job_id}\n" for job_id, sha in sorted(result_inventory)).encode("utf-8")
    audit = {
        "schema_version": f"{SCHEMA_VERSION}_audit",
        "status": "PASS_V4D_OPEN_TRAIN_MULTI_SEED_CONTACT_CLOSURE",
        "claim_boundary": CLAIM_BOUNDARY,
        "configuration": {
            "allowed_model_split": ALLOWED_SPLIT,
            "receptors": list(RECEPTORS),
            "expected_seeds": list(EXPECTED_SEEDS),
            "native_overlay_max_rmsd_angstrom": OVERLAY_RMSD_LIMIT_A,
            "top_k_after_pose_validity_filter": TOP_K,
            "minimum_valid_poses_per_successful_job": MINIMUM_VALID_POSES,
            "contact_cutoff_angstrom": CONTACT_CUTOFF_A,
            "pose_rank_weight": "normalized_1_over_log2_rank_plus_1",
            "seed_weighting": "equal_over_observed_successful_seeds",
            "pair_variance": "population",
            "uncertainty_weight": "1/(1+4*variance)",
            "residue_marginal": "pose_weighted_any_pvrig_contact_then_equal_seed_mean",
        },
        "counts": {
            "teacher_candidates": len(candidates),
            "teacher_parent_clusters": len({row["parent_framework_cluster"] for row in candidates.values()}),
            "scheduled_open_train_jobs": len(jobs),
            "successful_open_train_jobs": len(results),
            "failed_open_train_jobs": len(failed_job_ids),
            "complete_three_seed_candidates": len(complete_candidates),
            "partial_seed_candidates": len(partial_candidates),
            "selected_native_poses_before_filter": selected_before,
            "invalid_native_overlay_poses": invalid_count,
            "valid_native_poses_after_filter": valid_after,
            "pose_inventory_rows": len(inventory_rows),
            "pair_rows": len(pair_rows),
            "residue_marginal_rows": len(residue_rows),
            "zero_imputed_failed_seeds": 0,
        },
        "observed_seed_count_distribution": dict(sorted(Counter(observed_seed_counts.values()).items())),
        "failed_job_ids": sorted(failed_job_ids),
        "partial_candidate_ids": sorted(partial_candidates),
        "sealed_boundary": {
            "sealed_model_splits": sorted(SEALED_SPLITS),
            "sealed_candidate_metadata_rows_seen": len(sealed_candidate_ids),
            "sealed_result_files_opened": 0,
            "sealed_pose_files_opened": 0,
            "shared_job_results_tsv_opened": 0,
            "shared_pose_scores_tsv_opened": 0,
        },
        "source": {
            "canonical_raw_root": str(root),
            "contract_sha256": sha256_bytes(contract_raw),
            "candidates_sha256": sha256_bytes(candidates_raw),
            "docking_jobs_sha256": sha256_bytes(jobs_raw),
            "protocol_core_lock_sha256": sha256_bytes(protocol_core_lock_raw),
            "protocol_lock_sha256": sha256_bytes(protocol_lock_raw),
            "open_train_job_result_inventory_sha256": sha256_bytes(job_result_inventory_payload),
            "source_mutation_operations": 0,
        },
        "outputs": output_hashes,
    }
    atomic_json(output_dir / AUDIT_OUTPUT, audit)
    receipt = {
        "schema_version": f"{SCHEMA_VERSION}_receipt",
        "status": "COMPLETE_V4D_OPEN226_MULTI_SEED_CONTACT_TEACHER_V2",
        "claim_boundary": CLAIM_BOUNDARY,
        "counts": audit["counts"],
        "sealed_boundary": audit["sealed_boundary"],
        "source": audit["source"],
        "outputs": {
            **output_hashes,
            "audit_sha256": sha256_bytes(read_regular_snapshot(output_dir / AUDIT_OUTPUT, "audit_output")),
        },
    }
    atomic_json(output_dir / RECEIPT_OUTPUT, receipt)
    return receipt


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--raw-root", type=Path, required=True)
    value.add_argument("--contract", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--workers", type=int, default=8)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    receipt = extract(args.raw_root, args.contract, args.output_dir, workers=args.workers)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
