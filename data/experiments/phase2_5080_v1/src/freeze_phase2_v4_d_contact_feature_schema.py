#!/usr/bin/env python3
"""Freeze label-free, cross-seed-stable V3 contact features for V4-D training."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCHEMA_VERSION = "phase2_v4_d_contact_feature_schema_v2"
EXPECTED_FEATURE_SCHEMA_VERSION = "pvrig_candidate_v2_3_label_free_residue_contact_features_v3"
EXPECTED_FEATURE_CSV_SHA256 = "f48de64d253a76bc9cff19ab1348c1655be7306828289b28f9a04e5b95471e7d"
EXPECTED_FEATURE_AUDIT_SHA256 = "eb63f16aacef2ed3d7ed0a755bfc3c49a590e09248b28643b94dc7e2c4e27e29"
EXPECTED_FEATURE_RECEIPT_SHA256 = "b12c0ff0ce6760db7169ec3616dddaf05786e5ca795354f639ef2bf87c370e2b"
EXPECTED_ROWS = 7087
MIN_PAIRWISE_SEED_SPEARMAN = 0.60
MIN_BETWEEN_TO_WITHIN_RATIO = 0.50
LENGTH_CONFOUNDED_FEATURES = {
    "contact_cdr_hotspot_mass_length_confounded_diagnostic",
    "contact_cdr3_hotspot_mass_length_confounded_diagnostic",
}
CLAIM_BOUNDARY = (
    "Label-free feature stability selection for a fixed-PVRIG computational docking "
    "surrogate; not docking, binding, affinity, competition, or blocking evidence."
)


class FeatureSchemaError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def snapshot_file(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": path,
        "bytes": payload,
        "sha256": sha256_bytes(payload),
        "size_bytes": len(payload),
    }


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def validate_inputs(
    feature_csv: Path,
    feature_audit: Path,
    feature_receipt: Path,
    *,
    enforce_production_hashes: bool,
    expected_rows: int,
) -> tuple[
    pd.DataFrame,
    dict[str, Any],
    dict[str, Any],
    tuple[int, ...],
    tuple[str, ...],
    dict[str, dict[str, Any]],
]:
    snapshots = {
        "feature_csv": snapshot_file(feature_csv),
        "feature_audit": snapshot_file(feature_audit),
        "feature_release_receipt": snapshot_file(feature_receipt),
    }
    if enforce_production_hashes:
        if snapshots["feature_csv"]["sha256"] != EXPECTED_FEATURE_CSV_SHA256:
            raise FeatureSchemaError("feature_csv_sha256_mismatch")
        if snapshots["feature_audit"]["sha256"] != EXPECTED_FEATURE_AUDIT_SHA256:
            raise FeatureSchemaError("feature_audit_sha256_mismatch")
        if (
            snapshots["feature_release_receipt"]["sha256"]
            != EXPECTED_FEATURE_RECEIPT_SHA256
        ):
            raise FeatureSchemaError("feature_receipt_sha256_mismatch")
    audit = json.loads(snapshots["feature_audit"]["bytes"].decode("utf-8"))
    receipt = json.loads(
        snapshots["feature_release_receipt"]["bytes"].decode("utf-8")
    )
    if (
        audit.get("status") != "PASS"
        or audit.get("output_sha256") != snapshots["feature_csv"]["sha256"]
    ):
        raise FeatureSchemaError("feature_audit_status_or_output_hash_mismatch")
    if audit.get("feature_schema_version") != EXPECTED_FEATURE_SCHEMA_VERSION:
        raise FeatureSchemaError("feature_audit_schema_version_mismatch")
    if (
        receipt.get("status") != "PASS"
        or receipt.get("feature_schema_version") != EXPECTED_FEATURE_SCHEMA_VERSION
        or receipt.get("output_sha256") != snapshots["feature_csv"]["sha256"]
        or receipt.get("audit_sha256") != snapshots["feature_audit"]["sha256"]
        or int(receipt.get("output_row_count", -1)) != expected_rows
    ):
        raise FeatureSchemaError("feature_receipt_closure_mismatch")
    boundary = audit.get("label_free_contract", {})
    if any(
        int(boundary.get(field, -1)) != 0
        for field in ("docking_label_inputs_read", "v4d_job_state_read", "v4d_raw_results_read")
    ):
        raise FeatureSchemaError("feature_audit_not_label_free")
    frame = pd.read_csv(io.BytesIO(snapshots["feature_csv"]["bytes"]))
    if len(frame) != expected_rows or frame["candidate_id"].duplicated().any():
        raise FeatureSchemaError("feature_row_count_or_candidate_identity_mismatch")
    seeds = tuple(sorted(int(row["seed"]) for row in audit.get("checkpoints", [])))
    if len(seeds) < 3 or len(set(seeds)) != len(seeds):
        raise FeatureSchemaError("at_least_three_unique_feature_seeds_required")
    features = tuple(str(value) for value in audit.get("feature_names", []))
    if not features:
        raise FeatureSchemaError("feature_names_missing")
    diagnostic_features = set(
        audit.get("feature_policy", {}).get(
            "diagnostic_only_length_confounded_features", []
        )
    )
    if diagnostic_features != LENGTH_CONFOUNDED_FEATURES:
        raise FeatureSchemaError("length_confounded_feature_policy_mismatch")
    required = {
        column
        for feature in features
        for column in (
            *(f"seed{seed}_{feature}" for seed in seeds),
            f"{feature}_seed_mean",
            f"{feature}_seed_std",
        )
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise FeatureSchemaError(f"feature_columns_missing:{','.join(missing[:5])}")
    values = frame[list(required)].apply(pd.to_numeric, errors="coerce").to_numpy()
    if not np.isfinite(values).all():
        raise FeatureSchemaError("feature_values_non_finite")
    return frame, audit, receipt, seeds, features, snapshots


def feature_stability(
    frame: pd.DataFrame, seeds: tuple[int, ...], features: tuple[str, ...]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for feature in features:
        columns = [f"seed{seed}_{feature}" for seed in seeds]
        correlation = frame[columns].corr(method="spearman").to_numpy(dtype=float)
        pairwise = [
            float(correlation[left, right])
            for left in range(len(seeds))
            for right in range(left + 1, len(seeds))
        ]
        between = float(pd.to_numeric(frame[f"{feature}_seed_mean"]).std(ddof=1))
        within = float(pd.to_numeric(frame[f"{feature}_seed_std"]).mean())
        ratio = between / max(within, 1e-12)
        min_spearman = min(pairwise)
        cross_seed_stable = (
            np.isfinite(min_spearman)
            and min_spearman >= MIN_PAIRWISE_SEED_SPEARMAN
            and ratio >= MIN_BETWEEN_TO_WITHIN_RATIO
        )
        length_confounded = feature in LENGTH_CONFOUNDED_FEATURES
        selected = cross_seed_stable and not length_confounded
        output.append(
            {
                "feature": feature,
                "selected": bool(selected),
                "cross_seed_stable": bool(cross_seed_stable),
                "length_confounded": length_confounded,
                "minimum_pairwise_seed_spearman": min_spearman,
                "median_pairwise_seed_spearman": float(np.median(pairwise)),
                "between_candidate_standard_deviation": between,
                "mean_within_candidate_seed_standard_deviation": within,
                "between_to_within_ratio": ratio,
            }
        )
    return output


def run(
    feature_csv: Path,
    feature_audit: Path,
    feature_receipt: Path,
    output_path: Path,
    *,
    enforce_production_hashes: bool = True,
    expected_rows: int = EXPECTED_ROWS,
) -> dict[str, Any]:
    (
        frame,
        audit,
        feature_release_receipt,
        seeds,
        features,
        snapshots,
    ) = validate_inputs(
        feature_csv,
        feature_audit,
        feature_receipt,
        enforce_production_hashes=enforce_production_hashes,
        expected_rows=expected_rows,
    )
    stability = feature_stability(frame, seeds, features)
    selected = [row["feature"] for row in stability if row["selected"]]
    if not selected:
        raise FeatureSchemaError("no_cross_seed_stable_features")
    configuration = {
        "schema_version": SCHEMA_VERSION,
        "minimum_pairwise_seed_spearman": MIN_PAIRWISE_SEED_SPEARMAN,
        "minimum_between_to_within_ratio": MIN_BETWEEN_TO_WITHIN_RATIO,
        "seed_count": len(seeds),
        "seeds": list(seeds),
        "selection_uses_docking_labels": False,
        "production_hash_enforcement": enforce_production_hashes,
        "length_confounded_features_excluded_from_default_training": sorted(
            LENGTH_CONFOUNDED_FEATURES
        ),
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "PASS_FROZEN_LABEL_FREE_CONTACT_FEATURE_SCHEMA"
            if enforce_production_hashes
            else "TEST_ONLY_PASS_CONTACT_FEATURE_SCHEMA"
        ),
        "execution_mode": "production" if enforce_production_hashes else "test_only",
        "implementation": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__)),
        },
        "configuration": configuration,
        "configuration_sha256": sha256_json(configuration),
        "inputs": {
            "feature_csv": {
                "path": str(feature_csv.resolve()),
                "sha256": snapshots["feature_csv"]["sha256"],
                "size_bytes": snapshots["feature_csv"]["size_bytes"],
                "rows": len(frame),
            },
            "feature_audit": {
                "path": str(feature_audit.resolve()),
                "sha256": snapshots["feature_audit"]["sha256"],
                "size_bytes": snapshots["feature_audit"]["size_bytes"],
                "input_closure_sha256": audit.get("input_closure_sha256"),
                "release_closure_sha256": audit.get("release_closure_sha256"),
            },
            "feature_release_receipt": {
                "path": str(feature_receipt.resolve()),
                "sha256": snapshots["feature_release_receipt"]["sha256"],
                "size_bytes": snapshots["feature_release_receipt"]["size_bytes"],
                "schema_version": feature_release_receipt.get("schema_version"),
                "input_snapshot_content_closure_sha256": feature_release_receipt.get(
                    "input_snapshot_content_closure_sha256"
                ),
            },
        },
        "all_feature_count": len(features),
        "selected_feature_count": len(selected),
        "selected_features": selected,
        "diagnostic_only_length_confounded_features": [
            row["feature"]
            for row in stability
            if row["cross_seed_stable"] and row["length_confounded"]
        ],
        "required_shortcut_baseline": "cdr_length_only",
        "training_feature_sets": {
            "stable_seed_mean": [f"{feature}_seed_mean" for feature in selected],
            "stable_seed_mean_and_std": [
                column
                for feature in selected
                for column in (f"{feature}_seed_mean", f"{feature}_seed_std")
            ],
        },
        "feature_stability": stability,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    payload["payload_sha256"] = sha256_json(payload)
    write_json(output_path, payload)
    receipt = {
        "schema_version": "phase2_v4_d_contact_feature_schema_receipt_v2",
        "status": "PASS_COMPLETE_HASH_CLOSURE" if enforce_production_hashes else "TEST_ONLY_PASS_HASH_CLOSURE",
        "implementation_sha256": payload["implementation"]["sha256"],
        "configuration_sha256": payload["configuration_sha256"],
        "feature_csv_sha256": snapshots["feature_csv"]["sha256"],
        "feature_audit_sha256": snapshots["feature_audit"]["sha256"],
        "feature_release_receipt_sha256": snapshots["feature_release_receipt"][
            "sha256"
        ],
        "schema_file_sha256": sha256_file(output_path),
        "schema_payload_sha256": payload["payload_sha256"],
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json(output_path.with_suffix(".receipt.json"), receipt)
    return payload


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--feature-csv",
        type=Path,
        default=root / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.csv",
    )
    parser.add_argument(
        "--feature-audit",
        type=Path,
        default=root / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.audit.json",
    )
    parser.add_argument(
        "--feature-receipt",
        type=Path,
        default=root / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.receipt.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.json",
    )
    args = parser.parse_args(argv)
    result = run(args.feature_csv, args.feature_audit, args.feature_receipt, args.output)
    print(
        json.dumps(
            {
                "status": result["status"],
                "selected_feature_count": result["selected_feature_count"],
                "output": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
