#!/usr/bin/env python3
"""Collect and evaluate the frozen V2.4 strict nested whole-parent OOF run.

The evaluator is intentionally post-training and open-development only.  It
does not open or name any sealed evaluation artifact, does not refit a model,
and cannot select a promotion lane after metrics are observed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


CONTRACT_SCHEMA = "pvrig_v2_4_strict_terminal_evaluation_contract_v1"
GRAPH_SCHEMA = "pvrig_v2_4_strict_double_whole_parent_crossfit_plan_v1"
META_SCHEMA = "pvrig_v2_4_outer_meta_prediction_row_v2"
META_ROLE = "OUTER_TEST_META_PREDICTION"
BASE_SCHEMA = "pvrig_v2_4_receptor_base_feature_row_v2"
BASE_ROLE = "OUTER_TEST_BASE_FEATURE"
SEALED = re.compile(r"(^|[/\\._-])v4[/\\._-]?f($|[/\\._-])|test32", re.I)
TARGETS = (
    ("R_8X6B", "prediction_R8"),
    ("R_9E6Y", "prediction_R9"),
    ("R_dual_min", "prediction_R_dual_min"),
)


class EvaluationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvaluationError(message)


def reject_sealed(value: str | Path, context: str) -> None:
    require(not SEALED.search(str(value)), f"sealed_artifact_forbidden:{context}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    require(bool(rows), f"empty_output_rows:{path.name}")
    fields = list(rows[0])
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rankdata(values: Sequence[float]) -> np.ndarray:
    data = np.asarray(values, dtype=np.float64)
    order = np.argsort(data, kind="mergesort")
    ranks = np.empty(len(data), dtype=np.float64)
    start = 0
    while start < len(data):
        end = start + 1
        while end < len(data) and data[order[end]] == data[order[start]]:
            end += 1
        ranks[order[start:end]] = 0.5 * (start + end - 1) + 1.0
        start = end
    return ranks


def spearman(truth: Sequence[float], prediction: Sequence[float]) -> float:
    left, right = rankdata(truth), rankdata(prediction)
    if np.std(left) == 0.0 or np.std(right) == 0.0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def scalar_metrics(truth: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    error = prediction - truth
    return {
        "spearman": spearman(truth, prediction),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
    }


def evaluate_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    require(bool(rows), "cannot_evaluate_empty_rows")
    targets: dict[str, Any] = {}
    for truth_key, prediction_key in TARGETS:
        truth = np.asarray([float(row[truth_key]) for row in rows], dtype=np.float64)
        prediction = np.asarray([float(row[prediction_key]) for row in rows], dtype=np.float64)
        targets[truth_key] = scalar_metrics(truth, prediction)
    sources: dict[str, Any] = {}
    for source in sorted({str(row["teacher_source"]) for row in rows}):
        subset = [row for row in rows if row["teacher_source"] == source]
        sources[source] = {
            truth: scalar_metrics(
                np.asarray([float(row[truth]) for row in subset]),
                np.asarray([float(row[pred]) for row in subset]),
            )
            for truth, pred in TARGETS
        }
    by_parent: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_parent[str(row["parent_framework_cluster"])].append(row)
    parent_macro: dict[str, Any] = {}
    for truth_key, prediction_key in TARGETS:
        maes: list[float] = []
        rmses: list[float] = []
        correlations: list[float] = []
        for subset in by_parent.values():
            truth = np.asarray([float(row[truth_key]) for row in subset], dtype=np.float64)
            prediction = np.asarray([float(row[prediction_key]) for row in subset], dtype=np.float64)
            metric = scalar_metrics(truth, prediction)
            maes.append(metric["mae"])
            rmses.append(metric["rmse"])
            if len(subset) >= 3 and np.std(truth) > 0.0 and np.std(prediction) > 0.0:
                correlations.append(metric["spearman"])
        parent_macro[truth_key] = {
            "macro_mae": float(np.mean(maes)),
            "macro_rmse": float(np.mean(rmses)),
            "macro_within_parent_spearman": float(np.mean(correlations)) if correlations else 0.0,
            "spearman_parent_count": len(correlations),
        }
    folds = {}
    for fold in sorted({int(row["outer_fold"]) for row in rows}):
        subset = [row for row in rows if int(row["outer_fold"]) == fold]
        folds[str(fold)] = {
            truth: scalar_metrics(
                np.asarray([float(row[truth]) for row in subset]),
                np.asarray([float(row[pred]) for row in subset]),
            )
            for truth, pred in TARGETS
        }
    return {"targets": targets, "sources": sources, "parent_macro": parent_macro, "outer_folds": folds}


def load_json(path: Path) -> dict[str, Any]:
    reject_sealed(path, "json_path")
    return json.loads(path.read_text(encoding="utf-8"))


def graph_jobs(graph: Mapping[str, Any], kind: str) -> list[Mapping[str, Any]]:
    return [job for job in graph["jobs"] if job["kind"] == kind]


def lane_fold(job_id: str) -> tuple[str, int]:
    match = re.fullmatch(r"o([0-4])\.(B_TARGET_NO_CONTACT|C_SPLIT_MARGINAL|D_SPLIT_PAIR)\..+", job_id)
    require(match is not None, f"job_identity_invalid:{job_id}")
    return match.group(2), int(match.group(1))


def validate_json_pass(path: Path, context: str) -> dict[str, Any]:
    payload = load_json(path)
    require(str(payload.get("status", "")).startswith("PASS"), f"validation_not_pass:{context}")
    require(payload.get("sealed_evaluation_access_count", 0) == 0, f"sealed_access_nonzero:{context}")
    return payload


def normalize_meta(rows: Sequence[Mapping[str, str]], lane: str, fold: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        require(raw.get("schema_version") == META_SCHEMA, f"meta_schema:{lane}:{fold}")
        require(raw.get("evidence_role") == META_ROLE, f"meta_role:{lane}:{fold}")
        require(int(raw["outer_fold"]) == fold, f"meta_fold:{lane}:{fold}")
        candidate = raw["candidate_id"]
        require(candidate not in seen, f"duplicate_meta_candidate:{lane}:{candidate}")
        seen.add(candidate)
        values = [float(raw[key]) for key in (
            "R_8X6B", "R_9E6Y", "R_dual_min", "prediction_R8", "prediction_R9", "prediction_R_dual_min"
        )]
        require(all(math.isfinite(value) for value in values), f"nonfinite_meta:{lane}:{candidate}")
        require(math.isclose(values[2], min(values[0], values[1]), rel_tol=0.0, abs_tol=1e-12), f"truth_exact_min:{lane}:{candidate}")
        require(math.isclose(values[5], min(values[3], values[4]), rel_tol=0.0, abs_tol=1e-12), f"prediction_exact_min:{lane}:{candidate}")
        output.append({
            "model_id": lane,
            "candidate_id": candidate,
            "teacher_source": raw["teacher_source"],
            "parent_framework_cluster": raw["parent_framework_cluster"],
            "outer_fold": fold,
            "R_8X6B": values[0],
            "R_9E6Y": values[1],
            "R_dual_min": values[2],
            "prediction_R8": values[3],
            "prediction_R9": values[4],
            "prediction_R_dual_min": values[5],
            "meta_model_receipt_sha256": raw["meta_model_receipt_sha256"],
            "source_evidence_sha256": "",
        })
    return output


def normalize_m2(rows: Sequence[Mapping[str, str]], lane: str, fold: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        require(raw.get("schema_version") == BASE_SCHEMA, f"base_schema:{lane}:{fold}")
        require(raw.get("evidence_role") == BASE_ROLE, f"base_role:{lane}:{fold}")
        require(int(raw["outer_fold"]) == fold, f"base_fold:{lane}:{fold}")
        candidate = raw["candidate_id"]
        require(candidate not in seen, f"duplicate_base_candidate:{lane}:{candidate}")
        seen.add(candidate)
        values = [float(raw[key]) for key in ("R_8X6B", "R_9E6Y", "R_dual_min", "M2_R8", "M2_R9")]
        require(all(math.isfinite(value) for value in values), f"nonfinite_base:{lane}:{candidate}")
        require(math.isclose(values[2], min(values[0], values[1]), rel_tol=0.0, abs_tol=1e-12), f"base_truth_exact_min:{lane}:{candidate}")
        output.append({
            "model_id": "M2_FROZEN_ALPHA10",
            "candidate_id": candidate,
            "teacher_source": raw["teacher_source"],
            "parent_framework_cluster": raw["parent_framework_cluster"],
            "outer_fold": fold,
            "R_8X6B": values[0],
            "R_9E6Y": values[1],
            "R_dual_min": values[2],
            "prediction_R8": values[3],
            "prediction_R9": values[4],
            "prediction_R_dual_min": min(values[3], values[4]),
            "meta_model_receipt_sha256": "",
            "source_evidence_sha256": "",
        })
    return output


def keyed(rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        candidate = str(row["candidate_id"])
        require(candidate not in output, f"duplicate_candidate:{candidate}")
        output[candidate] = row
    return output


def same_numeric_predictions(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    fields = (
        "outer_fold", "R_8X6B", "R_9E6Y", "R_dual_min",
        "prediction_R8", "prediction_R9", "prediction_R_dual_min",
    )
    return all(math.isclose(float(left[field]), float(right[field]), rel_tol=0.0, abs_tol=1e-12) for field in fields)


def gate_metrics(metrics: Mapping[str, Any], m2: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    frozen = contract["promotion_gate"]
    target = metrics["targets"]["R_dual_min"]
    source_nonregression = all(
        metrics["sources"][source]["R_dual_min"]["mae"]
        <= m2["sources"][source]["R_dual_min"]["mae"]
        for source in m2["sources"]
    )
    parent_nonregression = (
        metrics["parent_macro"]["R_dual_min"]["macro_mae"]
        <= m2["parent_macro"]["R_dual_min"]["macro_mae"]
    )
    gates = {
        "Rdual_spearman": target["spearman"] >= frozen["required_Rdual_spearman"],
        "Rdual_mae": target["mae"] <= frozen["M2_Rdual_mae_ceiling"],
        "Rdual_rmse": target["rmse"] <= frozen["M2_Rdual_rmse_ceiling"],
        "source_Rdual_mae_nonregression_vs_M2": source_nonregression,
        "parent_macro_Rdual_mae_nonregression_vs_M2": parent_nonregression,
    }
    return {"gates": gates, "all_pass": all(gates.values())}


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    for path, context in ((args.contract, "contract"), (args.job_graph, "job_graph"), (args.runtime_root, "runtime"), (args.output_dir, "output")):
        reject_sealed(path, context)
    contract_path = args.contract.resolve()
    graph_path = args.job_graph.resolve()
    runtime_root = args.runtime_root.resolve()
    output_dir = args.output_dir.resolve()
    require(not output_dir.exists(), "output_dir_preexists")
    contract = load_json(contract_path)
    require(contract.get("schema_version") == CONTRACT_SCHEMA, "contract_schema")
    require(contract.get("status") == "FROZEN_BEFORE_ANY_STRICT_OUTER_META_PREDICTION_EXISTED", "contract_not_frozen")
    require(sha256_file(graph_path) == contract["expected_job_graph_sha256"], "job_graph_hash")
    graph = load_json(graph_path)
    require(graph.get("schema_version") == GRAPH_SCHEMA, "job_graph_schema")
    require(graph.get("sealed_evaluation_access_count") == 0, "graph_sealed_access")
    require(graph.get("prediction_metrics_access_count") == 0, "graph_metrics_access")
    jobs = graph.get("jobs")
    require(isinstance(jobs, list) and len(jobs) == contract["expected_job_count"], "job_count")
    kinds = Counter(job["kind"] for job in jobs)
    require(dict(sorted(kinds.items())) == contract["expected_job_kind_counts"], "job_kind_counts")
    for job in jobs:
        expected = Path(job["expected_result"])
        reject_sealed(expected, f"job_result:{job['job_id']}")
        require(expected.is_file(), f"job_result_missing:{job['job_id']}")
    terminal = load_json(runtime_root / "TERMINAL.json")
    require(terminal == {"returncode": 0, "status": "PASS"}, "runtime_terminal_not_pass")
    launch = load_json(runtime_root / "AUTHORIZED_LAUNCH_RECEIPT.json")
    require(launch.get("status") == "AUTHORIZED_LAUNCH_STARTED", "launch_receipt_status")
    require(launch.get("job_graph_sha256") == contract["expected_job_graph_sha256"], "launch_graph_hash")
    require(launch.get("job_count") == contract["expected_job_count"], "launch_job_count")
    require(launch.get("sealed_evaluation_access_count") == 0, "launch_sealed_access")

    lanes = tuple(contract["frozen_lanes"])
    folds = set(range(int(contract["expected_outer_folds"])))
    meta_jobs = graph_jobs(graph, "CPU_MATERIALIZE_OUTER_TEST_META_PREDICTION")
    meta_validation_jobs = graph_jobs(graph, "CPU_VALIDATE_OUTER_TEST_META_PREDICTION")
    base_jobs = graph_jobs(graph, "CPU_ASSEMBLE_OUTER_TEST_BASE_FEATURE")
    require(len(meta_jobs) == len(meta_validation_jobs) == len(base_jobs) == len(lanes) * len(folds), "outer_artifact_job_count")

    meta_by_identity = {lane_fold(job["job_id"]): Path(job["expected_result"]) for job in meta_jobs}
    meta_validation_by_identity = {lane_fold(job["job_id"]): Path(job["expected_result"]) for job in meta_validation_jobs}
    base_by_identity = {lane_fold(job["job_id"]): Path(job["expected_result"]) for job in base_jobs}
    expected_identities = {(lane, fold) for lane in lanes for fold in folds}
    require(set(meta_by_identity) == set(meta_validation_by_identity) == set(base_by_identity) == expected_identities, "lane_fold_closure")

    lane_rows: dict[str, list[dict[str, Any]]] = {lane: [] for lane in lanes}
    m2_by_lane: dict[str, list[dict[str, Any]]] = {lane: [] for lane in lanes}
    validation_hashes: dict[str, str] = {}
    stack_receipt_hashes: dict[str, str] = {}
    exact_min_violations = 0
    for lane, fold in sorted(expected_identities):
        meta_path = meta_by_identity[(lane, fold)]
        base_path = base_by_identity[(lane, fold)]
        validation_path = meta_validation_by_identity[(lane, fold)]
        validate_json_pass(validation_path, f"{lane}:outer_{fold}")
        validation_hashes[f"{lane}:outer_{fold}"] = sha256_file(validation_path)
        normalized = normalize_meta(read_tsv(meta_path), lane, fold)
        for row in normalized:
            row["source_evidence_sha256"] = sha256_file(meta_path)
            stack_receipt_hashes[str(row["meta_model_receipt_sha256"])] = str(row["meta_model_receipt_sha256"])
        lane_rows[lane].extend(normalized)
        baseline = normalize_m2(read_tsv(base_path), lane, fold)
        for row in baseline:
            row["source_evidence_sha256"] = sha256_file(base_path)
        m2_by_lane[lane].extend(baseline)

    expected_candidates = int(contract["expected_candidate_count"])
    expected_parents = int(contract["expected_parent_count"])
    expected_sources = contract["expected_sources"]
    reference_truth: dict[str, tuple[Any, ...]] | None = None
    for lane in lanes:
        rows = lane_rows[lane]
        indexed = keyed(rows)
        require(len(rows) == len(indexed) == expected_candidates, f"candidate_closure:{lane}")
        require(len({row["parent_framework_cluster"] for row in rows}) == expected_parents, f"parent_closure:{lane}")
        require(Counter(row["teacher_source"] for row in rows) == Counter(expected_sources), f"source_closure:{lane}")
        require({int(row["outer_fold"]) for row in rows} == folds, f"outer_fold_closure:{lane}")
        truth = {
            candidate: (
                row["teacher_source"], row["parent_framework_cluster"], int(row["outer_fold"]),
                float(row["R_8X6B"]), float(row["R_9E6Y"]), float(row["R_dual_min"]),
            )
            for candidate, row in indexed.items()
        }
        if reference_truth is None:
            reference_truth = truth
        else:
            require(truth == reference_truth, f"cross_lane_truth_mismatch:{lane}")

    m2_reference = keyed(m2_by_lane[lanes[0]])
    require(len(m2_reference) == expected_candidates, "M2_candidate_closure")
    for lane in lanes[1:]:
        comparison = keyed(m2_by_lane[lane])
        require(set(comparison) == set(m2_reference), f"M2_cross_lane_candidate_mismatch:{lane}")
        require(all(same_numeric_predictions(m2_reference[c], comparison[c]) for c in m2_reference), f"M2_cross_lane_numeric_mismatch:{lane}")

    m2_rows = list(m2_reference.values())
    metrics = {"M2_FROZEN_ALPHA10": evaluate_rows(m2_rows)}
    metrics.update({lane: evaluate_rows(lane_rows[lane]) for lane in lanes})
    m2_dual = metrics["M2_FROZEN_ALPHA10"]["targets"]["R_dual_min"]
    frozen_gate = contract["promotion_gate"]
    reproduction = {
        "spearman": abs(m2_dual["spearman"] - frozen_gate["frozen_M2_Rdual_spearman"]) <= 1e-12,
        "mae": abs(m2_dual["mae"] - frozen_gate["M2_Rdual_mae_ceiling"]) <= 1e-12,
        "rmse": abs(m2_dual["rmse"] - frozen_gate["M2_Rdual_rmse_ceiling"]) <= 1e-12,
    }
    require(all(reproduction.values()), "M2_exact_reproduction_failed")
    lane_gate_diagnostics = {
        lane: gate_metrics(metrics[lane], metrics["M2_FROZEN_ALPHA10"], contract)
        for lane in lanes
    }
    primary = contract["formal_primary_lane"]
    require(primary == "D_SPLIT_PAIR" and primary in lanes, "formal_primary_lane_invalid")
    primary_pass = lane_gate_diagnostics[primary]["all_pass"]
    status = "PASS_PROMOTE_V2_4_D_SPLIT_PAIR_STRICT_STACK" if primary_pass else "DO_NOT_PROMOTE_V2_4_D_SPLIT_PAIR_STRICT_STACK"

    output_dir.mkdir(parents=True, exist_ok=False)
    artifact_paths: dict[str, Path] = {}
    m2_path = output_dir / "M2_FROZEN_ALPHA10_OOF.tsv"
    write_tsv(m2_path, sorted(m2_rows, key=lambda row: (int(row["outer_fold"]), str(row["candidate_id"]))))
    artifact_paths["M2_FROZEN_ALPHA10_OOF"] = m2_path
    for lane in lanes:
        path = output_dir / f"{lane}_STRICT_OOF.tsv"
        write_tsv(path, sorted(lane_rows[lane], key=lambda row: (int(row["outer_fold"]), str(row["candidate_id"]))))
        artifact_paths[f"{lane}_STRICT_OOF"] = path

    metrics_payload = {
        "schema_version": "pvrig_v2_4_strict_terminal_oof_metrics_v1",
        "status": "PASS_STRICT_OOF_METRICS_COLLECTED",
        "models": metrics,
        "M2_exact_reproduction": reproduction,
        "candidate_count_per_model": expected_candidates,
        "parent_count": expected_parents,
        "source_counts": expected_sources,
        "outer_folds": len(folds),
        "exact_min_violations": exact_min_violations,
        "claim_boundary": contract["claim_boundary"],
    }
    metrics_path = output_dir / "STRICT_OOF_METRICS.json"
    write_json(metrics_path, metrics_payload)
    artifact_paths["STRICT_OOF_METRICS"] = metrics_path
    decision_payload = {
        "schema_version": "pvrig_v2_4_strict_terminal_promotion_decision_v1",
        "status": status,
        "formal_primary_lane": primary,
        "formal_primary_lane_all_gates_pass": primary_pass,
        "formal_primary_lane_gates": lane_gate_diagnostics[primary]["gates"],
        "lane_gate_diagnostics": lane_gate_diagnostics,
        "non_primary_lane_policy": contract["non_primary_lane_policy"],
        "M2_exact_reproduction": reproduction,
        "promotion_gate": frozen_gate,
        "contract_sha256": sha256_file(contract_path),
        "job_graph_sha256": sha256_file(graph_path),
        "sealed_evaluation_access_count": 0,
        "claim_boundary": contract["claim_boundary"],
    }
    decision_path = output_dir / "PROMOTION_DECISION.json"
    write_json(decision_path, decision_payload)
    artifact_paths["PROMOTION_DECISION"] = decision_path
    receipt_payload = {
        "schema_version": "pvrig_v2_4_strict_terminal_evaluation_receipt_v1",
        "status": status,
        "completed_job_count": len(jobs),
        "strict_oof_candidate_count_per_lane": expected_candidates,
        "strict_oof_parent_count": expected_parents,
        "strict_meta_validation_reports_passed": len(validation_hashes),
        "same_row_stacking_used": False,
        "exact_min_violations": exact_min_violations,
        "v4_f_or_test32_access_count": 0,
        "formal_primary_lane": primary,
        "artifacts": {
            name: {"path": str(path), "sha256": sha256_file(path)}
            for name, path in sorted(artifact_paths.items())
        },
        "contract": {"path": str(contract_path), "sha256": sha256_file(contract_path)},
        "job_graph": {"path": str(graph_path), "sha256": sha256_file(graph_path)},
        "runtime_terminal_sha256": sha256_file(runtime_root / "TERMINAL.json"),
        "launch_receipt_sha256": sha256_file(runtime_root / "AUTHORIZED_LAUNCH_RECEIPT.json"),
        "meta_validation_sha256": validation_hashes,
        "claim_boundary": contract["claim_boundary"],
    }
    receipt_path = output_dir / "EVALUATION_RECEIPT.json"
    write_json(receipt_path, receipt_payload)
    artifact_paths["EVALUATION_RECEIPT"] = receipt_path
    checksums = output_dir / "SHA256SUMS"
    with checksums.open("x", encoding="utf-8") as handle:
        for path in sorted(artifact_paths.values(), key=lambda item: item.name):
            handle.write(f"{sha256_file(path)}  {path.name}\n")
    return receipt_payload


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--contract", type=Path, required=True)
    value.add_argument("--job-graph", type=Path, required=True)
    value.add_argument("--runtime-root", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    return value


def main() -> int:
    receipt = evaluate(parser().parse_args())
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
