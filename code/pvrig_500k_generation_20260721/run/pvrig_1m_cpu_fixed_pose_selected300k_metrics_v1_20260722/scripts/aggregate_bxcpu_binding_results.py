#!/usr/bin/env python3
"""Merge per-task DeepNano/NanoBind outputs with strict ID and count checks."""

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


def read_by_id(path: Path, id_col: str):
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = {row[id_col]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"duplicate IDs in {path}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("result_root", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--expected-records", type=int, default=394295)
    args = parser.parse_args()

    task_dirs = sorted(p for p in args.result_root.glob("task_*") if p.is_dir())
    if not task_dirs:
        raise SystemExit(f"no task directories under {args.result_root}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    deep_values = []
    nano_values = []
    class_counts = {"0": 0, "1": 0}
    fieldnames = [
        "candidate_id",
        "antigen_id",
        "deepnano_binding_prior",
        "nanobind_binding_prior",
        "nanobind_binary_prediction",
        "source_task",
        "deepnano_inference_semantics",
    ]

    with gzip.open(args.output, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for task in task_dirs:
            complete = task / "COMPLETE.json"
            if not complete.exists() or json.loads(complete.read_text()).get("status") != "PASS":
                raise ValueError(f"task is not complete: {task}")
            deep = read_by_id(task / "output/deepnano_binding.csv", "Nanobody ID")
            nano = read_by_id(task / "output/nanobind_binding.csv", "nanobody_id")
            if deep.keys() != nano.keys():
                raise ValueError(f"model ID mismatch in {task}")
            for candidate_id, drow in deep.items():
                if candidate_id in seen:
                    raise ValueError(f"duplicate candidate across tasks: {candidate_id}")
                seen.add(candidate_id)
                dval = float(drow["Prediction"])
                nrow = nano[candidate_id]
                nval = float(nrow["probability"])
                pred = str(nrow["prediction"])
                deep_values.append(dval)
                nano_values.append(nval)
                class_counts[pred] = class_counts.get(pred, 0) + 1
                writer.writerow({
                    "candidate_id": candidate_id,
                    "antigen_id": drow["Antigen ID"],
                    "deepnano_binding_prior": repr(dval),
                    "nanobind_binding_prior": repr(nval),
                    "nanobind_binary_prediction": pred,
                    "source_task": task.name,
                    "deepnano_inference_semantics": "exact-length buckets; batch-composition invariant",
                })

    if len(seen) != args.expected_records:
        raise ValueError(f"record count {len(seen)} != expected {args.expected_records}")

    def stats(values):
        array = np.asarray(values, dtype=float)
        return {
            "min": float(array.min()),
            "q05": float(np.quantile(array, 0.05)),
            "median": float(np.median(array)),
            "q95": float(np.quantile(array, 0.95)),
            "max": float(array.max()),
            "mean": float(array.mean()),
        }

    summary = {
        "status": "PASS",
        "records": len(seen),
        "tasks": len(task_dirs),
        "deepnano_binding_prior": stats(deep_values),
        "nanobind_binding_prior": stats(nano_values),
        "nanobind_binary_counts": class_counts,
        "output": str(args.output),
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "scientific_boundary": "weak binding priors; not Kd, IC50, or blocking evidence",
    }
    summary_path = args.output.with_suffix(args.output.suffix + ".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
