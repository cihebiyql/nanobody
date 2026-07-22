#!/usr/bin/env python3
"""Materialize V2.18 pose-decomposition auxiliary targets.

The output is a training-target table only.  No value produced here is an
allowed production inference input.  Consumers must generate predictions with
nested whole-parent cross-fitting before using the values in a meta-model.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence


PRIMARY_SEED = "917"
REFERENCES = ("8x6b", "9e6y")
POSE_NUMERIC = (
    "geometry_utility",
    "hotspot_overlap",
    "total_occlusion",
    "cdr3_occlusion",
    "cdr3_fraction",
    "geometry_margin",
)
POSE_STATS = ("mean", "std", "min", "max", "q25", "q75")
JOB_NUMERIC = (
    "job_geometry_score",
    "raw_rank_weighted_geometry_score",
    "model_pair_consensus_fraction",
    "model_native_cross_support_agreement_fraction",
    "model_strict_a_fraction",
    "representative_pair_support_ordinal",
)


class MaterializationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MaterializationError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None, f"missing_header:{path}")
        rows = list(reader)
    return list(reader.fieldnames), rows


def read_unique(path: Path, key: str) -> dict[str, dict[str, str]]:
    fields, rows = read_rows(path)
    require(key in fields, f"missing_key:{path}:{key}")
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row[key]
        require(bool(value), f"empty_key:{path}:{key}")
        require(value not in result, f"duplicate_key:{path}:{key}:{value}")
        result[value] = row
    return result


def number(value: str, field: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise MaterializationError(f"invalid_number:{field}:{value}") from exc
    require(math.isfinite(result), f"nonfinite_number:{field}:{value}")
    return result


def quantile(values: Sequence[float], fraction: float) -> float:
    require(bool(values), "empty_quantile")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summary(values: Sequence[float]) -> dict[str, float]:
    require(bool(values), "empty_summary")
    return {
        "mean": statistics.fmean(values),
        "std": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
        "q25": quantile(values, 0.25),
        "q75": quantile(values, 0.75),
    }


def output_fields() -> list[str]:
    fields = ["candidate_id", "parent_framework_cluster", "sequence_sha256"]
    for reference in REFERENCES:
        for feature in POSE_NUMERIC:
            for stat in POSE_STATS:
                fields.append(f"pose_{reference}_{feature}_{stat}")
        fields.extend((f"pose_{reference}_A_fraction", f"pose_{reference}_B_fraction", f"pose_{reference}_count"))
        fields.extend(f"job_{reference}_{feature}" for feature in JOB_NUMERIC)
    fields.extend((
        "pose_dual_geometry_utility_mean_min",
        "pose_dual_geometry_utility_mean_gap",
        "pose_dual_hotspot_mean_min",
        "pose_dual_total_occlusion_mean_min",
        "pose_dual_A_fraction_min",
        "successful_dual_seed_count",
        "multiseed_uncertainty_available",
        "seed_dispersion_Rdual",
    ))
    return fields


def materialize(
    strict_train_path: Path,
    release_path: Path,
    pose_path: Path,
    job_path: Path,
    output_path: Path,
) -> dict[str, object]:
    strict = read_unique(strict_train_path, "candidate_id")
    release = read_unique(release_path, "candidate_id")
    eligible = {
        candidate_id
        for candidate_id, row in release.items()
        if candidate_id in strict
        and row.get("canonical_model_split") == "train"
        and row.get("training_label_status") == "WEAK_LABEL_AVAILABLE"
    }
    require(bool(eligible), "no_eligible_candidates")

    pose_groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    pose_fields, pose_rows = read_rows(pose_path)
    required_pose = {"candidate_id", "seed", "scoring_reference", "geometry_class", *POSE_NUMERIC}
    require(required_pose.issubset(pose_fields), f"pose_schema_missing:{sorted(required_pose-set(pose_fields))}")
    for row in pose_rows:
        candidate_id = row["candidate_id"]
        reference = row["scoring_reference"].lower()
        if candidate_id in eligible and row["seed"] == PRIMARY_SEED and reference in REFERENCES:
            pose_groups[(candidate_id, reference)].append(row)

    job_groups: dict[tuple[str, str], dict[str, str]] = {}
    job_fields, job_rows = read_rows(job_path)
    required_job = {"entity_id", "seed", "conformation", "canonical_state", *JOB_NUMERIC}
    require(required_job.issubset(job_fields), f"job_schema_missing:{sorted(required_job-set(job_fields))}")
    for row in job_rows:
        candidate_id = row["entity_id"]
        reference = row["conformation"].lower()
        if candidate_id not in eligible or row["seed"] != PRIMARY_SEED or reference not in REFERENCES:
            continue
        if row["canonical_state"] != "SUCCESS":
            continue
        key = (candidate_id, reference)
        require(key not in job_groups, f"duplicate_primary_job:{candidate_id}:{reference}")
        job_groups[key] = row

    complete = sorted(
        candidate_id for candidate_id in eligible
        if all((candidate_id, reference) in pose_groups and (candidate_id, reference) in job_groups for reference in REFERENCES)
    )
    require(bool(complete), "no_complete_pose_aux_candidates")
    records: list[dict[str, object]] = []
    for candidate_id in complete:
        release_row = release[candidate_id]
        strict_row = strict[candidate_id]
        record: dict[str, object] = {
            "candidate_id": candidate_id,
            "parent_framework_cluster": strict_row["parent_framework_cluster"],
            "sequence_sha256": release_row.get("sequence_sha256", strict_row.get("sequence_sha256", "")),
        }
        per_reference: dict[str, dict[str, float]] = {}
        for reference in REFERENCES:
            rows = pose_groups[(candidate_id, reference)]
            per_reference[reference] = {}
            for feature in POSE_NUMERIC:
                observed = summary([number(row[feature], feature) for row in rows])
                per_reference[reference][f"{feature}_mean"] = observed["mean"]
                for stat in POSE_STATS:
                    record[f"pose_{reference}_{feature}_{stat}"] = observed[stat]
            count = len(rows)
            record[f"pose_{reference}_A_fraction"] = sum(row["geometry_class"] == "A" for row in rows) / count
            record[f"pose_{reference}_B_fraction"] = sum(row["geometry_class"] == "B" for row in rows) / count
            record[f"pose_{reference}_count"] = count
            job = job_groups[(candidate_id, reference)]
            for feature in JOB_NUMERIC:
                record[f"job_{reference}_{feature}"] = number(job[feature], feature)

        utility = [per_reference[reference]["geometry_utility_mean"] for reference in REFERENCES]
        hotspot = [per_reference[reference]["hotspot_overlap_mean"] for reference in REFERENCES]
        occlusion = [per_reference[reference]["total_occlusion_mean"] for reference in REFERENCES]
        a_fraction = [float(record[f"pose_{reference}_A_fraction"]) for reference in REFERENCES]
        record["pose_dual_geometry_utility_mean_min"] = min(utility)
        record["pose_dual_geometry_utility_mean_gap"] = abs(utility[0] - utility[1])
        record["pose_dual_hotspot_mean_min"] = min(hotspot)
        record["pose_dual_total_occlusion_mean_min"] = min(occlusion)
        record["pose_dual_A_fraction_min"] = min(a_fraction)
        seed_count = int(release_row["successful_dual_seed_count"])
        dispersion = release_row.get("seed_dispersion_Rdual", "")
        available = seed_count >= 2 and dispersion != ""
        record["successful_dual_seed_count"] = seed_count
        record["multiseed_uncertainty_available"] = int(available)
        record["seed_dispersion_Rdual"] = number(dispersion, "seed_dispersion_Rdual") if available else ""
        records.append(record)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    require(not output_path.exists(), f"output_exists:{output_path}")
    fields = output_fields()
    with output_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    return {
        "schema_version": "pvrig_v2_18_pose_aux_targets_v1",
        "status": "PASS_POSE_AUX_TARGET_MATERIALIZATION",
        "strict_train_rows": len(strict),
        "release_eligible_rows": len(eligible),
        "output_rows": len(records),
        "excluded_incomplete_rows": len(eligible) - len(records),
        "primary_seed": PRIMARY_SEED,
        "output_sha256": sha256_file(output_path),
        "claim_boundary": "Training auxiliary targets only; forbidden as direct production inference inputs.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict-train", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--pose", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    report = materialize(args.strict_train, args.release, args.pose, args.jobs, args.output)
    require(not args.receipt.exists(), f"receipt_exists:{args.receipt}")
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
