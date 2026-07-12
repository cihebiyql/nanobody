#!/usr/bin/env python3
"""Parse RF2 best-model PDB metrics and select a backbone-diverse docking set."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


SCORE_RE = re.compile(r"^SCORE\s+([^:]+):\s+([-+0-9.eE]+)\s*$")
REQUIRED_METRICS = (
    "interaction_pae",
    "pred_lddt",
    "target_aligned_antibody_rmsd",
    "target_aligned_cdr_rmsd",
)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def parse_scores(path: Path) -> dict[str, float]:
    scores: dict[str, float] = {}
    with path.open(encoding="ascii", errors="replace") as handle:
        for line in handle:
            match = SCORE_RE.match(line.strip())
            if match:
                scores[match.group(1)] = float(match.group(2))
    return scores


def classify(scores: dict[str, float]) -> tuple[str, str]:
    missing = [name for name in REQUIRED_METRICS if name not in scores or not math.isfinite(scores[name])]
    if missing:
        return "RF2_FAILED_MISSING_METRICS", ",".join(missing)
    if scores["interaction_pae"] >= 10.0:
        return "RF2_LOW_INTERACTION_CONFIDENCE", "interaction_pae>=10"
    if scores["target_aligned_antibody_rmsd"] >= 2.0:
        return "RF2_POSE_NOT_RECOVERED", "target_aligned_antibody_rmsd>=2A"
    if scores["target_aligned_cdr_rmsd"] >= 2.0:
        return "RF2_POSE_NOT_RECOVERED", "target_aligned_cdr_rmsd>=2A"
    return "RF2_POSE_RECOVERED", "interaction_pae<10_and_target_aligned_rmsd<2A"


def select_diverse(rows: list[dict[str, object]], limit: int) -> list[dict[str, object]]:
    recovered = [row for row in rows if row["rf2_status"] == "RF2_POSE_RECOVERED"]
    recovered.sort(
        key=lambda row: (
            float(row["interaction_pae"]),
            max(float(row["target_aligned_antibody_rmsd"]), float(row["target_aligned_cdr_rmsd"])),
            -float(row["pred_lddt"]),
            float(row["mpnn_nll_score"] or 999),
            str(row["candidate_id"]),
        )
    )
    by_backbone: defaultdict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in recovered:
        by_backbone[(str(row["hotspot_set"]), str(row["backbone_index"]))].append(row)
    selected: list[dict[str, object]] = []
    depth = 0
    while len(selected) < limit:
        added = False
        for key in sorted(by_backbone):
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
    return selected


def parse(manifest_tsv: Path, fr4_mapping_tsv: Path, output_dir: Path, top_limit: int) -> dict[str, object]:
    manifest_rows = read_tsv(manifest_tsv)
    repaired_by_id = {row["candidate_id"]: row["qc_synthesis_sequence"] for row in read_tsv(fr4_mapping_tsv)}
    parsed: list[dict[str, object]] = []
    for row in manifest_rows:
        candidate_id = row["candidate_id"]
        output_pdb = Path(row["expected_output_pdb"])
        if not output_pdb.is_file():
            parsed.append({**row, "rf2_status": "RF2_FAILED_MISSING_OUTPUT", "rf2_reason": "missing_best_pdb"})
            continue
        scores = parse_scores(output_pdb)
        status, reason = classify(scores)
        parsed.append(
            {
                **row,
                "qc_synthesis_sequence": repaired_by_id.get(candidate_id, ""),
                "rf2_status": status,
                "rf2_reason": reason,
                "interaction_pae": scores.get("interaction_pae", ""),
                "pred_lddt": scores.get("pred_lddt", ""),
                "pae": scores.get("pae", ""),
                "target_aligned_antibody_rmsd": scores.get("target_aligned_antibody_rmsd", ""),
                "target_aligned_cdr_rmsd": scores.get("target_aligned_cdr_rmsd", ""),
                "framework_aligned_antibody_rmsd": scores.get("framework_aligned_antibody_rmsd", ""),
                "framework_aligned_cdr_rmsd": scores.get("framework_aligned_cdr_rmsd", ""),
                "rf2_output_pdb": str(output_pdb),
            }
        )

    selected = select_diverse(parsed, top_limit)
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in parsed for key in row}, key=lambda key: (key not in manifest_rows[0], key))
    parsed_path = output_dir / "rf2_metrics.tsv"
    with parsed_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(parsed)
    selected_fields = fields + (["docking_selection_rank"] if "docking_selection_rank" not in fields else [])
    selected_path = output_dir / "rf2_pose_recovered_top.tsv"
    with selected_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=selected_fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(selected)
    with (output_dir / "rf2_pose_recovered_top.fasta").open("w", encoding="ascii", newline="\n") as handle:
        for row in selected:
            sequence = str(row.get("qc_synthesis_sequence") or row["sequence"])
            handle.write(f">{row['candidate_id']}\n{sequence}\n")

    summary: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "expected_candidates": len(manifest_rows),
        "status_counts": dict(sorted(Counter(str(row["rf2_status"]) for row in parsed).items())),
        "pose_recovered": sum(row["rf2_status"] == "RF2_POSE_RECOVERED" for row in parsed),
        "docking_selected": len(selected),
        "docking_unique_backbones": len(
            {(str(row["hotspot_set"]), str(row["backbone_index"])) for row in selected}
        ),
        "thresholds": {
            "interaction_pae_max_exclusive": 10.0,
            "target_aligned_antibody_rmsd_max_a_exclusive": 2.0,
            "target_aligned_cdr_rmsd_max_a_exclusive": 2.0,
        },
        "scientific_boundary": "RF2 pose recovery is a consistency check, not experimental binding or blocking evidence.",
        "all_outputs_present": all(row["rf2_status"] != "RF2_FAILED_MISSING_OUTPUT" for row in parsed),
    }
    (output_dir / "rf2_parse_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest_tsv", type=Path)
    parser.add_argument("fr4_mapping_tsv", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--top-limit", type=int, default=50)
    args = parser.parse_args()
    print(json.dumps(parse(args.manifest_tsv, args.fr4_mapping_tsv, args.output_dir, args.top_limit), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

