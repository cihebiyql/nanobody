#!/usr/bin/env python3
"""Build a reproducible two-seed stability release for the V4-I Stage2 cohort.

The pose/job scoring formula is a frozen transcription of
``run_adaptive_v4h.py::summarize_job_fixed_top8`` and
``stage_base_v4f.py::utility``.  It intentionally reports computational
blocker-like geometry only; it is not binding, affinity, competition, or
experimental blocking evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


CONFORMATIONS = ("8x6b", "9e6y")
SUCCESS_STATES = {"SUCCESS", "PASS", "PASSED", "COMPLETE", "COMPLETED", "DONE"}
CLAIM = (
    "Two-seed 8X6B/9E6Y computational blocker-like geometry stability ranking "
    "only; not binding, affinity, competition, experimental blocking, Docking "
    "Gold, or formal biological validation."
)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv_atomic(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def as_float(value: Any, field: str) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid_float:{field}") from error
    if not math.isfinite(output):
        raise ValueError(f"nonfinite:{field}")
    return output


def soft(value: float, threshold: float) -> float:
    return value / (value + threshold)


def utility(score: Mapping[str, Any]) -> float:
    hotspot = as_float(score["hotspot_overlap"]["full"]["count"], "hotspot")
    holdout = as_float(score["hotspot_overlap"]["holdout"]["count"], "holdout")
    occlusion = score["vhh_pvrl2_occlusion"]
    total = as_float(occlusion["residue_pair_count"], "total")
    cdr3 = as_float(occlusion["by_vhh_region_pair_count"]["cdr3"], "cdr3")
    fraction = as_float(occlusion["cdr3_fraction"], "fraction")
    rmsd = as_float(score["overlay"]["t_ca_rmsd_a"], "rmsd")
    if rmsd > 1.0:
        raise ValueError(f"native_overlay_rmsd_above_1A:{rmsd}")
    clashes = as_float(score["clashes_2p5a"]["vhh_pvrig"]["residue_pair_count"], "clashes")
    base = (
        0.15 * min(max(hotspot / 23, 0), 1)
        + 0.25 * min(max(holdout / 11, 0), 1)
        + 0.25 * soft(total, 500)
        + 0.20 * soft(cdr3, 100)
        + 0.15 * soft(fraction, 0.15)
    )
    return base / (1 + clashes / 5)


def geometry_class(item: Mapping[str, Any]) -> str:
    hotspot = float(item["hotspot_overlap"]["full"]["count"])
    occ = item["vhh_pvrl2_occlusion"]
    total = float(occ["residue_pair_count"])
    cdr3 = float(occ["by_vhh_region_pair_count"]["cdr3"])
    fraction = float(occ["cdr3_fraction"])
    if hotspot >= 14 and total >= 500 and cdr3 >= 100 and fraction >= 0.15:
        return "A"
    if hotspot >= 14 and total < 50:
        return "C"
    if hotspot >= 10 and total >= 100 and cdr3 >= 20 and fraction >= 0.10:
        return "B"
    return "E"


def summarize_job_fixed_top8(result: Mapping[str, Any], conformation: str) -> tuple[float, int]:
    complete: list[tuple[float, str, dict[str, Any]]] = []
    for pose in result.get("pose_scores", []):
        reference_scores = {
            str(item["reference_id"]).lower(): item for item in pose.get("scores", [])
        }
        if set(reference_scores) == set(CONFORMATIONS):
            complete.append(
                (
                    float((pose.get("haddock_io") or {})["score"]),
                    str(pose.get("pose", "")),
                    reference_scores,
                )
            )
    if len(complete) < 4:
        raise ValueError("fewer_than_4_complete_models")
    complete.sort(key=lambda item: (item[0], item[1]))
    complete = complete[:8]
    raw_weights = [1 / math.log2(rank + 1) for rank in range(1, len(complete) + 1)]
    weights = [value / sum(raw_weights) for value in raw_weights]
    score = sum(weight * utility(item[2][conformation]) for weight, item in zip(weights, complete))
    model_reliability = 0.5 + 0.5 * min(len(complete) / 8, 1)
    other = "9e6y" if conformation == "8x6b" else "8x6b"
    pairs = [
        (geometry_class(item[2][conformation]), geometry_class(item[2][other]))
        for item in complete
    ]
    support = [(left in {"A", "B"}) == (right in {"A", "B"}) for left, right in pairs]
    labels = [
        "STRICT_A"
        if left == right == "A"
        else "SUPPORTED_AB"
        if left in {"A", "B"} and right in {"A", "B"}
        else "OTHER"
        for left, right in pairs
    ]
    agreement = sum(support) / len(support)
    consensus = max(labels.count(label) for label in set(labels)) / len(labels)
    return score * model_reliability * (0.5 + 0.25 * agreement + 0.25 * consensus), len(complete)


def score_job(payload: tuple[str, str, str, str]) -> dict[str, Any]:
    job_id, candidate_id, conformation, result_path = payload
    try:
        result = json.loads(Path(result_path).read_text(encoding="utf-8"))
        if str(result.get("state", "")).upper() not in SUCCESS_STATES:
            raise ValueError(f"result_state:{result.get('state', '')}")
        value, model_count = summarize_job_fixed_top8(result, conformation)
        if not math.isfinite(value):
            raise ValueError("nonfinite_job_score")
        return {
            "job_id": job_id,
            "candidate_id": candidate_id,
            "conformation": conformation,
            "score": value,
            "complete_model_count": model_count,
            "error": "",
        }
    except Exception as error:  # preserve per-job technical evidence
        return {
            "job_id": job_id,
            "candidate_id": candidate_id,
            "conformation": conformation,
            "score": None,
            "complete_model_count": 0,
            "error": f"SCORING:{type(error).__name__}:{error}",
        }


def average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        average = (start + 1 + end) / 2
        for position in range(start, end):
            ranks[order[position]] = average
        start = end
    return ranks


def pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    mean_left = statistics.fmean(left)
    mean_right = statistics.fmean(right)
    numerator = sum((x - mean_left) * (y - mean_right) for x, y in zip(left, right))
    denominator = math.sqrt(
        sum((x - mean_left) ** 2 for x in left) * sum((y - mean_right) ** 2 for y in right)
    )
    return numerator / denominator if denominator else None


def spearman(left: list[float], right: list[float]) -> float | None:
    return pearson(average_ranks(left), average_ranks(right))


def percentile(values: list[float], proportion: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * proportion
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def correlation_payload(pairs: Iterable[tuple[float, float]]) -> dict[str, Any]:
    materialized = list(pairs)
    left = [item[0] for item in materialized]
    right = [item[1] for item in materialized]
    return {
        "n": len(materialized),
        "pearson": pearson(left, right),
        "spearman": spearman(left, right),
    }


def status_for(root: Path, job_id: str) -> dict[str, Any]:
    path = root / "status" / "jobs" / f"{job_id}.json"
    if not path.is_file():
        return {"status": "MISSING", "error": "status_missing", "attempts": ""}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        return {"status": "UNREADABLE", "error": f"{type(error).__name__}:{error}", "attempts": ""}


def confidence_factor(min_seed_count: int) -> float:
    return {0: 0.0, 1: 0.80, 2: 0.90}.get(min_seed_count, 1.0)


def build(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    stage1_path = root / args.stage1_ranking
    selected_path = root / args.selected_candidates
    stage2_jobs_path = root / args.stage2_jobs
    all_jobs_path = root / args.all_jobs
    script_path = Path(__file__).resolve()

    stage1_rows = read_tsv(stage1_path)
    stage1_by_id = {row["candidate_id"]: row for row in stage1_rows}
    selected_rows = read_tsv(selected_path)
    selected_ids = {row["candidate_id"] for row in selected_rows}
    if len(selected_ids) != len(selected_rows):
        raise RuntimeError("duplicate_selected_candidate_id")
    missing_stage1 = sorted(selected_ids - set(stage1_by_id))
    if missing_stage1:
        raise RuntimeError(f"selected_candidates_missing_from_stage1:{missing_stage1[:5]}")

    stage2_jobs = read_tsv(stage2_jobs_path)
    if len(stage2_jobs) != 2 * len(selected_rows):
        raise RuntimeError(f"stage2_job_count_mismatch:{len(stage2_jobs)}:{len(selected_rows)}")
    expected_pairs = {(candidate_id, conf) for candidate_id in selected_ids for conf in CONFORMATIONS}
    observed_pairs = {(row["entity_id"], row["conformation"].lower()) for row in stage2_jobs}
    if observed_pairs != expected_pairs:
        raise RuntimeError("stage2_candidate_conformation_matrix_mismatch")

    technical: dict[str, list[str]] = defaultdict(list)
    scoring_payloads: list[tuple[str, str, str, str]] = []
    for job in stage2_jobs:
        state = status_for(root, job["job_id"])
        status = str(state.get("status", "PENDING")).upper()
        if status != "SUCCESS":
            technical[job["entity_id"]].append(
                f"{job['conformation']}:s1931:{status}:{state.get('error', '')}"
            )
            continue
        evidence = state.get("evidence") or f"results/{job['job_id']}/job_result.json"
        result_path = Path(str(evidence))
        if not result_path.is_absolute():
            result_path = root / result_path
        if not result_path.is_file():
            technical[job["entity_id"]].append(f"{job['conformation']}:s1931:RESULT_MISSING")
            continue
        scoring_payloads.append((job["job_id"], job["entity_id"], job["conformation"].lower(), str(result_path)))

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        scored_jobs = list(pool.map(score_job, scoring_payloads, chunksize=4))
    score1931: dict[str, dict[str, float]] = defaultdict(dict)
    model_counts: dict[str, dict[str, int]] = defaultdict(dict)
    for result in scored_jobs:
        if result["score"] is None:
            technical[result["candidate_id"]].append(
                f"{result['conformation']}:s1931:{result['error']}"
            )
        else:
            score1931[result["candidate_id"]][result["conformation"]] = float(result["score"])
            model_counts[result["candidate_id"]][result["conformation"]] = int(result["complete_model_count"])

    output_rows: list[dict[str, Any]] = []
    for candidate_id in selected_ids:
        source = stage1_by_id[candidate_id]
        per_conf: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for conf, field in (("8x6b", "median_score_8X6B"), ("9e6y", "median_score_9E6Y")):
            if source.get(field, ""):
                per_conf[conf].append((917, float(source[field])))
            if conf in score1931[candidate_id]:
                per_conf[conf].append((1931, score1931[candidate_id][conf]))
        counts = {conf: len(per_conf[conf]) for conf in CONFORMATIONS}
        analyzable = all(counts[conf] >= 1 for conf in CONFORMATIONS)
        medians = {
            conf: statistics.median(value for _, value in per_conf[conf])
            for conf in CONFORMATIONS
            if per_conf[conf]
        }
        min_seed_count = min(counts.values()) if analyzable else 0
        raw = min(medians.values()) if analyzable else None
        dispersions = {
            conf: statistics.pstdev(value for _, value in per_conf[conf])
            if len(per_conf[conf]) >= 2
            else 0.0
            for conf in CONFORMATIONS
        }
        dispersion_max = max(dispersions.values()) if analyzable else None
        seed917_8 = float(source["median_score_8X6B"]) if source.get("median_score_8X6B") else None
        seed917_9 = float(source["median_score_9E6Y"]) if source.get("median_score_9E6Y") else None
        seed1931_8 = score1931[candidate_id].get("8x6b")
        seed1931_9 = score1931[candidate_id].get("9e6y")
        output_rows.append(
            {
                "candidate_id": candidate_id,
                "sequence_sha256": source["sequence_sha256"],
                "parent_framework_cluster": source["parent_framework_cluster"],
                "target_patch_id": source["target_patch_id"],
                "design_mode": source["design_mode"],
                "stage1_full_rank": int(source["rank"]),
                "stage1_selected_rank": 0,
                "seed917_score_8X6B": f"{seed917_8:.9f}" if seed917_8 is not None else "",
                "seed917_score_9E6Y": f"{seed917_9:.9f}" if seed917_9 is not None else "",
                "seed917_R_dual_min": f"{min(seed917_8, seed917_9):.9f}" if seed917_8 is not None and seed917_9 is not None else "",
                "seed1931_score_8X6B": f"{seed1931_8:.9f}" if seed1931_8 is not None else "",
                "seed1931_score_9E6Y": f"{seed1931_9:.9f}" if seed1931_9 is not None else "",
                "seed1931_R_dual_min": f"{min(seed1931_8, seed1931_9):.9f}" if seed1931_8 is not None and seed1931_9 is not None else "",
                "seed1931_complete_models_8X6B": model_counts[candidate_id].get("8x6b", ""),
                "seed1931_complete_models_9E6Y": model_counts[candidate_id].get("9e6y", ""),
                "successful_seed_count_8X6B": counts["8x6b"],
                "successful_seed_ids_8X6B": ",".join(str(seed) for seed, _ in sorted(per_conf["8x6b"])),
                "successful_seed_count_9E6Y": counts["9e6y"],
                "successful_seed_ids_9E6Y": ",".join(str(seed) for seed, _ in sorted(per_conf["9e6y"])),
                "median_score_8X6B": f"{medians['8x6b']:.9f}" if "8x6b" in medians else "",
                "median_score_9E6Y": f"{medians['9e6y']:.9f}" if "9e6y" in medians else "",
                "R_dual_min": f"{raw:.9f}" if raw is not None else "",
                "seed_dispersion_8X6B": f"{dispersions['8x6b']:.9f}" if analyzable else "",
                "seed_dispersion_9E6Y": f"{dispersions['9e6y']:.9f}" if analyzable else "",
                "seed_dispersion_max": f"{dispersion_max:.9f}" if dispersion_max is not None else "",
                "confidence_adjusted_score": f"{raw * confidence_factor(min_seed_count):.9f}" if raw is not None else "",
                "docking_evidence_tier": f"DUAL_{min_seed_count}_SEED" if analyzable else "TECHNICAL_INCOMPLETE",
                "technical_reasons": ";".join(technical[candidate_id]),
                "seed1931_selected_rank": "",
                "combined_selected_rank": 0,
                "combined_minus_stage1_selected_rank": 0,
                "ranking_release": "stage2_seed917_1931_selected500",
                "claim_boundary": CLAIM,
            }
        )

    by_stage1 = sorted(output_rows, key=lambda row: (int(row["stage1_full_rank"]), row["candidate_id"]))
    for index, row in enumerate(by_stage1, 1):
        row["stage1_selected_rank"] = index
    by_seed1931 = sorted(
        [row for row in output_rows if row["seed1931_R_dual_min"] != ""],
        key=lambda row: (-float(row["seed1931_R_dual_min"]), row["candidate_id"]),
    )
    for index, row in enumerate(by_seed1931, 1):
        row["seed1931_selected_rank"] = index
    output_rows.sort(
        key=lambda row: (
            -int(str(row["docking_evidence_tier"]).split("_")[1])
            if str(row["docking_evidence_tier"]).startswith("DUAL_")
            else 1,
            -float(row["confidence_adjusted_score"] or -1),
            row["candidate_id"],
        )
    )
    for index, row in enumerate(output_rows, 1):
        row["combined_selected_rank"] = index
        row["combined_minus_stage1_selected_rank"] = index - int(row["stage1_selected_rank"])

    # Recompute a deterministic Stage1 sample from raw pose JSON to prove formula identity.
    sample_count = min(args.validation_sample, len(by_stage1))
    sample_indices = sorted(
        {round(index * (len(by_stage1) - 1) / max(sample_count - 1, 1)) for index in range(sample_count)}
    )
    sample_ids = {by_stage1[index]["candidate_id"] for index in sample_indices}
    validation_jobs = []
    for job in read_tsv(all_jobs_path):
        if job["entity_id"] not in sample_ids or int(job["seed"]) != 917:
            continue
        state = status_for(root, job["job_id"])
        if str(state.get("status", "")).upper() != "SUCCESS":
            continue
        evidence = state.get("evidence") or f"results/{job['job_id']}/job_result.json"
        result_path = Path(str(evidence))
        if not result_path.is_absolute():
            result_path = root / result_path
        validation_jobs.append((job["job_id"], job["entity_id"], job["conformation"].lower(), str(result_path)))
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        validation_scored = list(pool.map(score_job, validation_jobs, chunksize=2))
    validation_mismatches = []
    validation_success = 0
    for item in validation_scored:
        source = stage1_by_id[item["candidate_id"]]
        field = "median_score_8X6B" if item["conformation"] == "8x6b" else "median_score_9E6Y"
        expected = source.get(field, "")
        observed = f"{float(item['score']):.9f}" if item["score"] is not None else ""
        if expected != observed:
            validation_mismatches.append(
                {"job_id": item["job_id"], "field": field, "expected": expected, "observed": observed, "error": item["error"]}
            )
        else:
            validation_success += 1
    if validation_mismatches:
        raise RuntimeError(f"stage1_formula_reproduction_failed:{validation_mismatches[:3]}")

    fields = list(output_rows[0])
    ranking_path = root / args.output_ranking
    top50_path = root / args.output_top50
    job_scores_path = root / args.output_job_scores
    summary_path = root / args.output_summary
    receipt_path = root / args.output_receipt
    write_tsv_atomic(ranking_path, output_rows, fields)
    write_tsv_atomic(top50_path, output_rows[:50], fields)
    job_score_rows = sorted(scored_jobs, key=lambda row: row["job_id"])
    write_tsv_atomic(
        job_scores_path,
        job_score_rows,
        ["job_id", "candidate_id", "conformation", "score", "complete_model_count", "error"],
    )

    two_seed = [row for row in output_rows if row["docking_evidence_tier"] == "DUAL_2_SEED"]
    complete_1931 = [row for row in output_rows if row["seed1931_R_dual_min"] != ""]
    dispersions = [float(row["seed_dispersion_max"]) for row in two_seed]
    rank_shifts = [abs(int(row["combined_minus_stage1_selected_rank"])) for row in output_rows]
    correlation = {
        "R_dual_min_seed917_vs_seed1931": correlation_payload(
            (float(row["seed917_R_dual_min"]), float(row["seed1931_R_dual_min"]))
            for row in complete_1931
        ),
        "8X6B_seed917_vs_seed1931": correlation_payload(
            (float(row["seed917_score_8X6B"]), float(row["seed1931_score_8X6B"]))
            for row in output_rows
            if row["seed1931_score_8X6B"] != ""
        ),
        "9E6Y_seed917_vs_seed1931": correlation_payload(
            (float(row["seed917_score_9E6Y"]), float(row["seed1931_score_9E6Y"]))
            for row in output_rows
            if row["seed1931_score_9E6Y"] != ""
        ),
    }
    topk = {}
    stage1_order = [row["candidate_id"] for row in by_stage1]
    stage1931_order = [row["candidate_id"] for row in by_seed1931]
    combined_order = [row["candidate_id"] for row in output_rows]
    for k in (10, 25, 50, 100, 200):
        if k > len(output_rows):
            continue
        set1 = set(stage1_order[:k])
        set1931 = set(stage1931_order[:k])
        set_combined = set(combined_order[:k])
        topk[str(k)] = {
            "seed917_vs_seed1931_overlap": len(set1 & set1931),
            "seed917_vs_seed1931_fraction": len(set1 & set1931) / k,
            "seed917_vs_combined_overlap": len(set1 & set_combined),
            "seed917_vs_combined_fraction": len(set1 & set_combined) / k,
        }
    summary = {
        "schema_version": "pvrig_v4i_stage2_two_seed_stability_v1",
        "status": "PASS" if len(output_rows) == len(selected_rows) and not validation_mismatches else "FAIL",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_candidate_count": len(output_rows),
        "stage2_job_count": len(stage2_jobs),
        "stage2_job_terminal_counts": dict(
            sorted(Counter(str(status_for(root, row["job_id"]).get("status", "PENDING")).upper() for row in stage2_jobs).items())
        ),
        "evidence_tier_counts": dict(sorted(Counter(row["docking_evidence_tier"] for row in output_rows).items())),
        "stage1_formula_reproduction": {
            "sample_candidate_count": len(sample_ids),
            "sample_job_count": len(validation_jobs),
            "exact_9_decimal_match_count": validation_success,
            "mismatch_count": len(validation_mismatches),
        },
        "correlations": correlation,
        "topk_overlap": topk,
        "seed_dispersion_max": {
            "n": len(dispersions),
            "median": percentile(dispersions, 0.5),
            "p90": percentile(dispersions, 0.9),
            "p95": percentile(dispersions, 0.95),
            "max": max(dispersions) if dispersions else None,
        },
        "absolute_combined_rank_shift": {
            "n": len(rank_shifts),
            "median": percentile([float(x) for x in rank_shifts], 0.5),
            "p90": percentile([float(x) for x in rank_shifts], 0.9),
            "p95": percentile([float(x) for x in rank_shifts], 0.95),
            "max": max(rank_shifts) if rank_shifts else None,
        },
        "claim_boundary": CLAIM,
    }
    write_json_atomic(summary_path, summary)
    receipt = {
        "schema_version": "pvrig_v4i_stage2_stability_release_receipt_v1",
        "status": "PASS_STAGE2_TWO_SEED_STABILITY_RELEASE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "formula_source": {
            "description": "Frozen transcription of V4-H adaptive Top-8 scorer, validated against V4-I Stage1 raw jobs.",
            "script": str(script_path),
            "script_sha256": sha256(script_path),
        },
        "inputs": {str(path.relative_to(root)): sha256(path) for path in (stage1_path, selected_path, stage2_jobs_path, all_jobs_path)},
        "outputs": {str(path.relative_to(root)): sha256(path) for path in (ranking_path, top50_path, job_scores_path, summary_path)},
        "candidate_count": len(output_rows),
        "stage2_job_count": len(stage2_jobs),
        "formula_validation_exact_match_jobs": validation_success,
        "claim_boundary": CLAIM,
    }
    write_json_atomic(receipt_path, receipt)
    return {"summary": summary, "receipt": receipt}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--stage1-ranking", default="release/stage1_seed917_ranking.tsv")
    parser.add_argument("--selected-candidates", default="release/stage2_selected_seed1931_candidates.tsv")
    parser.add_argument("--stage2-jobs", default="manifests/stage2_selected_seed1931.tsv")
    parser.add_argument("--all-jobs", default="manifests/docking_jobs.tsv")
    parser.add_argument("--output-ranking", default="release/stage2_seed917_1931_selected500_ranking.tsv")
    parser.add_argument("--output-top50", default="release/stage2_seed917_1931_top50.tsv")
    parser.add_argument("--output-job-scores", default="reports/stage2_seed1931_job_scores.tsv")
    parser.add_argument("--output-summary", default="reports/stage2_seed917_1931_stability_summary.json")
    parser.add_argument("--output-receipt", default="release/STAGE2_STABILITY_RECEIPT.json")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--validation-sample", type=int, default=32)
    return parser.parse_args()


if __name__ == "__main__":
    payload = build(parse_args())
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
