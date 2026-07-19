#!/usr/bin/env python3
"""Fail-closed static validator for the V2.5 causal-ablation hardened V1.1 package."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


EXPECTED_LIVE_GRAPH_SHA = "ea1c4c1eedf189d9542e3e73b0c0368777b4073468fd4e39535b28fd7fa24185"
EXPECTED_PERTURBATIONS = {
    "HOTSPOT_INTERFACE_MASK_SWAP",
    "RECEPTOR_CONFORMER_SWAP",
    "TARGET_RESIDUE_FEATURE_PERMUTATION",
    "CONTACT_LABEL_WITHIN_PARENT_DONOR_SHUFFLE",
    "NO_CONTACT_META_EVIDENCE",
}
EXPECTED_MASK_NULL = "MATCHED_CARDINALITY_PREVALENCE_MASK_POSITION_NULL"
EXPECTED_MASK_NULL_REPLICATES = 256
EXPECTED_MASK_NULL_MASTER_SEED = 1931
SEALED_TOKENS = ("v4_f", "v4-f", "test32", "sealed")


class ValidationError(RuntimeError):
    pass


def require(value: bool, message: str) -> None:
    if not value:
        raise ValidationError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"json_object:{path}")
    return value


def reject_sealed_path(path: Path) -> None:
    lowered = str(path).casefold()
    require(not any(token in lowered for token in SEALED_TOKENS), f"sealed_path:{path}")


def validate(package_root: Path, source_root: Path | None = None) -> dict[str, Any]:
    package = package_root.resolve()
    reject_sealed_path(package)
    manifest = read_json(package / "PACKAGE_MANIFEST.json")
    require(manifest["status"] == "PASS_IMMUTABLE_NONLAUNCHING_PLAN_BUILT", "manifest_status")
    require(not manifest["launch_authorized"] and not manifest["training_or_prediction_executed"], "manifest_nonlaunch")
    require(not manifest["upstream_live_job_graph_modified"], "manifest_live_graph_modified")
    require(manifest["v4_f_test32_access_count"] == 0, "manifest_sealed_access")
    for relative, expected in manifest["files"].items():
        path = package / relative
        require(path.is_file() and not path.is_symlink(), f"package_file:{relative}")
        require(sha256(path) == expected, f"package_hash:{relative}")
    require(sha256(package / "CAUSAL_ABLATION_CONTRACT_V1_1.json") == manifest["contract_sha256"], "contract_hash")
    require(sha256(package / "ABLATION_JOB_GRAPH.json") == manifest["job_graph_sha256"], "job_graph_hash")

    contract = read_json(package / "CAUSAL_ABLATION_CONTRACT_V1_1.json")
    require(contract["status"] == "FROZEN_PRE_OUTER_RESULT_NONLAUNCHING_V1_1_HARDENED", "contract_status")
    require(set(contract["perturbations"]) == EXPECTED_PERTURBATIONS, "perturbation_set")
    require(contract["versioning"]["version"] == "V1.1", "version")
    require(not contract["versioning"]["frozen_v1_mutated"], "v1_mutated")
    require(contract["upstream_bindings"]["frozen_v1_implementation"]["sha256"] ==
            "b9b8f191f154710715619c21be0e7d0c751a7225f8fcef739c55dd65484a1b89", "v1_binding")
    require(contract["preobservation_assertions"]["e_shared_cross_lane_outer_metrics_read_count"] == 0, "outer_metrics_read")
    require(contract["preobservation_assertions"]["v4_f_test32_access_count"] == 0, "contract_sealed_access")
    require(not contract["preobservation_assertions"]["live_301_job_graph_modified"], "contract_live_graph_modified")
    require(contract["formal_primary_reference"]["base_lane"] == "E_DECOUPLED_CONTACT_SHARED", "primary_lane")
    require(contract["decision_boundary"]["role"] == "DIAGNOSTIC_ONLY_NOT_A_MODEL_PROMOTION_GATE", "diagnostic_boundary")
    require(not contract["decision_boundary"]["can_promote_v2_5"], "promotion_boundary")
    prediction = contract["prediction_contract"]
    require(prediction["derived_output"] == "prediction_Rdual=min(prediction_R8,prediction_R9)", "exact_min_formula")
    require(prediction["exact_min_tolerance"] == 1e-12 and not prediction["independent_Rdual_output_allowed"], "exact_min_contract")
    require(contract["perturbations"]["TARGET_RESIDUE_FEATURE_PERMUTATION"]["seed"] == 1931, "target_seed")
    shuffle = contract["perturbations"]["CONTACT_LABEL_WITHIN_PARENT_DONOR_SHUFFLE"]
    require(shuffle["seed"] == 1931 and shuffle["same_clean_selected_hparam_required"], "shuffle_contract")
    require(shuffle["singleton_parent_policy"] == "FAIL_CLOSED_NO_CROSS_PARENT_DONOR", "shuffle_singleton")
    require(shuffle["pre_optimizer_audit_required"] == "DONOR_RECIPIENT_CONTACT_PAYLOAD_DISTANCE_POWER_AUDIT_V1_1", "shuffle_audit")
    require(shuffle["audit_failure_policy"] == "FAIL_CLOSED_BEFORE_MODEL_OR_OPTIMIZER_INITIALIZATION", "shuffle_audit_failure")
    nulls = contract["null_controls"]
    require(EXPECTED_MASK_NULL in nulls, "mask_null_missing")
    mask_null = nulls[EXPECTED_MASK_NULL]
    require(mask_null["null_replicates"] == EXPECTED_MASK_NULL_REPLICATES, "mask_null_replicates")
    require(mask_null["master_seed"] == EXPECTED_MASK_NULL_MASTER_SEED, "mask_null_seed")
    require(mask_null["retraining_allowed"] is False and mask_null["model_forward_repetition_required"] is False, "mask_null_execution")
    invariants = set(mask_null["required_invariants"])
    require({
        "hotspot_cardinality_exact", "interface_cardinality_exact",
        "hotspot_prevalence_exact", "interface_prevalence_exact",
        "hotspot_interface_overlap_exact", "joint_mask_contingency_exact",
    } <= invariants, "mask_null_invariants")
    power = nulls["DONOR_RECIPIENT_CONTACT_PAYLOAD_DISTANCE_POWER_AUDIT_V1_1"]
    require(not power["uses_scalar_truth"] and not power["uses_heldout_rows"], "donor_power_leakage")
    require(power["failure_policy"].startswith("Any missing field"), "donor_power_failure_policy")
    require(power["thresholds"] == {
        "complete_payload_changed_fraction_min": 0.90,
        "supervision_changed_fraction_min": 0.80,
        "supervision_median_distance_min": 0.01,
        "supervision_mapped_to_eligible_median_ratio_min": 0.50,
        "supervision_kish_effective_fraction_min": 0.50,
        "per_parent_supervision_changed_fraction_min": 0.50,
        "distance_epsilon": 1e-8,
    }, "donor_power_thresholds")
    mask_gate = contract["causal_claim_gates"]["HOTSPOT_INTERFACE_MASK_SWAP"]
    require(mask_gate["matched_prevalence_position_null_required"], "mask_gate_null")
    require(mask_gate["matched_null_replicates"] == EXPECTED_MASK_NULL_REPLICATES, "mask_gate_replicates")
    require(mask_gate["matched_null_empirical_p_lte"] == 0.05, "mask_gate_p")

    graph = read_json(package / "ABLATION_JOB_GRAPH.json")
    require(graph["status"] == "FROZEN_NONLAUNCHING_PLAN_ONLY", "graph_status")
    require(not graph["execution_authorized"] and not graph["training_or_prediction_executed"], "graph_nonlaunch")
    require(not graph["live_301_job_graph_modified"], "graph_live_modified")
    require(graph["upstream_live_job_graph_sha256"] == EXPECTED_LIVE_GRAPH_SHA, "graph_upstream_sha")
    require(graph["v4_f_test32_access_count"] == 0, "graph_sealed_access")
    jobs = graph["jobs"]
    require(len(jobs) == 131 and len({job["job_id"] for job in jobs}) == 131, "job_ids")
    counts = Counter(job["kind"] for job in jobs)
    expected_counts = Counter({
        "GPU_INFERENCE_PERTURB": 45,
        "CPU_INFERENCE_ENSEMBLE": 15,
        "GPU_CONTACT_SHUFFLE_INNER_RETRAIN": 25,
        "GPU_CONTACT_SHUFFLE_OUTER_RETRAIN": 15,
        "CPU_CONTACT_SHUFFLE_ENSEMBLE": 5,
        "CPU_NESTED_META_EVALUATE": 25,
        "CPU_FINAL_COLLECT": 1,
    })
    require(counts == expected_counts, "job_counts")
    identifiers = {job["job_id"] for job in jobs}
    for job in jobs:
        require(not job["execution_authorized"], f"job_authorized:{job['job_id']}")
        require("command" not in job, f"job_command_present:{job['job_id']}")
        require(set(job["dependencies"]) <= identifiers, f"job_dependency:{job['job_id']}")
        for dependency in job["external_dependencies"]:
            require(not any(token in dependency.casefold() for token in SEALED_TOKENS), f"sealed_dependency:{job['job_id']}")
    inference = [job for job in jobs if job["kind"] == "GPU_INFERENCE_PERTURB"]
    require({job["perturbation"] for job in inference} == {
        "HOTSPOT_INTERFACE_MASK_SWAP", "RECEPTOR_CONFORMER_SWAP", "TARGET_RESIDUE_FEATURE_PERMUTATION",
    }, "inference_perturbations")
    require({job["seed"] for job in inference} == {43, 97, 193}, "inference_seeds")
    mask_jobs = [job for job in inference if job["perturbation"] == "HOTSPOT_INTERFACE_MASK_SWAP"]
    require(len(mask_jobs) == 15, "mask_job_count")
    require(all(job.get("required_null_control") == EXPECTED_MASK_NULL for job in mask_jobs), "mask_job_null")
    require(all(job.get("mask_null_replicates") == EXPECTED_MASK_NULL_REPLICATES for job in mask_jobs), "mask_job_replicates")
    require(all(job.get("mask_null_master_seed") == EXPECTED_MASK_NULL_MASTER_SEED for job in mask_jobs), "mask_job_seed")
    require(all(job.get("mask_null_rescore_uses_same_frozen_contact_map") is True for job in mask_jobs), "mask_job_rescore")
    require(all(job.get("mask_null_requires_additional_model_forward") is False for job in mask_jobs), "mask_job_no_forward")
    shuffle_jobs = [job for job in jobs if "CONTACT_SHUFFLE" in job["kind"] and "RETRAIN" in job["kind"]]
    require(all(job["donor_seed"] == 1931 for job in shuffle_jobs), "shuffle_seed_jobs")
    require(len(shuffle_jobs) == 40, "shuffle_job_count")
    require(all(job.get("pre_optimizer_payload_power_audit_required") is True for job in shuffle_jobs), "shuffle_job_audit")
    require(all(job.get("audit_failure_policy") == "FAIL_CLOSED_BEFORE_MODEL_OR_OPTIMIZER_INITIALIZATION" for job in shuffle_jobs), "shuffle_job_failure")
    require(graph["v1_1_hardening_embedded_without_extra_jobs"] == {
        "mask_null_bank_jobs": 15,
        "mask_null_replicates_per_job": 256,
        "contact_shuffle_pre_optimizer_audits": 40,
        "extra_jobs": 0,
    }, "hardening_job_contract")

    if source_root is not None:
        source = source_root.resolve()
        reject_sealed_path(source)
        live_graph = source.parent / "prepared/nonlaunching_package_v1_3/node1_bundle/plan/job_graph.json"
        require(live_graph.is_file() and sha256(live_graph) == EXPECTED_LIVE_GRAPH_SHA, "source_live_graph_changed")
        for binding in contract["upstream_bindings"].values():
            path = (source / binding["path"]).resolve()
            reject_sealed_path(path)
            require(path.is_file() and sha256(path) == binding["sha256"], f"source_binding:{path}")

    sums = {}
    for line in (package / "SHA256SUMS").read_text().splitlines():
        digest, relative = line.split("  ", 1)
        sums[relative] = digest
    for relative, expected in sums.items():
        require(sha256(package / relative) == expected, f"sums_hash:{relative}")
    return {
        "status": "PASS_IMMUTABLE_NONLAUNCHING_CAUSAL_ABLATION_AUDIT",
        "jobs": 131,
        "gpu_jobs": 85,
        "cpu_jobs": 46,
        "perturbations": sorted(EXPECTED_PERTURBATIONS),
        "matched_prevalence_mask_null_replicates": EXPECTED_MASK_NULL_REPLICATES,
        "contact_shuffle_pre_optimizer_audits": 40,
        "v1_frozen_package_mutated": False,
        "contract_sha256": manifest["contract_sha256"],
        "job_graph_sha256": manifest["job_graph_sha256"],
        "live_graph_modified": False,
        "v4_f_test32_access_count": 0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(validate(args.package_root, args.source_root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
