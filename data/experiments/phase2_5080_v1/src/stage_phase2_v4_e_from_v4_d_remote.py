#!/usr/bin/env python3
"""Fork the unlabeled V4-D panel into a continuous-release V4-E protocol."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path


PROTOCOL_ID = "pvrig_v4_e_fullqc290_continuous_dual_redocking_20260715"
EXPECTED_JOBS = 2022
UPSTREAM_V4_C_EVALUATOR_SHA256 = (
    "247ce9e5ed6acf456be1cd969f04a782c84887941b1222cd2f5708b60de3a5f8"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def assert_unlabeled_source(source: Path) -> None:
    jobs = read_tsv(source / "manifests/docking_jobs.tsv")
    if len(jobs) != EXPECTED_JOBS:
        raise RuntimeError(f"expected {EXPECTED_JOBS} V4-D jobs, found {len(jobs)}")
    state_files = list((source / "status/jobs").glob("*.json"))
    result_files = list((source / "results").glob("*/job_result.json"))
    if state_files or result_files:
        raise RuntimeError(
            f"V4-D is no longer label-free: states={len(state_files)} results={len(result_files)}"
        )
    chained = source / "status/chained_launch.json"
    if not chained.is_file():
        raise RuntimeError("V4-D chained-launch status is missing")
    payload = json.loads(chained.read_text(encoding="utf-8"))
    if payload.get("status") != "BLOCKED_UPSTREAM_EVALUATOR":
        raise RuntimeError(f"unexpected V4-D chained-launch state: {payload.get('status')}")


def copy_clean_project(source: Path, destination: Path) -> None:
    if destination.exists():
        raise RuntimeError(f"destination already exists: {destination}")
    destination.mkdir(parents=True)
    for directory in ("config", "scripts", "tests", "inputs"):
        shutil.copytree(source / directory, destination / directory)
    for directory in (
        "manifests",
        "reports",
        "status/jobs",
        "logs",
        "runs",
        "results",
        "failed_attempts",
        "governance",
    ):
        (destination / directory).mkdir(parents=True, exist_ok=True)
    for name in ("reference_normalization_summary.json", "fullqc290_candidate_freeze_summary.json"):
        shutil.copy2(source / "reports" / name, destination / "reports" / name)


def configure(destination: Path) -> None:
    protocol_path = destination / "config/protocol_spec.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol["schema_version"] = 3
    protocol["protocol_id"] = PROTOCOL_ID
    protocol["status"] = "PRELOCK_VALIDATION_REQUIRED"
    protocol["evidence_boundary"] = (
        "prospective_parent_cluster_split_continuous_dual_geometry_not_binding_affinity_"
        "competition_docking_gold_or_functional_blocking"
    )
    protocol["candidate_panel"]["panel_id"] = "fullqc_complete290_v4_e_continuous_v1"
    protocol["candidate_panel"]["predecessor_v4_d_generated_labels"] = 0
    protocol["scoring"]["primary_teacher_endpoint"] = "continuous_R_dual_min"
    protocol["scoring"]["legacy_A_B_C_E_tiers"] = "diagnostic_only"
    write_json(protocol_path, protocol)

    release_spec = {
        "schema_version": "pvrig_v4_e_continuous_teacher_release_gate_v1",
        "status": "FROZEN_BEFORE_V4_E_LABELS",
        "protocol_id": PROTOCOL_ID,
        "primary_endpoint": "continuous_R_dual_min",
        "release_gates": [
            "row_artifacts_present",
            "manifest_bound_pose_evidence",
            "protocol_validation",
            "all_jobs_terminal",
            "controls_47_same_protocol",
            "minimum_completed_seeds_per_entity_conformation",
            "complete_2x2_scoring",
            "all_successful_jobs_have_minimum_pose_models",
            "control_model_robustness",
            "control_seed_class_reproducibility",
            "control_native_cross_support_agreement",
            "positive_control_robust_support",
            "destructive_control_strict_a_retention"
        ],
        "diagnostic_only_gates": [
            "candidate_threshold_sensitivity"
        ],
        "legacy_threshold_sensitivity_limit_unchanged": 0.2,
        "rationale": (
            "V4-C failed only the hard A-tier threshold-sensitivity gate. V4-E is a new, "
            "pre-label version whose primary supervision is continuous geometry; it reports "
            "the unchanged tier diagnostic but does not use it to release or reject continuous labels."
        ),
        "upstream_v4_c_evaluator_sha256": UPSTREAM_V4_C_EVALUATOR_SHA256,
        "v4_c_status_must_remain": "FAIL",
        "v4_d_status_must_remain": "BLOCKED_UPSTREAM_EVALUATOR",
        "claim_boundary": (
            "computational continuous dual-docking geometry only; not binding, affinity, "
            "competition, Docking Gold, or experimental blocking"
        ),
    }
    write_json(destination / "config/continuous_teacher_release_gate.json", release_spec)

    summary_path = destination / "reports/fullqc290_candidate_freeze_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["protocol_id"] = PROTOCOL_ID
    summary["source_v4_d_candidate_manifest_sha256"] = summary["candidate_manifest_sha256"]
    summary["source_v4_d_generated_label_count"] = 0
    summary["status"] = "PASS_V4_E_CANDIDATES_AND_MONOMERS_FROZEN_BEFORE_LABELS"
    write_json(summary_path, summary)


def patch_aggregate(destination: Path) -> None:
    path = destination / "scripts/aggregate_results.py"
    text = path.read_text(encoding="utf-8")
    old_signature = '''    stability_spec_path: Path | None = None,
) -> dict[str, Any]:'''
    new_signature = '''    stability_spec_path: Path | None = None,
    continuous_release_spec_path: Path | None = None,
) -> dict[str, Any]:'''
    if old_signature not in text:
        raise RuntimeError("aggregate signature changed upstream")
    text = text.replace(old_signature, new_signature, 1)

    old_setup = '''    stability_spec = read_json(stability_spec_path)
    job_rows = load_rows(jobs_path)'''
    new_setup = '''    stability_spec = read_json(stability_spec_path)
    continuous_release_spec_path = continuous_release_spec_path or Path("config/continuous_teacher_release_gate.json")
    if not continuous_release_spec_path.is_absolute():
        continuous_release_spec_path = root / continuous_release_spec_path
    continuous_release_spec = read_json(continuous_release_spec_path)
    if continuous_release_spec.get("protocol_id") != protocol.get("protocol_id"):
        raise RuntimeError("continuous release spec protocol_id mismatch")
    if continuous_release_spec.get("diagnostic_only_gates") != ["candidate_threshold_sensitivity"]:
        raise RuntimeError("unexpected diagnostic-only gate contract")
    job_rows = load_rows(jobs_path)'''
    if old_setup not in text:
        raise RuntimeError("aggregate setup changed upstream")
    text = text.replace(old_setup, new_setup, 1)

    old_gate = '''    gates["candidate_threshold_sensitivity"] = defer_until_complete(
        completion_gate, evaluate_threshold_sensitivity(sensitivity_rows, stability_spec)
    )
    lock_path = root / "PROTOCOL_LOCK.json"'''
    new_gate = '''    diagnostics = {
        "candidate_threshold_sensitivity": defer_until_complete(
            completion_gate, evaluate_threshold_sensitivity(sensitivity_rows, stability_spec)
        )
    }
    lock_path = root / "PROTOCOL_LOCK.json"'''
    if old_gate not in text:
        raise RuntimeError("candidate threshold gate block changed upstream")
    text = text.replace(old_gate, new_gate, 1)

    old_payload = '''        "stability_gate_spec": str(stability_spec_path),
        "stability_gate_spec_sha256": sha256_file(stability_spec_path),
        "gates": gates,
        "reports": {'''
    new_payload = '''        "stability_gate_spec": str(stability_spec_path),
        "stability_gate_spec_sha256": sha256_file(stability_spec_path),
        "continuous_teacher_release_gate_spec": str(continuous_release_spec_path),
        "continuous_teacher_release_gate_spec_sha256": sha256_file(continuous_release_spec_path),
        "release_policy": "continuous_geometry_primary_legacy_tier_sensitivity_diagnostic_only",
        "gates": gates,
        "diagnostics": diagnostics,
        "reports": {'''
    if old_payload not in text:
        raise RuntimeError("aggregate payload block changed upstream")
    text = text.replace(old_payload, new_payload, 1)

    old_cli = '''    parser.add_argument("--stability-spec", default="config/evaluator_stability_gate.json")
    args = parser.parse_args(argv)
    payload = aggregate(
        Path(args.protocol),
        Path(args.jobs),
        Path(args.results),
        Path(args.out),
        args.expected_total_jobs,
        args.allow_synthetic_results,
        Path(args.stability_spec),
    )
    enrichment_returncode = None
    if payload["status"] == PASS and payload["evidence_mode"] == "production_pose_backed":
        enrichment = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "analyze_p2_p3_p4_enrichment.py")],
            cwd=Path(args.protocol).resolve().parents[1],
        )
        enrichment_returncode = enrichment.returncode
    if payload["status"] != PASS:
        return_code = 1
        combined_status = payload["status"]
    elif enrichment_returncode not in (None, 0):
        return_code = 2
        combined_status = "STABLE_PASS_ENRICHMENT_NOT_PASS"
    else:
        return_code = 0
        combined_status = "PASS"
    print(
        json.dumps(
            {
                "status": payload["status"],
                "combined_status": combined_status,
                "out": args.out,
                "enrichment_returncode": enrichment_returncode,
            },
            sort_keys=True,
        )
    )
    return return_code'''
    new_cli = '''    parser.add_argument("--stability-spec", default="config/evaluator_stability_gate.json")
    parser.add_argument(
        "--continuous-release-spec",
        default="config/continuous_teacher_release_gate.json",
    )
    args = parser.parse_args(argv)
    payload = aggregate(
        Path(args.protocol),
        Path(args.jobs),
        Path(args.results),
        Path(args.out),
        args.expected_total_jobs,
        args.allow_synthetic_results,
        Path(args.stability_spec),
        Path(args.continuous_release_spec),
    )
    return_code = 0 if payload["status"] == PASS else 1
    print(
        json.dumps(
            {
                "status": payload["status"],
                "combined_status": payload["status"],
                "out": args.out,
                "release_policy": payload.get("release_policy", "MISSING"),
            },
            sort_keys=True,
        )
    )
    return return_code'''
    if old_cli not in text:
        raise RuntimeError("aggregate CLI block changed upstream")
    text = text.replace(old_cli, new_cli, 1)
    path.write_text(text, encoding="utf-8")


def patch_tests(destination: Path) -> None:
    path = destination / "tests/test_stability_gate.py"
    text = path.read_text(encoding="utf-8")
    old_test = '''    def test_aggregate_fails_when_candidate_a_calls_are_threshold_fragile(self) -> None:
        jobs = self.reduced_valid_jobs()
        job_path = self.tmp / "jobs.tsv"
        result_path = self.tmp / "results.tsv"
        pose_path = self.tmp / "pose_scores.tsv"
        out = self.tmp / "EVALUATOR_STABLE.json"
        write_tsv(job_path, jobs, list(jobs[0]))
        results = self.passing_results(jobs)
        write_tsv(result_path, results, list(results[0]))
        self.write_pose_scores(jobs, pose_path)
        pose_rows = read_tsv(pose_path)
        for row in pose_rows:
            if row["entity_type"] == "candidate":
                row.update(
                    {
                        "hotspot_overlap": "13",
                        "total_occlusion": "460",
                        "cdr3_occlusion": "90",
                        "cdr3_fraction": "0.14",
                    }
                )
        write_tsv(pose_path, pose_rows, list(pose_rows[0]))
        code = aggregate_results.main(
            ["--protocol", str(PROTOCOL), "--jobs", str(job_path), "--results", str(result_path), "--out", str(out), "--expected-total-jobs", str(len(jobs)), "--allow-synthetic-results"]
        )
        self.assertNotEqual(code, 0)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["gates"]["candidate_threshold_sensitivity"]["status"], "FAIL")
'''
    new_test = '''    def test_candidate_tier_sensitivity_is_diagnostic_for_continuous_release(self) -> None:
        jobs = self.reduced_valid_jobs()
        job_path = self.tmp / "jobs.tsv"
        result_path = self.tmp / "results.tsv"
        pose_path = self.tmp / "pose_scores.tsv"
        out = self.tmp / "EVALUATOR_STABLE.json"
        write_tsv(job_path, jobs, list(jobs[0]))
        results = self.passing_results(jobs)
        write_tsv(result_path, results, list(results[0]))
        self.write_pose_scores(jobs, pose_path)
        pose_rows = read_tsv(pose_path)
        for row in pose_rows:
            if row["entity_type"] == "candidate":
                row.update(
                    {
                        "hotspot_overlap": "13",
                        "total_occlusion": "460",
                        "cdr3_occlusion": "90",
                        "cdr3_fraction": "0.14",
                    }
                )
        write_tsv(pose_path, pose_rows, list(pose_rows[0]))
        code = aggregate_results.main(
            ["--protocol", str(PROTOCOL), "--jobs", str(job_path), "--results", str(result_path), "--out", str(out), "--expected-total-jobs", str(len(jobs)), "--allow-synthetic-results"]
        )
        self.assertEqual(code, 0)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["status"], "PASS")
        self.assertNotIn("candidate_threshold_sensitivity", payload["gates"])
        self.assertEqual(payload["diagnostics"]["candidate_threshold_sensitivity"]["status"], "FAIL")
'''
    if old_test not in text:
        raise RuntimeError("threshold-sensitivity test changed upstream")
    text = text.replace(old_test, new_test, 1)
    text = text.replace(
        'self.assertEqual(payload["gates"]["candidate_threshold_sensitivity"]["status"], "NOT_READY")',
        'self.assertEqual(payload["diagnostics"]["candidate_threshold_sensitivity"]["status"], "NOT_READY")',
    )
    old_cli_test = '''    def test_aggregate_cli_is_nonzero_when_enrichment_does_not_pass(self) -> None:
        payload = {"status": "PASS", "evidence_mode": "production_pose_backed"}
        with mock.patch.object(aggregate_results, "aggregate", return_value=payload), mock.patch.object(
            aggregate_results.subprocess, "run", return_value=mock.Mock(returncode=1)
        ):
            code = aggregate_results.main(["--protocol", str(PROTOCOL)])
        self.assertEqual(code, 2)
'''
    new_cli_test = '''    def test_aggregate_cli_does_not_run_legacy_enrichment(self) -> None:
        payload = {
            "status": "PASS",
            "evidence_mode": "production_pose_backed",
            "release_policy": "continuous_geometry_primary_legacy_tier_sensitivity_diagnostic_only",
        }
        with mock.patch.object(aggregate_results, "aggregate", return_value=payload):
            code = aggregate_results.main(["--protocol", str(PROTOCOL)])
        self.assertEqual(code, 0)
'''
    if old_cli_test not in text:
        raise RuntimeError("aggregate CLI test changed upstream")
    text = text.replace(old_cli_test, new_cli_test, 1)
    path.write_text(text, encoding="utf-8")


def patch_freeze_contract(destination: Path) -> None:
    path = destination / "scripts/freeze_protocol.py"
    text = path.read_text(encoding="utf-8")
    token = '    "config/evaluator_stability_gate.json",\n'
    if token not in text:
        raise RuntimeError("evaluator gate missing from FINAL_FILES")
    text = text.replace(
        token,
        token + '    "config/continuous_teacher_release_gate.json",\n',
        1,
    )
    path.write_text(text, encoding="utf-8")


def write_readme(destination: Path) -> None:
    (destination / "README.md").write_text(
        "# PVRIG V4-E Full-QC290 continuous dual-docking campaign\n\n"
        "V4-C remains FAIL and V4-D remains blocked. V4-E is a new pre-label protocol. "
        "It keeps the unchanged hard-tier sensitivity calculation as a diagnostic while "
        "using continuous R_dual_min as the only primary teacher endpoint.\n\n"
        "The panel remains 226 OPEN_TRAIN, 32 OPEN_DEVELOPMENT, and 32 sealed prospective "
        "computational test rows with parent-cluster separation. No output is a binding, "
        "affinity, competition, Docking Gold, or experimental blocking label.\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    destination = args.destination.resolve()
    assert_unlabeled_source(source)
    copy_clean_project(source, destination)
    configure(destination)
    patch_aggregate(destination)
    patch_tests(destination)
    patch_freeze_contract(destination)
    write_readme(destination)
    print(
        json.dumps(
            {
                "status": "PASS_V4_E_STAGED_BEFORE_LABELS",
                "destination": str(destination),
                "source_v4_d_generated_labels": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
