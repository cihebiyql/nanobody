#!/usr/bin/env python3
"""Build trainer-ready V4D + adaptive V4H residue marginal targets."""

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
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "pvrig_v6_adaptive_dual_source_residue_contact_targets_v3"
CLAIM_BOUNDARY = (
    "Residue targets derived from independent dual-receptor computational Docking "
    "contacts; not binding probability, affinity, experimental blocking, Docking "
    "Gold, or final submission evidence."
)
RECEPTORS = ("8x6b", "9e6y")
SOURCES = ("V4D_OPEN_MULTI_SEED", "V4H_ADAPTIVE_SEED_RANKING")
V4D, V4H = SOURCES
OUTPUT_NAME = "v6_adaptive_dual_source_residue_contact_targets_v3.tsv.gz"
RECEIPT_NAME = "RUN_RECEIPT.json"
RECEIPT_SCHEMA = "pvrig_v2_4_adaptive_multiseed_dual_source_marginal_receipt_v1"
RECEIPT_STATUS = "PASS_V2_4_ADAPTIVE_MULTI_SEED_DUAL_SOURCE_MARGINAL_MATERIALIZED"
TEACHER_GENERATION = "V4D_MULTI_SEED_PLUS_V4H_ADAPTIVE_MULTI_SEED_V2"
OUTPUT_FIELDS = (
    "schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster",
    "teacher_source", "vhh_sequence_index", "vhh_aa",
    "contact_target_8x6b", "contact_target_9e6y",
    "contact_variance_8x6b", "contact_variance_9e6y",
    "contact_uncertainty_weight_8x6b", "contact_uncertainty_weight_9e6y",
    "observed_seed_count_8x6b", "observed_seed_count_9e6y",
    "expected_seed_count_8x6b", "expected_seed_count_9e6y",
    "target_mask_8x6b", "target_mask_9e6y",
    "aggregation_8x6b", "aggregation_9e6y", "claim_boundary",
)
TRAIN_REQUIRED = {
    "candidate_id", "sequence_sha256", "sequence", "parent_framework_cluster", "teacher_source",
}
V4D_REQUIRED = {
    "candidate_id", "sequence_sha256", "parent_framework_cluster", "receptor",
    "vhh_sequence_index", "vhh_aa", "contact_marginal_mean",
    "contact_marginal_variance", "contact_marginal_uncertainty_weight",
    "observed_seed_count", "expected_seed_count",
}
V4H_REQUIRED = {
    "schema_version", "teacher_state", "candidate_id", "sequence_sha256",
    "parent_framework_cluster", "receptor", "observed_seed_count",
    "observed_seed_ids", "vhh_sequence_index", "vhh_aa",
    "contact_marginal_mean", "contact_marginal_variance",
    "contact_marginal_uncertainty_weight", "supporting_seed_count",
    "seed_marginal_values",
}
CANDIDATE_REQUIRED = {
    "schema_version", "teacher_state", "candidate_id", "sequence_sha256",
    "parent_framework_cluster", "docking_evidence_tier", "paired_seed_ids",
    "paired_seed_count",
}


class ContactTargetError(RuntimeError):
    """Fail-closed V2 target materialization error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContactTargetError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_regular(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ContactTargetError(f"{label}_missing:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"{label}_not_regular_or_symlink:{path}")


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require_regular(path, "input")
    if path.suffix == ".gz":
        handle: Any = gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    else:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    with handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    require(fields and rows, f"empty_tsv:{path}")
    return fields, rows


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


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = (json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    with temporary.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def finite_unit(value: str, label: str) -> float:
    parsed = float(value)
    require(math.isfinite(parsed) and 0.0 <= parsed <= 1.0, f"{label}_invalid:{value}")
    return parsed


def read_json(path: Path, label: str) -> dict[str, Any]:
    require_regular(path, label)
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(payload, dict), f"{label}_not_object")
    return payload


def parse_seed_values(text: str, expected_count: int, label: str) -> list[tuple[int, float]]:
    values: list[tuple[int, float]] = []
    for item in text.split(";"):
        seed_text, separator, value_text = item.partition(":")
        require(bool(separator), f"{label}_format:{item}")
        seed = int(seed_text)
        require(seed in {917, 1931, 3253}, f"{label}_seed:{seed}")
        values.append((seed, finite_unit(value_text, label)))
    require(len(values) == expected_count, f"{label}_count:{len(values)}:{expected_count}")
    require(len({seed for seed, _ in values}) == expected_count, f"{label}_duplicate_seed")
    return values


def parse_seed_ids(text: str, expected_count: int, label: str) -> tuple[int, ...]:
    values = tuple(int(value) for value in text.split(","))
    require(len(values) == expected_count and len(set(values)) == expected_count, f"{label}_count")
    require(set(values) <= {917, 1931, 3253}, f"{label}_unexpected")
    return values


def validate_receipts(
    v4d_receipt_path: Path,
    v4d_marginal_path: Path,
    v4h_receipt_path: Path,
    v4h_residue_path: Path,
    v4h_candidate_path: Path,
    expected_v4d_candidates: int,
    expected_v4h_candidates: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    v4d = read_json(v4d_receipt_path, "v4d_receipt")
    require(v4d.get("schema_version") == "pvrig_v6_v4d_open226_multi_seed_contact_teacher_v2_receipt", "v4d_receipt_schema")
    require(v4d.get("status") == "COMPLETE_V4D_OPEN226_MULTI_SEED_CONTACT_TEACHER_V2", "v4d_receipt_status")
    require(int((v4d.get("counts") or {}).get("teacher_candidates", -1)) == expected_v4d_candidates, "v4d_receipt_candidates")
    require(int((v4d.get("counts") or {}).get("zero_imputed_failed_seeds", -1)) == 0, "v4d_zero_imputation")
    require((v4d.get("outputs") or {}).get("residue_marginal_sha256") == sha256_file(v4d_marginal_path), "v4d_marginal_hash")
    sealed = v4d.get("sealed_boundary") or {}
    for field in ("sealed_pose_files_opened", "sealed_result_files_opened", "shared_job_results_tsv_opened", "shared_pose_scores_tsv_opened"):
        require(int(sealed.get(field, -1)) == 0, f"v4d_sealed_boundary:{field}")
    require(int((v4d.get("source") or {}).get("source_mutation_operations", -1)) == 0, "v4d_source_mutation")
    v4h = read_json(v4h_receipt_path, "v4h_receipt")
    require(v4h.get("schema_version") == "pvrig_v6_v4h_adaptive_multiseed_contact_teacher_v2_receipt", "v4h_receipt_schema")
    require(v4h.get("status") == "PASS_V4H_ADAPTIVE_MULTI_SEED_CONTACT_EXTRACTION", "v4h_receipt_status")
    require(int(v4h.get("candidate_rows", -1)) == expected_v4h_candidates + 39, "v4h_candidate_rows")
    require(int(v4h.get("valid_candidate_rows", -1)) == expected_v4h_candidates, "v4h_valid_candidate_rows")
    require(int(v4h.get("technical_incomplete_candidate_rows", -1)) == 39, "v4h_na_candidate_rows")
    require(int(v4h.get("source_mutation_operations", -1)) == 0, "v4h_source_mutation")
    hashes = v4h.get("output_hashes") or {}
    require(isinstance(hashes.get("v4h_adaptive_residue_pair_contact_teacher.tsv.gz"), str), "v4h_pair_hash_missing")
    require(hashes.get(v4h_residue_path.name) == sha256_file(v4h_residue_path), "v4h_residue_hash")
    require(hashes.get(v4h_candidate_path.name) == sha256_file(v4h_candidate_path), "v4h_candidate_hash")
    return v4d, v4h


def load_training(
    path: Path, expected_source_counts: Mapping[str, int],
) -> tuple[dict[str, dict[str, str]], Counter[str]]:
    fields, rows = read_tsv(path)
    require(TRAIN_REQUIRED <= set(fields), f"training_fields_missing:{sorted(TRAIN_REQUIRED-set(fields))}")
    training: dict[str, dict[str, str]] = {}
    counts: Counter[str] = Counter()
    for row in rows:
        candidate = row["candidate_id"].strip()
        source = row["teacher_source"].strip()
        require(source in SOURCES, f"training_source_forbidden:{candidate}:{source}")
        require(candidate and candidate not in training, f"duplicate_training_candidate:{candidate}")
        sequence = row["sequence"].strip().upper()
        require(sequence and all(aa in "ACDEFGHIKLMNPQRSTVWY" for aa in sequence), f"invalid_sequence:{candidate}")
        require(hashlib.sha256(sequence.encode("ascii")).hexdigest() == row["sequence_sha256"], f"sequence_hash_mismatch:{candidate}")
        training[candidate] = {**row, "sequence": sequence, "teacher_source": source}
        counts[source] += 1
    require(dict(counts) == dict(expected_source_counts), f"source_counts_mismatch:{dict(counts)}:{dict(expected_source_counts)}")
    return training, counts


def validate_identity(row: Mapping[str, str], source: Mapping[str, str], *, label: str) -> tuple[str, int, str]:
    candidate = row["candidate_id"].strip()
    require(row["sequence_sha256"] == source["sequence_sha256"], f"{label}_sequence_hash_mismatch:{candidate}")
    require(row["parent_framework_cluster"] == source["parent_framework_cluster"], f"{label}_parent_mismatch:{candidate}")
    receptor = row["receptor"].strip().lower()
    require(receptor in RECEPTORS, f"{label}_receptor_invalid:{candidate}:{receptor}")
    index = int(row["vhh_sequence_index"])
    sequence = source["sequence"]
    require(1 <= index <= len(sequence), f"{label}_index_out_of_range:{candidate}:{index}")
    aa = row["vhh_aa"].strip().upper()
    require(aa == sequence[index - 1], f"{label}_aa_mismatch:{candidate}:{index}")
    return receptor, index, aa


def build_targets(
    training_tsv: Path,
    v4d_marginal_tsv: Path,
    v4d_receipt: Path,
    v4h_residue_tsv: Path,
    v4h_candidate_tsv: Path,
    v4h_receipt: Path,
    output_dir: Path,
    *,
    expected_source_counts: Mapping[str, int],
    expected_hashes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    require(set(expected_source_counts) == set(SOURCES), "expected_source_keys_invalid")
    require(all(int(value) > 0 for value in expected_source_counts.values()), "expected_source_count_invalid")
    require(not output_dir.exists(), f"output_dir_already_exists:{output_dir}")
    require(not output_dir.is_symlink(), "output_dir_symlink_forbidden")
    inputs = {
        "training_tsv": training_tsv,
        "v4d_marginal_tsv": v4d_marginal_tsv,
        "v4d_receipt": v4d_receipt,
        "v4h_residue_tsv": v4h_residue_tsv,
        "v4h_candidate_tsv": v4h_candidate_tsv,
        "v4h_receipt": v4h_receipt,
    }
    input_hashes = {name: sha256_file(path) for name, path in inputs.items()}
    if expected_hashes is not None:
        require(dict(expected_hashes) == input_hashes, f"input_hashes_mismatch:{input_hashes}")

    v4d_receipt_payload, v4h_receipt_payload = validate_receipts(
        v4d_receipt, v4d_marginal_tsv, v4h_receipt, v4h_residue_tsv, v4h_candidate_tsv,
        int(expected_source_counts[V4D]),
        int(expected_source_counts[V4H]),
    )
    training, source_counts = load_training(training_tsv, expected_source_counts)
    source_ids = {
        source: {candidate for candidate, row in training.items() if row["teacher_source"] == source}
        for source in SOURCES
    }
    require(source_ids[SOURCES[0]].isdisjoint(source_ids[SOURCES[1]]), "source_candidate_overlap")

    v4d_fields, v4d_rows = read_tsv(v4d_marginal_tsv)
    require(V4D_REQUIRED <= set(v4d_fields), f"v4d_fields_missing:{sorted(V4D_REQUIRED-set(v4d_fields))}")
    v4d_values: dict[tuple[str, str, int], dict[str, Any]] = {}
    v4d_receptors: defaultdict[str, set[str]] = defaultdict(set)
    for row in v4d_rows:
        candidate = row["candidate_id"].strip()
        require(candidate in source_ids["V4D_OPEN_MULTI_SEED"], f"v4d_candidate_not_in_source:{candidate}")
        receptor, index, _aa = validate_identity(row, training[candidate], label="v4d")
        key = (candidate, receptor, index)
        require(key not in v4d_values, f"duplicate_v4d_marginal:{key}")
        mean = finite_unit(row["contact_marginal_mean"], "v4d_marginal_mean")
        variance = float(row["contact_marginal_variance"])
        uncertainty = finite_unit(row["contact_marginal_uncertainty_weight"], "v4d_uncertainty")
        observed = int(row["observed_seed_count"])
        expected = int(row["expected_seed_count"])
        require(math.isfinite(variance) and variance >= 0.0, f"v4d_variance_invalid:{key}")
        require(expected == 3 and 2 <= observed <= expected, f"v4d_seed_count_invalid:{key}:{observed}:{expected}")
        require(abs(uncertainty - 1.0 / (1.0 + 4.0 * variance)) <= 1e-6, f"v4d_uncertainty_formula_mismatch:{key}")
        v4d_values[key] = {
            "target": mean, "variance": variance, "uncertainty": uncertainty,
            "observed": observed, "expected": expected,
        }
        v4d_receptors[candidate].add(receptor)
    require(set(v4d_receptors) == source_ids["V4D_OPEN_MULTI_SEED"], "v4d_candidate_closure_failed")
    for candidate in sorted(source_ids["V4D_OPEN_MULTI_SEED"]):
        require(v4d_receptors[candidate] == set(RECEPTORS), f"v4d_candidate_missing_receptor:{candidate}")
        sequence_length = len(training[candidate]["sequence"])
        for receptor in RECEPTORS:
            observed_indices = {index for cand, rec, index in v4d_values if cand == candidate and rec == receptor}
            require(observed_indices == set(range(1, sequence_length + 1)), f"v4d_residue_closure_failed:{candidate}:{receptor}")

    candidate_fields, candidate_rows = read_tsv(v4h_candidate_tsv)
    require(CANDIDATE_REQUIRED <= set(candidate_fields), f"v4h_candidate_fields_missing:{sorted(CANDIDATE_REQUIRED-set(candidate_fields))}")
    valid_v4h_candidates: set[str] = set()
    na_v4h_candidates: set[str] = set()
    candidate_seed_counts: dict[str, int] = {}
    for row in candidate_rows:
        candidate = row["candidate_id"].strip()
        require(candidate not in valid_v4h_candidates | na_v4h_candidates, f"v4h_candidate_duplicate:{candidate}")
        require(row["schema_version"] == "pvrig_v6_v4h_adaptive_multiseed_contact_teacher_v2", f"v4h_candidate_schema:{candidate}")
        if row["teacher_state"] == "TECHNICAL_INCOMPLETE_NA":
            require(row["paired_seed_count"] == "", f"v4h_na_seed_count_not_empty:{candidate}")
            na_v4h_candidates.add(candidate)
        else:
            count = int(row["paired_seed_count"])
            require(row["teacher_state"] == f"VALID_DUAL_{count}_SEED_CONTACT", f"v4h_candidate_state:{candidate}")
            require(count in {1, 2, 3}, f"v4h_candidate_seed_count:{candidate}")
            parse_seed_ids(row["paired_seed_ids"], count, f"v4h_candidate_seed_ids:{candidate}")
            valid_v4h_candidates.add(candidate)
            candidate_seed_counts[candidate] = count
    require(valid_v4h_candidates == source_ids[V4H], "v4h_valid_training_candidate_closure")
    require(len(na_v4h_candidates) == 39 and not (na_v4h_candidates & set(training)), "v4h_na_candidate_closure")

    v4h_fields, v4h_rows = read_tsv(v4h_residue_tsv)
    require(V4H_REQUIRED <= set(v4h_fields), f"v4h_fields_missing:{sorted(V4H_REQUIRED-set(v4h_fields))}")
    v4h_values: dict[tuple[str, str, int], dict[str, Any]] = {}
    v4h_receptors: defaultdict[str, set[str]] = defaultdict(set)
    for row in v4h_rows:
        candidate = row["candidate_id"].strip()
        require(candidate in source_ids[V4H], f"v4h_candidate_not_in_source:{candidate}")
        receptor, index, _aa = validate_identity(row, training[candidate], label="v4h")
        key = (candidate, receptor, index)
        require(key not in v4h_values, f"duplicate_v4h_marginal:{key}")
        observed = int(row["observed_seed_count"])
        require(observed == candidate_seed_counts[candidate], f"v4h_seed_count_mismatch:{key}")
        require(row["teacher_state"] == f"VALID_DUAL_{observed}_SEED_CONTACT", f"v4h_teacher_state:{key}")
        mean = finite_unit(row["contact_marginal_mean"], "v4h_marginal_mean")
        variance = float(row["contact_marginal_variance"])
        uncertainty = finite_unit(row["contact_marginal_uncertainty_weight"], "v4h_uncertainty")
        require(math.isfinite(variance) and variance >= 0.0, f"v4h_variance:{key}")
        require(abs(uncertainty - 1.0 / (1.0 + 4.0 * variance)) <= 1e-6, f"v4h_uncertainty_formula:{key}")
        seed_values = parse_seed_values(row["seed_marginal_values"], observed, "v4h_seed_marginal")
        numeric = [value for _, value in seed_values]
        seed_mean = sum(numeric) / observed
        seed_variance = sum((value - seed_mean) ** 2 for value in numeric) / observed
        # Adaptive source values are frozen at nine decimal places.
        require(abs(seed_mean - mean) <= 5e-9, f"v4h_seed_mean:{key}")
        require(abs(seed_variance - variance) <= 5e-9, f"v4h_seed_variance:{key}")
        require(int(row["supporting_seed_count"]) == sum(value > 0.0 for value in numeric), f"v4h_supporting_seed_count:{key}")
        v4h_values[key] = {
            "target": mean, "variance": variance, "uncertainty": uncertainty,
            "observed": observed, "expected": observed,
        }
        v4h_receptors[candidate].add(receptor)
    require(set(v4h_receptors) == source_ids[V4H], "v4h_candidate_closure_failed")
    for candidate in sorted(source_ids[V4H]):
        require(v4h_receptors[candidate] == set(RECEPTORS), f"v4h_candidate_missing_receptor:{candidate}")
        sequence_length = len(training[candidate]["sequence"])
        for receptor in RECEPTORS:
            observed_indices = {index for cand, rec, index in v4h_values if cand == candidate and rec == receptor}
            require(observed_indices == set(range(1, sequence_length + 1)), f"v4h_residue_closure:{candidate}:{receptor}")

    output_rows: list[dict[str, Any]] = []
    partial_v4d_candidate_receptors: set[tuple[str, str]] = set()
    for candidate in sorted(training):
        source = training[candidate]
        sequence = source["sequence"]
        for index, aa in enumerate(sequence, start=1):
            values: dict[str, dict[str, Any]] = {}
            for receptor in RECEPTORS:
                if source["teacher_source"] == "V4D_OPEN_MULTI_SEED":
                    value = v4d_values[(candidate, receptor, index)]
                    if value["observed"] < value["expected"]:
                        partial_v4d_candidate_receptors.add((candidate, receptor))
                    values[receptor] = {**value, "aggregation": "pose_any_contact_then_seed_mean"}
                else:
                    values[receptor] = {
                        **v4h_values[(candidate, receptor, index)],
                        "aggregation": "pose_any_contact_then_equal_intersection_seed_mean",
                    }
            output_rows.append({
                "schema_version": SCHEMA_VERSION,
                "candidate_id": candidate,
                "sequence_sha256": source["sequence_sha256"],
                "parent_framework_cluster": source["parent_framework_cluster"],
                "teacher_source": source["teacher_source"],
                "vhh_sequence_index": index,
                "vhh_aa": aa,
                **{f"contact_target_{receptor}": format(values[receptor]["target"], ".10g") for receptor in RECEPTORS},
                **{f"contact_variance_{receptor}": format(values[receptor]["variance"], ".10g") for receptor in RECEPTORS},
                **{f"contact_uncertainty_weight_{receptor}": format(values[receptor]["uncertainty"], ".10g") for receptor in RECEPTORS},
                **{f"observed_seed_count_{receptor}": values[receptor]["observed"] for receptor in RECEPTORS},
                **{f"expected_seed_count_{receptor}": values[receptor]["expected"] for receptor in RECEPTORS},
                **{f"target_mask_{receptor}": 1 for receptor in RECEPTORS},
                **{f"aggregation_{receptor}": values[receptor]["aggregation"] for receptor in RECEPTORS},
                "claim_boundary": CLAIM_BOUNDARY,
            })

    output_dir.mkdir(parents=True, exist_ok=False)
    output_path = output_dir / OUTPUT_NAME
    write_gzip_tsv(output_path, OUTPUT_FIELDS, output_rows)
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "status": RECEIPT_STATUS,
        "teacher_generation": TEACHER_GENERATION,
        "training_tsv_sha256": input_hashes["training_tsv"],
        "v4h_adaptive_source_receipt_sha256": input_hashes["v4h_receipt"],
        "v4d_source_receipt_sha256": input_hashes["v4d_receipt"],
        "v4h_adaptive_raw_pair_teacher_sha256": v4h_receipt_payload["output_hashes"]["v4h_adaptive_residue_pair_contact_teacher.tsv.gz"],
        "v4h_adaptive_raw_marginal_teacher_sha256": input_hashes["v4h_residue_tsv"],
        "candidate_rows": len(training),
        "v4d_candidate_rows": int(source_counts[V4D]),
        "v4h_valid_candidate_rows": int(source_counts[V4H]),
        "v4h_technical_incomplete_excluded": len(na_v4h_candidates),
        "legacy_stage1_rows": 0,
        "claim_boundary": CLAIM_BOUNDARY,
        "teacher_source_is_model_feature": False,
        "source_semantics": {
            V4D: "exact pose-any-contact marginal then equal observed-successful-seed mean",
            V4H: "exact pose-any-contact marginal then equal paired-seed-intersection mean; A/B/C preserve 3/2/1 paired seeds",
        },
        "inputs": {
            name: {"path": str(path.resolve()), "sha256": input_hashes[name]} for name, path in inputs.items()
        },
        "counts": {
            "training_candidates": len(training),
            "target_candidates": len({row["candidate_id"] for row in output_rows}),
            "target_rows": len(output_rows),
            "source_candidates": dict(source_counts),
            "v4d_marginal_rows": len(v4d_rows),
            "v4h_residue_rows": len(v4h_rows),
            "v4h_raw_candidate_rows": len(candidate_rows),
            "v4h_valid_candidate_rows": len(valid_v4h_candidates),
            "v4h_technical_na_candidate_rows": len(na_v4h_candidates),
            "partial_v4d_candidate_receptors": len(partial_v4d_candidate_receptors),
            "technical_na_rows_imputed": 0,
        },
        "upstream_receipts": {
            "v4d_status": v4d_receipt_payload["status"],
            "v4h_status": v4h_receipt_payload["status"],
        },
        "partial_v4d_candidate_receptors": [f"{candidate}:{receptor}" for candidate, receptor in sorted(partial_v4d_candidate_receptors)],
        "output": {"path": output_path.name, "sha256": sha256_file(output_path)},
    }
    atomic_json(output_dir / RECEIPT_NAME, receipt)
    return receipt


def parse_counts(values: Sequence[str]) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for item in values:
        source, separator, count = item.partition("=")
        require(bool(separator) and source in SOURCES and source not in parsed, f"invalid_source_count:{item}")
        parsed[source] = int(count)
    require(set(parsed) == set(SOURCES), "source_count_keys_incomplete")
    return parsed


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--training-tsv", type=Path, required=True)
    value.add_argument("--v4d-marginal-tsv", type=Path, required=True)
    value.add_argument("--v4d-receipt", type=Path, required=True)
    value.add_argument("--v4h-residue-tsv", type=Path, required=True)
    value.add_argument("--v4h-candidate-tsv", type=Path, required=True)
    value.add_argument("--v4h-receipt", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--expected-source-count", action="append", required=True)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    receipt = build_targets(
        args.training_tsv, args.v4d_marginal_tsv, args.v4d_receipt,
        args.v4h_residue_tsv, args.v4h_candidate_tsv, args.v4h_receipt,
        args.output_dir,
        expected_source_counts=parse_counts(args.expected_source_count),
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
