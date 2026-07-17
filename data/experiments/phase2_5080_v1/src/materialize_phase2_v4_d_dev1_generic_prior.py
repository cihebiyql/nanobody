#!/usr/bin/env python3
"""Materialize the hash-bound label-free generic prior for V4-D-DEV1.

The output contains only sequence identity/provenance and generic-model scores.
It deliberately excludes Docking, geometry, tier, blocking, affinity, and
experimental-label columns.  The prospective-test rows are label-free model
inputs only; no prospective Docking result is opened or copied.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence


EXP_DIR = Path("/mnt/d/work/抗体/data/experiments/phase2_5080_v1")
DEFAULT_SPLIT = EXP_DIR / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv"
DEFAULT_SOURCE = EXP_DIR / "prepared/pvrig_teacher_formal_v1_candidates/scored_candidates_v1.csv"
DEFAULT_OUTPUT = EXP_DIR / "prepared/pvrig_v4_d_dev1_open258_v1/generic_prior_v1"
EXPECTED_SPLIT_SHA256 = "c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd"
EXPECTED_SOURCE_SHA256 = "dd97835cfa3e39229d3ebddfe37768c7a8346a6237e35d2dbe16dc3d16ab965b"
EXPECTED_SOURCE_ROWS = 7087
EXPECTED_SPLIT_COUNTS = {
    "OPEN_TRAIN": 226,
    "OPEN_DEVELOPMENT": 32,
    "PROSPECTIVE_COMPUTATIONAL_TEST": 32,
}
OUTPUT_BASENAME = "v4d_dev1_fullqc290_label_free_generic_prior_v1.csv"
AUDIT_BASENAME = "v4d_dev1_fullqc290_label_free_generic_prior_v1.audit.json"
CHECKSUM_BASENAME = "SHA256SUMS"
OUTPUT_FIELDS = (
    "candidate_id",
    "sequence_sha256",
    "generic_binding_prior",
    "model_uncertainty",
    "model_disagreement",
    "generic_binding_prior_seed_43",
    "generic_binding_prior_seed_53",
    "generic_binding_prior_seed_67",
    "generic_binding_model",
    "generic_binding_train_summary_sha256",
    "target_sequence_sha256",
    "model_claim_boundary",
)
REQUIRED_SOURCE_FIELDS = frozenset({"vhh_sequence", *OUTPUT_FIELDS})
FORBIDDEN_SOURCE_COLUMN_PATTERNS = (
    re.compile(r"(?:^|_)dock(?:ing)?(?:_|$)", re.IGNORECASE),
    re.compile(r"geometry", re.IGNORECASE),
    re.compile(r"(?:^|_)r_(?:dual|8x6b|9e6y)(?:_|$)", re.IGNORECASE),
    re.compile(r"occlusion", re.IGNORECASE),
    re.compile(r"(?:^|_)pose(?:_|$)", re.IGNORECASE),
    re.compile(r"blocker", re.IGNORECASE),
    re.compile(r"hotspot_overlap", re.IGNORECASE),
    re.compile(r"supporting_pose", re.IGNORECASE),
    re.compile(r"geometry_tier", re.IGNORECASE),
    re.compile(r"(?:^|_)g[1-5](?:_|$)", re.IGNORECASE),
    re.compile(r"(?:binding|blocking|affinity|experimental)_label", re.IGNORECASE),
)
CLAIM_BOUNDARY = (
    "Hash-bound label-free generic binding-model prior for DEV-only sequence-surrogate "
    "input. It is not Docking or geometry evidence, a PVRIG binding probability, affinity, "
    "experimental blocking, prospective-test evaluation, or formal V4-F authority."
)


class GenericPriorError(RuntimeError):
    """A fail-closed generic-prior materialization error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GenericPriorError(message)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def require_regular(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise GenericPriorError(f"missing_file:{label}:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"not_regular_or_is_symlink:{label}:{path}")


def sequence_digest(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def header_digest(fields: Sequence[str]) -> str:
    raw = json.dumps(list(fields), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def forbidden_columns(fields: Sequence[str]) -> list[str]:
    return sorted(
        field
        for field in fields
        if any(pattern.search(field) is not None for pattern in FORBIDDEN_SOURCE_COLUMN_PATTERNS)
    )


def finite_number(raw: str, *, field: str, candidate_id: str, lower: float = 0.0, upper: float | None = None) -> None:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise GenericPriorError(f"invalid_numeric:{field}:{candidate_id}") from exc
    require(math.isfinite(value) and value >= lower, f"numeric_below_range:{field}:{candidate_id}")
    if upper is not None:
        require(value <= upper, f"numeric_above_range:{field}:{candidate_id}")


def read_split(path: Path, expected_sha256: str) -> list[dict[str, str]]:
    require_regular(path, "split_manifest")
    require(digest(path) == expected_sha256, "split_manifest_sha256_mismatch")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(
            {"candidate_id", "sequence_sha256", "sequence", "model_split"} <= set(reader.fieldnames or ()),
            "split_manifest_header_invalid",
        )
        rows = list(reader)
    expected_rows = sum(EXPECTED_SPLIT_COUNTS.values())
    require(len(rows) == expected_rows, "split_manifest_row_count_invalid")
    seen: set[str] = set()
    counts = {name: 0 for name in EXPECTED_SPLIT_COUNTS}
    for row in rows:
        candidate_id = row.get("candidate_id", "")
        require(candidate_id and candidate_id not in seen, f"split_candidate_duplicate_or_empty:{candidate_id}")
        seen.add(candidate_id)
        split = row.get("model_split", "")
        require(split in counts, f"split_role_invalid:{candidate_id}:{split}")
        counts[split] += 1
        sequence = row.get("sequence", "")
        sequence_sha256 = row.get("sequence_sha256", "")
        require(bool(sequence) and sequence_digest(sequence) == sequence_sha256, f"split_sequence_hash_invalid:{candidate_id}")
    require(counts == EXPECTED_SPLIT_COUNTS, f"split_counts_invalid:{counts}")
    return rows


def read_source(path: Path, expected_sha256: str, expected_rows: int) -> tuple[list[str], dict[str, dict[str, str]]]:
    require_regular(path, "generic_prior_source")
    require(digest(path) == expected_sha256, "generic_prior_source_sha256_mismatch")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or ())
        require(len(fields) == len(set(fields)), "generic_prior_source_duplicate_header")
        require(REQUIRED_SOURCE_FIELDS <= set(fields), "generic_prior_source_required_field_missing")
        require(forbidden_columns(fields) == [], "generic_prior_source_forbidden_label_column")
        rows = list(reader)
    require(len(rows) == expected_rows, "generic_prior_source_row_count_invalid")
    by_id: dict[str, dict[str, str]] = {}
    for row in rows:
        candidate_id = row.get("candidate_id", "")
        require(candidate_id and candidate_id not in by_id, f"generic_prior_source_duplicate_or_empty_id:{candidate_id}")
        by_id[candidate_id] = row
    return fields, by_id


def build_extract(
    split_rows: Sequence[Mapping[str, str]],
    source_by_id: Mapping[str, Mapping[str, str]],
) -> list[dict[str, str]]:
    split_ids = {row["candidate_id"] for row in split_rows}
    require(split_ids <= set(source_by_id), "generic_prior_source_missing_split_candidate")
    output: list[dict[str, str]] = []
    for split_row in split_rows:
        candidate_id = split_row["candidate_id"]
        source = source_by_id[candidate_id]
        require(source["sequence_sha256"] == split_row["sequence_sha256"], f"sequence_sha_mismatch:{candidate_id}")
        require(source["vhh_sequence"] == split_row["sequence"], f"sequence_mismatch:{candidate_id}")
        for field in (
            "generic_binding_prior",
            "generic_binding_prior_seed_43",
            "generic_binding_prior_seed_53",
            "generic_binding_prior_seed_67",
        ):
            finite_number(source[field], field=field, candidate_id=candidate_id, upper=1.0)
        for field in ("model_uncertainty", "model_disagreement"):
            finite_number(source[field], field=field, candidate_id=candidate_id)
        require(bool(source["generic_binding_model"]), f"generic_binding_model_empty:{candidate_id}")
        for field in ("generic_binding_train_summary_sha256", "target_sequence_sha256"):
            require(re.fullmatch(r"[0-9a-f]{64}", source[field]) is not None, f"invalid_hash:{field}:{candidate_id}")
        require(bool(source["model_claim_boundary"]), f"model_claim_boundary_empty:{candidate_id}")
        output.append({field: source[field] for field in OUTPUT_FIELDS})
    require(len(output) == sum(EXPECTED_SPLIT_COUNTS.values()), "generic_prior_extract_row_count_invalid")
    return output


def numeric_validation_summary(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    fields = (
        "generic_binding_prior",
        "model_uncertainty",
        "model_disagreement",
        "generic_binding_prior_seed_43",
        "generic_binding_prior_seed_53",
        "generic_binding_prior_seed_67",
    )
    ranges: dict[str, dict[str, float]] = {}
    for field in fields:
        values = [float(row[field]) for row in rows]
        ranges[field] = {"min": min(values), "max": max(values)}
    return {
        "all_numeric_values_finite": True,
        "probability_fields_within_closed_unit_interval": True,
        "uncertainty_and_disagreement_nonnegative": True,
        "ranges": ranges,
    }


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def materialize(
    split_path: Path,
    source_path: Path,
    output_dir: Path,
    *,
    expected_split_sha256: str = EXPECTED_SPLIT_SHA256,
    expected_source_sha256: str = EXPECTED_SOURCE_SHA256,
    expected_source_rows: int = EXPECTED_SOURCE_ROWS,
) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), "output_directory_already_exists")
    split_rows = read_split(split_path, expected_split_sha256)
    source_fields, source_by_id = read_source(source_path, expected_source_sha256, expected_source_rows)
    rows = build_extract(split_rows, source_by_id)
    output_dir.mkdir(parents=True)
    try:
        output_path = output_dir / OUTPUT_BASENAME
        with output_path.open("x", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        output_sha256 = digest(output_path)
        audit_path = output_dir / AUDIT_BASENAME
        audit = {
            "schema_version": "phase2_v4_d_dev1_label_free_generic_prior_v1",
            "status": "READY_LABEL_FREE_GENERIC_PRIOR_290_NOT_LAUNCH_AUTHORIZED",
            "source": {
                "path": str(source_path),
                "sha256": expected_source_sha256,
                "row_count": expected_source_rows,
                "header_sha256": header_digest(source_fields),
                "forbidden_docking_geometry_or_label_columns": forbidden_columns(source_fields),
            },
            "split_manifest": {
                "path": str(split_path),
                "sha256": expected_split_sha256,
                "row_count": len(split_rows),
                "split_counts": EXPECTED_SPLIT_COUNTS,
            },
            "output": {
                "path": OUTPUT_BASENAME,
                "sha256": output_sha256,
                "row_count": len(rows),
                "exact_header": list(OUTPUT_FIELDS),
                "candidate_id_sequence_sha256_exact_closure": True,
            },
            "numeric_validation": numeric_validation_summary(rows),
            "sealed_data_boundary": {
                "prospective_test_label_free_prior_rows_materialized": EXPECTED_SPLIT_COUNTS["PROSPECTIVE_COMPUTATIONAL_TEST"],
                "prospective_test_docking_result_files_opened": 0,
                "test32_metric_values_read": 0,
                "test32_label_rows_emitted": 0,
            },
            "development_only": True,
            "remote_execution_authorized": False,
            "formal_v4_f_unlock_eligible": False,
            "claim_boundary": CLAIM_BOUNDARY,
        }
        write_json(audit_path, audit)
        checksum_path = output_dir / CHECKSUM_BASENAME
        checksum_path.write_text(
            f"{output_sha256}  {OUTPUT_BASENAME}\n{digest(audit_path)}  {AUDIT_BASENAME}\n",
            encoding="ascii",
        )
        return {
            "status": audit["status"],
            "output_path": str(output_path),
            "output_sha256": output_sha256,
            "audit_path": str(audit_path),
            "audit_sha256": digest(audit_path),
            "row_count": len(rows),
            "test32_metric_values_read": 0,
            "remote_execution_authorized": False,
            "formal_v4_f_unlock_eligible": False,
        }
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split-manifest", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    print(json.dumps(materialize(args.split_manifest, args.source, args.output_dir), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
