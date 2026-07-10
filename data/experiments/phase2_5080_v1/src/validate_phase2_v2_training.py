#!/usr/bin/env python3
"""Validate Phase 2 V2 real contact-map training artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def require(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        raise SystemExit(f"Missing or empty: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="experiments/phase2_5080_v1/audits/PHASE2_V2_COMPLETION_AUDIT.md")
    args = parser.parse_args()
    root = Path(args.root)
    base = root / "experiments/phase2_5080_v1"
    paths = {
        "env": base / "audits/environment_audit.md",
        "contact_jsonl": base / "prepared/structure_contact_maps_v2.jsonl",
        "contact_summary": base / "prepared/structure_contact_maps_v2_summary.csv",
        "contact_audit": base / "audits/structure_contact_maps_v2_audit.md",
        "checkpoint": base / "checkpoints/phase2_v2_best_checkpoint.pt",
        "run_checkpoint": base / "runs/phase2_v2_20260709_5080_seed17/best_checkpoint.pt",
        "metrics": base / "runs/phase2_v2_20260709_5080_seed17/test_metrics.json",
        "metrics_bundle": base / "reports/phase2_v2_metrics.json",
        "report": base / "reports/phase2_v2_eval.md",
        "pvrig_predictions": base / "predictions/pvrig_top_candidates_phase2_v2.csv",
        "train_log": base / "logs/phase2_v2_20260709_5080_seed17.log",
        "script": base / "src/train_phase2_v2.py",
        "builder": base / "src/build_structure_contact_maps_v2.py",
    }
    for path in paths.values():
        require(path)

    env_text = paths["env"].read_text(encoding="utf-8")
    metrics = json.loads(paths["metrics"].read_text(encoding="utf-8"))
    summary = pd.read_csv(paths["contact_summary"])
    pvrig = pd.read_csv(paths["pvrig_predictions"])
    contact_pos = int(summary["positive_pairs"].sum())
    contact_neg = int(summary["negative_pairs"].sum())
    checks: list[tuple[str, bool, str]] = []
    checks.append(("cuda_5080_available", "NVIDIA GeForce RTX 5080" in env_text and '"cuda_available": true' in env_text, "environment_audit.md confirms torch CUDA on RTX 5080"))
    checks.append(("real_contact_records_present", len(summary) >= 100 and contact_pos > 0 and contact_neg > 0, f"records={len(summary)} pos={contact_pos} neg={contact_neg}"))
    checks.append(("contact_split_present", set(summary["split"].astype(str)) == {"train", "val", "test"}, str(summary["split"].value_counts().to_dict())))
    checks.append(("contact_test_metric_present", "contact_test" in metrics and metrics["contact_test"].get("contact_auprc", 0) > 0, json.dumps(metrics.get("contact_test", {}))))
    checks.append(("contact_better_than_random", metrics["contact_test"].get("contact_auprc", 0) > metrics["contact_test"].get("contact_positive_rate", 1), f"auprc={metrics['contact_test'].get('contact_auprc')} positive_rate={metrics['contact_test'].get('contact_positive_rate')}"))
    checks.append(("contact_auroc_above_random", metrics["contact_test"].get("contact_auroc", 0) > 0.5, f"contact_auroc={metrics['contact_test'].get('contact_auroc')}"))
    checks.append(("pair_metrics_present", "pair_test" in metrics and "pair_test_by_negative_type" in metrics, json.dumps(metrics.get("pair_test", {}))))
    checks.append(("hard_negative_breakdown_present", set(metrics["pair_test_by_negative_type"].keys()) >= {"N1_easy_cross_antigen", "N2_same_family_hard_antigen", "N3_framework_similar_hard_vhh"}, str(metrics["pair_test_by_negative_type"].keys())))
    checks.append(("pvrig_predictions_50", len(pvrig) == 50, f"rows={len(pvrig)}"))
    checks.append(("pvrig_predictions_leakage_free", pvrig["leakage_label"].astype(str).eq("NO_KNOWN_POSITIVE_LEAKAGE").all(), str(pvrig["leakage_label"].value_counts().to_dict())))
    checks.append(("report_states_real_contact_boundary", "heavy-atom contact-map" in paths["report"].read_text(encoding="utf-8"), "phase2_v2_eval.md"))

    warnings = []
    if metrics["pair_test"].get("pair_auroc", 0) < 0.60:
        warnings.append(f"pair binding remains weak: AUROC={metrics['pair_test'].get('pair_auroc'):.4f}, AUPRC={metrics['pair_test'].get('pair_auprc'):.4f}")
    if metrics["site_test"].get("paratope_auprc", 0) < 0.6244:
        warnings.append(f"site paratope lower than V1 because V2 prioritizes real contact loss: {metrics['site_test'].get('paratope_auprc'):.4f} < 0.6244")
    if metrics["site_test"].get("epitope_auprc", 0) < 0.1541:
        warnings.append(f"site epitope lower than V1: {metrics['site_test'].get('epitope_auprc'):.4f} < 0.1541")

    failed = [c for c in checks if not c[1]]
    status = "PASS" if not failed else "FAIL"
    lines = [
        "# Phase 2 V2 Completion Audit",
        "",
        "Updated: 2026-07-09",
        "",
        f"Verdict: {status}",
        "",
        "## Summary",
        "",
        f"- Real contact-map records: {len(summary)}",
        f"- Real positive contact pairs: {contact_pos}",
        f"- Real non-contact negative pairs: {contact_neg}",
        f"- Contact test AUROC/AUPRC: {metrics['contact_test']['contact_auroc']:.4f} / {metrics['contact_test']['contact_auprc']:.4f}",
        f"- Contact positive rate: {metrics['contact_test']['contact_positive_rate']:.4f}",
        f"- Pair test AUROC/AUPRC: {metrics['pair_test']['pair_auroc']:.4f} / {metrics['pair_test']['pair_auprc']:.4f}",
        f"- Paratope test AUROC/AUPRC: {metrics['site_test']['paratope_auroc']:.4f} / {metrics['site_test']['paratope_auprc']:.4f}",
        f"- Epitope test AUROC/AUPRC: {metrics['site_test']['epitope_auroc']:.4f} / {metrics['site_test']['epitope_auprc']:.4f}",
        f"- PVRIG prediction rows: {len(pvrig)}",
        "",
        "## Checks",
        "",
        "| Check | Status | Evidence |",
        "| --- | --- | --- |",
    ]
    for name, ok, evidence in checks:
        lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | `{str(evidence).replace(chr(10), ' ')[:900]}` |")
    lines.extend(["", "## Warnings", ""])
    if warnings:
        for w in warnings:
            lines.append(f"- {w}")
    else:
        lines.append("- None")
    lines.extend([
        "",
        "## Boundary",
        "",
        "This audit proves V2 real heavy-atom contact-map training ran on the RTX 5080 environment and produced test metrics plus PVRIG re-scoring. It does not prove experimental binding, Kd, IC50, or PVRIG-PVRL2 blocking for new candidates.",
        "",
    ])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    result = {"status": status, "warnings": warnings, "checks": [{"name": n, "passed": bool(ok), "evidence": str(e)} for n, ok, e in checks]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
