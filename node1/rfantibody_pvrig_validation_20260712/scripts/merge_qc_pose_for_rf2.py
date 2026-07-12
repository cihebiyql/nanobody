#!/usr/bin/env python3
"""Merge pose/MPNN evidence with full repaired-sequence QC to freeze RF2 inputs."""

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


def merge(
    pose_shortlist_tsv: Path,
    repair_mapping_tsv: Path,
    fast_merged_tsv: Path,
    full_merged_tsv: Path,
    output_dir: Path,
) -> dict[str, object]:
    pose_rows = read_tsv(pose_shortlist_tsv)
    repair_rows = read_tsv(repair_mapping_tsv)
    fast_rows = read_tsv(fast_merged_tsv)
    full_rows = read_tsv(full_merged_tsv)
    repair_by_id = {row["candidate_id"]: row for row in repair_rows}
    fast_by_id = {row["candidate_id"]: row for row in fast_rows}
    full_by_id = {row["candidate_id"]: row for row in full_rows}
    for label, rows, by_id in (
        ("pose", pose_rows, {row["candidate_id"]: row for row in pose_rows}),
        ("repair", repair_rows, repair_by_id),
        ("fast", fast_rows, fast_by_id),
        ("full", full_rows, full_by_id),
    ):
        if len(rows) != len(by_id):
            raise ValueError(f"duplicate candidate ID in {label} input")

    merged: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    for pose in pose_rows:
        candidate_id = pose["candidate_id"]
        repair = repair_by_id.get(candidate_id)
        fast = fast_by_id.get(candidate_id)
        full = full_by_id.get(candidate_id)
        missing = [name for name, row in (("repair", repair), ("fast", fast), ("full", full)) if row is None]
        if missing:
            raise ValueError(f"{candidate_id}: missing merge rows {missing}")
        repaired_sequence = repair["qc_synthesis_sequence"]
        if fast["sequence"] != repaired_sequence or full["sequence"] != repaired_sequence:
            raise ValueError(f"{candidate_id}: QC sequence is not the FR4-restored sequence")
        row: dict[str, object] = {
            **pose,
            "qc_synthesis_sequence": repaired_sequence,
            "qc_fast_hard_fail": fast.get("hard_fail", ""),
            "qc_fast_recommendation": fast.get("recommendation", ""),
            "qc_fast_reason_summary": fast.get("reason_summary", ""),
            "qc_full_hard_fail": full.get("hard_fail", ""),
            "qc_full_recommendation": full.get("recommendation", ""),
            "qc_full_reason_summary": full.get("reason_summary", ""),
            "qc_full_final_score": full.get("final_score", ""),
            "qc_full_abnativ_vhh_score": full.get("AbNatiV_VHH_score", ""),
            "qc_full_sapiens_status": full.get("official_validator_pass", ""),
        }
        if fast.get("hard_fail") == "True" or full.get("hard_fail") == "True":
            row["rf2_eligibility"] = "REJECT_SEQUENCE_QC_HARD_FAIL"
            rejected.append(row)
        else:
            row["rf2_eligibility"] = "ELIGIBLE_POSE_AND_SEQUENCE_QC"
            merged.append(row)

    merged.sort(
        key=lambda row: (
            str(row["hotspot_set"]),
            int(row["backbone_index"]),
            float(row["mpnn_nll_score"]),
            str(row["candidate_id"]),
        )
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = list(merged[0] if merged else rejected[0])
    for name, rows in (("rf2_shortlist_final.tsv", merged), ("rf2_sequence_qc_rejected.tsv", rejected)):
        with (output_dir / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    with (output_dir / "rf2_shortlist_final.fasta").open("w", encoding="ascii", newline="\n") as handle:
        for row in merged:
            handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")

    summary: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pose_shortlist_candidates": len(pose_rows),
        "eligible_candidates": len(merged),
        "rejected_candidates": len(rejected),
        "eligible_backbones": len({(row["hotspot_set"], row["backbone_index"]) for row in merged}),
        "eligible_by_set": dict(sorted(Counter(str(row["hotspot_set"]) for row in merged).items())),
        "rejected_by_reason": dict(sorted(Counter(str(row["qc_full_reason_summary"]) for row in rejected).items())),
        "sequence_policy": "RF2 uses original pose sequence; QC/synthesis sequence restores one terminal FR4 serine.",
        "scientific_boundary": "Eligibility combines sequence QC and design-pose triage; it does not imply binding or blocking.",
        "all_checks_passed": True,
    }
    (output_dir / "rf2_shortlist_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pose_shortlist_tsv", type=Path)
    parser.add_argument("repair_mapping_tsv", type=Path)
    parser.add_argument("fast_merged_tsv", type=Path)
    parser.add_argument("full_merged_tsv", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            merge(
                args.pose_shortlist_tsv,
                args.repair_mapping_tsv,
                args.fast_merged_tsv,
                args.full_merged_tsv,
                args.output_dir,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

