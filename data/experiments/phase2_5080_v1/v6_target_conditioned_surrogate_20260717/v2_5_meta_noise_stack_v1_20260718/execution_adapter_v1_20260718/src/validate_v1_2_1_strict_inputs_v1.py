#!/usr/bin/env python3
"""Validate strict V1.2.1 D-lane evidence without evaluating performance."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import sys

HERE = Path(__file__).resolve().parent
BASE_SRC = HERE.parents[1] / "src"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BASE_SRC))

from execution_common_v1 import (
    ExecutionContractError,
    atomic_write_json,
    finite_float,
    read_json,
    read_tsv,
    require,
    scan_zero_access_counts,
    sha256_file,
    unique_by,
    verify_named_hashes,
)
from meta_noise_stack_v1 import validate_c2_outer_oof


REQUIRED_COLUMNS = {
    "schema_version", "evidence_role", "candidate_id", "teacher_source",
    "parent_framework_cluster", "outer_fold", "inner_fold", "R_8X6B",
    "R_9E6Y", "R_dual_min", "M2_R8", "neural_R8", "contact_score_R8",
    "M2_R9", "neural_R9", "contact_score_R9",
}


def _expected_inner(inner_manifest: Sequence[Mapping[str, str]], fold: int) -> dict[str, Mapping[str, str]]:
    score = [
        row for row in inner_manifest
        if int(row["outer_fold"]) == fold and row["candidate_role"] == "score"
    ]
    return unique_by(score, "candidate_id", f"inner_score_outer_{fold}")


def _expected_outer(outer_manifest: Sequence[Mapping[str, str]], fold: int) -> dict[str, Mapping[str, str]]:
    score = [
        row for row in outer_manifest
        if int(row["outer_fold"]) == fold and row["candidate_role"] == "score"
    ]
    return unique_by(score, "candidate_id", f"outer_score_{fold}")


def _validate_evidence(
    path: Path,
    validation_path: Path,
    provenance_path: Path,
    expected: Mapping[str, Mapping[str, str]],
    labels: Mapping[str, Mapping[str, str]],
    *,
    fold: int,
    role: str,
    manifest_sha256: str,
) -> dict[str, Any]:
    rows = read_tsv(path)
    require(REQUIRED_COLUMNS <= set(rows[0]), f"evidence_schema_missing:{path}")
    observed = unique_by(rows, "candidate_id", f"evidence_{fold}_{role}")
    require(set(observed) == set(expected), f"evidence_candidate_closure:{fold}:{role}")
    expected_role = "INNER_OOF_BASE_FEATURE" if role == "inner" else "OUTER_TEST_BASE_FEATURE"
    for candidate, row in observed.items():
        expected_row = expected[candidate]
        label = labels[candidate]
        require(row["evidence_role"] == expected_role, f"evidence_role:{candidate}")
        require(int(row["outer_fold"]) == fold, f"evidence_outer_fold:{candidate}")
        if role == "inner":
            require(int(row["inner_fold"]) == int(expected_row["inner_fold"]), f"evidence_inner_fold:{candidate}")
        else:
            require(row["inner_fold"] == "NONE", f"outer_inner_fold_not_none:{candidate}")
        for field in ("teacher_source", "parent_framework_cluster"):
            require(str(row[field]) == str(label[field]) == str(expected_row[field]), f"evidence_identity:{field}:{candidate}")
        values = [finite_float(row, name) for name in (
            "R_8X6B", "R_9E6Y", "R_dual_min", "M2_R8", "neural_R8",
            "contact_score_R8", "M2_R9", "neural_R9", "contact_score_R9",
        )]
        require(abs(values[2] - min(values[0], values[1])) <= 1e-12, f"truth_exact_min:{candidate}")
        require(abs(values[0] - float(label["R_8X6B"])) <= 1e-12, f"truth_R8_identity:{candidate}")
        require(abs(values[1] - float(label["R_9E6Y"])) <= 1e-12, f"truth_R9_identity:{candidate}")

    validation = read_json(validation_path)
    provenance = read_json(provenance_path)
    scan_zero_access_counts(validation, context=str(validation_path))
    scan_zero_access_counts(provenance, context=str(provenance_path))
    require(str(validation.get("status", "")).startswith("PASS"), f"validation_not_pass:{validation_path}")
    require(validation.get("evidence_role") == expected_role, f"validation_role:{validation_path}")
    require(int(validation.get("candidate_count", -1)) == len(rows), f"validation_count:{validation_path}")
    require(validation.get("evidence_tsv_sha256") == sha256_file(path), f"validation_evidence_hash:{path}")
    require(validation.get("provenance_json_sha256") == sha256_file(provenance_path), f"validation_provenance_hash:{path}")
    require(validation.get("split_manifest_sha256") == manifest_sha256, f"validation_manifest_hash:{path}")
    return {
        "row_count": len(rows),
        "evidence_sha256": sha256_file(path),
        "validation_sha256": sha256_file(validation_path),
        "provenance_sha256": sha256_file(provenance_path),
        "role": expected_role,
        "candidate_closure": True,
        "exact_min_violations": 0,
    }


def validate(args: argparse.Namespace) -> dict[str, Any]:
    contract_path = Path(args.contract).resolve()
    package_root = Path(args.package_root).resolve()
    runtime_root = Path(args.runtime_root).resolve()
    input_root = Path(args.input_root).resolve()
    contract = read_json(contract_path)
    require(contract["status"] == "FROZEN_DESIGN_UNAUTHORIZED_DO_NOT_EVALUATE", "contract_status")
    require(contract["authorization"]["execution_authorized"] is False, "contract_unexpectedly_authorized")
    upstream = contract["upstream_v2_4_strict"]
    require(upstream["allowed_lane"] == "D_SPLIT_PAIR", "allowed_lane_not_D")
    require(set(upstream["forbidden_lanes_as_v2_5_predictors"]) == {"B_TARGET_NO_CONTACT", "C_SPLIT_MARGINAL"}, "forbidden_lane_contract")

    graph_path = package_root / "plan" / "job_graph.json"
    package_manifest_path = package_root / "PACKAGE_MANIFEST.json"
    overlay_path = package_root / "contracts" / "EXPLICIT_AUTHORIZATION_OVERLAY.json"
    launch_receipt_path = runtime_root / "AUTHORIZED_LAUNCH_RECEIPT.json"
    bindings = {
        "job_graph": (graph_path, upstream["job_graph_sha256"]),
        "package_manifest": (package_manifest_path, upstream["package_manifest_sha256"]),
        "upstream_authorization_overlay": (overlay_path, upstream["authorization_overlay_sha256"]),
        "launch_receipt": (launch_receipt_path, upstream["launch_receipt_sha256"]),
    }
    binding_hashes = {}
    for name, (path, expected_hash) in bindings.items():
        observed = sha256_file(path)
        require(observed == expected_hash, f"upstream_hash_mismatch:{name}:{observed}")
        binding_hashes[name] = observed
    graph = read_json(graph_path)
    package_manifest = read_json(package_manifest_path)
    upstream_overlay = read_json(overlay_path)
    launch_receipt = read_json(launch_receipt_path)
    for name, value in (("graph", graph), ("package_manifest", package_manifest), ("upstream_overlay", upstream_overlay), ("launch_receipt", launch_receipt)):
        scan_zero_access_counts(value, context=name)
    require(int(graph["job_counts"]["GPU_BASE_TRAIN_INNER"] + graph["job_counts"]["GPU_BASE_REFIT_OUTER_TRAIN"]) == int(upstream["expected_job_counts"]["gpu"]), "graph_gpu_job_count")
    require(len(graph["jobs"]) == int(upstream["expected_job_counts"]["total"]), "graph_total_job_count")
    require(int(launch_receipt["job_count"]) == len(graph["jobs"]), "launch_job_count")
    require(launch_receipt["job_graph_sha256"] == upstream["job_graph_sha256"], "launch_graph_hash")

    input_hashes = verify_named_hashes(input_root, contract["canonical_inputs"])
    terminal_path = runtime_root / "TERMINAL.json"
    if not terminal_path.exists():
        require(args.allow_waiting, "strict_terminal_missing")
        return {
            "schema_version": "pvrig_v2_5_strict_input_closure_receipt_v1",
            "status": "WAITING_STRICT_V1_2_1_TERMINAL",
            "execution_authorized": False,
            "formal_evaluator_launched": False,
            "performance_evaluation_performed": False,
            "terminal_path": str(terminal_path),
            "contract_sha256": sha256_file(contract_path),
            "input_hashes": input_hashes,
            "upstream_binding_hashes": binding_hashes,
        }
    terminal = read_json(terminal_path)
    scan_zero_access_counts(terminal, context="terminal")
    require(terminal.get("status") == upstream["expected_terminal"]["status"], "terminal_status")
    require(int(terminal.get("returncode", -1)) == int(upstream["expected_terminal"]["returncode"]), "terminal_returncode")

    missing = []
    result_hashes = {}
    for job in graph["jobs"]:
        path = Path(str(job["expected_result"]))
        require(str(path).startswith(str(runtime_root) + "/"), f"job_result_outside_runtime:{job['job_id']}")
        if not path.is_file() or path.is_symlink():
            missing.append(str(job["job_id"]))
        else:
            result_hashes[str(job["job_id"])] = sha256_file(path)
    require(not missing, f"job_result_closure_missing:{','.join(missing[:10])}")

    labels_rows = read_tsv(input_root / contract["canonical_inputs"]["labels"]["filename"])
    labels = unique_by(labels_rows, "candidate_id", "label")
    outer_manifest = read_tsv(input_root / contract["canonical_inputs"]["outer_manifest"]["filename"])
    inner_manifest = read_tsv(input_root / contract["canonical_inputs"]["inner_manifest"]["filename"])
    expected = contract["expected_counts"]
    require(len(labels) == int(expected["candidates"]), "label_candidate_count")
    require(len({row["parent_framework_cluster"] for row in labels_rows}) == int(expected["parents"]), "label_parent_count")
    require(Counter(row["development_reliability_tier"] for row in labels_rows) == Counter({k: int(v) for k, v in expected["tier_counts"].items()}), "label_tier_counts")
    require(Counter(row["teacher_source"] for row in labels_rows) == Counter({k: int(v) for k, v in expected["source_counts"].items()}), "label_source_counts")

    fold_evidence = {}
    all_outer_candidates = set()
    for fold in range(int(expected["outer_folds"])):
        root = runtime_root / "evidence" / "D_SPLIT_PAIR" / f"outer_{fold}"
        inner_expected = _expected_inner(inner_manifest, fold)
        outer_expected = _expected_outer(outer_manifest, fold)
        require(set(inner_expected).isdisjoint(outer_expected), f"inner_outer_candidate_overlap:{fold}")
        require({row["parent_framework_cluster"] for row in inner_expected.values()}.isdisjoint({row["parent_framework_cluster"] for row in outer_expected.values()}), f"inner_outer_parent_overlap:{fold}")
        all_outer_candidates.update(outer_expected)
        fold_evidence[str(fold)] = {
            "inner": _validate_evidence(
                root / "inner_oof_base.tsv", root / "inner_oof_base.validation.json",
                root / "inner_oof_provenance.json", inner_expected, labels,
                fold=fold, role="inner", manifest_sha256=input_hashes["inner_manifest"],
            ),
            "outer": _validate_evidence(
                root / "outer_test_base.tsv", root / "outer_test_base.validation.json",
                root / "outer_test_provenance.json", outer_expected, labels,
                fold=fold, role="outer", manifest_sha256=input_hashes["outer_manifest"],
            ),
        }
    require(all_outer_candidates == set(labels), "outer_candidate_scored_once_closure")

    c2_rows = read_tsv(input_root / contract["canonical_inputs"]["existing_c2_outer_oof"]["filename"])
    c2_audit = validate_c2_outer_oof(c2_rows, labels)
    return {
        "schema_version": "pvrig_v2_5_strict_input_closure_receipt_v1",
        "status": "PASS_INPUTS_READY_UNAUTHORIZED",
        "execution_authorized": False,
        "formal_evaluator_launched": False,
        "performance_evaluation_performed": False,
        "contract_sha256": sha256_file(contract_path),
        "terminal_sha256": sha256_file(terminal_path),
        "input_hashes": input_hashes,
        "upstream_binding_hashes": binding_hashes,
        "expected_job_count": len(graph["jobs"]),
        "closed_job_result_count": len(result_hashes),
        "job_result_hashes": result_hashes,
        "allowed_lane_read": "D_SPLIT_PAIR",
        "forbidden_lane_read_count": 0,
        "fold_evidence": fold_evidence,
        "c2_outer_oof_closure": c2_audit,
        "v4_f_test32_access_count": 0,
        "claim_boundary": contract["claim_boundary"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--allow-waiting", action="store_true")
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve()
    try:
        receipt = validate(args)
        atomic_write_json(output_dir / "INPUT_CLOSURE_RECEIPT.json", receipt)
        return 0
    except (ExecutionContractError, Exception) as exc:
        failure = {
            "schema_version": "pvrig_v2_5_strict_input_closure_receipt_v1",
            "status": "FAIL_INPUT_CLOSURE",
            "execution_authorized": False,
            "formal_evaluator_launched": False,
            "performance_evaluation_performed": False,
            "error": f"{type(exc).__name__}:{exc}",
        }
        atomic_write_json(output_dir / "INPUT_CLOSURE_RECEIPT.json", failure)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
