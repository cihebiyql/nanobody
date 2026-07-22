#!/usr/bin/env python3
"""Build exact-ID prefilter/NBB2/TNP inputs for the corrected CPU700k set."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


COMMON = [
    "candidate_id", "sequence", "sequence_sha256", "sequence_length", "route_id",
    "generation_seed", "target_patch_assignment", "design_mode", "parent_id",
    "parent_cluster", "cdr1_after", "cdr2_after", "cdr3_after", "designed_regions",
    "generator", "generator_version", "generation_batch", "max_positive_cdr_identity",
    "max_positive_cdr_identity_detail",
]
SOURCE = [
    "source_candidate_id", "source_run_id", "source_arm_id",
    "source_backbone_group_id", "source_pose_id", "source_mpnn_index", "source_row_kind",
]
PREFILTER_METRICS = [
    "anarci_qc_status", "anarci_qc_reasons", "risk_tier",
    "developability_risk_proxy_partial", "expression_purity_risk_proxy_partial",
    "abnativ_status", "AbNatiV VHH Score", "mean_self_probability",
    "binding_model_raw_disagreement", "deepnano_binding_prior", "nanobind_binding_prior",
]
NBB2_FIELDS = [
    "candidate_id", "sequence_sha256", "structure_model", "structure_model_version",
    "structure_source", "pdb_relative_path", "pdb_sha256", "pdb_bytes",
    "pdb_sequence_match", "atom_records", "mean_predicted_error_angstrom",
    "elapsed_seconds", "worker_id", "slurm_job_id", "status", "failure_reason",
]
TNP_FIELDS = [
    "candidate_id", "status", "failure_reason", "pdb_path", "total_cdr_length",
    "cdr3_length", "cdr3_compactness", "psh", "ppc", "pnc", "flag_L", "flag_L3",
    "flag_C", "flag_PSH", "flag_PPC", "flag_PNC", "red_flag_count",
    "amber_flag_count", "metric_semantics",
]


def op(path: Path, mode: str):
    return gzip.open(path, mode, newline="") if path.suffix == ".gz" else path.open(mode, newline="")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_restricted(paths: list[Path], candidate_ids: set[str], required: set[str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for path in paths:
        with op(path, "rt") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise SystemExit(f"{path}: missing fields {sorted(missing)}")
            for row in reader:
                candidate_id = row["candidate_id"]
                if candidate_id not in candidate_ids:
                    continue
                if candidate_id in result:
                    raise SystemExit(f"duplicate retained metric ID: {candidate_id}")
                result[candidate_id] = row
    missing_ids = candidate_ids - set(result)
    if missing_ids:
        raise SystemExit(f"metric ID closure missing {len(missing_ids)} records")
    return result


def write_rows(path: Path, fields: list[str], rows):
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--prefilter", type=Path, action="append", required=True)
    parser.add_argument("--nbb2", type=Path, action="append", required=True)
    parser.add_argument("--tnp", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected", type=int, default=700000)
    parser.add_argument("--allow-technical-na", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    candidates: dict[str, dict[str, str]] = {}
    sequences: set[str] = set()
    with op(args.candidates, "rt") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            candidate_id, sequence = row["candidate_id"], row["sequence"]
            if candidate_id in candidates or sequence in sequences:
                raise SystemExit(f"candidate uniqueness failure: {candidate_id}")
            candidates[candidate_id] = row
            sequences.add(sequence)
    if len(candidates) != args.expected:
        raise SystemExit(f"candidate count {len(candidates)} != {args.expected}")
    candidate_ids = set(candidates)

    prefilter = load_restricted(args.prefilter, candidate_ids, {"candidate_id", *PREFILTER_METRICS})
    nbb2 = load_restricted(args.nbb2, candidate_ids, set(NBB2_FIELDS))
    tnp = load_restricted(args.tnp, candidate_ids, set(TNP_FIELDS))
    order = sorted(candidate_ids)

    nbb2_counts = Counter(nbb2[candidate_id]["status"] for candidate_id in order)
    tnp_counts = Counter(tnp[candidate_id]["status"] for candidate_id in order)
    anarci_counts = Counter(prefilter[candidate_id]["anarci_qc_status"] for candidate_id in order)
    if not args.allow_technical_na:
        if nbb2_counts != {"SUCCESS": args.expected}:
            raise SystemExit(f"retained NBB2 technical failures remain: {dict(nbb2_counts)}")
        if tnp_counts != {"PASS": args.expected}:
            raise SystemExit(f"retained TNP technical failures remain: {dict(tnp_counts)}")
        if anarci_counts != {"PASS": args.expected}:
            raise SystemExit(f"retained ANARCI failures remain: {dict(anarci_counts)}")

    prefilter_fields = COMMON + SOURCE + PREFILTER_METRICS
    prefilter_path = args.output_dir / "cpu700k_prefilter.tsv.gz"
    nbb2_path = args.output_dir / "cpu700k_nbb2.tsv.gz"
    tnp_path = args.output_dir / "cpu700k_tnp.tsv.gz"
    write_rows(
        prefilter_path,
        prefilter_fields,
        (
            {field: candidates[candidate_id].get(field, "") for field in COMMON + SOURCE}
            | {field: prefilter[candidate_id].get(field, "") for field in PREFILTER_METRICS}
            for candidate_id in order
        ),
    )
    write_rows(
        nbb2_path,
        NBB2_FIELDS,
        ({field: nbb2[candidate_id].get(field, "") for field in NBB2_FIELDS} for candidate_id in order),
    )
    write_rows(
        tnp_path,
        TNP_FIELDS,
        ({field: tnp[candidate_id].get(field, "") for field in TNP_FIELDS} for candidate_id in order),
    )

    outputs = [prefilter_path, nbb2_path, tnp_path]
    receipt = {
        "status": "PASS" if not args.allow_technical_na else "NONRELEASABLE_WITH_TECHNICAL_NA",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "records": args.expected,
        "id_set_exact_match": True,
        "candidate_sequence_exact_unique": True,
        "status_counts": {
            "anarci": dict(sorted(anarci_counts.items())),
            "nbb2": dict(sorted(nbb2_counts.items())),
            "tnp": dict(sorted(tnp_counts.items())),
        },
        "technical_na_is_not_biological_negative": True,
        "outputs": {path.name: sha(path) for path in outputs},
    }
    (args.output_dir / "READY.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "SHA256SUMS").write_text(
        "".join(f"{receipt['outputs'][path.name]}  {path.name}\n" for path in outputs)
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
