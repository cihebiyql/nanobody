#!/usr/bin/env python3
"""Recursively verify the frozen C2-refined Top7500 publication chain."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "pvrig_v2_19_c2_refined_top7500_publication_verification_v1"
STATUS = "PASS_C2_REFINED_TOP7500_PUBLICATION_VERIFIED"
CLAIM = (
    "Recursively hash-closed delivery of label-free computational Docking-geometry "
    "surrogates only; not binding, affinity, experimental blocking, calibrated "
    "probability, Docking truth, or Docking Gold."
)
PLAN_SCHEMA = "pvrig_v2_19_top30k_c2_shard_plan_v1"
PLAN_STATUS = "PASS_TOP30K_LABEL_FREE_C2_SHARD_PLAN"
RAW_SCHEMA = "pvrig_v2_5_label_free_coarse_pose_36d_v1"
RAW_RECEIPT_SCHEMA = "pvrig_v2_5_label_free_coarse_pose_pilot_v1"
RAW_RECEIPT_STATUS = "PASS_LABEL_FREE_COARSE_POSE_FEATURES"
STAGE_STATUS = "PASS_TOP150K_FOUR_MODEL_PRELIMINARY_SELECTION"
STAGING_STATUS = "PASS_TOP150K_LABEL_FREE_NBB2_ARCHIVE_STAGING"
C2_STATUS = "PASS_TOP30K_LABEL_FREE_C2_32D_CLOSURE"
ADAPTER_STATUS = "PASS_TOP30K_V2_11_C2_MULTIMODAL_INFERENCE"
FINAL_STATUS = "PASS_C2_REFINED_TOP7500_DOCKING_READY"
FORBIDDEN_FIELDS = (
    "truth", "teacher", "docking_score", "docking_gold", "haddock", "occlusion",
    "experimental", "geometry_tier",
)
ZERO_KEYS = {
    "candidate_docking_pose_files_opened", "teacher_label_files_opened",
    "teacher_label_values_read", "truth_columns_read", "v4_f_files_opened",
    "geometry_label_columns_read", "docking_truth_access_count",
    "experimental_label_access_count",
}
EXCLUSIONS = {
    "8x6b__pose_count", "9e6y__pose_count",
    "8x6b__top20_score_entropy", "9e6y__top20_score_entropy",
}
EXPECTED_C2_FEATURES = [
    f"C2__{name}" for name in (
        "8x6b__acceptable_count", "8x6b__acceptable_fraction",
        "8x6b__best_composite", "8x6b__top20_composite_mean",
        "8x6b__top20_composite_std", "8x6b__top20_composite_iqr",
        "8x6b__best_shape", "8x6b__best_hotspot", "8x6b__best_charge",
        "8x6b__best_clash_fraction", "8x6b__best_cdr_contact_fraction",
        "8x6b__best_cdr3_orientation", "9e6y__acceptable_count",
        "9e6y__acceptable_fraction", "9e6y__best_composite",
        "9e6y__top20_composite_mean", "9e6y__top20_composite_std",
        "9e6y__top20_composite_iqr", "9e6y__best_shape", "9e6y__best_hotspot",
        "9e6y__best_charge", "9e6y__best_clash_fraction",
        "9e6y__best_cdr_contact_fraction", "9e6y__best_cdr3_orientation",
        "dual__common_acceptable_count", "dual__common_acceptable_fraction",
        "dual__acceptable_jaccard", "dual__best_min_composite",
        "dual__top20_min_composite_mean", "dual__top20_min_composite_std",
        "dual__best_receptor_gap", "dual__pose_score_correlation",
    )
]
LANES = (
    "C2_COARSE_POSE_PCA8", "M2_C2_CONVEX", "S0_M2_C2_CONVEX",
    "SHALLOW_GBDT_CHALLENGER",
)
CHANNELS = {
    "C2_REFINED_CONSENSUS": 6750,
    "TARGET_MODEL_C2_SUPPORTED_RESCUE": 500,
    "PARENT_BALANCED_C2_DIVERSITY": 250,
}


class VerificationError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise VerificationError(message)


def sha256_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"not_regular:{path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def ordered_id_sha256(ids: Sequence[str]) -> str:
    return hashlib.sha256(("\n".join(ids) + "\n").encode()).hexdigest()


def same_path(recorded: str, path: Path) -> bool:
    return bool(recorded) and Path(recorded).resolve() == path.resolve()


def read_json(path: Path, role: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"{role}_not_regular")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{role}_invalid_json") from exc
    require(isinstance(value, dict), f"{role}_not_mapping")
    return value


def read_tsv(path: Path, role: str, *, allow_empty: bool = False) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"{role}_not_regular")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        require(fields and len(fields) == len(set(fields)), f"{role}_header")
        for field in fields:
            lowered = field.lower()
            require(not any(token in lowered for token in FORBIDDEN_FIELDS),
                    f"{role}_forbidden_field:{field}")
        rows = [dict(row) for row in reader]
    require(rows or allow_empty, f"{role}_empty")
    return fields, rows


def index_rows(rows: Sequence[Mapping[str, str]], role: str) -> dict[str, Mapping[str, str]]:
    result: dict[str, Mapping[str, str]] = {}
    for row in rows:
        candidate = row.get("candidate_id", "")
        require(candidate and candidate not in result, f"{role}_duplicate:{candidate}")
        result[candidate] = row
    return result


def finite(raw: str, label: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise VerificationError(f"invalid_numeric:{label}") from exc
    require(math.isfinite(value), f"nonfinite:{label}")
    return value


def walk_items(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key), item
            yield from walk_items(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_items(item)


def verify_declared_zeroes(receipt: Mapping[str, Any], role: str,
                           required: Sequence[str]) -> None:
    observed: dict[str, list[Any]] = {}
    for key, value in walk_items(receipt):
        if key in ZERO_KEYS:
            observed.setdefault(key, []).append(value)
    for key in required:
        require(key in observed, f"{role}_zero_key_missing:{key}")
    for key, values in observed.items():
        require(all(value == 0 for value in values), f"{role}_nonzero:{key}:{values}")


def verify_output_map(root: Path, outputs: Mapping[str, str], role: str) -> dict[str, str]:
    require(outputs, f"{role}_outputs_empty")
    result = {}
    for name, expected in outputs.items():
        require(Path(name).name == name and len(expected) == 64, f"{role}_output_record:{name}")
        path = root / name
        require(sha256_file(path) == expected, f"{role}_output_hash:{name}")
        result[name] = expected
    return result


def verify_sha256sums(path: Path, expected: Mapping[str, str], role: str) -> None:
    require(path.is_file() and not path.is_symlink(), f"{role}_sha256sums_not_regular")
    observed: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split(None, 1)
        require(len(parts) == 2, f"{role}_sha256sums_line")
        digest, name = parts[0], parts[1].lstrip(" *")
        require(name not in observed, f"{role}_sha256sums_duplicate:{name}")
        observed[name] = digest
    require(observed == dict(expected), f"{role}_sha256sums_contract")


def verify_fasta(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    require(path.is_file() and not path.is_symlink(), "fasta_not_regular")
    lines = path.read_text(encoding="utf-8").splitlines()
    require(len(lines) == 2 * len(rows), "fasta_line_count")
    for index, row in enumerate(rows):
        header, sequence = lines[2 * index:2 * index + 2]
        require(header.startswith(f">{row['candidate_id']} "), f"fasta_header:{index}")
        require(sequence == row["sequence"], f"fasta_sequence:{row['candidate_id']}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    require(not args.output_json.exists() and not args.output_json.is_symlink(), "output_exists")
    root = args.runtime_root.resolve()
    prelim = root / "four_model_preliminary_top7500_v1"
    staging = root / "nbb2_staging_full150k_v1"
    plan_root = root / "c2_top30k_shard_plan_v1"
    shard_root = root / "c2_top30k_shard_outputs_v1"
    c2_root = root / "c2_top30k_32d_v1"
    adapter_root = root / "c2_top30k_multimodal_predictions_v1"
    final_root = root / "c2_refined_top7500_docking_handoff_v1"

    assets = {
        "coarse_code": (args.coarse_code, args.coarse_code_sha256),
        "vendor_adapter": (args.vendor_adapter, args.vendor_adapter_sha256),
        "model_artifact": (args.model_artifact, args.model_artifact_sha256),
        "target_npz": (args.target_npz, args.target_npz_sha256),
        "target_pdb8": (args.target_pdb8, args.target_pdb8_sha256),
        "target_pdb9": (args.target_pdb9, args.target_pdb9_sha256),
    }
    asset_audit = {}
    for role, (path, expected) in assets.items():
        observed = sha256_file(path)
        require(observed == expected, f"asset_hash:{role}")
        asset_audit[role] = {"path": str(path.resolve()), "sha256": observed}

    stage_path = prelim / "STAGE1_TOP30000_FOR_C2.tsv"
    stage_receipt_path = prelim / "RUN_RECEIPT.json"
    stage_receipt = read_json(stage_receipt_path, "stage_receipt")
    require(stage_receipt.get("status") == STAGE_STATUS, "stage_status")
    stage_outputs = verify_output_map(prelim, stage_receipt.get("outputs", {}), "stage")
    require(stage_outputs.get(stage_path.name) == sha256_file(stage_path), "stage1_hash")
    require(stage_receipt.get("stage1_rows") == args.stage1_rows, "stage_receipt_rows")
    verify_declared_zeroes(stage_receipt, "stage", (
        "docking_truth_access_count", "experimental_label_access_count",
    ))
    stage_fields, stage_rows = read_tsv(stage_path, "stage1")
    require(len(stage_rows) == args.stage1_rows, "stage1_rows")
    require({"candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster"} <= set(stage_fields),
            "stage1_fields")
    stage_by_id = index_rows(stage_rows, "stage1")
    stage_ids = [row["candidate_id"] for row in stage_rows]
    for row in stage_rows:
        require(sha256_text(row["sequence"]) == row["sequence_sha256"],
                f"stage_sequence_hash:{row['candidate_id']}")

    staging_receipt_path = staging / "top150k_nbb2_staging_receipt_v1.json"
    staging_receipt = read_json(staging_receipt_path, "staging_receipt")
    require(staging_receipt.get("status") == STAGING_STATUS, "staging_status")
    staging_outputs = verify_output_map(staging, staging_receipt.get("outputs", {}), "staging")
    require(set(staging_outputs) == {
        "top150k_m2_structure_manifest_v1.tsv", "top150k_graph_structure_manifest_v1.tsv",
        "top150k_archive_audit_v1.tsv",
    }, "staging_output_set")
    require(staging_receipt.get("counts", {}).get("candidates") >= args.stage1_rows,
            "staging_candidate_count")
    verify_declared_zeroes(staging_receipt, "staging", (
        "candidate_docking_pose_files_opened", "geometry_label_columns_read",
    ))
    structure_path = staging / "top150k_m2_structure_manifest_v1.tsv"
    structure_fields, structure_rows = read_tsv(structure_path, "structure")
    require({"candidate_id", "sequence_sha256", "parent_framework_cluster", "monomer_path",
             "monomer_sha256", "cdr1_range", "cdr2_range", "cdr3_range"} <= set(structure_fields),
            "structure_fields")
    structure_by_id = index_rows(structure_rows, "structure")

    plan_path = plan_root / "SHARD_PLAN.json"
    plan_sha = sha256_file(plan_path)
    plan = read_json(plan_path, "plan")
    require(plan.get("schema_version") == PLAN_SCHEMA and plan.get("status") == PLAN_STATUS,
            "plan_contract")
    require(plan.get("counts") == {"rows": args.stage1_rows, "shards": args.shards}, "plan_counts")
    require(plan.get("inputs", {}).get("preliminary_sha256") == sha256_file(stage_path),
            "plan_stage_hash")
    require(plan.get("inputs", {}).get("structure_manifest_sha256") == sha256_file(structure_path),
            "plan_structure_hash")
    verify_declared_zeroes(plan, "plan", ("truth_columns_read", "candidate_docking_pose_files_opened"))
    require(len(plan.get("shards", [])) == args.shards, "plan_shards")

    combined_ids: list[str] = []
    manifest_rows_by_shard: dict[str, list[dict[str, str]]] = {}
    for shard in plan["shards"]:
        shard_id = shard["shard_id"]
        manifest_path = plan_root / shard["relative_path"]
        require(sha256_file(manifest_path) == shard["sha256"], f"manifest_hash:{shard_id}")
        fields, rows = read_tsv(manifest_path, f"manifest:{shard_id}")
        require(len(rows) == shard["rows"], f"manifest_rows:{shard_id}")
        ids = [row["candidate_id"] for row in rows]
        require(ordered_id_sha256(ids) == shard["ordered_candidate_id_sha256"],
                f"manifest_order_hash:{shard_id}")
        require({"candidate_id", "sequence_sha256", "parent_framework_cluster", "monomer_pdb",
                 "monomer_sha256", "cdr1_range", "cdr2_range", "cdr3_range"} <= set(fields),
                f"manifest_fields:{shard_id}")
        for row in rows:
            candidate = row["candidate_id"]
            require(candidate in stage_by_id and candidate in structure_by_id,
                    f"manifest_candidate:{candidate}")
            stage_row, structure_row = stage_by_id[candidate], structure_by_id[candidate]
            require(row["sequence_sha256"] == stage_row["sequence_sha256"] == structure_row["sequence_sha256"],
                    f"manifest_sequence:{candidate}")
            require(row["parent_framework_cluster"] == stage_row["parent_framework_cluster"] == structure_row["parent_framework_cluster"],
                    f"manifest_parent:{candidate}")
            monomer = Path(row["monomer_pdb"])
            require(monomer.is_absolute() and same_path(structure_row["monomer_path"], monomer),
                    f"manifest_monomer_path:{candidate}")
            require(row["monomer_sha256"] == structure_row["monomer_sha256"] == sha256_file(monomer),
                    f"manifest_monomer_hash:{candidate}")
        combined_ids.extend(ids)
        manifest_rows_by_shard[shard_id] = rows
    require(combined_ids == stage_ids, "plan_stage_order_closure")
    require(plan.get("ordered_candidate_id_sha256") == ordered_id_sha256(stage_ids), "plan_ordered_hash")
    require(plan.get("candidate_set_sha256") == ordered_id_sha256(sorted(stage_ids)), "plan_set_hash")

    targets = {
        "target_npz": assets["target_npz"], "target_pdb8": assets["target_pdb8"],
        "target_pdb9": assets["target_pdb9"],
    }
    observed_shards = []
    for shard in plan["shards"]:
        shard_id = shard["shard_id"]
        rows = manifest_rows_by_shard[shard_id]
        table = shard_root / shard_id / "coarse_pose_features_36d.tsv"
        receipt_path = shard_root / shard_id / "FEATURE_RECEIPT.json"
        fields, feature_rows = read_tsv(table, f"raw_features:{shard_id}")
        require(len(feature_rows) == len(rows), f"raw_rows:{shard_id}")
        require([row["candidate_id"] for row in feature_rows] == [row["candidate_id"] for row in rows],
                f"raw_order:{shard_id}")
        numeric = [field for field in fields if field not in {"candidate_id", "monomer_sha256", "feature_schema"}]
        require(len(numeric) == 36 and EXCLUSIONS <= set(numeric), f"raw_feature_count:{shard_id}")
        require([f"C2__{name}" for name in numeric if name not in EXCLUSIONS] == EXPECTED_C2_FEATURES,
                f"raw_feature_order:{shard_id}")
        for source, row in zip(rows, feature_rows):
            require(row["feature_schema"] == RAW_SCHEMA and row["monomer_sha256"] == source["monomer_sha256"],
                    f"raw_row_closure:{row['candidate_id']}")
            for name in numeric:
                finite(row[name], f"raw:{row['candidate_id']}:{name}")
        receipt = read_json(receipt_path, f"raw_receipt:{shard_id}")
        require(receipt.get("schema_version") == RAW_RECEIPT_SCHEMA and receipt.get("status") == RAW_RECEIPT_STATUS,
                f"raw_receipt_contract:{shard_id}")
        require(receipt.get("candidate_count") == len(rows) and receipt.get("feature_count") == 36 and
                receipt.get("pose_count_per_receptor") == 300 and receipt.get("all_features_finite") is True,
                f"raw_receipt_counts:{shard_id}")
        verify_declared_zeroes(receipt, f"raw:{shard_id}", (
            "candidate_docking_pose_files_opened", "teacher_label_files_opened", "v4_f_files_opened",
        ))
        require(receipt.get("inputs", {}).get("candidate_manifest", {}).get("sha256") == shard["sha256"],
                f"raw_manifest_hash:{shard_id}")
        for role, (path, expected) in targets.items():
            record = receipt.get("inputs", {}).get(role, {})
            require(record.get("sha256") == expected and same_path(record.get("path", ""), path),
                    f"raw_target:{shard_id}:{role}")
        outputs = receipt.get("outputs", {})
        require(len(outputs) == 1, f"raw_output_count:{shard_id}")
        recorded_path, recorded_hash = next(iter(outputs.items()))
        feature_sha = sha256_file(table)
        require(same_path(recorded_path, table) and recorded_hash == feature_sha,
                f"raw_output_hash:{shard_id}")
        observed_shards.append({"shard_id": shard_id, "rows": len(rows),
                                "feature_sha256": feature_sha, "receipt_sha256": sha256_file(receipt_path)})

    c2_table = c2_root / "TOP30000_C2_32D.tsv"
    c2_receipt_path = c2_root / "RUN_RECEIPT.json"
    c2_receipt = read_json(c2_receipt_path, "c2_receipt")
    require(c2_receipt.get("status") == C2_STATUS, "c2_status")
    require(c2_receipt.get("counts") == {"rows": args.stage1_rows, "raw_features": 36,
                                          "model_features": 32, "shards": args.shards}, "c2_counts")
    require(c2_receipt.get("inputs", {}).get("plan_sha256") == plan_sha, "c2_plan_hash")
    require(c2_receipt.get("feature_names") == EXPECTED_C2_FEATURES, "c2_feature_names")
    require(set(c2_receipt.get("predeclared_exclusions", [])) == EXCLUSIONS, "c2_exclusions")
    require(c2_receipt.get("shards") == observed_shards, "c2_shard_audit")
    for role, (_path, expected) in targets.items():
        require(c2_receipt.get("inputs", {}).get(role + "_sha256") == expected,
                f"c2_target_hash:{role}")
    c2_sha = sha256_file(c2_table)
    require(c2_receipt.get("output", {}).get("sha256") == c2_sha and
            same_path(c2_receipt.get("output", {}).get("path", ""), c2_table), "c2_output")
    verify_declared_zeroes(c2_receipt, "c2", (
        "candidate_docking_pose_files_opened", "teacher_label_values_read",
    ))
    c2_fields, c2_rows = read_tsv(c2_table, "c2_table")
    require(c2_fields == ["candidate_id", "sequence_sha256", "parent_framework_cluster", *EXPECTED_C2_FEATURES],
            "c2_table_feature_order")
    require([row["candidate_id"] for row in c2_rows] == stage_ids, "c2_table_order")
    for row in c2_rows:
        source = stage_by_id[row["candidate_id"]]
        require(row["sequence_sha256"] == source["sequence_sha256"] and
                row["parent_framework_cluster"] == source["parent_framework_cluster"],
                f"c2_table_closure:{row['candidate_id']}")
        for name in EXPECTED_C2_FEATURES:
            finite(row[name], f"c2:{row['candidate_id']}:{name}")
    verify_sha256sums(c2_root / "SHA256SUMS", {
        c2_table.name: c2_sha, c2_receipt_path.name: sha256_file(c2_receipt_path),
    }, "c2")

    adapter_table = adapter_root / "TOP30000_C2_MULTIMODAL_PREDICTIONS.tsv"
    adapter_receipt_path = adapter_root / "RUN_RECEIPT.json"
    adapter_receipt = read_json(adapter_receipt_path, "adapter_receipt")
    require(adapter_receipt.get("status") == ADAPTER_STATUS, "adapter_status")
    require(adapter_receipt.get("counts") == {"rows": args.stage1_rows, "lanes": 4, "c2_features": 32},
            "adapter_counts")
    require(adapter_receipt.get("lanes") == list(LANES), "adapter_lanes")
    inputs = adapter_receipt.get("inputs", {})
    require(inputs.get("vendor_adapter", {}).get("sha256") == args.vendor_adapter_sha256,
            "adapter_vendor_hash")
    require(inputs.get("artifact", {}).get("sha256") == args.model_artifact_sha256,
            "adapter_artifact_hash")
    require(inputs.get("c2_features", {}).get("sha256") == c2_sha,
            "adapter_c2_hash")
    require(inputs.get("stage1_sha256") == sha256_file(stage_path), "adapter_stage_hash")
    base_path = root / "s0_m2_predictions_full150k_v1" / "PRODUCTION_PREDICTIONS_RANK_READY.tsv"
    require(inputs.get("base_predictions_sha256") == sha256_file(base_path), "adapter_base_hash")
    adapter_sha = sha256_file(adapter_table)
    require(adapter_receipt.get("output", {}).get("sha256") == adapter_sha and
            same_path(adapter_receipt.get("output", {}).get("path", ""), adapter_table), "adapter_output")
    verify_declared_zeroes(adapter_receipt, "adapter", (
        "candidate_docking_pose_files_opened", "teacher_label_values_read",
    ))
    adapter_fields, adapter_rows = read_tsv(adapter_table, "adapter_table")
    require(len(adapter_rows) == args.stage1_rows and [r["candidate_id"] for r in adapter_rows] == stage_ids,
            "adapter_order")
    for lane in LANES:
        needed = {f"{lane}__R8", f"{lane}__R9", f"{lane}__Rdual_exact_min",
                  f"{lane}__Rdual_rank", f"{lane}__Rdual_rank_percentile"}
        require(needed <= set(adapter_fields), f"adapter_lane_fields:{lane}")
        ranks = []
        for row in adapter_rows:
            r8 = finite(row[f"{lane}__R8"], f"adapter:{lane}:R8")
            r9 = finite(row[f"{lane}__R9"], f"adapter:{lane}:R9")
            dual = finite(row[f"{lane}__Rdual_exact_min"], f"adapter:{lane}:dual")
            require(abs(dual - min(r8, r9)) <= 1e-9, f"adapter_exact_min:{lane}:{row['candidate_id']}")
            rank = int(row[f"{lane}__Rdual_rank"]); ranks.append(rank)
            pct = finite(row[f"{lane}__Rdual_rank_percentile"], f"adapter:{lane}:pct")
            require(abs(pct - (1 - (rank - 1) / max(1, args.stage1_rows - 1))) <= 1e-9,
                    f"adapter_percentile:{lane}:{row['candidate_id']}")
        require(sorted(ranks) == list(range(1, args.stage1_rows + 1)), f"adapter_ranks:{lane}")
    verify_sha256sums(adapter_root / "SHA256SUMS", {
        adapter_table.name: adapter_sha, adapter_receipt_path.name: sha256_file(adapter_receipt_path),
    }, "adapter")

    final_table = final_root / "TOP7500_C2_REFINED.tsv"
    final_fasta = final_root / "TOP7500_C2_REFINED.fasta"
    final_core = final_root / "TOP7500_C2_REFINED_HIGH_CONFIDENCE_CORE.tsv"
    final_receipt_path = final_root / "RUN_RECEIPT.json"
    final_receipt = read_json(final_receipt_path, "final_receipt")
    require(final_receipt.get("status") == FINAL_STATUS and final_receipt.get("rows") == args.final_rows,
            "final_contract")
    expected_channels = dict(CHANNELS)
    if args.final_rows != 7500:
        expected_channels = json.loads(args.expected_channels_json)
    require(final_receipt.get("channels") == expected_channels, "final_receipt_channels")
    require(final_receipt.get("inputs") == {"stage1_sha256": sha256_file(stage_path),
                                             "c2_sha256": adapter_sha}, "final_inputs")
    verify_declared_zeroes(final_receipt, "final", (
        "candidate_docking_pose_files_opened", "teacher_label_values_read",
    ))
    final_outputs = final_receipt.get("outputs", {})
    expected_final_names = {final_table.name, final_fasta.name, final_core.name}
    require(set(final_outputs) == expected_final_names, "final_output_set")
    for path in (final_table, final_fasta, final_core):
        require(final_outputs[path.name] == sha256_file(path), f"final_output_hash:{path.name}")
    final_fields, final_rows = read_tsv(final_table, "final_table")
    require(len(final_rows) == args.final_rows, "final_rows")
    final_by_id = index_rows(final_rows, "final")
    require(set(final_by_id) <= set(stage_by_id), "final_subset")
    for index, row in enumerate(final_rows, 1):
        source = stage_by_id[row["candidate_id"]]
        require(int(row["final_c2_refined_rank"]) == index, f"final_rank:{index}")
        require(row["sequence"] == source["sequence"] and row["sequence_sha256"] == source["sequence_sha256"] and
                row["parent_framework_cluster"] == source["parent_framework_cluster"],
                f"final_closure:{row['candidate_id']}")
        require(row["high_confidence_core_flag"] in {"true", "false"},
                f"final_core_flag:{row['candidate_id']}")
    require(dict(Counter(row["selection_channel"] for row in final_rows)) == expected_channels,
            "final_channel_counts")
    core_fields, core_rows = read_tsv(final_core, "final_core", allow_empty=True)
    expected_core = [row for row in final_rows if row["high_confidence_core_flag"] == "true"]
    require(core_fields == final_fields and core_rows == expected_core, "final_core_closure")
    require(final_receipt.get("high_confidence_core_rows") == len(core_rows), "final_core_receipt_count")
    verify_fasta(final_fasta, final_rows)
    final_sum_expected = {path.name: sha256_file(path) for path in
                          (final_table, final_fasta, final_core, final_receipt_path)}
    verify_sha256sums(final_root / "SHA256SUMS", final_sum_expected, "final")

    receipt = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_boundary": CLAIM,
        "runtime_root": str(root),
        "counts": {"stage1_rows": len(stage_rows), "staging_rows": len(structure_rows),
                   "shards": len(plan["shards"]), "raw_feature_rows": sum(s["rows"] for s in observed_shards),
                   "c2_rows": len(c2_rows), "adapter_rows": len(adapter_rows),
                   "final_rows": len(final_rows), "high_confidence_core_rows": len(core_rows)},
        "chain": {
            "stage1_receipt_sha256": sha256_file(stage_receipt_path),
            "stage1_sha256": sha256_file(stage_path),
            "staging_receipt_sha256": sha256_file(staging_receipt_path),
            "structure_manifest_sha256": sha256_file(structure_path),
            "shard_plan_sha256": plan_sha,
            "c2_receipt_sha256": sha256_file(c2_receipt_path),
            "c2_32d_sha256": c2_sha,
            "adapter_receipt_sha256": sha256_file(adapter_receipt_path),
            "adapter_predictions_sha256": adapter_sha,
            "final_receipt_sha256": sha256_file(final_receipt_path),
            "final_sha256sums_sha256": sha256_file(final_root / "SHA256SUMS"),
        },
        "assets": asset_audit,
        "final_outputs": final_sum_expected,
        "channels": expected_channels,
        "invariants": {
            "recursive_receipt_and_hash_closure": True,
            "candidate_sequence_parent_closure": True,
            "selected_monomer_hashes_recomputed": True,
            "raw_and_32d_feature_order_exact": True,
            "exact_min_and_rank_percentiles_verified": True,
            "final_quota_fasta_core_and_sha256sums_exact": True,
            "scoring_or_ranking_modified": False,
            "automatic_cleanup_or_in_place_retry": False,
            "candidate_docking_pose_files_opened": 0,
            "teacher_label_values_read": 0,
        },
        "verifier_sha256": sha256_file(Path(__file__)),
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    temporary = args.output_json.with_name(f".{args.output_json.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, args.output_json)
    return receipt


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runtime-root", type=Path, required=True)
    for role in ("coarse-code", "vendor-adapter", "model-artifact", "target-npz", "target-pdb8", "target-pdb9"):
        p.add_argument(f"--{role}", type=Path, required=True)
        p.add_argument(f"--{role}-sha256", required=True)
    p.add_argument("--output-json", type=Path, required=True)
    p.add_argument("--stage1-rows", type=int, default=30000)
    p.add_argument("--shards", type=int, default=32)
    p.add_argument("--final-rows", type=int, default=7500)
    p.add_argument("--expected-channels-json", default='{}')
    return p


if __name__ == "__main__":
    print(json.dumps(run(parser().parse_args()), sort_keys=True))
