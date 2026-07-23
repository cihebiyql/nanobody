#!/usr/bin/env python3
"""Validate the 150K M2 table and S0+M2 predictions before terminal publication."""

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


def validate_m2(path: Path, expected_rows: int) -> tuple[dict[str, tuple[str, str]], int]:
    mapping: dict[str, tuple[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None, "m2_header_missing")
        metadata = {"schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster", "model_split", "asset_lane", "monomer_sha256"}
        features = [field for field in reader.fieldnames if field not in metadata]
        require(len(features) == 126, f"m2_feature_count:{len(features)}")
        for row in reader:
            candidate = row["candidate_id"]
            require(candidate and candidate not in mapping, f"m2_candidate_duplicate:{candidate}")
            mapping[candidate] = (row["sequence_sha256"], row["parent_framework_cluster"])
            for field in features:
                require(math.isfinite(float(row[field])), f"m2_nonfinite:{candidate}:{field}")
    require(len(mapping) == expected_rows, f"m2_rows:{len(mapping)}")
    require(len({value[0] for value in mapping.values()}) == expected_rows, "m2_sequence_not_unique")
    return mapping, len(features)


def validate_predictions(path: Path, expected: dict[str, tuple[str, str]]) -> int:
    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None, "prediction_header_missing")
        numeric = [field for field in reader.fieldnames if field.endswith(("__R8", "__R9", "__Rdual_exact_min"))]
        require(numeric, "prediction_numeric_columns_missing")
        for row in reader:
            candidate = row["candidate_id"]
            require(candidate in expected and candidate not in seen, f"prediction_candidate_invalid:{candidate}")
            require(row.get("parent_framework_cluster") == expected[candidate][1], f"prediction_parent_mismatch:{candidate}")
            for field in numeric:
                require(math.isfinite(float(row[field])), f"prediction_nonfinite:{candidate}:{field}")
            seen.add(candidate)
    require(seen == set(expected), "prediction_candidate_set_mismatch")
    return len(numeric)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m2-tsv", type=Path, required=True)
    parser.add_argument("--prediction-tsv", type=Path, required=True)
    parser.add_argument("--m2-receipt", type=Path, required=True)
    parser.add_argument("--prediction-receipt", type=Path, required=True)
    parser.add_argument("--staging-terminal", type=Path, required=True)
    parser.add_argument("--environment-preflight", type=Path, required=True)
    parser.add_argument("--expected-rows", type=int, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.m2_tsv, args.prediction_tsv, args.m2_receipt, args.prediction_receipt, args.staging_terminal, args.environment_preflight):
        require(path.is_file() and not path.is_symlink(), f"input_invalid:{path}")
    mapping, feature_count = validate_m2(args.m2_tsv, args.expected_rows)
    prediction_numeric_count = validate_predictions(args.prediction_tsv, mapping)
    payload = {
        "schema_version": "pvrig_top150k_m2_s0m2_recovery_validation_v2",
        "status": "PASS_TOP150K_M2_S0M2_RECOVERY_VALIDATION",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows": len(mapping),
        "m2_feature_count": feature_count,
        "prediction_numeric_count": prediction_numeric_count,
        "all_numeric_finite": True,
        "candidate_sequence_parent_closed": True,
        "runtime": {"python_executable": os.path.realpath(os.sys.executable), "python": platform.python_version()},
        "inputs": {str(path): sha256_file(path) for path in (args.m2_tsv, args.prediction_tsv, args.m2_receipt, args.prediction_receipt, args.staging_terminal, args.environment_preflight)},
        "truth_access": {"candidate_docking_pose_files_opened": 0, "teacher_labels_opened": 0},
    }
    atomic_json(args.receipt, payload)
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
