#!/usr/bin/env python3
"""Label-free variance audit and deterministic receptor-symmetric 12D summary."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compact_row(row):
    def v(field):
        return float(row[field])

    def pair(stem):
        return v(f"8x6b__{stem}"), v(f"9e6y__{stem}")

    best8, best9 = pair("best_composite")
    top8, top9 = pair("top20_composite_mean")
    shape8, shape9 = pair("best_shape")
    hot8, hot9 = pair("best_hotspot")
    orient8, orient9 = pair("best_cdr3_orientation")
    return {
        "candidate_id": row["candidate_id"],
        "feature_schema": "pvrig_v2_5_label_free_coarse_pose_symmetric12d_v1",
        "sym_best_composite_mean": 0.5 * (best8 + best9),
        "sym_best_composite_min": min(best8, best9),
        "sym_best_composite_gap": abs(best8 - best9),
        "sym_top20_composite_mean": 0.5 * (top8 + top9),
        "sym_top20_composite_min": min(top8, top9),
        "sym_top20_composite_gap": abs(top8 - top9),
        "sym_best_shape_min": min(shape8, shape9),
        "sym_best_hotspot_min": min(hot8, hot9),
        "sym_best_cdr3_orientation_min": min(orient8, orient9),
        "dual_common_acceptable_fraction": v("dual__common_acceptable_fraction"),
        "dual_acceptable_jaccard": v("dual__acceptable_jaccard"),
        "dual_top20_min_composite_std": v("dual__top20_min_composite_std"),
    }


def main(args):
    input_path = Path(args.feature_tsv).resolve()
    with input_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    numeric_fields = [field for field in rows[0] if "__" in field]
    values = np.asarray([[float(row[field]) for field in numeric_fields] for row in rows])
    std = values.std(axis=0)
    constant = [field for field, value in zip(numeric_fields, std) if value <= 1e-12]
    near_constant = [
        field for field, value in zip(numeric_fields, std)
        if 1e-12 < value <= 1e-3
    ]
    compact = [compact_row(row) for row in rows]
    compact_fields = [field for field in compact[0] if field not in {"candidate_id", "feature_schema"}]
    compact_values = np.asarray([[float(row[field]) for field in compact_fields] for row in compact])
    output_path = Path(args.output_tsv)
    with output_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(compact[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(compact)
    receipt = {
        "schema_version": "pvrig_v2_5_label_free_coarse_pose_variance_compression_audit_v1",
        "status": "PASS_LABEL_FREE_VARIANCE_AND_COMPRESSION_AUDIT",
        "candidate_count": len(rows),
        "raw_feature_count": len(numeric_fields),
        "raw_constant_columns": constant,
        "raw_near_constant_columns_std_le_1e_3": near_constant,
        "raw_nonconstant_feature_count": int(np.sum(std > 1e-12)),
        "compact_feature_count": len(compact_fields),
        "compact_all_finite": bool(np.isfinite(compact_values).all()),
        "compact_constant_columns": [
            field for field, value in zip(compact_fields, compact_values.std(axis=0)) if value <= 1e-12
        ],
        "selection_basis": "Fixed receptor-symmetry and dual-conformer semantic coverage; no teacher label is read by this program.",
        "temporal_boundary": "Development contract created after the smoke feature run; formal utility must be judged only by later whole-parent OOF evaluation, never the smoke19 descriptive labels.",
        "pca_challenger": {
            "allowed": True,
            "input_columns": "raw columns with inner-train std > 1e-12, excluding pose_count QC",
            "fit_scope": "inner-train parent clusters only",
            "standardization_scope": "inner-train parent clusters only",
            "component_count": 8,
            "forbidden": ["fit on all 1507 rows", "fit on outer-test rows", "choose components using teacher labels"],
        },
        "input": {"path": str(input_path), "sha256": sha256_file(input_path)},
        "output": {"path": str(output_path), "sha256": sha256_file(output_path)},
    }
    Path(args.output_json).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature-tsv", required=True)
    parser.add_argument("--output-tsv", required=True)
    parser.add_argument("--output-json", required=True)
    main(parser.parse_args())
