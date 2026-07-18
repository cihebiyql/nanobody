#!/usr/bin/env python3
"""Canonical closure validation plus synthetic protocol dry-run (no metrics)."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from meta_noise_stack_v1 import (
    CLAIM_BOUNDARY,
    read_tsv,
    run_outer_fold,
    validate_c2_outer_oof,
    validate_whole_parent_split_contract,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def synthetic_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inner: list[dict[str, Any]] = []
    outer: list[dict[str, Any]] = []
    for index in range(30):
        fold = index % 5
        base = 0.48 + 0.003 * index
        m2 = np.asarray([base + 0.004, base - 0.002])
        neural = m2 + np.asarray([0.012 * np.sin(index), 0.010 * np.cos(index)])
        contact = m2 + np.asarray([0.006 * np.cos(index / 2), 0.007 * np.sin(index / 3)])
        c2 = m2 + np.asarray([0.008 * np.sin(index / 4), -0.006 * np.cos(index / 5)])
        truth = m2 + 0.20 * (neural - m2) + 0.25 * (contact - m2) + 0.15 * (c2 - m2)
        tier = ("A", "B", "C")[index % 3]
        row = {
            "candidate_id": f"SYN_INNER_{index:03d}",
            "teacher_source": "SYN_SOURCE_A" if index % 2 == 0 else "SYN_SOURCE_B",
            "parent_framework_cluster": f"SYN_PARENT_{index:03d}",
            "outer_fold": 0,
            "inner_fold": fold,
            "development_reliability_tier": tier,
            "seed_dispersion_max": 0.015 + 0.001 * (index % 7) if tier in {"A", "B"} else 0.0,
            "truth_R8": truth[0], "truth_R9": truth[1],
            "m2_R8": m2[0], "m2_R9": m2[1],
            "neural_R8": neural[0], "neural_R9": neural[1],
            "contact_R8": contact[0], "contact_R9": contact[1],
            "c2_R8": c2[0], "c2_R9": c2[1],
        }
        inner.append(row)
    for index in range(10):
        base = 0.50 + 0.004 * index
        m2 = np.asarray([base, base - 0.005])
        neural = m2 + np.asarray([0.004, -0.003])
        contact = m2 + np.asarray([0.002, 0.006])
        c2 = m2 + np.asarray([-0.001, 0.003])
        outer.append({
            "candidate_id": f"SYN_OUTER_{index:03d}",
            "teacher_source": "SYN_SOURCE_A" if index % 2 == 0 else "SYN_SOURCE_B",
            "parent_framework_cluster": f"SYN_OUTER_PARENT_{index:03d}",
            "outer_fold": 0,
            "inner_fold": -1,
            "development_reliability_tier": "C",
            "seed_dispersion_max": 0.0,
            "truth_R8": -999.0, "truth_R9": 999.0,
            "m2_R8": m2[0], "m2_R9": m2[1],
            "neural_R8": neural[0], "neural_R9": neural[1],
            "contact_R8": contact[0], "contact_R9": contact[1],
            "c2_R8": c2[0], "c2_R9": c2[1],
        })
    return inner, outer


def main(args: argparse.Namespace) -> None:
    contract_path = Path(args.contract).resolve()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract["status"] != "PREFROZEN_IMPLEMENTATION_NO_PERFORMANCE_RESULTS":
        raise ValueError("contract status mismatch")
    input_paths = {name: Path(spec["path"]).resolve() for name, spec in contract["inputs"].items()}
    observed_hashes = {name: sha256_file(path) for name, path in input_paths.items()}
    for name, digest in observed_hashes.items():
        if digest != contract["inputs"][name]["sha256"]:
            raise ValueError(f"input hash mismatch:{name}:{digest}")

    labels_rows = read_tsv(input_paths["labels"])
    labels = {row["candidate_id"]: row for row in labels_rows}
    if len(labels) != contract["expected"]["candidates"]:
        raise ValueError("label candidate count mismatch")
    if len({row["parent_framework_cluster"] for row in labels_rows}) != contract["expected"]["parent_framework_clusters"]:
        raise ValueError("parent count mismatch")
    tier_counts = Counter(row["development_reliability_tier"] for row in labels_rows)
    if dict(tier_counts) != contract["expected"]["development_reliability_tiers"]:
        raise ValueError("tier count mismatch")
    source_counts = Counter(row["teacher_source"] for row in labels_rows)
    if dict(source_counts) != contract["expected"]["teacher_sources"]:
        raise ValueError("source count mismatch")

    split_audit = validate_whole_parent_split_contract(
        labels_rows,
        read_tsv(input_paths["outer_manifest"]),
        read_tsv(input_paths["inner_manifest"]),
    )
    c2_audit = validate_c2_outer_oof(
        read_tsv(input_paths["existing_c2_outer_oof"]), labels
    )

    inner, outer = synthetic_rows()
    result = run_outer_fold(inner, outer, include_gbdt=True)
    if not np.array_equal(
        result["primary_prediction_dual"],
        np.minimum(result["primary_prediction_two"][:, 0], result["primary_prediction_two"][:, 1]),
    ):
        raise ValueError("primary exact-min dry-run failure")
    if not np.array_equal(
        result["reliability_prediction_dual"],
        np.minimum(result["reliability_prediction_two"][:, 0], result["reliability_prediction_two"][:, 1]),
    ):
        raise ValueError("reliability exact-min dry-run failure")
    if not np.array_equal(
        result["gbdt_prediction_dual"],
        np.minimum(result["gbdt_prediction_two"][:, 0], result["gbdt_prediction_two"][:, 1]),
    ):
        raise ValueError("GBDT exact-min dry-run failure")

    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("nonempty output directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema_version": "pvrig_v2_5_meta_noise_protocol_dry_run_receipt_v1",
        "status": "PASS_V2_5_META_NOISE_BUILD_TEST_DRY_RUN",
        "claim_boundary": CLAIM_BOUNDARY,
        "contract": {"path": str(contract_path), "sha256": sha256_file(contract_path)},
        "canonical_input_hashes": observed_hashes,
        "canonical_counts": {
            "candidates": len(labels),
            "parents": len({row["parent_framework_cluster"] for row in labels_rows}),
            "tier_counts": dict(sorted(tier_counts.items())),
            "source_counts": dict(sorted(source_counts.items())),
        },
        "split_audit": split_audit,
        "c2_outer_oof_audit": c2_audit,
        "synthetic_protocol": {
            "inner_oof_rows": len(inner),
            "outer_score_rows": len(outer),
            "primary_meta": result["primary_model"].audit(),
            "reliability_meta": result["reliability_model"].audit(),
            "noise": result["noise_audit"],
            "gbdt": result["gbdt_config"],
            "exact_min_violations": 0,
            "outer_truth_accessed_for_fit": False,
            "same_row_stacking": False,
        },
        "performance_metrics_computed": False,
        "formal_training_or_prediction_launched": False,
        "v4_f_test32_access_count": 0,
    }
    receipt_path = output_dir / "DRY_RUN_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n")
    (output_dir / "SHA256SUMS").write_text(
        f"{sha256_file(receipt_path)}  {receipt_path.name}\n", encoding="utf-8"
    )
    print(json.dumps({"status": receipt["status"], "receipt": str(receipt_path)}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--output-dir", required=True)
    main(parser.parse_args())

