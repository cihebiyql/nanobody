#!/usr/bin/env python3
"""Validate Phase 2 V2.2 full2277 training delivery artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def require(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        raise SystemExit(f"Missing or empty: {path}")


def metric(d: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    cur: Any = d
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    try:
        return float(cur)
    except (TypeError, ValueError):
        return default


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--out",
        default="experiments/phase2_5080_v1/audits/PHASE2_V2_2_FULL2277_FINAL_VALIDATION.md",
    )
    parser.add_argument(
        "--json-out",
        default="experiments/phase2_5080_v1/audits/phase2_v2_2_full2277_final_validation.json",
    )
    args = parser.parse_args()

    root = Path(args.root)
    base = root / "experiments/phase2_5080_v1"
    run = base / "runs/phase2_v2_2_full2277_20260709_seed41"
    paths = {
        "env": base / "audits/environment_audit.md",
        "contact_jsonl": base / "prepared/structure_contact_maps_v2_full2277.jsonl",
        "contact_summary_csv": base / "prepared/structure_contact_maps_v2_full2277_summary.csv",
        "contact_summary_json": base / "audits/structure_contact_maps_v2_full2277_summary.json",
        "contact_audit": base / "audits/structure_contact_maps_v2_full2277_audit.md",
        "checkpoint": base / "checkpoints/phase2_v2_2_full2277_best_checkpoint.pt",
        "run_checkpoint": run / "best_checkpoint.pt",
        "metrics": run / "test_metrics.json",
        "history": run / "metrics_history.json",
        "metrics_bundle": base / "reports/phase2_v2_2_full2277_metrics.json",
        "comparison": base / "reports/phase2_v2_2_full2277_comparison.json",
        "report": base / "reports/phase2_v2_2_full2277_eval.md",
        "pvrig_predictions": base / "predictions/pvrig_top_candidates_phase2_v2_2_full2277.csv",
        "train_log": base / "logs/phase2_v2_2_full2277_20260709_seed41.log",
        "script": base / "src/train_phase2_v2.py",
        "builder": base / "src/build_structure_contact_maps_v2.py",
    }
    for path in paths.values():
        if path == paths["comparison"]:
            continue
        require(path)

    env_text = paths["env"].read_text(encoding="utf-8")
    metrics = json.loads(paths["metrics"].read_text(encoding="utf-8"))
    v21_metrics = json.loads((base / "runs/phase2_v2_1_expanded800_20260709_seed31/test_metrics.json").read_text(encoding="utf-8"))
    summary = json.loads(paths["contact_summary_json"].read_text(encoding="utf-8"))
    v21_summary = json.loads((base / "audits/structure_contact_maps_v2_expanded800_summary.json").read_text(encoding="utf-8"))
    summary_csv = pd.read_csv(paths["contact_summary_csv"])
    pvrig = pd.read_csv(paths["pvrig_predictions"])
    report_text = paths["report"].read_text(encoding="utf-8")

    comparison = {
        "dataset_expansion": {
            "v21_records": int(v21_summary["records"]),
            "v22_records": int(summary["records"]),
            "v21_positive_pairs": int(v21_summary["positive_pairs"]),
            "v22_positive_pairs": int(summary["positive_pairs"]),
            "v21_negative_pairs": int(v21_summary["negative_pairs"]),
            "v22_negative_pairs": int(summary["negative_pairs"]),
            "record_multiplier": int(summary["records"]) / max(int(v21_summary["records"]), 1),
            "positive_pair_multiplier": int(summary["positive_pairs"]) / max(int(v21_summary["positive_pairs"]), 1),
        },
        "metrics": {
            "v21_contact_auroc": metric(v21_metrics, "contact_test", "contact_auroc"),
            "v22_contact_auroc": metric(metrics, "contact_test", "contact_auroc"),
            "v21_contact_auprc": metric(v21_metrics, "contact_test", "contact_auprc"),
            "v22_contact_auprc": metric(metrics, "contact_test", "contact_auprc"),
            "v21_contact_test_records": metric(v21_metrics, "dataset_sizes", "contact_test"),
            "v22_contact_test_records": metric(metrics, "dataset_sizes", "contact_test"),
            "v21_paratope_auprc": metric(v21_metrics, "site_test", "paratope_auprc"),
            "v22_paratope_auprc": metric(metrics, "site_test", "paratope_auprc"),
            "v21_epitope_auprc": metric(v21_metrics, "site_test", "epitope_auprc"),
            "v22_epitope_auprc": metric(metrics, "site_test", "epitope_auprc"),
            "v21_pair_auroc": metric(v21_metrics, "pair_test", "pair_auroc"),
            "v22_pair_auroc": metric(metrics, "pair_test", "pair_auroc"),
            "v21_pair_auprc": metric(v21_metrics, "pair_test", "pair_auprc"),
            "v22_pair_auprc": metric(metrics, "pair_test", "pair_auprc"),
        },
        "interpretation": "V2.2 uses the full2277 contact-map dataset and improves contact, site, and pair metrics over V2.1; pair-level classification is improved but still not sufficient as standalone blocker proof.",
    }
    paths["comparison"].write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    contact_auprc = metric(metrics, "contact_test", "contact_auprc")
    contact_auroc = metric(metrics, "contact_test", "contact_auroc")
    contact_random = metric(metrics, "contact_test", "contact_positive_rate")
    paratope_auprc = metric(metrics, "site_test", "paratope_auprc")
    epitope_auprc = metric(metrics, "site_test", "epitope_auprc")
    pair_auroc = metric(metrics, "pair_test", "pair_auroc")
    pair_auprc = metric(metrics, "pair_test", "pair_auprc")

    checks: list[tuple[str, bool, str]] = []
    checks.append(("cuda_5080_environment_recorded", "NVIDIA GeForce RTX 5080" in env_text and '"cuda_available": true' in env_text, "environment audit records RTX 5080 CUDA"))
    checks.append(("full2277_contact_dataset_present", int(summary["records"]) >= 8000 and int(summary["positive_pairs"]) > 800000 and int(summary["negative_pairs"]) > 3000000, f"records={summary['records']} pos={summary['positive_pairs']} neg={summary['negative_pairs']}"))
    checks.append(("contact_summary_csv_matches_json", len(summary_csv) == int(summary["records"]) and int(summary_csv["positive_pairs"].sum()) == int(summary["positive_pairs"]) and int(summary_csv["negative_pairs"].sum()) == int(summary["negative_pairs"]), f"csv_records={len(summary_csv)}"))
    checks.append(("train_val_test_contact_split_present", set(summary["split_counts"].keys()) == {"train", "val", "test"} and int(summary["split_counts"]["test"]) >= 800, json.dumps(summary["split_counts"], ensure_ascii=False)))
    checks.append(("training_outputs_present", paths["checkpoint"].stat().st_size > 1_000_000 and paths["run_checkpoint"].stat().st_size > 1_000_000, f"checkpoint_mb={paths['checkpoint'].stat().st_size / 1_000_000:.1f}"))
    checks.append(("contact_model_above_random", contact_auprc > contact_random and contact_auroc > 0.5, f"contact_auroc={contact_auroc:.4f} contact_auprc={contact_auprc:.4f} random={contact_random:.4f}"))
    checks.append(("improves_contact_over_v21", contact_auprc > metric(v21_metrics, "contact_test", "contact_auprc") and contact_auroc > metric(v21_metrics, "contact_test", "contact_auroc"), f"contact AUPRC {metric(v21_metrics, 'contact_test', 'contact_auprc'):.4f}->{contact_auprc:.4f}"))
    checks.append(("improves_site_over_v21", paratope_auprc > metric(v21_metrics, "site_test", "paratope_auprc") and epitope_auprc > metric(v21_metrics, "site_test", "epitope_auprc"), f"paratope {metric(v21_metrics, 'site_test', 'paratope_auprc'):.4f}->{paratope_auprc:.4f}; epitope {metric(v21_metrics, 'site_test', 'epitope_auprc'):.4f}->{epitope_auprc:.4f}"))
    checks.append(("improves_pair_over_v21", pair_auroc > metric(v21_metrics, "pair_test", "pair_auroc") and pair_auprc > metric(v21_metrics, "pair_test", "pair_auprc"), f"pair AUROC/AUPRC {metric(v21_metrics, 'pair_test', 'pair_auroc'):.4f}/{metric(v21_metrics, 'pair_test', 'pair_auprc'):.4f}->{pair_auroc:.4f}/{pair_auprc:.4f}"))
    checks.append(("pvrig_predictions_clean", len(pvrig) == 50 and pvrig["leakage_label"].astype(str).eq("NO_KNOWN_POSITIVE_LEAKAGE").all(), f"rows={len(pvrig)} leakage={pvrig['leakage_label'].value_counts().to_dict()}"))
    checks.append(("report_states_boundary", "真实 heavy-atom contact-map" in report_text and "不是最终 blocker 判定" in report_text, "report keeps computational-prior boundary"))

    warnings = []
    if pair_auroc < 0.60:
        warnings.append(f"pair head improved but remains below strong standalone threshold: AUROC={pair_auroc:.4f}, AUPRC={pair_auprc:.4f}")
    if contact_auprc <= contact_random:
        warnings.append("contact head does not beat random positive rate")

    failed = [name for name, ok, _ in checks if not ok]
    status = "PASS" if not failed else "FAIL"
    result = {
        "status": status,
        "failed_checks": failed,
        "warnings": warnings,
        "summary": {
            "records": int(summary["records"]),
            "positive_pairs": int(summary["positive_pairs"]),
            "negative_pairs": int(summary["negative_pairs"]),
            "contact_auroc": contact_auroc,
            "contact_auprc": contact_auprc,
            "contact_positive_rate": contact_random,
            "paratope_auprc": paratope_auprc,
            "epitope_auprc": epitope_auprc,
            "pair_auroc": pair_auroc,
            "pair_auprc": pair_auprc,
            "pvrig_prediction_rows": int(len(pvrig)),
        },
        "checks": [{"name": n, "passed": bool(ok), "evidence": e} for n, ok, e in checks],
    }

    Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Phase 2 V2.2 Full2277 Final Validation",
        "",
        "Updated: 2026-07-09",
        "",
        f"Verdict: {status}",
        "",
        "## Summary",
        "",
        f"- Full contact records: {summary['records']}",
        f"- Positive contact pairs <=4.5 A: {summary['positive_pairs']}",
        f"- Negative contact pairs >=8.0 A: {summary['negative_pairs']}",
        f"- Contact test AUROC/AUPRC: {contact_auroc:.4f} / {contact_auprc:.4f}",
        f"- Contact positive rate: {contact_random:.4f}",
        f"- Paratope AUPRC: {paratope_auprc:.4f}",
        f"- Epitope AUPRC: {epitope_auprc:.4f}",
        f"- Pair AUROC/AUPRC: {pair_auroc:.4f} / {pair_auprc:.4f}",
        f"- PVRIG prediction rows: {len(pvrig)}",
        "",
        "## Checks",
        "",
        "| Check | Status | Evidence |",
        "| --- | --- | --- |",
    ]
    for name, ok, evidence in checks:
        lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | `{str(evidence).replace(chr(10), ' ').replace('|', '/')[:900]}` |")
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {w}" for w in warnings] if warnings else ["- None"])
    lines.extend([
        "",
        "## Boundary",
        "",
        "This validates V2.2 as a completed computational training/evaluation package over the full2277 real-contact dataset. It supports candidate prioritization and next-round structure computation, but it does not claim experimental binding, Kd, IC50, wet-lab efficacy, clinical effect, or proven PVRIG-PVRL2 blocking.",
        "",
    ])
    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
