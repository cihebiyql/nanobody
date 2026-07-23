#!/usr/bin/env python3
"""Validate and atomically publish the Top150K B-only V3.1 recovery terminal."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "pvrig_top150k_b_only_recovery_validation_v3_1"
PREFLIGHT_STATUS = "PASS_EXISTING_GRAPH_L1_AND_V2_FAILURE_CLOSED"
TERMINAL_STATUS = "PASS_GRAPH_L1_B_FULL150K_COMPLETE_VIA_B_ONLY_RECOVERY_V3_1"
INFERENCE_STATUS = "PASS_TRUTH_FREE_CLEAN_ATTENTION_CHECKPOINT_ENSEMBLE_INFERENCE"
PROFILE_STATUS = "PASS_EXACT_V211_B4_CHECKPOINT_PROFILE"
PROFILE_ID = "pvrig_v211_full10644_b4_exact_production_profile_v3"
GRAPH_STATUS = "PASS_LABEL_FREE_MONOMER_GRAPH_CACHE"
COMPACT_FIELDS = ("candidate_id", "sequence_sha256", "sequence", "parent_framework_cluster")
PREDICTION_NAME = "clean_attention_checkpoint_ensemble_predictions.tsv"
EXPECTED_B_SEEDS = (43, 917, 1931, 3253)
EXPECTED_B_HASHES = (
    "0a09ca095cda3eb0ba75582f9a0dcbfa2fd2e3007fe6733020b7a79b897c7723",
    "642984c4b2e07016fd1698b43fbb8851ce6f77fc6fd279e7eab9c9142746e9ca",
    "0e8ab9b9b0d6ce07bd2fa12ed3118577c883a491e9b275ea672c2050bac311a5",
    "6a5ccdb459d0aa7d3126122ebfb2919228a0c1c529382fb1db4d40ab179e662f",
)
EXPECTED_SCHEMA = "pvrig_v2_11_full10644_clean_attention_runner_v1"
EXPECTED_SPLIT = "v29_canonical_release_v1_joint_cdr3_D1"
ENSEMBLE_FIELDS = (
    "ensemble_R_8X6B_mean", "ensemble_R_8X6B_std", "ensemble_R_9E6Y_mean",
    "ensemble_R_9E6Y_std", "ensemble_R_dual_mean", "ensemble_R_dual_std",
    "ensemble_exact_min_of_receptor_means", "ensemble_receptor_gap_abs",
    "ensemble_checkpoint_rank_std", "ensemble_conservative_R_dual_score",
    "ensemble_R_dual_mean_rank", "ensemble_conservative_rank",
    "ensemble_conservative_top_fraction", "ensemble_checkpoint_count", "claim_boundary",
)


class RecoveryValidationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecoveryValidationError(message)


def sha256_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"regular_file_required:{path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Mapping[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"json_file_invalid:{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(payload, Mapping), f"json_not_object:{path}")
    return payload


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    require(not path.exists(), f"publication_target_exists:{path}")
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


def load_manifest(path: Path, expected_rows: int) -> list[tuple[str, str, str, str]]:
    require(path.is_file() and not path.is_symlink(), "manifest_invalid")
    rows: list[tuple[str, str, str, str]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(tuple(reader.fieldnames or ()) == COMPACT_FIELDS, "manifest_fields_invalid")
        for row in reader:
            identity = tuple(row[field] for field in COMPACT_FIELDS)
            require(all(identity), "manifest_identity_empty")
            rows.append(identity)  # type: ignore[arg-type]
    require(len(rows) == expected_rows, f"manifest_rows:{len(rows)}")
    require(len({row[0] for row in rows}) == expected_rows, "manifest_candidate_duplicate")
    return rows


def expected_prediction_header(checkpoint_count: int) -> tuple[str, ...]:
    fields = list(COMPACT_FIELDS)
    for index in range(checkpoint_count):
        prefix = f"checkpoint_{index:03d}"
        fields.extend((f"{prefix}_R_8X6B", f"{prefix}_R_9E6Y", f"{prefix}_R_dual_min"))
    fields.extend(ENSEMBLE_FIELDS)
    return tuple(fields)


def validate_prediction_table(
    path: Path,
    manifest_rows: Sequence[tuple[str, str, str, str]],
    checkpoint_count: int,
) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"prediction_table_invalid:{path}")
    prefixes = tuple(f"checkpoint_{index:03d}" for index in range(checkpoint_count))
    count = 0
    max_exact_error = 0.0
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = tuple(reader.fieldnames or ())
        require(fields == expected_prediction_header(checkpoint_count), f"prediction_header_not_exact_profile:{path}")
        for prefix in prefixes:
            for suffix in ("R_8X6B", "R_9E6Y", "R_dual_min"):
                require(f"{prefix}_{suffix}" in fields, f"prediction_field_missing:{prefix}_{suffix}")
        numeric_fields = [field for field in fields if field not in {*COMPACT_FIELDS, "claim_boundary"}]
        for expected, row in zip(manifest_rows, reader):
            observed = tuple(row[field] for field in COMPACT_FIELDS)
            require(observed == expected, f"prediction_identity_or_order_mismatch:{expected[0]}")
            require(row.get("claim_boundary", "").strip() != "", f"claim_boundary_empty:{expected[0]}")
            for field in numeric_fields:
                require(math.isfinite(float(row[field])), f"prediction_nonfinite:{expected[0]}:{field}")
            require(int(row["ensemble_checkpoint_count"]) == checkpoint_count, f"checkpoint_count_row:{expected[0]}")
            for prefix in prefixes:
                r8 = float(row[f"{prefix}_R_8X6B"])
                r9 = float(row[f"{prefix}_R_9E6Y"])
                dual = float(row[f"{prefix}_R_dual_min"])
                error = abs(dual - min(r8, r9))
                require(error <= 1e-8, f"checkpoint_exact_min_row:{expected[0]}:{prefix}:{error}")
                max_exact_error = max(max_exact_error, error)
            r8_mean = float(row["ensemble_R_8X6B_mean"])
            r9_mean = float(row["ensemble_R_9E6Y_mean"])
            derived = float(row["ensemble_exact_min_of_receptor_means"])
            error = abs(derived - min(r8_mean, r9_mean))
            require(error <= 1e-8, f"ensemble_exact_min_row:{expected[0]}:{error}")
            require(abs(float(row["ensemble_receptor_gap_abs"]) - abs(r8_mean-r9_mean)) <= 1e-8, f"receptor_gap_row:{expected[0]}")
            count += 1
        require(count == len(manifest_rows), f"prediction_rows:{count}")
        require(next(reader, None) is None, "prediction_extra_rows")
    return {"rows": count, "sha256": sha256_file(path), "max_exact_min_abs_error": max_exact_error}


def validate_inference_receipt(
    path: Path,
    output_path: Path,
    manifest_path: Path,
    expected_rows: int,
    expected_checkpoints: int,
) -> Mapping[str, Any]:
    receipt = load_json(path)
    require(receipt.get("status") == INFERENCE_STATUS, f"inference_status:{path}")
    counts = receipt.get("counts", {})
    require(counts.get("rows") == expected_rows, f"inference_rows:{path}")
    require(counts.get("checkpoints") == expected_checkpoints, f"inference_checkpoint_count:{path}")
    firewall = receipt.get("input_firewall", {})
    for key in ("teacher_fields_read", "truth_fields_read", "docking_pose_files_opened", "contact_supervision_fields_read", "candidate_id_model_input_count", "parent_id_model_input_count"):
        require(firewall.get(key) == 0, f"inference_firewall:{path}:{key}")
    inference = receipt.get("inference", {})
    batch_size = int(inference.get("batch_size", 0))
    require(batch_size == 64, f"inference_batch_size:{path}:{batch_size}")
    batches = math.ceil(expected_rows / batch_size)
    require(inference.get("backbone_forward_batches") == batches, f"inference_backbone_batches:{path}")
    require(inference.get("head_forward_batches") == batches * expected_checkpoints, f"inference_head_batches:{path}")
    require(inference.get("shared_backbone_once_per_batch") is True, f"inference_backbone_not_shared:{path}")
    require(inference.get("exact_min_inference") is True, f"inference_exact_min_false:{path}")
    require(float(inference.get("exact_min_max_abs_error", math.inf)) <= 1e-7, f"inference_exact_min_error:{path}")
    require(receipt.get("outputs", {}).get(PREDICTION_NAME) == sha256_file(output_path), f"inference_output_hash:{path}")
    require(receipt.get("input_bindings", {}).get("manifest", {}).get("sha256") == sha256_file(manifest_path), f"inference_manifest_hash:{path}")
    return receipt


def validate_graph_receipt(path: Path, expected_rows: int) -> tuple[Mapping[str, Any], dict[str, str]]:
    receipt = load_json(path)
    require(receipt.get("status") == GRAPH_STATUS, "graph_status")
    require(receipt.get("counts", {}).get("entities") == expected_rows, "graph_entity_count")
    forbidden = receipt.get("forbidden_model_features", [])
    require("candidate_docking_pose" in forbidden and "teacher_source" in forbidden, "graph_firewall_missing")
    output_hashes = receipt.get("outputs")
    require(isinstance(output_hashes, Mapping), "graph_output_hashes_missing")
    cache = path.parent / "graph_cache_v2.npz"
    manifest = path.parent / "graph_manifest_v2.tsv"
    cache_sha = sha256_file(cache)
    manifest_sha = sha256_file(manifest)
    require(output_hashes.get("graph_cache_v2.npz") == cache_sha, "graph_cache_receipt_hash_mismatch")
    require(output_hashes.get("graph_manifest_v2.tsv") == manifest_sha, "graph_manifest_receipt_hash_mismatch")
    return receipt, {
        "graph_receipt": sha256_file(path),
        "graph_cache_v2.npz": cache_sha,
        "graph_manifest_v2.tsv": manifest_sha,
    }


def build_preflight(
    *, manifest: Path, graph_receipt: Path, l1_output: Path, l1_receipt: Path,
    failed_b_log: Path, expected_rows: int,
) -> dict[str, Any]:
    manifest_rows = load_manifest(manifest, expected_rows)
    _graph, graph_bindings = validate_graph_receipt(graph_receipt, expected_rows)
    validate_inference_receipt(l1_receipt, l1_output, manifest, expected_rows, 5)
    l1_summary = validate_prediction_table(l1_output, manifest_rows, 5)
    require(failed_b_log.is_file() and not failed_b_log.is_symlink(), "failed_b_log_invalid")
    failure_text = failed_b_log.read_text(encoding="utf-8", errors="replace")
    require("checkpoint_schema_invalid:pvrig_v2_11_full10644_clean_attention_runner_v1" in failure_text, "failed_b_log_reason_mismatch")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": PREFLIGHT_STATUS,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows": expected_rows,
        "bindings": {
            "manifest": sha256_file(manifest), **graph_bindings,
            "l1_output": l1_summary["sha256"], "l1_receipt": sha256_file(l1_receipt),
            "failed_v2_b_log": sha256_file(failed_b_log),
        },
        "l1": l1_summary,
        "old_v2_failure_reason": "checkpoint_schema_invalid:pvrig_v2_11_full10644_clean_attention_runner_v1",
        "truth_access": {"teacher_labels_opened": 0, "candidate_docking_pose_files_opened": 0},
    }


def validate_preflight_immutable(
    preflight: Mapping[str, Any], *, manifest: Path, graph_receipt: Path,
    l1_output: Path, l1_receipt: Path, failed_b_log: Path, expected_rows: int,
) -> None:
    require(preflight.get("status") == PREFLIGHT_STATUS and preflight.get("rows") == expected_rows, "preflight_status_or_rows")
    bindings = preflight.get("bindings", {})
    _graph, graph_bindings = validate_graph_receipt(graph_receipt, expected_rows)
    current = {
        "manifest": sha256_file(manifest), **graph_bindings,
        "l1_output": sha256_file(l1_output), "l1_receipt": sha256_file(l1_receipt),
        "failed_v2_b_log": sha256_file(failed_b_log),
    }
    require(bindings == current, "preflight_inputs_changed")


def validate_profile_receipt(path: Path, b_receipt: Mapping[str, Any]) -> Mapping[str, Any]:
    profile = load_json(path)
    require(profile.get("status") == PROFILE_STATUS and profile.get("profile_id") == PROFILE_ID, "profile_status_or_id")
    require(profile.get("checkpoint_schema") == EXPECTED_SCHEMA and profile.get("split_id") == EXPECTED_SPLIT, "profile_schema_or_split")
    checkpoints = profile.get("checkpoints")
    require(isinstance(checkpoints, list) and len(checkpoints) == 4, "profile_checkpoint_count")
    require(tuple(item.get("seed") for item in checkpoints) == EXPECTED_B_SEEDS, "profile_seed_set_or_order")
    require(tuple(item.get("checkpoint", {}).get("sha256") for item in checkpoints) == EXPECTED_B_HASHES, "profile_checkpoint_hashes")
    bound = b_receipt.get("input_bindings", {}).get("checkpoints")
    require(isinstance(bound, list) and len(bound) == 4, "b_receipt_checkpoint_count")
    require(tuple(item.get("seed") for item in bound) == EXPECTED_B_SEEDS, "b_receipt_seed_set_or_order")
    require(tuple(item.get("sha256") for item in bound) == EXPECTED_B_HASHES, "b_receipt_checkpoint_hashes")
    require(all(item.get("schema_version") == EXPECTED_SCHEMA and item.get("split_id") == EXPECTED_SPLIT and item.get("variant") == "BASE" for item in bound), "b_receipt_checkpoint_metadata")
    return profile


def build_terminal(
    *, manifest: Path, graph_receipt: Path, l1_output: Path, l1_receipt: Path,
    b_output: Path, b_receipt: Path, profile_receipt: Path, preflight_receipt: Path,
    failed_b_log: Path, expected_rows: int,
) -> dict[str, Any]:
    preflight = load_json(preflight_receipt)
    validate_preflight_immutable(
        preflight, manifest=manifest, graph_receipt=graph_receipt, l1_output=l1_output,
        l1_receipt=l1_receipt, failed_b_log=failed_b_log, expected_rows=expected_rows,
    )
    manifest_rows = load_manifest(manifest, expected_rows)
    graph, graph_bindings = validate_graph_receipt(graph_receipt, expected_rows)
    l1 = validate_inference_receipt(l1_receipt, l1_output, manifest, expected_rows, 5)
    l1_summary = validate_prediction_table(l1_output, manifest_rows, 5)
    b = validate_inference_receipt(b_receipt, b_output, manifest, expected_rows, 4)
    b_summary = validate_prediction_table(b_output, manifest_rows, 4)
    profile = validate_profile_receipt(profile_receipt, b)
    require(preflight.get("bindings", {}).get("l1_output") == l1_summary["sha256"], "l1_not_reused_byte_exact")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": TERMINAL_STATUS,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows": expected_rows,
        "graph": {"entities": graph["counts"]["entities"], **graph_bindings},
        "L1": {"receipt_sha256": sha256_file(l1_receipt), **l1_summary, "reused_without_recomputation": True},
        "B": {"receipt_sha256": sha256_file(b_receipt), **b_summary, "profile_receipt_sha256": sha256_file(profile_receipt)},
        "profile": {"profile_id": profile["profile_id"], "seeds": list(EXPECTED_B_SEEDS), "checkpoint_hashes": list(EXPECTED_B_HASHES)},
        "preflight_receipt_sha256": sha256_file(preflight_receipt),
        "old_v2_failure_evidence_sha256": sha256_file(failed_b_log),
        "all_numeric_finite": True,
        "candidate_sequence_parent_order_closed": True,
        "exact_min_closed": True,
        "truth_access": {"teacher_labels_opened": 0, "candidate_docking_pose_files_opened": 0, "contact_supervision_fields_read": 0},
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("mode", choices=("preflight", "publish"))
    value.add_argument("--manifest", type=Path, required=True)
    value.add_argument("--graph-receipt", type=Path, required=True)
    value.add_argument("--l1-output", type=Path, required=True)
    value.add_argument("--l1-receipt", type=Path, required=True)
    value.add_argument("--failed-b-log", type=Path, required=True)
    value.add_argument("--expected-rows", type=int, required=True)
    value.add_argument("--preflight-receipt", type=Path, required=True)
    value.add_argument("--b-output", type=Path)
    value.add_argument("--b-receipt", type=Path)
    value.add_argument("--profile-receipt", type=Path)
    value.add_argument("--versioned-terminal", type=Path)
    value.add_argument("--canonical-terminal", type=Path)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.mode == "preflight":
        require(not args.preflight_receipt.exists(), "preflight_receipt_exists")
        payload = build_preflight(
            manifest=args.manifest, graph_receipt=args.graph_receipt, l1_output=args.l1_output,
            l1_receipt=args.l1_receipt, failed_b_log=args.failed_b_log, expected_rows=args.expected_rows,
        )
        atomic_json(args.preflight_receipt, payload)
    else:
        for name in ("b_output", "b_receipt", "profile_receipt", "versioned_terminal", "canonical_terminal"):
            require(getattr(args, name) is not None, f"publish_argument_missing:{name}")
        payload = build_terminal(
            manifest=args.manifest, graph_receipt=args.graph_receipt, l1_output=args.l1_output,
            l1_receipt=args.l1_receipt, b_output=args.b_output, b_receipt=args.b_receipt,
            profile_receipt=args.profile_receipt, preflight_receipt=args.preflight_receipt,
            failed_b_log=args.failed_b_log, expected_rows=args.expected_rows,
        )
        atomic_json(args.versioned_terminal, payload)
        atomic_json(args.canonical_terminal, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
