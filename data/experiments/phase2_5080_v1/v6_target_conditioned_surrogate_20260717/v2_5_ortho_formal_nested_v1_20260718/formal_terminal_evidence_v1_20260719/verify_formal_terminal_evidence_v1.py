#!/usr/bin/env python3
"""Verify the immutable V2.5 terminal and strict-meta evidence snapshot."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
SNAPSHOT = HERE / "remote_snapshot"
RUNTIME = SNAPSHOT / "pvrig_v2_5_ortho_formal_nested_runtime_v1_3_20260718"
FORMAL = SNAPSHOT / "pvrig_v2_5_strict_cross_lane_meta_formal_result_v1_1_20260718"
WATCH = SNAPSHOT / "pvrig_v2_5_strict_cross_lane_meta_watch_v1_1_20260718"
V25_ROOT = HERE.parent
CONTRACT = (
    V25_ROOT
    / "evaluation_contract_v1_20260718"
    / "CROSS_LANE_NESTED_META_EVALUATION_CONTRACT_V1.json"
)
PACKAGE_MANIFEST = (
    V25_ROOT
    / "strict_cross_lane_meta_evaluator_v1_1_20260718"
    / "prepared"
    / "nonlaunching_package_v1_1"
    / "PACKAGE_MANIFEST.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def exact_min_error(rows: list[dict[str, str]], prefix: str) -> float:
    return max(
        abs(
            float(row[f"{prefix}_Rdual"])
            - min(float(row[f"{prefix}_R8"]), float(row[f"{prefix}_R9"]))
        )
        for row in rows
    )


def parse_sha_list(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        result[name.strip()] = digest
    return result


def main() -> None:
    checks: dict[str, bool] = {}

    terminal = read_json(RUNTIME / "TERMINAL.json")
    graph = read_json(RUNTIME / "GRAPH_STATUS.json")
    runtime_result = read_json(RUNTIME / "final" / "RESULT.json")
    watcher = read_json(WATCH / "WATCHER_STATUS.json")
    pretruth_receipt = read_json(FORMAL / "PRETRUTH_FREEZE_RECEIPT.json")
    formal_receipt = read_json(FORMAL / "FORMAL_EXECUTION_RECEIPT.json")
    formal_parameters = read_json(FORMAL / "FORMAL_PARAMETERS.json")
    metrics = read_json(FORMAL / "FORMAL_METRICS.json")

    checks["runtime_301_of_301"] = (
        terminal["completed"] == 301
        and terminal["status"] == "PASS"
        and terminal["returncode"] == 0
        and graph["completed"] == 301
        and graph["pending"] == 0
        and graph["running"] == 0
    )
    checks["strict_watcher_terminal_pass"] = (
        watcher["status"] == "PASS_FROZEN_EVALUATOR_TERMINAL"
        and watcher["live_graph_modified"] is False
    )
    v4_f_authoritative_documents = (
        terminal,
        graph,
        runtime_result,
        watcher,
        pretruth_receipt,
        formal_receipt,
    )
    checks["v4_f_firewall_zero"] = all(
        doc["v4_f_test32_access_count"] == 0
        for doc in v4_f_authoritative_documents
    )

    checks["contract_hash_closure"] = (
        sha256(CONTRACT)
        == pretruth_receipt["contract_sha256"]
        == formal_receipt["contract_sha256"]
        == watcher["contract_sha256"]
    )
    checks["package_hash_closure"] = (
        sha256(PACKAGE_MANIFEST) == watcher["package_manifest_sha256"]
    )
    checks["pretruth_prediction_hash_closure"] = (
        sha256(FORMAL / "OUTER_PREDICTIONS_PRETRUTH.tsv")
        == pretruth_receipt["prediction_sha256"]
        == formal_parameters["pretruth_prediction_sha256"]
    )
    checks["pretruth_parameter_hash_closure"] = (
        sha256(FORMAL / "FORMAL_PARAMETERS_PRETRUTH.json")
        == pretruth_receipt["parameters_sha256"]
        == formal_parameters["pretruth_parameters_sha256"]
    )
    checks["pretruth_receipt_hash_closure"] = (
        sha256(FORMAL / "PRETRUTH_FREEZE_RECEIPT.json")
        == formal_parameters["pretruth_freeze_receipt_sha256"]
    )
    checks["formal_artifact_hash_closure"] = all(
        sha256(FORMAL / name) == digest
        for name, digest in formal_receipt["artifacts"].items()
    )
    checks["formal_receipt_hash_closure"] = (
        sha256(FORMAL / "FORMAL_EXECUTION_RECEIPT.json")
        == watcher["formal_receipt_sha256"]
    )
    checks["runtime_hash_closure"] = (
        sha256(RUNTIME / "TERMINAL.json")
        == formal_receipt["runtime_terminal_sha256"]
        and sha256(RUNTIME / "final" / "RESULT.json")
        == formal_receipt["runtime_final_result_sha256"]
        and terminal["job_graph_sha256"]
        == formal_receipt["runtime_job_graph_sha256"]
        == pretruth_receipt["runtime_job_graph_sha256"]
    )
    checks["runtime_result_summary_identity"] = (
        sha256(RUNTIME / "final" / "RESULT.json")
        == sha256(RUNTIME / "final" / "FORMAL_OPEN_OUTER_SUMMARY.json")
    )

    remote_hashes = parse_sha_list(HERE / "REMOTE_SHA256SUMS.txt")
    local_hashes = parse_sha_list(HERE / "LOCAL_SHA256SUMS_RELATIVE.txt")
    checks["remote_local_snapshot_hash_identity"] = remote_hashes == local_hashes

    pretruth_rows = read_tsv(FORMAL / "OUTER_PREDICTIONS_PRETRUTH.tsv")
    formal_rows = read_tsv(FORMAL / "FORMAL_OUTER_OOF_PREDICTIONS.tsv")
    selected_rows = read_tsv(FORMAL / "SELECTED_PRODUCTION_PREDICTIONS.tsv")

    model_counts = Counter(row["model_id"] for row in formal_rows)
    candidate_sets = {
        model: {row["candidate_id"] for row in formal_rows if row["model_id"] == model}
        for model in model_counts
    }
    checks["formal_1507_per_model"] = (
        len(model_counts) == 8 and set(model_counts.values()) == {1507}
    )
    checks["formal_candidate_set_closure"] = (
        len({frozenset(value) for value in candidate_sets.values()}) == 1
        and len(next(iter(candidate_sets.values()))) == 1507
    )
    checks["formal_31_parent_5_fold_closure"] = (
        len({row["parent_framework_cluster"] for row in formal_rows}) == 31
        and {int(row["outer_fold"]) for row in formal_rows} == {0, 1, 2, 3, 4}
    )

    pretruth_predictions = {
        (row["model_id"], row["candidate_id"], row["outer_fold"]): (
            row["pred_R8"],
            row["pred_R9"],
            row["pred_Rdual"],
        )
        for row in pretruth_rows
    }
    formal_predictions = {
        (row["model_id"], row["candidate_id"], row["outer_fold"]): (
            row["pred_R8"],
            row["pred_R9"],
            row["pred_Rdual"],
        )
        for row in formal_rows
    }
    checks["pretruth_formal_prediction_identity"] = (
        len(pretruth_rows) == len(formal_rows) == 12056
        and pretruth_predictions == formal_predictions
    )

    predicted_exact_min_error = exact_min_error(formal_rows, "pred")
    truth_exact_min_error = exact_min_error(formal_rows, "truth")
    selected_exact_min_error = exact_min_error(selected_rows, "pred")
    checks["exact_min_zero"] = (
        predicted_exact_min_error == 0.0
        and truth_exact_min_error == 0.0
        and selected_exact_min_error == 0.0
        and runtime_result["exact_min_contract"] is True
    )
    checks["selected_exact_m2_fallback_1507"] = (
        len(selected_rows) == 1507
        and {row["model_id"] for row in selected_rows} == {"M2_FROZEN_ALPHA10"}
        and {row["selected_from_model_id"] for row in selected_rows}
        == {"M2_FROZEN_ALPHA10"}
        and formal_receipt["selected_production_model_id"] == "M2_FROZEN_ALPHA10"
        and formal_receipt["decision"] == "DO_NOT_PROMOTE_EXACT_M2_FALLBACK"
    )

    decision = metrics["decision"]
    primary = decision["primary_metrics"]["targets"]["Rdual"]
    m2 = decision["m2_metrics"]["targets"]["Rdual"]
    lane_metrics = {
        model: data["targets"]["Rdual"] for model, data in metrics["metrics"].items()
    }
    report = {
        "schema_version": "pvrig_v2_5_formal_terminal_evidence_verification_v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "counts": {
            "runtime_jobs_completed": terminal["completed"],
            "formal_models": len(model_counts),
            "rows_per_model": sorted(set(model_counts.values())),
            "formal_total_rows": len(formal_rows),
            "candidates": len(next(iter(candidate_sets.values()))),
            "parent_clusters": len(
                {row["parent_framework_cluster"] for row in formal_rows}
            ),
            "outer_folds": sorted({int(row["outer_fold"]) for row in formal_rows}),
            "selected_production_rows": len(selected_rows),
        },
        "exact_min_max_abs_error": {
            "formal_prediction": predicted_exact_min_error,
            "formal_truth": truth_exact_min_error,
            "selected_production_prediction": selected_exact_min_error,
        },
        "formal_decision": {
            "status": decision["status"],
            "selected_production_model_id": metrics["selected_production_model_id"],
            "checks": decision["checks"],
            "primary_Rdual": primary,
            "M2_Rdual": m2,
            "Rdual_spearman_delta_vs_M2": primary["spearman"] - m2["spearman"],
            "Rdual_mae_delta_vs_M2": primary["mae"] - m2["mae"],
            "Rdual_rmse_delta_vs_M2": primary["rmse"] - m2["rmse"],
            "paired_parent_bootstrap": decision["paired_parent_bootstrap"],
            "parents_with_nonnegative_Rdual_mae_delta": decision[
                "parents_with_nonnegative_Rdual_mae_delta"
            ],
        },
        "lane_Rdual_metrics": lane_metrics,
        "hashes": {
            "contract_sha256": sha256(CONTRACT),
            "package_manifest_sha256": sha256(PACKAGE_MANIFEST),
            "pretruth_freeze_receipt_sha256": sha256(
                FORMAL / "PRETRUTH_FREEZE_RECEIPT.json"
            ),
            "formal_execution_receipt_sha256": sha256(
                FORMAL / "FORMAL_EXECUTION_RECEIPT.json"
            ),
            "runtime_terminal_sha256": sha256(RUNTIME / "TERMINAL.json"),
            "runtime_result_sha256": sha256(RUNTIME / "final" / "RESULT.json"),
        },
        "claim_boundary": formal_receipt["claim_boundary"],
        "notes": [
            "GRAPH_STATUS.json retains the scheduler's last RUNNING label, but has 301 completed, 0 pending, and 0 running; TERMINAL.json is the authoritative PASS terminal.",
            "The strict evaluator completed, but promotion gates failed for Rdual Spearman and parent bootstrap; production therefore remains the exact M2 fallback.",
        ],
    }
    output = HERE / "VERIFICATION_REPORT.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
