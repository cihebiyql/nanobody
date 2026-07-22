#!/usr/bin/env python3
"""Build the hash-bound fixed-pose Top150k sequence/structure/TNP release."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import time
from collections import Counter
from pathlib import Path


def load_by_id(path: Path) -> tuple[list[str], dict[str, dict[str, str]]]:
    opener = gzip.open if path.suffix == ".gz" else Path.open
    with opener(path, "rt", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows: dict[str, dict[str, str]] = {}
        for row in reader:
            candidate_id = row["candidate_id"]
            if candidate_id in rows:
                raise ValueError(f"duplicate candidate_id in {path}: {candidate_id}")
            rows[candidate_id] = row
    return fields, rows


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_nonnegative_int(value: str, label: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"negative {label}: {value}")
    return parsed


def tnp_review_tier(red_flags: int) -> str:
    if red_flags == 0:
        return "CLEAR"
    if red_flags == 1:
        return "REVIEW"
    return "HIGH_RISK_REVIEW"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--structure", required=True, type=Path)
    parser.add_argument("--tnp", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--expected", type=int, default=150000)
    args = parser.parse_args()

    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    selection_fields, selection = load_by_id(args.selection)
    structure_fields, structure = load_by_id(args.structure)
    tnp_fields, tnp = load_by_id(args.tnp)

    id_sets = {"selection": set(selection), "structure": set(structure), "tnp": set(tnp)}
    if any(len(ids) != args.expected for ids in id_sets.values()):
        raise ValueError({name: len(ids) for name, ids in id_sets.items()})
    if not (id_sets["selection"] == id_sets["structure"] == id_sets["tnp"]):
        raise ValueError("candidate ID sets do not match exactly")

    structure_extra = [field for field in structure_fields if field != "candidate_id"]
    tnp_extra = [field for field in tnp_fields if field != "candidate_id"]
    derived_fields = [
        "tnp_review_tier",
        "multimetric_hard_gate",
        "multimetric_model_coverage",
        "tnp_input_structure_relation",
        "surrogate_prediction_status",
    ]
    output_fields = selection_fields + [f"nbb2_{field}" for field in structure_extra]
    output_fields += [f"tnp_{field}" for field in tnp_extra] + derived_fields

    args.output_dir.mkdir(parents=True)
    output = args.output_dir / "fixed_pose_top150k_multimetric.tsv.gz"
    tnp_red_flags: Counter[int] = Counter()
    tnp_amber_flags: Counter[int] = Counter()
    review_tiers: Counter[str] = Counter()
    parent_clusters: Counter[str] = Counter()
    with gzip.open(output, "wt", newline="", compresslevel=1) as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for candidate_id in sorted(selection):
            srow = selection[candidate_id]
            nrow = structure[candidate_id]
            trow = tnp[candidate_id]
            if srow["sequence_sha256"] != nrow["sequence_sha256"]:
                raise ValueError(f"sequence SHA256 mismatch: {candidate_id}")
            if nrow.get("status") != "SUCCESS" or nrow.get("pdb_sequence_match", "").lower() != "true":
                raise ValueError(f"invalid NBB2 status: {candidate_id}")
            if trow.get("status") != "PASS":
                raise ValueError(f"invalid TNP status: {candidate_id}")
            for field in ("cdr3_compactness", "psh", "ppc", "pnc"):
                if not math.isfinite(float(trow[field])):
                    raise ValueError(f"non-finite TNP {field}: {candidate_id}")
            red_flags = parse_nonnegative_int(trow["red_flag_count"], "red_flag_count")
            amber_flags = parse_nonnegative_int(trow["amber_flag_count"], "amber_flag_count")
            tier = tnp_review_tier(red_flags)

            merged = dict(srow)
            merged.update({f"nbb2_{field}": nrow[field] for field in structure_extra})
            merged.update({f"tnp_{field}": trow[field] for field in tnp_extra})
            merged["tnp_review_tier"] = tier
            merged["multimetric_hard_gate"] = str(
                srow.get("prestructure_hard_gate", "").lower() == "true"
            )
            merged["multimetric_model_coverage"] = (
                "sequence_descriptors;DeepNano;NanoBind;Sapiens;AbNatiV;ANARCI;NBB2;TNP;"
                "DockingSurrogate=PENDING_MODEL_READY"
            )
            merged["tnp_input_structure_relation"] = (
                "same_candidate_sequence_and_nbb2_version_ephemeral_recompute;"
                "not_individual_pdb_sha256_bound"
            )
            merged["surrogate_prediction_status"] = "PENDING_MODEL_READY"
            writer.writerow(merged)

            tnp_red_flags[red_flags] += 1
            tnp_amber_flags[amber_flags] += 1
            review_tiers[tier] += 1
            parent_clusters[srow.get("parent_cluster", "")] += 1

    output_sha256 = sha256(output)
    receipt = {
        "status": "READY_PENDING_DOCKING_SURROGATE",
        "records": len(selection),
        "id_set_exact_match": True,
        "sequence_sha256_exact_match": True,
        "nbb2_status_counts": {"SUCCESS": len(selection)},
        "tnp_status_counts": {"PASS": len(selection)},
        "tnp_red_flag_count_distribution": {str(k): v for k, v in sorted(tnp_red_flags.items())},
        "tnp_amber_flag_count_distribution": {str(k): v for k, v in sorted(tnp_amber_flags.items())},
        "tnp_review_tier_counts": dict(sorted(review_tiers.items())),
        "parent_clusters": len(parent_clusters),
        "largest_parent_cluster_records": max(parent_clusters.values()),
        "output": output.name,
        "output_sha256": output_sha256,
        "input_sha256": {
            "selection": sha256(args.selection),
            "structure": sha256(args.structure),
            "tnp": sha256(args.tnp),
        },
        "scoring_policy": (
            "raw independent metrics plus transparent TNP review tier; no post-hoc composite score "
            "before a hash-bound Docking surrogate MODEL_READY release"
        ),
        "coverage_field_policy": (
            "model_coverage is preserved from the prestructure input for audit; "
            "multimetric_model_coverage is authoritative for this release"
        ),
        "tnp_structure_provenance": (
            "TNP used an ephemeral same-sequence same-NBB2-version recomputation; the durable archived "
            "PDB hash is retained separately and is not claimed to be the exact TNP input hash"
        ),
        "scientific_boundaries": {
            "binding_priors": "weak binding priors; not Kd, IC50, or blocking evidence",
            "nbb2": "VHH monomer geometry prediction; not binding, affinity, docking, or blocking evidence",
            "tnp": "structure developability proxy; not measured expression or purity",
            "surrogate": "pending; no Docking-geometry prediction is present in this release",
        },
        "created_epoch": time.time(),
    }
    (args.output_dir / "READY.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "SHA256SUMS").write_text(f"{output_sha256}  {output.name}\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
