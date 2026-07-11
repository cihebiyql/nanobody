# Phase 2 V2.5 Final Audit V1

- Status: **PASS**
- Formal decision: **DATA_NOT_READY_FOR_TARGET_MODEL**
- Data readiness: **DATA_NOT_READY**
- Checks: 27/27 pass-or-warn
- Claim boundary: `ranking_evidence_not_experimental_blocker_validation`

## Checks

- [PASS] `evidence_registry_artifact_present` (REQUIRED) - {'path': 'experiments/phase2_5080_v1/data_splits/evidence_registry_v2_5.csv', 'present': True}
- [PASS] `formal_blinded_artifact_present` (REQUIRED) - {'path': 'experiments/phase2_5080_v1/prepared/phase2_v2_5_generic/nanobind_affinity_formal_blinded_v2_5.csv', 'present': True}
- [PASS] `formal_labels_artifact_present` (REQUIRED) - {'path': 'experiments/phase2_5080_v1/prepared/phase2_v2_5_generic/nanobind_affinity_formal_labels_sealed_v2_5.csv', 'present': True}
- [PASS] `external_dataset_usage_artifact_present` (REQUIRED) - {'path': 'experiments/phase2_5080_v1/data_splits/external_dataset_usage_manifest_v2_5.csv', 'present': True}
- [PASS] `pose_summary_artifact_present` (REQUIRED) - {'path': 'experiments/phase2_5080_v1/prepared/pvrig_pose_proxy_summary_v2_5.csv', 'present': True}
- [PASS] `metrics_artifact_present` (REQUIRED) - {'path': 'experiments/phase2_5080_v1/reports/phase2_v2_5_metrics_v1.json', 'present': True}
- [PASS] `preregistration_artifact_present` (REQUIRED) - {'path': 'experiments/phase2_5080_v1/audits/phase2_v2_5_preregistration_v1.json', 'present': True}
- [PASS] `canonical_required_schema_fields_present` (REQUIRED) - []
- [PASS] `canonical_required_schema_fields_non_null` (REQUIRED) - {'forbidden_use': 0, 'leakage_group_id': 0, 'sequence_sha256': 0, 'ground_truth_kind': 0, 'target_id': 0, 'sample_id': 0, 'source_id': 0, 'sealed_status': 0, 'label_axis': 0, 'evidence_level': 0, 'vhh_sequence': 0, 'source_path_or_locator': 0, 'dataset_version': 0, 'target_sequence_sha256': 0, 'split_group_id': 0, 'target_construct': 0, 'family_id': 0, 'allowed_use': 0}
- [PASS] `conditional_nulls_have_missing_reason` (REQUIRED) - {'rows_without_missing_reason': []}
- [PASS] `proxy_evidence_not_used_as_verified_truth` (REQUIRED) - []
- [PASS] `constructed_proxy_not_ordinary_bce_eligible` (REQUIRED) - []
- [PASS] `known_positive_and_controls_not_in_ordinary_lanes` (REQUIRED) - []
- [PASS] `verified_negative_has_assay_source_locator` (REQUIRED) - []
- [PASS] `assay_metric_units_and_directions_present` (REQUIRED) - []
- [PASS] `mutation_primary_has_reference_and_measured_effect` (REQUIRED) - []
- [PASS] `formal_blinded_manifest_does_not_expose_labels` (REQUIRED) - []
- [PASS] `external_dataset_metadata_fields_present` (REQUIRED) - {'missing': [], 'accepted_version_fields_present': ['source_version']}
- [PASS] `external_dataset_metadata_complete` (REQUIRED) - {'forbidden_use': 0, 'license_or_usage_status': 0, 'excluded_row_count': 0, 'accession_mapping_status': 0, 'sequence_mapping_status': 0, 'unit_normalization_status': 0, 'source_id': 0, 'duplicate_policy': 0, 'redistribution_allowed': 0, 'enters_training_or_evaluation': 0, 'source_or_dataset_version': 0}
- [PASS] `external_dataset_boolean_fields_valid` (REQUIRED) - []
- [PASS] `external_dataset_usage_approved_when_entering_training_or_evaluation` (REQUIRED) - []
- [PASS] `reviewed_local_use_training_requires_redistribution_prohibition` (REQUIRED) - []
- [PASS] `calibration_not_applicable_without_verified_pos_and_neg` (REQUIRED) - {'counts': {'verified_binary_positive': 0, 'verified_binary_negative': 0}, 'calibration': {'fit_split': 'dev_only', 'reason': 'verified positive and verified negative labels are not both present', 'status': 'NOT_APPLICABLE'}, 'probability_fields': {}}
- [PASS] `pose_global_fusion_requires_80pct_exact_qc_coverage` (REQUIRED) - {'coverage': 0.04, 'global_fusion_applied': False, 'missingness_audit_pass': False}
- [PASS] `registered_input_sha256_values_match` (REQUIRED) - {}
- [PASS] `claim_boundary_excludes_forbidden_biological_claims` (REQUIRED) - forbidden claim scan passed
- [PASS] `generic_transfer_success_cannot_be_pvrig_target_success` (REQUIRED) - {'decision': 'DATA_NOT_READY_FOR_TARGET_MODEL', 'readiness': 'DATA_NOT_READY'}
