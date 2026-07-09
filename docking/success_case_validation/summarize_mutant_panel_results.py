#!/usr/bin/env python3
"""Stratify mutant validation panel consensus results by metadata layers."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PANEL_ROOT = ROOT / "docking" / "calibration" / "mutant_validation_panel"
CLASS_ORDER = [
    "CONSENSUS_BLOCKER_LIKE_A",
    "SINGLE_BASELINE_BLOCKER_RECHECK",
    "BLOCKER_PLAUSIBLE_B",
    "EVIDENCE_INFERENCE_ONLY_E",
]
SUMMARY_FIELDS = [
    "stratification",
    "stratum",
    "panel_records",
    "consensus_rows",
    "CONSENSUS_BLOCKER_LIKE_A",
    "SINGLE_BASELINE_BLOCKER_RECHECK",
    "BLOCKER_PLAUSIBLE_B",
    "EVIDENCE_INFERENCE_ONLY_E",
    "OTHER_CONSENSUS_CLASS",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-root", type=Path, default=DEFAULT_PANEL_ROOT)
    parser.add_argument("--panel-csv", type=Path)
    parser.add_argument("--status-csv", type=Path)
    parser.add_argument("--leakage-csv", type=Path)
    parser.add_argument("--out-md", type=Path)
    parser.add_argument("--out-csv", type=Path)
    return parser.parse_args()


def require_file(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"missing {label}: {path}")


def read_csv(path: Path, label: str) -> list[dict[str, str]]:
    require_file(path, label)
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def index_by(rows: list[dict[str, str]], key: str, label: str) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row.get(key, "")
        if not value:
            raise SystemExit(f"missing {key} value in {label}")
        if value in indexed:
            raise SystemExit(f"duplicate {key}={value} in {label}")
        indexed[value] = row
    return indexed


def resolve_path(value: str, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def consensus_candidates(item: dict[str, str], status: dict[str, str], panel_root: Path) -> list[Path]:
    name = item["mutant_name"]
    workdir = Path(status.get("workdir") or item.get("workdir") or panel_root / "workdirs" / name)
    candidates: list[Path] = []
    status_consensus = (status.get("consensus_csv") or "").strip()
    if status_consensus and status_consensus.lower() not in {"yes", "no", "missing"}:
        candidates.append(resolve_path(status_consensus, panel_root))
    candidates.extend(
        [
            workdir / "reports" / "multibaseline_consensus.csv",
            workdir / "reports" / f"{name}_multibaseline_consensus.csv",
            workdir / "reports" / f"{name}_8x6b_9e6y_consensus.csv",
        ]
    )
    return candidates


def find_consensus_csv(item: dict[str, str], status: dict[str, str], panel_root: Path) -> Path:
    candidates = consensus_candidates(item, status, panel_root)
    for path in candidates:
        if path.exists():
            return path
    checked = "; ".join(str(path) for path in candidates)
    raise SystemExit(f"missing consensus CSV for {item['mutant_name']}; checked: {checked}")


def base_name(item: dict[str, str]) -> str:
    return item.get("base_name") or item.get("base_molecule") or item["mutant_name"]


def case_level_call(counts: Counter[str]) -> str:
    if counts["CONSENSUS_BLOCKER_LIKE_A"]:
        return "HAS_CONSENSUS_BLOCKER_LIKE_A"
    if counts["SINGLE_BASELINE_BLOCKER_RECHECK"]:
        return "HAS_SINGLE_BASELINE_BLOCKER_RECHECK"
    if counts["BLOCKER_PLAUSIBLE_B"]:
        return "BLOCKER_PLAUSIBLE_B_ONLY"
    if counts["EVIDENCE_INFERENCE_ONLY_E"]:
        return "EVIDENCE_INFERENCE_ONLY_E_ONLY"
    return "NO_USABLE_CONSENSUS_ROWS"


def is_disruptive_alanine(item: dict[str, str]) -> bool:
    mutation_class = item.get("mutation_class", "").lower()
    mutations = item.get("mutations_1based", "").upper()
    changed_cdr = item.get("changed_cdr", "").upper()
    return (
        "alanine" in mutation_class
        or "ala" in mutation_class
        or ("CDR3" in changed_cdr and any(token.endswith("A") for token in mutations.replace(",", ";").split(";")))
    )


def add_to_bucket(bucket: dict[str, object], counts: Counter[str]) -> None:
    bucket["panel_records"] = int(bucket["panel_records"]) + 1
    bucket["consensus_rows"] = int(bucket["consensus_rows"]) + sum(counts.values())
    for key, value in counts.items():
        if key in CLASS_ORDER:
            bucket[key] = int(bucket[key]) + value
        else:
            bucket["OTHER_CONSENSUS_CLASS"] = int(bucket["OTHER_CONSENSUS_CLASS"]) + value


def empty_bucket() -> dict[str, object]:
    bucket: dict[str, object] = {"panel_records": 0, "consensus_rows": 0, "OTHER_CONSENSUS_CLASS": 0}
    for key in CLASS_ORDER:
        bucket[key] = 0
    return bucket


def build_analysis(panel_root: Path, panel_csv: Path, status_csv: Path, leakage_csv: Path) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    panel_rows = read_csv(panel_csv, "mutant panel CSV")
    status_rows = read_csv(status_csv, "mutant panel status CSV")
    leakage_rows = read_csv(leakage_csv, "mutant panel sequence leakage CSV")
    status_by_name = index_by(status_rows, "mutant_name", "status CSV")
    leakage_by_name = index_by(leakage_rows, "candidate_id", "leakage CSV")

    if len(panel_rows) != 36:
        raise SystemExit(f"expected 36 panel rows, found {len(panel_rows)} in {panel_csv}")

    detail_rows: list[dict[str, str]] = []
    buckets: dict[tuple[str, str], dict[str, object]] = defaultdict(empty_bucket)
    review_candidates: list[dict[str, str]] = []

    for item in panel_rows:
        name = item["mutant_name"]
        if name not in status_by_name:
            raise SystemExit(f"missing status row for {name} in {status_csv}")
        if name not in leakage_by_name:
            raise SystemExit(f"missing leakage row for {name} in {leakage_csv}")
        consensus_csv = find_consensus_csv(item, status_by_name[name], panel_root)
        consensus_rows = read_csv(consensus_csv, f"consensus CSV for {name}")
        counts = Counter(row.get("consensus_class", "") for row in consensus_rows)
        leakage = leakage_by_name[name]
        row = {
            "panel_order": item["panel_order"],
            "mutant_name": name,
            "base_name": base_name(item),
            "family": item.get("family", ""),
            "mutation_class": item.get("mutation_class", ""),
            "mutations_1based": item.get("mutations_1based", ""),
            "changed_cdr": item.get("changed_cdr", ""),
            "leakage_label": leakage.get("leakage_label", ""),
            "case_level_call": case_level_call(counts),
            "consensus_rows": str(sum(counts.values())),
            "consensus_csv": str(consensus_csv),
        }
        for key in CLASS_ORDER:
            row[key] = str(counts[key])
        row["OTHER_CONSENSUS_CLASS"] = str(sum(value for key, value in counts.items() if key not in CLASS_ORDER))
        detail_rows.append(row)

        for stratification, stratum in [
            ("family", row["family"]),
            ("mutation_class", row["mutation_class"]),
            ("leakage_label", row["leakage_label"]),
            ("base_name", row["base_name"]),
        ]:
            add_to_bucket(buckets[(stratification, stratum)], counts)

        if is_disruptive_alanine(item) and (counts["CONSENSUS_BLOCKER_LIKE_A"] or counts["SINGLE_BASELINE_BLOCKER_RECHECK"]):
            review_candidates.append(row)

    summary_rows: list[dict[str, str]] = []
    for (stratification, stratum), bucket in sorted(buckets.items()):
        out = {"stratification": stratification, "stratum": stratum}
        out.update({field: str(bucket[field]) for field in SUMMARY_FIELDS if field not in {"stratification", "stratum"}})
        summary_rows.append(out)
    return detail_rows, summary_rows, review_candidates


def write_summary_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def class_text(row: dict[str, str]) -> str:
    parts = [f"{key}={row[key]}" for key in CLASS_ORDER]
    if row.get("OTHER_CONSENSUS_CLASS") not in {"", "0"}:
        parts.append(f"OTHER={row['OTHER_CONSENSUS_CLASS']}")
    return "; ".join(parts)


def write_md(path: Path, detail_rows: list[dict[str, str]], summary_rows: list[dict[str, str]], review_candidates: list[dict[str, str]], out_csv: Path) -> None:
    aggregate = Counter()
    case_calls = Counter(row["case_level_call"] for row in detail_rows)
    for row in detail_rows:
        aggregate["consensus_rows"] += int(row["consensus_rows"])
        for key in CLASS_ORDER + ["OTHER_CONSENSUS_CLASS"]:
            aggregate[key] += int(row[key])

    lines = [
        "# Mutant Panel Result Stratification",
        "",
        "Updated: 2026-07-08",
        "",
        "## Bottom line",
        "",
        f"- Panel records summarized: {len(detail_rows)}",
        f"- Consensus rows summarized: {aggregate['consensus_rows']}",
        f"- Aggregate classes: A/A={aggregate['CONSENSUS_BLOCKER_LIKE_A']}; single-A={aggregate['SINGLE_BASELINE_BLOCKER_RECHECK']}; B={aggregate['BLOCKER_PLAUSIBLE_B']}; E={aggregate['EVIDENCE_INFERENCE_ONLY_E']}; other={aggregate['OTHER_CONSENSUS_CLASS']}",
        f"- Case-level calls: {'; '.join(f'{key}={value}' for key, value in sorted(case_calls.items()))}",
        f"- Manual-review candidates from CDR3-disruptive/alanine rows retaining A/A or single-A evidence: {len(review_candidates)}",
        f"- Machine-readable stratification CSV: `{out_csv.name}`",
        "",
        "## Stratification summaries",
        "",
    ]

    for stratification in ["family", "mutation_class", "leakage_label", "base_name"]:
        lines.extend(
            [
                f"### By {stratification}",
                "",
                "| stratum | panel records | consensus rows | A/A | single-A | B | E | other |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in [r for r in summary_rows if r["stratification"] == stratification]:
            lines.append(
                f"| {row['stratum']} | {row['panel_records']} | {row['consensus_rows']} | "
                f"{row['CONSENSUS_BLOCKER_LIKE_A']} | {row['SINGLE_BASELINE_BLOCKER_RECHECK']} | "
                f"{row['BLOCKER_PLAUSIBLE_B']} | {row['EVIDENCE_INFERENCE_ONLY_E']} | {row['OTHER_CONSENSUS_CLASS']} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Manual-review candidates",
            "",
            "These rows are CDR3 disruptive/alanine mutants but still contain A/A or single-baseline A consensus support, so they should be inspected before using the mutation panel as a fragility/negative-control readout.",
            "",
            "| order | mutant | base | family | mutation class | mutation | leakage | case call | A/A | single-A | B | E |",
            "| ---: | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in review_candidates:
        lines.append(
            f"| {row['panel_order']} | {row['mutant_name']} | {row['base_name']} | {row['family']} | "
            f"{row['mutation_class']} | {row['mutations_1based']} | {row['leakage_label']} | {row['case_level_call']} | "
            f"{row['CONSENSUS_BLOCKER_LIKE_A']} | {row['SINGLE_BASELINE_BLOCKER_RECHECK']} | "
            f"{row['BLOCKER_PLAUSIBLE_B']} | {row['EVIDENCE_INFERENCE_ONLY_E']} |"
        )
    if not review_candidates:
        lines.append("| - | none | - | - | - | - | - | - | 0 | 0 | 0 | 0 |")

    lines.extend(
        [
            "",
            "## Per-panel record summary",
            "",
            "| order | mutant | base | family | mutation class | leakage | case call | class counts | consensus CSV |",
            "| ---: | --- | --- | ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for row in detail_rows:
        lines.append(
            f"| {row['panel_order']} | {row['mutant_name']} | {row['base_name']} | {row['family']} | "
            f"{row['mutation_class']} | {row['leakage_label']} | {row['case_level_call']} | {class_text(row)} | `{row['consensus_csv']}` |"
        )

    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "- This report stratifies docking/postprocess labels only; it is not experimental evidence of PVRIG-PVRL2 blocking.",
            "- Exact/near known positives remain leakage or perturbation controls unless separately approved for candidate ranking.",
            "- Single-baseline A rows require manual pose review/redock before promotion.",
            "",
            "## Reproducibility",
            "",
            "```bash",
            "python docking/success_case_validation/summarize_mutant_panel_results.py",
            "```",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    panel_root = args.panel_root.resolve()
    panel_csv = args.panel_csv or panel_root / "mutant_panel.csv"
    status_csv = args.status_csv or panel_root / "mutant_panel_status.csv"
    leakage_csv = args.leakage_csv or panel_root / "mutant_panel_sequence_leakage.csv"
    out_md = args.out_md or panel_root / "MUTANT_PANEL_RESULT_STRATIFICATION.md"
    out_csv = args.out_csv or panel_root / "mutant_panel_result_stratification_summary.csv"

    detail_rows, summary_rows, review_candidates = build_analysis(panel_root, panel_csv, status_csv, leakage_csv)
    write_summary_csv(out_csv, summary_rows)
    write_md(out_md, detail_rows, summary_rows, review_candidates, out_csv)

    aggregate = Counter()
    for row in detail_rows:
        for key in CLASS_ORDER:
            aggregate[key] += int(row[key])
    print("OK mutant panel results stratified")
    print(f"panel_records={len(detail_rows)}")
    print(f"consensus_rows={sum(int(row['consensus_rows']) for row in detail_rows)}")
    for key in CLASS_ORDER:
        print(f"{key}={aggregate[key]}")
    print(f"manual_review_candidates={len(review_candidates)}")
    print(f"summary_csv={out_csv}")
    print(f"summary_md={out_md}")


if __name__ == "__main__":
    main()
