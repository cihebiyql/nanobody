#!/usr/bin/env python3
"""Bind V2.6 delta_noise from nonadaptive V4-D OPEN_TRAIN three-seed Rdual."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


FORMULA = "clip(median_candidate(MAD_seed(Rdual))*1.4826*sqrt(2), 0.01, 0.03)"
CLAIM = (
    "V2.6 computational Docking-geometry measurement tolerance binding only; "
    "not binding, affinity, competition, experimental blocking, or Docking Gold."
)


class BindingError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def median_absolute_deviation(values: list[float]) -> float:
    if not values:
        raise BindingError("mad_requires_values")
    center = statistics.median(values)
    return statistics.median(abs(value - center) for value in values)


def bind_delta_noise(candidate_values: dict[str, list[float]]) -> dict[str, float]:
    if not candidate_values:
        raise BindingError("candidate_values_empty")
    mads = []
    for candidate_id, values in candidate_values.items():
        if len(values) != 3 or any(not math.isfinite(value) for value in values):
            raise BindingError(f"candidate_not_exactly_three_finite_seeds:{candidate_id}")
        mads.append(median_absolute_deviation(values))
    median_mad = statistics.median(mads)
    raw = median_mad * 1.4826 * math.sqrt(2.0)
    clipped = min(max(raw, 0.01), 0.03)
    return {"median_candidate_mad": median_mad, "unclipped_delta_noise": raw, "delta_noise": clipped}


def load_v4d_three_seed_rdual(path: Path) -> dict[str, list[float]]:
    receptor: dict[tuple[str, int, str], float] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="\t")
        required = {"campaign", "candidate_id", "receptor", "seed", "score"}
        if not required <= set(reader.fieldnames or []):
            raise BindingError("source_schema_missing")
        for row in reader:
            if row["campaign"].upper() != "V4D":
                raise BindingError("source_contains_non_v4d_row")
            receptor_name = row["receptor"].lower()
            if receptor_name not in {"8x6b", "9e6y"}:
                raise BindingError(f"invalid_receptor:{receptor_name}")
            key = (row["candidate_id"], int(row["seed"]), receptor_name)
            if key in receptor:
                raise BindingError(f"duplicate_receptor_seed:{key}")
            value = float(row["score"])
            if not math.isfinite(value):
                raise BindingError(f"nonfinite_score:{key}")
            receptor[key] = value
    candidates = sorted({key[0] for key in receptor})
    output: dict[str, list[float]] = {}
    for candidate_id in candidates:
        seeds = sorted({key[1] for key in receptor if key[0] == candidate_id})
        paired = [
            seed for seed in seeds
            if (candidate_id, seed, "8x6b") in receptor and (candidate_id, seed, "9e6y") in receptor
        ]
        if len(paired) != 3:
            continue
        output[candidate_id] = [
            min(receptor[(candidate_id, seed, "8x6b")], receptor[(candidate_id, seed, "9e6y")])
            for seed in paired
        ]
    if len(output) != 225:
        raise BindingError(f"v4d_complete_three_seed_candidate_count:{len(output)}")
    return output


def run(source: Path, out: Path) -> dict[str, Any]:
    candidate_values = load_v4d_three_seed_rdual(source)
    values = bind_delta_noise(candidate_values)
    payload: dict[str, Any] = {
        "schema_version": "pvrig_v2_6_delta_noise_binding_v1",
        "status": "FROZEN_V2_6_DELTA_NOISE_FROM_NONADAPTIVE_V4D_OPEN_TRAIN",
        "formula": FORMULA,
        "cohort": "V4-D OPEN_TRAIN candidates with exactly three paired 8X6B/9E6Y seeds",
        "candidate_count": len(candidate_values),
        "seed_count_per_candidate": 3,
        "median_candidate_MAD_seed_Rdual": values["median_candidate_mad"],
        "normal_consistency_factor": 1.4826,
        "paired_difference_factor": math.sqrt(2.0),
        "unclipped_delta_noise": values["unclipped_delta_noise"],
        "clip_bounds": [0.01, 0.03],
        "delta_noise": values["delta_noise"],
        "source_path": str(source),
        "source_sha256": sha256_file(source),
        "adaptive_v4h_excluded": True,
        "adaptive_v4h_exclusion_rationale": (
            "V4-H seed2/seed3 candidates were selected after observing seed917, restricting score range "
            "and biasing repeat reliability/noise estimates."
        ),
        "candidate_is_statistical_unit": True,
        "v4_f_or_test32_results_accessed": 0,
        "claim_boundary": CLAIM,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(run(a.source, a.out), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
