#!/usr/bin/env python3
"""Validate the PVRIG-VHH MVP output contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def require_file(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        raise SystemExit(f"Missing or empty required file: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", default="model_data/mvp_candidates_v0.csv")
    parser.add_argument("--scores", default="reports/mvp_pvrig_candidate_scores_v0.csv")
    parser.add_argument("--top", default="reports/mvp_pvrig_top_candidates_v0.csv")
    parser.add_argument("--controls", default="reports/mvp_pvrig_control_scores_v0.csv")
    parser.add_argument("--summary", default="reports/mvp_pvrig_summary_v0.json")
    parser.add_argument("--report", default="reports/MVP_PVRIG_VHH_WORKFLOW_REPORT.md")
    parser.add_argument("--contact", default="model_data/sabdab2_single_domain_contacts_mvp.csv")
    parser.add_argument("--contact-report", default="reports/sabdab2_contact_extraction_mvp.md")
    parser.add_argument("--audit-out", default="")
    args = parser.parse_args()

    paths = {name: Path(value) for name, value in vars(args).items() if name != "audit_out" and value}
    for path in paths.values():
        require_file(path)

    pool = pd.read_csv(paths["pool"])
    scores = pd.read_csv(paths["scores"])
    top = pd.read_csv(paths["top"])
    controls = pd.read_csv(paths["controls"])
    contact = pd.read_csv(paths["contact"])
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))

    checks: list[tuple[str, bool, str]] = []
    checks.append(("pool_nonempty", len(pool) > 0, f"pool_rows={len(pool)}"))
    checks.append(("scores_match_pool", len(scores) == len(pool), f"scores={len(scores)} pool={len(pool)}"))
    checks.append(("top_nonempty", len(top) > 0, f"top_rows={len(top)}"))
    checks.append(("controls_nonempty", len(controls) > 0, f"control_rows={len(controls)}"))
    checks.append(("contact_nonempty", len(contact) > 0, f"contact_rows={len(contact)}"))
    checks.append(("top_all_no_leakage", top["leakage_label"].astype(str).eq("NO_KNOWN_POSITIVE_LEAKAGE").all(), top["leakage_label"].value_counts().to_dict().__repr__()))
    checks.append(("top_all_new_candidates", top["candidate_role"].astype(str).str.contains("new_candidate", na=False).all(), top["candidate_role"].value_counts().to_dict().__repr__()))
    checks.append(("controls_all_excluded_or_held", controls["final_blocker_like_calibrated_label"].astype(str).str.contains("EXCLUDE|HOLD_NEAR", regex=True, na=False).all(), controls["final_blocker_like_calibrated_label"].value_counts().to_dict().__repr__()))
    checks.append(("known_positive_exact_controls_present", int((scores["leakage_label"] == "EXACT_KNOWN_POSITIVE").sum()) > 0, scores["leakage_label"].value_counts().to_dict().__repr__()))
    checks.append(("near_positive_controls_present", int((scores["leakage_label"] == "NEAR_KNOWN_POSITIVE_OR_CDR_SIMILAR").sum()) > 0, scores["leakage_label"].value_counts().to_dict().__repr__()))
    checks.append(("summary_counts_agree", int(summary.get("candidate_pool_rows", -1)) == len(pool) and int(summary.get("scored_rows", -1)) == len(scores), json.dumps({k: summary.get(k) for k in ["candidate_pool_rows", "scored_rows", "top_rows", "control_rows"]}, ensure_ascii=False)))
    checks.append(("contact_summary_agrees", int(summary.get("contact_extraction_summary", {}).get("contact_rows", -1)) == len(contact), json.dumps(summary.get("contact_extraction_summary", {}), ensure_ascii=False)))

    failed = [rec for rec in checks if not rec[1]]
    result = {
        "status": "PASS" if not failed else "FAIL",
        "pool_rows": int(len(pool)),
        "scores_rows": int(len(scores)),
        "top_rows": int(len(top)),
        "control_rows": int(len(controls)),
        "contact_rows": int(len(contact)),
        "contact_structures": int(contact["pdb"].nunique()) if "pdb" in contact.columns else 0,
        "final_label_counts": scores["final_blocker_like_calibrated_label"].value_counts().to_dict(),
        "leakage_label_counts": scores["leakage_label"].value_counts().to_dict(),
        "checks": [{"name": name, "passed": bool(ok), "evidence": evidence} for name, ok, evidence in checks],
    }
    if args.audit_out:
        out = Path(args.audit_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# PVRIG-VHH MVP Completion Audit",
            "",
            "Updated: 2026-07-09",
            "",
            f"Verdict: {result['status']}",
            "",
            "## Summary",
            "",
            f"- Candidate pool rows: {result['pool_rows']}",
            f"- Scored rows: {result['scores_rows']}",
            f"- Top new candidates: {result['top_rows']}",
            f"- Control rows: {result['control_rows']}",
            f"- Structure contact rows: {result['contact_rows']} across {result['contact_structures']} structures",
            "",
            "## Checks",
            "",
            "| Check | Status | Evidence |",
            "| --- | --- | --- |",
        ]
        for check in result["checks"]:
            status = "PASS" if check["passed"] else "FAIL"
            evidence = str(check["evidence"]).replace("\n", " ")
            lines.append(f"| {check['name']} | {status} | `{evidence}` |")
        lines.extend(
            [
                "",
                "## Boundary",
                "",
                "This audit proves the MVP computational workflow is runnable and internally gated. It does not prove experimental Kd, IC50, or cellular blocking for new candidates.",
                "",
            ]
        )
        out.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
