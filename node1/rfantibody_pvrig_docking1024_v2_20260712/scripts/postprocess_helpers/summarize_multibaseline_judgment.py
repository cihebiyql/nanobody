#!/usr/bin/env python3
"""Summarize blocker judgment calls across reference-structure baselines."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


OUTPUT_FIELDS = [
    "model",
    "consensus_class",
    "baseline_count",
    "blocker_like_count",
    "plausible_count",
    "binder_like_count",
    "evidence_only_count",
    "baseline_classes",
    "best_haddock_rank",
    "recommended_next_step",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Combine one or more apply_blocker_judgment.py CSV outputs into a "
            "multi-baseline consensus summary."
        )
    )
    parser.add_argument(
        "--classification",
        action="append",
        required=True,
        help="Baseline-labeled classification CSV, for example 8x6b=path/to/file.csv. Repeatable.",
    )
    parser.add_argument("--out-csv", required=True, type=Path, help="Output consensus CSV.")
    parser.add_argument("--out-md", type=Path, help="Optional Markdown consensus report.")
    parser.add_argument("--candidate-name", default="candidate", help="Name shown in Markdown report.")
    return parser.parse_args()


def parse_classification_arg(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise SystemExit(f"--classification must be label=path, got {value!r}")
    label, path = value.split("=", 1)
    label = label.strip()
    if not label:
        raise SystemExit(f"empty baseline label in {value!r}")
    csv_path = Path(path)
    if not csv_path.exists():
        raise SystemExit(f"missing classification CSV: {csv_path}")
    return label, csv_path


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def to_float(text: str | None, default: float = 999999.0) -> float:
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def consensus_for(classes: list[str], baseline_count: int) -> tuple[str, str]:
    counts = Counter(classes)
    a = counts["BLOCKER_LIKE_A"]
    b = counts["BLOCKER_PLAUSIBLE_B"]
    c = counts["BINDER_LIKE_C"]
    e = counts["EVIDENCE_INFERENCE_ONLY_E"]

    if a >= 2 and c == 0:
        return (
            "CONSENSUS_BLOCKER_LIKE_A",
            "prioritize after leakage and format checks; both reference baselines support blocker-like geometry",
        )
    if a >= 1 and c >= 1:
        return (
            "DISCORDANT_REDOCK_REQUIRED",
            "one baseline is blocker-like but another is binder-like; inspect alignment and redock before prioritizing",
        )
    if a == 0 and b > 0 and c > 0:
        return (
            "DISCORDANT_PLAUSIBLE_VS_BINDER_RECHECK",
            "one baseline is plausible but another is binder-like; inspect PVRL2 placement and do not prioritize without redocking or assay evidence",
        )
    if a == 1:
        if baseline_count == 1:
            return (
                "SINGLE_BASELINE_BLOCKER_RECHECK",
                "repeat against 9E6Y before final ranking; current single baseline supports blocker-like geometry",
            )
        return (
            "SINGLE_BASELINE_BLOCKER_RECHECK",
            "inspect weaker baseline and decide whether this is an alternative epitope or an unstable pose",
        )
    if c == baseline_count and baseline_count > 0:
        if baseline_count == 1:
            return (
                "SINGLE_BASELINE_BINDER_LIKE_C",
                "downgrade for now; current baseline shows hotspot/binding without enough PVRL2 occlusion",
            )
        return (
            "CONSENSUS_BINDER_LIKE_C",
            "downgrade; available baselines show hotspot/binding without enough PVRL2 occlusion",
        )
    if b > 0 and c == 0:
        return (
            "BLOCKER_PLAUSIBLE_B",
            "keep as follow-up only; collect stronger occlusion or assay evidence",
        )
    if e == baseline_count and baseline_count > 0:
        return (
            "EVIDENCE_INFERENCE_ONLY_E",
            "do not prioritize as blocker until missing occlusion or blocking evidence is collected",
        )
    return (
        "INCOMPLETE_OR_MIXED_EVIDENCE",
        "review input columns, baseline alignment, and missing evidence before ranking",
    )


def build_summary(inputs: list[tuple[str, Path]]) -> list[dict[str, str]]:
    by_model: dict[str, list[tuple[str, dict[str, str]]]] = defaultdict(list)
    for label, path in inputs:
        for row in read_rows(path):
            model = row.get("model", "").strip()
            if model:
                by_model[model].append((label, row))

    output: list[dict[str, str]] = []
    for model, baseline_rows in sorted(by_model.items()):
        classes = [row.get("blocker_class", "") for _, row in baseline_rows]
        consensus_class, next_step = consensus_for(classes, len(baseline_rows))
        counts = Counter(classes)
        best_rank = min(to_float(row.get("haddock_rank")) for _, row in baseline_rows)
        baseline_classes = ";".join(f"{label}:{row.get('blocker_class', '')}" for label, row in baseline_rows)
        output.append(
            {
                "model": model,
                "consensus_class": consensus_class,
                "baseline_count": str(len(baseline_rows)),
                "blocker_like_count": str(counts["BLOCKER_LIKE_A"]),
                "plausible_count": str(counts["BLOCKER_PLAUSIBLE_B"]),
                "binder_like_count": str(counts["BINDER_LIKE_C"]),
                "evidence_only_count": str(counts["EVIDENCE_INFERENCE_ONLY_E"]),
                "baseline_classes": baseline_classes,
                "best_haddock_rank": f"{best_rank:g}",
                "recommended_next_step": next_step,
            }
        )
    return output


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_md(path: Path, rows: list[dict[str, str]], candidate_name: str) -> None:
    counts = Counter(row["consensus_class"] for row in rows)
    lines = [
        f"# Multi-baseline blocker consensus: {candidate_name}",
        "",
        "## Summary",
        "",
    ]
    for label, count in sorted(counts.items()):
        lines.append(f"- {label}: {count}")
    lines.extend(
        [
            "",
            "## Poses",
            "",
            "| model | consensus | baselines | best_rank | next_step |",
            "| --- | --- | --- | ---: | --- |",
        ]
    )
    for row in rows:
        baselines = row["baseline_classes"].replace("|", "/")
        next_step = row["recommended_next_step"].replace("|", "/")
        lines.append(
            f"| {row['model']} | {row['consensus_class']} | {baselines} | "
            f"{row['best_haddock_rank']} | {next_step} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "- A single 8X6B pass is useful but remains a recheck label until 9E6Y is scored.",
            "- Two-baseline support is stronger than a single-baseline blocker-like call.",
            "- Discordant A/C calls should trigger alignment inspection or redocking, not automatic promotion.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    inputs = [parse_classification_arg(item) for item in args.classification]
    rows = build_summary(inputs)
    write_csv(args.out_csv, rows)
    if args.out_md:
        write_md(args.out_md, rows, args.candidate_name)
    counts = Counter(row["consensus_class"] for row in rows)
    print("multi-baseline summary complete")
    print(f"rows={len(rows)}")
    for label, count in sorted(counts.items()):
        print(f"{label}={count}")


if __name__ == "__main__":
    main()
