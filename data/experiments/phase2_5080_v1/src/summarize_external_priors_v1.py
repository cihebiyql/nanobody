#!/usr/bin/env python3
"""Summarize long-form external priors into auditable candidate features."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


MODELS = ("nanobind_seq", "nanobind_site", "nanobind_pro", "deepnano_seq", "deepnano_site")
SITE_MODELS = ("nanobind_site", "deepnano_site")
SCALAR_MODELS = ("nanobind_seq", "nanobind_pro", "deepnano_seq")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize_site(scores: list[float], mapping: list[dict[str, str]]) -> dict[str, Any]:
    if len(scores) != len(mapping):
        raise ValueError(f"Site vector length {len(scores)} does not match domain mapping length {len(mapping)}")
    weights = [float(row["target_weight"]) for row in mapping]
    target_indices = [idx for idx, weight in enumerate(weights) if weight > 0]
    background_indices = [idx for idx, weight in enumerate(weights) if weight == 0]
    weighted_denom = sum(weights)
    target_weighted_mean = sum(score * weight for score, weight in zip(scores, weights)) / weighted_denom
    top = sorted(range(len(scores)), key=lambda idx: scores[idx], reverse=True)[:10]
    top_rows = [
        {
            "model_position_1based": idx + 1,
            "full_position_1based": int(mapping[idx]["full_position_1based"]),
            "aa": mapping[idx]["aa"],
            "score": scores[idx],
            "target_weight": weights[idx],
            "hotspot_ids": mapping[idx]["hotspot_ids"],
        }
        for idx in top
    ]
    target_mean = mean([scores[idx] for idx in target_indices])
    background_mean = mean([scores[idx] for idx in background_indices])
    return {
        "site_vector_length": len(scores),
        "site_mean": mean(scores),
        "site_max": max(scores),
        "site_top10_mean": mean([scores[idx] for idx in top]),
        "site_count_ge_0_5": sum(score >= 0.5 for score in scores),
        "target_weighted_mean": target_weighted_mean,
        "target_unweighted_mean": target_mean,
        "background_mean": background_mean,
        "target_minus_background": target_mean - background_mean,
        "top10_positions_json": json.dumps(top_rows, separators=(",", ":")),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--candidate-base", type=Path, required=True)
    parser.add_argument("--domain-mapping", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-json", type=Path, required=True)
    parser.add_argument("--audit-md", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw = read_csv(args.raw)
    candidates = read_csv(args.candidate_base)
    mapping_all = read_csv(args.domain_mapping)
    mapping = sorted(
        (row for row in mapping_all if row["in_model_domain"] == "yes"),
        key=lambda row: int(row["model_index_0based"]),
    )
    grouped: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in raw:
        key = row["candidate_id"]
        model = row["model_key"]
        if model in grouped[key]:
            raise ValueError(f"Duplicate raw prior row for {key}/{model}")
        grouped[key][model] = row

    candidate_by_id = {row["candidate_id"]: row for row in candidates}
    if set(grouped) != set(candidate_by_id):
        raise ValueError("Candidate IDs differ between raw priors and candidate base")
    output_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        model_rows = grouped[candidate_id]
        if set(model_rows) != set(MODELS):
            raise ValueError(f"Missing model rows for {candidate_id}: {set(MODELS) - set(model_rows)}")
        if any(row["status"] != "ok" for row in model_rows.values()):
            raise ValueError(f"Unavailable external prior for {candidate_id}")
        out: dict[str, Any] = dict(candidate)
        out["candidate_sequence_length"] = model_rows[MODELS[0]]["candidate_sequence_length"]
        out["candidate_sequence_sha256"] = model_rows[MODELS[0]]["candidate_sequence_sha256"]
        out["antigen_id"] = model_rows[MODELS[0]]["antigen_id"]
        out["antigen_length"] = model_rows[MODELS[0]]["antigen_length"]
        out["antigen_sequence_sha256"] = model_rows[MODELS[0]]["antigen_sequence_sha256"]
        for model in SCALAR_MODELS:
            out[f"{model}_raw_score"] = float(model_rows[model]["raw_score"])
            if model_rows[model]["raw_components_json"]:
                components = json.loads(model_rows[model]["raw_components_json"])
                for name, value in components.items():
                    out[f"{model}_{name}"] = float(value)
        for model in SITE_MODELS:
            scores = [float(value) for value in json.loads(model_rows[model]["raw_site_scores_json"])]
            for name, value in summarize_site(scores, mapping).items():
                out[f"{model}_{name}"] = value
        out["external_prior_models_ok"] = len(MODELS)
        out["external_prior_evidence_boundary"] = "external_nanobody_antigen_binding_and_site_priors_not_blocker_scores"
        output_rows.append(out)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(output_rows[0])
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    scalar_stats = {}
    for model in SCALAR_MODELS:
        values = [float(row[f"{model}_raw_score"]) for row in output_rows]
        scalar_stats[model] = {
            "min": min(values),
            "mean": mean(values),
            "median": statistics.median(values),
            "max": max(values),
        }
    site_stats = {}
    for model in SITE_MODELS:
        values = [float(row[f"{model}_target_weighted_mean"]) for row in output_rows]
        enrichments = [float(row[f"{model}_target_minus_background"]) for row in output_rows]
        site_stats[model] = {
            "target_weighted_mean_min": min(values),
            "target_weighted_mean_mean": mean(values),
            "target_weighted_mean_max": max(values),
            "target_enrichment_positive_count": sum(value > 0 for value in enrichments),
        }
    audit = {
        "status": "PASS",
        "raw_rows": len(raw),
        "candidate_rows": len(output_rows),
        "status_counts": dict(Counter(row["status"] for row in raw)),
        "model_counts": dict(Counter(row["model_key"] for row in raw)),
        "domain_positions": len(mapping),
        "domain_full_position_range": [int(mapping[0]["full_position_1based"]), int(mapping[-1]["full_position_1based"])],
        "scalar_stats": scalar_stats,
        "site_stats": site_stats,
        "evidence_boundary": "External model outputs are uncalibrated binding/site priors, not blocker probabilities.",
    }
    args.audit_json.parent.mkdir(parents=True, exist_ok=True)
    args.audit_json.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# External Prior Summary Audit V1",
        "",
        "Verdict: PASS",
        "",
        f"- Candidates: {len(output_rows)}",
        f"- Raw model rows: {len(raw)}",
        f"- Models per candidate: {len(MODELS)}",
        f"- Target domain positions: {len(mapping)} ({mapping[0]['full_position_1based']}-{mapping[-1]['full_position_1based']})",
        f"- Status counts: {audit['status_counts']}",
        f"- Scalar score statistics: `{json.dumps(scalar_stats, sort_keys=True)}`",
        f"- Site target statistics: `{json.dumps(site_stats, sort_keys=True)}`",
        "- Evidence boundary: uncalibrated external binding/site priors, not PVRIG blocker probabilities.",
        "",
    ]
    args.audit_md.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(args.output), "audit": str(args.audit_json)}, indent=2))


if __name__ == "__main__":
    main()
