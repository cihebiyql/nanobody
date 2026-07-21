#!/usr/bin/env python3
"""Generate and fast-QC one full-scale CPU route shard."""

from __future__ import annotations

import argparse
import csv
import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("cpu_generator", HERE / "generate_local_cpu_routes.py")
GEN = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(GEN)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    args = parser.parse_args()
    tasks = GEN.read_tsv(args.tasks)
    parents = GEN.read_csv(args.inputs / "top_200_vhh_scaffolds_for_design.csv")
    for parent in parents:
        parent["cdr1"] = GEN.sequence_order_cdr12(parent["sequence_aa"], parent["cdr1"], "cdr1")
        parent["cdr2"] = GEN.sequence_order_cdr12(parent["sequence_aa"], parent["cdr2"], "cdr2")
        parent["cdr3"] = GEN.sequence_order_cdr3(parent["sequence_aa"], int(parent["cdr3_len"]))
    parent_by_id = {row["sequence_id"]: row for row in parents}
    donors = GEN.donor_index(parents)
    positives = GEN.load_positive_cdrs(
        args.inputs / "known_positive_CDR_table.csv",
        args.inputs / "known_positive_antibodies.fasta",
    )
    generated = []
    for task in tasks:
        candidate = GEN.generate_candidate(task, parent_by_id[task["parent_id"]], donors)
        candidate.update(
            GEN.fast_qc(
                str(candidate["sequence"]),
                {region: str(candidate[f"{region}_after"]) for region in ("cdr1", "cdr2", "cdr3")},
                task["parent_sequence"],
                positives,
            )
        )
        candidate["exact_duplicate_global"] = "pending_global_merge"
        generated.append(candidate)
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    fields = list(generated[0])
    GEN.write_tsv(args.output_prefix.with_suffix(".raw.tsv"), generated, fields)
    passing = [row for row in generated if row["fast_qc_status"] == "PASS"]
    GEN.write_tsv(args.output_prefix.with_suffix(".pass.tsv"), passing, fields)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

