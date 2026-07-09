#!/usr/bin/env python3
"""Run threshold-sensitivity checks on the completed patent VHH calibration batch."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from summarize_multibaseline_judgment import consensus_for


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BATCH_ROOT = ROOT / "docking" / "calibration" / "patent_success_validation"
DEFAULT_EXPECTED = {
    "CONSENSUS_BLOCKER_LIKE_A": 3,
    "SINGLE_BASELINE_BLOCKER_RECHECK": 36,
    "BLOCKER_PLAUSIBLE_B": 57,
    "EVIDENCE_INFERENCE_ONLY_E": 13,
}


@dataclass(frozen=True)
class Thresholds:
    hotspot_min: float
    total_min: float
    cdr3_min: float
    cdr3_fraction_min: float
    binder_total_max: float

    @property
    def label(self) -> str:
        return (
            f"h{self.hotspot_min:g}_t{self.total_min:g}_"
            f"c{self.cdr3_min:g}_f{self.cdr3_fraction_min:g}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, default=DEFAULT_BATCH_ROOT)
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
        help="Do not fail if the default threshold aggregate no longer matches the locked calibration counts.",
    )
    return parser.parse_args()


def parse_grid(text: str) -> list[float]:
    values = [float(item.strip()) for item in text.split(",") if item.strip()]
    if not values:
        raise SystemExit(f"empty grid: {text!r}")
    return values


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def to_float(value: str | None, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def classify_metric(row: dict[str, str], thresholds: Thresholds) -> str:
    hotspot = to_float(row.get("hotspot_overlap_count"))
    total = to_float(row.get("total_vhh_pvrl2_residue_pair_occlusion"))
    cdr3 = to_float(row.get("cdr3_pvrl2_residue_pair_occlusion"))
    fraction = to_float(row.get("cdr3_occlusion_fraction"))

    pass_hotspot = hotspot >= thresholds.hotspot_min
    pass_total = total >= thresholds.total_min
    pass_cdr3 = cdr3 >= thresholds.cdr3_min
    pass_fraction = fraction >= thresholds.cdr3_fraction_min

    if pass_hotspot and pass_total and pass_cdr3 and pass_fraction:
        return "BLOCKER_LIKE_A"
    if pass_hotspot and total < thresholds.binder_total_max:
        return "BINDER_LIKE_C"
    if total >= thresholds.total_min and (pass_hotspot or cdr3 >= 50):
        return "BLOCKER_PLAUSIBLE_B"
    if total >= 300 and hotspot >= 10 and cdr3 >= 50:
        return "BLOCKER_PLAUSIBLE_B"
    return "EVIDENCE_INFERENCE_ONLY_E"


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


def read_case_baselines(workdir: Path, name: str) -> dict[str, list[dict[str, str]]]:
    reports = workdir / "reports"
    paths = {
        "8x6b": reports / f"{name}_8x6b_blocker_classification.csv",
        "9e6y": reports / f"{name}_9e6y_blocker_classification.csv",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise SystemExit("missing baseline classification CSVs: " + "; ".join(missing))
    return {label: read_csv(path) for label, path in paths.items()}


def iter_thresholds(args: argparse.Namespace) -> Iterable[Thresholds]:
    for hotspot in parse_grid(args.hotspot_grid):
        for total in parse_grid(args.total_grid):
            for cdr3 in parse_grid(args.cdr3_grid):
                for fraction in parse_grid(args.fraction_grid):
                    yield Thresholds(hotspot, total, cdr3, fraction, args.binder_total_max)


def summarize_for_threshold(
    manifest_rows: list[dict[str, str]],
    case_inputs: dict[str, dict[str, list[dict[str, str]]]],
    thresholds: Thresholds,
    default_case_calls: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    aggregate = Counter()
    baseline_counts = Counter()
    case_calls: dict[str, str] = {}
    case_with_any_a = 0
    case_with_consensus_a = 0
    case_with_only_e = 0
    per_family: dict[str, Counter[str]] = defaultdict(Counter)

    for item in manifest_rows:
        name = item["calibration_name"]
        molecule = item["molecule_name"]
        family = item["family"]
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
            consensus_class, _ = consensus_for(classes, len(classes))
            case_counter[consensus_class] += 1
            aggregate[consensus_class] += 1
        call = case_level_call(case_counter)
        case_calls[molecule] = call
        per_family[family][call] += 1
        if case_counter["CONSENSUS_BLOCKER_LIKE_A"]:
            case_with_consensus_a += 1
        if case_counter["CONSENSUS_BLOCKER_LIKE_A"] or case_counter["SINGLE_BASELINE_BLOCKER_RECHECK"]:
            case_with_any_a += 1
        if call == "EVIDENCE_INFERENCE_ONLY_E_ONLY":
            case_with_only_e += 1

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
        "cases_with_consensus_a": str(case_with_consensus_a),
        "cases_with_any_a_signal": str(case_with_any_a),
        "cases_evidence_only": str(case_with_only_e),
        "changed_case_calls_vs_default": str(changed_cases),
        "families_with_consensus_a": ";".join(
            f"{family}:{counts['HAS_CONSENSUS_BLOCKER_LIKE_A']}" for family, counts in sorted(per_family.items())
        ),
        "baseline_class_counts": ";".join(f"{key}={value}" for key, value in sorted(baseline_counts.items())),
    }
    return row, case_calls


def write_md(path: Path, rows: list[dict[str, str]], default_row: dict[str, str]) -> None:
    default_total = int(default_row["total_consensus_rows"])
    exact_default = ", ".join(
        [
            f"A/A={default_row['consensus_blocker_like_a']}",
            f"single-A={default_row['single_baseline_blocker_recheck']}",
            f"B={default_row['blocker_plausible_b']}",
            f"E={default_row['evidence_inference_only_e']}",
        ]
    )
    stable_rows = [row for row in rows if row["changed_case_calls_vs_default"] == "0"]
    conservative = sorted(rows, key=lambda r: (int(r["consensus_blocker_like_a"]), int(r["single_baseline_blocker_recheck"])))[:5]
    permissive = sorted(rows, key=lambda r: (-int(r["consensus_blocker_like_a"]), -int(r["single_baseline_blocker_recheck"])))[:5]
    lines = [
        "# Threshold Sensitivity Report",
        "",
        "## Bottom line",
        "",
        f"- Default threshold row summarizes {default_total} consensus pose rows: {exact_default}.",
        f"- Grid rows tested: {len(rows)}.",
        f"- Case-level calls unchanged vs default in {len(stable_rows)}/{len(rows)} parameter settings.",
        "- This is a postprocessing robustness check on completed docking outputs; it does not replace fresh docking for new mutants.",
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
        "| threshold | A/A | single-A | plausible-B | evidence-E | changed cases |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in permissive:
        lines.append(
            f"| {row['threshold_label']} | {row['consensus_blocker_like_a']} | "
            f"{row['single_baseline_blocker_recheck']} | {row['blocker_plausible_b']} | "
            f"{row['evidence_inference_only_e']} | {row['changed_case_calls_vs_default']} |"
        )
    lines.extend(
        [
            "",
            "## Most conservative settings by A signal",
            "",
            "| threshold | A/A | single-A | plausible-B | evidence-E | changed cases |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in conservative:
        lines.append(
            f"| {row['threshold_label']} | {row['consensus_blocker_like_a']} | "
            f"{row['single_baseline_blocker_recheck']} | {row['blocker_plausible_b']} | "
            f"{row['evidence_inference_only_e']} | {row['changed_case_calls_vs_default']} |"
        )
    lines.extend(
        [
            "",
            "## Use in production batching",
            "",
            "- Keep the default HR-151 calibrated gate for primary ranking; use the grid only as a stability audit.",
            "- Promote candidates only when dual-baseline support or repeated single-baseline A signal survives leakage and manual pose review.",
            "- Treat threshold-sensitive A calls as re-dock/re-score items, not as final blockers.",
            "- Re-run this script after any scoring, CDR-range, or consensus-rule change.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    batch_root = args.batch_root.resolve()
    manifest_path = batch_root / "batch_manifest.csv"
    if not manifest_path.exists():
        raise SystemExit(f"missing batch manifest: {manifest_path}")
    manifest_rows = read_csv(manifest_path)
    case_inputs = {
        row["calibration_name"]: read_case_baselines(Path(row["workdir"]), row["calibration_name"])
        for row in manifest_rows
    }
    default_threshold = Thresholds(14, 500, 100, 0.15, args.binder_total_max)
    default_row, default_calls = summarize_for_threshold(manifest_rows, case_inputs, default_threshold)
    if not args.no_default_assert:
        observed = {
            "CONSENSUS_BLOCKER_LIKE_A": int(default_row["consensus_blocker_like_a"]),
            "SINGLE_BASELINE_BLOCKER_RECHECK": int(default_row["single_baseline_blocker_recheck"]),
            "BLOCKER_PLAUSIBLE_B": int(default_row["blocker_plausible_b"]),
            "EVIDENCE_INFERENCE_ONLY_E": int(default_row["evidence_inference_only_e"]),
        }
        if observed != DEFAULT_EXPECTED:
            raise SystemExit(f"default aggregate drift: observed={observed} expected={DEFAULT_EXPECTED}")

    rows: list[dict[str, str]] = []
    for thresholds in iter_thresholds(args):
        row, _ = summarize_for_threshold(manifest_rows, case_inputs, thresholds, default_calls)
        rows.append(row)
    rows.sort(key=lambda r: (float(r["hotspot_min"]), float(r["total_min"]), float(r["cdr3_min"]), float(r["cdr3_fraction_min"])))
    out_csv = args.out_csv or batch_root / "threshold_sensitivity_summary.csv"
    out_md = args.out_md or batch_root / "THRESHOLD_SENSITIVITY_REPORT.md"
    fields = list(rows[0])
    write_csv(out_csv, rows, fields)
    write_md(out_md, rows, default_row)
    print("OK threshold sensitivity analyzed")
    print(f"grid_rows={len(rows)}")
    print(f"default_counts=A/A:{default_row['consensus_blocker_like_a']} single-A:{default_row['single_baseline_blocker_recheck']} B:{default_row['blocker_plausible_b']} E:{default_row['evidence_inference_only_e']}")
    print(f"stable_case_call_rows={sum(1 for row in rows if row['changed_case_calls_vs_default'] == '0')}")
    print(f"out_csv={out_csv}")
    print(f"out_md={out_md}")


if __name__ == "__main__":
    main()
