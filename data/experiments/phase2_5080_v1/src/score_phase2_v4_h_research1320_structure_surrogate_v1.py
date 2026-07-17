#!/usr/bin/env python3
"""Score V4-H research1320 with the frozen OPEN_TRAIN structure surrogate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA_VERSION = "phase2_v4_h_research1320_structure_surrogate_v1"
STATUS = "COMPLETE_LABEL_FREE_V4_H_RESEARCH1320_STRUCTURE_SURROGATE_RANKING"
EXPECTED_FEATURE_SHA256 = "c778c420792c095073d0cbf2e60e754ff5c1273e8c032eb06104223db8e365a5"
EXPECTED_CONFIG_SHA256 = "1d6419bae5e9ee4c365f1efb4f36a828bbd7f84dfebbf89f529ce62e745d334f"
EXPECTED_FIT_SHA256 = "15cd307b6b79cdec50cdd4b2266b5a129c9690607bffc3795248030e3da76d3a"
EXPECTED_ROWS = 1320
METADATA_FIELDS = {
    "schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster",
    "target_patch_id", "design_mode", "monomer_sha256", "claim_boundary",
}
CLAIM_BOUNDARY = (
    "Research-only sequence-to-monomer-structure surrogate estimate of "
    "independent dual-receptor computational docking geometry R_dual_min; not "
    "Docking Gold, binding probability, affinity, competition, experimental "
    "blocking, formal validation, or final submission authority."
)


class ScoringError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ScoringError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_fit(payload: Any, prefix: str) -> tuple[float, np.ndarray, np.ndarray, np.ndarray]:
    required = [f"{prefix}__{name}" for name in ("intercept", "coefficient", "center", "scale")]
    require(all(name in payload.files for name in required), f"fit_arrays_missing:{prefix}")
    intercept = np.asarray(payload[required[0]], dtype=np.float64)
    coefficient = np.asarray(payload[required[1]], dtype=np.float64)
    center = np.asarray(payload[required[2]], dtype=np.float64)
    scale = np.asarray(payload[required[3]], dtype=np.float64)
    require(intercept.shape == (1,), "fit_intercept_shape_invalid")
    require(coefficient.ndim == center.ndim == scale.ndim == 1, "fit_vector_rank_invalid")
    require(len(coefficient) == len(center) == len(scale), "fit_vector_length_mismatch")
    require(np.isfinite(intercept).all() and np.isfinite(coefficient).all() and np.isfinite(center).all() and np.isfinite(scale).all(), "fit_nonfinite")
    require(np.all(scale > 0), "fit_scale_nonpositive")
    return float(intercept[0]), coefficient, center, scale


def score(
    features_path: Path,
    config_path: Path,
    fits_path: Path,
    output_dir: Path,
    *,
    expected_feature_sha256: str = EXPECTED_FEATURE_SHA256,
    expected_config_sha256: str = EXPECTED_CONFIG_SHA256,
    expected_fit_sha256: str = EXPECTED_FIT_SHA256,
    expected_rows: int = EXPECTED_ROWS,
) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_exists:{output_dir}")
    require(sha256_file(features_path) == expected_feature_sha256, "feature_table_hash_mismatch")
    require(sha256_file(config_path) == expected_config_sha256, "scoring_config_hash_mismatch")
    require(sha256_file(fits_path) == expected_fit_sha256, "scoring_fits_hash_mismatch")
    config = json.loads(config_path.read_text())
    require(config.get("fit_rows") == 226, "scoring_config_fit_rows_invalid")
    require(config.get("primary_target") == "R_dual_min", "scoring_config_target_invalid")
    require(config.get("open_development_target_values_accessed") == 0, "scoring_config_dev_boundary_invalid")
    require(config.get("V4_F_test32_labels_accessed") == 0, "scoring_config_test_boundary_invalid")
    hyperparameters = config.get("full_train_hyperparameters") or {}
    require(hyperparameters.get("fusion_structure_weight") == 1.0, "late_fusion_not_structure_only")
    require(hyperparameters.get("residual_gamma") == 0.0, "residual_not_structure_only")
    with features_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    require(len(rows) == expected_rows, f"feature_row_count_invalid:{len(rows)}")
    require(len({row["candidate_id"] for row in rows}) == expected_rows, "candidate_ids_not_unique")
    feature_names = [name for name in fields if name not in METADATA_FIELDS]
    require(feature_names == config.get("structure_feature_names"), "structure_feature_schema_mismatch")
    x = np.asarray([[float(row[name]) for name in feature_names] for row in rows], dtype=np.float64)
    require(x.shape == (expected_rows, 126), f"feature_matrix_shape_invalid:{x.shape}")
    require(np.isfinite(x).all(), "feature_matrix_nonfinite")
    with np.load(fits_path) as fits:
        intercept, coefficient, center, scale = load_fit(fits, "M2_structure")
    require(len(coefficient) == 126, "structure_fit_dimension_invalid")
    prediction = intercept + ((x - center) / scale) @ coefficient
    require(np.isfinite(prediction).all(), "structure_prediction_nonfinite")
    order = sorted(range(expected_rows), key=lambda index: (-float(prediction[index]), rows[index]["candidate_id"]))
    rank_by_index = {index: rank for rank, index in enumerate(order, start=1)}
    output_rows = []
    denominator = max(expected_rows - 1, 1)
    for index in order:
        row = rows[index]
        rank = rank_by_index[index]
        output_rows.append({
            "schema_version": SCHEMA_VERSION,
            "candidate_id": row["candidate_id"],
            "sequence_sha256": row["sequence_sha256"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "target_patch_id": row["target_patch_id"],
            "design_mode": row["design_mode"],
            "predicted_R_dual_min_structure_only": f"{prediction[index]:.12g}",
            "research_rank": rank,
            "research_rank_percentile": f"{(expected_rows - rank) / denominator:.12g}",
            "selected_full_train_behavior": "M2_STRUCTURE_ONLY",
            "claim_boundary": CLAIM_BOUNDARY,
        })
    output_dir.mkdir(parents=True)
    output = output_dir / "v4h_research1320_structure_surrogate_ranking_v1.tsv"
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(output_rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader(); writer.writerows(output_rows)
    atomic_write(output, buffer.getvalue().encode("utf-8"))
    quantiles = np.quantile(prediction, [0.0, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 1.0])
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "input_hashes": {
            "features": expected_feature_sha256,
            "config": expected_config_sha256,
            "fits": expected_fit_sha256,
        },
        "row_count": expected_rows,
        "unique_candidate_ids": expected_rows,
        "feature_count": len(feature_names),
        "selected_full_train_behavior": "M2_STRUCTURE_ONLY",
        "selection_reason": "OPEN_TRAIN parent-group CV selected fusion structure weight 1.0 and residual gamma 0.0; both adaptive families reduce to the structure-only Ridge.",
        "prediction_summary": {
            name: float(value) for name, value in zip(
                ("min", "q05", "q10", "q25", "median", "q75", "q90", "q95", "max"), quantiles
            )
        },
        "output": {"path": output.name, "sha256": sha256_file(output)},
        "sealed_boundary": {
            "V4_H_docking_result_files_opened": 0,
            "V4_H_status_files_opened": 0,
            "V4_H_pose_files_opened": 0,
            "V4_H_geometry_labels_accessed": 0,
            "V4_F_test32_rows_accessed": 0,
            "formal_or_prospective_authority": False,
        },
    }
    audit_path = output_dir / "v4h_research1320_structure_surrogate_ranking_v1.audit.json"
    atomic_write(audit_path, (json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"))
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "ranking_sha256": sha256_file(output),
        "audit_sha256": sha256_file(audit_path),
        "row_count": expected_rows,
        "selected_full_train_behavior": "M2_STRUCTURE_ONLY",
        "V4_H_geometry_labels_accessed": 0,
        "V4_F_test32_rows_accessed": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    receipt_path = output_dir / "v4h_research1320_structure_surrogate_ranking_v1.receipt.json"
    atomic_write(receipt_path, (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": STATUS,
        "row_count": expected_rows,
        "selected_full_train_behavior": "M2_STRUCTURE_ONLY",
        "prediction_summary": audit["prediction_summary"],
        "ranking_sha256": sha256_file(output),
        "receipt_sha256": sha256_file(receipt_path),
        "V4_H_geometry_labels_accessed": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--fits", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = score(args.features, args.config, args.fits, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
