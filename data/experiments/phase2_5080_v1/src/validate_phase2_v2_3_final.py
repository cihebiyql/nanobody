#!/usr/bin/env python3
"""Validate the complete P0-P4 Phase 2 V2.3 deliverable."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
PROJECT_ROOT = DATA_ROOT.parent
DEFAULT_JSON = EXP_DIR / "audits" / "phase2_v2_3_p0_p4_final_audit_v1.json"
DEFAULT_MARKDOWN = EXP_DIR / "audits" / "PHASE2_V2_3_P0_P4_FINAL_AUDIT_V1.md"
SEEDS = (43, 53, 67)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def sequence_hash(sequence: str) -> str:
    return hashlib.sha256(str(sequence).strip().upper().encode("utf-8")).hexdigest()


def build_audit(unit_test_log: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, evidence: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), "evidence": evidence})

    split = load_json(EXP_DIR / "audits" / "clustered_split_validation_v2.json")
    check("p0_independent_split_validation_pass", split.get("status") == "PASS", f"checks={len(split.get('checks', []))}")
    check("p0_all_72_split_checks_pass", len(split.get("checks", [])) == 72 and not split.get("failed_checks"), split.get("failed_checks", []))

    target = load_json(DATA_ROOT / "model_data" / "pvrig_target_domain_contract_v1.json")
    check("p1_target_proxy_contract_is_explicit", target.get("model_domain_start_1based_inclusive") == 39 and target.get("model_domain_end_1based_inclusive") == 171, target.get("boundary_status"))
    check("p1_target_is_not_mislabeled_reviewed_domain", "proxy_not_reviewed" in str(target.get("boundary_status")), target.get("boundary_status"))
    priors = load_json(EXP_DIR / "audits" / "external_prior_summary_full50_v1.json")
    check("p1_external_priors_complete", priors.get("status") == "PASS" and priors.get("raw_rows") == 250 and priors.get("status_counts") == {"ok": 250}, priors.get("model_counts"))
    check("p1_external_prior_boundary", "not blocker probabilities" in str(priors.get("evidence_boundary")), priors.get("evidence_boundary"))

    cache = load_json(EXP_DIR / "audits" / "esm2_cache_validation_v2_3.json")
    check("p2_esm2_cache_exhaustive_pass", cache.get("status") == "PASS" and cache.get("manifest_rows") == 4935 and cache.get("validated_tensor_keys") == 4935, {"rows": cache.get("manifest_rows"), "shards": cache.get("shard_count")})
    check("p2_esm2_cache_no_orphans", cache.get("orphan_shard_keys") == 0, cache.get("orphan_shard_keys"))

    dataset_sizes = None
    run_metrics = []
    for seed in SEEDS:
        run = EXP_DIR / "runs" / f"phase2_v2_3_strict_hardened_20260710_seed{seed}"
        metrics = load_json(run / "test_metrics.json")
        run_metrics.append(metrics)
        check(f"p2_seed{seed}_metrics_present", (run / "best_checkpoint.pt").exists() and metrics.get("ranking_test", {}).get("ranking_groups") == 175.0, str(run))
        check(f"p2_seed{seed}_pair_boundary", "not verified non-binders" in str(metrics.get("pair_test", {}).get("pair_metric_boundary")), metrics.get("pair_test", {}).get("pair_metric_boundary"))
        if dataset_sizes is None:
            dataset_sizes = metrics.get("dataset_sizes")
        else:
            check(f"p2_seed{seed}_dataset_sizes_match", metrics.get("dataset_sizes") == dataset_sizes, metrics.get("dataset_sizes"))
        portable = EXP_DIR / "checkpoints" / f"phase2_v2_3_strict_seed{seed}_best_checkpoint.pt"
        check(f"p2_seed{seed}_portable_checkpoint", portable.exists() and portable.stat().st_size > 0, str(portable))

    gpu = load_json(EXP_DIR / "audits" / "phase2_v2_3_gpu_telemetry_summary_v1.json")
    check("p2_three_cuda_runs_telemetry_pass", gpu.get("status") == "PASS" and gpu.get("formal_training_runs") == 3 and all(row.get("device") == "cuda" for row in gpu.get("runs", [])), gpu.get("gpu_names"))
    check("p2_gpu_was_materially_used", all(row.get("gpu_utilization_max_pct", 0) >= 60 and row.get("gpu_memory_max_mib", 0) >= 5500 for row in gpu.get("runs", [])), [{"seed": row.get("seed"), "max_util": row.get("gpu_utilization_max_pct"), "max_mem": row.get("gpu_memory_max_mib")} for row in gpu.get("runs", [])])
    staging = load_json(EXP_DIR / "audits" / "v2_3_runtime_staging_equivalence_v1.json")
    check("p2_runtime_staging_byte_equivalent", staging.get("status") == "PASS" and staging.get("file_pairs") == 27 and staging.get("all_sha256_match") is True, staging.get("total_bytes"))
    portable_equivalence = load_json(EXP_DIR / "audits" / "phase2_v2_3_portable_inference_equivalence_v1.json")
    check("p2_portable_inference_exact", portable_equivalence.get("status") == "PASS" and max(portable_equivalence.get("max_abs_differences", {}).values(), default=1.0) == 0.0, portable_equivalence.get("max_abs_differences"))

    multiseed = load_json(EXP_DIR / "reports" / "phase2_v2_3_multiseed_summary_v1.json")
    check("p4_multiseed_summary_pass", multiseed.get("status") == "PASS" and multiseed.get("n_runs") == 3 and set(multiseed.get("seeds", [])) == {"43", "53", "67"}, multiseed.get("run_ids"))
    check("p4_calibration_honestly_not_applicable", multiseed.get("calibration", {}).get("status") == "NOT_APPLICABLE", multiseed.get("calibration"))
    evaluation = load_json(EXP_DIR / "reports" / "phase2_v2_3_strict_evaluation_v1.json")
    check("p4_pair_ranking_limitation_explicit", evaluation.get("status") == "COMPLETED_WITH_PAIR_RANKING_LIMITATION" and evaluation.get("metrics", {}).get("ranking_mrr", {}).get("mean", 1.0) < evaluation.get("random_baselines", {}).get("ranking_mrr", 0.0), evaluation.get("ranking_interpretation"))
    tuning = load_json(EXP_DIR / "audits" / "phase2_v2_3_tuning_decision_v1.json")
    check("p4_validation_only_tuning_decision", tuning.get("decision") == "REJECT_RANKFOCUSED_KEEP_BASELINE_CONFIG" and tuning.get("test_metrics_used_for_selection") is False, tuning.get("reason"))

    pose_inventory = load_json(EXP_DIR / "audits" / "p3_top50_pose_inventory_v1.json")
    pose_fusion = load_json(EXP_DIR / "audits" / "p3_late_fusion_rankings_v1.json")
    pose_validation = load_json(EXP_DIR / "audits" / "p3_late_fusion_validation_v1.json")
    check("p3_pose_inventory_complete", pose_inventory.get("status") == "PASS" and pose_inventory.get("candidate_count") == 50 and pose_inventory.get("pdb_files_scanned") == 1680, pose_inventory.get("decision"))
    check("p3_zero_pose_data_gate_explicit", pose_inventory.get("exact_pose_candidate_count") == 0 and pose_fusion.get("pose_used_rows") == 0 and pose_fusion.get("missing_pose_ai_prior_only_rows") == 50, {"pose_coverage": pose_inventory.get("exact_pose_candidate_count"), "ai_only": pose_fusion.get("missing_pose_ai_prior_only_rows")})
    check("p3_fusion_validation_pass", pose_validation.get("status") == "PASS" and not pose_validation.get("failed_checks"), pose_validation.get("failed_checks"))

    ensemble_path = EXP_DIR / "predictions" / "pvrig_candidate_ranking_ai_prior_v2_3_multiseed_ensemble.csv"
    p3_path = EXP_DIR / "predictions" / "p3_late_fusion_rankings_v1.csv"
    ensemble = pd.read_csv(ensemble_path)
    p3 = pd.read_csv(p3_path)
    check("p4_ensemble_has_50_three_seed_rows", len(ensemble) == 50 and ensemble["candidate_id"].is_unique and (ensemble["phase2_v2_3_seed_count"] == 3).all(), str(ensemble_path))
    check("p3_output_has_50_ai_only_rows", len(p3) == 50 and p3["candidate_id"].is_unique and (p3["p3_missing_pose_policy"] == "AI_PRIOR_ONLY").all(), str(p3_path))
    check("candidate_leakage_labels_clean", set(ensemble["leakage_label"].astype(str)) == {"NO_KNOWN_POSITIVE_LEAKAGE"}, ensemble["leakage_label"].value_counts().to_dict())

    candidates = pd.read_csv(DATA_ROOT / "model_data" / "mvp_candidates_v0.csv")
    candidate_seqs = set(candidates.loc[candidates["candidate_id"].isin(ensemble["candidate_id"]), "vhh_seq"].map(sequence_hash))
    controls = pd.read_csv(EXP_DIR / "data_splits" / "pvrig_external_calibration_manifest_v1.csv")
    held_controls = controls[controls["role"].astype(str).isin({"known_positive_calibration_only", "mutant_or_leakage_control"})]
    control_seqs = set(held_controls["sequence"].map(sequence_hash))
    check("known_controls_absent_from_candidate_ensemble", not (candidate_seqs & control_seqs), f"hash_overlap={len(candidate_seqs & control_seqs)}")

    log_text = unit_test_log.read_text(encoding="utf-8", errors="ignore") if unit_test_log.exists() else ""
    check("final_unit_suite_57_pass", "Ran 57 tests" in log_text and "OK" in log_text, str(unit_test_log))
    readme = (EXP_DIR / "README.md").read_text(encoding="utf-8")
    progress = (PROJECT_ROOT / "PROJECT_PROGRESS.md").read_text(encoding="utf-8")
    check("readme_documents_v2_3_boundary", "V2.3 Strict Deliverable" in readme and "calibrated binding/blocker probabilities" in readme and "ranking AI priors" in readme, str(EXP_DIR / "README.md"))
    check("project_progress_updated", "Latest Phase 2 Model Update - 2026-07-10" in progress and "Ranking MRR" in progress, str(PROJECT_ROOT / "PROJECT_PROGRESS.md"))

    failed = [item["name"] for item in checks if not item["passed"]]
    return {
        "status": "PASS_WITH_PAIR_RANKING_LIMITATION" if not failed else "FAIL",
        "failed_checks": failed,
        "check_count": len(checks),
        "checks": checks,
        "summary": {
            "seeds": list(SEEDS),
            "strict_dataset_sizes": dataset_sizes,
            "contact_auprc_mean": multiseed.get("metrics", {}).get("contact_auprc", {}).get("mean"),
            "paratope_auprc_mean": multiseed.get("metrics", {}).get("paratope_auprc", {}).get("mean"),
            "epitope_auprc_mean": multiseed.get("metrics", {}).get("epitope_auprc", {}).get("mean"),
            "ranking_mrr_mean": multiseed.get("metrics", {}).get("ranking_mrr", {}).get("mean"),
            "ranking_mrr_random_expectation": evaluation.get("random_baselines", {}).get("ranking_mrr"),
            "candidate_rows": len(ensemble),
            "p3_pose_coverage": pose_inventory.get("exact_pose_candidate_count"),
            "calibration_status": multiseed.get("calibration", {}).get("status"),
        },
        "boundary": "Computational ranking evidence only; no experimental binding, Kd, IC50, or blocker-efficacy claim.",
    }


def write_markdown(result: dict[str, Any], path: Path) -> None:
    summary = result["summary"]
    lines = [
        "# Phase 2 V2.3 P0-P4 Final Audit V1",
        "",
        f"- Status: **{result['status']}**",
        f"- Checks: {result['check_count'] - len(result['failed_checks'])}/{result['check_count']} passed",
        f"- Seeds: {', '.join(str(seed) for seed in summary['seeds'])}",
        f"- Candidate rows: {summary['candidate_rows']}",
        f"- Exact pose coverage: {summary['p3_pose_coverage']}/50",
        f"- Calibration: {summary['calibration_status']}",
        "",
        "## Final Metrics",
        "",
        f"- Contact AUPRC mean: {summary['contact_auprc_mean']:.6f}",
        f"- Paratope AUPRC mean: {summary['paratope_auprc_mean']:.6f}",
        f"- Epitope AUPRC mean: {summary['epitope_auprc_mean']:.6f}",
        f"- Ranking MRR mean/random: {summary['ranking_mrr_mean']:.6f} / {summary['ranking_mrr_random_expectation']:.6f}",
        "",
        "## Checks",
        "",
    ]
    for item in result["checks"]:
        mark = "PASS" if item["passed"] else "FAIL"
        lines.append(f"- [{mark}] `{item['name']}` - {item['evidence']}")
    lines.extend(["", result["boundary"], ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit-test-log", type=Path, default=EXP_DIR / "logs" / "v2_3_final_full_unit_and_compile.log")
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown-out", type=Path, default=DEFAULT_MARKDOWN)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_audit(args.unit_test_log)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(result, args.markdown_out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
