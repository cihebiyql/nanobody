#!/usr/bin/env python3
"""Aggregate per-candidate 8X6B/9E6Y geometry into training-ready TSV tables."""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_tsv(path: Path, rows: list[dict[str, object]], preferred: list[str]) -> None:
    fields = list(preferred)
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tsv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def numeric(values: list[str], mode: str) -> str:
    parsed = []
    for value in values:
        try:
            parsed.append(float(value))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return ""
    result = min(parsed) if mode == "min" else max(parsed)
    return f"{result:g}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_root.resolve()
    manifest = root / "docking/manifests/docking_candidates.tsv"
    with manifest.open(newline="", encoding="utf-8") as handle:
        candidates = list(csv.DictReader(handle, delimiter="\t"))

    candidate_rows: list[dict[str, object]] = []
    baseline_rows: list[dict[str, object]] = []
    consensus_rows: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        reports = root / "docking/postprocessed" / candidate_id / "reports"
        state = read_json(root / "docking/state/postprocess" / f"{candidate_id}.json")
        all_classification: list[dict[str, str]] = []
        for baseline in ("8x6b", "9e6y"):
            path = reports / f"{candidate_id}_{baseline}_blocker_classification.csv"
            rows = read_csv(path)
            all_classification.extend(rows)
            for row in rows:
                baseline_rows.append(
                    {
                        "candidate_id": candidate_id,
                        "baseline_id": baseline.upper(),
                        "baseline_mode": "8X6B_guided_docking_then_reference_overlay",
                        "restraint_policy": candidate["restraint_policy"],
                        **row,
                    }
                )
        consensus = read_csv(reports / f"{candidate_id}_8x6b_9e6y_consensus.csv")
        for row in consensus:
            consensus_rows.append({"candidate_id": candidate_id, **row})
        class_counts = Counter(row.get("consensus_class", "") for row in consensus)
        status = str(state.get("status", "missing"))
        a_fraction = class_counts.get("CONSENSUS_BLOCKER_LIKE_A", 0) / len(consensus) if consensus else 0.0
        candidate_rows.append(
            {
                "candidate_id": candidate_id,
                "postprocess_status": status,
                "scored_pose_count": len(consensus),
                "baseline_blocker_geometry": f"{a_fraction:.6g}" if consensus else "",
                "baseline_affinity_proxy": numeric([row.get("haddock_score", "") for row in all_classification], "min"),
                "consensus_blocker_like_a_count": class_counts.get("CONSENSUS_BLOCKER_LIKE_A", 0),
                "single_baseline_recheck_count": class_counts.get("SINGLE_BASELINE_BLOCKER_RECHECK", 0),
                "blocker_plausible_count": class_counts.get("BLOCKER_PLAUSIBLE_B", 0),
                "binder_like_count": class_counts.get("CONSENSUS_BINDER_LIKE_C", 0) + class_counts.get("SINGLE_BASELINE_BINDER_LIKE_C", 0),
                "evidence_only_count": class_counts.get("EVIDENCE_INFERENCE_ONLY_E", 0),
                "best_haddock_rank": numeric([row.get("haddock_rank", "") for row in all_classification], "min"),
                "best_haddock_score": numeric([row.get("haddock_score", "") for row in all_classification], "min"),
                "evidence_boundary": "dual_reference_geometry_proxy_not_binding_affinity_or_blockade_proof",
            }
        )
        if status != "success":
            failures.append(
                {
                    "candidate_id": candidate_id,
                    "stage": "dual_baseline_postprocess",
                    "status": status,
                    "reason": state.get("message", "postprocess incomplete"),
                    "attempt": state.get("attempt", ""),
                }
            )

    data = root / "data"
    write_tsv(
        data / "baseline_postprocess.tsv",
        candidate_rows,
        [
            "candidate_id", "postprocess_status", "scored_pose_count", "baseline_blocker_geometry",
            "baseline_affinity_proxy", "consensus_blocker_like_a_count", "single_baseline_recheck_count",
            "blocker_plausible_count", "binder_like_count", "evidence_only_count", "best_haddock_rank",
            "best_haddock_score", "evidence_boundary",
        ],
    )
    write_tsv(
        data / "docking_pose_baseline_metrics.tsv",
        baseline_rows,
        ["candidate_id", "model", "baseline_id", "baseline_mode", "haddock_rank", "haddock_score", "blocker_class"],
    )
    write_tsv(
        data / "docking_pose_consensus.tsv",
        consensus_rows,
        ["candidate_id", "model", "consensus_class", "baseline_count", "baseline_classes", "best_haddock_rank"],
    )
    write_tsv(
        data / "postprocess_failures.tsv",
        failures,
        ["candidate_id", "stage", "status", "reason", "attempt"],
    )
    summary = {
        "candidate_count": len(candidates),
        "postprocess_success_candidates": sum(row["postprocess_status"] == "success" for row in candidate_rows),
        "pose_consensus_rows": len(consensus_rows),
        "baseline_metric_rows": len(baseline_rows),
        "status_counts": dict(sorted(Counter(str(row["postprocess_status"]) for row in candidate_rows).items())),
        "baseline_mode": "8X6B guided docking with 8X6B and 9E6Y reference-overlay scoring",
        "scientific_boundary": "9E6Y is an overlay score, not an independent 9E6Y docking run",
    }
    (data / "dual_baseline_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
