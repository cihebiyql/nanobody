#!/usr/bin/env python3
"""Validate Phase 2 V2.1 expanded800 training delivery artifacts."""
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


def passfail(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--out",
        default="experiments/phase2_5080_v1/audits/PHASE2_V2_1_FINAL_VALIDATION.md",
    )
    parser.add_argument(
        "--json-out",
        default="experiments/phase2_5080_v1/audits/phase2_v2_1_final_validation.json",
    )
    args = parser.parse_args()

    root = Path(args.root)
    base = root / "experiments/phase2_5080_v1"
    paths = {
        "env": base / "audits/environment_audit.md",
        "contact_jsonl": base / "prepared/structure_contact_maps_v2_expanded800.jsonl",
        "contact_summary_csv": base / "prepared/structure_contact_maps_v2_expanded800_summary.csv",
        "contact_summary_json": base / "audits/structure_contact_maps_v2_expanded800_summary.json",
        "contact_audit": base / "audits/structure_contact_maps_v2_expanded800_audit.md",
        "checkpoint": base / "checkpoints/phase2_v2_1_expanded800_best_checkpoint.pt",
        "run_checkpoint": base / "runs/phase2_v2_1_expanded800_20260709_seed31/best_checkpoint.pt",
        "metrics": base / "runs/phase2_v2_1_expanded800_20260709_seed31/test_metrics.json",
        "metrics_bundle": base / "reports/phase2_v2_1_expanded800_metrics.json",
        "comparison": base / "reports/phase2_v2_1_expanded800_comparison.json",
        "report": base / "reports/phase2_v2_1_expanded800_eval.md",
        "pvrig_predictions": base / "predictions/pvrig_top_candidates_phase2_v2_1_expanded800.csv",
        "train_log": base / "logs/phase2_v2_1_expanded800_20260709_seed31.log",
        "script": base / "src/train_phase2_v2.py",
        "builder": base / "src/build_structure_contact_maps_v2.py",
        "completion_audit": base / "audits/PHASE2_V2_1_EXPANDED800_AUDIT.md",
    }
    for path in paths.values():
        require(path)

    env_text = paths["env"].read_text(encoding="utf-8")
    metrics = json.loads(paths["metrics"].read_text(encoding="utf-8"))
    comparison = json.loads(paths["comparison"].read_text(encoding="utf-8"))
    summary_json = json.loads(paths["contact_summary_json"].read_text(encoding="utf-8"))
    summary_csv = pd.read_csv(paths["contact_summary_csv"])
    pvrig = pd.read_csv(paths["pvrig_predictions"])
    audit_text = paths["completion_audit"].read_text(encoding="utf-8")
    report_text = paths["report"].read_text(encoding="utf-8")

    contact_auprc = metric(metrics, "contact_test", "contact_auprc")
    contact_auroc = metric(metrics, "contact_test", "contact_auroc")
    contact_random = metric(metrics, "contact_test", "contact_positive_rate")
    paratope_auprc = metric(metrics, "site_test", "paratope_auprc")
    epitope_auprc = metric(metrics, "site_test", "epitope_auprc")
    pair_auroc = metric(metrics, "pair_test", "pair_auroc")
    pair_auprc = metric(metrics, "pair_test", "pair_auprc")
    v1_paratope = metric(comparison, "metrics", "v1_site_paratope_auprc")
    v1_epitope = metric(comparison, "metrics", "v1_site_epitope_auprc")

    checks: list[tuple[str, bool, str]] = []
    checks.append((
        "cuda_5080_environment_recorded",
        "NVIDIA GeForce RTX 5080" in env_text and '"cuda_available": true' in env_text,
        "environment_audit.md records RTX 5080 CUDA availability",
    ))
    checks.append((
        "expanded800_contact_dataset_present",
        int(summary_json.get("input_structures_sampled", 0)) >= 800
        and int(summary_json.get("records", 0)) >= 2700
        and int(summary_json.get("positive_pairs", 0)) > 0
        and int(summary_json.get("negative_pairs", 0)) > 0,
        f"structures={summary_json.get('input_structures_sampled')} records={summary_json.get('records')} pos={summary_json.get('positive_pairs')} neg={summary_json.get('negative_pairs')}",
    ))
    checks.append((
        "contact_summary_csv_matches_json",
        len(summary_csv) == int(summary_json.get("records", -1))
        and int(summary_csv["positive_pairs"].sum()) == int(summary_json.get("positive_pairs", -2))
        and int(summary_csv["negative_pairs"].sum()) == int(summary_json.get("negative_pairs", -3)),
        f"csv_records={len(summary_csv)} csv_pos={int(summary_csv['positive_pairs'].sum())} csv_neg={int(summary_csv['negative_pairs'].sum())}",
    ))
    checks.append((
        "train_val_test_contact_split_present",
        set(summary_json.get("split_counts", {}).keys()) == {"train", "val", "test"}
        and int(summary_json["split_counts"].get("test", 0)) >= 300,
        json.dumps(summary_json.get("split_counts", {}), ensure_ascii=False),
    ))
    checks.append((
        "training_outputs_present",
        paths["checkpoint"].stat().st_size > 1_000_000 and paths["run_checkpoint"].stat().st_size > 1_000_000,
        f"checkpoint_mb={paths['checkpoint'].stat().st_size / 1_000_000:.1f}",
    ))
    checks.append((
        "contact_model_above_random",
        contact_auprc > contact_random and contact_auroc > 0.5,
        f"contact_auroc={contact_auroc:.4f} contact_auprc={contact_auprc:.4f} random={contact_random:.4f}",
    ))
    checks.append((
        "site_heads_improved_over_v1",
        paratope_auprc > v1_paratope and epitope_auprc > v1_epitope,
        f"paratope {v1_paratope:.4f}->{paratope_auprc:.4f}; epitope {v1_epitope:.4f}->{epitope_auprc:.4f}",
    ))
    checks.append((
        "pair_metrics_present_with_boundary",
        pair_auroc > 0 and pair_auprc > 0 and "pair head remains weak" in audit_text,
        f"pair_auroc={pair_auroc:.4f} pair_auprc={pair_auprc:.4f}",
    ))
    checks.append((
        "pvrig_predictions_clean",
        len(pvrig) == 50
        and "leakage_label" in pvrig.columns
        and pvrig["leakage_label"].astype(str).eq("NO_KNOWN_POSITIVE_LEAKAGE").all(),
        f"rows={len(pvrig)} leakage={pvrig['leakage_label'].value_counts().to_dict() if 'leakage_label' in pvrig else 'missing'}",
    ))
    checks.append((
        "reports_state_delivery_boundary",
        "does not prove experimental binding" in audit_text
        and (
            "real heavy-atom contact-map" in report_text
            or "真实 heavy-atom contact-map" in report_text
        ),
        "audit/report preserve computational-only boundary",
    ))
    checks.append((
        "comparison_records_expansion",
        metric(comparison, "dataset_expansion", "record_multiplier") >= 7.0,
        f"record_multiplier={metric(comparison, 'dataset_expansion', 'record_multiplier'):.2f}",
    ))

    warnings = []
    if pair_auroc < 0.60:
        warnings.append(f"pair head remains weak: AUROC={pair_auroc:.4f}, AUPRC={pair_auprc:.4f}")
    if contact_auprc < metric(comparison, "metrics", "v2_contact_auprc"):
        warnings.append(
            "contact AUPRC is lower than small V2 but uses a much larger test set: "
            f"{contact_auprc:.4f} vs {metric(comparison, 'metrics', 'v2_contact_auprc'):.4f}"
        )

    failed = [name for name, ok, _ in checks if not ok]
    status = "PASS" if not failed else "FAIL"
    result = {
        "status": status,
        "failed_checks": failed,
        "warnings": warnings,
        "summary": {
            "records": int(summary_json["records"]),
            "positive_pairs": int(summary_json["positive_pairs"]),
            "negative_pairs": int(summary_json["negative_pairs"]),
            "contact_auroc": contact_auroc,
            "contact_auprc": contact_auprc,
            "contact_positive_rate": contact_random,
            "paratope_auprc": paratope_auprc,
            "epitope_auprc": epitope_auprc,
            "pair_auroc": pair_auroc,
            "pair_auprc": pair_auprc,
            "pvrig_prediction_rows": int(len(pvrig)),
        },
        "checks": [
            {"name": name, "passed": bool(ok), "evidence": evidence}
            for name, ok, evidence in checks
        ],
    }

    out_json = Path(args.json_out)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Phase 2 V2.1 Final Validation",
        "",
        "Updated: 2026-07-09",
        "",
        f"Verdict: {status}",
        "",
        "## Summary",
        "",
        f"- Expanded contact records: {summary_json['records']}",
        f"- Positive contact pairs <=4.5 A: {summary_json['positive_pairs']}",
        f"- Negative contact pairs >=8.0 A: {summary_json['negative_pairs']}",
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
        safe_evidence = str(evidence).replace("\n", " ").replace("|", "/")
        lines.append(f"| {name} | {passfail(ok)} | `{safe_evidence[:900]}` |")
    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None")
    lines.extend([
        "",
        "## Boundary",
        "",
        "This validates V2.1 as a completed computational training/evaluation package. It does not claim experimental binding, Kd, IC50, wet-lab efficacy, or clinical effect. Pair-level classification remains the main model bottleneck.",
        "",
    ])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
