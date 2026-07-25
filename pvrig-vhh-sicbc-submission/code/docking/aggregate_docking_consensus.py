#!/usr/bin/env python3
"""Aggregate per-model dual-baseline consensus into conservative candidate labels."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def candidate_label(classes: Counter[str], best_a_rank: int | None) -> tuple[str, str]:
    consensus_a = classes.get("CONSENSUS_BLOCKER_LIKE_A", 0)
    single_a = classes.get("SINGLE_BASELINE_BLOCKER_RECHECK", 0)
    plausible = classes.get("BLOCKER_PLAUSIBLE_B", 0)
    binder = classes.get("BINDER_LIKE_C", 0)
    if consensus_a >= 2 and best_a_rank is not None and best_a_rank <= 3:
        return "CONSENSUS_BLOCKER_LIKE_A", "FINAL_POSITIVE_HIGH"
    if consensus_a >= 1:
        return "CONSENSUS_A_SPARSE_RECHECK", "FINAL_RECHECK_SINGLE_BASELINE"
    if single_a >= 1:
        return "SINGLE_BASELINE_BLOCKER_RECHECK", "FINAL_RECHECK_SINGLE_BASELINE"
    if plausible >= 1:
        return "BLOCKER_PLAUSIBLE_B", "FINAL_POSITIVE_PLAUSIBLE"
    if binder >= 1:
        return "BINDER_LIKE_C", "FINAL_BINDER_NOT_BLOCKER"
    return "EVIDENCE_INFERENCE_ONLY_E", "FINAL_INSUFFICIENT_GEOMETRY"


def apply_rf2_boundary(docking_label: str, rf2_evidence_status: str) -> str:
    if "DIAGNOSTIC_FALLBACK_NOT_STRICT_POSE_RECOVERY" in rf2_evidence_status:
        return "FINAL_DIAGNOSTIC_ONLY_RF2_NOT_RECOVERED"
    return docking_label


def aggregate(manifest_tsv: Path, postprocess_root: Path, output_dir: Path) -> dict[str, object]:
    manifest = read_tsv(manifest_tsv)
    rows: list[dict[str, object]] = []
    missing: list[str] = []
    for source in manifest:
        candidate_id = source["candidate_id"]
        consensus_path = postprocess_root / candidate_id / "reports" / f"{candidate_id}_8x6b_9e6y_consensus.csv"
        if not consensus_path.is_file():
            missing.append(candidate_id)
            continue
        with consensus_path.open(newline="", encoding="utf-8-sig") as handle:
            models = list(csv.DictReader(handle))
        classes = Counter(row["consensus_class"] for row in models)
        a_ranks = [int(float(row["best_haddock_rank"])) for row in models if row["consensus_class"] == "CONSENSUS_BLOCKER_LIKE_A"]
        best_a_rank = min(a_ranks) if a_ranks else None
        computational_class, docking_label = candidate_label(classes, best_a_rank)
        rf2_evidence_status = source.get("docking_evidence_status", "")
        final_label = apply_rf2_boundary(docking_label, rf2_evidence_status)
        best_model = min(models, key=lambda row: int(float(row["best_haddock_rank"])))
        rows.append(
            {
                "candidate_id": candidate_id,
                "hotspot_set": source.get("hotspot_set", ""),
                "backbone_index": source.get("backbone_index", ""),
                "mpnn_index": source.get("mpnn_index", ""),
                "docking_selection_rank": source.get("docking_selection_rank", ""),
                "rf2_interaction_pae": source.get("interaction_pae", ""),
                "rf2_pred_lddt": source.get("pred_lddt", ""),
                "rf2_target_aligned_antibody_rmsd": source.get("target_aligned_antibody_rmsd", ""),
                "rf2_target_aligned_cdr_rmsd": source.get("target_aligned_cdr_rmsd", ""),
                "model_count": len(models),
                "consensus_blocker_like_a_count": classes.get("CONSENSUS_BLOCKER_LIKE_A", 0),
                "single_baseline_recheck_count": classes.get("SINGLE_BASELINE_BLOCKER_RECHECK", 0),
                "blocker_plausible_b_count": classes.get("BLOCKER_PLAUSIBLE_B", 0),
                "binder_like_c_count": classes.get("BINDER_LIKE_C", 0),
                "evidence_only_count": classes.get("EVIDENCE_INFERENCE_ONLY_E", 0),
                "best_consensus_a_haddock_rank": best_a_rank if best_a_rank is not None else "",
                "top_haddock_model": best_model["model"],
                "top_haddock_model_consensus_class": best_model["consensus_class"],
                "computational_blocker_class": computational_class,
                "docking_geometry_label": docking_label,
                "rf2_docking_evidence_status": rf2_evidence_status,
                "final_blocker_label": final_label,
                "consensus_csv": str(consensus_path),
            }
        )
    if missing:
        raise ValueError(f"missing consensus CSV for {len(missing)} candidates: {missing[:5]}")
    priority = {
        "FINAL_POSITIVE_HIGH": 0,
        "FINAL_RECHECK_SINGLE_BASELINE": 1,
        "FINAL_POSITIVE_PLAUSIBLE": 2,
        "FINAL_BINDER_NOT_BLOCKER": 3,
        "FINAL_INSUFFICIENT_GEOMETRY": 4,
        "FINAL_DIAGNOSTIC_ONLY_RF2_NOT_RECOVERED": 5,
    }
    rows.sort(
        key=lambda row: (
            priority[str(row["final_blocker_label"])],
            -int(row["consensus_blocker_like_a_count"]),
            int(row["docking_selection_rank"] or 10**9),
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["final_rank"] = rank
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with (output_dir / "final_blocker_screen.tsv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    summary: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(rows),
        "final_label_counts": dict(sorted(Counter(str(row["final_blocker_label"]) for row in rows).items())),
        "final_positive_high": sum(row["final_blocker_label"] == "FINAL_POSITIVE_HIGH" for row in rows),
        "high_rule": (
            "at least two A/A models and best A/A HADDOCK rank <=3, and the candidate must not be an "
            "RF2 diagnostic fallback"
        ),
        "scientific_boundary": "All labels are computational priorities, not experimental binding, Kd, or blockade claims.",
        "all_checks_passed": True,
    }
    (output_dir / "final_blocker_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest_tsv", type=Path)
    parser.add_argument("postprocess_root", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(aggregate(args.manifest_tsv, args.postprocess_root, args.output_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
