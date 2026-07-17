#!/usr/bin/env python3
"""Score V4-H research1320 with the frozen OPEN_TRAIN sequence surrogate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import torch


SCHEMA_VERSION = "phase2_v4_h_research1320_sequence_surrogate_v1"
STATUS = "COMPLETE_LABEL_FREE_V4_H_RESEARCH1320_SEQUENCE_SURROGATE_RANKING"
EXPECTED_CANDIDATE_SHA256 = "f02cfeaac9775442bb1748c7bb63413a1077b5df11f9cd7214e983d0e51c0551"
EXPECTED_SEQUENCE_MANIFEST_SHA256 = "9d5004b362ad9b51c5bfd11eec4c9e6c2313cc61554b6fe7d15a39a9f796207f"
EXPECTED_EMBEDDING_MANIFEST_SHA256 = "504deb5a0f1106c87e8b1fb557148891e0287fdd22db959806398ecd63052d80"
EXPECTED_EMBEDDING_SUMMARY_SHA256 = "5e7793d5694730aa2a5b0cbe6c7887eba1d973fc5ddbb4d02f8e9f5425f67c4e"
EXPECTED_EMBEDDING_SHARD_SHA256 = "3e4e95eec0a0bbdb649f6a954c5df4d998d0da7476978c945046e757933d7de1"
EXPECTED_EMBEDDING_CONFIG_SHA256 = "e525cb725bc5b9ea93c2f91ba84209cc3992d1e65e0e0d78f79b7c219ba33636"
EXPECTED_CONFIG_SHA256 = "1d6419bae5e9ee4c365f1efb4f36a828bbd7f84dfebbf89f529ce62e745d334f"
EXPECTED_FIT_SHA256 = "15cd307b6b79cdec50cdd4b2266b5a129c9690607bffc3795248030e3da76d3a"
EXPECTED_ROWS = 1320
CHANNELS = (("vhhbert", 768), ("esm2", 320), ("physchem", 27))
CLAIM_BOUNDARY = (
    "Research-only sequence surrogate estimate of independent dual-receptor "
    "computational docking geometry R_dual_min; not Docking Gold, binding "
    "probability, affinity, competition, experimental blocking, formal "
    "validation, or final submission authority."
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


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_table(path: Path, delimiter: str) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        fields = list(reader.fieldnames or [])
        return fields, [dict(row) for row in reader]


def load_fit(payload: Any) -> tuple[float, np.ndarray, np.ndarray, np.ndarray]:
    names = [f"M1_sequence__{name}" for name in ("intercept", "coefficient", "center", "scale")]
    require(all(name in payload.files for name in names), "fit_arrays_missing:M1_sequence")
    intercept = np.asarray(payload[names[0]], dtype=np.float64)
    coefficient = np.asarray(payload[names[1]], dtype=np.float64)
    center = np.asarray(payload[names[2]], dtype=np.float64)
    scale = np.asarray(payload[names[3]], dtype=np.float64)
    require(intercept.shape == (1,), "fit_intercept_shape_invalid")
    require(coefficient.shape == center.shape == scale.shape == (1115,), "fit_vector_shape_invalid")
    require(
        np.isfinite(intercept).all()
        and np.isfinite(coefficient).all()
        and np.isfinite(center).all()
        and np.isfinite(scale).all(),
        "fit_nonfinite",
    )
    require(np.all(scale > 0), "fit_scale_nonpositive")
    return float(intercept[0]), coefficient, center, scale


def score(
    candidates_path: Path,
    sequence_manifest_path: Path,
    embedding_manifest_path: Path,
    embedding_summary_path: Path,
    embedding_shard_path: Path,
    config_path: Path,
    fits_path: Path,
    output_dir: Path,
    *,
    expected_candidate_sha256: str = EXPECTED_CANDIDATE_SHA256,
    expected_sequence_manifest_sha256: str = EXPECTED_SEQUENCE_MANIFEST_SHA256,
    expected_embedding_manifest_sha256: str = EXPECTED_EMBEDDING_MANIFEST_SHA256,
    expected_embedding_summary_sha256: str = EXPECTED_EMBEDDING_SUMMARY_SHA256,
    expected_embedding_shard_sha256: str = EXPECTED_EMBEDDING_SHARD_SHA256,
    expected_embedding_config_sha256: str = EXPECTED_EMBEDDING_CONFIG_SHA256,
    expected_config_sha256: str = EXPECTED_CONFIG_SHA256,
    expected_fit_sha256: str = EXPECTED_FIT_SHA256,
    expected_rows: int = EXPECTED_ROWS,
) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_exists:{output_dir}")
    pinned = (
        (candidates_path, expected_candidate_sha256, "candidate_table_hash_mismatch"),
        (sequence_manifest_path, expected_sequence_manifest_sha256, "sequence_manifest_hash_mismatch"),
        (embedding_manifest_path, expected_embedding_manifest_sha256, "embedding_manifest_hash_mismatch"),
        (embedding_summary_path, expected_embedding_summary_sha256, "embedding_summary_hash_mismatch"),
        (embedding_shard_path, expected_embedding_shard_sha256, "embedding_shard_hash_mismatch"),
        (config_path, expected_config_sha256, "scoring_config_hash_mismatch"),
        (fits_path, expected_fit_sha256, "scoring_fits_hash_mismatch"),
    )
    for path, expected, error in pinned:
        require(sha256_file(path) == expected, error)

    config = json.loads(config_path.read_text())
    require(config.get("fit_rows") == 226, "scoring_config_fit_rows_invalid")
    require(config.get("primary_target") == "R_dual_min", "scoring_config_target_invalid")
    require(config.get("open_development_target_values_accessed") == 0, "scoring_config_dev_boundary_invalid")
    require(config.get("V4_F_test32_labels_accessed") == 0, "scoring_config_test_boundary_invalid")
    require((config.get("feature_dimensions") or {}).get("sequence") == 1115, "sequence_feature_dimension_invalid")
    require((config.get("full_train_hyperparameters") or {}).get("sequence_alpha") == 1000.0, "sequence_alpha_invalid")

    _candidate_fields, candidates = load_table(candidates_path, "\t")
    require(len(candidates) == expected_rows, f"candidate_row_count_invalid:{len(candidates)}")
    require(len({row["candidate_id"] for row in candidates}) == expected_rows, "candidate_ids_not_unique")
    require(len({row["sequence_sha256"] for row in candidates}) == expected_rows, "candidate_sequence_hashes_not_unique")
    candidate_by_hash = {row["sequence_sha256"]: row for row in candidates}

    _sequence_fields, sequence_rows = load_table(sequence_manifest_path, ",")
    _embedding_fields, embedding_rows = load_table(embedding_manifest_path, ",")
    require(len(sequence_rows) == len(embedding_rows) == expected_rows, "embedding_input_row_count_invalid")
    sequence_hashes = [row["sequence_sha256"] for row in sequence_rows]
    embedding_hashes = [row["sequence_sha256"] for row in embedding_rows]
    require(sequence_hashes == sorted(sequence_hashes), "sequence_manifest_not_hash_sorted")
    require(embedding_hashes == sequence_hashes, "embedding_manifest_order_mismatch")
    require(set(sequence_hashes) == set(candidate_by_hash), "candidate_embedding_hash_set_mismatch")
    require(
        [int(row["shard_index"]) for row in embedding_rows] == list(range(expected_rows)),
        "embedding_shard_indices_invalid",
    )
    require(
        {row["config_sha256"] for row in embedding_rows} == {expected_embedding_config_sha256},
        "embedding_manifest_config_mismatch",
    )

    summary = json.loads(embedding_summary_path.read_text())
    require(summary.get("sequence_count") == expected_rows, "embedding_summary_count_invalid")
    require(summary.get("vhh_sequence_count") == expected_rows, "embedding_summary_vhh_count_invalid")
    require(summary.get("antigen_sequence_count") == 0, "embedding_summary_antigen_count_invalid")
    require(summary.get("device") == "cuda", "embedding_summary_device_invalid")
    require(summary.get("cuda_device_name") == "NVIDIA GeForce RTX 5080", "embedding_summary_gpu_invalid")
    require(summary.get("config_sha256") == expected_embedding_config_sha256, "embedding_summary_config_mismatch")
    require(summary.get("sequence_manifest_sha256") == expected_sequence_manifest_sha256, "embedding_summary_input_mismatch")
    require(summary.get("embedding_manifest_sha256") == expected_embedding_manifest_sha256, "embedding_summary_manifest_mismatch")

    payload = torch.load(embedding_shard_path, map_location="cpu", weights_only=True)
    require(payload.get("sequence_sha256") == sequence_hashes, "embedding_shard_order_mismatch")
    expected_shard_config = sha256_text(json.dumps(
        {"config": summary["config"], "sequence_sha256": sequence_hashes},
        separators=(",", ":"), sort_keys=True,
    ))
    require(payload.get("config_sha256") == expected_shard_config, "embedding_shard_config_mismatch")
    arrays: list[np.ndarray] = []
    for channel, dimension in CHANNELS:
        tensor = payload.get(channel)
        require(isinstance(tensor, torch.Tensor), f"embedding_tensor_missing:{channel}")
        require(tuple(tensor.shape) == (expected_rows, dimension), f"embedding_shape_invalid:{channel}")
        array = tensor.detach().cpu().float().numpy().astype(np.float64, copy=False)
        require(np.isfinite(array).all(), f"embedding_nonfinite:{channel}")
        arrays.append(array)
    available = payload.get("vhhbert_available")
    require(
        isinstance(available, torch.Tensor)
        and tuple(available.shape) == (expected_rows,)
        and bool(available.bool().all()),
        "vhhbert_availability_invalid",
    )
    x = np.concatenate(arrays, axis=1)
    require(x.shape == (expected_rows, 1115), "sequence_matrix_shape_invalid")

    with np.load(fits_path) as fits:
        intercept, coefficient, center, scale = load_fit(fits)
    prediction = intercept + ((x - center) / scale) @ coefficient
    require(np.isfinite(prediction).all(), "sequence_prediction_nonfinite")

    ordered_indices = sorted(
        range(expected_rows),
        key=lambda index: (-float(prediction[index]), candidate_by_hash[sequence_hashes[index]]["candidate_id"]),
    )
    denominator = max(expected_rows - 1, 1)
    output_rows: list[dict[str, Any]] = []
    for rank, index in enumerate(ordered_indices, start=1):
        candidate = candidate_by_hash[sequence_hashes[index]]
        output_rows.append({
            "schema_version": SCHEMA_VERSION,
            "candidate_id": candidate["candidate_id"],
            "sequence_sha256": sequence_hashes[index],
            "parent_framework_cluster": candidate["parent_framework_cluster"],
            "target_patch_id": candidate["target_patch_id"],
            "design_mode": candidate["design_mode"],
            "predicted_R_dual_min_sequence_only": f"{prediction[index]:.12g}",
            "research_rank": rank,
            "research_rank_percentile": f"{(expected_rows - rank) / denominator:.12g}",
            "frozen_model": "M1_SEQUENCE_ONLY",
            "claim_boundary": CLAIM_BOUNDARY,
        })

    output_dir.mkdir(parents=True)
    ranking_path = output_dir / "v4h_research1320_sequence_surrogate_ranking_v1.tsv"
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(output_rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(output_rows)
    atomic_write(ranking_path, buffer.getvalue().encode("utf-8"))
    quantiles = np.quantile(prediction, [0.0, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 1.0])
    input_hashes = {
        "candidates": expected_candidate_sha256,
        "sequence_manifest": expected_sequence_manifest_sha256,
        "embedding_manifest": expected_embedding_manifest_sha256,
        "embedding_summary": expected_embedding_summary_sha256,
        "embedding_shard": expected_embedding_shard_sha256,
        "scoring_config": expected_config_sha256,
        "scoring_fits": expected_fit_sha256,
    }
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "input_hashes": input_hashes,
        "row_count": expected_rows,
        "unique_candidate_ids": expected_rows,
        "feature_count": 1115,
        "channel_order": [name for name, _dimension in CHANNELS],
        "frozen_model": "M1_SEQUENCE_ONLY",
        "prediction_summary": {
            name: float(value) for name, value in zip(
                ("min", "q05", "q10", "q25", "median", "q75", "q90", "q95", "max"), quantiles
            )
        },
        "output": {"path": ranking_path.name, "sha256": sha256_file(ranking_path)},
        "sealed_boundary": {
            "V4_H_docking_result_files_opened": 0,
            "V4_H_status_files_opened": 0,
            "V4_H_pose_files_opened": 0,
            "V4_H_geometry_labels_accessed": 0,
            "V4_F_test32_rows_accessed": 0,
            "formal_or_prospective_authority": False,
        },
    }
    audit_path = output_dir / "v4h_research1320_sequence_surrogate_ranking_v1.audit.json"
    atomic_write(audit_path, (json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"))
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "ranking_sha256": sha256_file(ranking_path),
        "audit_sha256": sha256_file(audit_path),
        "row_count": expected_rows,
        "frozen_model": "M1_SEQUENCE_ONLY",
        "V4_H_geometry_labels_accessed": 0,
        "V4_F_test32_rows_accessed": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    receipt_path = output_dir / "v4h_research1320_sequence_surrogate_ranking_v1.receipt.json"
    atomic_write(receipt_path, (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": STATUS,
        "row_count": expected_rows,
        "frozen_model": "M1_SEQUENCE_ONLY",
        "prediction_summary": audit["prediction_summary"],
        "ranking_sha256": sha256_file(ranking_path),
        "receipt_sha256": sha256_file(receipt_path),
        "V4_H_geometry_labels_accessed": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--sequence-manifest", type=Path, required=True)
    parser.add_argument("--embedding-manifest", type=Path, required=True)
    parser.add_argument("--embedding-summary", type=Path, required=True)
    parser.add_argument("--embedding-shard", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--fits", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = score(
        args.candidates,
        args.sequence_manifest,
        args.embedding_manifest,
        args.embedding_summary,
        args.embedding_shard,
        args.config,
        args.fits,
        args.output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
