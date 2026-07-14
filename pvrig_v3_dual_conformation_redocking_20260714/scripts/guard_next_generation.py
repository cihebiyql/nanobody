#!/usr/bin/env python3
"""Block generation until both evaluator stability and frozen-panel enrichment pass."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from analyze_p2_p3_p4_enrichment import analyze as recompute_enrichment
from common import project_root, read_json, sha256_file


def blocked(reason: str) -> int:
    print(json.dumps({"status": "BLOCKED", "reason": reason}, sort_keys=True), file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=project_root())
    parser.add_argument("--evaluator", default="reports/EVALUATOR_STABLE.json")
    parser.add_argument("--enrichment", default="reports/P2_P3_P4_ENRICHMENT.json")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    evaluator_path = Path(args.evaluator)
    if not evaluator_path.is_absolute():
        evaluator_path = root / evaluator_path
    enrichment_path = Path(args.enrichment)
    if not enrichment_path.is_absolute():
        enrichment_path = root / enrichment_path
    lock_path = root / "PROTOCOL_LOCK.json"
    manifest_path = root / "manifests/docking_jobs.tsv"
    stability_spec_path = root / "config/evaluator_stability_gate.json"
    enrichment_spec_path = root / "config/next_generation_gate_spec.json"
    core_lock_path = root / "PROTOCOL_CORE_LOCK.json"
    candidates_path = root / "inputs/candidates_128.tsv"
    job_results_path = root / "reports/job_results.tsv"
    pose_scores_path = root / "reports/pose_scores.tsv"
    required = (
        (evaluator_path, "evaluator"),
        (enrichment_path, "enrichment"),
        (lock_path, "protocol_lock"),
        (manifest_path, "job_manifest"),
        (core_lock_path, "protocol_core_lock"),
        (candidates_path, "candidates"),
        (job_results_path, "job_results"),
        (pose_scores_path, "pose_scores"),
        (stability_spec_path, "stability_spec"),
        (enrichment_spec_path, "enrichment_spec"),
    )
    for path, label in required:
        if not path.is_file():
            return blocked(f"missing_{label}:{path}")
    evaluator = read_json(evaluator_path)
    enrichment = read_json(enrichment_path)
    enrichment_spec = read_json(enrichment_spec_path)
    lock = read_json(lock_path)
    core_lock = read_json(core_lock_path)
    if evaluator.get("status") != "PASS":
        return blocked(f"evaluator_status_not_pass:{evaluator.get('status', 'MISSING')}")
    if evaluator.get("unlockable") is not True:
        return blocked("evaluator_not_unlockable")
    if evaluator.get("evidence_mode") != "production_pose_backed":
        return blocked(f"evaluator_evidence_mode_not_production:{evaluator.get('evidence_mode', 'MISSING')}")
    if not evaluator.get("gates"):
        return blocked("evaluator_gates_missing")
    if any(item.get("status") != "PASS" for item in evaluator.get("gates", {}).values()):
        return blocked("one_or_more_evaluator_gates_not_pass")
    if enrichment.get("status") != "PASS":
        return blocked(f"enrichment_status_not_pass:{enrichment.get('status', 'MISSING')}")
    if enrichment.get("unlockable") is not True:
        return blocked("enrichment_not_unlockable")
    if enrichment.get("evidence_mode") != "production_pose_backed":
        return blocked(f"enrichment_evidence_mode_not_production:{enrichment.get('evidence_mode', 'MISSING')}")
    eligible_phases = enrichment.get("eligible_phases", [])
    if not eligible_phases or any(phase not in {"P2", "P3", "P4"} for phase in eligible_phases):
        return blocked("eligible_p2_p3_p4_phases_missing_or_invalid")
    if enrichment.get("gate_id") != enrichment_spec.get("gate_id"):
        return blocked("enrichment_gate_id_mismatch")
    if enrichment.get("inference_scope") != enrichment_spec.get("inference_scope"):
        return blocked("enrichment_inference_scope_mismatch")
    phase_rows = {str(row.get("phase")): row for row in enrichment.get("phase_results", [])}
    if any(phase not in phase_rows or str(phase_rows[phase].get("eligible", "")).lower() != "true" for phase in eligible_phases):
        return blocked("eligible_phase_result_missing_or_not_supported")
    if lock.get("status") != "LOCKED":
        return blocked(f"protocol_lock_status_not_locked:{lock.get('status', 'MISSING')}")
    if core_lock.get("status") != "CORE_LOCKED":
        return blocked(f"protocol_core_lock_status_not_locked:{core_lock.get('status', 'MISSING')}")
    core_lock_file_sha = sha256_file(core_lock_path)
    if core_lock_file_sha != lock.get("core_lock_sha256"):
        return blocked("protocol_core_lock_file_sha256_mismatch")
    if core_lock.get("protocol_core_sha256") != lock.get("protocol_core_sha256"):
        return blocked("protocol_core_sha256_mismatch")
    core_file_records = core_lock.get("files", [])
    if not core_file_records:
        return blocked("core_protocol_file_manifest_missing")
    drifted_core_files = []
    for record in core_file_records:
        relative = str(record.get("path", ""))
        path = root / relative
        if not relative or not path.is_file() or sha256_file(path) != record.get("sha256"):
            drifted_core_files.append(relative or "MISSING_PATH")
    if drifted_core_files:
        return blocked(f"core_protocol_files_drifted:{','.join(sorted(drifted_core_files))}")
    final_file_records = lock.get("files", [])
    if not final_file_records:
        return blocked("final_protocol_file_manifest_missing")
    drifted_final_files = []
    for record in final_file_records:
        relative = str(record.get("path", ""))
        path = root / relative
        if not relative or not path.is_file() or sha256_file(path) != record.get("sha256"):
            drifted_final_files.append(relative or "MISSING_PATH")
    if drifted_final_files:
        return blocked(f"final_protocol_files_drifted:{','.join(sorted(drifted_final_files))}")
    if evaluator.get("protocol_core_sha256") != lock.get("protocol_core_sha256"):
        return blocked("protocol_core_sha256_mismatch")
    if evaluator.get("protocol_core_lock_file_sha256") != core_lock_file_sha:
        return blocked("evaluator_protocol_core_lock_file_sha256_mismatch")
    if evaluator.get("protocol_lock_sha256") != lock.get("protocol_lock_sha256"):
        return blocked("protocol_lock_sha256_mismatch")
    lock_file_sha = sha256_file(lock_path)
    if evaluator.get("protocol_lock_file_sha256") != lock_file_sha:
        return blocked("protocol_lock_file_sha256_mismatch")
    if evaluator.get("stability_gate_spec_sha256") != sha256_file(stability_spec_path):
        return blocked("stability_gate_spec_sha256_mismatch")
    evidence_hashes = {
        "candidates_sha256": sha256_file(candidates_path),
        "job_results_sha256": sha256_file(job_results_path),
        "pose_scores_sha256": sha256_file(pose_scores_path),
    }
    for key, observed in evidence_hashes.items():
        if evaluator.get(key) != observed:
            return blocked(f"evaluator_{key}_mismatch")
    manifest_sha = sha256_file(manifest_path)
    if manifest_sha != lock.get("job_manifest_sha256") or manifest_sha != evaluator.get("job_manifest_sha256"):
        return blocked("job_manifest_sha256_mismatch")
    bindings = enrichment.get("bindings", {})
    if bindings.get("evaluator_evidence_mode") != "production_pose_backed" or bindings.get("evaluator_unlockable") is not True:
        return blocked("enrichment_evaluator_binding_not_unlockable_production")
    if bindings.get("evaluator_file_sha256") != sha256_file(evaluator_path):
        return blocked("enrichment_evaluator_file_sha256_mismatch")
    for key, expected in (
        ("protocol_core_sha256", lock.get("protocol_core_sha256")),
        ("protocol_lock_sha256", lock.get("protocol_lock_sha256")),
        ("protocol_lock_file_sha256", lock_file_sha),
        ("job_manifest_sha256", manifest_sha),
        ("protocol_core_lock_file_sha256", core_lock_file_sha),
        *tuple(evidence_hashes.items()),
    ):
        if bindings.get(key) != expected:
            return blocked(f"enrichment_{key}_mismatch")
    if enrichment.get("gate_spec_file_sha256") != sha256_file(enrichment_spec_path):
        return blocked("enrichment_gate_spec_sha256_mismatch")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        recomputed = recompute_enrichment(
            root,
            enrichment_spec_path,
            tmp / "P2_P3_P4_ENRICHMENT.json",
            tmp / "p2_p3_p4_enrichment.tsv",
        )
    if recomputed.get("status") != "PASS":
        return blocked(f"recomputed_enrichment_status_not_pass:{recomputed.get('status', 'MISSING')}")
    if recomputed != enrichment:
        return blocked("enrichment_report_does_not_match_current_evidence_recomputation")
    print(
        json.dumps(
            {
                "status": "UNLOCKED",
                "evaluator": str(evaluator_path),
                "enrichment": str(enrichment_path),
                "eligible_phases": eligible_phases,
                "protocol_lock_sha256": lock["protocol_lock_sha256"],
                "job_manifest_sha256": manifest_sha,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
