#!/usr/bin/env python3
"""Summarize positive/control ranges and matched mutation deltas."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


NUMERIC_FIELDS = (
    "boltz_iptm",
    "boltz_confidence",
    "chai_best_iptm",
    "chai_best_confidence",
)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite_values(rows: list[dict[str, str]], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        try:
            value = float(row[field])
        except (KeyError, TypeError, ValueError):
            continue
        if value == value:
            values.append(value)
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve()
    reports = project / "reports"
    candidate_path = reports / "CONTROL_INDEPENDENT_COMPLEX_CANDIDATE_SUMMARY.tsv"
    rows = read_tsv(candidate_path)
    if len(rows) != 9:
        raise ValueError(f"expected 9 controls, found {len(rows)}")
    positives = [
        row for row in rows if row["control_class"] == "EXPERIMENTAL_POSITIVE_BLOCKER"
    ]
    mutants = [
        row
        for row in rows
        if row["control_class"] == "COMPUTATIONAL_DISRUPTIVE_CONTROL"
    ]
    if len(positives) != 5 or len(mutants) != 4:
        raise ValueError("control class cardinality mismatch")

    ranges: dict[str, Any] = {}
    for label, group in (("positive", positives), ("disruptive", mutants)):
        ranges[label] = {
            field: {
                "n": len(values := finite_values(group, field)),
                "min": min(values) if values else None,
                "median": statistics.median(values) if values else None,
                "max": max(values) if values else None,
            }
            for field in NUMERIC_FIELDS
        }
        ranges[label]["independent_support_counts"] = dict(
            sorted(Counter(row["independent_complex_support"] for row in group).items())
        )
        ranges[label]["boltz_pair_label_counts"] = dict(
            sorted(Counter(row["boltz_pair_label"] for row in group).items())
        )
        ranges[label]["chai_best_pair_label_counts"] = dict(
            sorted(Counter(row["chai_best_pair_label"] for row in group).items())
        )

    positive_by_base = {row["base_molecule"]: row for row in positives}
    deltas: list[dict[str, Any]] = []
    for mutant in mutants:
        parent = positive_by_base[mutant["base_molecule"]]
        record: dict[str, Any] = {
            "base_molecule": mutant["base_molecule"],
            "positive_candidate_id": parent["candidate_id"],
            "mutant_candidate_id": mutant["candidate_id"],
            "mutation": mutant["mutation"],
            "positive_support": parent["independent_complex_support"],
            "mutant_support": mutant["independent_complex_support"],
            "positive_boltz_pair_label": parent["boltz_pair_label"],
            "mutant_boltz_pair_label": mutant["boltz_pair_label"],
            "positive_chai_pair_label": parent["chai_best_pair_label"],
            "mutant_chai_pair_label": mutant["chai_best_pair_label"],
        }
        for field in NUMERIC_FIELDS:
            try:
                record[f"delta_mutant_minus_positive_{field}"] = (
                    float(mutant[field]) - float(parent[field])
                )
            except (TypeError, ValueError):
                record[f"delta_mutant_minus_positive_{field}"] = ""
        deltas.append(record)
    delta_path = reports / "CONTROL_MATCHED_MUTATION_DELTAS.tsv"
    write_tsv(delta_path, deltas)

    payload = {
        "schema_version": "pvrig.control.independent_complex.calibration_summary.v1",
        "state": "COMPLETE",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "positive_count": 5,
        "disruptive_control_count": 4,
        "ranges": ranges,
        "candidate_summary_sha256": sha256_file(candidate_path),
        "matched_delta_sha256": sha256_file(delta_path),
        "interpretation": {
            "positive_range_role": (
                "Observed five-positive model range; use as a soft calibration "
                "band, not a universal hard threshold."
            ),
            "mutant_role": (
                "Matched alanine perturbation sensitivity check only. These "
                "mutants are not experimentally confirmed negatives."
            ),
            "ranking_rule": (
                "Promote cross-tool blocker-geometry agreement first; use "
                "confidence/ipTM only after checking whether positives separate "
                "from matched mutants."
            ),
        },
        "claim_boundary": (
            "Computational co-folding calibration does not establish experimental "
            "affinity, purity, expression, or blocking."
        ),
    }
    out = reports / "CONTROL_CALIBRATION_RANGES.json"
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
