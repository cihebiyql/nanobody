#!/usr/bin/env python3
"""Collect pose evidence, aggregate all jobs, and enforce evaluator stability."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import read_json, sha256_file, write_json, write_tsv
from validate_protocol import FAIL, NOT_READY, PASS, evaluate as validate_protocol, gate, load_rows, overall_status


SUCCESS_STATES = {"SUCCESS", "PASS", "PASSED", "COMPLETE", "COMPLETED", "DONE"}
PENDING_STATES = {"", "PENDING", "QUEUED", "RUNNING", "MISSING_EVIDENCE"}
CLASS_ORDER = ["A", "B", "C", "E"]
LEGACY_THRESHOLDS = {"hotspot": 14.0, "total_occlusion": 500.0, "cdr3_occlusion": 100.0, "cdr3_fraction": 0.15}


def entity_id(row: dict[str, str]) -> str:
    return row.get("entity_id") or row.get("candidate_id") or row.get("control_id") or ""


def entity_type(row: dict[str, str]) -> str:
    return (row.get("entity_type") or "").lower()


def control_class(row: dict[str, str]) -> str:
    return (row.get("control_class") or "").lower()


def is_success(row: dict[str, str] | None) -> bool:
    return bool(row) and str(row.get("state", "")).upper() in SUCCESS_STATES


def metric(score: dict[str, Any], *path: str, default: float = 0.0) -> float:
    value: Any = score
    for key in path:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def classify_geometry(score: dict[str, Any], scale: float = 1.0) -> str:
    hotspot = metric(score, "hotspot_overlap", "full", "count")
    total = metric(score, "vhh_pvrl2_occlusion", "residue_pair_count")
    cdr3 = metric(score, "vhh_pvrl2_occlusion", "by_vhh_region_pair_count", "cdr3")
    fraction = metric(score, "vhh_pvrl2_occlusion", "cdr3_fraction")
    thresholds = {key: value * scale for key, value in LEGACY_THRESHOLDS.items()}
    if hotspot >= thresholds["hotspot"] and total >= thresholds["total_occlusion"] and cdr3 >= thresholds["cdr3_occlusion"] and fraction >= thresholds["cdr3_fraction"]:
        return "A"
    if hotspot >= thresholds["hotspot"] and total < 50 * scale:
        return "C"
    if hotspot >= 10 * scale and total >= 100 * scale and cdr3 >= 20 * scale and fraction >= 0.10 * scale:
        return "B"
    return "E"


def geometry_margin(score: dict[str, Any]) -> float:
    ratios = [
        metric(score, "hotspot_overlap", "full", "count") / LEGACY_THRESHOLDS["hotspot"],
        metric(score, "vhh_pvrl2_occlusion", "residue_pair_count") / LEGACY_THRESHOLDS["total_occlusion"],
        metric(score, "vhh_pvrl2_occlusion", "by_vhh_region_pair_count", "cdr3") / LEGACY_THRESHOLDS["cdr3_occlusion"],
        metric(score, "vhh_pvrl2_occlusion", "cdr3_fraction") / LEGACY_THRESHOLDS["cdr3_fraction"],
    ]
    return min(ratios)


def pose_rows_for_job(job: dict[str, str], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in evidence.get("pose_scores", []):
        score_by_ref = {score["reference_id"]: score for score in payload.get("scores", [])}
        if set(score_by_ref) != {"8x6b", "9e6y"}:
            continue
        model = Path(str(payload.get("pose", ""))).name
        haddock = payload.get("haddock_io") or {}
        for reference_id, score in sorted(score_by_ref.items()):
            rows.append(
                {
                    "job_id": job["job_id"],
                    "entity_id": job["entity_id"],
                    "entity_type": job["entity_type"],
                    "control_class": job.get("control_class", ""),
                    "dock_conformation": job["conformation"],
                    "scoring_reference": reference_id,
                    "seed": job["seed"],
                    "model": model,
                    "haddock_score": haddock.get("score"),
                    "air_energy": haddock.get("unw_energies.air"),
                    "geometry_class": classify_geometry(score),
                    "geometry_margin": round(geometry_margin(score), 6),
                    "hotspot_overlap": int(metric(score, "hotspot_overlap", "full", "count")),
                    "anchor_overlap": int(metric(score, "hotspot_overlap", "anchor", "count")),
                    "holdout_overlap": int(metric(score, "hotspot_overlap", "holdout", "count")),
                    "total_occlusion": int(metric(score, "vhh_pvrl2_occlusion", "residue_pair_count")),
                    "cdr3_occlusion": int(metric(score, "vhh_pvrl2_occlusion", "by_vhh_region_pair_count", "cdr3")),
                    "cdr3_fraction": metric(score, "vhh_pvrl2_occlusion", "cdr3_fraction"),
                    "clash_atom_pairs": int(metric(score, "clashes_2p5a", "atom_pair_count")),
                    "clash_residue_pairs": int(metric(score, "clashes_2p5a", "residue_pair_count")),
                    "overlay_rmsd_a": metric(score, "overlay", "t_ca_rmsd_a"),
                }
            )
    return rows


def representative_pose_rows(rows: list[dict[str, Any]], dock_conformation: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    by_model: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_model[str(row["model"])][str(row["scoring_reference"])] = row
    complete = [(model, refs) for model, refs in by_model.items() if set(refs) == {"8x6b", "9e6y"}]
    if not complete:
        return None
    def key(item: tuple[str, dict[str, dict[str, Any]]]) -> tuple[float, str]:
        model, refs = item
        raw = refs[dock_conformation].get("haddock_score")
        try:
            score = float(raw)
        except (TypeError, ValueError):
            score = math.inf
        return score, model
    _model, refs = sorted(complete, key=key)[0]
    other = "9e6y" if dock_conformation == "8x6b" else "8x6b"
    return refs[dock_conformation], refs[other]


def collect_results(root: Path, job_rows: list[dict[str, str]], results_path: Path, poses_path: Path) -> list[dict[str, Any]]:
    result_rows: list[dict[str, Any]] = []
    all_pose_rows: list[dict[str, Any]] = []
    for job in job_rows:
        state_path = root / "status/jobs" / f"{job['job_id']}.json"
        state = read_json(state_path, {})
        state_name = str(state.get("status") or "PENDING")
        evidence_path = root / str(state.get("evidence") or f"results/{job['job_id']}/job_result.json")
        pose_rows: list[dict[str, Any]] = []
        if state_name == "SUCCESS" and evidence_path.is_file():
            pose_rows = pose_rows_for_job(job, read_json(evidence_path))
            all_pose_rows.extend(pose_rows)
        representative = representative_pose_rows(pose_rows, job["conformation"]) if pose_rows else None
        if state_name == "SUCCESS" and representative is None:
            state_name = "MISSING_EVIDENCE"
        native, cross = representative if representative else ({}, {})
        retained_a = native.get("geometry_class") == "A" or cross.get("geometry_class") == "A"
        disruptive = job.get("expected_behavior") == "DISRUPTIVE_CONTROL"
        result_rows.append(
            {
                "job_id": job["job_id"],
                "entity_id": job["entity_id"],
                "entity_type": job["entity_type"],
                "control_class": job.get("control_class", ""),
                "expected_behavior": job.get("expected_behavior", ""),
                "conformation": job["conformation"],
                "seed": job["seed"],
                "state": state_name,
                "attempts": state.get("attempts", 0),
                "selected_model_count": state.get("selected_model_count", 0),
                "pose_score_model_count": len({row["model"] for row in pose_rows}),
                "pose_backed_2x2": str(bool(representative)).lower(),
                "representative_model": native.get("model", ""),
                "haddock_score": native.get("haddock_score", ""),
                "air_energy": native.get("air_energy", ""),
                "native_class": native.get("geometry_class", ""),
                "cross_class": cross.get("geometry_class", ""),
                "native_hotspot_overlap": native.get("hotspot_overlap", ""),
                "cross_hotspot_overlap": cross.get("hotspot_overlap", ""),
                "native_holdout_overlap": native.get("holdout_overlap", ""),
                "cross_holdout_overlap": cross.get("holdout_overlap", ""),
                "native_total_occlusion": native.get("total_occlusion", ""),
                "cross_total_occlusion": cross.get("total_occlusion", ""),
                "native_cdr3_occlusion": native.get("cdr3_occlusion", ""),
                "cross_cdr3_occlusion": cross.get("cdr3_occlusion", ""),
                "native_cdr3_fraction": native.get("cdr3_fraction", ""),
                "cross_cdr3_fraction": cross.get("cdr3_fraction", ""),
                "anomaly_flag": str(bool(disruptive and retained_a)).lower(),
                "anomaly_reason": "disruptive_control_retained_A" if disruptive and retained_a else "",
                "job_hash": job["job_hash"],
            }
        )
    result_fields = list(result_rows[0]) if result_rows else ["job_id", "state"]
    pose_fields = list(all_pose_rows[0]) if all_pose_rows else [
        "job_id", "entity_id", "entity_type", "control_class", "dock_conformation", "scoring_reference", "seed", "model",
        "haddock_score", "air_energy", "geometry_class", "geometry_margin", "hotspot_overlap", "anchor_overlap", "holdout_overlap",
        "total_occlusion", "cdr3_occlusion", "cdr3_fraction", "clash_atom_pairs", "clash_residue_pairs", "overlay_rmsd_a",
    ]
    write_tsv(results_path, result_rows, result_fields)
    write_tsv(poses_path, all_pose_rows, pose_fields)
    return [{key: str(value) for key, value in row.items()} for row in result_rows]


def result_class(result: dict[str, str], docked: str, scored: str) -> str:
    return (result.get("native_class") if docked == scored else result.get("cross_class") or "").upper()


def evaluate_artifacts(job_rows: list[dict[str, str]], result_rows: list[dict[str, str]]) -> dict[str, Any]:
    if not job_rows:
        return gate(NOT_READY, ["job_manifest_missing_or_empty"])
    if not result_rows:
        return gate(NOT_READY, ["result_table_missing_or_empty"])
    return gate(PASS, [], job_count=len(job_rows), result_count=len(result_rows))


def evaluate_lineage_and_pose_evidence(
    job_rows: list[dict[str, str]], result_rows: list[dict[str, str]]
) -> dict[str, Any]:
    reasons: list[str] = []
    job_by_id = {row.get("job_id", ""): row for row in job_rows if row.get("job_id")}
    result_by_id = {row.get("job_id", ""): row for row in result_rows if row.get("job_id")}
    if len(job_by_id) != len(job_rows):
        reasons.append("manifest_job_ids_blank_or_duplicate")
    if len(result_by_id) != len(result_rows):
        reasons.append("result_job_ids_blank_or_duplicate")
    missing = sorted(set(job_by_id) - set(result_by_id))
    extra = sorted(set(result_by_id) - set(job_by_id))
    if missing:
        reasons.append(f"result_rows_missing_manifest_jobs:{len(missing)}")
    if extra:
        reasons.append(f"result_rows_contain_unknown_jobs:{len(extra)}")
    for job_id in sorted(set(job_by_id) & set(result_by_id)):
        job = job_by_id[job_id]
        result = result_by_id[job_id]
        if result.get("job_hash") != job.get("job_hash"):
            reasons.append(f"job_hash_mismatch:{job_id}")
        if is_success(result):
            if result.get("pose_backed_2x2", "").lower() != "true":
                reasons.append(f"success_without_pose_backed_2x2:{job_id}")
            try:
                selected_count = int(float(result.get("selected_model_count") or 0))
                pose_count = int(float(result.get("pose_score_model_count") or 0))
            except (TypeError, ValueError):
                selected_count = pose_count = 0
            if selected_count < 1:
                reasons.append(f"success_without_selected_model:{job_id}")
            if pose_count < 1:
                reasons.append(f"success_without_pose_score_model:{job_id}")
            if not result.get("representative_model") or not result.get("native_class") or not result.get("cross_class"):
                reasons.append(f"success_missing_representative_native_cross:{job_id}")
            try:
                float(result.get("haddock_score", ""))
            except (TypeError, ValueError):
                reasons.append(f"success_missing_haddock_score:{job_id}")
    status = PASS if not reasons else (NOT_READY if missing and not result_rows else FAIL)
    return gate(status, reasons, manifest_jobs=len(job_rows), result_jobs=len(result_rows))


def evaluate_completion(result_rows: list[dict[str, str]], expected: int) -> dict[str, Any]:
    counts = Counter(row.get("state", "PENDING").upper() for row in result_rows)
    pending = sum(counts.get(state, 0) for state in PENDING_STATES)
    if len(result_rows) != expected:
        return gate(NOT_READY, [f"expected_{expected}_result_rows_got_{len(result_rows)}"], counts=dict(counts))
    if pending:
        return gate(NOT_READY, [f"jobs_not_terminal:{pending}"], counts=dict(counts))
    return gate(PASS, [], counts=dict(counts))


def evaluate_controls(job_rows: list[dict[str, str]], expected_controls: int) -> dict[str, Any]:
    controls = [row for row in job_rows if entity_type(row) == "control"]
    entities = {entity_id(row) for row in controls}
    hashes = {row.get("protocol_core_sha256", "") for row in controls}
    reasons = []
    if len(entities) != expected_controls:
        reasons.append(f"expected_{expected_controls}_controls_got_{len(entities)}")
    if len(hashes) != 1 or "" in hashes:
        reasons.append("controls_not_bound_to_one_protocol_core")
    return gate(PASS if not reasons else FAIL, reasons, control_entities=len(entities))


def evaluate_successful_seeds(job_rows: list[dict[str, str]], result_by_job: dict[str, dict[str, str]], minimum: int) -> dict[str, Any]:
    successes: dict[tuple[str, str], set[str]] = defaultdict(set)
    states: dict[tuple[str, str], list[str]] = defaultdict(list)
    for job in job_rows:
        key = (entity_id(job), job["conformation"])
        result = result_by_job.get(job["job_id"], {})
        states[key].append(result.get("state", "PENDING").upper())
        if is_success(result):
            successes[key].add(job["seed"])
    failed: list[str] = []
    waiting: list[str] = []
    for key in sorted(states):
        count = len(successes[key])
        if count >= minimum:
            continue
        reason = f"{key[0]}:{key[1]}:successful_seeds_{count}"
        if any(state in PENDING_STATES for state in states[key]):
            waiting.append(reason)
        else:
            failed.append(reason)
    status = FAIL if failed else NOT_READY if waiting else PASS
    return gate(status, failed + waiting, checked_entity_conformations=len(states))


def evaluate_complete_matrix(result_rows: list[dict[str, str]]) -> dict[str, Any]:
    missing = [row["job_id"] for row in result_rows if is_success(row) and (not row.get("native_class") or not row.get("cross_class"))]
    return gate(PASS if not missing else FAIL, [f"incomplete_native_cross:{job_id}" for job_id in missing])


def evaluate_positive_controls(result_rows: list[dict[str, str]]) -> dict[str, Any]:
    positives = [row for row in result_rows if row.get("control_class") == "positive_control" and is_success(row)]
    if not positives:
        return gate(NOT_READY, ["no_successful_positive_controls"])
    classes = [row[key] for row in positives for key in ("native_class", "cross_class") if row.get(key)]
    if classes and all(value == "E" for value in classes):
        return gate(FAIL, ["positive_controls_collapsed_to_e_only"], observed_classes=dict(Counter(classes)))
    return gate(PASS, [], observed_classes=dict(Counter(classes)))


def evaluate_disruptive_flags(result_rows: list[dict[str, str]]) -> dict[str, Any]:
    reasons = []
    for row in result_rows:
        if row.get("expected_behavior") != "DISRUPTIVE_CONTROL" or not is_success(row):
            continue
        if "A" in {row.get("native_class"), row.get("cross_class")} and row.get("anomaly_flag", "").lower() != "true":
            reasons.append(f"disruptive_retained_A_without_anomaly:{row['job_id']}")
    return gate(PASS if not reasons else FAIL, reasons)


def write_control_drift(path: Path, result_rows: list[dict[str, str]]) -> None:
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in result_rows:
        if row.get("entity_type") == "control":
            grouped[(row["entity_id"], row.get("control_class", ""), row.get("expected_behavior", ""))].append(row)
    output = []
    for (entity, cclass, expected), rows in sorted(grouped.items()):
        classes = [row.get(key, "") for row in rows for key in ("native_class", "cross_class") if row.get(key)]
        counts = Counter(classes)
        output.append(
            {
                "entity_id": entity,
                "control_class": cclass,
                "expected_behavior": expected,
                "successful_jobs": sum(is_success(row) for row in rows),
                "native_cross_disagreement_jobs": sum(row.get("native_class") != row.get("cross_class") for row in rows if is_success(row)),
                "anomaly_jobs": sum(row.get("anomaly_flag") == "true" for row in rows),
                **{f"class_{cls}": counts.get(cls, 0) for cls in CLASS_ORDER},
            }
        )
    write_tsv(path, output, ["entity_id", "control_class", "expected_behavior", "successful_jobs", "native_cross_disagreement_jobs", "anomaly_jobs"] + [f"class_{cls}" for cls in CLASS_ORDER])


def write_threshold_sensitivity(path: Path, pose_rows: list[dict[str, str]]) -> None:
    output = []
    for scale in (0.8, 0.9, 1.0, 1.1, 1.2):
        count = 0
        for row in pose_rows:
            proxy = {
                "hotspot_overlap": {"full": {"count": row.get("hotspot_overlap", 0)}},
                "vhh_pvrl2_occlusion": {
                    "residue_pair_count": row.get("total_occlusion", 0),
                    "by_vhh_region_pair_count": {"cdr3": row.get("cdr3_occlusion", 0)},
                    "cdr3_fraction": row.get("cdr3_fraction", 0),
                },
            }
            count += classify_geometry(proxy, scale) == "A"
        output.append({"threshold_scale": scale, "a_pose_count": count, "pose_score_count": len(pose_rows)})
    write_tsv(path, output, ["threshold_scale", "a_pose_count", "pose_score_count"])


def aggregate(
    protocol_path: Path,
    jobs_path: Path,
    results_path: Path,
    out_path: Path,
    expected_total_jobs: int | None = None,
    allow_synthetic_results: bool = False,
) -> dict[str, Any]:
    protocol_path = protocol_path.resolve()
    root = protocol_path.resolve().parents[1]
    jobs_path = jobs_path if jobs_path.is_absolute() else root / jobs_path
    results_path = results_path if results_path.is_absolute() else root / results_path
    out_path = out_path if out_path.is_absolute() else root / out_path
    protocol = read_json(protocol_path)
    job_rows = load_rows(jobs_path)
    default_results = root / "reports/job_results.tsv"
    report_dir = out_path.parent
    pose_path = report_dir / "pose_scores.tsv"
    if allow_synthetic_results:
        result_rows = load_rows(results_path)
    else:
        result_rows = collect_results(root, job_rows, results_path, pose_path) if job_rows else []
    pose_rows = load_rows(pose_path)
    result_by_job = {row["job_id"]: row for row in result_rows if row.get("job_id")}
    validation_path = report_dir / "PROTOCOL_VALIDATION.json"
    validation = validate_protocol(protocol_path, jobs_path, validation_path, expected_total_jobs)
    expected_jobs = expected_total_jobs or int(protocol["docking"]["expected_total_jobs"])
    gates = {
        "artifacts_present": evaluate_artifacts(job_rows, result_rows),
        "manifest_bound_pose_evidence": evaluate_lineage_and_pose_evidence(job_rows, result_rows),
        "protocol_validation": gate(validation["status"], [name for name, value in validation["gates"].items() if value["status"] != PASS]),
        "all_jobs_terminal": evaluate_completion(result_rows, expected_jobs),
    }
    if job_rows and result_rows:
        gates.update(
            {
                "controls_47_same_protocol": evaluate_controls(job_rows, int(protocol["controls"]["expected_count"])),
                "successful_seeds_per_entity_conformation": evaluate_successful_seeds(
                    job_rows, result_by_job, int(protocol["stability_gate"]["minimum_successful_seeds_per_entity_conformation"])
                ),
                "complete_2x2_scoring": evaluate_complete_matrix(result_rows),
                "positive_controls_not_e_only": evaluate_positive_controls(result_rows),
                "destructive_alanine_a_flagged": evaluate_disruptive_flags(result_rows),
            }
        )
    write_control_drift(report_dir / "control_drift.tsv", result_rows)
    write_threshold_sensitivity(report_dir / "threshold_sensitivity.tsv", pose_rows)
    lock_path = root / "PROTOCOL_LOCK.json"
    final_lock = read_json(lock_path, {})
    payload = {
        "status": overall_status(gates),
        "evidence_mode": "synthetic_test_only" if allow_synthetic_results else "production_pose_backed",
        "protocol_id": protocol.get("protocol_id"),
        "protocol_core_sha256": validation["gates"]["core_lock"].get("protocol_core_sha256", ""),
        "protocol_lock_sha256": final_lock.get("protocol_lock_sha256", ""),
        "protocol_lock_file_sha256": sha256_file(lock_path) if lock_path.is_file() else "",
        "job_manifest_sha256": sha256_file(jobs_path) if jobs_path.is_file() else "",
        "job_set_hash": validation.get("job_set_hash", ""),
        "job_count": len(job_rows),
        "result_count": len(result_rows),
        "pose_score_count": len(pose_rows),
        "gates": gates,
        "reports": {
            "protocol_validation": str(validation_path),
            "job_results": str(results_path),
            "pose_scores": str(pose_path),
            "control_drift": str(report_dir / "control_drift.tsv"),
            "threshold_sensitivity": str(report_dir / "threshold_sensitivity.tsv"),
        },
    }
    write_json(out_path, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="config/protocol_spec.json")
    parser.add_argument("--jobs", default="manifests/docking_jobs.tsv")
    parser.add_argument("--results", default="reports/job_results.tsv")
    parser.add_argument("--out", default="reports/EVALUATOR_STABLE.json")
    parser.add_argument("--expected-total-jobs", type=int)
    parser.add_argument("--allow-synthetic-results", action="store_true", help="Tests only; guard_next_generation rejects this mode")
    args = parser.parse_args(argv)
    payload = aggregate(
        Path(args.protocol),
        Path(args.jobs),
        Path(args.results),
        Path(args.out),
        args.expected_total_jobs,
        args.allow_synthetic_results,
    )
    print(json.dumps({"status": payload["status"], "out": args.out}, sort_keys=True))
    return 0 if payload["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
