#!/usr/bin/env python3
"""Fail-closed replay of the frozen V2.13 L1 whole-parent OOF aggregate.

The five fold files contain float32 evaluation targets.  The frozen aggregate
was serialized from the original train-only scalar teacher, so a byte-exact
replay also needs that train-only teacher projection.  Its digest is trusted
only through the preregistration-bound frozen OOF receipt.  No development,
frozen-test, quarantine, or sealed path is permitted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


SCHEMA = "pvrig_v2_20_v213_b0_oof_replay_v1"
STATUS = "PASS_V213_B0_OOF_BYTE_EXACT_REPLAY"
FOLD_REQUIRED_FIELDS = frozenset({
    "candidate_id", "sequence_sha256", "parent_framework_cluster", "fold_id", "seed", "variant",
    "target_R_8X6B", "target_R_9E6Y", "target_R_dual_min",
    "prediction_R_8X6B", "prediction_R_9E6Y", "prediction_R_dual_min",
})
TEACHER_REQUIRED_FIELDS = frozenset({
    "candidate_id", "sequence_sha256", "parent_framework_cluster", "R_8X6B", "R_9E6Y", "R_dual_min",
})
OUTPUT_FIELDS = (
    "candidate_id", "sequence_sha256", "parent_framework_cluster", "fold_id", "seed", "variant",
    "truth_R8", "truth_R9", "truth_Rdual_exact_min",
    "B_TOP5_L1__R8", "B_TOP5_L1__R9", "B_TOP5_L1__Rdual_exact_min",
)
PREREG_EXACT_FIELDS = (
    "candidate_id", "sequence_sha256", "parent_id", "fold_id", "seed",
    "true_R8", "true_R9", "true_Rdual", "pred_R8", "pred_R9", "pred_Rdual",
)
FORBIDDEN_PATH_TOKENS = (
    "open_development", "open-development", "frozen_test", "frozen-test",
    "test32", "sealed", "quarantine",
)


class ReplayError(RuntimeError):
    """A fail-closed replay contract violation."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReplayError(message)


def assert_train_oof_path(path: Path, label: str) -> None:
    lowered = str(path).lower()
    for token in FORBIDDEN_PATH_TOKENS:
        require(token not in lowered, f"forbidden_path:{label}:{token}:{path}")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_regular_snapshot(path: Path, label: str) -> bytes:
    assert_train_oof_path(path, label)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ReplayError(f"open_failed:{label}:{path}") from error
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode), f"not_regular:{label}:{path}")
        require(before.st_size > 0, f"empty_file:{label}:{path}")
        blocks: list[bytes] = []
        while True:
            block = os.read(descriptor, 8 * 1024 * 1024)
            if not block:
                break
            blocks.append(block)
        after = os.fstat(descriptor)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        require(identity(before) == identity(after), f"changed_during_read:{label}:{path}")
        raw = b"".join(blocks)
        require(len(raw) == before.st_size, f"short_read:{label}:{path}")
        return raw
    finally:
        os.close(descriptor)


def parse_json(raw: bytes, label: str) -> dict[str, Any]:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, f"duplicate_json_key:{label}:{key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
    except Exception as error:
        raise ReplayError(f"invalid_json:{label}") from error
    require(isinstance(value, dict), f"json_not_object:{label}")
    return value


def parse_tsv(raw: bytes, label: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text = raw.decode("utf-8")
        require(not text.startswith("\ufeff"), f"utf8_bom_forbidden:{label}")
        reader = csv.DictReader(io.StringIO(text, newline=""), delimiter="\t")
        fields = list(reader.fieldnames or ())
        rows = [dict(row) for row in reader]
    except ReplayError:
        raise
    except Exception as error:
        raise ReplayError(f"invalid_tsv:{label}") from error
    require(fields and len(fields) == len(set(fields)), f"bad_header:{label}")
    require(rows, f"empty_tsv:{label}")
    require(all(None not in row and all(value is not None for value in row.values()) for row in rows), f"ragged_tsv:{label}")
    return fields, rows


def format12(value: float) -> str:
    require(math.isfinite(value), "nonfinite_numeric_value")
    return format(value, ".12g")


def _float32_serialized(value: str) -> str:
    return format12(float(np.float32(float(value))))


def reconstruct_aggregate_bytes(
    fold_tables: Mapping[int, tuple[list[str], list[dict[str, str]]]],
    teacher_fields: Sequence[str],
    teacher_rows: Sequence[Mapping[str, str]],
    *,
    expected_seed: int,
    expected_variant: str = "L1",
) -> tuple[bytes, list[dict[str, str]], dict[int, int]]:
    """Recreate the V2.13 aggregate serialization without reading the aggregate."""

    require(TEACHER_REQUIRED_FIELDS <= set(teacher_fields), "teacher_fields_missing")
    teacher: dict[str, Mapping[str, str]] = {}
    for row in teacher_rows:
        candidate = row["candidate_id"]
        require(candidate and candidate not in teacher, f"teacher_candidate_duplicate:{candidate}")
        teacher[candidate] = row

    folded: dict[str, Mapping[str, str]] = {}
    fold_counts: dict[int, int] = {}
    for fold_id in sorted(fold_tables):
        fields, rows = fold_tables[fold_id]
        require(FOLD_REQUIRED_FIELDS <= set(fields), f"fold_fields_missing:{fold_id}")
        seen: set[str] = set()
        for row in rows:
            candidate = row["candidate_id"]
            require(candidate and candidate not in seen and candidate not in folded, f"fold_candidate_duplicate:{fold_id}:{candidate}")
            require(int(row["fold_id"]) == fold_id, f"fold_id_mismatch:{candidate}")
            require(int(row["seed"]) == expected_seed, f"seed_mismatch:{candidate}")
            require(row["variant"] == expected_variant, f"variant_mismatch:{candidate}")
            require(candidate in teacher, f"fold_candidate_not_in_teacher:{candidate}")
            source = teacher[candidate]
            require(row["sequence_sha256"] == source["sequence_sha256"], f"sequence_sha256_mismatch:{candidate}")
            require(row["parent_framework_cluster"] == source["parent_framework_cluster"], f"parent_mismatch:{candidate}")

            truth8 = float(source["R_8X6B"])
            truth9 = float(source["R_9E6Y"])
            truth_dual = float(source["R_dual_min"])
            require(all(math.isfinite(value) for value in (truth8, truth9, truth_dual)), f"teacher_nonfinite:{candidate}")
            require(abs(truth_dual - min(truth8, truth9)) <= 1e-12, f"teacher_exact_min_mismatch:{candidate}")
            require(row["target_R_8X6B"] == _float32_serialized(source["R_8X6B"]), f"fold_truth8_float32_mismatch:{candidate}")
            require(row["target_R_9E6Y"] == _float32_serialized(source["R_9E6Y"]), f"fold_truth9_float32_mismatch:{candidate}")
            folded_truth_dual = min(float(np.float32(truth8)), float(np.float32(truth9)))
            require(row["target_R_dual_min"] == format12(folded_truth_dual), f"fold_truth_dual_float32_mismatch:{candidate}")

            prediction8 = float(row["prediction_R_8X6B"])
            prediction9 = float(row["prediction_R_9E6Y"])
            prediction_dual = float(row["prediction_R_dual_min"])
            require(all(math.isfinite(value) for value in (prediction8, prediction9, prediction_dual)), f"prediction_nonfinite:{candidate}")
            require(row["prediction_R_dual_min"] == format12(min(prediction8, prediction9)), f"prediction_exact_min_mismatch:{candidate}")
            seen.add(candidate)
            folded[candidate] = row
        fold_counts[fold_id] = len(rows)

    require(set(folded) == set(teacher), "fold_teacher_candidate_exact_closure_failed")
    output_rows: list[dict[str, str]] = []
    for candidate in sorted(teacher):
        source, prediction = teacher[candidate], folded[candidate]
        truth8, truth9 = float(source["R_8X6B"]), float(source["R_9E6Y"])
        prediction8, prediction9 = float(prediction["prediction_R_8X6B"]), float(prediction["prediction_R_9E6Y"])
        output_rows.append({
            "candidate_id": candidate,
            "sequence_sha256": source["sequence_sha256"],
            "parent_framework_cluster": source["parent_framework_cluster"],
            "fold_id": prediction["fold_id"],
            "seed": str(expected_seed),
            "variant": expected_variant,
            "truth_R8": format12(truth8),
            "truth_R9": format12(truth9),
            "truth_Rdual_exact_min": format12(min(truth8, truth9)),
            "B_TOP5_L1__R8": format12(prediction8),
            "B_TOP5_L1__R9": format12(prediction9),
            "B_TOP5_L1__Rdual_exact_min": format12(min(prediction8, prediction9)),
        })

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_FIELDS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(output_rows)
    return buffer.getvalue().encode("utf-8"), output_rows, fold_counts


def replay_b0(
    *,
    preregistration_path: Path,
    fold_prediction_paths: Mapping[int, Path],
    train_teacher_path: Path,
    frozen_aggregate_path: Path,
    frozen_metrics_path: Path,
    frozen_receipt_path: Path,
) -> dict[str, Any]:
    prereg_raw = read_regular_snapshot(preregistration_path, "preregistration")
    prereg = parse_json(prereg_raw, "preregistration")
    strict = prereg.get("strict_oof") or {}
    gate = prereg.get("B0_replay_gate") or {}
    require(gate.get("required_before_C0_or_C1_training") is True, "b0_gate_not_required")
    require(tuple(gate.get("row_by_row_exact_fields") or ()) == PREREG_EXACT_FIELDS, "b0_exact_field_contract_mismatch")
    require(gate.get("numeric_comparison") == "exact serialized decimal string equality, not tolerance equality", "numeric_comparison_not_exact")

    expected_rows = int(strict.get("rows", 0))
    expected_parents = int(strict.get("parents", 0))
    expected_folds = int(strict.get("folds", 0))
    expected_seed = int(strict.get("seed_phase_1", -1))
    bindings = {int(item["fold"]): item for item in strict.get("fold_bindings") or ()}
    require(expected_rows > 0 and expected_parents > 0 and expected_folds > 0, "strict_oof_counts_invalid")
    require(set(bindings) == set(range(expected_folds)), "strict_oof_fold_binding_closure")
    require(set(fold_prediction_paths) == set(bindings), "provided_fold_path_closure")

    aggregate_raw = read_regular_snapshot(frozen_aggregate_path, "frozen_b0_aggregate")
    metrics_raw = read_regular_snapshot(frozen_metrics_path, "frozen_b0_metrics")
    receipt_raw = read_regular_snapshot(frozen_receipt_path, "frozen_b0_receipt")
    require(frozen_aggregate_path.name == gate.get("aggregate_prediction_path"), "aggregate_filename_mismatch")
    require(sha256_bytes(aggregate_raw) == gate.get("aggregate_prediction_sha256"), "aggregate_prereg_hash_mismatch")
    require(sha256_bytes(metrics_raw) == gate.get("metrics_sha256"), "metrics_prereg_hash_mismatch")
    require(sha256_bytes(receipt_raw) == gate.get("receipt_sha256"), "receipt_prereg_hash_mismatch")

    receipt = parse_json(receipt_raw, "frozen_b0_receipt")
    counts = receipt.get("counts") or {}
    require(counts == {"folds": expected_folds, "parents": expected_parents, "rows": expected_rows, "seed": expected_seed}, "frozen_receipt_counts_mismatch")
    access = receipt.get("input_access") or {}
    require(access.get("open_development_rows") == 0 and access.get("frozen_test_rows") == 0, "frozen_receipt_forbidden_access")
    outputs = receipt.get("outputs") or {}
    require(outputs.get(frozen_aggregate_path.name) == sha256_bytes(aggregate_raw), "receipt_aggregate_hash_mismatch")
    require(outputs.get(frozen_metrics_path.name) == sha256_bytes(metrics_raw), "receipt_metrics_hash_mismatch")

    teacher_raw = read_regular_snapshot(train_teacher_path, "train_only_teacher")
    receipt_inputs = receipt.get("inputs") or {}
    require(sha256_bytes(teacher_raw) == receipt_inputs.get("teacher_sha256"), "train_teacher_receipt_hash_mismatch")
    teacher_fields, teacher_rows = parse_tsv(teacher_raw, "train_only_teacher")
    require(len(teacher_rows) == expected_rows, "train_teacher_row_count_mismatch")
    require(len({row["parent_framework_cluster"] for row in teacher_rows}) == expected_parents, "train_teacher_parent_count_mismatch")

    fold_tables: dict[int, tuple[list[str], list[dict[str, str]]]] = {}
    fold_hashes: dict[str, str] = {}
    receipt_folds = receipt_inputs.get("folds") or {}
    for fold_id in range(expected_folds):
        raw = read_regular_snapshot(fold_prediction_paths[fold_id], f"fold_{fold_id}_predictions")
        digest = sha256_bytes(raw)
        require(digest == bindings[fold_id].get("prediction_sha256"), f"fold_prereg_hash_mismatch:{fold_id}")
        require(digest == (receipt_folds.get(str(fold_id)) or {}).get("predictions"), f"fold_receipt_hash_mismatch:{fold_id}")
        table = parse_tsv(raw, f"fold_{fold_id}_predictions")
        require(len(table[1]) == int(bindings[fold_id].get("score_rows", -1)), f"fold_score_rows_mismatch:{fold_id}")
        fold_tables[fold_id] = table
        fold_hashes[str(fold_id)] = digest

    reconstructed, expected_aggregate_rows, fold_counts = reconstruct_aggregate_bytes(
        fold_tables, teacher_fields, teacher_rows, expected_seed=expected_seed,
    )
    require(sum(fold_counts.values()) == expected_rows, "five_fold_row_count_mismatch")
    require(sha256_bytes(reconstructed) == gate.get("aggregate_prediction_sha256"), "reconstructed_aggregate_hash_mismatch")
    require(reconstructed == aggregate_raw, "reconstructed_aggregate_bytes_mismatch")

    aggregate_fields, aggregate_rows = parse_tsv(aggregate_raw, "frozen_b0_aggregate")
    require(tuple(aggregate_fields) == OUTPUT_FIELDS, "aggregate_header_mismatch")
    require(len(aggregate_rows) == len(expected_aggregate_rows) == expected_rows, "aggregate_row_count_mismatch")
    for index, (observed, expected) in enumerate(zip(aggregate_rows, expected_aggregate_rows)):
        for field in OUTPUT_FIELDS:
            require(observed[field] == expected[field], f"aggregate_exact_field_mismatch:{index}:{field}")

    parse_json(metrics_raw, "frozen_b0_metrics")
    return {
        "schema_version": SCHEMA,
        "status": STATUS,
        "claim_boundary": "Frozen train9849 whole-parent OOF replay only; no development or frozen-test access and no model training.",
        "counts": {"rows": expected_rows, "parents": expected_parents, "folds": expected_folds, "seed": expected_seed},
        "closure": {
            "byte_exact": True,
            "row_by_row_all_output_fields_exact": True,
            "stable_sort": "candidate_id ascending",
            "numeric_comparison": gate["numeric_comparison"],
            "fold_score_rows": {str(key): value for key, value in sorted(fold_counts.items())},
        },
        "input_access": {"open_development_rows": 0, "frozen_test_rows": 0, "quarantine_rows": 0},
        "hashes": {
            "preregistration": sha256_bytes(prereg_raw),
            "train_only_teacher": sha256_bytes(teacher_raw),
            "fold_predictions": fold_hashes,
            "aggregate": sha256_bytes(aggregate_raw),
            "metrics": sha256_bytes(metrics_raw),
            "receipt": sha256_bytes(receipt_raw),
        },
    }


def _parse_fold_argument(value: str) -> tuple[int, Path]:
    try:
        fold_text, path_text = value.split("=", 1)
        fold_id = int(fold_text)
    except Exception as error:
        raise argparse.ArgumentTypeError("fold prediction must be FOLD_ID=PATH") from error
    return fold_id, Path(path_text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--fold-prediction", action="append", type=_parse_fold_argument, required=True)
    parser.add_argument("--train-teacher", type=Path, required=True)
    parser.add_argument("--frozen-aggregate", type=Path, required=True)
    parser.add_argument("--frozen-metrics", type=Path, required=True)
    parser.add_argument("--frozen-receipt", type=Path, required=True)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args(argv)
    fold_paths = dict(args.fold_prediction)
    require(len(fold_paths) == len(args.fold_prediction), "duplicate_fold_argument")
    result = replay_b0(
        preregistration_path=args.preregistration,
        fold_prediction_paths=fold_paths,
        train_teacher_path=args.train_teacher,
        frozen_aggregate_path=args.frozen_aggregate,
        frozen_metrics_path=args.frozen_metrics,
        frozen_receipt_path=args.frozen_receipt,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output_json is not None:
        assert_train_oof_path(args.output_json, "output_json")
        with args.output_json.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
