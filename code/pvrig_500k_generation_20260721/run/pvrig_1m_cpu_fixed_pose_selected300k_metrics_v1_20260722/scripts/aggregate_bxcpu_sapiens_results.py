#!/usr/bin/env python3
"""Merge validated per-task Sapiens outputs into one compressed table."""

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("result_root", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--expected-records", type=int, default=394295)
    args = parser.parse_args()

    tasks = sorted(p for p in args.result_root.glob("task_*") if p.is_dir())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    scores = []
    mutation_counts = []
    fieldnames = None
    with gzip.open(args.output, "wt", newline="") as target:
        writer = None
        for task in tasks:
            receipt = task / "COMPLETE.json"
            if not receipt.exists() or json.loads(receipt.read_text()).get("status") != "PASS":
                raise ValueError(f"task is not complete: {task}")
            with (task / "output/sapiens.csv").open(newline="") as source:
                reader = csv.DictReader(source)
                if fieldnames is None:
                    fieldnames = reader.fieldnames
                    writer = csv.DictWriter(target, fieldnames=fieldnames, delimiter="\t")
                    writer.writeheader()
                elif reader.fieldnames != fieldnames:
                    raise ValueError(f"column mismatch in {task}")
                for row in reader:
                    candidate_id = row["seq_id"]
                    if candidate_id in seen:
                        raise ValueError(f"duplicate candidate: {candidate_id}")
                    seen.add(candidate_id)
                    scores.append(float(row["mean_self_probability"]))
                    mutation_counts.append(int(row["num_suggested_mutations"]))
                    writer.writerow(row)

    if len(seen) != args.expected_records:
        raise ValueError(f"record count {len(seen)} != expected {args.expected_records}")

    def stats(values):
        a=np.asarray(values,dtype=float)
        return {"min":float(a.min()),"q05":float(np.quantile(a,.05)),
                "median":float(np.median(a)),"q95":float(np.quantile(a,.95)),
                "max":float(a.max()),"mean":float(a.mean())}

    summary={"status":"PASS","records":len(seen),"tasks":len(tasks),
             "mean_self_probability":stats(scores),
             "num_suggested_mutations":stats(mutation_counts),
             "output":str(args.output),
             "output_sha256":hashlib.sha256(args.output.read_bytes()).hexdigest(),
             "scientific_boundary":"human-likeness/developability proxy; not measured expression or purity"}
    summary_path=args.output.with_suffix(args.output.suffix+".summary.json")
    summary_path.write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
    print(json.dumps(summary,sort_keys=True))


if __name__ == "__main__":
    main()
