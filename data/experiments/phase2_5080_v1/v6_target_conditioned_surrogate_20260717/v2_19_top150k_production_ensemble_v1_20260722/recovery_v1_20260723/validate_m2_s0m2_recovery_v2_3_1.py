#!/usr/bin/env python3
"""Validate completed 150K M2/S0+M2 outputs and publish an audit receipt.

V2.3 fixes the V2 validator's metadata allowlist: ``claim_boundary`` is
provenance metadata emitted by the frozen M2 materializer, not a 127th numeric
feature.  The validator also closes the output hashes against both producer
receipts before a terminal receipt may be published.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class ValidationError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValidationError(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


M2_PREFIX_METADATA = [
    "schema_version",
    "candidate_id",
    "sequence_sha256",
    "parent_framework_cluster",
    "model_split",
    "asset_lane",
    "monomer_sha256",
]


def validate_m2(
    path: Path, expected_rows: int, expected_features: list[str]
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    mapping: dict[str, tuple[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None, "m2_header_missing")
        expected_header = [*M2_PREFIX_METADATA, *expected_features, "claim_boundary"]
        require(reader.fieldnames == expected_header, "m2_header_not_exact_training_schema")
        features = list(expected_features)
        require(len(features) == 126, f"m2_feature_count:{len(features)}")
        require(len(features) == len(set(features)), "m2_feature_names_not_unique")
        require(all("__" in field for field in features), "m2_feature_name_not_structural")
        for row in reader:
            candidate = row["candidate_id"]
            require(candidate and candidate not in mapping, f"m2_candidate_duplicate:{candidate}")
            sequence_sha = row["sequence_sha256"]
            parent = row["parent_framework_cluster"]
            require(sequence_sha and parent, f"m2_identity_metadata_missing:{candidate}")
            require(row.get("claim_boundary", "").strip() != "", f"m2_claim_boundary_missing:{candidate}")
            mapping[candidate] = (sequence_sha, parent)
            for field in features:
                require(math.isfinite(float(row[field])), f"m2_nonfinite:{candidate}:{field}")
    require(len(mapping) == expected_rows, f"m2_rows:{len(mapping)}")
    require(len({value[0] for value in mapping.values()}) == expected_rows, "m2_sequence_not_unique")
    return mapping, features


def validate_predictions(path: Path, expected: dict[str, tuple[str, str]]) -> list[str]:
    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None, "prediction_header_missing")
        numeric = [field for field in reader.fieldnames if field.endswith(("__R8", "__R9", "__Rdual_exact_min"))]
        require(len(numeric) == 6, f"prediction_numeric_columns:{len(numeric)}")
        for row in reader:
            candidate = row["candidate_id"]
            require(candidate in expected and candidate not in seen, f"prediction_candidate_invalid:{candidate}")
            require(row.get("sequence_sha256") == expected[candidate][0], f"prediction_sequence_mismatch:{candidate}")
            require(row.get("parent_framework_cluster") == expected[candidate][1], f"prediction_parent_mismatch:{candidate}")
            require(row.get("claim_boundary", "").strip() != "", f"prediction_claim_boundary_missing:{candidate}")
            for field in numeric:
                require(math.isfinite(float(row[field])), f"prediction_nonfinite:{candidate}:{field}")
            seen.add(candidate)
    require(seen == set(expected), "prediction_candidate_set_mismatch")
    return numeric


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"json_not_object:{path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m2-tsv", type=Path, required=True)
    parser.add_argument("--prediction-tsv", type=Path, required=True)
    parser.add_argument("--m2-receipt", type=Path, required=True)
    parser.add_argument("--prediction-receipt", type=Path, required=True)
    parser.add_argument("--staging-terminal", type=Path, required=True)
    parser.add_argument("--environment-preflight", type=Path, required=True)
    parser.add_argument("--training-m2-tsv", type=Path, required=True)
    parser.add_argument("--training-m2-receipt", type=Path, required=True)
    parser.add_argument("--model-artifact", type=Path, required=True)
    parser.add_argument("--normalization-receipt", type=Path, required=True)
    parser.add_argument("--equivalence-receipt", type=Path, required=True)
    parser.add_argument("--expected-rows", type=int, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    inputs = (
        args.m2_tsv,
        args.prediction_tsv,
        args.m2_receipt,
        args.prediction_receipt,
        args.staging_terminal,
        args.environment_preflight,
        args.training_m2_tsv,
        args.training_m2_receipt,
        args.model_artifact,
        args.normalization_receipt,
        args.equivalence_receipt,
    )
    for path in inputs:
        require(path.is_file() and not path.is_symlink(), f"input_invalid:{path}")

    training_receipt = load_json(args.training_m2_receipt)
    expected_features = training_receipt.get("feature_names")
    require(isinstance(expected_features, list), "training_feature_names_missing")
    require(len(expected_features) == 126, "training_feature_count")
    require(training_receipt.get("counts", {}).get("features") == 126, "training_receipt_features")
    require(training_receipt.get("output", {}).get("sha256") == sha256_file(args.training_m2_tsv), "training_m2_hash")
    mapping, features = validate_m2(args.m2_tsv, args.expected_rows, expected_features)
    prediction_numeric = validate_predictions(args.prediction_tsv, mapping)
    m2_sha = sha256_file(args.m2_tsv)
    prediction_sha = sha256_file(args.prediction_tsv)

    m2_receipt = load_json(args.m2_receipt)
    require(m2_receipt.get("status") == "PASS_CANONICAL10644_M2_126D_FEATURES_MATERIALIZED", "m2_receipt_status")
    require(m2_receipt.get("counts", {}).get("rows") == args.expected_rows, "m2_receipt_rows")
    require(m2_receipt.get("counts", {}).get("features") == 126, "m2_receipt_features")
    require(m2_receipt.get("feature_names") == features, "m2_receipt_feature_names")
    require(m2_receipt.get("output", {}).get("sha256") == m2_sha, "m2_receipt_output_hash")

    prediction_receipt = load_json(args.prediction_receipt)
    require(prediction_receipt.get("status") == "PASS_LABEL_FREE_PRODUCTION_MULTIMODAL_INFERENCE", "prediction_receipt_status")
    require(prediction_receipt.get("counts", {}).get("rows") == args.expected_rows, "prediction_receipt_rows")
    require(prediction_receipt.get("output", {}).get("rows") == args.expected_rows, "prediction_output_rows")
    require(prediction_receipt.get("output", {}).get("sha256") == prediction_sha, "prediction_receipt_output_hash")
    require(prediction_receipt.get("invariants", {}).get("teacher_label_values_read") == 0, "prediction_teacher_access")
    require(prediction_receipt.get("invariants", {}).get("candidate_docking_pose_files_opened") == 0, "prediction_pose_access")

    staging = load_json(args.staging_terminal)
    require(staging.get("status") == "PASS_TOP150K_LABEL_FREE_NBB2_ARCHIVE_STAGING", "staging_status")
    environment = load_json(args.environment_preflight)
    require(environment.get("status") == "PASS_TOP150K_M2_S0M2_ENVIRONMENT_PREFLIGHT", "environment_status")

    payload = {
        "schema_version": "pvrig_top150k_m2_s0m2_recovery_validation_v2_3_1",
        "status": "PASS_TOP150K_M2_S0M2_RECOVERY_VALIDATION",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows": len(mapping),
        "m2_feature_count": len(features),
        "prediction_numeric_count": len(prediction_numeric),
        "all_numeric_finite": True,
        "candidate_sequence_parent_closed": True,
        "producer_receipt_hashes_closed": True,
        "runtime": {"python_executable": os.path.realpath(os.sys.executable), "python": platform.python_version()},
        "inputs": {str(path): sha256_file(path) for path in inputs},
        "truth_access": {"candidate_docking_pose_files_opened": 0, "teacher_labels_opened": 0},
    }
    atomic_json(args.receipt, payload)
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
