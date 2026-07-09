#!/usr/bin/env python3
"""Run threshold-sensitivity checks on the completed mutant/control panel."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from analyze_threshold_sensitivity import Thresholds, classify_metric, parse_grid
from summarize_multibaseline_judgment import consensus_for


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PANEL_ROOT = ROOT / "docking" / "calibration" / "mutant_validation_panel"
DEFAULT_EXPECTED = Counter(
    {
        "CONSENSUS_BLOCKER_LIKE_A": 8,
        "SINGLE_BASELINE_BLOCKER_RECHECK": 109,
        "BLOCKER_PLAUSIBLE_B": 210,
        "EVIDENCE_INFERENCE_ONLY_E": 30,
    }
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-root", type=Path, default=DEFAULT_PANEL_ROOT)
    parser.add_argument("--out-csv", type=Path)
    parser.add_argument("--out-md", type=Path)
    parser.add_argument("--hotspot-grid", default="12,14,16")
    parser.add_argument("--total-grid", default="400,500,600")
    parser.add_argument("--cdr3-grid", default="75,100,125")
    parser.add_argument("--fraction-grid", default="0.10,0.15,0.20")
    parser.add_argument("--binder-total-max", type=float, default=50.0)
    parser.add_argument(
        "--no-default-assert",
        action="store_true",
        help="Do not fail if the default threshold aggregate no longer matches the locked mutant-panel counts.",
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"missing CSV: {path}")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def iter_thresholds(args: argparse.Namespace) -> Iterable[Thresholds]:
    for hotspot in parse_grid(args.hotspot_grid):
        for total in parse_grid(args.total_grid):
            for cdr3 in parse_grid(args.cdr3_grid):
                for fraction in parse_grid(args.fraction_grid):
                    yield Thresholds(hotspot, total, cdr3, fraction, args.binder_total_max)


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


def is_disruptive_alanine(row: dict[str, str]) -> bool:
    mutation_class = row.get("mutation_class", "").lower()
    changed_cdr = row.get("changed_cdr", "").upper()
    mutations = row.get("mutations_1based", "").upper().replace(",", ";").split(";")
    return (
        "alanine" in mutation_class
        or "ala" in mutation_class
        or ("CDR3" in changed_cdr and any(token.endswith("A") for token in mutations))
    )


def read_panel_baselines(workdir: Path, name: str) -> dict[str, list[dict[str, str]]]:
    reports = workdir / "reports"
    paths = {
        "8x6b": reports / f"{name}_8x6b_blocker_classification.csv",
        "9e6y": reports / f"{name}_9e6y_blocker_classification.csv",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise SystemExit("missing mutant baseline classification CSVs: " + "; ".join(missing))
    return {label: read_csv(path) for label, path in paths.items()}


def summarize_for_threshold(
    panel_rows: list[dict[str, str]],
    case_inputs: dict[str, dict[str, list[dict[str, str]]]],
    thresholds: Thresholds,
    default_case_calls: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    aggregate = Counter()
    baseline_counts = Counter()
    case_calls: dict[str, str] = {}
    family_calls: dict[str, Counter[str]] = defaultdict(Counter)
    mutation_calls: dict[str, Counter[str]] = defaultdict(Counter)
    disruptive_any_a = 0
    disruptive_consensus_a = 0
    cases_any_a = 0
    cases_consensus_a = 0

    for item in panel_rows:
        name = item["mutant_name"]
        by_model: dict[str, list[str]] = defaultdict(list)
        for baseline, rows in case_inputs[name].items():
            for row in rows:
                model = row.get("model", "").strip()
                if not model:
                    continue
                cls = classify_metric(row, thresholds)
                by_model[model].append(cls)
                baseline_counts[f"{baseline}:{cls}"] += 1

        case_counter = Counter()
        for model, classes in sorted(by_model.items()):
            consensus_class, _next_step = consensus_for(classes, len(classes))
            case_counter[consensus_class] += 1
            aggregate[consensus_class] += 1

        call = case_level_call(case_counter)
        case_calls[name] = call
        family_calls[item["family"]][call] += 1
        mutation_calls[item["mutation_class"]][call] += 1

        has_consensus_a = bool(case_counter["CONSENSUS_BLOCKER_LIKE_A"])
        has_any_a = has_consensus_a or bool(case_counter["SINGLE_BASELINE_BLOCKER_RECHECK"])
        if has_consensus_a:
            cases_consensus_a += 1
        if has_any_a:
            cases_any_a += 1
        if is_disruptive_alanine(item) and has_consensus_a:
            disruptive_consensus_a += 1
        if is_disruptive_alanine(item) and has_any_a:
            disruptive_any_a += 1

    changed_cases = 0
    if default_case_calls is not None:
        changed_cases = sum(1 for key, value in case_calls.items() if default_case_calls.get(key) != value)

    row = {
        "threshold_label": thresholds.label,
        "hotspot_min": f"{thresholds.hotspot_min:g}",
        "total_min": f"{thresholds.total_min:g}",
        "cdr3_min": f"{thresholds.cdr3_min:g}",
        "cdr3_fraction_min": f"{thresholds.cdr3_fraction_min:g}",
        "binder_total_max": f"{thresholds.binder_total_max:g}",
        "total_consensus_rows": str(sum(aggregate.values())),
        "consensus_blocker_like_a": str(aggregate["CONSENSUS_BLOCKER_LIKE_A"]),
        "single_baseline_blocker_recheck": str(aggregate["SINGLE_BASELINE_BLOCKER_RECHECK"]),
        "blocker_plausible_b": str(aggregate["BLOCKER_PLAUSIBLE_B"]),
        "discordant_redock_required": str(aggregate["DISCORDANT_REDOCK_REQUIRED"]),
        "discordant_plausible_vs_binder_recheck": str(aggregate["DISCORDANT_PLAUSIBLE_VS_BINDER_RECHECK"]),
        "consensus_binder_like_c": str(aggregate["CONSENSUS_BINDER_LIKE_C"]),
        "evidence_inference_only_e": str(aggregate["EVIDENCE_INFERENCE_ONLY_E"]),
        "cases_with_consensus_a": str(cases_consensus_a),
        "cases_with_any_a_signal": str(cases_any_a),
        "disruptive_controls_with_consensus_a": str(disruptive_consensus_a),
        "disruptive_controls_with_any_a_signal": str(disruptive_any_a),
        "changed_case_calls_vs_default": str(changed_cases),
        "families_with_consensus_a": ";".join(
            f"{family}:{counts['HAS_CONSENSUS_BLOCKER_LIKE_A']}" for family, counts in sorted(family_calls.items())
        ),
        "mutation_classes_with_consensus_a": ";".join(
            f"{label}:{counts['HAS_CONSENSUS_BLOCKER_LIKE_A']}" for label, counts in sorted(mutation_calls.items())
        ),
        "baseline_class_counts": ";".join(f"{key}={value}" for key, value in sorted(baseline_counts.items())),
    }
    return row, case_calls


def write_md(path: Path, rows: list[dict[str, str]], default_row: dict[str, str]) -> None:
    stable_rows = [row for row in rows if row["changed_case_calls_vs_default"] == "0"]
    permissive = sorted(rows, key=lambda r: (-int(r["consensus_blocker_like_a"]), -int(r["single_baseline_blocker_recheck"])))[:5]
    conservative = sorted(rows, key=lambda r: (int(r["consensus_blocker_like_a"]), int(r["single_baseline_blocker_recheck"])))[:5]
    high_disruptive = sorted(
        rows,
        key=lambda r: (-int(r["disruptive_controls_with_consensus_a"]), -int(r["disruptive_controls_with_any_a_signal"])),
    )[:5]
    low_disruptive = sorted(
        rows,
        key=lambda r: (int(r["disruptive_controls_with_consensus_a"]), int(r["disruptive_controls_with_any_a_signal"])),
    )[:5]

    lines = [
        "# Mutant Panel Threshold Sensitivity Report",
        "",
        "Updated: 2026-07-08",
        "",
        "## Bottom line",
        "",
        f"- Default threshold row summarizes {default_row['total_consensus_rows']} consensus pose rows: "
        f"A/A={default_row['consensus_blocker_like_a']}, "
        f"single-A={default_row['single_baseline_blocker_recheck']}, "
        f"B={default_row['blocker_plausible_b']}, E={default_row['evidence_inference_only_e']}.",
        f"- Grid rows tested: {len(rows)}.",
        f"- Case-level calls unchanged vs default in {len(stable_rows)}/{len(rows)} parameter settings.",
        f"- Default retained-A disruptive/alanine controls: consensus-A={default_row['disruptive_controls_with_consensus_a']}, any-A={default_row['disruptive_controls_with_any_a_signal']}.",
        "- This is a postprocessing robustness check on completed mutant/control docking outputs; it does not make near-positive mutants into new designs.",
        "",
        "## Default gate",
        "",
        "- hotspot_overlap_count >= 14",
        "- total_vhh_pvrl2_residue_pair_occlusion >= 500",
        "- cdr3_pvrl2_residue_pair_occlusion >= 100",
        "- cdr3_occlusion_fraction >= 0.15",
        "- hotspot-only total occlusion < 50 remains binder-like/nonblocking.",
        "",
        "## Most permissive settings by A signal",
        "",
        "| threshold | A/A | single-A | B | E | changed cases | disruptive any-A |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in permissive:
        lines.append(
            f"| {row['threshold_label']} | {row['consensus_blocker_like_a']} | {row['single_baseline_blocker_recheck']} | "
            f"{row['blocker_plausible_b']} | {row['evidence_inference_only_e']} | {row['changed_case_calls_vs_default']} | "
            f"{row['disruptive_controls_with_any_a_signal']} |"
        )

    lines.extend(
        [
            "",
            "## Most conservative settings by A signal",
            "",
            "| threshold | A/A | single-A | B | E | changed cases | disruptive any-A |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in conservative:
        lines.append(
            f"| {row['threshold_label']} | {row['consensus_blocker_like_a']} | {row['single_baseline_blocker_recheck']} | "
            f"{row['blocker_plausible_b']} | {row['evidence_inference_only_e']} | {row['changed_case_calls_vs_default']} | "
            f"{row['disruptive_controls_with_any_a_signal']} |"
        )

    lines.extend(
        [
            "",
            "## Disruptive/alanine retained-A sensitivity",
            "",
            "High retained-A settings:",
            "",
            "| threshold | disruptive consensus-A | disruptive any-A | A/A | single-A |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in high_disruptive:
        lines.append(
            f"| {row['threshold_label']} | {row['disruptive_controls_with_consensus_a']} | "
            f"{row['disruptive_controls_with_any_a_signal']} | {row['consensus_blocker_like_a']} | "
            f"{row['single_baseline_blocker_recheck']} |"
        )
    lines.extend(
        [
            "",
            "Low retained-A settings:",
            "",
            "| threshold | disruptive consensus-A | disruptive any-A | A/A | single-A |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in low_disruptive:
        lines.append(
            f"| {row['threshold_label']} | {row['disruptive_controls_with_consensus_a']} | "
            f"{row['disruptive_controls_with_any_a_signal']} | {row['consensus_blocker_like_a']} | "
            f"{row['single_baseline_blocker_recheck']} |"
        )

    lines.extend(
        [
            "",
            "## Use in production batching",
            "",
            "- Use this report to decide which mutant/control A calls are threshold-sensitive and need redocking or pose inspection.",
            "- Do not promote exact/near known-positive mutant rows; they are leakage and robustness controls.",
            "- If a new candidate resembles the retained-A disruptive controls, require stricter manual pose review before prioritization.",
            "- Re-run after any scoring, CDR-range, consensus, or HADDOCK restraint change.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    panel_root = args.panel_root.resolve()
    panel_csv = panel_root / "mutant_panel.csv"
    panel_rows = read_csv(panel_csv)
    if len(panel_rows) != 36:
        raise SystemExit(f"expected 36 mutant panel rows, found {len(panel_rows)} in {panel_csv}")

    case_inputs = {
        row["mutant_name"]: read_panel_baselines(Path(row["workdir"]), row["mutant_name"])
        for row in panel_rows
    }
    default_threshold = Thresholds(14, 500, 100, 0.15, args.binder_total_max)
    default_row, default_case_calls = summarize_for_threshold(panel_rows, case_inputs, default_threshold)

    observed_default = Counter(
        {
            "CONSENSUS_BLOCKER_LIKE_A": int(default_row["consensus_blocker_like_a"]),
            "SINGLE_BASELINE_BLOCKER_RECHECK": int(default_row["single_baseline_blocker_recheck"]),
            "BLOCKER_PLAUSIBLE_B": int(default_row["blocker_plausible_b"]),
            "EVIDENCE_INFERENCE_ONLY_E": int(default_row["evidence_inference_only_e"]),
        }
    )
    if not args.no_default_assert and observed_default != DEFAULT_EXPECTED:
        raise SystemExit(f"default mutant threshold aggregate drift: {observed_default} != {DEFAULT_EXPECTED}")

    rows = []
    for thresholds in iter_thresholds(args):
        row, _case_calls = summarize_for_threshold(panel_rows, case_inputs, thresholds, default_case_calls)
        rows.append(row)

    out_csv = args.out_csv or panel_root / "mutant_panel_threshold_sensitivity_summary.csv"
    out_md = args.out_md or panel_root / "MUTANT_PANEL_THRESHOLD_SENSITIVITY_REPORT.md"
    fields = list(rows[0])
    write_csv(out_csv, rows, fields)
    write_md(out_md, rows, default_row)

    stable = sum(1 for row in rows if row["changed_case_calls_vs_default"] == "0")
    print("OK mutant panel threshold sensitivity analyzed")
    print(f"grid_rows={len(rows)}")
    print(
        "default_counts="
        f"A/A:{default_row['consensus_blocker_like_a']} "
        f"single-A:{default_row['single_baseline_blocker_recheck']} "
        f"B:{default_row['blocker_plausible_b']} "
        f"E:{default_row['evidence_inference_only_e']}"
    )
    print(f"stable_case_call_rows={stable}")
    print(f"default_disruptive_any_a={default_row['disruptive_controls_with_any_a_signal']}")
    print(f"out_csv={out_csv}")
    print(f"out_md={out_md}")


if __name__ == "__main__":
    main()
