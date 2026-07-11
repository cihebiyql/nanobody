#!/usr/bin/env python3
"""Summarize V2.5 Node1 monomer QC and exact complex-pose coverage."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent

DEFAULT_ENSEMBLE = EXP_DIR / "predictions/pvrig_candidate_ranking_ai_prior_v2_4_multiseed_ensemble.csv"
DEFAULT_EXACT_POSES = EXP_DIR / "data_splits/phase2_v2_4_candidate_pose_index.csv"
DEFAULT_BATCH_ROOT = WORKSPACE_ROOT / "docking/candidates/v2_5_pose_batch"
DEFAULT_CSV = EXP_DIR / "prepared/pvrig_pose_proxy_summary_v2_5.csv"
DEFAULT_AUDIT = EXP_DIR / "audits/phase2_v2_5_pose_coverage_audit.json"
DEFAULT_REPORT = DEFAULT_BATCH_ROOT / "reports/RUN_REPORT.md"

CLAIM_BOUNDARY = "computational_pose_qc_proxy_not_binding_or_blocker_proof"


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_gate_evidence(remote: Path) -> dict[str, object]:
    logs = sorted((remote / "logs").glob("run_node1_v2_5_pose_batch.*.log"))
    if not logs:
        return {"status": "LOAD_GATE_EVIDENCE_NOT_FOUND"}
    path = logs[-1]
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"LOAD_GATE_REFUSE load1=([0-9.]+) threshold=([0-9.]+)", text)
    evidence: dict[str, object] = {
        "log_path": str(path),
        "log_sha256": file_sha256(path),
        "latest_log_selected": True,
    }
    if match:
        evidence.update(
            {
                "status": "GATED_NOT_RUN_DUE_NODE1_LOAD",
                "observed_load1": float(match.group(1)),
                "threshold": float(match.group(2)),
            }
        )
    else:
        evidence["status"] = "LATEST_LOG_HAS_NO_LOAD_GATE_REFUSAL"
    return evidence


def build_summary(args: argparse.Namespace) -> tuple[pd.DataFrame, dict]:
    ensemble = pd.read_csv(args.ensemble).sort_values("consensus_rank")
    exact = pd.read_csv(args.exact_poses)
    exact_by_id = exact.set_index("candidate_id").to_dict("index")
    batch = pd.read_csv(args.batch_root / "manifests/selected_candidates_manifest.tsv", sep="\t")
    selected = set(batch["candidate_id"].astype(str))
    remote = args.batch_root / "remote_sync"
    rows: list[dict[str, object]] = []
    for _, source in ensemble.iterrows():
        candidate_id = str(source["candidate_id"])
        prior = exact_by_id.get(candidate_id)
        is_selected = candidate_id in selected
        seq_report_path = remote / "reports" / candidate_id / f"{candidate_id}_sequence_validation.json"
        geometry_path = remote / "reports" / candidate_id / f"{candidate_id}_monomer_geometry_qc.json"
        seq_report = load_json(seq_report_path) if seq_report_path.exists() else {}
        geometry = load_json(geometry_path) if geometry_path.exists() else {}
        chain = geometry.get("chains", {}).get("A", {}) if geometry else {}
        exact_complex = prior is not None and str(prior.get("pose_index_status", "")) == "verified_pose_proxy"
        if exact_complex:
            pose_id = str(prior["pose_id"])
            pose_status = "exact_qc_passed"
            local_evidence = str(prior.get("local_haddock_top_dir", ""))
        elif is_selected and seq_report and geometry:
            pose_id = ""
            pose_status = "monomer_qc_passed_no_complex_pose"
            local_evidence = str(seq_report_path.parent)
        else:
            pose_id = ""
            pose_status = "no_candidate_specific_pose"
            local_evidence = ""
        fallback_log = remote / "logs" / f"{candidate_id}_nanobodybuilder2_unrefined_fallback.log"
        nbb2_status = (
            "completed_unrefined_fallback" if fallback_log.exists() else
            "completed_refined_default" if is_selected and seq_report else
            str(prior.get("nbb2_status", "not_run")) if prior else "not_run"
        )
        rows.append(
            {
                "candidate_id": candidate_id,
                "consensus_rank": int(source["consensus_rank"]),
                "candidate_identity_sha256": str(source["candidate_identity_sha256"]),
                "pose_id": pose_id,
                "pose_qc_status": pose_status,
                "monomer_qc_status": "pass" if bool(chain.get("likely_sane_backbone")) else ("pass_from_v2_4" if exact_complex else "not_run"),
                "monomer_sequence_exact_match": bool(seq_report.get("exact_match")) if seq_report else (bool(prior.get("vhh_chain_a_exact_match")) if prior else False),
                "monomer_ca_count": int(chain.get("ca_count", prior.get("monomer_ca_count", 0) if prior else 0) or 0),
                "complex_pose_available": bool(exact_complex),
                "exact_qc_passed": bool(exact_complex),
                "selected_for_v2_5_batch": bool(is_selected),
                "nbb2_status": nbb2_status,
                "evidence_level": "E3",
                "allowed_use": "POSE_PROXY_TRIAGE_ONLY",
                "global_fusion_eligible": False,
                "local_evidence_path": local_evidence,
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )
    frame = pd.DataFrame(rows)
    exact_count = int(frame["exact_qc_passed"].sum())
    monomer_count = int((frame["monomer_qc_status"] == "pass").sum())
    coverage = exact_count / len(frame)
    gate = load_gate_evidence(remote)
    audit = {
        "status": "PASS",
        "schema_version": "phase2_v2_5_pose_coverage_v1",
        "candidate_count": int(len(frame)),
        "prior_exact_complex_pose_count": exact_count,
        "v2_5_new_monomer_sequence_geometry_qc_pass_count": monomer_count,
        "exact_qc_passed_coverage": coverage,
        "global_fusion_min_coverage": 0.8,
        "global_fusion_applied": False,
        "missingness_audit_pass": False,
        "missingness_reason": "candidate-specific complex poses remain selected-rank dependent and cover less than 80 percent",
        "haddock3_status": gate["status"],
        "haddock3_load_gate_evidence": gate,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    return frame, audit


def write_report(frame: pd.DataFrame, audit: dict, path: Path) -> None:
    selected = frame[frame["selected_for_v2_5_batch"]]
    gate = audit["haddock3_load_gate_evidence"]
    if gate.get("status") == "GATED_NOT_RUN_DUE_NODE1_LOAD":
        haddock_line = f"- HADDOCK3: gated and not started at load1 `{gate.get('observed_load1')}` versus threshold `{gate.get('threshold')}`."
    else:
        haddock_line = f"- HADDOCK3: latest-log status `{gate.get('status')}`; no historical gate is promoted to current state."
    lines = [
        "# V2.5 Node1 Pose/QC Run Report",
        "",
        f"- Candidate universe: {len(frame)}.",
        f"- Existing exact QC-passed complex poses: {audit['prior_exact_complex_pose_count']}/{len(frame)} ({audit['exact_qc_passed_coverage']:.1%}).",
        f"- New V2.5 NanoBodyBuilder2 monomer sequence/geometry QC passes: {audit['v2_5_new_monomer_sequence_geometry_qc_pass_count']}/{len(selected)} selected candidates.",
        haddock_line,
        "- Global pose fusion: disabled; exact complex coverage is below 80% and pose missingness is rank-dependent.",
        f"- Claim boundary: `{CLAIM_BOUNDARY}`.",
        "",
        "## V2.5 Monomer Batch",
        "",
        "| Candidate | Rank | NBB2 | Sequence | Geometry | CA |",
        "| --- | ---: | --- | --- | --- | ---: |",
    ]
    for _, row in selected.sort_values("consensus_rank").iterrows():
        lines.append(
            f"| {row['candidate_id']} | {row['consensus_rank']} | {row['nbb2_status']} | "
            f"{'exact' if row['monomer_sequence_exact_match'] else 'FAIL'} | {row['monomer_qc_status']} | {row['monomer_ca_count']} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict:
    frame, audit = build_summary(args)
    if len(frame) != 50 or int(frame["exact_qc_passed"].sum()) != 2:
        raise ValueError("Expected 50 candidates and exactly two existing exact complex poses")
    selected = frame[frame["selected_for_v2_5_batch"]]
    if len(selected) != 8 or not selected["monomer_sequence_exact_match"].all() or not selected["monomer_qc_status"].eq("pass").all():
        raise ValueError("V2.5 selected monomer batch did not pass 8/8 sequence and geometry QC")
    args.csv_out.parent.mkdir(parents=True, exist_ok=True)
    args.audit_out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.csv_out, index=False)
    args.audit_out.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report(frame, audit, args.report_out)
    return audit


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ensemble", type=Path, default=DEFAULT_ENSEMBLE)
    parser.add_argument("--exact-poses", type=Path, default=DEFAULT_EXACT_POSES)
    parser.add_argument("--batch-root", type=Path, default=DEFAULT_BATCH_ROOT)
    parser.add_argument("--csv-out", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--audit-out", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--report-out", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


def main() -> None:
    print(json.dumps(run(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
