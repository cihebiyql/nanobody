#!/usr/bin/env python3
"""Audit endpoint-aligned threshold sensitivity across frozen PVRIG campaigns.

This is a post-V4-D method audit.  It never changes or releases the original
V4-D evaluator and emits no candidate-level labels.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any


THRESHOLDS = {
    "hotspot_overlap": 14.0,
    "total_occlusion": 500.0,
    "cdr3_occlusion": 100.0,
    "cdr3_fraction": 0.15,
}
SCALES = (0.9, 1.0, 1.1)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scaled(value: float, scale: float) -> float:
    return float(Decimal(str(value)) * Decimal(str(scale)))


def strict_a(row: dict[str, str], scale: float) -> bool:
    return all(float(row[key]) >= scaled(value, scale) for key, value in THRESHOLDS.items())


def complete_candidate_pairs(rows: list[dict[str, str]]) -> list[dict[str, dict[str, str]]]:
    grouped: dict[tuple[str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        if row.get("entity_type") != "candidate":
            continue
        grouped[(row["job_id"], row["model"])][row["scoring_reference"]] = row
    return [refs for refs in grouped.values() if set(refs) == {"8x6b", "9e6y"}]


def representative_pairs(
    pairs: list[dict[str, dict[str, str]]],
) -> list[dict[str, dict[str, str]]]:
    by_job: dict[str, list[dict[str, dict[str, str]]]] = defaultdict(list)
    for pair in pairs:
        by_job[next(iter(pair.values()))["job_id"]].append(pair)

    def key(pair: dict[str, dict[str, str]]) -> tuple[float, str]:
        row = next(iter(pair.values()))
        try:
            score = float(row.get("haddock_score", ""))
        except (TypeError, ValueError):
            score = math.inf
        return score, row["model"]

    return [min(job_pairs, key=key) for _, job_pairs in sorted(by_job.items())]


def sensitivity(pairs: list[dict[str, dict[str, str]]], maximum_delta: float) -> dict[str, Any]:
    rates: dict[str, float] = {}
    counts: dict[str, int] = {}
    for scale in SCALES:
        count = sum(strict_a(pair["8x6b"], scale) and strict_a(pair["9e6y"], scale) for pair in pairs)
        counts[str(scale)] = count
        rates[str(scale)] = round(count / len(pairs), 6) if pairs else 0.0
    deltas = {
        "0.9": round(abs(rates["0.9"] - rates["1.0"]), 6),
        "1.1": round(abs(rates["1.1"] - rates["1.0"]), 6),
    }
    reasons = [f"delta_above_{maximum_delta}:scale_{scale}:{delta}" for scale, delta in deltas.items() if delta > maximum_delta]
    return {
        "status": "PASS" if not reasons and pairs else "FAIL",
        "reasons": reasons or ([] if pairs else ["no_complete_representative_pairs"]),
        "representative_job_count": len(pairs),
        "strict_a_counts": counts,
        "strict_a_rates": rates,
        "absolute_rate_deltas": deltas,
        "maximum_absolute_delta": maximum_delta,
    }


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def audit_campaign(name: str, pose_scores: Path, evaluator: Path, maximum_delta: float) -> dict[str, Any]:
    evaluator_payload = json.loads(evaluator.read_text(encoding="utf-8"))
    expected_pose_hash = evaluator_payload.get("pose_scores_sha256")
    actual_pose_hash = sha256(pose_scores)
    if actual_pose_hash != expected_pose_hash:
        raise ValueError(f"{name}: pose score hash mismatch")
    if evaluator_payload.get("evidence_mode") != "production_pose_backed":
        raise ValueError(f"{name}: evaluator is not production pose-backed")
    all_pairs = complete_candidate_pairs(read_tsv(pose_scores))
    representatives = representative_pairs(all_pairs)
    result = sensitivity(representatives, maximum_delta)
    result.update(
        {
            "campaign": name,
            "pose_scores_path": str(pose_scores),
            "pose_scores_sha256": actual_pose_hash,
            "source_evaluator_path": str(evaluator),
            "source_evaluator_sha256": sha256(evaluator),
            "source_evaluator_status": evaluator_payload.get("status"),
            "source_evaluator_unlockable": evaluator_payload.get("unlockable"),
            "all_selected_model_pair_count": len(all_pairs),
        }
    )
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--campaign",
        action="append",
        nargs=3,
        metavar=("NAME", "POSE_SCORES", "EVALUATOR"),
        required=True,
    )
    parser.add_argument("--maximum-delta", type=float, default=0.2)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    campaigns = [
        audit_campaign(name, Path(pose_scores), Path(evaluator), args.maximum_delta)
        for name, pose_scores, evaluator in args.campaign
    ]
    passed = bool(campaigns) and all(item["status"] == "PASS" for item in campaigns)
    payload = {
        "schema_version": "pvrig_v4e_endpoint_aligned_sensitivity_method_audit_v1",
        "status": "PASS_METHOD_AUDIT" if passed else "FAIL_METHOD_AUDIT",
        "method": {
            "unit": "one_lowest_haddock_score_model_pair_per_successful_candidate_job",
            "thresholds": THRESHOLDS,
            "scales": list(SCALES),
            "maximum_absolute_delta": args.maximum_delta,
            "numeric_comparison": "decimal_string_product",
        },
        "campaigns": campaigns,
        "governance": {
            "timing": "post_V4D_failure_retrospective_method_audit",
            "original_v4d_evaluator_modified": False,
            "original_v4d_evaluator_released": False,
            "candidate_level_labels_emitted": False,
            "prospective_test_validity_claimed": False,
        },
        "claim_boundary": "Evaluator-method audit only; not binding, affinity, competition, experimental blocking, or original V4-D release authority.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
