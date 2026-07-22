#!/usr/bin/env python3
"""Collect five V2.14 listwise whole-parent folds into an exact-closure OOF table."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


HERE = Path(__file__).resolve().parent
RUNNER_PATH = HERE / "run_v214_listwise_fold_v1.py"
SPEC = importlib.util.spec_from_file_location("v214_listwise_oof_runner_for_collection", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("runner_import_invalid")
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)
BASE = RUNNER.BASE

SCHEMA = "pvrig_v2_14_listwise_top5_oof_collection_v1"
METRICS_NAME = "OOF_METRICS.json"
RECEIPT_NAME = "OOF_RECEIPT.json"
FLOAT32_ATOL = 4e-8


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BASE.CleanAttentionError(message)


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"tsv_invalid:{path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields, rows = list(reader.fieldnames or ()), [dict(row) for row in reader]
    require(fields and rows, f"tsv_empty:{path}")
    return fields, rows


def collect(
    teacher_path: Path,
    assignment_path: Path,
    contracts_dir: Path,
    run_root: Path,
    output_dir: Path,
    variant: str,
) -> dict[str, Any]:
    require(variant in {"N1", "N2", "N3"}, "variant_invalid")
    output_name = f"V214_{variant}_TRAIN9849_OOF_PREDICTIONS.tsv"
    require(not output_dir.exists(), "output_exists")
    rows = BASE.load_rows(teacher_path, 9849)
    truth = {row.candidate_id: row for row in rows}
    assignment_fields, assignment_rows = read_tsv(assignment_path)
    require({"candidate_id", "sequence_sha256", "parent_framework_cluster", "fold_id"} <= set(assignment_fields), "assignment_fields")
    assignment = {row["candidate_id"]: row for row in assignment_rows}
    require(len(assignment) == len(assignment_rows) == 9849 and set(assignment) == set(truth), "assignment_exact_closure")
    loaded: dict[str, tuple[float, float]] = {}
    fold_audit = []
    input_hashes: dict[str, Any] = {}
    max_truth_diff = max_truth_min_diff = max_prediction_min_diff = 0.0

    for fold_id in range(5):
        contract_path = contracts_dir / f"fold_{fold_id}_contract.json"
        contract = BASE.load_contract(contract_path)
        require(int(contract["task"]["fold_id"]) == fold_id and int(contract["task"]["seed"]) == 43, f"fold_contract:{fold_id}")
        split_path = BASE._verify_bound_file(contract["split_manifest"], f"fold_split_{fold_id}")
        expected = contract["expected_counts"]
        split = BASE.load_split(split_path, rows, int(expected["train"]), int(expected["score"]))
        expected_ids = {rows[index].candidate_id for index in split.development_indices}
        require(expected_ids == {candidate for candidate, item in assignment.items() if int(item["fold_id"]) == fold_id}, f"fold_assignment:{fold_id}")
        fold_dir = run_root / f"fold_{fold_id}"
        result_path = fold_dir / RUNNER.RESULT_NAME
        prediction_path = fold_dir / RUNNER.PREDICTION_NAME
        require(result_path.is_file() and prediction_path.is_file(), f"fold_output_missing:{fold_id}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        require(result.get("status") == "PASS_V2_14_LISTWISE_TOP5_FOLD", f"fold_status:{fold_id}")
        require(int(result.get("fold_id", -1)) == fold_id and int(result.get("seed", -1)) == 43, f"fold_identity:{fold_id}")
        require(result.get("variant") == variant, f"fold_variant:{fold_id}")
        require(result.get("open_development_access_count") == 0 and result.get("frozen_test_access_count") == 0, f"fold_access:{fold_id}")
        require((result.get("outputs") or {}).get(RUNNER.PREDICTION_NAME) == BASE.sha256_file(prediction_path), f"fold_prediction_hash:{fold_id}")
        prediction_fields, prediction_rows = read_tsv(prediction_path)
        required = {
            "candidate_id", "sequence_sha256", "parent_framework_cluster", "fold_id", "seed", "variant",
            "target_R_8X6B", "target_R_9E6Y", "target_R_dual_min",
            "prediction_R_8X6B", "prediction_R_9E6Y", "prediction_R_dual_min",
        }
        require(required <= set(prediction_fields), f"prediction_fields:{fold_id}")
        fold_ids = set()
        for raw in prediction_rows:
            candidate = raw["candidate_id"]
            require(candidate in expected_ids and candidate not in loaded and candidate not in fold_ids, f"candidate_fold_closure:{fold_id}:{candidate}")
            row = truth[candidate]
            require(raw["sequence_sha256"] == row.sequence_sha256 and raw["parent_framework_cluster"] == row.parent, f"candidate_identity:{candidate}")
            require(int(raw["fold_id"]) == fold_id and int(raw["seed"]) == 43, f"prediction_fold_seed:{candidate}")
            require(raw["variant"] == variant, f"prediction_variant:{candidate}")
            target = (float(raw["target_R_8X6B"]), float(raw["target_R_9E6Y"]))
            prediction = (float(raw["prediction_R_8X6B"]), float(raw["prediction_R_9E6Y"]))
            require(all(math.isfinite(value) for value in target + prediction), f"nonfinite:{candidate}")
            truth_diff = max(abs(target[index] - row.targets[index]) for index in range(2))
            truth_min_diff = abs(float(raw["target_R_dual_min"]) - min(target))
            prediction_min_diff = abs(float(raw["prediction_R_dual_min"]) - min(prediction))
            max_truth_diff = max(max_truth_diff, truth_diff)
            max_truth_min_diff = max(max_truth_min_diff, truth_min_diff)
            max_prediction_min_diff = max(max_prediction_min_diff, prediction_min_diff)
            require(truth_diff <= FLOAT32_ATOL, f"truth_mismatch:{candidate}")
            require(truth_min_diff <= FLOAT32_ATOL and prediction_min_diff <= FLOAT32_ATOL, f"exact_min_mismatch:{candidate}")
            loaded[candidate] = prediction
            fold_ids.add(candidate)
        require(fold_ids == expected_ids and len(fold_ids) == int(expected["score"]), f"fold_row_exact_closure:{fold_id}")
        fold_audit.append({
            "fold_id": fold_id, "train_rows": len(split.train_indices), "score_rows": len(split.development_indices),
            "train_parents": len(split.train_parents), "score_parents": len(split.development_parents), "parent_overlap": 0,
        })
        input_hashes[str(fold_id)] = {
            "contract": BASE.sha256_file(contract_path), "result": BASE.sha256_file(result_path),
            "predictions": BASE.sha256_file(prediction_path),
        }

    require(len(loaded) == 9849 and set(loaded) == set(truth), "five_fold_prediction_exact_closure")
    candidate_ids = [row.candidate_id for row in rows]
    parents = [row.parent for row in rows]
    targets = np.asarray([row.targets for row in rows], dtype=np.float64)
    predictions = np.asarray([loaded[candidate] for candidate in candidate_ids], dtype=np.float64)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    metrics = BASE.comprehensive_metrics(candidate_ids, parents, targets, predictions)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        output_path = staging / output_name
        fields = (
            "candidate_id", "sequence_sha256", "parent_framework_cluster", "fold_id", "seed", "variant",
            "truth_R8", "truth_R9", "truth_Rdual_exact_min",
            f"B_TOP5_{variant}__R8", f"B_TOP5_{variant}__R9", f"B_TOP5_{variant}__Rdual_exact_min",
        )
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for row in rows:
                pred = loaded[row.candidate_id]
                writer.writerow({
                    "candidate_id": row.candidate_id, "sequence_sha256": row.sequence_sha256,
                    "parent_framework_cluster": row.parent, "fold_id": assignment[row.candidate_id]["fold_id"], "seed": "43", "variant": variant,
                    "truth_R8": f"{row.targets[0]:.12g}", "truth_R9": f"{row.targets[1]:.12g}",
                    "truth_Rdual_exact_min": f"{min(row.targets):.12g}",
                    f"B_TOP5_{variant}__R8": f"{pred[0]:.12g}",
                    f"B_TOP5_{variant}__R9": f"{pred[1]:.12g}",
                    f"B_TOP5_{variant}__Rdual_exact_min": f"{min(pred):.12g}",
                })
        metrics_path = staging / METRICS_NAME
        metrics_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
        receipt = {
            "schema_version": SCHEMA,
            "status": "PASS_V2_14_LISTWISE_TRAIN9849_WHOLE_PARENT_OOF",
            "variant": variant,
            "claim_boundary": BASE.CLAIM_BOUNDARY,
            "counts": {"rows": 9849, "parents": 54, "folds": 5, "seed": 43},
            "fold_audit": fold_audit,
            "numeric_closure": {
                "float32_atol": FLOAT32_ATOL, "max_truth_abs_diff": max_truth_diff,
                "max_truth_exact_min_abs_diff": max_truth_min_diff,
                "max_prediction_exact_min_abs_diff": max_prediction_min_diff,
            },
            "inputs": {
                "teacher_sha256": BASE.sha256_file(teacher_path),
                "assignment_sha256": BASE.sha256_file(assignment_path),
                "folds": input_hashes,
            },
            "input_access": {"open_development_rows": 0, "frozen_test_rows": 0},
            "outputs": {output_name: BASE.sha256_file(output_path), METRICS_NAME: BASE.sha256_file(metrics_path)},
        }
        receipt_path = staging / RECEIPT_NAME
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        hashes = {name: BASE.sha256_file(staging / name) for name in (output_name, METRICS_NAME, RECEIPT_NAME)}
        (staging / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())))
        os.replace(staging, output_dir)
        return receipt
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--assignment", type=Path, required=True)
    parser.add_argument("--contracts-dir", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--variant", choices=("N1", "N2", "N3"), required=True)
    args = parser.parse_args(argv)
    result = collect(args.teacher, args.assignment, args.contracts_dir, args.run_root, args.output_dir, args.variant)
    print(json.dumps({"status": result["status"], "counts": result["counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
