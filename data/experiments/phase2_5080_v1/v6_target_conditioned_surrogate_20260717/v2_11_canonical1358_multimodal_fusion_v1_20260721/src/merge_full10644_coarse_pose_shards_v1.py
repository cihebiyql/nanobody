#!/usr/bin/env python3
"""Validate and merge frozen V2.5 coarse-pose shard outputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import stat
from collections import Counter
from pathlib import Path
from typing import Any


PLAN_SCHEMA = "pvrig_v2_11_canonical10644_coarse_pose_shard_plan_v1"
PLAN_STATUS = "PASS_CANONICAL10644_COARSE_POSE_SHARD_PLAN"
FROZEN_RECEIPT_SCHEMA = "pvrig_v2_5_label_free_coarse_pose_pilot_v1"
FROZEN_RECEIPT_STATUS = "PASS_LABEL_FREE_COARSE_POSE_FEATURES"
FEATURE_SCHEMA = "pvrig_v2_5_label_free_coarse_pose_36d_v1"
OUTPUT_SCHEMA = "pvrig_v2_11_canonical10644_coarse_pose_36d_closure_v1"
READY_STATUS = "PASS_CANONICAL10644_COARSE_POSE_36D_SHARD_CLOSURE"
CLAIM_BOUNDARY = (
    "Merged frozen V2.5 36D label-free coarse rigid-body features from hash-closed "
    "VHH monomers and two fixed public PVRIG structures; no candidate Docking pose, "
    "teacher label, binding, affinity, competition, or blocking truth."
)
RECEPTOR_SUFFIXES = (
    "pose_count", "acceptable_count", "acceptable_fraction", "best_composite",
    "top20_composite_mean", "top20_composite_std", "top20_composite_iqr",
    "top20_score_entropy", "best_shape", "best_hotspot", "best_charge",
    "best_clash_fraction", "best_cdr_contact_fraction", "best_cdr3_orientation",
)
DUAL_FIELDS = (
    "dual__common_acceptable_count", "dual__common_acceptable_fraction",
    "dual__acceptable_jaccard", "dual__best_min_composite",
    "dual__top20_min_composite_mean", "dual__top20_min_composite_std",
    "dual__best_receptor_gap", "dual__pose_score_correlation",
)
FEATURE_FIELDS = tuple(
    f"{target}__{suffix}" for target in ("8x6b", "9e6y") for suffix in RECEPTOR_SUFFIXES
) + DUAL_FIELDS
OUTPUT_FIELDS = ("candidate_id", "monomer_sha256", "feature_schema") + FEATURE_FIELDS


class MergeError(RuntimeError):
    """Fail-closed merge error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MergeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ordered_id_sha256(candidate_ids: list[str]) -> str:
    return hashlib.sha256(("\n".join(candidate_ids) + "\n").encode("utf-8")).hexdigest()


def require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise MergeError(f"missing_file:{label}:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"not_regular_file:{label}:{path}")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists() and not path.is_symlink(), f"output_exists:{path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_tsv(path: Path, required_fields: tuple[str, ...], exact_header: bool = False) -> list[dict[str, str]]:
    require_regular_file(path, "tsv")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None, f"missing_header:{path}")
        require(len(reader.fieldnames) == len(set(reader.fieldnames)), f"duplicate_header:{path}")
        if exact_header:
            require(tuple(reader.fieldnames) == required_fields, f"feature_header_mismatch:{path}")
        else:
            missing = [field for field in required_fields if field not in reader.fieldnames]
            require(not missing, f"missing_fields:{path}:{','.join(missing)}")
        return list(reader)


def same_resolved_path(left: str, right: Path) -> bool:
    return Path(left).resolve() == right.resolve()


def validate_target(
    receipt: dict[str, Any], key: str, path: Path, expected_sha256: str, shard_id: str
) -> None:
    record = receipt.get("inputs", {}).get(key, {})
    require(record.get("sha256") == expected_sha256, f"target_receipt_sha256_mismatch:{shard_id}:{key}")
    require(same_resolved_path(record.get("path", ""), path), f"target_receipt_path_mismatch:{shard_id}:{key}")


def merge(
    plan_json: Path,
    expected_plan_sha256: str,
    shard_output_root: Path,
    target_npz: Path,
    target_npz_sha256: str,
    target_pdb8: Path,
    target_pdb8_sha256: str,
    target_pdb9: Path,
    target_pdb9_sha256: str,
    output_dir: Path,
    expected_rows: int,
) -> dict[str, Any]:
    plan_json = plan_json.resolve()
    shard_output_root = shard_output_root.resolve()
    output_dir = output_dir.resolve()
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_dir_exists:{output_dir}")
    require_regular_file(plan_json, "shard_plan")
    actual_plan_sha256 = sha256_file(plan_json)
    require(actual_plan_sha256 == expected_plan_sha256, "shard_plan_sha256_mismatch")
    plan = json.loads(plan_json.read_text(encoding="utf-8"))
    require(plan.get("schema_version") == PLAN_SCHEMA, "shard_plan_schema_mismatch")
    require(plan.get("status") == PLAN_STATUS, "shard_plan_status_mismatch")
    require(plan.get("counts", {}).get("candidates") == expected_rows, "shard_plan_row_count_mismatch")
    require(16 <= plan.get("counts", {}).get("shards", 0) <= 32, "shard_plan_count_invalid")

    source = Path(plan["source"]["structure_manifest_path"]).resolve()
    require_regular_file(source, "source_structure_manifest")
    source_sha256 = sha256_file(source)
    require(source_sha256 == plan["source"]["structure_manifest_sha256"], "source_manifest_sha256_mismatch")
    source_rows = read_tsv(source, ("candidate_id", "monomer_sha256", "model_split", "asset_lane"))
    require(len(source_rows) == expected_rows, "source_manifest_row_count_mismatch")
    source_ids = [row["candidate_id"] for row in source_rows]
    require(len(source_ids) == len(set(source_ids)), "duplicate_source_candidate_id")
    require(ordered_id_sha256(source_ids) == plan["ordered_candidate_id_sha256"],
            "source_candidate_order_sha256_mismatch")
    source_by_id = {row["candidate_id"]: row for row in source_rows}

    target_specs = (
        (target_npz.resolve(), target_npz_sha256, "target_npz"),
        (target_pdb8.resolve(), target_pdb8_sha256, "target_pdb8"),
        (target_pdb9.resolve(), target_pdb9_sha256, "target_pdb9"),
    )
    for path, expected_sha256, label in target_specs:
        require_regular_file(path, label)
        require(sha256_file(path) == expected_sha256, f"target_sha256_mismatch:{label}")

    feature_by_id: dict[str, dict[str, str]] = {}
    shard_audit: list[dict[str, Any]] = []
    observed_shard_ids: set[str] = set()
    for shard in plan["shards"]:
        shard_id = shard["shard_id"]
        require(shard_id not in observed_shard_ids, f"duplicate_shard_id:{shard_id}")
        observed_shard_ids.add(shard_id)
        manifest = (plan_json.parent / shard["manifest_relative_path"]).resolve()
        require_regular_file(manifest, f"shard_manifest:{shard_id}")
        manifest_sha256 = sha256_file(manifest)
        require(manifest_sha256 == shard["manifest_sha256"], f"shard_manifest_sha256_mismatch:{shard_id}")
        manifest_rows = read_tsv(manifest, ("candidate_id", "monomer_pdb", "monomer_sha256"))
        manifest_ids = [row["candidate_id"] for row in manifest_rows]
        require(len(manifest_rows) == shard["candidate_count"], f"shard_manifest_count_mismatch:{shard_id}")
        require(ordered_id_sha256(manifest_ids) == shard["ordered_candidate_id_sha256"],
                f"shard_manifest_order_sha256_mismatch:{shard_id}")

        shard_dir = shard_output_root / shard_id
        feature_path = shard_dir / "coarse_pose_features_36d.tsv"
        receipt_path = shard_dir / "FEATURE_RECEIPT.json"
        feature_rows = read_tsv(feature_path, OUTPUT_FIELDS, exact_header=True)
        require(len(feature_rows) == len(manifest_rows), f"feature_row_count_mismatch:{shard_id}")
        require([row["candidate_id"] for row in feature_rows] == manifest_ids,
                f"feature_candidate_order_mismatch:{shard_id}")
        require_regular_file(receipt_path, f"feature_receipt:{shard_id}")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        require(receipt.get("schema_version") == FROZEN_RECEIPT_SCHEMA,
                f"feature_receipt_schema_mismatch:{shard_id}")
        require(receipt.get("status") == FROZEN_RECEIPT_STATUS,
                f"feature_receipt_status_mismatch:{shard_id}")
        require(receipt.get("candidate_count") == len(feature_rows),
                f"feature_receipt_count_mismatch:{shard_id}")
        require(receipt.get("feature_count") == 36, f"feature_receipt_width_mismatch:{shard_id}")
        require(receipt.get("pose_count_per_receptor") == 300, f"pose_count_mismatch:{shard_id}")
        require(receipt.get("all_features_finite") is True, f"receipt_nonfinite:{shard_id}")
        boundary = receipt.get("sealed_boundary", {})
        for key in ("candidate_docking_pose_files_opened", "teacher_label_files_opened", "v4_f_files_opened"):
            require(boundary.get(key) == 0, f"sealed_boundary_violation:{shard_id}:{key}")
        candidate_input = receipt.get("inputs", {}).get("candidate_manifest", {})
        require(candidate_input.get("sha256") == manifest_sha256,
                f"candidate_manifest_receipt_sha256_mismatch:{shard_id}")
        require(same_resolved_path(candidate_input.get("path", ""), manifest),
                f"candidate_manifest_receipt_path_mismatch:{shard_id}")
        validate_target(receipt, "target_npz", target_npz, target_npz_sha256, shard_id)
        validate_target(receipt, "target_pdb8", target_pdb8, target_pdb8_sha256, shard_id)
        validate_target(receipt, "target_pdb9", target_pdb9, target_pdb9_sha256, shard_id)
        feature_sha256 = sha256_file(feature_path)
        output_records = receipt.get("outputs", {})
        require(len(output_records) == 1, f"feature_receipt_output_count_invalid:{shard_id}")
        receipt_output_path, receipt_output_sha = next(iter(output_records.items()))
        require(same_resolved_path(receipt_output_path, feature_path),
                f"feature_receipt_output_path_mismatch:{shard_id}")
        require(receipt_output_sha == feature_sha256, f"feature_receipt_output_sha256_mismatch:{shard_id}")

        for manifest_row, feature_row in zip(manifest_rows, feature_rows):
            candidate_id = feature_row["candidate_id"]
            require(candidate_id in source_by_id, f"unknown_feature_candidate:{candidate_id}")
            require(candidate_id not in feature_by_id, f"duplicate_feature_candidate:{candidate_id}")
            require(feature_row["monomer_sha256"] == manifest_row["monomer_sha256"] ==
                    source_by_id[candidate_id]["monomer_sha256"], f"monomer_sha256_join_mismatch:{candidate_id}")
            require(feature_row["feature_schema"] == FEATURE_SCHEMA,
                    f"feature_schema_mismatch:{candidate_id}")
            for field in FEATURE_FIELDS:
                try:
                    value = float(feature_row[field])
                except ValueError as exc:
                    raise MergeError(f"feature_not_numeric:{candidate_id}:{field}") from exc
                require(math.isfinite(value), f"feature_not_finite:{candidate_id}:{field}")
            feature_by_id[candidate_id] = feature_row
        shard_audit.append({
            "shard_id": shard_id,
            "candidate_count": len(feature_rows),
            "manifest_sha256": manifest_sha256,
            "feature_tsv_sha256": feature_sha256,
            "feature_receipt_sha256": sha256_file(receipt_path),
            "runtime_seconds": receipt.get("runtime_seconds"),
        })

    require(len(feature_by_id) == expected_rows, f"merged_candidate_count_invalid:{len(feature_by_id)}")
    require(set(feature_by_id) == set(source_ids), "merged_candidate_set_not_exact")
    merged_rows = [feature_by_id[candidate_id] for candidate_id in source_ids]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(OUTPUT_FIELDS), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(merged_rows)
    output_dir.mkdir(parents=True)
    output_path = output_dir / "canonical10644_coarse_pose_features_36d_v1.tsv"
    atomic_write(output_path, buffer.getvalue().encode("utf-8"))
    receipt = {
        "schema_version": OUTPUT_SCHEMA,
        "status": READY_STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "counts": {
            "candidates": len(merged_rows),
            "features": len(FEATURE_FIELDS),
            "shards": len(shard_audit),
            "splits": dict(sorted(Counter(row["model_split"] for row in source_rows).items())),
            "asset_lanes": dict(sorted(Counter(row["asset_lane"] for row in source_rows).items())),
        },
        "inputs": {
            "shard_plan": {"path": str(plan_json), "sha256": actual_plan_sha256},
            "structure_manifest": {"path": str(source), "sha256": source_sha256},
            "target_npz": {"path": str(target_npz.resolve()), "sha256": target_npz_sha256},
            "target_pdb8": {"path": str(target_pdb8.resolve()), "sha256": target_pdb8_sha256},
            "target_pdb9": {"path": str(target_pdb9.resolve()), "sha256": target_pdb9_sha256},
        },
        "shards": shard_audit,
        "output": {"path": str(output_path), "sha256": sha256_file(output_path)},
        "invariants": {
            "candidate_set_exact": True,
            "frozen_structure_manifest_order_preserved": True,
            "all_features_finite": True,
            "monomer_sha256_join_exact": True,
            "all_shard_and_target_hashes_verified": True,
            "frozen_v2_5_feature_code_modified": False,
            "candidate_docking_pose_files_opened": 0,
            "teacher_label_files_opened": 0,
        },
    }
    receipt_path = output_dir / "canonical10644_coarse_pose_features_36d_v1.receipt.json"
    atomic_write(receipt_path, (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": READY_STATUS,
        "rows": len(merged_rows),
        "features": len(FEATURE_FIELDS),
        "output_sha256": sha256_file(output_path),
        "receipt_sha256": sha256_file(receipt_path),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--plan-json", type=Path, required=True)
    result.add_argument("--expected-plan-sha256", required=True)
    result.add_argument("--shard-output-root", type=Path, required=True)
    result.add_argument("--target-npz", type=Path, required=True)
    result.add_argument("--target-npz-sha256", required=True)
    result.add_argument("--target-pdb8", type=Path, required=True)
    result.add_argument("--target-pdb8-sha256", required=True)
    result.add_argument("--target-pdb9", type=Path, required=True)
    result.add_argument("--target-pdb9-sha256", required=True)
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--expected-rows", type=int, default=10644)
    return result


def main() -> int:
    args = parser().parse_args()
    result = merge(
        args.plan_json,
        args.expected_plan_sha256,
        args.shard_output_root,
        args.target_npz,
        args.target_npz_sha256,
        args.target_pdb8,
        args.target_pdb8_sha256,
        args.target_pdb9,
        args.target_pdb9_sha256,
        args.output_dir,
        args.expected_rows,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
