#!/usr/bin/env python3
"""Prepare the already-used external hTNFa block for frozen V3-G2 comparison."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_BLINDED = EXP_DIR / "prepared/phase2_v3_binding/binding_formal_blinded_v3.csv"
DEFAULT_LABELS = EXP_DIR / "prepared/phase2_v3_binding/binding_formal_labels_sealed_v3.csv"
DEFAULT_DEVELOPMENT = EXP_DIR / "prepared/phase2_v3_g2/binding_cluster_safe_v1.csv"
DEFAULT_OUTPUT = EXP_DIR / "prepared/phase2_v3_g2/external_hTNFa_evaluation_v1.csv"
CLAIM_BOUNDARY = "external_hTNFa_comparison_previously_unsealed_in_V3_not_pristine_new_formal_test"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare(blinded_path: Path, labels_path: Path, development_path: Path, output_path: Path) -> dict[str, Any]:
    blinded = pd.read_csv(blinded_path)
    labels = pd.read_csv(labels_path)
    blinded = blinded[blinded["formal_block"].astype(str) == "external_hTNFa"].copy()
    labels = labels[labels["formal_block"].astype(str) == "external_hTNFa"].copy()
    if blinded["sample_id"].duplicated().any() or labels["sample_id"].duplicated().any():
        raise ValueError("External hTNFa sample IDs are not unique")
    if set(blinded["sample_id"].astype(str)) != set(labels["sample_id"].astype(str)):
        raise ValueError("External hTNFa blinded rows and labels do not match")
    merged = blinded.merge(labels[["sample_id", "label"]], on="sample_id", how="inner", validate="one_to_one")
    merged["split"] = "external_hTNFa"
    merged["claim_boundary"] = CLAIM_BOUNDARY
    merged = merged.sort_values("sample_id").reset_index(drop=True)
    development_hashes = set(pd.read_csv(development_path, usecols=["sequence_sha256"])["sequence_sha256"].astype(str))
    exact_overlap = len(development_hashes & set(merged["sequence_sha256"].astype(str)))
    if exact_overlap:
        raise ValueError(f"External hTNFa exact VHH overlap with retained development: {exact_overlap}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output_path, index=False)
    audit: dict[str, Any] = {
        "status": "PASS_EXTERNAL_HTNFA_COMPARISON_DATA_READY",
        "schema_version": "phase2_v3_g2_external_htnfa_prepare_audit_v1",
        "rows": len(merged),
        "unique_vhh": merged["sequence_sha256"].nunique(),
        "unique_targets": merged["target_sequence_sha256"].nunique(),
        "label_counts": merged["label"].astype(int).value_counts().sort_index().to_dict(),
        "exact_vhh_overlap_with_retained_development": exact_overlap,
        "input_sha256": {
            "blinded": sha256_file(blinded_path),
            "labels": sha256_file(labels_path),
            "development": sha256_file(development_path),
        },
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "formal_history": "This block was unsealed and used by the earlier V3 run; it is an external comparison, not a pristine untouched test.",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    audit_path = output_path.with_name("external_hTNFa_evaluation_audit_v1.json")
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blinded", type=Path, default=DEFAULT_BLINDED)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--development", type=Path, default=DEFAULT_DEVELOPMENT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    print(json.dumps(prepare(args.blinded, args.labels, args.development, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
