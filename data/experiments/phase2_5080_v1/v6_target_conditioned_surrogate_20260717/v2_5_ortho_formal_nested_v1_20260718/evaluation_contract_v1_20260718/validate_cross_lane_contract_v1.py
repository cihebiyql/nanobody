#!/usr/bin/env python3
"""Fail-closed structural validator for the frozen V2.5 cross-lane contract."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence


PRIMARY = "E_DECOUPLED_CONTACT_SHARED"
DIAGNOSTICS = {
    "B_CLEAN_TARGET_ATTENTION",
    "E_DECOUPLED_CONTACT_DETACHED",
}
REQUIRED_RAW_FIELDS = {
    "candidate_id",
    "outer_fold",
    "parent_framework_cluster",
    "teacher_source",
    "truth_R8",
    "truth_R9",
    "truth_Rdual",
    "M2_R8",
    "M2_R9",
    "C2_R8",
    "C2_R9",
    "E_SHARED_R8",
    "E_SHARED_R9",
    "contact_score_R8",
    "contact_score_R9",
}


class ContractError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate(contract: dict[str, Any], contract_dir: Path, *, verify_upstream_hashes: bool) -> dict[str, Any]:
    require(contract["status"] == "FROZEN_PRE_OUTER_RESULT_CROSS_LANE_DECISION_CONTRACT", "status_not_prefrozen")
    assertions = contract["preobservation_assertions"]
    require(assertions["cross_lane_outer_metrics_read_count"] == 0, "outer_metrics_already_read")
    require(assertions["v4_f_test32_access_count"] == 0, "sealed_access_nonzero")
    require(assertions["posthoc_lane_selection_allowed"] is False, "posthoc_lane_selection_enabled")
    require(assertions["live_training_graph_modified_by_this_contract"] is False, "live_graph_modification_claimed")

    roles = contract["lane_roles"]
    require(roles["formal_primary_base_lane"] == PRIMARY, "primary_lane_changed")
    require(set(roles["diagnostic_only_lanes"]) == DIAGNOSTICS, "diagnostic_lane_set_changed")
    require("cannot replace" in roles["selection_policy"], "diagnostic_replacement_not_forbidden")
    require("clip_grad_norm_" in roles["detached_claim_boundary"], "detached_indirect_coupling_missing")

    prediction = contract["prediction_contract"]
    require(prediction["direct_targets"] == ["R_8X6B", "R_9E6Y"], "direct_targets_changed")
    require(prediction["derived_output"] == "prediction_Rdual=min(prediction_R8,prediction_R9)", "exact_min_missing")
    require(prediction["independent_Rdual_output_allowed"] is False, "free_rdual_enabled")

    primary = contract["primary_stack"]
    require(primary["model_id"] == "M2_C2_E_SHARED_CONTACT2D_CONSTRAINED_STACK", "primary_model_changed")
    require(primary["role"] == "FORMAL_PRIMARY_PRODUCTION_CHALLENGER", "primary_role_changed")
    require(set(primary["base_components"]) == {"M2_FROZEN_ALPHA10", "C2_INNER_SELECTED_PCA8_RIDGE", PRIMARY}, "base_components_changed")
    require(set(primary["raw_required_fields"]) == REQUIRED_RAW_FIELDS, "required_raw_fields_changed")

    contact = primary["contact_feature_policy"]
    require(contact["available_primary_raw_dimension"] == 2, "contact_dimension_changed")
    require(contact["raw_fields"] == ["contact_score_R8", "contact_score_R9"], "contact_fields_changed")
    require(contact["full_14d_contact_summary_allowed"] is False, "unpersisted_contact_enabled")
    require(contact["scaling"]["scope"] == "outer-train inner-OOF rows only", "contact_scaling_scope_changed")
    require(contact["scaling"]["outer_test_fit_or_recalibration"] is False, "outer_contact_scaling_enabled")

    formula = primary["formula"]
    require(formula["contact_is_not_an_R_prediction"] is True, "contact_semantics_changed")
    require(formula["forbidden_formula"] == "contact_score_r-M2_r", "contact_minus_m2_guard_missing")
    require(set(formula["constraints"]) == {"w_E>=0", "w_C2>=0", "w_E+w_C2<=1", "beta_C>=0"}, "constraints_changed")
    require(formula["parameter_sharing"] == "w_E,w_C2,beta_C are shared across R8 and R9", "parameter_sharing_changed")
    require(formula["intercept"] is False, "intercept_enabled")

    fallback = primary["exact_m2_fallback"]
    require(fallback["candidate_parameters"] == {"w_E": 0.0, "w_C2": 0.0, "beta_C": 0.0}, "m2_fallback_not_exact")
    require(fallback["must_be_numerically_reproducible"] is True, "m2_fallback_not_reproducible")

    nested = contract["nested_cross_fitting"]
    require(nested["outer_unit"] == "parent_framework_cluster", "outer_unit_changed")
    require(nested["same_row_base_fit_and_meta_evaluation_allowed"] is False, "same_row_stacking_enabled")
    require(nested["outer_test_used_for_fit_scaling_selection_or_calibration"] is False, "outer_test_fit_enabled")
    require(nested["whole_parent_isolation_required"] is True, "whole_parent_isolation_disabled")

    gate = contract["promotion_gate"]
    require(gate["all_criteria_required"] is True, "partial_gate_enabled")
    require(gate["Rdual_spearman_min"] == 0.6194011215999979, "rho_gate_changed")
    require(gate["Rdual_mae_max"] == 0.0323587150283071, "mae_gate_changed")
    require(gate["Rdual_rmse_max"] == 0.04290748546218935, "rmse_gate_changed")
    require(gate["each_source_Rdual_mae_nonregression_vs_M2"] is True, "source_mae_gate_removed")
    require(gate["both_source_delta_Rdual_spearman_min"] == 0.0, "source_rho_gate_changed")
    require(gate["parent_macro_Rdual_mae_nonregression_vs_M2"] is True, "parent_macro_gate_removed")
    require(gate["parents_with_nonnegative_Rdual_mae_delta_min"] == 16, "parent_count_gate_changed")
    require(gate["paired_parent_bootstrap_delta_Rdual_spearman_95ci_lower_gt"] == 0.0, "bootstrap_gate_changed")
    require("retain exact M2 fallback" in gate["decision"], "fallback_decision_missing")

    prohibited = "\n".join(contract["prohibitions"])
    for phrase in (
        "V4-F/test32 access",
        "post-result lane selection",
        "B or E_DETACHED replacing E_SHARED as the formal primary",
        "same-row base prediction used to train and evaluate the meta-head",
        "R_dual_min predicted as an independent free output",
    ):
        require(phrase in prohibited, f"missing_prohibition:{phrase}")

    checked_hashes = 0
    if verify_upstream_hashes:
        for name, identity in contract["upstream_identity"].items():
            path = (contract_dir / identity["path"]).resolve()
            require(path.is_file(), f"upstream_missing:{name}")
            require(sha256(path) == identity["sha256"], f"upstream_hash_mismatch:{name}")
            checked_hashes += 1

    return {
        "schema_version": "pvrig_v2_5_cross_lane_contract_validation_v1",
        "status": "PASS",
        "primary_lane": PRIMARY,
        "diagnostic_lanes": sorted(DIAGNOSTICS),
        "required_raw_fields": len(REQUIRED_RAW_FIELDS),
        "upstream_hashes_checked": checked_hashes,
        "v4_f_test32_access_count": 0,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--contract", type=Path, required=True)
    result.add_argument("--verify-upstream-hashes", action="store_true")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    contract = json.loads(args.contract.read_text())
    result = validate(contract, args.contract.parent, verify_upstream_hashes=args.verify_upstream_hashes)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
