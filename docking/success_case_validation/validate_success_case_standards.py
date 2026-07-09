#!/usr/bin/env python3
"""Validate local success-case criteria artifacts and source references."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docking" / "success_case_validation"
CSV_PATH = OUT / "success_case_mechanism_criteria_matrix.csv"
JSON_PATH = OUT / "blocker_judgment_rules_v2.json"
MD_PATHS = [
    OUT / "blocker_design_judgment_standards_v2.md",
    OUT / "success_case_validation_report.md",
    OUT / "README.md",
    OUT / "SEQUENCE_TO_BLOCKER_WORKFLOW_STATUS.md",
    OUT / "POSITIVE_MECHANISM_STRUCTURAL_VALIDATION_AUDIT.md",
    OUT / "WORKFLOW_ROBUSTNESS_VALIDATION_PLAN.md",
    OUT / "WORKFLOW_COMPLETION_AUDIT.md",
]
WORKFLOW_FILES = [
    OUT / "apply_blocker_judgment.py",
    OUT / "prepare_candidate_sequence_workflow.py",
    OUT / "prepare_patent_success_validation_batch.py",
    OUT / "process_haddock3_calibration_run.py",
    OUT / "check_patent_success_calibration_status.py",
    OUT / "validate_patent_sequence_artifacts.py",
    OUT / "score_reference_baseline.py",
    OUT / "summarize_multibaseline_judgment.py",
    OUT / "summarize_patent_success_calibration.py",
    OUT / "validate_batch_screening_outputs.py",
    OUT / "analyze_threshold_sensitivity.py",
    OUT / "analyze_mutant_panel_threshold_sensitivity.py",
    OUT / "prepare_mutant_validation_batch.py",
    OUT / "check_vhh_sequence_leakage.py",
    OUT / "summarize_mutant_panel_status.py",
    OUT / "summarize_mutant_panel_results.py",
    OUT / "run_mutant_panel_batch.py",
    OUT / "validate_mutant_panel_completion.py",
    OUT / "test_success_case_workflow.py",
    OUT / "test_blocker_screening_robustness.py",
    ROOT / "docking" / "scripts" / "normalize_pdb_chain.py",
]
EXPECTED_CASES = {
    "COM701_CPA7021_Tab5",
    "PVRIG_VHH_20_30_38_39_151_HR151",
    "IBI352g4a",
    "GSK4381562_SRF813",
    "SHR2002_TIGIT8_PVRIG30",
    "PM1009_SIM0348",
    "CD112RIVE_structure_guided_trap",
    "NK_cell_blockade_biology",
}
REF_RE = re.compile(r"(?P<path>[^:;]+\.(?:md|csv)):(?P<start>\d+)(?:-(?P<end>\d+))?")


def load_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def validate_refs(rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    for row in rows:
        refs = row.get("source_refs", "")
        matches = list(REF_RE.finditer(refs))
        if not matches:
            errors.append(f"{row.get('criterion_id')}: no parseable source refs")
            continue
        for match in matches:
            rel = match.group("path").strip()
            start = int(match.group("start"))
            end = int(match.group("end") or start)
            path = ROOT / rel
            if not path.exists():
                errors.append(f"{row.get('criterion_id')}: missing source {rel}")
                continue
            lines = load_lines(path)
            if start < 1 or end < start or end > len(lines):
                errors.append(f"{row.get('criterion_id')}: invalid source range {rel}:{start}-{end}, file has {len(lines)} lines")
                continue
            snippet = "".join(lines[start - 1:end]).strip()
            if not snippet:
                errors.append(f"{row.get('criterion_id')}: empty source range {rel}:{start}-{end}")
    return errors


def main() -> None:
    if not CSV_PATH.exists():
        raise SystemExit(f"missing {CSV_PATH}")
    with CSV_PATH.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if len(rows) < 30:
        raise SystemExit(f"too few criteria rows: {len(rows)}")
    cases = {row["case_id"] for row in rows}
    missing = EXPECTED_CASES - cases
    if missing:
        raise SystemExit(f"missing case ids: {sorted(missing)}")
    required_layers = {"hard_negative_control", "hard_computational_gate", "format_context", "anti_overfit", "cell_context"}
    layers = {row["criterion_layer"] for row in rows}
    missing_layers = required_layers - layers
    if missing_layers:
        raise SystemExit(f"missing required layers: {sorted(missing_layers)}")
    errors = validate_refs(rows)
    if errors:
        raise SystemExit("source reference validation failed:\n" + "\n".join(errors[:20]))
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    classifier = data.get("classifier", {})
    for label in ["BLOCKER_LIKE_A", "BINDER_LIKE_C", "FORMAT_CONTEXT_D"]:
        if label not in classifier:
            raise SystemExit(f"missing classifier label {label}")
    for path in MD_PATHS:
        text = path.read_text(encoding="utf-8")
        if len(text) < 2000 or "##" not in text:
            raise SystemExit(f"markdown artifact looks incomplete: {path}")
    for path in WORKFLOW_FILES:
        if not path.exists() or path.stat().st_size < 1000:
            raise SystemExit(f"workflow file looks incomplete: {path}")
    print("OK success-case standards validation passed")
    print(f"criteria_rows={len(rows)}")
    print(f"case_ids={','.join(sorted(cases))}")
    print(f"artifacts={CSV_PATH},{JSON_PATH},{','.join(str(p) for p in MD_PATHS + WORKFLOW_FILES)}")


if __name__ == "__main__":
    main()
