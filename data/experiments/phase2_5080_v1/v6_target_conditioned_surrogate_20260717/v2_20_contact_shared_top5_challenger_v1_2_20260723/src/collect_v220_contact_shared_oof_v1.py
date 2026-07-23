#!/usr/bin/env python3
"""Collect five V2.20 whole-parent fold outputs into one audited OOF table."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "pvrig.v220.contact_shared_oof_collection.v1"
ARMS = ("C0", "C1")
FOLDS = tuple(range(5))
EXPECTED_ROWS = 9849
EXPECTED_PARENTS = 54
PREDICTION_NAME = "fold_predictions.tsv"
RESULT_NAME = "RESULT.json"
FLOAT_ATOL = 1e-9


class CollectionError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectionError(message)


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
    require(spec is not None and spec.loader is not None, f"module_spec_invalid:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"tsv_invalid:{path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or ())
        rows = [dict(row) for row in reader]
    require(fields and len(fields) == len(set(fields)) and rows, f"tsv_empty_or_invalid:{path}")
    return fields, rows


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _verify_result(
    result: Mapping[str, Any], *, arm: str, fold_id: int, prediction_path: Path
) -> None:
    require(result.get("status") == f"PASS_V220_{arm}_CONTACT_SHARED_FOLD", f"fold_status:{fold_id}")
    require(result.get("arm") == arm, f"fold_arm:{fold_id}")
    require(int(result.get("fold_id", -1)) == fold_id, f"fold_identity:{fold_id}")
    require(int(result.get("seed", -1)) == 43, f"fold_seed:{fold_id}")
    split = result.get("split") or {}
    require(int(split.get("whole_parent_overlap", -1)) == 0, f"fold_parent_overlap:{fold_id}")
    firewall = result.get("neural_input_firewall") or {}
    require(int(firewall.get("outer_score_contact_numeric_reads", -1)) == 0, f"score_contact_access:{fold_id}")
    require(firewall.get("contact_labels_forwarded") is False, f"contact_label_forward:{fold_id}")
    require(result.get("exact_min_inference") is True, f"exact_min_flag:{fold_id}")
    require((result.get("outputs") or {}).get(PREDICTION_NAME) == sha256_file(prediction_path), f"prediction_hash:{fold_id}")


def collect(
    *,
    teacher_path: Path,
    assignment_path: Path,
    contracts_dir: Path,
    run_root: Path,
    output_dir: Path,
    arm: str,
    v213_runner_path: Path,
) -> dict[str, Any]:
    require(arm in ARMS, f"arm_invalid:{arm}")
    require(not output_dir.exists(), f"output_exists:{output_dir}")
    base = load_module(v213_runner_path, "v220_oof_collector_v213_base")
    rows = base.load_rows(teacher_path, EXPECTED_ROWS)
    truth = {row.candidate_id: row for row in rows}
    require(len(truth) == EXPECTED_ROWS, "teacher_candidate_closure")

    assignment_fields, assignment_rows = read_tsv(assignment_path)
    require(
        {"candidate_id", "sequence_sha256", "parent_framework_cluster", "fold_id"}
        <= set(assignment_fields),
        "assignment_fields",
    )
    assignment = {row["candidate_id"]: row for row in assignment_rows}
    require(len(assignment) == len(assignment_rows) == EXPECTED_ROWS, "assignment_duplicates")
    require(set(assignment) == set(truth), "assignment_exact_closure")

    predictions: dict[str, tuple[float, float]] = {}
    fold_audit: list[dict[str, Any]] = []
    input_hashes: dict[str, Any] = {}
    max_truth_error = max_truth_min_error = max_prediction_min_error = 0.0
    initial_by_fold: dict[str, str] = {}

    required_fields = {
        "candidate_id",
        "sequence_sha256",
        "parent_framework_cluster",
        "fold_id",
        "seed",
        "arm",
        "target_R_8X6B",
        "target_R_9E6Y",
        "target_R_dual_min",
        "prediction_R_8X6B",
        "prediction_R_9E6Y",
        "prediction_R_dual_min",
    }

    for fold_id in FOLDS:
        contract_path = contracts_dir / f"fold_{fold_id}_contract.json"
        contract = base.load_contract(contract_path)
        require(int(contract["task"]["fold_id"]) == fold_id, f"contract_fold:{fold_id}")
        require(int(contract["task"]["seed"]) == 43, f"contract_seed:{fold_id}")
        split_path = base._verify_bound_file(contract["split_manifest"], f"split_{fold_id}")
        expected = contract["expected_counts"]
        split = base.load_split(split_path, rows, int(expected["train"]), int(expected["score"]))
        expected_ids = {rows[index].candidate_id for index in split.development_indices}
        assigned_ids = {
            candidate for candidate, item in assignment.items() if int(item["fold_id"]) == fold_id
        }
        require(expected_ids == assigned_ids, f"fold_assignment:{fold_id}")

        fold_dir = run_root / f"fold_{fold_id}"
        result_path = fold_dir / RESULT_NAME
        prediction_path = fold_dir / PREDICTION_NAME
        require(result_path.is_file() and not result_path.is_symlink(), f"result_missing:{fold_id}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        _verify_result(result, arm=arm, fold_id=fold_id, prediction_path=prediction_path)
        pairing = result.get("pairing") or {}
        initial_by_fold[str(fold_id)] = str(pairing.get("serialized_initial_state_sha256", ""))
        require(initial_by_fold[str(fold_id)], f"initial_state_hash_missing:{fold_id}")

        fields, table = read_tsv(prediction_path)
        require(required_fields <= set(fields), f"prediction_fields:{fold_id}")
        seen_fold: set[str] = set()
        for raw in table:
            candidate = raw["candidate_id"]
            require(candidate in expected_ids, f"candidate_not_score_fold:{fold_id}:{candidate}")
            require(candidate not in predictions and candidate not in seen_fold, f"candidate_duplicate:{candidate}")
            expected_row = truth[candidate]
            require(raw["sequence_sha256"] == expected_row.sequence_sha256, f"sequence_hash:{candidate}")
            require(raw["parent_framework_cluster"] == expected_row.parent, f"parent:{candidate}")
            require(int(raw["fold_id"]) == fold_id and int(raw["seed"]) == 43, f"fold_seed_row:{candidate}")
            require(raw["arm"] == arm, f"arm_row:{candidate}")
            try:
                target = (float(raw["target_R_8X6B"]), float(raw["target_R_9E6Y"]))
                prediction = (
                    float(raw["prediction_R_8X6B"]),
                    float(raw["prediction_R_9E6Y"]),
                )
                target_min = float(raw["target_R_dual_min"])
                prediction_min = float(raw["prediction_R_dual_min"])
            except Exception as error:
                raise CollectionError(f"numeric_parse:{candidate}") from error
            require(all(math.isfinite(value) for value in (*target, *prediction, target_min, prediction_min)), f"nonfinite:{candidate}")
            truth_error = max(abs(target[index] - expected_row.targets[index]) for index in range(2))
            truth_min_error = abs(target_min - min(target))
            prediction_min_error = abs(prediction_min - min(prediction))
            max_truth_error = max(max_truth_error, truth_error)
            max_truth_min_error = max(max_truth_min_error, truth_min_error)
            max_prediction_min_error = max(max_prediction_min_error, prediction_min_error)
            require(truth_error <= FLOAT_ATOL, f"truth_mismatch:{candidate}")
            require(truth_min_error <= FLOAT_ATOL, f"truth_exact_min:{candidate}")
            require(prediction_min_error <= FLOAT_ATOL, f"prediction_exact_min:{candidate}")
            predictions[candidate] = prediction
            seen_fold.add(candidate)
        require(seen_fold == expected_ids, f"fold_exact_closure:{fold_id}")
        fold_audit.append(
            {
                "fold_id": fold_id,
                "train_rows": len(split.train_indices),
                "score_rows": len(split.development_indices),
                "train_parents": len(split.train_parents),
                "score_parents": len(split.development_parents),
                "parent_overlap": 0,
            }
        )
        input_hashes[str(fold_id)] = {
            "contract_sha256": sha256_file(contract_path),
            "result_sha256": sha256_file(result_path),
            "prediction_sha256": sha256_file(prediction_path),
        }

    require(len(predictions) == EXPECTED_ROWS and set(predictions) == set(truth), "five_fold_exact_closure")
    require(len({row.parent for row in rows}) == EXPECTED_PARENTS, "parent_count")
    require(len(set(initial_by_fold.values())) == 1, "initial_state_not_byte_identical_across_folds")

    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        prediction_name = f"V220_{arm}_TRAIN9849_OOF_PREDICTIONS.tsv"
        prediction_out = staging / prediction_name
        fields = (
            "candidate_id",
            "sequence_sha256",
            "parent_framework_cluster",
            "fold_id",
            "seed",
            "arm",
            "truth_R8",
            "truth_R9",
            "truth_Rdual_exact_min",
            f"V220_{arm}__R8",
            f"V220_{arm}__R9",
            f"V220_{arm}__Rdual_exact_min",
        )
        with prediction_out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for row in rows:
                predicted = predictions[row.candidate_id]
                writer.writerow(
                    {
                        "candidate_id": row.candidate_id,
                        "sequence_sha256": row.sequence_sha256,
                        "parent_framework_cluster": row.parent,
                        "fold_id": assignment[row.candidate_id]["fold_id"],
                        "seed": "43",
                        "arm": arm,
                        "truth_R8": f"{row.targets[0]:.12g}",
                        "truth_R9": f"{row.targets[1]:.12g}",
                        "truth_Rdual_exact_min": f"{min(row.targets):.12g}",
                        f"V220_{arm}__R8": f"{predicted[0]:.12g}",
                        f"V220_{arm}__R9": f"{predicted[1]:.12g}",
                        f"V220_{arm}__Rdual_exact_min": f"{min(predicted):.12g}",
                    }
                )
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "status": f"PASS_V220_{arm}_TRAIN9849_WHOLE_PARENT_OOF",
            "arm": arm,
            "counts": {"rows": EXPECTED_ROWS, "parents": EXPECTED_PARENTS, "folds": 5, "seed": 43},
            "fold_audit": fold_audit,
            "paired_initial_state_sha256": next(iter(initial_by_fold.values())),
            "numeric_closure": {
                "atol": FLOAT_ATOL,
                "max_truth_abs_error": max_truth_error,
                "max_truth_exact_min_abs_error": max_truth_min_error,
                "max_prediction_exact_min_abs_error": max_prediction_min_error,
            },
            "input_access": {"open_development_rows": 0, "frozen_test_rows": 0},
            "inputs": {
                "teacher_sha256": sha256_file(teacher_path),
                "assignment_sha256": sha256_file(assignment_path),
                "folds": input_hashes,
            },
            "outputs": {prediction_name: sha256_file(prediction_out)},
        }
        receipt_path = staging / "OOF_RECEIPT.json"
        atomic_json(receipt_path, receipt)
        (staging / "SHA256SUMS").write_text(
            "".join(
                f"{sha256_file(staging / name)}  {name}\n"
                for name in sorted((prediction_name, "OOF_RECEIPT.json"))
            ),
            encoding="utf-8",
        )
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
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--v213-runner", type=Path, required=True)
    args = parser.parse_args(argv)
    result = collect(
        teacher_path=args.teacher,
        assignment_path=args.assignment,
        contracts_dir=args.contracts_dir,
        run_root=args.run_root,
        output_dir=args.output_dir,
        arm=args.arm,
        v213_runner_path=args.v213_runner,
    )
    print(json.dumps({"status": result["status"], "counts": result["counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
