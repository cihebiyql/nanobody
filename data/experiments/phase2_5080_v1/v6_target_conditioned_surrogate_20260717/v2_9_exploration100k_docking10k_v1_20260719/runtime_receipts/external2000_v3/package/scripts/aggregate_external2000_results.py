#!/usr/bin/env python3
"""Aggregate the external 2,000-candidate, dual-receptor, single-seed shard.

This is a shard-level evidence collector, not the full calibrated V29/V3 evaluator.
It deliberately does not apply the 47-control or multi-seed stability gates.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from aggregate_results import collect_results, evaluate_lineage_and_pose_evidence, is_success
from common import read_json, sha256_file, write_json, write_tsv
from validate_protocol import load_rows

PENDING = {"", "PENDING", "QUEUED", "RUNNING", "MISSING_EVIDENCE"}
PAIR_ORDINAL = {"OTHER": 0, "SUPPORTED_AB": 1, "STRICT_A": 2}


def resolved(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def manifest_gate(
    root: Path,
    jobs: list[dict[str, str]],
    expected_sequences: int,
    expected_jobs: int,
    expected_seed: str,
) -> dict[str, Any]:
    reasons: list[str] = []
    by_entity: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in jobs:
        by_entity[row.get("entity_id", "")].append(row)
    job_ids = [row.get("job_id", "") for row in jobs]
    job_hashes = [row.get("job_hash", "") for row in jobs]
    protocol_hashes = {row.get("protocol_core_sha256", "") for row in jobs}
    if len(jobs) != expected_jobs:
        reasons.append(f"expected_jobs_{expected_jobs}_got_{len(jobs)}")
    if len(by_entity) != expected_sequences or "" in by_entity:
        reasons.append(f"expected_entities_{expected_sequences}_got_{len(by_entity) - int('' in by_entity)}")
    if len(set(job_ids)) != len(job_ids) or any(not value for value in job_ids):
        reasons.append("job_ids_blank_or_duplicate")
    if len(set(job_hashes)) != len(job_hashes) or any(not value for value in job_hashes):
        reasons.append("job_hashes_blank_or_duplicate")
    if {row.get("entity_type", "") for row in jobs} != {"candidate"}:
        reasons.append("manifest_must_contain_candidates_only")
    if {row.get("seed", "") for row in jobs} != {expected_seed}:
        reasons.append("manifest_seed_set_mismatch")
    malformed = []
    for entity, rows in by_entity.items():
        if len(rows) != 2 or {row.get("conformation", "") for row in rows} != {"8x6b", "9e6y"}:
            malformed.append(entity)
    if malformed:
        reasons.append(f"entities_without_exact_dual_receptor_pair:{len(malformed)}")
    lock = read_json(root / "PROTOCOL_CORE_LOCK.json", {})
    locked_hash = str(lock.get("protocol_core_sha256", ""))
    if len(protocol_hashes) != 1 or "" in protocol_hashes:
        reasons.append("manifest_not_bound_to_one_protocol_core")
    elif locked_hash and next(iter(protocol_hashes)) != locked_hash:
        reasons.append("manifest_protocol_core_mismatch")
    missing_monomers = [row["job_id"] for row in jobs if not resolved(root, row.get("monomer_source", "")).is_file()]
    if missing_monomers:
        reasons.append(f"missing_monomer_sources:{len(missing_monomers)}")
    for rel in (
        "inputs/normalized/8x6b_pvrig_receptor.pdb",
        "inputs/normalized/9e6y_pvrig_receptor.pdb",
        "inputs/normalized/8x6b_TL_reference.pdb",
        "inputs/normalized/9e6y_TL_reference.pdb",
        "reports/reference_normalization_summary.json",
    ):
        if not (root / rel).is_file():
            reasons.append(f"missing_runtime_dependency:{rel}")
    return {
        "status": "PASS" if not reasons else "FAIL",
        "reasons": sorted(reasons),
        "job_count": len(jobs),
        "entity_count": len(by_entity),
        "seed_set": sorted({row.get("seed", "") for row in jobs}),
        "conformation_set": sorted({row.get("conformation", "") for row in jobs}),
        "protocol_core_sha256": sorted(protocol_hashes),
    }


def candidate_rows(
    root: Path, jobs: list[dict[str, str]], results: list[dict[str, str]]
) -> list[dict[str, Any]]:
    result_by_job = {row.get("job_id", ""): row for row in results}
    grouped: dict[str, dict[str, tuple[dict[str, str], dict[str, str]]]] = defaultdict(dict)
    for job in jobs:
        grouped[job["entity_id"]][job["conformation"]] = (job, result_by_job.get(job["job_id"], {}))
    output: list[dict[str, Any]] = []
    for entity in sorted(grouped):
        confs = grouped[entity]
        row: dict[str, Any] = {"entity_id": entity, "seed": "917"}
        ordinals: list[int] = []
        errors: list[str] = []
        states: list[str] = []
        for conf in ("8x6b", "9e6y"):
            job, result = confs.get(conf, ({}, {}))
            state = str(result.get("state") or "PENDING").upper()
            states.append(state)
            label = str(result.get("representative_pair_label") or "")
            if is_success(result) and label in PAIR_ORDINAL:
                ordinals.append(PAIR_ORDINAL[label])
            status = read_json(root / "status/jobs" / f"{job.get('job_id', '')}.json", {}) if job else {}
            error = str(status.get("error") or "")
            if error:
                errors.append(f"{conf}:{error}")
            prefix = conf
            row.update(
                {
                    f"{prefix}_job_id": job.get("job_id", ""),
                    f"{prefix}_job_hash": job.get("job_hash", ""),
                    f"{prefix}_state": state,
                    f"{prefix}_native_class": result.get("native_class", ""),
                    f"{prefix}_cross_class": result.get("cross_class", ""),
                    f"{prefix}_pair_label": label,
                    f"{prefix}_pair_support_ordinal": PAIR_ORDINAL.get(label, ""),
                    f"{prefix}_haddock_score": result.get("haddock_score", ""),
                    f"{prefix}_selected_model_count": result.get("selected_model_count", ""),
                    f"{prefix}_pose_score_model_count": result.get("pose_score_model_count", ""),
                    f"{prefix}_model_pair_consensus_fraction": result.get("model_pair_consensus_fraction", ""),
                    f"{prefix}_model_native_cross_support_agreement_fraction": result.get(
                        "model_native_cross_support_agreement_fraction", ""
                    ),
                    f"{prefix}_error": error,
                }
            )
        if len(ordinals) == 2 and all(state == "SUCCESS" for state in states):
            dual_ordinal: int | str = min(ordinals)
            dual_label = {value: key for key, value in PAIR_ORDINAL.items()}[dual_ordinal]
            dual_state = "COMPLETE_DUAL_SUCCESS"
        elif any(state in PENDING for state in states):
            dual_ordinal = ""
            dual_label = ""
            dual_state = "NOT_READY"
        else:
            dual_ordinal = ""
            dual_label = ""
            dual_state = "TECHNICAL_NA"
        row.update(
            {
                "dual_state": dual_state,
                "dual_exact_min_pair_label": dual_label,
                "dual_exact_min_pair_support_ordinal": dual_ordinal,
                "technical_failure_reason": " | ".join(errors),
            }
        )
        output.append(row)
    return output


def aggregate(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    jobs_path = resolved(root, args.jobs)
    result_path = resolved(root, args.job_results)
    pose_path = resolved(root, args.pose_scores)
    candidate_path = resolved(root, args.candidate_summary)
    out_path = resolved(root, args.out)
    for path in (result_path, pose_path, candidate_path, out_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    jobs = load_rows(jobs_path)
    manifest = manifest_gate(root, jobs, args.expected_sequences, args.expected_jobs, str(args.expected_seed))
    results = collect_results(root, jobs, result_path, pose_path) if jobs else []
    lineage = evaluate_lineage_and_pose_evidence(jobs, results)
    candidates = candidate_rows(root, jobs, results)
    fields = list(candidates[0]) if candidates else ["entity_id", "dual_state"]
    write_tsv(candidate_path, candidates, fields)
    result_counts = Counter(str(row.get("state") or "PENDING").upper() for row in results)
    candidate_counts = Counter(str(row.get("dual_state") or "NOT_READY") for row in candidates)
    pending_jobs = sum(result_counts.get(state, 0) for state in PENDING)
    technical_na_jobs = len(results) - result_counts.get("SUCCESS", 0) - pending_jobs
    if manifest["status"] == "FAIL" or lineage["status"] == "FAIL":
        status = "FAIL"
    elif pending_jobs:
        status = "NOT_READY"
    elif technical_na_jobs:
        status = "COMPLETE_WITH_TECHNICAL_NA"
    else:
        status = "COMPLETE"
    payload = {
        "schema_version": "pvrig_v29_external2000_aggregation_v1",
        "status": status,
        "scope": "external_shard_partial_aggregation",
        "unlockable": False,
        "calibration_controls_applied": False,
        "multiseed_stability_gate_applied": False,
        "full_v29_merge_and_canonical_aggregation_required": True,
        "claim_boundary": "Computational dual-receptor, single-seed Docking geometry evidence only; not affinity, Kd, IC50, expression, purity, or experimental blocking.",
        "pair_support_ordinal_mapping": PAIR_ORDINAL,
        "job_count": len(jobs),
        "candidate_count": len(candidates),
        "job_state_counts": dict(sorted(result_counts.items())),
        "candidate_state_counts": dict(sorted(candidate_counts.items())),
        "pending_jobs": pending_jobs,
        "technical_na_jobs": technical_na_jobs,
        "gates": {"external_manifest": manifest, "manifest_bound_pose_evidence": lineage},
        "protocol_core_sha256": manifest.get("protocol_core_sha256", []),
        "job_manifest_sha256": sha256_file(jobs_path) if jobs_path.is_file() else "",
        "job_results_sha256": sha256_file(result_path) if result_path.is_file() else "",
        "pose_scores_sha256": sha256_file(pose_path) if pose_path.is_file() else "",
        "candidate_summary_sha256": sha256_file(candidate_path) if candidate_path.is_file() else "",
        "reports": {
            "job_results": str(result_path),
            "pose_scores": str(pose_path),
            "candidate_dual_summary": str(candidate_path),
        },
        "merge_contract": {
            "return_to_full_project": ["status/jobs", "results", "runs"],
            "identity_keys": ["job_id", "job_hash", "protocol_core_sha256"],
            "technical_failures": "NA_not_negative",
            "canonical_full_aggregator": "scripts/aggregate_results.py in the complete V29 project after all shard results are merged",
        },
    }
    write_json(out_path, payload)
    return payload


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    p.add_argument("--jobs", default="manifests/docking_jobs.tsv")
    p.add_argument("--job-results", default="reports/external_job_results.tsv")
    p.add_argument("--pose-scores", default="reports/external_pose_scores.tsv")
    p.add_argument("--candidate-summary", default="reports/external_candidate_dual.tsv")
    p.add_argument("--out", default="reports/EXTERNAL2000_AGGREGATION.json")
    p.add_argument("--expected-sequences", type=int, default=2000)
    p.add_argument("--expected-jobs", type=int, default=4000)
    p.add_argument("--expected-seed", type=int, default=917)
    args = p.parse_args()
    payload = aggregate(args)
    print(json.dumps({"status": payload["status"], "out": str(resolved(Path(args.root).resolve(), args.out))}, sort_keys=True))
    return 2 if payload["status"] == "FAIL" else 1 if payload["status"] == "NOT_READY" else 0


if __name__ == "__main__":
    raise SystemExit(main())
