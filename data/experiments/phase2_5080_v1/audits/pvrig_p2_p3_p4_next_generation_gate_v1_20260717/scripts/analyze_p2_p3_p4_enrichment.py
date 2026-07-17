#!/usr/bin/env python3
"""Analyze P2/P3/P4 robust-A enrichment inside the frozen 128 panel."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import read_json, sha256_file, write_json, write_tsv

PASS = "PASS"
FAIL = "FAIL"
NOT_READY = "NOT_READY"
SUCCESS_STATES = {"SUCCESS", "PASS", "PASSED", "COMPLETE", "COMPLETED", "DONE"}
DEFAULT_CONFIG = "config/next_generation_gate_spec.json"
PHASE_RE = re.compile(r"(?:^|_)P([1-6])(?:_|$)")


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [{key: "" if value is None else value for key, value in row.items()} for row in csv.DictReader(handle, delimiter="\t")]


def resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def phase_from_candidate(row: dict[str, str]) -> str:
    for value in (row.get("arm_id", ""), row.get("candidate_id", ""), row.get("entity_id", "")):
        match = PHASE_RE.search(value)
        if match:
            return f"P{match.group(1)}"
    return ""


def is_success(row: dict[str, str]) -> bool:
    return row.get("state", "").upper() in SUCCESS_STATES


def to_float(value: str, default: float | None = None) -> float | None:
    try:
        if value == "" or value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def preflight(root: Path, config: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    inputs = config["inputs"]
    paths = {name: resolve(root, path) for name, path in inputs.items()}
    reasons = [f"missing_{name}:{path}" for name, path in paths.items() if not path.is_file()]
    if reasons:
        return reasons, {"paths": {key: str(value) for key, value in paths.items()}}

    evaluator = read_json(paths["evaluator"], {})
    core_lock = read_json(paths["protocol_core_lock"], {})
    lock = read_json(paths["protocol_lock"], {})
    manifest_sha = sha256_file(paths["job_manifest"])
    candidates_sha = sha256_file(paths["candidates"])
    job_results_sha = sha256_file(paths["job_results"])
    pose_scores_sha = sha256_file(paths["pose_scores"])
    evaluator_sha = sha256_file(paths["evaluator"])
    core_lock_file_sha = sha256_file(paths["protocol_core_lock"])
    lock_file_sha = sha256_file(paths["protocol_lock"])
    bindings = {
        "evaluator_file_sha256": evaluator_sha,
        "evaluator_evidence_mode": evaluator.get("evidence_mode", ""),
        "evaluator_unlockable": evaluator.get("unlockable", False),
        "protocol_core_lock_file_sha256": core_lock_file_sha,
        "protocol_core_sha256": lock.get("protocol_core_sha256", ""),
        "protocol_lock_sha256": lock.get("protocol_lock_sha256", ""),
        "protocol_lock_file_sha256": lock_file_sha,
        "job_manifest_sha256": manifest_sha,
        "candidates_sha256": candidates_sha,
        "job_results_sha256": job_results_sha,
        "pose_scores_sha256": pose_scores_sha,
        "evaluator_reported_protocol_core_sha256": evaluator.get("protocol_core_sha256", ""),
        "evaluator_reported_protocol_lock_sha256": evaluator.get("protocol_lock_sha256", ""),
        "evaluator_reported_job_manifest_sha256": evaluator.get("job_manifest_sha256", ""),
        "evaluator_reported_candidates_sha256": evaluator.get("candidates_sha256", ""),
        "evaluator_reported_job_results_sha256": evaluator.get("job_results_sha256", ""),
        "evaluator_reported_pose_scores_sha256": evaluator.get("pose_scores_sha256", ""),
    }

    if evaluator.get("status") != PASS:
        reasons.append(f"evaluator_status_not_pass:{evaluator.get('status', 'MISSING')}")
    if evaluator.get("evidence_mode") != "production_pose_backed":
        reasons.append(f"evaluator_evidence_mode_not_production:{evaluator.get('evidence_mode', 'MISSING')}")
    if evaluator.get("unlockable") is not True:
        reasons.append("evaluator_not_unlockable")
    if not evaluator.get("gates"):
        reasons.append("evaluator_gates_missing")
    elif any(item.get("status") != PASS for item in evaluator.get("gates", {}).values()):
        reasons.append("one_or_more_evaluator_gates_not_pass")
    if lock.get("status") != "LOCKED":
        reasons.append(f"protocol_lock_status_not_locked:{lock.get('status', 'MISSING')}")
    if core_lock.get("status") != "CORE_LOCKED":
        reasons.append(f"protocol_core_lock_status_not_locked:{core_lock.get('status', 'MISSING')}")
    if core_lock_file_sha != lock.get("core_lock_sha256"):
        reasons.append("protocol_core_lock_file_sha256_mismatch")
    if core_lock.get("protocol_core_sha256") != lock.get("protocol_core_sha256"):
        reasons.append("protocol_core_lock_sha256_mismatch")
    if evaluator.get("protocol_core_sha256") != lock.get("protocol_core_sha256"):
        reasons.append("protocol_core_sha256_mismatch")
    if evaluator.get("protocol_lock_sha256") != lock.get("protocol_lock_sha256"):
        reasons.append("protocol_lock_sha256_mismatch")
    if evaluator.get("protocol_lock_file_sha256") != lock_file_sha:
        reasons.append("protocol_lock_file_sha256_mismatch")
    if evaluator.get("job_manifest_sha256") != lock.get("job_manifest_sha256") or manifest_sha != lock.get("job_manifest_sha256"):
        reasons.append("job_manifest_sha256_mismatch")
    for key, observed in (
        ("candidates_sha256", candidates_sha),
        ("job_results_sha256", job_results_sha),
        ("pose_scores_sha256", pose_scores_sha),
    ):
        if evaluator.get(key) != observed:
            reasons.append(f"evaluator_{key}_mismatch")
    if evaluator.get("protocol_core_lock_file_sha256") != core_lock_file_sha:
        reasons.append("evaluator_protocol_core_lock_file_sha256_mismatch")
    return reasons, {"paths": {key: str(value) for key, value in paths.items()}, "bindings": bindings}


def candidate_robust_a(
    candidate_id: str,
    conformations: set[str],
    rows: list[dict[str, str]],
    min_success: int,
    min_support: int,
    min_pose_models: int,
    consensus_min: float,
    strict_a_fraction_min: float,
) -> tuple[bool | None, dict[str, Any]]:
    by_conf: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_conf[row.get("conformation", "")].append(row)
    details: dict[str, Any] = {}
    for conformation in sorted(conformations):
        conf_rows = by_conf.get(conformation, [])
        success_rows = [row for row in conf_rows if is_success(row)]
        success_seeds = {row.get("seed", "") for row in success_rows if row.get("seed", "")}
        if len(success_seeds) < min_success:
            details[conformation] = {
                "successful_seed_count": len(success_seeds),
                "supporting_a_a_seed_count": 0,
                "status": "not_ready",
            }
            return None, details
        support_seeds: set[str] = set()
        for row in success_rows:
            if row.get("native_class", "").upper() != "A" or row.get("cross_class", "").upper() != "A":
                continue
            pose_models = to_float(row.get("pose_score_model_count", ""), None)
            if pose_models is None or pose_models < min_pose_models:
                continue
            if "model_pair_consensus_fraction" in row:
                fraction = to_float(row.get("model_pair_consensus_fraction", ""), None)
                if fraction is None or fraction < consensus_min:
                    continue
            strict_a_fraction = to_float(row.get("model_strict_a_fraction", ""), None)
            if strict_a_fraction is None or strict_a_fraction < strict_a_fraction_min:
                continue
            support_seeds.add(row.get("seed", ""))
        details[conformation] = {
            "successful_seed_count": len(success_seeds),
            "supporting_a_a_seed_count": len(support_seeds),
            "status": "pass" if len(support_seeds) >= min_support else "fail",
        }
        if len(support_seeds) < min_support:
            return False, details
    return True, details


def wilson(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    phat = successes / n
    denom = 1.0 + z * z / n
    center = (phat + z * z / (2.0 * n)) / denom
    half = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * n)) / n) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def fisher_greater(a: int, b: int, c: int, d: int) -> float:
    row1 = a + b
    row2 = c + d
    col1 = a + c
    total = row1 + row2
    if total == 0:
        return 1.0
    denom = math.comb(total, row1)
    high = min(row1, col1)
    return min(1.0, sum(math.comb(col1, x) * math.comb(total - col1, row1 - x) / denom for x in range(a, high + 1)))


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running = 0.0
    m = len(ordered)
    for index, (phase, p_value) in enumerate(ordered):
        running = max(running, min(1.0, p_value * (m - index)))
        adjusted[phase] = running
    return adjusted


def rate(successes: int, n: int) -> float:
    return successes / n if n else 0.0


def analyze(root: Path, config_path: Path, json_out: Path | None = None, tsv_out: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    config_path = resolve(root, config_path)
    config = read_json(config_path)
    inputs = config["inputs"]
    outputs = config["outputs"]
    json_out = resolve(root, json_out or outputs["json"])
    tsv_out = resolve(root, tsv_out or outputs["tsv"])

    preflight_reasons, metadata = preflight(root, config)
    metadata["gate_spec_file_sha256"] = sha256_file(config_path)
    if preflight_reasons:
        payload = build_payload(NOT_READY, preflight_reasons, config, metadata, [], [])
        write_outputs(json_out, tsv_out, payload, [])
        return payload

    candidates = read_tsv(resolve(root, inputs["candidates"]))
    results = read_tsv(resolve(root, inputs["job_results"]))
    jobs = read_tsv(resolve(root, inputs["job_manifest"]))
    if not candidates or not results or not jobs:
        reasons = []
        if not candidates:
            reasons.append("candidate_table_missing_or_empty")
        if not results:
            reasons.append("job_results_missing_or_empty")
        if not jobs:
            reasons.append("job_manifest_missing_or_empty")
        payload = build_payload(NOT_READY, reasons, config, metadata, [], [])
        write_outputs(json_out, tsv_out, payload, [])
        return payload

    candidate_ids = {row.get("candidate_id", "") for row in candidates if row.get("candidate_id")}
    panel_contract = config["panel_contract"]
    panel_reasons: list[str] = []
    if len(candidates) != int(panel_contract["expected_candidate_count"]):
        panel_reasons.append(
            f"candidate_count_mismatch:{len(candidates)}:{panel_contract['expected_candidate_count']}"
        )
    if len(candidate_ids) != len(candidates):
        panel_reasons.append("candidate_ids_blank_or_duplicate")
    conformations = {row.get("conformation", "") for row in jobs if row.get("entity_type") == "candidate" and row.get("conformation")}
    result_by_entity: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in results:
        if row.get("entity_type") == "candidate" and row.get("entity_id") in candidate_ids:
            result_by_entity[row["entity_id"]].append(row)

    robust = config["robust_a_definition"]
    min_success = int(robust["minimum_successful_seeds_per_conformation"])
    min_support = int(robust["minimum_supporting_a_a_seeds_per_conformation"])
    min_pose_models = int(robust["minimum_pose_models_per_supporting_seed"])
    consensus_min = float(robust["model_pair_consensus_fraction_min"])
    strict_a_fraction_min = float(robust["model_strict_a_fraction_min"])
    candidate_calls: dict[str, dict[str, Any]] = {}
    phase_totals: dict[str, int] = defaultdict(int)
    phase_evaluable: dict[str, int] = defaultdict(int)
    phase_robust: dict[str, int] = defaultdict(int)
    readiness_reasons: list[str] = panel_reasons

    for row in candidates:
        candidate_id = row.get("candidate_id", "")
        phase = phase_from_candidate(row)
        if not candidate_id or not phase:
            readiness_reasons.append(f"candidate_phase_unparseable:{candidate_id or 'MISSING'}")
            continue
        phase_totals[phase] += 1
        call, details = candidate_robust_a(
            candidate_id,
            conformations,
            result_by_entity.get(candidate_id, []),
            min_success,
            min_support,
            min_pose_models,
            consensus_min,
            strict_a_fraction_min,
        )
        candidate_calls[candidate_id] = {"phase": phase, "robust_A": call, "conformations": details}
        if call is None:
            continue
        phase_evaluable[phase] += 1
        phase_robust[phase] += int(call)

    expected_phase_counts = {str(key): int(value) for key, value in panel_contract["expected_phase_counts"].items()}
    for phase, expected_count in sorted(expected_phase_counts.items()):
        if phase_totals[phase] != expected_count:
            readiness_reasons.append(f"phase_count_mismatch:{phase}:{phase_totals[phase]}:{expected_count}")

    targets = list(config["phases"]["targets"])
    comparator_phases = set(config["phases"]["comparator_pool"])
    comparator_n = sum(phase_evaluable[phase] for phase in comparator_phases)
    comparator_success = sum(phase_robust[phase] for phase in comparator_phases)
    comparator_total = sum(phase_totals[phase] for phase in comparator_phases)
    comparator_coverage = comparator_n / comparator_total if comparator_total else 0.0
    thresholds = config["thresholds"]

    rows: list[dict[str, Any]] = []
    p_values: dict[str, float] = {}
    for phase in targets:
        a = phase_robust[phase]
        n = phase_evaluable[phase]
        b = n - a
        c = comparator_success
        d = comparator_n - comparator_success
        p_value = fisher_greater(a, b, c, d) if n and comparator_n else 1.0
        p_values[phase] = p_value
        target_rate = rate(a, n)
        comp_rate = rate(c, comparator_n)
        target_ci = wilson(a, n)
        comp_ci = wilson(c, comparator_n)
        risk_difference = target_rate - comp_rate
        risk_ratio = math.inf if comp_rate == 0.0 and target_rate > 0.0 else (target_rate / comp_rate if comp_rate > 0.0 else 0.0)
        coverage = n / phase_totals[phase] if phase_totals[phase] else 0.0
        rows.append(
            {
                "phase": phase,
                "target_total_candidates": phase_totals[phase],
                "target_evaluable_n": n,
                "target_robust_A_n": a,
                "target_robust_A_rate": target_rate,
                "target_wilson95_low": target_ci[0],
                "target_wilson95_high": target_ci[1],
                "comparator_phases": ",".join(config["phases"]["comparator_pool"]),
                "comparator_total_candidates": comparator_total,
                "comparator_evaluable_n": comparator_n,
                "comparator_robust_A_n": c,
                "comparator_robust_A_rate": comp_rate,
                "comparator_wilson95_low": comp_ci[0],
                "comparator_wilson95_high": comp_ci[1],
                "target_coverage": coverage,
                "comparator_coverage": comparator_coverage,
                "risk_difference": risk_difference,
                "risk_ratio": risk_ratio,
                "fisher_exact_p_greater": p_value,
            }
        )

    adjusted = holm_adjust(p_values)
    eligible_phases: list[str] = []
    coverage_reasons: list[str] = []
    for row in rows:
        phase = str(row["phase"])
        row["holm_adjusted_p"] = adjusted[phase]
        enough = (
            int(row["target_evaluable_n"]) >= int(thresholds["minimum_phase_n"])
            and int(row["comparator_evaluable_n"]) >= int(thresholds["minimum_comparator_n"])
            and float(row["target_coverage"]) >= float(thresholds["minimum_coverage_fraction"])
            and float(row["comparator_coverage"]) >= float(thresholds["minimum_coverage_fraction"])
        )
        if not enough:
            coverage_reasons.append(f"{phase}:coverage_or_n_below_threshold")
        passes = (
            enough
            and float(row["target_robust_A_rate"]) >= float(thresholds["minimum_target_robust_a_rate"])
            and float(row["risk_difference"]) >= float(thresholds["minimum_risk_difference"])
            and float(row["risk_ratio"]) >= float(thresholds["minimum_risk_ratio"])
            and float(row["holm_adjusted_p"]) <= float(thresholds["maximum_holm_adjusted_p"])
        )
        row["eligible"] = str(passes).lower()
        if passes:
            eligible_phases.append(phase)

    if readiness_reasons or coverage_reasons:
        status = NOT_READY
    else:
        status = PASS if eligible_phases else FAIL
    reasons = readiness_reasons + ([] if eligible_phases else coverage_reasons)
    if status == FAIL:
        reasons.append("complete_production_data_no_reliable_p2_p3_p4_enrichment")
    payload = build_payload(status, reasons, config, metadata, rows, eligible_phases)
    payload["candidate_call_counts"] = {
        "total_candidates": len(candidates),
        "evaluable_candidates": sum(phase_evaluable.values()),
        "robust_A_candidates": sum(phase_robust.values()),
        "not_ready_candidates": sum(1 for item in candidate_calls.values() if item["robust_A"] is None),
    }
    write_outputs(json_out, tsv_out, payload, rows)
    return payload


def clean_number(value: Any) -> Any:
    if isinstance(value, float):
        if math.isinf(value):
            return "Infinity"
        if math.isnan(value):
            return None
        return round(value, 10)
    return value


def build_payload(
    status: str,
    reasons: list[str],
    config: dict[str, Any],
    metadata: dict[str, Any],
    phase_rows: list[dict[str, Any]],
    eligible_phases: list[str],
) -> dict[str, Any]:
    return {
        "status": status,
        "unlockable": status == PASS,
        "evidence_mode": metadata.get("bindings", {}).get("evaluator_evidence_mode", "unverified"),
        "reasons": sorted(set(reasons)),
        "gate_id": config.get("gate_id"),
        "inference_scope": config.get("inference_scope"),
        "eligible_phases": eligible_phases,
        "thresholds": config.get("thresholds", {}),
        "robust_a_definition": config.get("robust_a_definition", {}),
        "bindings": metadata.get("bindings", {}),
        "gate_spec_file_sha256": metadata.get("gate_spec_file_sha256", ""),
        "paths": metadata.get("paths", {}),
        "phase_results": [{key: clean_number(value) for key, value in row.items()} for row in phase_rows],
    }


def write_outputs(json_out: Path, tsv_out: Path, payload: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    write_json(json_out, payload)
    fields = [
        "phase",
        "target_total_candidates",
        "target_evaluable_n",
        "target_robust_A_n",
        "target_robust_A_rate",
        "target_wilson95_low",
        "target_wilson95_high",
        "comparator_phases",
        "comparator_total_candidates",
        "comparator_evaluable_n",
        "comparator_robust_A_n",
        "comparator_robust_A_rate",
        "comparator_wilson95_low",
        "comparator_wilson95_high",
        "target_coverage",
        "comparator_coverage",
        "risk_difference",
        "risk_ratio",
        "fisher_exact_p_greater",
        "holm_adjusted_p",
        "eligible",
    ]
    serial_rows = [{key: clean_number(row.get(key, "")) for key in fields} for row in rows]
    write_tsv(tsv_out, serial_rows, fields)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path, default=Path(DEFAULT_CONFIG))
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--tsv-out", type=Path)
    args = parser.parse_args(argv)
    payload = analyze(args.root, args.config, args.json_out, args.tsv_out)
    print(json.dumps({"status": payload["status"], "eligible_phases": payload.get("eligible_phases", [])}, sort_keys=True))
    return 0 if payload["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
