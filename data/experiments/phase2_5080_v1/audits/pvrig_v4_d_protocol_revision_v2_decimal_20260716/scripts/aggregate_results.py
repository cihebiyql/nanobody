#!/usr/bin/env python3
"""Collect pose evidence, aggregate all jobs, and enforce evaluator stability."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
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


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def pair_label(native_class: str, cross_class: str, supported_classes: set[str] | None = None) -> str:
    supported = supported_classes or {"A", "B"}
    native = native_class.upper()
    cross = cross_class.upper()
    if native == "A" and cross == "A":
        return "STRICT_A"
    if native in supported and cross in supported:
        return "SUPPORTED_AB"
    return "OTHER"


def model_robustness(rows: list[dict[str, Any]], dock_conformation: str) -> dict[str, Any]:
    by_model: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_model[str(row["model"])][str(row["scoring_reference"])] = row
    complete = [refs for refs in by_model.values() if set(refs) == {"8x6b", "9e6y"}]
    if not complete:
        return {
            "complete_model_count": 0,
            "pair_consensus_fraction": 0.0,
            "native_cross_support_agreement_fraction": 0.0,
            "strict_a_fraction": 0.0,
        }
    other = "9e6y" if dock_conformation == "8x6b" else "8x6b"
    labels = [
        pair_label(refs[dock_conformation]["geometry_class"], refs[other]["geometry_class"])
        for refs in complete
    ]
    support_agreement = [
        (refs[dock_conformation]["geometry_class"] in {"A", "B"})
        == (refs[other]["geometry_class"] in {"A", "B"})
        for refs in complete
    ]
    counts = Counter(labels)
    return {
        "complete_model_count": len(complete),
        "pair_consensus_fraction": max(counts.values()) / len(labels),
        "native_cross_support_agreement_fraction": sum(support_agreement) / len(support_agreement),
        "strict_a_fraction": counts.get("STRICT_A", 0) / len(labels),
    }


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
        robustness = model_robustness(pose_rows, job["conformation"]) if pose_rows else model_robustness([], job["conformation"])
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
                "pose_score_model_count": robustness["complete_model_count"],
                "pose_backed_2x2": str(bool(representative)).lower(),
                "representative_model": native.get("model", ""),
                "haddock_score": native.get("haddock_score", ""),
                "air_energy": native.get("air_energy", ""),
                "native_class": native.get("geometry_class", ""),
                "cross_class": cross.get("geometry_class", ""),
                "representative_pair_label": pair_label(
                    str(native.get("geometry_class", "")), str(cross.get("geometry_class", ""))
                ) if representative else "",
                "model_pair_consensus_fraction": round(float(robustness["pair_consensus_fraction"]), 6),
                "model_native_cross_support_agreement_fraction": round(
                    float(robustness["native_cross_support_agreement_fraction"]), 6
                ),
                "model_strict_a_fraction": round(float(robustness["strict_a_fraction"]), 6),
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


def defer_until_complete(completion: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    if completion["status"] == PASS:
        return observed
    return gate(NOT_READY, ["awaiting_all_jobs_terminal"], partial_observation=observed)


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
    successful = [row for row in result_rows if is_success(row)]
    if not successful:
        return gate(NOT_READY, ["no_successful_pose_backed_jobs"], successful_jobs=0)
    missing = [row["job_id"] for row in successful if not row.get("native_class") or not row.get("cross_class")]
    return gate(
        PASS if not missing else FAIL,
        [f"incomplete_native_cross:{job_id}" for job_id in missing],
        successful_jobs=len(successful),
    )


def evaluate_model_robustness(result_rows: list[dict[str, str]], spec: dict[str, Any]) -> dict[str, Any]:
    controls = [row for row in result_rows if entity_type(row) == "control" and is_success(row)]
    if not controls:
        return gate(NOT_READY, ["no_successful_control_jobs"], successful_control_jobs=0)
    completion = spec["completion"]
    reproducibility = spec["reproducibility"]
    minimum_models = int(completion["minimum_pose_models_per_successful_job"])
    minimum_consensus = float(reproducibility["minimum_model_pair_consensus_fraction"])
    minimum_agreement = float(reproducibility["minimum_model_native_cross_support_agreement_fraction"])
    robust = [
        row
        for row in controls
        if int(as_float(row.get("pose_score_model_count"))) >= minimum_models
        and as_float(row.get("model_pair_consensus_fraction")) >= minimum_consensus
        and as_float(row.get("model_native_cross_support_agreement_fraction")) >= minimum_agreement
    ]
    observed = len(robust) / len(controls)
    required = float(reproducibility["minimum_robust_control_job_fraction"])
    reasons = [] if observed >= required else [f"robust_control_job_fraction_below_{required}:{observed:.6f}"]
    return gate(
        PASS if not reasons else FAIL,
        reasons,
        successful_control_jobs=len(controls),
        robust_control_jobs=len(robust),
        robust_control_job_fraction=round(observed, 6),
        required_fraction=required,
        minimum_pose_models=minimum_models,
    )


def evaluate_successful_job_model_minimum(result_rows: list[dict[str, str]], spec: dict[str, Any]) -> dict[str, Any]:
    successful = [row for row in result_rows if is_success(row)]
    if not successful:
        return gate(NOT_READY, ["no_successful_jobs"], successful_jobs=0)
    minimum = int(spec["completion"]["minimum_pose_models_per_successful_job"])
    deficient = [
        row["job_id"]
        for row in successful
        if int(as_float(row.get("pose_score_model_count"))) < minimum
    ]
    return gate(
        PASS if not deficient else FAIL,
        [f"successful_job_below_{minimum}_pose_models:{job_id}" for job_id in deficient],
        successful_jobs=len(successful),
        deficient_jobs=len(deficient),
        minimum_pose_models=minimum,
    )


def seed_label_groups(result_rows: list[dict[str, str]]) -> dict[tuple[str, str], list[str]]:
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in result_rows:
        if not is_success(row):
            continue
        grouped[(entity_id(row), row.get("conformation", ""))].append(
            pair_label(row.get("native_class", ""), row.get("cross_class", ""))
        )
    return grouped


def evaluate_control_seed_reproducibility(result_rows: list[dict[str, str]], spec: dict[str, Any]) -> dict[str, Any]:
    control_ids = {entity_id(row) for row in result_rows if entity_type(row) == "control"}
    expected_groups = {(control_id, conformation) for control_id in control_ids for conformation in ("8x6b", "9e6y")}
    grouped = seed_label_groups([row for row in result_rows if entity_type(row) == "control"])
    minimum = int(spec["completion"]["minimum_successful_seeds_per_entity_conformation"])
    waiting = [key for key in sorted(expected_groups) if len(grouped.get(key, [])) < minimum]
    if waiting:
        return gate(
            NOT_READY,
            [f"incomplete_control_seed_group:{entity}:{conformation}" for entity, conformation in waiting],
            expected_control_entity_conformations=len(expected_groups),
        )
    consensus = []
    for key in sorted(expected_groups):
        counts = Counter(grouped[key])
        consensus.append(max(counts.values()) >= minimum)
    observed = sum(consensus) / len(consensus) if consensus else 0.0
    required = float(spec["reproducibility"]["minimum_control_entity_conformation_seed_consensus_fraction"])
    reasons = [] if observed >= required else [f"control_seed_consensus_fraction_below_{required}:{observed:.6f}"]
    return gate(
        PASS if not reasons else FAIL,
        reasons,
        expected_control_entity_conformations=len(expected_groups),
        consensus_entity_conformations=sum(consensus),
        consensus_fraction=round(observed, 6),
        required_fraction=required,
    )


def robust_entities(
    result_rows: list[dict[str, str]], control_class_name: str, accepted_labels: set[str], minimum: int
) -> tuple[set[str], set[str], bool]:
    rows = [row for row in result_rows if row.get("control_class") == control_class_name]
    entities = {entity_id(row) for row in rows}
    grouped = seed_label_groups(rows)
    complete = True
    robust: set[str] = set()
    for entity in sorted(entities):
        supported_by_conformation = []
        for conformation in ("8x6b", "9e6y"):
            labels = grouped.get((entity, conformation), [])
            if len(labels) < minimum:
                complete = False
            supported_by_conformation.append(sum(label in accepted_labels for label in labels) >= minimum)
        if all(supported_by_conformation):
            robust.add(entity)
    return entities, robust, complete


def evaluate_positive_controls(result_rows: list[dict[str, str]], spec: dict[str, Any]) -> dict[str, Any]:
    minimum = int(spec["completion"]["minimum_successful_seeds_per_entity_conformation"])
    entities, robust, complete = robust_entities(
        result_rows, "positive_control", {"STRICT_A", "SUPPORTED_AB"}, minimum
    )
    if not entities or not complete:
        return gate(
            NOT_READY,
            ["positive_control_matrix_incomplete" if entities else "positive_controls_missing"],
            positive_entities=len(entities),
            robust_supported_entities=len(robust),
        )
    observed = len(robust) / len(entities)
    required = float(spec["control_calibration"]["minimum_positive_robust_supported_entity_fraction"])
    reasons = [] if observed >= required else [f"positive_robust_supported_fraction_below_{required}:{observed:.6f}"]
    return gate(
        PASS if not reasons else FAIL,
        reasons,
        positive_entities=len(entities),
        robust_supported_entities=len(robust),
        robust_supported_fraction=round(observed, 6),
        required_fraction=required,
    )


def evaluate_destructive_controls(result_rows: list[dict[str, str]], spec: dict[str, Any]) -> dict[str, Any]:
    minimum = int(spec["completion"]["minimum_successful_seeds_per_entity_conformation"])
    entities, robust, complete = robust_entities(result_rows, "destructive_alanine", {"STRICT_A"}, minimum)
    if not entities or not complete:
        return gate(
            NOT_READY,
            ["destructive_control_matrix_incomplete" if entities else "destructive_controls_missing"],
            destructive_entities=len(entities),
            robust_strict_a_entities=len(robust),
        )
    observed = len(robust) / len(entities)
    maximum = float(spec["control_calibration"]["maximum_destructive_robust_strict_a_entity_fraction"])
    reasons = [] if observed <= maximum else [f"destructive_robust_strict_a_fraction_above_{maximum}:{observed:.6f}"]
    return gate(
        PASS if not reasons else FAIL,
        reasons,
        destructive_entities=len(entities),
        robust_strict_a_entities=len(robust),
        robust_strict_a_fraction=round(observed, 6),
        maximum_fraction=maximum,
    )


def evaluate_control_native_cross_agreement(result_rows: list[dict[str, str]], spec: dict[str, Any]) -> dict[str, Any]:
    controls = [row for row in result_rows if entity_type(row) == "control" and is_success(row)]
    if not controls:
        return gate(NOT_READY, ["no_successful_control_jobs"])
    disagreements = sum(
        (row.get("native_class") in {"A", "B"}) != (row.get("cross_class") in {"A", "B"})
        for row in controls
    )
    observed = disagreements / len(controls)
    maximum = float(spec["reproducibility"]["maximum_control_native_cross_support_disagreement_fraction"])
    reasons = [] if observed <= maximum else [f"control_native_cross_disagreement_above_{maximum}:{observed:.6f}"]
    return gate(
        PASS if not reasons else FAIL,
        reasons,
        successful_control_jobs=len(controls),
        disagreement_jobs=disagreements,
        disagreement_fraction=round(observed, 6),
        maximum_fraction=maximum,
    )


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


def class_at_scale(row: dict[str, str], scale: float) -> str:
    proxy = {
        "hotspot_overlap": {"full": {"count": row.get("hotspot_overlap", 0)}},
        "vhh_pvrl2_occlusion": {
            "residue_pair_count": row.get("total_occlusion", 0),
            "by_vhh_region_pair_count": {"cdr3": row.get("cdr3_occlusion", 0)},
            "cdr3_fraction": row.get("cdr3_fraction", 0),
        },
    }
    return classify_geometry(proxy, scale)


def threshold_sensitivity_rows(pose_rows: list[dict[str, str]], scales: list[float]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for cohort in ("candidate", "control", "all"):
        selected = pose_rows if cohort == "all" else [row for row in pose_rows if entity_type(row) == cohort]
        by_model: dict[tuple[str, str], dict[str, dict[str, str]]] = defaultdict(dict)
        for row in selected:
            by_model[(row.get("job_id", ""), row.get("model", ""))][row.get("scoring_reference", "")] = row
        complete = [refs for refs in by_model.values() if set(refs) == {"8x6b", "9e6y"}]
        for scale in scales:
            strict_a = sum(
                class_at_scale(refs["8x6b"], scale) == "A" and class_at_scale(refs["9e6y"], scale) == "A"
                for refs in complete
            )
            output.append(
                {
                    "threshold_scale": scale,
                    "cohort": cohort,
                    "model_pair_count": len(complete),
                    "strict_a_pair_count": strict_a,
                    "strict_a_pair_rate": round(strict_a / len(complete), 6) if complete else 0.0,
                }
            )
    return output


def write_threshold_sensitivity(path: Path, rows: list[dict[str, Any]]) -> None:
    write_tsv(
        path,
        rows,
        ["threshold_scale", "cohort", "model_pair_count", "strict_a_pair_count", "strict_a_pair_rate"],
    )


def evaluate_threshold_sensitivity(rows: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    config = spec["threshold_sensitivity"]
    cohort = str(config["cohort"])
    selected = {float(row["threshold_scale"]): row for row in rows if row["cohort"] == cohort}
    scales = [float(value) for value in config["scales"]]
    if any(scale not in selected or int(selected[scale]["model_pair_count"]) == 0 for scale in scales):
        return gate(NOT_READY, [f"threshold_sensitivity_missing_pose_pairs:{cohort}"])
    baseline = as_float(selected[1.0]["strict_a_pair_rate"])
    deltas = {str(scale): abs(as_float(selected[scale]["strict_a_pair_rate"]) - baseline) for scale in scales if scale != 1.0}
    maximum = float(config["maximum_absolute_strict_a_rate_delta_from_scale_1"])
    reasons = [f"strict_a_rate_delta_above_{maximum}:scale_{scale}:{delta:.6f}" for scale, delta in deltas.items() if delta > maximum]
    return gate(
        PASS if not reasons else FAIL,
        reasons,
        cohort=cohort,
        baseline_rate=baseline,
        absolute_rate_deltas={scale: round(delta, 6) for scale, delta in deltas.items()},
        maximum_absolute_delta=maximum,
    )


def aggregate(
    protocol_path: Path,
    jobs_path: Path,
    results_path: Path,
    out_path: Path,
    expected_total_jobs: int | None = None,
    allow_synthetic_results: bool = False,
    stability_spec_path: Path | None = None,
) -> dict[str, Any]:
    protocol_path = protocol_path.resolve()
    root = protocol_path.resolve().parents[1]
    jobs_path = jobs_path if jobs_path.is_absolute() else root / jobs_path
    results_path = results_path if results_path.is_absolute() else root / results_path
    out_path = out_path if out_path.is_absolute() else root / out_path
    protocol = read_json(protocol_path)
    stability_spec_path = stability_spec_path or Path("config/evaluator_stability_gate.json")
    if not stability_spec_path.is_absolute():
        stability_spec_path = root / stability_spec_path
    stability_spec = read_json(stability_spec_path)
    job_rows = load_rows(jobs_path)
    report_dir = out_path.parent
    pose_path = report_dir / "pose_scores.tsv"
    candidates_path = root / "inputs/candidates_290.tsv"
    core_lock_path = root / "PROTOCOL_CORE_LOCK.json"
    if allow_synthetic_results:
        result_rows = load_rows(results_path)
    else:
        result_rows = collect_results(root, job_rows, results_path, pose_path) if job_rows else []
    pose_rows = load_rows(pose_path)
    result_by_job = {row["job_id"]: row for row in result_rows if row.get("job_id")}
    validation_path = report_dir / "PROTOCOL_VALIDATION.json"
    validation = validate_protocol(protocol_path, jobs_path, validation_path, expected_total_jobs)
    expected_jobs = expected_total_jobs or int(protocol["docking"]["expected_total_jobs"])
    completion_gate = evaluate_completion(result_rows, expected_jobs)
    gates = {
        "row_artifacts_present": evaluate_artifacts(job_rows, result_rows),
        "manifest_bound_pose_evidence": evaluate_lineage_and_pose_evidence(job_rows, result_rows),
        "protocol_validation": gate(validation["status"], [name for name, value in validation["gates"].items() if value["status"] != PASS]),
        "all_jobs_terminal": completion_gate,
    }
    if job_rows and result_rows:
        gates.update(
            {
                "controls_47_same_protocol": evaluate_controls(job_rows, int(protocol["controls"]["expected_count"])),
                "minimum_completed_seeds_per_entity_conformation": evaluate_successful_seeds(
                    job_rows,
                    result_by_job,
                    int(stability_spec["completion"]["minimum_successful_seeds_per_entity_conformation"]),
                ),
                "complete_2x2_scoring": defer_until_complete(
                    completion_gate, evaluate_complete_matrix(result_rows)
                ),
                "all_successful_jobs_have_minimum_pose_models": defer_until_complete(
                    completion_gate, evaluate_successful_job_model_minimum(result_rows, stability_spec)
                ),
                "control_model_robustness": defer_until_complete(
                    completion_gate, evaluate_model_robustness(result_rows, stability_spec)
                ),
                "control_seed_class_reproducibility": defer_until_complete(
                    completion_gate, evaluate_control_seed_reproducibility(result_rows, stability_spec)
                ),
                "control_native_cross_support_agreement": defer_until_complete(
                    completion_gate, evaluate_control_native_cross_agreement(result_rows, stability_spec)
                ),
                "positive_control_robust_support": defer_until_complete(
                    completion_gate, evaluate_positive_controls(result_rows, stability_spec)
                ),
                "destructive_control_strict_a_retention": defer_until_complete(
                    completion_gate, evaluate_destructive_controls(result_rows, stability_spec)
                ),
            }
        )
    write_control_drift(report_dir / "control_drift.tsv", result_rows)
    sensitivity_rows = threshold_sensitivity_rows(
        pose_rows, [float(value) for value in stability_spec["threshold_sensitivity"]["scales"]]
    )
    write_threshold_sensitivity(report_dir / "threshold_sensitivity.tsv", sensitivity_rows)
    gates["candidate_threshold_sensitivity"] = defer_until_complete(
        completion_gate, evaluate_threshold_sensitivity(sensitivity_rows, stability_spec)
    )
    lock_path = root / "PROTOCOL_LOCK.json"
    final_lock = read_json(lock_path, {})
    status = overall_status(gates)
    completed_pose_backed_jobs = sum(
        is_success(row) and row.get("pose_backed_2x2", "").lower() == "true" for row in result_rows
    )
    successful_control_entities = len(
        {entity_id(row) for row in result_rows if entity_type(row) == "control" and is_success(row)}
    )
    payload = {
        "status": status,
        "unlockable": status == PASS and not allow_synthetic_results,
        "evidence_mode": "synthetic_test_only" if allow_synthetic_results else "production_pose_backed",
        "protocol_id": protocol.get("protocol_id"),
        "protocol_core_sha256": validation["gates"]["core_lock"].get("protocol_core_sha256", ""),
        "protocol_core_lock_file_sha256": sha256_file(core_lock_path) if core_lock_path.is_file() else "",
        "protocol_lock_sha256": final_lock.get("protocol_lock_sha256", ""),
        "protocol_lock_file_sha256": sha256_file(lock_path) if lock_path.is_file() else "",
        "job_manifest_sha256": sha256_file(jobs_path) if jobs_path.is_file() else "",
        "job_results_sha256": sha256_file(results_path) if results_path.is_file() else "",
        "pose_scores_sha256": sha256_file(pose_path) if pose_path.is_file() else "",
        "candidates_sha256": sha256_file(candidates_path) if candidates_path.is_file() else "",
        "job_set_hash": validation.get("job_set_hash", ""),
        "job_count": len(job_rows),
        "result_count": len(result_rows),
        "pose_score_count": len(pose_rows),
        "completed_pose_backed_jobs": completed_pose_backed_jobs,
        "successful_control_entities": successful_control_entities,
        "stability_gate_spec": str(stability_spec_path),
        "stability_gate_spec_sha256": sha256_file(stability_spec_path),
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
    parser.add_argument("--stability-spec", default="config/evaluator_stability_gate.json")
    args = parser.parse_args(argv)
    payload = aggregate(
        Path(args.protocol),
        Path(args.jobs),
        Path(args.results),
        Path(args.out),
        args.expected_total_jobs,
        args.allow_synthetic_results,
        Path(args.stability_spec),
    )
    enrichment_returncode = None
    if payload["status"] == PASS and payload["evidence_mode"] == "production_pose_backed":
        enrichment = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "analyze_p2_p3_p4_enrichment.py")],
            cwd=Path(args.protocol).resolve().parents[1],
        )
        enrichment_returncode = enrichment.returncode
    if payload["status"] != PASS:
        return_code = 1
        combined_status = payload["status"]
    elif enrichment_returncode not in (None, 0):
        return_code = 2
        combined_status = "STABLE_PASS_ENRICHMENT_NOT_PASS"
    else:
        return_code = 0
        combined_status = "PASS"
    print(
        json.dumps(
            {
                "status": payload["status"],
                "combined_status": combined_status,
                "out": args.out,
                "enrichment_returncode": enrichment_returncode,
            },
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
