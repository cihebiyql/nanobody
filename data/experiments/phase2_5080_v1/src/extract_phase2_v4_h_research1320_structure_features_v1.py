#!/usr/bin/env python3
"""Extract label-free invariant monomer features for V4-H research1320."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import stat
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import extract_phase2_v4_d_open258_structure_features_v1 as shared  # noqa: E402


SCHEMA_VERSION = "phase2_v4_h_research1320_structure_features_v1"
STATUS = "PASS_V4_H_RESEARCH1320_LABEL_FREE_STRUCTURE_FEATURES"
EXPECTED_INPUT_MANIFEST_SHA256 = "099a8360e07cb724d3790d33349c1e54df57f5d675e50875df1c1b2f7aa90711"
EXPECTED_CANDIDATE_MANIFEST_SHA256 = "f02cfeaac9775442bb1748c7bb63413a1077b5df11f9cd7214e983d0e51c0551"
EXPECTED_ROWS = 1320
CLAIM_BOUNDARY = (
    "Label-free rigid-motion-invariant V4-H monomer descriptors for research "
    "development only; no docking result, pose, geometry label, binding, "
    "affinity, or experimental blocking truth."
)


class FeatureError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FeatureError(message)


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
        raise FeatureError(f"missing_file:{label}:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"not_regular_or_symlink:{label}:{path}")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require_regular(path, "tsv")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def unique_sequence_range(sequence: str, fragment: str, label: str) -> str:
    require(fragment and len(fragment) >= 3, f"cdr_fragment_too_short:{label}")
    require(sequence.count(fragment) == 1, f"cdr_fragment_not_unique:{label}")
    start = sequence.index(fragment) + 1
    return f"{start}-{start + len(fragment) - 1}"


def derive_cdr_ranges(candidate: Mapping[str, str]) -> dict[str, str]:
    sequence = candidate["sequence"]
    return {
        "CDR1": unique_sequence_range(sequence, candidate["cdr1_after"], "CDR1"),
        "CDR2": unique_sequence_range(sequence, candidate["cdr2_after"], "CDR2"),
        "CDR3": unique_sequence_range(sequence, candidate["cdr3_after"], "CDR3"),
    }


def extract(
    input_root: Path,
    candidate_manifest: Path,
    output_dir: Path,
    *,
    expected_input_manifest_sha256: str = EXPECTED_INPUT_MANIFEST_SHA256,
    expected_candidate_manifest_sha256: str = EXPECTED_CANDIDATE_MANIFEST_SHA256,
    expected_rows: int = EXPECTED_ROWS,
) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_exists:{output_dir}")
    input_manifest = input_root / "research1320_structure_inputs_v1.tsv"
    input_receipt = input_root / "MATERIALIZATION_RECEIPT_V1.json"
    require_regular(input_manifest, "structure_input_manifest")
    require_regular(input_receipt, "structure_input_receipt")
    require(sha256_file(input_manifest) == expected_input_manifest_sha256, "structure_input_manifest_hash_mismatch")
    require(sha256_file(candidate_manifest) == expected_candidate_manifest_sha256, "candidate_manifest_hash_mismatch")
    receipt = json.loads(input_receipt.read_text())
    require(receipt.get("status") == "PASS_LABEL_FREE_STRUCTURE_INPUTS_MATERIALIZED", "structure_input_receipt_status_invalid")
    require(receipt.get("output_manifest_sha256") == expected_input_manifest_sha256, "structure_input_receipt_hash_mismatch")
    forbidden = receipt.get("forbidden_path_channels_opened") or {}
    require(all(forbidden.get(key) == 0 for key in ("results", "status", "pose", "test32")), "forbidden_channel_opened")
    input_fields, input_rows = load_tsv(input_manifest)
    candidate_fields, candidates = load_tsv(candidate_manifest)
    input_required = {
        "candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster",
        "target_patch_id", "design_mode", "monomer_relative_path", "monomer_sha256",
        "source_chain",
    }
    candidate_required = {
        "candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster",
        "target_patch_id", "design_mode", "cdr1_after", "cdr2_after", "cdr3_after",
    }
    require(input_required <= set(input_fields), "structure_input_fields_missing")
    require(candidate_required <= set(candidate_fields), "candidate_fields_missing")
    require(len(input_rows) == len(candidates) == expected_rows, "row_count_invalid")
    require(len({row["candidate_id"] for row in input_rows}) == expected_rows, "structure_input_ids_not_unique")
    require(len({row["candidate_id"] for row in candidates}) == expected_rows, "candidate_ids_not_unique")
    candidate_by_key = {(row["candidate_id"], row["sequence_sha256"]): row for row in candidates}
    input_keys = [(row["candidate_id"], row["sequence_sha256"]) for row in input_rows]
    require(set(input_keys) == set(candidate_by_key), "candidate_structure_composite_closure_failed")
    feature_rows: list[dict[str, Any]] = []
    feature_names: list[str] | None = None
    for row, key in zip(input_rows, input_keys):
        candidate = candidate_by_key[key]
        for field in ("sequence", "parent_framework_cluster", "target_patch_id", "design_mode"):
            require(row[field] == candidate[field], f"candidate_structure_metadata_mismatch:{row['candidate_id']}:{field}")
        relative = Path(row["monomer_relative_path"])
        require(not relative.is_absolute() and ".." not in relative.parts, f"unsafe_monomer_relative_path:{row['candidate_id']}")
        pdb = input_root / relative
        require_regular(pdb, f"monomer_pdb:{row['candidate_id']}")
        require(sha256_file(pdb) == row["monomer_sha256"], f"monomer_hash_mismatch:{row['candidate_id']}")
        ranges = derive_cdr_ranges(candidate)
        try:
            values = shared.structure_features(pdb, row["source_chain"], ranges)
        except shared.FeatureError as exc:
            raise FeatureError(f"structure_feature_failure:{row['candidate_id']}:{exc}") from exc
        if feature_names is None:
            feature_names = sorted(values)
        require(sorted(values) == feature_names, f"feature_schema_drift:{row['candidate_id']}")
        feature_rows.append({
            "schema_version": SCHEMA_VERSION,
            "candidate_id": row["candidate_id"],
            "sequence_sha256": row["sequence_sha256"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "target_patch_id": row["target_patch_id"],
            "design_mode": row["design_mode"],
            "monomer_sha256": row["monomer_sha256"],
            **{name: f"{values[name]:.9g}" for name in feature_names},
            "claim_boundary": CLAIM_BOUNDARY,
        })
    require(feature_names is not None and len(feature_names) == 126, "feature_schema_invalid")
    output_dir.mkdir(parents=True)
    table = output_dir / "research1320_structure_features_v1.tsv"
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(feature_rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader(); writer.writerows(feature_rows)
    atomic_write(table, buffer.getvalue().encode("utf-8"))
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "inputs": {
            "structure_input_manifest_sha256": expected_input_manifest_sha256,
            "structure_input_receipt_sha256": sha256_file(input_receipt),
            "candidate_manifest_sha256": expected_candidate_manifest_sha256,
        },
        "output": {
            "path": table.name,
            "sha256": sha256_file(table),
            "row_count": len(feature_rows),
            "feature_count": len(feature_names),
            "feature_names": feature_names,
            "all_numeric_values_finite": True,
        },
        "sealed_boundary": {
            "docking_result_files_opened": 0,
            "status_files_opened": 0,
            "pose_files_opened": 0,
            "geometry_label_values_read": 0,
            "test32_rows_opened": 0,
        },
    }
    audit_path = table.with_suffix(table.suffix + ".audit.json")
    atomic_write(audit_path, (json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    completion = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "feature_table_sha256": sha256_file(table),
        "feature_audit_sha256": sha256_file(audit_path),
        "row_count": len(feature_rows),
        "feature_count": len(feature_names),
        "docking_result_files_opened": 0,
        "geometry_label_values_read": 0,
        "test32_rows_opened": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    completion_path = output_dir / "research1320_structure_features_v1.receipt.json"
    atomic_write(completion_path, (json.dumps(completion, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": STATUS,
        "row_count": len(feature_rows),
        "feature_count": len(feature_names),
        "feature_table_sha256": sha256_file(table),
        "receipt_sha256": sha256_file(completion_path),
        "geometry_label_values_read": 0,
        "test32_rows_opened": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = extract(args.input_root, args.candidate_manifest, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
