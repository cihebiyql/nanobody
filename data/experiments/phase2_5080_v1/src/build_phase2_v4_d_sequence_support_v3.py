#!/usr/bin/env python3
"""Support V3 lock verifier and label-free domain-classification core.

The production preregistration is immutable and no Docking or experimental
label path is accepted.  This first implementation validates the complete
frozen input closure and provides the same-neighbor/domain/null-gate logic used
by synthetic tests.  Real ESM2/contact recomputation for null sequences remains
fail-closed until a separately reviewed materialization adapter is added.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "phase2_v4_d_sequence_support_v3_preregistration_v1"
LOCK_STATUS = "FROZEN_LABEL_FREE_BEFORE_SUPPORT_V3_PRODUCTION_CALCULATION"
EXPECTED_PREREGISTRATION_SHA256 = (
    "72dc6adc1e3404c65304d489b303f6d7ba6a08d3edd626518dbcfc74c34c186a"
)
EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PREREGISTRATION = (
    EXPERIMENT_ROOT / "audits/phase2_v4_d_sequence_support_v3_preregistration.json"
)

REQUIRED_INPUTS = {
    "candidate_pool",
    "v4_d_split_manifest",
    "esm2_residue_cache_manifest",
    "cdr_masks",
    "contact_feature_release_receipt",
    "contact_feature_schema",
}
REQUIRED_CHANNELS = (
    "full_esm_cosine",
    "cdr_esm_cosine",
    "cdr1_edit",
    "cdr2_edit",
    "cdr3_edit",
    "cdr_2mer_cosine",
    "cdr_3mer_cosine",
    "contact_euclidean",
)
NULL_GATE_TARGETS = {
    "cdr_composition_shuffle": ("IN_DOMAIN", "in_domain_fraction_maximum"),
    "cross_parent_cdr_graft": ("IN_DOMAIN", "in_domain_fraction_maximum"),
    "channel_splice": ("IN_DOMAIN", "in_domain_fraction_maximum"),
    "unseen_parent_chimera": ("NEAR_DOMAIN", "near_domain_fraction_maximum"),
}
FORBIDDEN_FEATURE_COLUMNS = {
    "r_8x6b",
    "r_9e6y",
    "r_dual_mean",
    "r_dual_min",
    "r_dual_gap",
    "teacher_uncertainty",
    "geometry_tier",
    "docking_label",
    "experimental_label",
    "binding_label",
    "blocking_label",
}
CONSUMED_CANDIDATE_FIELDS = {
    "candidate_id",
    "vhh_sequence",
    "sequence_sha256",
    "parent_framework_cluster",
    "cdr1_after",
    "cdr2_after",
    "cdr3_after",
}


class SupportV3Error(RuntimeError):
    """Raised when a frozen contract or support invariant is violated."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sequence_sha256(sequence: str) -> str:
    return sha256_bytes(sequence.encode("ascii"))


def normalize_sequence(value: str, label: str) -> str:
    sequence = "".join(str(value).split()).upper()
    if not sequence or set(sequence) - set("ACDEFGHIKLMNPQRSTVWY"):
        raise SupportV3Error(f"invalid_sequence:{label}")
    return sequence


def read_table(path: Path, delimiter: str) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    if not fields:
        raise SupportV3Error(f"empty_table_header:{path}")
    return rows, fields


def require_fields(fields: Iterable[str], required: Iterable[str], label: str) -> None:
    missing = sorted(set(required) - set(fields))
    if missing:
        raise SupportV3Error(f"missing_fields:{label}:{','.join(missing)}")


def validate_no_label_features(fields: Iterable[str], label: str) -> None:
    forbidden = sorted({field.lower() for field in fields} & FORBIDDEN_FEATURE_COLUMNS)
    if forbidden:
        raise SupportV3Error(f"forbidden_label_feature_columns:{label}:{','.join(forbidden)}")


def resolve_locked_path(repo_root: Path, relative_path: str) -> Path:
    raw = Path(relative_path)
    if raw.is_absolute():
        raise SupportV3Error(f"frozen_input_path_must_be_relative:{relative_path}")
    root = repo_root.resolve()
    resolved = (root / raw).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SupportV3Error(f"frozen_input_path_escapes_repo:{relative_path}") from exc
    return resolved


def resolve_recorded_path(repo_root: Path, recorded: str) -> Path:
    path = Path(recorded)
    if path.is_file():
        return path
    parts = path.parts
    if "experiments" in parts:
        index = parts.index("experiments")
        fallback = (repo_root / Path(*parts[index:])).resolve()
        if fallback.is_file():
            return fallback
    raise SupportV3Error(f"recorded_path_missing:{recorded}")


def verify_locked_path(path: Path, expected_sha256: str, label: str) -> str:
    if not path.is_file():
        raise SupportV3Error(f"locked_input_missing:{label}:{path}")
    observed = sha256_file(path)
    if observed != expected_sha256:
        raise SupportV3Error(
            f"locked_input_sha256_mismatch:{label}:{observed}:{expected_sha256}"
        )
    return observed


def load_preregistration(
    path: Path = DEFAULT_PREREGISTRATION,
    *,
    expected_sha256: str = EXPECTED_PREREGISTRATION_SHA256,
) -> dict[str, Any]:
    verify_locked_path(path, expected_sha256, "preregistration")
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SupportV3Error(f"invalid_preregistration_json:{path}") from exc
    if lock.get("schema_version") != SCHEMA_VERSION or lock.get("status") != LOCK_STATUS:
        raise SupportV3Error("preregistration_schema_or_status_mismatch")
    if set(lock.get("frozen_inputs", {})) != REQUIRED_INPUTS:
        raise SupportV3Error("preregistration_frozen_input_set_mismatch")
    if lock.get("reference_contract", {}).get("reference_split") != "OPEN_TRAIN only":
        raise SupportV3Error("preregistration_reference_split_mismatch")
    if lock.get("null_controls", {}).get("null_generation_label_access") is not False:
        raise SupportV3Error("preregistration_null_label_access_not_false")
    if lock.get("decision_policy", {}).get("all_gates_required") is not True:
        raise SupportV3Error("preregistration_all_gates_not_required")
    if set(lock.get("hard_gates", {})) != {
        "nested_validation",
        "deployment_coverage",
        *NULL_GATE_TARGETS,
    }:
        raise SupportV3Error("preregistration_hard_gate_set_mismatch")
    expected_outputs = {
        "candidate7087_sequence_support_v3.csv",
        "candidate7087_sequence_support_v3.audit.json",
        "candidate7087_sequence_support_v3.receipt.json",
    }
    if set(lock.get("publication_contract", {}).get("required_outputs", [])) != expected_outputs:
        raise SupportV3Error("preregistration_output_set_mismatch")
    return lock


def _unique_map(rows: Sequence[Mapping[str, str]], key: str, label: str) -> dict[str, Mapping[str, str]]:
    output: dict[str, Mapping[str, str]] = {}
    for row in rows:
        value = row.get(key, "")
        if not value or value in output:
            raise SupportV3Error(f"missing_or_duplicate_key:{label}:{value}")
        output[value] = row
    return output


def _validate_snapshot_records(repo_root: Path, snapshot: Mapping[str, Any]) -> None:
    if not snapshot:
        raise SupportV3Error("contact_receipt_input_snapshot_empty")
    for label, record in sorted(snapshot.items()):
        if not isinstance(record, Mapping):
            raise SupportV3Error(f"contact_snapshot_record_invalid:{label}")
        path = resolve_recorded_path(repo_root, str(record.get("path", "")))
        verify_locked_path(path, str(record.get("sha256", "")), f"contact_snapshot:{label}")
        expected_size = int(record.get("size_bytes", -1))
        if path.stat().st_size != expected_size:
            raise SupportV3Error(f"contact_snapshot_size_mismatch:{label}")


def validate_frozen_inputs(lock: Mapping[str, Any], repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Validate every preregistered input without materializing support scores."""

    inputs = lock["frozen_inputs"]
    resolved: dict[str, Path] = {}
    for label, record in inputs.items():
        path = resolve_locked_path(repo_root, str(record["path"]))
        verify_locked_path(path, str(record["sha256"]), label)
        resolved[label] = path

    candidate_rows, candidate_fields = read_table(resolved["candidate_pool"], ",")
    require_fields(candidate_fields, CONSUMED_CANDIDATE_FIELDS, "candidate_pool")
    if len(candidate_rows) != int(inputs["candidate_pool"]["rows"]):
        raise SupportV3Error("candidate_pool_row_count_mismatch")
    candidates = _unique_map(candidate_rows, "candidate_id", "candidate_pool")
    candidate_by_sha: dict[str, Mapping[str, str]] = {}
    for candidate_id, row in candidates.items():
        sequence = normalize_sequence(row["vhh_sequence"], candidate_id)
        digest = sequence_sha256(sequence)
        if row["sequence_sha256"] != digest or digest in candidate_by_sha:
            raise SupportV3Error(f"candidate_sequence_hash_or_uniqueness_mismatch:{candidate_id}")
        candidate_by_sha[digest] = row

    split_rows, split_fields = read_table(resolved["v4_d_split_manifest"], "\t")
    require_fields(
        split_fields,
        {"candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster", "model_split"},
        "v4_d_split_manifest",
    )
    if len(split_rows) != int(inputs["v4_d_split_manifest"]["rows"]):
        raise SupportV3Error("split_manifest_row_count_mismatch")
    split_by_id = _unique_map(split_rows, "candidate_id", "v4_d_split_manifest")
    open_train = [row for row in split_rows if row["model_split"] == "OPEN_TRAIN"]
    if len(open_train) != int(inputs["v4_d_split_manifest"]["open_train_rows"]):
        raise SupportV3Error("open_train_row_count_mismatch")
    if len({row["parent_framework_cluster"] for row in open_train}) != int(
        inputs["v4_d_split_manifest"]["open_train_parent_clusters"]
    ):
        raise SupportV3Error("open_train_parent_count_mismatch")
    for candidate_id, row in split_by_id.items():
        source = candidates.get(candidate_id)
        if source is None:
            raise SupportV3Error(f"split_candidate_missing_from_pool:{candidate_id}")
        sequence = normalize_sequence(row["sequence"], f"split:{candidate_id}")
        if (
            row["sequence_sha256"] != sequence_sha256(sequence)
            or row["sequence_sha256"] != source["sequence_sha256"]
            or row["parent_framework_cluster"] != source["parent_framework_cluster"]
        ):
            raise SupportV3Error(f"split_candidate_identity_mismatch:{candidate_id}")

    mask_rows, mask_fields = read_table(resolved["cdr_masks"], ",")
    require_fields(
        mask_fields,
        {"sequence_hash", "vhh_seq", "cdr1_seq", "cdr2_seq", "cdr3_seq", "status"},
        "cdr_masks",
    )
    validate_no_label_features(mask_fields, "cdr_masks")
    mask_by_sha = _unique_map(mask_rows, "sequence_hash", "cdr_masks")
    if set(mask_by_sha) != set(candidate_by_sha):
        raise SupportV3Error("cdr_mask_candidate_sequence_set_mismatch")
    for digest, row in mask_by_sha.items():
        sequence = normalize_sequence(row["vhh_seq"], f"mask:{digest}")
        if sequence_sha256(sequence) != digest:
            raise SupportV3Error(f"cdr_mask_sequence_hash_mismatch:{digest}")

    cache_rows, cache_fields = read_table(resolved["esm2_residue_cache_manifest"], ",")
    require_fields(
        cache_fields,
        {"model_sha256", "sequence_sha256", "chain_type", "shard_path", "shard_key"},
        "esm2_cache_manifest",
    )
    validate_no_label_features(cache_fields, "esm2_cache_manifest")
    expected_model_sha = str(inputs["esm2_residue_cache_manifest"]["model_weights_sha256"])
    if any(row["model_sha256"] != expected_model_sha for row in cache_rows):
        raise SupportV3Error("esm2_model_weights_hash_mismatch")
    vhh_cache = [row for row in cache_rows if row["chain_type"].lower() == "vhh"]
    vhh_cache_by_sha = _unique_map(vhh_cache, "sequence_sha256", "esm2_vhh_cache")
    if set(vhh_cache_by_sha) != set(candidate_by_sha):
        raise SupportV3Error("esm2_cache_candidate_sequence_set_mismatch")
    cache_root = resolved["esm2_residue_cache_manifest"].parent
    for shard_name in {row["shard_path"] for row in vhh_cache}:
        shard = (cache_root / shard_name).resolve()
        if not shard.is_file():
            raise SupportV3Error(f"esm2_cache_shard_missing:{shard_name}")

    contact_receipt = json.loads(
        resolved["contact_feature_release_receipt"].read_text(encoding="utf-8")
    )
    if contact_receipt.get("status") != "PASS":
        raise SupportV3Error("contact_feature_release_receipt_not_pass")
    _validate_snapshot_records(repo_root, contact_receipt.get("input_snapshot", {}))
    contact_csv = resolve_recorded_path(repo_root, str(contact_receipt.get("output", "")))
    verify_locked_path(contact_csv, str(contact_receipt.get("output_sha256", "")), "contact_csv")
    contact_rows, contact_fields = read_table(contact_csv, ",")
    validate_no_label_features(contact_fields, "contact_features")
    require_fields(contact_fields, {"candidate_id", "sequence_sha256"}, "contact_features")
    if len(contact_rows) != int(contact_receipt.get("output_row_count", -1)):
        raise SupportV3Error("contact_feature_row_count_mismatch")
    contact_by_id = _unique_map(contact_rows, "candidate_id", "contact_features")
    if set(contact_by_id) != set(candidates):
        raise SupportV3Error("contact_feature_candidate_set_mismatch")
    for candidate_id, row in contact_by_id.items():
        if row["sequence_sha256"] != candidates[candidate_id]["sequence_sha256"]:
            raise SupportV3Error(f"contact_feature_sequence_hash_mismatch:{candidate_id}")

    schema = json.loads(resolved["contact_feature_schema"].read_text(encoding="utf-8"))
    if (
        schema.get("status") != "PASS_FROZEN_LABEL_FREE_CONTACT_FEATURE_SCHEMA"
        or int(schema.get("selected_feature_count", -1))
        != int(inputs["contact_feature_schema"]["selected_feature_count"])
    ):
        raise SupportV3Error("contact_feature_schema_status_or_count_mismatch")
    selected_features = list(schema.get("selected_features", []))
    if len(selected_features) != len(set(selected_features)):
        raise SupportV3Error("contact_feature_schema_duplicate_features")
    diagnostic = set(schema.get("diagnostic_only_length_confounded_features", []))
    if set(selected_features) & diagnostic:
        raise SupportV3Error("contact_schema_includes_length_confounded_diagnostic")
    schema_receipt = resolved["contact_feature_schema"].with_suffix(".receipt.json")
    verify_locked_path(
        schema_receipt,
        str(inputs["contact_feature_schema"]["receipt_sha256"]),
        "contact_feature_schema_receipt",
    )

    return {
        "status": "PASS_FROZEN_LABEL_FREE_INPUT_CLOSURE",
        "candidate_count": len(candidate_rows),
        "split_count": len(split_rows),
        "open_train_count": len(open_train),
        "open_train_parent_count": len({row["parent_framework_cluster"] for row in open_train}),
        "cdr_mask_count": len(mask_rows),
        "esm2_vhh_cache_count": len(vhh_cache),
        "contact_feature_count": len(contact_rows),
        "stable_contact_feature_count": len(selected_features),
        "consumed_candidate_fields": sorted(CONSUMED_CANDIDATE_FIELDS),
        "docking_or_experimental_label_paths_opened": 0,
        "input_sha256": {
            label: str(record["sha256"]) for label, record in sorted(inputs.items())
        },
    }


def _vector(values: Sequence[float], label: str) -> tuple[float, ...]:
    output = tuple(float(value) for value in values)
    if not output or any(not math.isfinite(value) for value in output):
        raise SupportV3Error(f"invalid_vector:{label}")
    return output


@dataclass(frozen=True)
class SupportRecord:
    candidate_id: str
    sequence_sha256: str
    declared_parent: str
    full_esm: tuple[float, ...]
    cdr_esm: tuple[float, ...]
    cdr1: str
    cdr2: str
    cdr3: str
    contact: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.sequence_sha256 or not self.declared_parent:
            raise SupportV3Error("support_record_identity_missing")
        object.__setattr__(self, "full_esm", _vector(self.full_esm, "full_esm"))
        object.__setattr__(self, "cdr_esm", _vector(self.cdr_esm, "cdr_esm"))
        object.__setattr__(self, "contact", _vector(self.contact, "contact"))
        for field in ("cdr1", "cdr2", "cdr3"):
            object.__setattr__(self, field, normalize_sequence(getattr(self, field), field))


@dataclass(frozen=True)
class DomainDecision:
    label: str
    neighbor_id: str
    neighbor_parent: str
    distances: Mapping[str, float]


def cosine_distance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise SupportV3Error("cosine_vector_width_mismatch")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm <= 0.0 or right_norm <= 0.0:
        raise SupportV3Error("cosine_zero_norm")
    similarity = sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)
    return max(0.0, min(2.0, 1.0 - similarity))


def normalized_levenshtein(left: str, right: str) -> float:
    if left == right:
        return 0.0
    if not left or not right:
        return 1.0
    previous = list(range(len(right) + 1))
    for i, lvalue in enumerate(left, start=1):
        current = [i]
        for j, rvalue in enumerate(right, start=1):
            current.append(
                min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (lvalue != rvalue))
            )
        previous = current
    return previous[-1] / max(len(left), len(right))


def _kmer_counts(record: SupportRecord, k: int) -> Counter[str]:
    counts: Counter[str] = Counter()
    for region, sequence in enumerate((record.cdr1, record.cdr2, record.cdr3), start=1):
        for index in range(max(0, len(sequence) - k + 1)):
            counts[f"{region}:{sequence[index:index + k]}"] += 1
    return counts


def sparse_cosine_distance(left: Mapping[str, int], right: Mapping[str, int]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm <= 0.0 or right_norm <= 0.0:
        raise SupportV3Error("kmer_zero_norm")
    shared = set(left) & set(right)
    similarity = sum(left[key] * right[key] for key in shared) / (left_norm * right_norm)
    return max(0.0, min(1.0, 1.0 - similarity))


def normalized_euclidean(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise SupportV3Error("euclidean_vector_width_mismatch")
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)) / len(left))


def channel_distances(query: SupportRecord, reference: SupportRecord) -> dict[str, float]:
    return {
        "full_esm_cosine": cosine_distance(query.full_esm, reference.full_esm),
        "cdr_esm_cosine": cosine_distance(query.cdr_esm, reference.cdr_esm),
        "cdr1_edit": normalized_levenshtein(query.cdr1, reference.cdr1),
        "cdr2_edit": normalized_levenshtein(query.cdr2, reference.cdr2),
        "cdr3_edit": normalized_levenshtein(query.cdr3, reference.cdr3),
        "cdr_2mer_cosine": sparse_cosine_distance(_kmer_counts(query, 2), _kmer_counts(reference, 2)),
        "cdr_3mer_cosine": sparse_cosine_distance(_kmer_counts(query, 3), _kmer_counts(reference, 3)),
        "contact_euclidean": normalized_euclidean(query.contact, reference.contact),
    }


def validate_thresholds(thresholds: Mapping[str, float], label: str) -> dict[str, float]:
    if set(thresholds) != set(REQUIRED_CHANNELS):
        raise SupportV3Error(f"threshold_channel_set_mismatch:{label}")
    output = {key: float(value) for key, value in thresholds.items()}
    if any(not math.isfinite(value) or value < 0.0 for value in output.values()):
        raise SupportV3Error(f"invalid_threshold:{label}")
    return output


def _passing_neighbor(
    query: SupportRecord,
    references: Iterable[SupportRecord],
    thresholds: Mapping[str, float],
) -> tuple[SupportRecord, dict[str, float]] | None:
    limits = validate_thresholds(thresholds, "neighbor")
    passing: list[tuple[float, str, SupportRecord, dict[str, float]]] = []
    for reference in references:
        if (
            reference.candidate_id == query.candidate_id
            or reference.sequence_sha256 == query.sequence_sha256
        ):
            continue
        distances = channel_distances(query, reference)
        if all(distances[channel] <= limits[channel] for channel in REQUIRED_CHANNELS):
            ratios = [
                0.0 if limits[channel] == 0.0 else distances[channel] / limits[channel]
                for channel in REQUIRED_CHANNELS
            ]
            passing.append((max(ratios), reference.candidate_id, reference, distances))
    if not passing:
        return None
    _ratio, _candidate_id, reference, distances = min(passing, key=lambda row: (row[0], row[1]))
    return reference, distances


def classify_domain(
    query: SupportRecord,
    references: Sequence[SupportRecord],
    in_domain_thresholds: Mapping[str, float],
    global_thresholds: Mapping[str, float],
) -> DomainDecision:
    if not references:
        raise SupportV3Error("empty_reference_set")
    exact = [
        row
        for row in references
        if row.candidate_id == query.candidate_id or row.sequence_sha256 == query.sequence_sha256
    ]
    if exact:
        reference = min(exact, key=lambda row: row.candidate_id)
        return DomainDecision("TRAIN_REFERENCE", reference.candidate_id, reference.declared_parent, {})

    same_parent = [row for row in references if row.declared_parent == query.declared_parent]
    matched = _passing_neighbor(query, same_parent, in_domain_thresholds)
    if matched is not None:
        reference, distances = matched
        return DomainDecision("IN_DOMAIN", reference.candidate_id, reference.declared_parent, distances)

    cross_parent = [row for row in references if row.declared_parent != query.declared_parent]
    matched = _passing_neighbor(query, cross_parent, global_thresholds)
    if matched is not None:
        reference, distances = matched
        return DomainDecision("NEAR_DOMAIN", reference.candidate_id, reference.declared_parent, distances)
    return DomainDecision("OUT_OF_DOMAIN", "", "", {})


def evaluate_null_control(
    kind: str,
    queries: Sequence[SupportRecord],
    references: Sequence[SupportRecord],
    in_domain_thresholds: Mapping[str, float],
    global_thresholds: Mapping[str, float],
    lock: Mapping[str, Any],
) -> dict[str, Any]:
    if kind not in NULL_GATE_TARGETS or not queries:
        raise SupportV3Error(f"invalid_null_control:{kind}")
    target_label, gate_name = NULL_GATE_TARGETS[kind]
    labels = [
        classify_domain(row, references, in_domain_thresholds, global_thresholds).label
        for row in queries
    ]
    observed = sum(label == target_label for label in labels) / len(labels)
    maximum = float(lock["hard_gates"][kind][gate_name])
    return {
        "kind": kind,
        "row_count": len(labels),
        "target_label": target_label,
        "observed_fraction": observed,
        "maximum": maximum,
        "passed": observed <= maximum,
        "label_counts": dict(sorted(Counter(labels).items())),
    }


def evaluate_gate_bundle(
    lock: Mapping[str, Any],
    *,
    nested_in_domain_fraction: float,
    nested_parent_fractions: Mapping[str, float],
    deployment_labels: Sequence[str],
    null_results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if set(null_results) != set(NULL_GATE_TARGETS):
        raise SupportV3Error("null_result_set_mismatch")
    if not nested_parent_fractions:
        raise SupportV3Error("nested_parent_fractions_empty")
    if not deployment_labels or any(label == "TRAIN_REFERENCE" for label in deployment_labels):
        raise SupportV3Error("deployment_denominator_invalid")
    expected_denominator = int(lock["hard_gates"]["deployment_coverage"]["denominator"])
    if len(deployment_labels) != expected_denominator:
        raise SupportV3Error("deployment_denominator_count_mismatch")
    in_domain_count = sum(label == "IN_DOMAIN" for label in deployment_labels)
    in_domain_fraction = in_domain_count / len(deployment_labels)
    nested_gate = lock["hard_gates"]["nested_validation"]
    deployment_gate = lock["hard_gates"]["deployment_coverage"]
    gates = {
        "nested_validation": {
            "observed": nested_in_domain_fraction,
            "minimum": float(nested_gate["in_domain_fraction_minimum"]),
            "every_parent_observed_minimum": min(nested_parent_fractions.values()),
            "every_parent_minimum": float(nested_gate["every_parent_fraction_minimum"]),
            "passed": (
                nested_in_domain_fraction >= float(nested_gate["in_domain_fraction_minimum"])
                and min(nested_parent_fractions.values())
                >= float(nested_gate["every_parent_fraction_minimum"])
            ),
        },
        "deployment_coverage": {
            "observed_count": in_domain_count,
            "minimum_count": int(deployment_gate["in_domain_count_minimum"]),
            "observed_fraction": in_domain_fraction,
            "minimum_fraction": float(deployment_gate["in_domain_fraction_minimum"]),
            "passed": (
                in_domain_count >= int(deployment_gate["in_domain_count_minimum"])
                and in_domain_fraction >= float(deployment_gate["in_domain_fraction_minimum"])
            ),
        },
        **{kind: dict(null_results[kind]) for kind in sorted(NULL_GATE_TARGETS)},
    }
    passed = all(gate.get("passed") is True for gate in gates.values())
    return {
        "status": lock["decision_policy"]["pass" if passed else "fail"],
        "all_gates_passed": passed,
        "gates": gates,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--validate-frozen-inputs", action="store_true")
    args = parser.parse_args(argv)
    lock = load_preregistration(args.preregistration)
    if not args.validate_frozen_inputs:
        raise SupportV3Error(
            "production_materialization_not_implemented:run_validate_frozen_inputs_only;"
            "real_ESM2_and_contact_null_recomputation_requires_a_separately_reviewed_adapter"
        )
    closure = validate_frozen_inputs(lock, args.repo_root)
    print(
        json.dumps(
            {
                **closure,
                "implementation_status": "SYNTHETIC_VALIDATED_SKELETON",
                "production_support_table_published": False,
                "remaining_gap": (
                    "real ESM2/contact materialization and four null recomputations are not implemented"
                ),
                "preregistration_sha256": EXPECTED_PREREGISTRATION_SHA256,
                "claim_boundary": lock["claim_boundary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
