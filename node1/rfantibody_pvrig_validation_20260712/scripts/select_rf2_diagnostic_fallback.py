#!/usr/bin/env python3
"""Select a diverse diagnostic docking set when no RF2 pose meets strict recovery gates."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def annotate(row: dict[str, str]) -> dict[str, object]:
    interaction_pae = float(row["interaction_pae"])
    antibody_rmsd = float(row["target_aligned_antibody_rmsd"])
    cdr_rmsd = float(row["target_aligned_cdr_rmsd"])
    max_rmsd = max(antibody_rmsd, cdr_rmsd)
    if interaction_pae < 10:
        stratum = "LOW_IPAE_ALTERNATE_OR_NEAR_POSE"
        stratum_priority = 0
    elif max_rmsd < 3 and interaction_pae < 15:
        stratum = "NEAR_POSE_BORDERLINE_IPAE"
        stratum_priority = 1
    else:
        stratum = "BEST_AVAILABLE_COMPOSITE"
        stratum_priority = 2
    composite = interaction_pae / 10.0 + max_rmsd / 5.0 - float(row["pred_lddt"]) * 0.25
    return {
        **row,
        "rf2_diagnostic_stratum": stratum,
        "rf2_diagnostic_stratum_priority": stratum_priority,
        "rf2_max_target_aligned_rmsd": max_rmsd,
        "rf2_diagnostic_composite": composite,
        "docking_evidence_status": "RF2_DIAGNOSTIC_FALLBACK_NOT_STRICT_POSE_RECOVERY",
    }


def select(metrics_tsv: Path, output_dir: Path, limit: int) -> dict[str, object]:
    rows = [annotate(row) for row in read_tsv(metrics_tsv)]
    if not rows:
        raise ValueError("RF2 metrics are empty")
    if any(row["rf2_status"] == "RF2_POSE_RECOVERED" for row in rows):
        raise ValueError("strict RF2 pose-recovered candidates exist; diagnostic fallback is not appropriate")
    rows.sort(
        key=lambda row: (
            int(row["rf2_diagnostic_stratum_priority"]),
            float(row["rf2_diagnostic_composite"]),
            float(row["interaction_pae"]),
            str(row["candidate_id"]),
        )
    )
    by_backbone: defaultdict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_backbone[(str(row["hotspot_set"]), str(row["backbone_index"]))].append(row)
    backbone_order = sorted(
        by_backbone,
        key=lambda key: (
            int(by_backbone[key][0]["rf2_diagnostic_stratum_priority"]),
            float(by_backbone[key][0]["rf2_diagnostic_composite"]),
            key,
        ),
    )
    selected: list[dict[str, object]] = []
    depth = 0
    while len(selected) < limit:
        added = False
        for key in backbone_order:
            candidates = by_backbone[key]
            if depth < len(candidates):
                selected.append(candidates[depth])
                added = True
                if len(selected) == limit:
                    break
        if not added:
            break
        depth += 1
    for rank, row in enumerate(selected, start=1):
        row["docking_selection_rank"] = rank

    output_dir.mkdir(parents=True, exist_ok=True)
    fields = list(selected[0])
    with (output_dir / "rf2_diagnostic_docking_top.tsv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(selected)
    with (output_dir / "rf2_diagnostic_docking_top.fasta").open("w", encoding="ascii", newline="\n") as handle:
        for row in selected:
            sequence = str(row.get("qc_synthesis_sequence") or row["sequence"])
            handle.write(f">{row['candidate_id']}\n{sequence}\n")
    summary: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rf2_candidates": len(rows),
        "strict_pose_recovered": 0,
        "diagnostic_selected": len(selected),
        "diagnostic_unique_backbones": len(
            {(str(row["hotspot_set"]), str(row["backbone_index"])) for row in selected}
        ),
        "selected_by_set": dict(sorted(Counter(str(row["hotspot_set"]) for row in selected).items())),
        "selected_by_stratum": dict(
            sorted(Counter(str(row["rf2_diagnostic_stratum"]) for row in selected).items())
        ),
        "selection_formula": "interaction_pae/10 + max(target_aligned_RMSD)/5 - 0.25*pred_lddt",
        "scientific_boundary": (
            "These candidates failed strict blind RF2 pose recovery. Docking is diagnostic and cannot rescue "
            "them into a high-confidence blocker class without explicitly retaining this failure flag."
        ),
        "all_checks_passed": True,
    }
    (output_dir / "rf2_diagnostic_docking_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metrics_tsv", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()
    print(json.dumps(select(args.metrics_tsv, args.output_dir, args.limit), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

