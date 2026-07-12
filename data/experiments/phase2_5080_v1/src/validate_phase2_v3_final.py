#!/usr/bin/env python3
"""Validate the complete V3 train, formal, deployment, and runtime evidence chain."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from phase2_v3_contracts import sha256_file, write_json_atomic

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_PREPARED = EXP_DIR / "prepared" / "phase2_v3_binding"
DEFAULT_SCORE = EXP_DIR / "predictions" / "pvrig_candidate_ranking_v3.csv"
DEFAULT_HANDOFF = EXP_DIR / "predictions" / "pvrig_candidate_ranking_v3_node1_handoff.csv"
DEFAULT_NODE1 = EXP_DIR / "audits" / "phase2_v3_node1_runtime_audit.json"
DEFAULT_TEST_LOG = EXP_DIR / "logs" / "phase2_v3_tests.log"
DEFAULT_JSON = EXP_DIR / "audits" / "phase2_v3_final_validation.json"
DEFAULT_MD = EXP_DIR / "audits" / "PHASE2_V3_FINAL_VALIDATION.md"


def add_check(checks: list[dict[str, Any]], name: str, passed: bool, evidence: Any) -> None:
    checks.append({"name": name, "status": "PASS" if passed else "FAIL", "evidence": evidence})


def validate(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    required_json = [
        EXP_DIR / "audits" / "phase2_v3_preregistration.json",
        EXP_DIR / "audits" / "phase2_v3_test_spec.json",
        EXP_DIR / "configs" / "phase2_v3_binding_prior.json",
    ]
    for path in required_json:
        try:
            json.loads(path.read_text(encoding="utf-8"))
            add_check(checks, f"valid_json:{path.name}", True, str(path))
        except Exception as exc:
            add_check(checks, f"valid_json:{path.name}", False, repr(exc))
    architecture = EXP_DIR / "reports" / "PHASE2_V3_ARCHITECTURE_PLAN.md"
    add_check(checks, "architecture_plan_exists", architecture.is_file(), str(architecture))

    prepare_audit_path = args.prepared / "binding_prepare_audit_v3.json"
    prepare = json.loads(prepare_audit_path.read_text(encoding="utf-8"))
    add_check(checks, "primary_formal_vhh_disjoint", prepare["split_audit"]["primary_external_hTNFa_vhh_overlap"] == 0, prepare["split_audit"])
    add_check(checks, "pvrig_deployment_panel_frozen", prepare["deployment_sequence_audit"].get("candidate_count") == 24, prepare["deployment_sequence_audit"])
    add_check(checks, "development_and_formal_nonempty", all(int(prepare["row_counts"].get(key, 0)) > 0 for key in ("train", "dev", "formal")), prepare["row_counts"])
    blinded_path = args.prepared / "binding_formal_blinded_v3.csv"
    blinded_columns = pd.read_csv(blinded_path, nrows=0).columns
    add_check(checks, "formal_blinded_has_no_label", "label" not in blinded_columns, list(blinded_columns))
    train_splits = set(pd.read_csv(args.prepared / "binding_train_dev_v3.csv", usecols=["split"])["split"].astype(str))
    add_check(checks, "training_has_no_formal_rows", train_splits == {"train", "dev"}, sorted(train_splits))

    embedding_summary_path = args.prepared / "embeddings" / "embedding_summary_v3.json"
    embedding = json.loads(embedding_summary_path.read_text(encoding="utf-8"))
    manifest_path = Path(embedding["embedding_manifest"])
    add_check(checks, "real_cuda_embeddings", embedding["config"]["backend"] == "real" and embedding["device"] == "cuda", {"backend": embedding["config"]["backend"], "device": embedding["device"], "gpu": embedding["cuda_device_name"]})
    add_check(checks, "embedding_manifest_hash", sha256_file(manifest_path) == embedding["embedding_manifest_sha256"], str(manifest_path))
    manifest = pd.read_csv(manifest_path)
    add_check(checks, "embedding_sequence_count", len(manifest) == int(embedding["sequence_count"]), {"manifest": len(manifest), "summary": embedding["sequence_count"]})

    run_root = args.run_dir.resolve()
    train_summary = json.loads((run_root / "train_summary.json").read_text(encoding="utf-8"))
    add_check(checks, "three_preregistered_seeds", train_summary["seeds"] == [43, 53, 67], train_summary["seeds"])
    required_models = {"vhh_only", "esm2_pair", "v3_full", "v3_full_label_shuffle", "v3_full_target_shuffle"}
    add_check(checks, "required_model_variants", set(train_summary["results"]) == required_models, sorted(train_summary["results"]))
    checkpoint_failures = []
    for model_name, results in train_summary["results"].items():
        for result in results:
            path = Path(result["checkpoint"])
            if not path.is_file() or sha256_file(path) != result["checkpoint_sha256"]:
                checkpoint_failures.append(f"{model_name}:{result['seed']}")
    add_check(checks, "checkpoint_hashes", not checkpoint_failures, checkpoint_failures)
    add_check(checks, "train_never_read_formal_labels", train_summary["formal_unseal_status"] == "SEALED_LABELS_NOT_READ", train_summary["formal_unseal_status"])

    formal_path = run_root / "formal_evaluation" / "formal_evaluation_summary.json"
    formal = json.loads(formal_path.read_text(encoding="utf-8"))
    audit = json.loads((run_root / "formal_unseal_audit.json").read_text(encoding="utf-8"))
    add_check(checks, "formal_one_shot_complete", formal["formal_unseal_status"] == "UNSEALED_EXPLICIT_ONE_SHOT_COMPLETE" and audit["formal_run_count"] == 1, {"status": formal["formal_unseal_status"], "count": audit["formal_run_count"]})
    expected_status = "PASS_IMPROVED_PRIOR" if all(formal["formal_decision"]["checks"].values()) else "FAIL_FALLBACK_TO_BASELINE"
    add_check(checks, "formal_decision_consistent", formal["formal_decision"]["status"] == expected_status, formal["formal_decision"])
    expected_deployment = "v3_full" if expected_status == "PASS_IMPROVED_PRIOR" else formal["selected_baseline"]
    add_check(checks, "deployment_method_consistent", formal["deployment_method"] == expected_deployment, {"expected": expected_deployment, "observed": formal["deployment_method"]})
    add_check(checks, "formal_labels_not_used_for_training", audit["formal_labels_used_for_training_or_selection"] is False, audit)

    score_summary = json.loads(args.score.with_suffix(".summary.json").read_text(encoding="utf-8"))
    score_frame = pd.read_csv(args.score)
    handoff = pd.read_csv(args.handoff)
    add_check(checks, "pvrig_panel_cardinality", len(score_frame) == 24 and score_frame["candidate_id"].nunique() == 24, len(score_frame))
    add_check(checks, "prospective_handoff_cardinality", len(handoff) == 6 and handoff["candidate_id"].nunique() == 6, len(handoff))
    add_check(checks, "calibration_lane_separate", int(score_frame["screening_lane"].eq("CALIBRATION_ONLY").sum()) == 5 and score_frame.loc[score_frame["screening_lane"].eq("CALIBRATION_ONLY"), "screening_rank"].isna().all(), score_frame["screening_lane"].value_counts().to_dict())
    add_check(checks, "score_hash", sha256_file(args.score) == score_summary["output_sha256"], str(args.score))
    add_check(checks, "handoff_hash", sha256_file(args.handoff) == score_summary["node1_handoff_sha256"], str(args.handoff))

    if args.node1_audit.is_file():
        node1 = json.loads(args.node1_audit.read_text(encoding="utf-8"))
        node1_pass = node1.get("status") == "PASS" and node1.get("handoff_sha256") == sha256_file(args.handoff)
        add_check(checks, "node1_runtime_and_handoff", node1_pass, node1)
    else:
        add_check(checks, "node1_runtime_and_handoff", False, f"missing {args.node1_audit}")
    test_text = args.test_log.read_text(encoding="utf-8") if args.test_log.is_file() else ""
    add_check(checks, "v3_test_suite", "OK" in test_text and "FAILED" not in test_text, str(args.test_log))

    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    result = {
        "schema_version": "phase2_v3_final_validation_v1",
        "status": status,
        "run_dir": str(run_root),
        "check_count": len(checks),
        "failed_check_count": sum(item["status"] == "FAIL" for item in checks),
        "checks": checks,
        "formal_decision": formal["formal_decision"]["status"],
        "deployment_method": formal["deployment_method"],
        "claim_boundary": "validation_of_computational_binding_prior_not_pvrig_blocker_truth",
    }
    write_json_atomic(args.json_out, result)
    lines = [
        "# Phase 2 V3 Final Validation",
        "",
        f"- Status: **{status}**",
        f"- Formal decision: `{result['formal_decision']}`",
        f"- Deployment method: `{result['deployment_method']}`",
        f"- Checks: `{result['check_count']}`; failed: `{result['failed_check_count']}`",
        "",
        "## Checks",
        "",
    ]
    lines.extend(f"- {item['status']}: `{item['name']}`" for item in checks)
    lines.extend(["", "Computational validation does not establish PVRIG binding or blocking truth.", ""])
    args.markdown_out.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": status, "failed": result["failed_check_count"]}, sort_keys=True))
    if status != "PASS":
        raise SystemExit(1)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, default=DEFAULT_PREPARED)
    parser.add_argument("--score", type=Path, default=DEFAULT_SCORE)
    parser.add_argument("--handoff", type=Path, default=DEFAULT_HANDOFF)
    parser.add_argument("--node1-audit", type=Path, default=DEFAULT_NODE1)
    parser.add_argument("--test-log", type=Path, default=DEFAULT_TEST_LOG)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown-out", type=Path, default=DEFAULT_MD)
    return parser.parse_args()


if __name__ == "__main__":
    validate(parse_args())
