#!/usr/bin/env python3
"""Build exact open1507 label-free PDB/CDR manifest without reading target labels."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from coarse_pose_features_v1 import sha256_file


def read_tsv(path):
    with Path(path).open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main(args):
    split_path = Path(args.outer_split).resolve()
    closure_path = Path(args.graph_closure).resolve()
    split_rows = read_tsv(split_path)
    cohort = {}
    for row in split_rows:
        if row["candidate_role"] != "score":
            continue
        candidate = row["candidate_id"]
        if candidate in cohort:
            raise ValueError(f"duplicate score candidate: {candidate}")
        if row["teacher_source"] not in {"V4D_OPEN_MULTI_SEED", "V4H_ADAPTIVE_SEED_RANKING"}:
            raise ValueError(f"non-open teacher source: {row['teacher_source']}")
        cohort[candidate] = row
    closure_rows = {row["candidate_id"]: row for row in read_tsv(closure_path)}
    if set(cohort) != set(closure_rows):
        raise ValueError("outer score cohort and graph closure candidate sets differ")

    roots = {
        "V4D_ARCHIVE_OPEN_TRAIN_LABEL_FREE": Path(args.v4d_monomer_root).resolve(),
        "V4H_DIRECT_LABEL_FREE_BUNDLE": Path(args.v4h_monomer_root).resolve(),
    }
    output_rows = []
    for candidate in sorted(cohort):
        split = cohort[candidate]
        closure = closure_rows[candidate]
        source = closure["structure_source"]
        if source not in roots:
            raise ValueError(f"unexpected structure source: {source}")
        monomer = roots[source] / f"{candidate}.pdb"
        if not monomer.is_file():
            raise ValueError(f"missing monomer: {candidate}")
        actual_hash = sha256_file(monomer)
        if actual_hash != closure["monomer_sha256"]:
            raise ValueError(f"monomer hash mismatch: {candidate}")
        if closure["parent_framework_cluster"] != split["parent_framework_cluster"]:
            raise ValueError(f"parent mismatch: {candidate}")
        output_rows.append({
            "candidate_id": candidate,
            "sequence_sha256": closure["sequence_sha256"],
            "parent_framework_cluster": closure["parent_framework_cluster"],
            "teacher_source_audit_only": split["teacher_source"],
            "outer_fold": split["outer_fold"],
            "structure_source": source,
            "monomer_pdb": str(monomer),
            "monomer_sha256": actual_hash,
            "cdr1_range": closure["cdr1_range"],
            "cdr2_range": closure["cdr2_range"],
            "cdr3_range": closure["cdr3_range"],
            "claim_boundary": "Open-only label-free monomer/CDR cohort input; no docking pose or scalar target is an input feature.",
        })
    if len(output_rows) != 1507:
        raise ValueError(f"expected 1507 open candidates, got {len(output_rows)}")
    output_path = Path(args.output_tsv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)
    receipt = {
        "schema_version": "pvrig_v2_5_open1507_label_free_monomer_manifest_v1",
        "status": "PASS_OPEN1507_LABEL_FREE_INPUT_CLOSURE",
        "candidate_count": len(output_rows),
        "parent_count": len({row["parent_framework_cluster"] for row in output_rows}),
        "structure_source_counts": dict(Counter(row["structure_source"] for row in output_rows)),
        "outer_fold_counts": dict(Counter(row["outer_fold"] for row in output_rows)),
        "sealed_boundary": {
            "scalar_teacher_columns_read": 0,
            "candidate_docking_pose_files_opened": 0,
            "v4_f_files_opened": 0,
        },
        "inputs": {
            "outer_split": {"path": str(split_path), "sha256": sha256_file(split_path)},
            "graph_closure": {"path": str(closure_path), "sha256": sha256_file(closure_path)},
        },
        "output": {"path": str(output_path), "sha256": sha256_file(output_path)},
    }
    Path(args.output_json).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--outer-split", required=True)
    parser.add_argument("--graph-closure", required=True)
    parser.add_argument("--v4d-monomer-root", required=True)
    parser.add_argument("--v4h-monomer-root", required=True)
    parser.add_argument("--output-tsv", required=True)
    parser.add_argument("--output-json", required=True)
    main(parser.parse_args())
