#!/usr/bin/env python3
"""Apply success-case-calibrated PVRIG blocker judgment rules to pose scores."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_RULES = SCRIPT_DIR / "blocker_judgment_rules_v2.json"


FIELD_ALIASES = {
    "model": ["model", "pose", "pose_id"],
    "haddock_rank": ["haddock_rank", "rank"],
    "haddock_score": ["haddock_score", "score"],
    "hotspot_overlap_count": ["hotspot_overlap_count"],
    "total_occlusion": [
        "total_vhh_pvrl2_residue_pair_occlusion",
        "total_pvrl2_residue_pair_occlusion",
    ],
    "cdr3_occlusion": [
        "cdr3_pvrl2_residue_pair_occlusion",
        "cdr3_residue_pair_occlusion",
    ],
    "cdr3_fraction": [
        "cdr3_occlusion_fraction",
        "cdr3_residue_pair_occlusion_fraction",
    ],
    "framework_occlusion": [
        "framework_residue_pair_occlusion",
        "framework_pvrl2_residue_pair_occlusion",
    ],
}


OUTPUT_FIELDS = [
    "model",
    "haddock_rank",
    "haddock_score",
    "hotspot_overlap_count",
    "total_vhh_pvrl2_residue_pair_occlusion",
    "cdr3_pvrl2_residue_pair_occlusion",
    "cdr3_occlusion_fraction",
    "framework_residue_pair_occlusion",
    "pass_hotspot",
    "pass_total_occlusion",
    "pass_cdr3_occlusion",
    "pass_cdr3_fraction",
    "blocker_class",
    "confidence",
    "classification_reason",
    "recommended_next_step",
    "evidence_boundary",
    "source_score_files",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Classify PVRIG VHH/antibody docking poses using the local "
            "success-case-calibrated blocker judgment rules."
        )
    )
    parser.add_argument(
        "--occlusion-csv",
        required=True,
        type=Path,
        help="CSV containing total/CDR3 PVRL2 occlusion metrics.",
    )
    parser.add_argument(
        "--mechanism-csv",
        type=Path,
        help="Optional CSV with HADDOCK rank/score and hotspot metrics to merge by model.",
    )
    parser.add_argument(
        "--rules-json",
        type=Path,
        default=DEFAULT_RULES,
        help=f"Judgment rules JSON. Default: {DEFAULT_RULES}",
    )
    parser.add_argument("--out-csv", required=True, type=Path, help="Output classification CSV.")
    parser.add_argument("--out-md", type=Path, help="Optional human-readable Markdown report.")
    parser.add_argument(
        "--candidate-name",
        default="candidate",
        help="Name shown in the Markdown report.",
    )
    parser.add_argument(
        "--format-context",
        default="naked_vhh",
        choices=["naked_vhh", "vhh_fc", "igg1", "igg4", "bispecific", "unknown"],
        help="Intended molecule format context; this is annotated, not inferred from docking.",
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def norm_key(value: str | None) -> str:
    return (value or "").strip()


def pick(row: dict[str, str], canonical: str) -> str:
    for field in FIELD_ALIASES[canonical]:
        if field in row and row[field] != "":
            return row[field]
    return ""


def to_float(value: str | float | int | None, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (float, int)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def load_rules(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = data["classifier"]["BLOCKER_LIKE_A"]["required_for_vhh_docking"]
    return {
        "hotspot_min": threshold_value(required["hotspot_overlap_count"]),
        "total_min": threshold_value(required["total_vhh_pvrl2_residue_pair_occlusion"]),
        "cdr3_min": threshold_value(required["cdr3_pvrl2_residue_pair_occlusion"]),
        "cdr3_fraction_min": threshold_value(required["cdr3_occlusion_fraction"]),
        "binder_total_max": 50.0,
        "raw": data,
    }


def threshold_value(text: str) -> float:
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", text)
    if not match:
        raise ValueError(f"Cannot parse threshold from {text!r}")
    return float(match.group(0))


def merge_rows(occlusion_rows: list[dict[str, str]], mechanism_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    mechanism_by_model = {norm_key(pick(row, "model")): row for row in mechanism_rows}
    merged: list[dict[str, str]] = []
    for row in occlusion_rows:
        model = norm_key(pick(row, "model"))
        combined = dict(mechanism_by_model.get(model, {}))
        combined.update(row)
        merged.append(combined)
    return merged


def bool_text(value: bool) -> str:
    return "yes" if value else "no"


def classify(row: dict[str, str], rules: dict[str, Any], format_context: str, source_files: str) -> dict[str, str]:
    hotspot = to_float(pick(row, "hotspot_overlap_count"))
    total = to_float(pick(row, "total_occlusion"))
    cdr3 = to_float(pick(row, "cdr3_occlusion"))
    cdr3_fraction = to_float(pick(row, "cdr3_fraction"))
    framework = to_float(pick(row, "framework_occlusion"))

    pass_hotspot = hotspot >= rules["hotspot_min"]
    pass_total = total >= rules["total_min"]
    pass_cdr3 = cdr3 >= rules["cdr3_min"]
    pass_fraction = cdr3_fraction >= rules["cdr3_fraction_min"]

    if pass_hotspot and pass_total and pass_cdr3 and pass_fraction:
        blocker_class = "BLOCKER_LIKE_A"
        confidence = "high_screening"
        reason = "passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds"
        next_step = "repeat scoring against 9E6Y baseline, run leakage checks, then prioritize for assay or higher-resolution modeling"
    elif pass_hotspot and total < rules["binder_total_max"]:
        blocker_class = "BINDER_LIKE_C"
        confidence = "high_screening_negative"
        reason = "hotspot/interface contact is present but PVRL2 overlay occlusion is below binder-like cutoff"
        next_step = "downgrade or redock with PVRL2-competition restraints; do not prioritize as blocker"
    elif total >= rules["total_min"] and (pass_hotspot or cdr3 >= 50):
        blocker_class = "BLOCKER_PLAUSIBLE_B"
        confidence = "medium_screening"
        reason = "substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing"
        next_step = "inspect pose manually, check 9E6Y baseline, and consider alternative/distinct epitope rationale"
    elif total >= 300 and hotspot >= 10 and cdr3 >= 50:
        blocker_class = "BLOCKER_PLAUSIBLE_B"
        confidence = "low_medium_screening"
        reason = "partial occlusion and interface signal suggest possible blocker geometry below A thresholds"
        next_step = "redock or rescore; keep only if distinct-epitope or format context explains the weaker HR-151-like metrics"
    else:
        blocker_class = "EVIDENCE_INFERENCE_ONLY_E"
        confidence = "low_screening"
        reason = "does not meet blocker-like or binder-like calibrated criteria from current available columns"
        next_step = "collect missing blocking/occlusion evidence or deprioritize for blocker workflow"

    if format_context in {"vhh_fc", "igg1", "igg4", "bispecific"}:
        next_step += "; separately evaluate format/Fc/NK/TIGIT context because docking does not prove these effects"

    return {
        "model": norm_key(pick(row, "model")),
        "haddock_rank": norm_key(pick(row, "haddock_rank")),
        "haddock_score": norm_key(pick(row, "haddock_score")),
        "hotspot_overlap_count": f"{hotspot:g}",
        "total_vhh_pvrl2_residue_pair_occlusion": f"{total:g}",
        "cdr3_pvrl2_residue_pair_occlusion": f"{cdr3:g}",
        "cdr3_occlusion_fraction": f"{cdr3_fraction:.6g}",
        "framework_residue_pair_occlusion": f"{framework:g}",
        "pass_hotspot": bool_text(pass_hotspot),
        "pass_total_occlusion": bool_text(pass_total),
        "pass_cdr3_occlusion": bool_text(pass_cdr3),
        "pass_cdr3_fraction": bool_text(pass_fraction),
        "blocker_class": blocker_class,
        "confidence": confidence,
        "classification_reason": reason,
        "recommended_next_step": next_step,
        "evidence_boundary": (
            "Docking/overlay classification only; not experimental proof of PVRIG-PVRL2 blocking. "
            "Residue contacts remain inference unless supported by complex structure or epitope mapping."
        ),
        "source_score_files": source_files,
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def sort_for_report(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    order = {
        "BLOCKER_LIKE_A": 0,
        "BLOCKER_PLAUSIBLE_B": 1,
        "FORMAT_CONTEXT_D": 2,
        "BINDER_LIKE_C": 3,
        "EVIDENCE_INFERENCE_ONLY_E": 4,
    }

    def key(row: dict[str, str]) -> tuple[int, float]:
        rank = to_float(row.get("haddock_rank"), 999999)
        return (order.get(row["blocker_class"], 99), rank)

    return sorted(rows, key=key)


def write_markdown(path: Path, rows: list[dict[str, str]], candidate_name: str, format_context: str, rules_path: Path) -> None:
    counts = Counter(row["blocker_class"] for row in rows)
    lines = [
        f"# Blocker judgment report: {candidate_name}",
        "",
        f"Format context: `{format_context}`",
        f"Rules: `{rules_path}`",
        "",
        "## Summary",
        "",
    ]
    for label in ["BLOCKER_LIKE_A", "BLOCKER_PLAUSIBLE_B", "BINDER_LIKE_C", "EVIDENCE_INFERENCE_ONLY_E", "FORMAT_CONTEXT_D"]:
        if counts.get(label, 0):
            lines.append(f"- {label}: {counts[label]}")
    lines.extend(
        [
            "",
            "## Top classified poses",
            "",
            "| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in sort_for_report(rows)[:20]:
        reason = row["classification_reason"].replace("|", "/")
        lines.append(
            "| {model} | {blocker_class} | {haddock_rank} | {hotspot_overlap_count} | "
            "{total_vhh_pvrl2_residue_pair_occlusion} | {cdr3_pvrl2_residue_pair_occlusion} | "
            "{cdr3_occlusion_fraction} | {reason} |".format(reason=reason, **row)
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.",
            "- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.",
            "- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.",
            "- Repeat the overlay against 9E6Y before final candidate ranking.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    rules = load_rules(args.rules_json)
    occlusion_rows = read_csv(args.occlusion_csv)
    mechanism_rows = read_csv(args.mechanism_csv) if args.mechanism_csv else []
    merged = merge_rows(occlusion_rows, mechanism_rows)
    source_files = str(args.occlusion_csv)
    if args.mechanism_csv:
        source_files += f";{args.mechanism_csv}"
    classified = [classify(row, rules, args.format_context, source_files) for row in merged]
    write_csv(args.out_csv, classified)
    if args.out_md:
        write_markdown(args.out_md, classified, args.candidate_name, args.format_context, args.rules_json)
    counts = Counter(row["blocker_class"] for row in classified)
    print("classification complete")
    print(f"rows={len(classified)}")
    for label, count in sorted(counts.items()):
        print(f"{label}={count}")


if __name__ == "__main__":
    main()
