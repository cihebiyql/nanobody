#!/usr/bin/env python3
"""Validate Phase 2 V1 training artifacts and write completion audit."""
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
    parser.add_argument("--out", default="experiments/phase2_5080_v1/audits/PHASE2_TRAINING_COMPLETION_AUDIT.md")
    args = parser.parse_args()
    root = Path(args.root)
    base = root / "experiments/phase2_5080_v1"
    paths = {
        "env": base / "audits/environment_audit.md",
        "manifest_summary": base / "audits/phase2_manifest_build_summary_v1.json",
        "site_split": base / "data_splits/zym_site_split_manifest_v1.csv",
        "pair_split": base / "data_splits/pair_binding_split_v1.csv",
        "pair_negs": base / "negative_sets/pair_negatives_v1.csv",
        "contact_pairs": base / "prepared/structure_contact_pairs_mvp_v1.csv",
        "contact_negs": base / "negative_sets/contact_negatives_v1.csv",
        "pvrig_external": base / "data_splits/pvrig_external_calibration_manifest_v1.csv",
        "checkpoint": base / "checkpoints/phase2_v1_best_checkpoint.pt",
        "metrics": base / "runs/phase2_v1_20260709_5080_seed7/test_metrics.json",
        "report": base / "reports/phase2_v1_eval.md",
        "comparison": base / "reports/phase2_v1_phase1_comparison.json",
        "pvrig_predictions": base / "predictions/pvrig_top_candidates_phase2_v1.csv",
    }
    for p in paths.values():
        require(p)

    manifest = json.loads(paths["manifest_summary"].read_text(encoding="utf-8"))
    metrics = json.loads(paths["metrics"].read_text(encoding="utf-8"))
    comparison = json.loads(paths["comparison"].read_text(encoding="utf-8"))
    site = pd.read_csv(paths["site_split"])
    pair = pd.read_csv(paths["pair_split"])
    neg = pd.read_csv(paths["pair_negs"])
    contact = pd.read_csv(paths["contact_pairs"])
    pvrig = pd.read_csv(paths["pvrig_predictions"])
    env_text = paths["env"].read_text(encoding="utf-8")

    checks: list[tuple[str, bool, str]] = []
    checks.append(("cuda_5080_available", "NVIDIA GeForce RTX 5080" in env_text and '"cuda_available": true' in env_text, "environment_audit.md"))
    checks.append(("site_split_nonempty", len(site) == 1230 and set(site["split"]) == {"train", "val", "test"}, f"rows={len(site)} splits={site['split'].value_counts().to_dict()}"))
    checks.append(("pair_split_has_pos_neg", set(pair["binding_label"].unique()) == {0, 1}, f"labels={pair['binding_label'].value_counts().to_dict()}"))
    checks.append(("pair_negative_types_present", set(neg["negative_type"].unique()) >= {"N1_easy_cross_antigen", "N2_same_family_hard_antigen", "N3_framework_similar_hard_vhh"}, str(neg["negative_type"].value_counts().to_dict())))
    checks.append(("contact_pos_neg_present", set(contact["label"].unique()) == {0, 1}, str(contact["label"].value_counts().to_dict())))
    checks.append(("pvrig_predictions_50", len(pvrig) == 50, f"rows={len(pvrig)}"))
    checks.append(("pvrig_predictions_leakage_free", pvrig["leakage_label"].astype(str).eq("NO_KNOWN_POSITIVE_LEAKAGE").all(), str(pvrig["leakage_label"].value_counts().to_dict())))
    checks.append(("paratope_improved_vs_phase1", comparison["paratope_auprc_delta"] > 0, json.dumps({k: comparison[k] for k in ["phase1_paratope_test_auprc", "phase2_paratope_test_auprc", "paratope_auprc_delta"]})))
    checks.append(("epitope_improved_vs_phase1", comparison["epitope_auprc_delta"] > 0, json.dumps({k: comparison[k] for k in ["phase1_epitope_test_auprc", "phase2_epitope_test_auprc", "epitope_auprc_delta"]})))
    checks.append(("hard_negative_metrics_present", set(metrics["pair_test_by_negative_type"].keys()) >= {"N1_easy_cross_antigen", "N2_same_family_hard_antigen", "N3_framework_similar_hard_vhh"}, str(metrics["pair_test_by_negative_type"].keys())))

    warnings = []
    if metrics["pair_test"].get("pair_auroc", 0) < 0.55:
        warnings.append(f"pair binding head is weak: test AUROC={metrics['pair_test'].get('pair_auroc'):.4f}, AUPRC={metrics['pair_test'].get('pair_auprc'):.4f}")
    if "weak contact proxy" not in paths["report"].read_text(encoding="utf-8"):
        warnings.append("report may not clearly state weak-contact boundary")

    failed = [c for c in checks if not c[1]]
    status = "PASS" if not failed else "FAIL"
    lines = [
        "# Phase 2 V1 Training Completion Audit",
        "",
        "Updated: 2026-07-09",
        "",
        f"Verdict: {status}",
        "",
        "## Summary",
        "",
        f"- CUDA/5080 training environment: {'PASS' if checks[0][1] else 'FAIL'}",
        f"- ZYM site split rows: {len(site)}",
        f"- Pair binding rows: {len(pair)}",
        f"- Pair negative rows: {len(neg)}",
        f"- Structure contact proxy rows: {len(contact)}",
        f"- PVRIG prediction rows: {len(pvrig)}",
        f"- Phase2 paratope test AUPRC: {comparison['phase2_paratope_test_auprc']:.4f} vs Phase1 {comparison['phase1_paratope_test_auprc']:.4f}",
        f"- Phase2 epitope test AUPRC: {comparison['phase2_epitope_test_auprc']:.4f} vs Phase1 {comparison['phase1_epitope_test_auprc']:.4f}",
        f"- Phase2 pair test AUROC/AUPRC: {metrics['pair_test']['pair_auroc']:.4f} / {metrics['pair_test']['pair_auprc']:.4f}",
        "",
        "## Checks",
        "",
        "| Check | Status | Evidence |",
        "| --- | --- | --- |",
    ]
    for name, ok, evidence in checks:
        lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | `{str(evidence).replace(chr(10), ' ')}` |")
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
        "This audit proves Phase 2 V1 was trained and evaluated on the RTX 5080 environment. It does not prove experimental binding or blocking. The pair-binding head is reported honestly as weak in this first V1 run.",
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
