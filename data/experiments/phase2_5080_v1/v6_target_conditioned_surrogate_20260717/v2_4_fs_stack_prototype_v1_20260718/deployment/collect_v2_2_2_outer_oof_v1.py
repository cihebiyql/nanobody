#!/usr/bin/env python3
"""Wait for and collect V2.2.2 open-only four-lane outer OOF evidence.

This collector is deliberately terminal-only.  It validates the frozen
V2.2.2 outer-development receipt and all 20 RESULT/prediction bundles, writes
open-only descriptive OOF metrics, and stops.  It never reads V4-F/test32 and
never launches the strict nested stack.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import pathlib
import shutil
import struct
import time
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping, Sequence

LANES = (
    "A_VHH_ONLY",
    "B_TARGET_NO_CONTACT",
    "C_SPLIT_MARGINAL",
    "D_SPLIT_PAIR",
)
FOLDS = tuple(range(5))
EXPECTED_WEIGHTS = {
    "A_VHH_ONLY": {"marginal": 0.0, "pair": 0.0},
    "B_TARGET_NO_CONTACT": {"marginal": 0.0, "pair": 0.0},
    "C_SPLIT_MARGINAL": {"marginal": 1.5, "pair": 0.0},
    "D_SPLIT_PAIR": {"marginal": 1.0, "pair": 0.5},
}
MANIFEST_SCHEMA = "pvrig_v6_residue_v2_4_node1_deployment_manifest_v2_2_2_bundle_receipt_contract_corrected"
READY_STATUS = "PREFREEZE_V2_2_2_ADAPTIVE_MULTI_SEED_READY_DO_NOT_START"
FREEZE_SCHEMA = "pvrig_v6_residue_v2_4_implementation_freeze_v2_2_2_bundle_receipt_contract_corrected"
FREEZE_STATUS = "PASS_V2_4_ADAPTIVE_MULTI_SEED_IMPLEMENTATION_V2_2_2_FROZEN_FOR_TINY_SMOKE_AND_OUTER_DEVELOPMENT"
OUTER_SCHEMA = "pvrig_v6_residue_v2_4_node1_outer_development_receipt_v2_2_2_bundle_receipt_contract_corrected"
OUTER_STATUS = "PASS_V2_4_ADAPTIVE_V2_2_2_FOUR_LANE_OUTER_DEVELOPMENT_AFTER_INDEPENDENT_GATES"
RESULT_SCHEMA = "pvrig_v2_4_open_base_split_trainer_v1"
RESULT_STATUS = "PASS_OPEN_BASE_SPLIT_COMPLETE"
BUNDLE_REVISION = "V2.2.2_BUNDLE_RECEIPT_CONTRACT_CORRECTED"
CLAIM_BOUNDARY = (
    "Open-only adaptive-multiseed independent 8X6B/9E6Y computational Docking "
    "geometry surrogate; not binding, affinity, experimental blocking, Docking Gold, "
    "or submission evidence."
)
TRAINER_RESULT_CLAIM_BOUNDARY = (
    "Open-only computational surrogate of independent 8X6B/9E6Y Docking "
    "geometry; not binding probability, affinity, experimental blocking, "
    "Docking Gold, or submission evidence."
)
FORBIDDEN_TOKENS = ("v4_f", "test32", "prospective_computational_test")
PREDICTION_FIELDS = (
    "candidate_id", "teacher_source", "parent_framework_cluster", "split_id", "lane",
    "truth_R8", "truth_R9", "truth_Rdual", "M2_R8", "M2_R9", "M2_Rdual",
    "neural_R8", "neural_R9", "neural_Rdual", "contact_score_R8", "contact_score_R9",
    "contact_score_role", "contact_score_formula_sha256", "base_training_parent_set_sha256",
    "base_training_parent_count", "base_model_receipt_sha256",
)


class CollectionError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectionError(message)


def sha256_file(path: pathlib.Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"file_missing_or_symlink:{path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: pathlib.Path, label: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"{label}_missing_or_symlink:{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(payload, dict), f"{label}_not_object")
    return payload


def atomic_json(path: pathlib.Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    require(not os.path.lexists(temporary), f"temporary_path_exists:{temporary}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def safe_path(path: pathlib.Path, label: str) -> pathlib.Path:
    lowered = str(path).lower()
    require(path.is_absolute(), f"{label}_not_absolute:{path}")
    require(not any(token in lowered for token in FORBIDDEN_TOKENS), f"forbidden_path:{label}:{path}")
    return path


def exact_min(left: float, right: float, dual: float) -> bool:
    return struct.pack("!d", dual) == struct.pack("!d", min(left, right))


def finite_float(value: str, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise CollectionError(f"nonfloat:{label}:{value}") from exc
    require(math.isfinite(parsed), f"nonfinite:{label}")
    return parsed


def average_ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = 0.5 * (start + end - 1) + 1.0
        for offset in range(start, end):
            ranks[order[offset]] = rank
        start = end
    return ranks


def spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    require(len(left) == len(right) and len(left) >= 2, "spearman_shape")
    x, y = average_ranks(left), average_ranks(right)
    xm, ym = sum(x) / len(x), sum(y) / len(y)
    numerator = sum((a - xm) * (b - ym) for a, b in zip(x, y))
    denominator = math.sqrt(sum((a - xm) ** 2 for a in x) * sum((b - ym) ** 2 for b in y))
    if denominator == 0:
        return None
    result = numerator / denominator
    require(math.isfinite(result), "spearman_nonfinite")
    return result


def metrics(truth: Sequence[float], prediction: Sequence[float]) -> dict[str, float | None]:
    require(len(truth) == len(prediction) and len(truth) > 0, "metric_shape")
    residual = [prediction[index] - truth[index] for index in range(len(truth))]
    return {
        "spearman": spearman(truth, prediction) if len(truth) >= 2 else None,
        "mae": sum(abs(value) for value in residual) / len(residual),
        "rmse": math.sqrt(sum(value * value for value in residual) / len(residual)),
    }


def validate_manifest_and_freeze(
    manifest_path: pathlib.Path, freeze_path: pathlib.Path, runtime_root: pathlib.Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = load_json(manifest_path, "ready_manifest")
    freeze = load_json(freeze_path, "implementation_freeze")
    require(manifest.get("schema_version") == MANIFEST_SCHEMA, "manifest_schema")
    require(manifest.get("status") == READY_STATUS, "manifest_status")
    require(manifest.get("claim_boundary") == CLAIM_BOUNDARY, "manifest_claim_boundary")
    require(manifest.get("trainer_result_claim_boundary") == TRAINER_RESULT_CLAIM_BOUNDARY, "manifest_trainer_claim")
    require((manifest.get("technical_supersession") or {}).get("bundle_revision") == BUNDLE_REVISION, "manifest_revision")
    require(pathlib.Path(manifest.get("runtime_root", "")) == runtime_root, "manifest_runtime_root")
    require(manifest.get("sealed_evaluation_access_count") == 0, "manifest_sealed_access")
    require(manifest.get("prediction_metrics_access_count") == 0, "manifest_prediction_access")
    require((manifest.get("calibration_contract") or {}).get("frozen_lane_contact_weights") == EXPECTED_WEIGHTS, "manifest_lane_weights")
    require(freeze.get("schema_version") == FREEZE_SCHEMA, "freeze_schema")
    require(freeze.get("status") == FREEZE_STATUS, "freeze_status")
    require(freeze.get("manifest_sha256") == sha256_file(manifest_path), "freeze_manifest_sha")
    require(freeze.get("claim_boundary") == CLAIM_BOUNDARY, "freeze_claim_boundary")
    require(freeze.get("trainer_result_claim_boundary") == TRAINER_RESULT_CLAIM_BOUNDARY, "freeze_trainer_claim")
    require(freeze.get("bundle_revision") == BUNDLE_REVISION, "freeze_revision")
    require(freeze.get("frozen_lane_contact_weights") == EXPECTED_WEIGHTS, "freeze_lane_weights")
    require(freeze.get("sealed_evaluation_access_count") == 0, "freeze_sealed_access")
    require(freeze.get("prediction_metrics_access_count") == 0, "freeze_prediction_access")
    require(freeze.get("v4_f_test32_access_count") == 0, "freeze_test32_access")
    return manifest, freeze


def read_training_table(manifest: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    record = manifest["artifacts"]["training_tsv"]
    path = safe_path(pathlib.Path(record["node1_path"]), "training_tsv")
    require(sha256_file(path) == record["sha256"], "training_tsv_sha")
    rows: dict[str, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"candidate_id", "teacher_source", "parent_framework_cluster", "outer_fold", "R_8X6B", "R_9E6Y", "R_dual_min"}
        require(required <= set(reader.fieldnames or ()), "training_fields")
        for row in reader:
            candidate = row["candidate_id"]
            require(candidate and candidate not in rows, f"training_candidate_duplicate:{candidate}")
            r8 = finite_float(row["R_8X6B"], f"training_R8:{candidate}")
            r9 = finite_float(row["R_9E6Y"], f"training_R9:{candidate}")
            dual = finite_float(row["R_dual_min"], f"training_Rdual:{candidate}")
            require(exact_min(r8, r9, dual), f"training_exact_min:{candidate}")
            rows[candidate] = row
    expected_count = int(manifest["expected_training_counts"]["rows"])
    require(len(rows) == expected_count, f"training_row_count:{len(rows)}:{expected_count}")
    return rows


def validate_outer_receipt(
    receipt_path: pathlib.Path,
    manifest_path: pathlib.Path,
    freeze_path: pathlib.Path,
    manifest: Mapping[str, Any],
    freeze: Mapping[str, Any],
    runtime_root: pathlib.Path,
) -> tuple[dict[str, Any], dict[tuple[str, int], Mapping[str, Any]]]:
    receipt = load_json(receipt_path, "outer_receipt")
    require(receipt.get("schema_version") == OUTER_SCHEMA, "outer_schema")
    require(receipt.get("status") == OUTER_STATUS, "outer_status")
    require(receipt.get("manifest_sha256") == sha256_file(manifest_path), "outer_manifest_sha")
    require(receipt.get("implementation_freeze_sha256") == sha256_file(freeze_path), "outer_freeze_sha")
    require(receipt.get("formal_artifact_sha256") == freeze["formal_artifact_sha256"], "outer_formal_artifacts")
    smoke_path = runtime_root / "status" / "SMOKE_RECEIPT.json"
    require(receipt.get("smoke_receipt_sha256") == sha256_file(smoke_path), "outer_smoke_sha")
    require(receipt.get("calibration_receipt_sha256") == manifest["artifacts"]["calibration_receipt"]["sha256"], "outer_calibration_sha")
    require(receipt.get("claim_boundary") == CLAIM_BOUNDARY, "outer_claim_boundary")
    require(receipt.get("trainer_result_claim_boundary") == TRAINER_RESULT_CLAIM_BOUNDARY, "outer_trainer_claim")
    require(receipt.get("bundle_revision") == BUNDLE_REVISION, "outer_revision")
    require(receipt.get("sealed_evaluation_access_count") == 0, "outer_sealed_access")
    require(receipt.get("prediction_metrics_access_count") == 0, "outer_prediction_access")
    outer = receipt.get("outer_development")
    require(isinstance(outer, dict) and set(outer) == set(LANES), "outer_lane_closure")
    records: dict[tuple[str, int], Mapping[str, Any]] = {}
    for lane in LANES:
        lane_records = outer[lane]
        require(isinstance(lane_records, list) and len(lane_records) == len(FOLDS), f"outer_fold_count:{lane}")
        for fold, record in enumerate(lane_records):
            require(record.get("lane") == lane and record.get("outer_fold") == fold, f"outer_identity:{lane}:{fold}")
            records[(lane, fold)] = record
    require(len(records) == 20, "outer_result_record_count")
    return receipt, records


def read_predictions(path: pathlib.Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"prediction_missing_or_symlink:{path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or ())
        require(tuple(fields) == PREDICTION_FIELDS, f"prediction_fields:{path}")
        rows = list(reader)
    require(rows, f"prediction_empty:{path}")
    return fields, rows


def validate_result(
    *, lane: str, fold: int, runtime_root: pathlib.Path, manifest: Mapping[str, Any],
    training: Mapping[str, Mapping[str, str]], outer_record: Mapping[str, Any]
) -> tuple[list[str], list[dict[str, str]], dict[str, str]]:
    output = runtime_root / "outer_development" / lane / f"fold_{fold}"
    result_path = output / "RESULT.json"
    log_path = output.parent / f"fold_{fold}.trainer.log"
    require(outer_record.get("result_sha256") == sha256_file(result_path), f"outer_result_sha:{lane}:{fold}")
    require(outer_record.get("log_sha256") == sha256_file(log_path), f"outer_log_sha:{lane}:{fold}")
    result = load_json(result_path, f"result:{lane}:{fold}")
    require(result.get("schema_version") == RESULT_SCHEMA, f"result_schema:{lane}:{fold}")
    require(result.get("status") == RESULT_STATUS, f"result_status:{lane}:{fold}")
    require(result.get("lane") == lane, f"result_lane:{lane}:{fold}")
    require(result.get("claim_boundary") == TRAINER_RESULT_CLAIM_BOUNDARY, f"result_claim:{lane}:{fold}")
    require(result.get("open_only") is True, f"result_open_only:{lane}:{fold}")
    require(result.get("v4_f_test32_access_count") == 0, f"result_test32_access:{lane}:{fold}")
    require(result.get("loss_weights") == {"receptor": 1.0, "dual": 0.5, **EXPECTED_WEIGHTS[lane]}, f"result_lane_weights:{lane}:{fold}")
    split_record = manifest["artifacts"][f"outer_split_{fold}"]
    split_path = safe_path(pathlib.Path(split_record["node1_path"]), f"outer_split_{fold}")
    require(sha256_file(split_path) == split_record["sha256"], f"split_sha:{fold}")
    split = load_json(split_path, f"split:{fold}")
    require(result.get("split") == split, f"result_split_exact:{lane}:{fold}")
    require(split.get("outer_fold") == fold and split.get("split_id") == f"outer_development_{fold}", f"split_identity:{fold}")
    require(split.get("open_only") is True and split.get("v4_f_test32_access_count") == 0, f"split_open_only:{fold}")
    train_parent_set = set(split["train_parents"])
    expected_source_counts: dict[str, dict[str, int]] = {}
    for source in sorted({row["teacher_source"] for row in training.values()}):
        selected = [row for row in training.values() if row["teacher_source"] == source and row["parent_framework_cluster"] in train_parent_set]
        if selected:
            expected_source_counts[source] = {
                "parents": len({row["parent_framework_cluster"] for row in selected}),
                "candidates": len(selected),
            }
    weight_audit = result.get("source_parent_candidate_weighting") or {}
    require(weight_audit.get("contract") == "0.5/source -> equal parent -> equal candidate", f"source_weight_contract:{lane}:{fold}")
    require(abs(float(weight_audit.get("sum")) - 1.0) <= 1e-12, f"source_weight_sum:{lane}:{fold}")
    source_weights = weight_audit.get("sources") or {}
    require(set(source_weights) == set(expected_source_counts), f"source_weight_sources:{lane}:{fold}")
    require(len(source_weights) == 2, f"source_weight_two_sources:{lane}:{fold}")
    for source, expected in expected_source_counts.items():
        observed = source_weights[source]
        require(observed.get("parents") == expected["parents"], f"source_weight_parents:{lane}:{fold}:{source}")
        require(observed.get("candidates") == expected["candidates"], f"source_weight_candidates:{lane}:{fold}:{source}")
        require(abs(float(observed.get("mass")) - 0.5) <= 1e-12, f"source_weight_mass:{lane}:{fold}:{source}")
    artifacts = result.get("artifacts")
    require(isinstance(artifacts, dict), f"result_artifacts:{lane}:{fold}")
    for label, artifact in artifacts.items():
        artifact_path = output / artifact["path"]
        require(artifact_path.parent == output, f"result_artifact_escape:{lane}:{fold}:{label}")
        require(sha256_file(artifact_path) == artifact["sha256"], f"result_artifact_sha:{lane}:{fold}:{label}")
    prediction_artifact = artifacts["predictions"]
    prediction_path = output / prediction_artifact["path"]
    fields, rows = read_predictions(prediction_path)
    require(len(rows) == prediction_artifact["rows"], f"prediction_row_receipt:{lane}:{fold}")
    score_parents = set(split["score_parents"])
    expected_candidates = {candidate for candidate, row in training.items() if row["parent_framework_cluster"] in score_parents}
    observed_candidates = {row["candidate_id"] for row in rows}
    require(len(observed_candidates) == len(rows), f"prediction_candidate_duplicate:{lane}:{fold}")
    require(observed_candidates == expected_candidates, f"prediction_candidate_closure:{lane}:{fold}")
    formula_sha = manifest["artifacts"]["contact_formula"]["sha256"]
    canonical: dict[str, str] = {}
    for row in rows:
        candidate = row["candidate_id"]
        source = training[candidate]
        require(row["lane"] == lane and row["split_id"] == split["split_id"], f"prediction_identity:{lane}:{fold}:{candidate}")
        require(row["teacher_source"] == source["teacher_source"], f"prediction_source:{lane}:{fold}:{candidate}")
        require(row["parent_framework_cluster"] == source["parent_framework_cluster"], f"prediction_parent:{lane}:{fold}:{candidate}")
        require(int(source["outer_fold"]) == fold, f"prediction_training_outer_fold:{lane}:{fold}:{candidate}")
        require(row["base_training_parent_set_sha256"] == split["train_parent_set_sha256"], f"prediction_train_parent_sha:{lane}:{fold}:{candidate}")
        require(int(row["base_training_parent_count"]) == len(split["train_parents"]), f"prediction_train_parent_count:{lane}:{fold}:{candidate}")
        require(row["base_model_receipt_sha256"] == artifacts["component_receipts"]["sha256"], f"prediction_component_sha:{lane}:{fold}:{candidate}")
        for target, source_name in (("R8", "R_8X6B"), ("R9", "R_9E6Y"), ("Rdual", "R_dual_min")):
            require(finite_float(row[f"truth_{target}"], f"truth:{lane}:{fold}:{candidate}:{target}") == finite_float(source[source_name], f"training:{candidate}:{target}"), f"prediction_truth:{lane}:{fold}:{candidate}:{target}")
        for prefix in ("truth", "M2", "neural"):
            r8 = finite_float(row[f"{prefix}_R8"], f"{prefix}_R8:{candidate}")
            r9 = finite_float(row[f"{prefix}_R9"], f"{prefix}_R9:{candidate}")
            dual = finite_float(row[f"{prefix}_Rdual"], f"{prefix}_Rdual:{candidate}")
            require(exact_min(r8, r9, dual), f"prediction_exact_min:{lane}:{fold}:{candidate}:{prefix}")
        if lane == "A_VHH_ONLY":
            require(row["contact_score_formula_sha256"] == "", f"prediction_A_formula_forbidden:{fold}:{candidate}")
        else:
            require(row["contact_score_formula_sha256"] == formula_sha, f"prediction_formula_sha:{lane}:{fold}:{candidate}")
        canonical[candidate] = "\0".join(
            [row["teacher_source"], row["parent_framework_cluster"]]
            + [row[f"truth_{target}"] for target in ("R8", "R9", "Rdual")]
            + [row[f"M2_{target}"] for target in ("R8", "R9", "Rdual")]
        )
    return fields, rows, canonical


def lane_report(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    report_metrics: dict[str, Any] = {}
    for component in ("M2", "neural"):
        report_metrics[component] = {}
        for target in ("R8", "R9", "Rdual"):
            truth = [float(row[f"truth_{target}"]) for row in rows]
            prediction = [float(row[f"{component}_{target}"]) for row in rows]
            report_metrics[component][target] = metrics(truth, prediction)
    source_strata = {}
    for source in sorted({row["teacher_source"] for row in rows}):
        subset = [row for row in rows if row["teacher_source"] == source]
        source_strata[source] = {
            "rows": len(subset),
            "parents": len({row["parent_framework_cluster"] for row in subset}),
            "M2_Rdual": metrics([float(row["truth_Rdual"]) for row in subset], [float(row["M2_Rdual"]) for row in subset]),
            "neural_Rdual": metrics([float(row["truth_Rdual"]) for row in subset], [float(row["neural_Rdual"]) for row in subset]),
        }
    parent_values = []
    for parent in sorted({row["parent_framework_cluster"] for row in rows}):
        subset = [row for row in rows if row["parent_framework_cluster"] == parent]
        value = spearman([float(row["truth_Rdual"]) for row in subset], [float(row["neural_Rdual"]) for row in subset]) if len(subset) >= 3 else None
        if value is not None:
            parent_values.append(value)
    return {
        "rows": len(rows),
        "parents": len({row["parent_framework_cluster"] for row in rows}),
        "teacher_source_counts": dict(sorted(Counter(row["teacher_source"] for row in rows).items())),
        "metrics": report_metrics,
        "source_strata": source_strata,
        "neural_Rdual_parent_macro_spearman": sum(parent_values) / len(parent_values) if parent_values else None,
        "neural_Rdual_parent_macro_parent_count": len(parent_values),
    }


def collect(
    *, manifest_path: pathlib.Path, freeze_path: pathlib.Path, runtime_root: pathlib.Path,
    output_root: pathlib.Path
) -> dict[str, Any]:
    safe_path(manifest_path, "manifest_path")
    safe_path(freeze_path, "freeze_path")
    safe_path(runtime_root, "runtime_root")
    safe_path(output_root, "output_root")
    require(runtime_root.is_dir() and not runtime_root.is_symlink(), "runtime_missing_or_symlink")
    collection_root = output_root / "collection_v1"
    terminal_path = output_root / "TERMINAL_RECEIPT.json"
    require(not os.path.lexists(collection_root), f"collection_output_exists:{collection_root}")
    require(not os.path.lexists(terminal_path), f"terminal_exists:{terminal_path}")
    manifest, freeze = validate_manifest_and_freeze(manifest_path, freeze_path, runtime_root)
    training = read_training_table(manifest)
    receipt_path = runtime_root / "status" / "OUTER_DEVELOPMENT_RECEIPT.json"
    outer_receipt, outer_records = validate_outer_receipt(
        receipt_path, manifest_path, freeze_path, manifest, freeze, runtime_root
    )
    temporary = output_root / f".collection_v1.tmp.{os.getpid()}"
    require(not os.path.lexists(temporary), f"collection_temporary_exists:{temporary}")
    (temporary / "oof").mkdir(parents=True)
    lane_rows: dict[str, list[dict[str, str]]] = {}
    result_hashes: dict[str, str] = {}
    prediction_hashes: dict[str, str] = {}
    reference_canonical: dict[str, str] | None = None
    score_parent_occurrences: Counter[str] = Counter()
    for fold in FOLDS:
        split = load_json(pathlib.Path(manifest["artifacts"][f"outer_split_{fold}"]["node1_path"]), f"split_for_partition:{fold}")
        score_parent_occurrences.update(split["score_parents"])
    expected_parents = {row["parent_framework_cluster"] for row in training.values()}
    require(set(score_parent_occurrences) == expected_parents, "score_parent_partition_set")
    require(set(score_parent_occurrences.values()) == {1}, "score_parent_partition_multiplicity")
    try:
        for lane in LANES:
            rows: list[dict[str, str]] = []
            canonical: dict[str, str] = {}
            fields: list[str] | None = None
            for fold in FOLDS:
                fold_fields, fold_rows, fold_canonical = validate_result(
                    lane=lane, fold=fold, runtime_root=runtime_root, manifest=manifest,
                    training=training, outer_record=outer_records[(lane, fold)],
                )
                fields = fold_fields if fields is None else fields
                require(fields == fold_fields, f"prediction_field_drift:{lane}:{fold}")
                for row in fold_rows:
                    row = dict(row)
                    row["outer_fold"] = str(fold)
                    rows.append(row)
                require(not set(canonical) & set(fold_canonical), f"lane_fold_candidate_overlap:{lane}:{fold}")
                canonical.update(fold_canonical)
                result_path = runtime_root / "outer_development" / lane / f"fold_{fold}" / "RESULT.json"
                prediction_path = result_path.parent / "base_score_predictions.tsv"
                result_hashes[f"{lane}/fold_{fold}"] = sha256_file(result_path)
                prediction_hashes[f"{lane}/fold_{fold}"] = sha256_file(prediction_path)
            require(set(canonical) == set(training), f"lane_candidate_closure:{lane}")
            if reference_canonical is None:
                reference_canonical = canonical
            else:
                require(canonical == reference_canonical, f"cross_lane_identity_truth_m2_mismatch:{lane}")
            rows.sort(key=lambda row: row["candidate_id"])
            output_path = temporary / "oof" / f"{lane}.outer_oof.tsv"
            output_fields = list(fields or ()) + ["outer_fold"]
            with output_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=output_fields, delimiter="\t", lineterminator="\n")
                writer.writeheader(); writer.writerows(rows)
            lane_rows[lane] = rows
        lane_metrics = {lane: lane_report(rows) for lane, rows in lane_rows.items()}
        comparisons = {}
        for left, right in (("B_TARGET_NO_CONTACT", "A_VHH_ONLY"), ("C_SPLIT_MARGINAL", "B_TARGET_NO_CONTACT"), ("D_SPLIT_PAIR", "C_SPLIT_MARGINAL"), ("D_SPLIT_PAIR", "A_VHH_ONLY")):
            left_value = lane_metrics[left]["metrics"]["neural"]["Rdual"]["spearman"]
            right_value = lane_metrics[right]["metrics"]["neural"]["Rdual"]["spearman"]
            require(left_value is not None and right_value is not None, f"comparison_spearman_undefined:{left}:{right}")
            comparisons[f"{left}_minus_{right}_neural_Rdual_spearman"] = left_value - right_value
        oof_hashes = {
            lane: sha256_file(temporary / "oof" / f"{lane}.outer_oof.tsv") for lane in LANES
        }
        metrics_payload = {
            "schema_version": "pvrig_v2_4_v2_2_2_four_lane_open_outer_oof_metrics_v1",
            "status": "PASS_V2_2_2_FOUR_LANE_OPEN_OUTER_OOF_METRICS_DESCRIPTIVE_ONLY",
            "rows_per_lane": len(training),
            "parents": len(expected_parents),
            "lanes": lane_metrics,
            "comparisons": comparisons,
            "result_sha256": result_hashes,
            "source_prediction_sha256": prediction_hashes,
            "materialized_oof_sha256": oof_hashes,
            "promotion_authorized": False,
            "strict_nested_stack_started": False,
            "automatic_strict_nested_stack_launch": False,
            "sealed_evaluation_access_count": 0,
            "prediction_metrics_access_count": 0,
            "v4_f_test32_access_count": 0,
            "claim_boundary": CLAIM_BOUNDARY,
            "trainer_result_claim_boundary": TRAINER_RESULT_CLAIM_BOUNDARY,
            "bundle_revision": BUNDLE_REVISION,
        }
        metrics_path = temporary / "OOF_METRICS.json"
        atomic_json(metrics_path, metrics_payload)
        validation_payload = {
            "schema_version": "pvrig_v2_4_v2_2_2_four_lane_outer_validation_v1",
            "status": "PASS_V2_2_2_ALL_20_RESULTS_HASH_PARENT_SOURCE_WEIGHT_EXACT_MIN_CLOSED",
            "outer_development_receipt_sha256": sha256_file(receipt_path),
            "ready_manifest_sha256": sha256_file(manifest_path),
            "implementation_freeze_sha256": sha256_file(freeze_path),
            "training_tsv_sha256": manifest["artifacts"]["training_tsv"]["sha256"],
            "result_count": 20,
            "prediction_rows_per_lane": len(training),
            "candidate_ids_per_lane": len(training),
            "parent_partition_exact": True,
            "teacher_source_exact": True,
            "truth_exact": True,
            "truth_m2_cross_lane_exact": True,
            "truth_m2_neural_exact_min": True,
            "frozen_lane_weights": EXPECTED_WEIGHTS,
            "claims_exact": True,
            "artifact_hashes_exact": True,
            "strict_nested_stack_started": False,
            "v4_f_test32_access_count": 0,
        }
        validation_path = temporary / "VALIDATION_REPORT.json"
        atomic_json(validation_path, validation_payload)
        os.replace(temporary, collection_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    terminal = {
        "schema_version": "pvrig_v2_4_v2_2_2_post_outer_terminal_receipt_v1",
        "status": "PASS_V2_2_2_OPEN_OUTER_COLLECTED_TERMINAL_STOP_NO_AUTOMATIC_NESTED_STACK",
        "outer_development_receipt_path": str(receipt_path),
        "outer_development_receipt_sha256": sha256_file(receipt_path),
        "ready_manifest_sha256": sha256_file(manifest_path),
        "implementation_freeze_sha256": sha256_file(freeze_path),
        "collection_root": str(collection_root),
        "oof_metrics_path": str(collection_root / "OOF_METRICS.json"),
        "oof_metrics_sha256": sha256_file(collection_root / "OOF_METRICS.json"),
        "validation_report_path": str(collection_root / "VALIDATION_REPORT.json"),
        "validation_report_sha256": sha256_file(collection_root / "VALIDATION_REPORT.json"),
        "materialized_oof_sha256": {
            lane: sha256_file(collection_root / "oof" / f"{lane}.outer_oof.tsv") for lane in LANES
        },
        "result_count": 20,
        "rows_per_lane": len(training),
        "frozen_lane_weights": EXPECTED_WEIGHTS,
        "claim_boundary": CLAIM_BOUNDARY,
        "trainer_result_claim_boundary": TRAINER_RESULT_CLAIM_BOUNDARY,
        "bundle_revision": BUNDLE_REVISION,
        "promotion_authorized": False,
        "strict_nested_stack_started": False,
        "automatic_strict_nested_stack_launch": False,
        "next_action_requires_independent_authorization": True,
        "sealed_evaluation_access_count": 0,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
    }
    atomic_json(terminal_path, terminal)
    return terminal


def watch(
    *, manifest_path: pathlib.Path, freeze_path: pathlib.Path, runtime_root: pathlib.Path,
    output_root: pathlib.Path, poll_seconds: float, timeout_seconds: float
) -> dict[str, Any]:
    require(poll_seconds > 0, "poll_seconds_nonpositive")
    require(timeout_seconds >= 0, "timeout_seconds_negative")
    output_root.mkdir(parents=True, exist_ok=True)
    status_path = output_root / "WATCHER_STATUS.json"
    terminal_path = output_root / "TERMINAL_RECEIPT.json"
    if terminal_path.is_file() and not terminal_path.is_symlink():
        terminal = load_json(terminal_path, "existing_terminal")
        require(terminal.get("schema_version") == "pvrig_v2_4_v2_2_2_post_outer_terminal_receipt_v1", "existing_terminal_schema")
        require(terminal.get("status") == "PASS_V2_2_2_OPEN_OUTER_COLLECTED_TERMINAL_STOP_NO_AUTOMATIC_NESTED_STACK", "existing_terminal_status")
        require(terminal.get("claim_boundary") == CLAIM_BOUNDARY, "existing_terminal_claim")
        require(terminal.get("trainer_result_claim_boundary") == TRAINER_RESULT_CLAIM_BOUNDARY, "existing_terminal_trainer_claim")
        require(terminal.get("bundle_revision") == BUNDLE_REVISION, "existing_terminal_revision")
        require(terminal.get("strict_nested_stack_started") is False, "existing_terminal_nested_started")
        require(terminal.get("automatic_strict_nested_stack_launch") is False, "existing_terminal_automatic_launch")
        require(terminal.get("v4_f_test32_access_count") == 0, "existing_terminal_test32_access")
        require(sha256_file(pathlib.Path(terminal["oof_metrics_path"])) == terminal["oof_metrics_sha256"], "existing_terminal_metrics_sha")
        require(sha256_file(pathlib.Path(terminal["validation_report_path"])) == terminal["validation_report_sha256"], "existing_terminal_validation_sha")
        return terminal
    receipt_path = runtime_root / "status" / "OUTER_DEVELOPMENT_RECEIPT.json"
    start = time.monotonic()
    while not receipt_path.is_file():
        elapsed = time.monotonic() - start
        if timeout_seconds and elapsed >= timeout_seconds:
            raise CollectionError("watch_timeout_before_outer_receipt")
        atomic_json(status_path, {
            "schema_version": "pvrig_v2_4_v2_2_2_post_outer_watcher_status_v1",
            "status": "WAITING_OUTER_DEVELOPMENT_RECEIPT",
            "outer_development_receipt_path": str(receipt_path),
            "elapsed_seconds": elapsed,
            "strict_nested_stack_started": False,
            "automatic_strict_nested_stack_launch": False,
            "v4_f_test32_access_count": 0,
        })
        time.sleep(poll_seconds)
    atomic_json(status_path, {
        "schema_version": "pvrig_v2_4_v2_2_2_post_outer_watcher_status_v1",
        "status": "OUTER_RECEIPT_PRESENT_VALIDATING_20_RESULTS",
        "outer_development_receipt_path": str(receipt_path),
        "strict_nested_stack_started": False,
        "automatic_strict_nested_stack_launch": False,
        "v4_f_test32_access_count": 0,
    })
    terminal = collect(
        manifest_path=manifest_path, freeze_path=freeze_path, runtime_root=runtime_root,
        output_root=output_root,
    )
    atomic_json(status_path, {
        "schema_version": "pvrig_v2_4_v2_2_2_post_outer_watcher_status_v1",
        "status": "TERMINAL_OPEN_OUTER_COLLECTION_COMPLETE_STOPPED",
        "terminal_receipt_path": str(terminal_path),
        "terminal_receipt_sha256": sha256_file(terminal_path),
        "strict_nested_stack_started": False,
        "automatic_strict_nested_stack_launch": False,
        "v4_f_test32_access_count": 0,
    })
    return terminal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-manifest", type=pathlib.Path, required=True)
    parser.add_argument("--implementation-freeze", type=pathlib.Path, required=True)
    parser.add_argument("--runtime-root", type=pathlib.Path, required=True)
    parser.add_argument("--output-root", type=pathlib.Path, required=True)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--timeout-seconds", type=float, default=0.0)
    parser.add_argument("--collect-now", action="store_true")
    args = parser.parse_args()
    function = collect if args.collect_now else watch
    kwargs = {
        "manifest_path": args.ready_manifest,
        "freeze_path": args.implementation_freeze,
        "runtime_root": args.runtime_root,
        "output_root": args.output_root,
    }
    if not args.collect_now:
        kwargs.update(poll_seconds=args.poll_seconds, timeout_seconds=args.timeout_seconds)
    result = function(**kwargs)
    print(json.dumps({
        "status": result["status"],
        "terminal_receipt": str(args.output_root / "TERMINAL_RECEIPT.json"),
        "strict_nested_stack_started": False,
        "automatic_strict_nested_stack_launch": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CollectionError, OSError, json.JSONDecodeError, ValueError, TypeError) as error:
        print(f"FAIL_V2_2_2_POST_OUTER_COLLECTION:{error}", file=os.sys.stderr)
        raise SystemExit(1)
