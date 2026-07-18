#!/usr/bin/env python3
"""Build V2 dual-source residue marginal targets without erasing teacher semantics."""

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


SCHEMA_VERSION = "pvrig_v6_residue_dual_source_contact_targets_v2"
CLAIM_BOUNDARY = (
    "Residue targets derived from independent dual-receptor computational Docking "
    "contacts; not binding probability, affinity, experimental blocking, Docking "
    "Gold, or final submission evidence."
)
RECEPTORS = ("8x6b", "9e6y")
SOURCES = ("V4D_OPEN_MULTI_SEED", "V4H_STAGE1_SEED917")
OUTPUT_NAME = "v6_dual_source_residue_contact_targets_v2.tsv.gz"
RECEIPT_NAME = "RUN_RECEIPT.json"
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
    "teacher_state", "candidate_id", "sequence_sha256", "parent_framework_cluster",
    "receptor", "vhh_sequence_index", "vhh_aa", "pvrig_uniprot_position",
    "contact_frequency_pose_weighted",
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
    v4h_pair_tsv: Path,
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
        "v4h_pair_tsv": v4h_pair_tsv,
    }
    input_hashes = {name: sha256_file(path) for name, path in inputs.items()}
    if expected_hashes is not None:
        require(dict(expected_hashes) == input_hashes, f"input_hashes_mismatch:{input_hashes}")

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

    v4h_fields, v4h_rows = read_tsv(v4h_pair_tsv)
    require(V4H_REQUIRED <= set(v4h_fields), f"v4h_fields_missing:{sorted(V4H_REQUIRED-set(v4h_fields))}")
    v4h_values: dict[tuple[str, str, int], float] = {}
    v4h_receptors: defaultdict[str, set[str]] = defaultdict(set)
    observed_pairs: set[tuple[str, str, int, int]] = set()
    for row in v4h_rows:
        candidate = row["candidate_id"].strip()
        require(candidate in source_ids["V4H_STAGE1_SEED917"], f"v4h_candidate_not_in_source:{candidate}")
        receptor, index, _aa = validate_identity(row, training[candidate], label="v4h")
        pvrig_position = int(row["pvrig_uniprot_position"])
        pair_key = (candidate, receptor, index, pvrig_position)
        require(pair_key not in observed_pairs, f"duplicate_v4h_pair:{pair_key}")
        observed_pairs.add(pair_key)
        frequency = finite_unit(row["contact_frequency_pose_weighted"], "v4h_pair_frequency")
        key = (candidate, receptor, index)
        v4h_values[key] = max(v4h_values.get(key, 0.0), frequency)
        v4h_receptors[candidate].add(receptor)
    require(set(v4h_receptors) == source_ids["V4H_STAGE1_SEED917"], "v4h_candidate_closure_failed")
    for candidate in sorted(source_ids["V4H_STAGE1_SEED917"]):
        require(v4h_receptors[candidate] == set(RECEPTORS), f"v4h_candidate_missing_receptor:{candidate}")

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
                        "target": v4h_values.get((candidate, receptor, index), 0.0),
                        "variance": 0.0, "uncertainty": 1.0, "observed": 1, "expected": 1,
                        "aggregation": "max_pair_frequency_compatibility",
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
        "schema_version": f"{SCHEMA_VERSION}_receipt",
        "status": "PASS_DUAL_SOURCE_CONTACT_TARGETS_V2",
        "claim_boundary": CLAIM_BOUNDARY,
        "teacher_source_is_model_feature": False,
        "source_semantics": {
            "V4D_OPEN_MULTI_SEED": "exact pose-any-contact marginal then equal observed-seed mean",
            "V4H_STAGE1_SEED917": "max pair-frequency compatibility marginal from frozen single-seed teacher",
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
            "v4h_pair_rows": len(v4h_rows),
            "partial_v4d_candidate_receptors": len(partial_v4d_candidate_receptors),
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
    value.add_argument("--v4h-pair-tsv", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--expected-source-count", action="append", required=True)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    receipt = build_targets(
        args.training_tsv, args.v4d_marginal_tsv, args.v4h_pair_tsv, args.output_dir,
        expected_source_counts=parse_counts(args.expected_source_count),
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
