#!/usr/bin/env python3
"""Evaluate the frozen V2.20 Phase-1 C1-vs-C0/B0 scalar OOF gate.

Passing this gate only authorizes Phase-1b contact/target ablations.  It is not
final production promotion and does not access open development or frozen test.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "pvrig.v220.phase1_core_gate.v1"
DEFAULT_GATES = {
    "ef5_absolute_gain": 0.10,
    "hits_gain": 5,
    "bootstrap_ci_lower": 0.0,
    "per_fold_delta_floor_for_four": -0.25,
    "minimum_folds_at_floor": 4,
    "minimum_single_fold_delta": -0.75,
    "minimum_ef10": 2.5652,
    "minimum_spearman": 0.5362,
    "maximum_mae": 0.03985,
}


class Phase1GateError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Phase1GateError(message)


def sha256_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"file_invalid:{path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(path: Path, name: str) -> Any:
    require(path.is_file() and not path.is_symlink(), f"module_invalid:{path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"module_spec:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes() if path.is_file() and not path.is_symlink() else b""
    require(bool(raw), f"json_invalid:{path}")
    try:
        value = json.loads(raw)
    except Exception as error:
        raise Phase1GateError(f"json_parse:{path}") from error
    require(isinstance(value, dict), f"json_object_required:{path}")
    return value, hashlib.sha256(raw).hexdigest()


def fold_map(path: Path) -> dict[str, int]:
    require(path.is_file() and not path.is_symlink(), f"oof_invalid:{path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = set(reader.fieldnames or ())
        require({"candidate_id", "fold_id"} <= fields, f"fold_fields:{path}")
        mapping: dict[str, int] = {}
        for row in reader:
            candidate = row["candidate_id"]
            require(candidate and candidate not in mapping, f"fold_candidate_duplicate:{candidate}")
            mapping[candidate] = int(row["fold_id"])
    return mapping


def verify_receipts(
    *,
    b0_path: Path,
    c0_path: Path,
    c1_path: Path,
    b0_replay_path: Path,
    c0_receipt_path: Path,
    c1_receipt_path: Path,
    pairing_receipt_path: Path,
    expected_rows: int,
    expected_parents: int,
) -> dict[str, str]:
    b0, b0_hash = load_json(b0_replay_path)
    c0, c0_hash = load_json(c0_receipt_path)
    c1, c1_hash = load_json(c1_receipt_path)
    pairing, pairing_hash = load_json(pairing_receipt_path)
    require(b0.get("status") == "PASS_V213_B0_OOF_BYTE_EXACT_REPLAY", "b0_replay_status")
    require(c0.get("status") == "PASS_V220_C0_TRAIN9849_WHOLE_PARENT_OOF", "c0_oof_status")
    require(c1.get("status") == "PASS_V220_C1_TRAIN9849_WHOLE_PARENT_OOF", "c1_oof_status")
    require(pairing.get("status") == "PASS_V220_C0_C1_FIVE_FOLD_CAUSAL_PAIRING", "pairing_status")
    for label, receipt in (("C0", c0), ("C1", c1)):
        counts = receipt.get("counts") or {}
        require(int(counts.get("rows", -1)) == expected_rows, f"{label}_rows")
        require(int(counts.get("parents", -1)) == expected_parents, f"{label}_parents")
        require(int(counts.get("folds", -1)) == 5, f"{label}_folds")
        output_name = f"V220_{label}_TRAIN9849_OOF_PREDICTIONS.tsv"
        expected_hash = (receipt.get("outputs") or {}).get(output_name)
        observed_path = c0_path if label == "C0" else c1_path
        require(expected_hash == sha256_file(observed_path), f"{label}_output_hash")
    pairing_folds = {
        int(item.get("fold_id", -1)): item for item in pairing.get("folds") or ()
    }
    require(set(pairing_folds) == set(range(5)), "pairing_fold_closure")
    for fold_id in range(5):
        paired = pairing_folds[fold_id]
        c0_fold = ((c0.get("inputs") or {}).get("folds") or {}).get(str(fold_id)) or {}
        c1_fold = ((c1.get("inputs") or {}).get("folds") or {}).get(str(fold_id)) or {}
        require(
            paired.get("C0_result_sha256") == c0_fold.get("result_sha256"),
            f"pairing_C0_result_closure:{fold_id}",
        )
        require(
            paired.get("C1_result_sha256") == c1_fold.get("result_sha256"),
            f"pairing_C1_result_closure:{fold_id}",
        )
    counts = b0.get("counts") or {}
    require(int(counts.get("rows", -1)) == expected_rows, "B0_rows")
    require(int(counts.get("parents", -1)) == expected_parents, "B0_parents")
    require((b0.get("hashes") or {}).get("aggregate") == sha256_file(b0_path), "B0_output_hash")
    return {
        "B0_replay_receipt_sha256": b0_hash,
        "C0_oof_receipt_sha256": c0_hash,
        "C1_oof_receipt_sha256": c1_hash,
        "pairing_receipt_sha256": pairing_hash,
    }


def gate_decision(
    metrics: Mapping[str, Mapping[str, Any]],
    bootstrap: Mapping[str, Any],
    per_fold: Mapping[str, Mapping[str, Mapping[str, Any]]],
    gates: Mapping[str, float | int] = DEFAULT_GATES,
) -> tuple[dict[str, bool], bool]:
    b0, c0, c1 = metrics["B0"], metrics["C0"], metrics["C1"]
    reference_ef5 = max(float(b0["EF_true_top10_at_budget5"]), float(c0["EF_true_top10_at_budget5"]))
    reference_hits = max(int(b0["hits_at_budget5"]), int(c0["hits_at_budget5"]))
    deltas = bootstrap["paired_deltas"]
    c1_c0_lower = float(deltas["C1_minus_C0"]["paired_percentile_95_ci"][0])
    c1_b0_lower = float(deltas["C1_minus_B0"]["paired_percentile_95_ci"][0])
    fold_deltas = [
        float(per_fold[str(fold)]["C1"]["EF_true_top10_at_budget5"])
        - float(per_fold[str(fold)]["C0"]["EF_true_top10_at_budget5"])
        for fold in range(5)
    ]
    checks = {
        "pooled_ef5_gain": float(c1["EF_true_top10_at_budget5"]) >= reference_ef5 + float(gates["ef5_absolute_gain"]),
        "pooled_hits_gain": int(c1["hits_at_budget5"]) >= reference_hits + int(gates["hits_gain"]),
        "bootstrap_C1_minus_C0_lower_positive": c1_c0_lower > float(gates["bootstrap_ci_lower"]),
        "bootstrap_C1_minus_B0_lower_positive": c1_b0_lower > float(gates["bootstrap_ci_lower"]),
        "four_fold_stability": sum(delta >= float(gates["per_fold_delta_floor_for_four"]) for delta in fold_deltas) >= int(gates["minimum_folds_at_floor"]),
        "minimum_fold_stability": min(fold_deltas) >= float(gates["minimum_single_fold_delta"]),
        "minimum_ef10": float(c1["EF_true_top10_at_budget10"]) >= float(gates["minimum_ef10"]),
        "minimum_spearman": float(c1["Rdual_Spearman"]) >= float(gates["minimum_spearman"]),
        "maximum_mae": float(c1["Rdual_MAE"]) <= float(gates["maximum_mae"]),
    }
    return checks, all(checks.values())


def evaluate_phase1(
    *,
    b0_path: Path,
    c0_path: Path,
    c1_path: Path,
    b0_replay_path: Path,
    c0_receipt_path: Path,
    c1_receipt_path: Path,
    pairing_receipt_path: Path,
    evaluator_path: Path,
    preregistration_path: Path,
    expected_rows: int = 9849,
    expected_parents: int = 54,
    bootstrap_replicates: int = 10000,
    bootstrap_seed: int = 20260723,
) -> dict[str, Any]:
    prereg, prereg_hash = load_json(preregistration_path)
    require(
        prereg.get("status") == "FROZEN_PRETRAINING_PHASE1_CORE_PROTOCOL",
        "preregistration_status",
    )
    evaluation_contract = prereg.get("phase1_core_evaluation") or {}
    require(
        int(evaluation_contract.get("whole_parent_bootstrap_replicates", -1))
        == bootstrap_replicates
        == 10000,
        "bootstrap_replicates_drift",
    )
    require(
        int(evaluation_contract.get("bootstrap_seed", -1))
        == bootstrap_seed
        == 20260723,
        "bootstrap_seed_drift",
    )
    frozen_gates = evaluation_contract.get("all_required") or {}
    gate_bindings = {
        "C1_EF5_gain_over_max_B0_C0": "ef5_absolute_gain",
        "C1_hits_gain_over_max_B0_C0": "hits_gain",
        "C1_minus_C0_bootstrap_95ci_lower_gt": "bootstrap_ci_lower",
        "C1_minus_B0_bootstrap_95ci_lower_gt": "bootstrap_ci_lower",
        "at_least_four_fold_C1_minus_C0_EF5_gte": "per_fold_delta_floor_for_four",
        "minimum_single_fold_C1_minus_C0_EF5": "minimum_single_fold_delta",
        "minimum_C1_EF10": "minimum_ef10",
        "minimum_C1_Rdual_Spearman": "minimum_spearman",
        "maximum_C1_Rdual_MAE": "maximum_mae",
    }
    for prereg_key, local_key in gate_bindings.items():
        require(
            float(frozen_gates.get(prereg_key, float("nan")))
            == float(DEFAULT_GATES[local_key]),
            f"frozen_gate_drift:{prereg_key}",
        )
    expected_evaluator_hash = (
        prereg.get("implementation_hashes_before_initial_state_materialization")
        or {}
    ).get("src/evaluate_v220_oof_v1.py")
    require(
        expected_evaluator_hash == sha256_file(evaluator_path),
        "frozen_evaluator_hash_mismatch",
    )
    receipt_hashes = verify_receipts(
        b0_path=b0_path,
        c0_path=c0_path,
        c1_path=c1_path,
        b0_replay_path=b0_replay_path,
        c0_receipt_path=c0_receipt_path,
        c1_receipt_path=c1_receipt_path,
        pairing_receipt_path=pairing_receipt_path,
        expected_rows=expected_rows,
        expected_parents=expected_parents,
    )
    evaluator = load_module(evaluator_path, "v220_phase1_core_evaluator")
    paths = {"B0": b0_path, "C0": c0_path, "C1": c1_path}
    rows, hashes, folds = {}, {}, {}
    for name, path in paths.items():
        rows[name], hashes[name] = evaluator.load_oof_tsv(path)
        folds[name] = fold_map(path)
        require(len(rows[name]) == expected_rows, f"{name}_row_count")
        require(len({row.parent_id for row in rows[name]}) == expected_parents, f"{name}_parent_count")
    evaluator._validate_aligned_models(rows)
    require(folds["B0"] == folds["C0"] == folds["C1"], "fold_assignment_mismatch")
    reference_by_id = {row.candidate_id: row for row in rows["B0"]}
    parent_fold: dict[str, int] = {}
    for candidate, fold_id in folds["B0"].items():
        parent = reference_by_id[candidate].parent_id
        if parent in parent_fold:
            require(parent_fold[parent] == fold_id, f"parent_crosses_folds:{parent}")
        parent_fold[parent] = fold_id
    require(set(folds["B0"].values()) == set(range(5)), "five_folds_required")

    metrics = {name: evaluator.evaluate_rows(value) for name, value in rows.items()}
    bootstrap = evaluator.paired_parent_bootstrap(
        rows,
        paired_deltas=(("C1", "C0"), ("C1", "B0")),
        replicates=bootstrap_replicates,
        seed=bootstrap_seed,
        expected_parents=expected_parents,
    )
    per_fold: dict[str, Any] = {}
    for fold_id in range(5):
        per_fold[str(fold_id)] = {}
        for name in ("B0", "C0", "C1"):
            selected = [row for row in rows[name] if folds[name][row.candidate_id] == fold_id]
            require(bool(selected), f"empty_fold:{name}:{fold_id}")
            per_fold[str(fold_id)][name] = evaluator.evaluate_rows(selected)
    checks, passed = gate_decision(metrics, bootstrap, per_fold)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_ADVANCE_TO_PHASE1B_CONTACT_TARGET_ABLATIONS" if passed else "FAIL_NO_V220_PHASE1_CORE_PROMOTION",
        "claim_boundary": "Train9849 strict whole-parent OOF computational Docking-geometry surrogate evaluation only; no open-development or frozen-test access and no biological claim.",
        "decision_scope": "Phase-1 core PASS authorizes preregistered Phase-1b ablations only; it is not production promotion.",
        "metrics": metrics,
        "per_fold_metrics": per_fold,
        "bootstrap": bootstrap,
        "gates": dict(DEFAULT_GATES),
        "gate_checks": checks,
        "all_core_gates_pass": passed,
        "input_hashes": hashes,
        "receipt_hashes": receipt_hashes,
        "preregistration_sha256": prereg_hash,
        "input_access": {"open_development_rows": 0, "frozen_test_rows": 0},
    }


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    require(not path.exists(), f"output_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--b0", type=Path, required=True)
    parser.add_argument("--c0", type=Path, required=True)
    parser.add_argument("--c1", type=Path, required=True)
    parser.add_argument("--b0-replay-receipt", type=Path, required=True)
    parser.add_argument("--c0-oof-receipt", type=Path, required=True)
    parser.add_argument("--c1-oof-receipt", type=Path, required=True)
    parser.add_argument("--pairing-receipt", type=Path, required=True)
    parser.add_argument("--evaluator", type=Path, required=True)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=10000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260723)
    args = parser.parse_args(argv)
    result = evaluate_phase1(
        b0_path=args.b0,
        c0_path=args.c0,
        c1_path=args.c1,
        b0_replay_path=args.b0_replay_receipt,
        c0_receipt_path=args.c0_oof_receipt,
        c1_receipt_path=args.c1_oof_receipt,
        pairing_receipt_path=args.pairing_receipt,
        evaluator_path=args.evaluator,
        preregistration_path=args.preregistration,
        bootstrap_replicates=args.bootstrap_replicates,
        bootstrap_seed=args.bootstrap_seed,
    )
    atomic_json(args.output_json, result)
    print(json.dumps({"status": result["status"], "all_core_gates_pass": result["all_core_gates_pass"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
