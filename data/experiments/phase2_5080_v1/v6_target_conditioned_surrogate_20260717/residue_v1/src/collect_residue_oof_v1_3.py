#!/usr/bin/env python3
"""Independently collect V1.3 outer-fold predictions and bootstrap by parent."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


SCHEMA_VERSION = "pvrig_v6_residue_v1_3_oof_collector"
CLAIM_BOUNDARY = (
    "Sequence approximation of independent dual-receptor computational Docking "
    "geometry; not binding probability, affinity, experimental competition, "
    "blocking, Docking Gold, or final submission evidence."
)
PREDICTION_FIELDS = {
    "candidate_id", "parent_framework_cluster", "outer_fold", "R_dual_min",
    "m2_prediction", "residue_prediction",
}
GOVERNANCE_RELATIVE_PATH = "../PREREGISTRATION_V1_1_IMPLEMENTATION_AMENDMENT.json"
GOVERNANCE_SHA256 = "dddc693483c1f9a4145b6e28b74bdc9290ec5e7544e9da302e88cc4c10aa1226"
GOVERNANCE_SCHEMA = "pvrig_v6_implementation_amendment_v1_1"
GOVERNANCE_STATUS = "FROZEN_BEFORE_ANY_NODE1_V6_MODEL_SMOKE_OR_PRODUCTION_TRAINING"
EXACT_PROMOTION_GATE = (
    "global Spearman improves; parent-centered and Top20 non-degrade; "
    "parent bootstrap positive fraction >=0.80 and median delta >0"
)


class OofError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OofError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = 0.5 * (start + end - 1)
        start = end
    return ranks


def spearman(target: np.ndarray, prediction: np.ndarray) -> float:
    if len(target) < 2 or np.std(target) < 1e-12 or np.std(prediction) < 1e-12:
        return 0.0
    return float(np.corrcoef(rankdata(target), rankdata(prediction))[0, 1])


def parent_center(values: np.ndarray, parents: Sequence[str]) -> np.ndarray:
    centered = values.copy()
    for parent in sorted(set(parents)):
        indices = np.asarray([index for index, value in enumerate(parents) if value == parent], dtype=int)
        centered[indices] -= float(np.mean(centered[indices]))
    return centered


def metrics(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, float]:
    target = np.asarray([float(row["R_dual_min"]) for row in rows])
    prediction = np.asarray([float(row[field]) for row in rows])
    parents = [str(row["parent_framework_cluster"]) for row in rows]
    budget = max(1, math.ceil(0.20 * len(rows)))
    truth = set(np.argsort(-target, kind="mergesort")[:budget].tolist())
    predicted = set(np.argsort(-prediction, kind="mergesort")[:budget].tolist())
    return {
        "spearman": spearman(target, prediction),
        "parent_centered_spearman": spearman(parent_center(target, parents), parent_center(prediction, parents)),
        "top20_recall": len(truth & predicted) / len(truth),
        "mae": float(np.mean(np.abs(target - prediction))),
    }


def validate_oof_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    require(bool(rows), "oof_rows_empty")
    seen: set[str] = set()
    parent_fold: dict[str, set[int]] = {}
    for row in rows:
        candidate = str(row["candidate_id"])
        require(candidate not in seen, f"duplicate_oof_candidate:{candidate}")
        seen.add(candidate)
        fold = int(row.get("outer_fold", 0))
        parent_fold.setdefault(str(row["parent_framework_cluster"]), set()).add(fold)
        for field in ("R_dual_min", "m2_prediction", "residue_prediction"):
            require(math.isfinite(float(row[field])), f"oof_nonfinite:{candidate}:{field}")
    require(all(len(folds) == 1 for folds in parent_fold.values()), "oof_parent_crosses_outer_folds")


def deltas(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    m2 = metrics(rows, "m2_prediction")
    residue = metrics(rows, "residue_prediction")
    return {
        "spearman": residue["spearman"] - m2["spearman"],
        "parent_centered_spearman": residue["parent_centered_spearman"] - m2["parent_centered_spearman"],
        "top20_recall": residue["top20_recall"] - m2["top20_recall"],
        "mae_improvement": m2["mae"] - residue["mae"],
    }


def parent_bootstrap(rows: Sequence[Mapping[str, Any]], *, replicates: int, seed: int) -> dict[str, Any]:
    validate_oof_rows(rows)
    require(replicates >= 100, "bootstrap_replicates_too_small")
    by_parent: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_parent.setdefault(str(row["parent_framework_cluster"]), []).append(row)
    parents = sorted(by_parent)
    require(len(parents) >= 2, "bootstrap_too_few_parents")
    rng = np.random.default_rng(seed)
    delta_spearman: list[float] = []
    for _ in range(replicates):
        selected = rng.choice(parents, size=len(parents), replace=True)
        replicate: list[Mapping[str, Any]] = []
        # Give duplicate draws distinct bootstrap group ids for parent-centering.
        for draw_index, parent in enumerate(selected.tolist()):
            for row in by_parent[parent]:
                clone = dict(row)
                clone["parent_framework_cluster"] = f"draw{draw_index}:{parent}"
                replicate.append(clone)
        delta_spearman.append(float(deltas(replicate)["spearman"]))
    values = np.asarray(delta_spearman, dtype=np.float64)
    return {
        "repetitions": replicates,
        "seed": seed,
        "parent_count": len(parents),
        "median_delta_spearman": float(np.median(values)),
        "positive_fraction": float(np.mean(values > 0)),
        "ci95_lower": float(np.quantile(values, 0.025)),
        "ci95_upper": float(np.quantile(values, 0.975)),
    }


def promotion_decision(rows: Sequence[Mapping[str, Any]], bootstrap: Mapping[str, Any]) -> dict[str, Any]:
    point = deltas(rows)
    gates = {
        "global_spearman_improves": point["spearman"] > 0,
        "parent_centered_non_degradation": point["parent_centered_spearman"] >= 0,
        "top20_recall_non_degradation": point["top20_recall"] >= 0,
        "parent_bootstrap_direction_stable": (
            float(bootstrap["positive_fraction"]) >= 0.80
            and float(bootstrap["median_delta_spearman"]) > 0
        ),
    }
    return {
        "status": "PROMOTE_RESIDUE_V1_3_OVER_M2" if all(gates.values()) else "DO_NOT_PROMOTE_RESIDUE_V1_3",
        "point_deltas": point,
        "gates": gates,
        "diagnostics": {
            "mae_improves": point["mae_improvement"] > 0,
            "mae_improvement": point["mae_improvement"],
            "bootstrap_ci95_lower": float(bootstrap["ci95_lower"]),
            "bootstrap_ci95_upper": float(bootstrap["ci95_upper"]),
        },
    }


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def validate_governance_amendment(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"governance_missing:{path}")
    require(not path.is_symlink(), "governance_symlink_forbidden")
    require(sha256_file(path) == GOVERNANCE_SHA256, "governance_sha256_mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(payload.get("schema_version") == GOVERNANCE_SCHEMA, "governance_schema_invalid")
    require(payload.get("status") == GOVERNANCE_STATUS, "governance_status_invalid")
    frozen = payload.get("frozen_implementation") or {}
    require(frozen.get("promotion_gate") == EXACT_PROMOTION_GATE, "governance_promotion_gate_invalid")
    require(int(frozen.get("bootstrap_repetitions", 0)) == 1000, "governance_bootstrap_repetitions_invalid")
    return payload


def validate_implementation_freeze(path: Path, root: Path, governance_path: Path) -> dict[str, str]:
    require(path.is_file() and not path.is_symlink(), "collector_implementation_freeze_missing")
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(payload.get("schema_version") == "pvrig_v6_residue_v1_3_implementation_freeze", "collector_implementation_freeze_schema_invalid")
    require(payload.get("status") == "IMPLEMENTED_CPU_VALIDATED_NOT_REMOTE_TRAINED", "collector_implementation_freeze_status_invalid")
    governance = payload.get("governance") or {}
    require(governance.get("path") == GOVERNANCE_RELATIVE_PATH, "freeze_governance_path_mismatch")
    require(governance.get("sha256") == GOVERNANCE_SHA256, "freeze_governance_sha256_mismatch")
    require(governance.get("promotion_gate") == EXACT_PROMOTION_GATE, "freeze_governance_promotion_gate_mismatch")
    resolved_governance = (root / GOVERNANCE_RELATIVE_PATH).resolve()
    require(resolved_governance == governance_path.resolve(), "freeze_governance_resolved_path_mismatch")
    validate_governance_amendment(governance_path)
    hashes = dict(payload.get("implementation_sha256") or {})
    require(bool(hashes), "collector_implementation_hashes_empty")
    for relative, expected in hashes.items():
        implementation = root / relative
        require(implementation.is_file() and not implementation.is_symlink(), f"collector_implementation_missing:{relative}")
        require(sha256_file(implementation) == expected, f"collector_implementation_hash_mismatch:{relative}")
    return hashes


def validate_outer_binding_documents(
    result: Mapping[str, Any],
    seal: Mapping[str, Any],
    contract: Mapping[str, Any],
    collector_freeze_sha256: str,
) -> None:
    require(result.get("status") == "PASS_OUTER_FOLD_COMPLETE", "outer_run_not_complete")
    require(int(result.get("outer_evaluation_count", 0)) == 1, "outer_evaluation_count_invalid")
    require(seal.get("status") == "SEALED_COMPLETE_ONE_EVALUATION", "outer_evaluation_seal_invalid")
    result_binding = str(result.get("binding_hash") or "")
    seal_binding = str(seal.get("binding_hash") or "")
    contract_binding = str(contract.get("binding_hash") or "")
    require(bool(result_binding) and result_binding == seal_binding == contract_binding, "outer_binding_closure_failed")
    external = (contract.get("binding") or {}).get("external_hashes") or {}
    require(external.get("implementation_freeze_sha256") == collector_freeze_sha256, "outer_freeze_binding_mismatch")


def collect(args: argparse.Namespace) -> dict[str, Any]:
    require(not args.output_dir.exists() and not args.output_dir.is_symlink(), "collector_output_must_not_exist")
    require(len(args.outer_run_dir) == 5, "collector_requires_five_outer_runs")
    governance_payload = validate_governance_amendment(args.governance_amendment)
    collector_freeze_sha256 = sha256_file(args.implementation_freeze)
    implementation_hashes_bound = validate_implementation_freeze(
        args.implementation_freeze, Path(__file__).parents[1], args.governance_amendment,
    )
    with args.training_tsv.open(encoding="utf-8-sig", newline="") as handle:
        expected_rows = list(csv.DictReader(handle, delimiter="\t"))
    expected = {row["candidate_id"]: row for row in expected_rows}
    require(len(expected) == len(expected_rows), "training_candidate_duplicate")
    combined: list[dict[str, Any]] = []
    run_audits = []
    observed_folds: set[int] = set()
    implementation_hashes: set[str] = set()
    for run_dir in args.outer_run_dir:
        result_path = run_dir / "RESULT.json"
        prediction_path = run_dir / "outer_test_predictions.tsv"
        contract_path = run_dir / "contract.json"
        seal_path = run_dir / "OUTER_EVALUATION_SEAL.json"
        for path in (result_path, prediction_path, contract_path, seal_path):
            require(path.is_file() and not path.is_symlink(), f"collector_input_missing:{path}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        validate_outer_binding_documents(result, seal, contract, collector_freeze_sha256)
        require(seal.get("result_sha256") == sha256_file(result_path), f"outer_evaluation_result_hash_mismatch:{run_dir}")
        require(result["artifacts"]["outer_test_predictions.tsv"] == sha256_file(prediction_path), f"prediction_hash_mismatch:{run_dir}")
        require(result["artifacts"]["contract.json"] == sha256_file(contract_path), f"contract_hash_mismatch:{run_dir}")
        fold = int(result["outer_fold"])
        require(fold not in observed_folds, f"duplicate_outer_fold:{fold}")
        observed_folds.add(fold)
        contract_implementation = contract["binding"]["implementation_hashes"]
        require(contract_implementation == implementation_hashes_bound, f"outer_run_implementation_freeze_mismatch:{run_dir}")
        implementation_hashes.add(hashlib.sha256(json.dumps(contract_implementation, sort_keys=True).encode()).hexdigest())
        with prediction_path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            require(PREDICTION_FIELDS <= set(reader.fieldnames or []), f"prediction_fields_missing:{run_dir}")
            rows = [dict(row) for row in reader]
        require(all(int(row["outer_fold"]) == fold for row in rows), f"prediction_fold_mismatch:{run_dir}")
        combined.extend(rows)
        run_audits.append({"outer_fold": fold, "result_sha256": sha256_file(result_path), "prediction_sha256": sha256_file(prediction_path)})
    require(observed_folds == set(range(5)), f"outer_fold_closure_failed:{sorted(observed_folds)}")
    require(len(implementation_hashes) == 1, "outer_runs_implementation_hash_mismatch")
    validate_oof_rows(combined)
    observed = {row["candidate_id"] for row in combined}
    require(observed == set(expected), f"oof_candidate_closure_failed:missing={len(set(expected)-observed)}:extra={len(observed-set(expected))}")
    for row in combined:
        source = expected[row["candidate_id"]]
        require(row["parent_framework_cluster"] == source["parent_framework_cluster"], f"oof_parent_mismatch:{row['candidate_id']}")
        require(int(row["outer_fold"]) == int(source["outer_fold"]), f"oof_frozen_fold_mismatch:{row['candidate_id']}")
        require(abs(float(row["R_dual_min"]) - float(source["R_dual_min"])) <= 1e-6, f"oof_target_mismatch:{row['candidate_id']}")
    bootstrap = parent_bootstrap(combined, replicates=args.bootstrap_replicates, seed=args.bootstrap_seed)
    decision = promotion_decision(combined, bootstrap)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    oof_path = args.output_dir / "residue_v1_3_nested_oof_predictions.tsv"
    with oof_path.open("w", encoding="utf-8", newline="") as handle:
        fields = ["candidate_id", "parent_framework_cluster", "outer_fold", "R_dual_min", "m2_prediction", "residue_prediction"]
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(combined, key=lambda row: row["candidate_id"]))
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": decision["status"],
        "candidate_count": len(combined),
        "parent_count": len({row["parent_framework_cluster"] for row in combined}),
        "m2_metrics": metrics(combined, "m2_prediction"),
        "residue_metrics": metrics(combined, "residue_prediction"),
        "bootstrap": bootstrap,
        "promotion": decision,
        "outer_runs": sorted(run_audits, key=lambda row: row["outer_fold"]),
        "training_tsv_sha256": sha256_file(args.training_tsv),
        "implementation_freeze_sha256": sha256_file(args.implementation_freeze),
        "implementation_hashes": implementation_hashes_bound,
        "governance_amendment_sha256": sha256_file(args.governance_amendment),
        "governance_schema_version": governance_payload["schema_version"],
        "promotion_gate_contract": EXACT_PROMOTION_GATE,
        "outputs": {"oof_predictions_sha256": sha256_file(oof_path)},
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_json(args.output_dir / "OOF_PROMOTION_REPORT.json", report)
    return report


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--training-tsv", type=Path, required=True)
    value.add_argument("--outer-run-dir", type=Path, action="append", required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--implementation-freeze", type=Path, required=True)
    value.add_argument("--governance-amendment", type=Path, required=True)
    value.add_argument("--bootstrap-replicates", type=int, default=2000)
    value.add_argument("--bootstrap-seed", type=int, default=20260718)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    report = collect(args)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
