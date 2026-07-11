# Phase 2 V2.3 P0-P4 Final Audit V1

- Status: **PASS_WITH_PAIR_RANKING_LIMITATION**
- Checks: 37/37 passed
- Seeds: 43, 53, 67
- Candidate rows: 50
- Exact pose coverage: 0/50
- Calibration: NOT_APPLICABLE

## Final Metrics

- Contact AUPRC mean: 0.519729
- Paratope AUPRC mean: 0.630628
- Epitope AUPRC mean: 0.159777
- Ranking MRR mean/random: 0.524921 / 0.532976

## Checks

- [PASS] `p0_independent_split_validation_pass` - checks=72
- [PASS] `p0_all_72_split_checks_pass` - []
- [PASS] `p1_target_proxy_contract_is_explicit` - derived_structure_supported_proxy_not_reviewed_uniprot_topological_domain
- [PASS] `p1_target_is_not_mislabeled_reviewed_domain` - derived_structure_supported_proxy_not_reviewed_uniprot_topological_domain
- [PASS] `p1_external_priors_complete` - {'nanobind_seq': 50, 'nanobind_site': 50, 'nanobind_pro': 50, 'deepnano_seq': 50, 'deepnano_site': 50}
- [PASS] `p1_external_prior_boundary` - External model outputs are uncalibrated binding/site priors, not blocker probabilities.
- [PASS] `p2_esm2_cache_exhaustive_pass` - {'rows': 4935, 'shards': 21}
- [PASS] `p2_esm2_cache_no_orphans` - 0
- [PASS] `p2_seed43_metrics_present` - /mnt/d/work/抗体/data/experiments/phase2_5080_v1/runs/phase2_v2_3_strict_hardened_20260710_seed43
- [PASS] `p2_seed43_pair_boundary` - constructed rows are unlabeled contrastive candidates, not verified non-binders
- [PASS] `p2_seed43_portable_checkpoint` - /mnt/d/work/抗体/data/experiments/phase2_5080_v1/checkpoints/phase2_v2_3_strict_seed43_best_checkpoint.pt
- [PASS] `p2_seed53_metrics_present` - /mnt/d/work/抗体/data/experiments/phase2_5080_v1/runs/phase2_v2_3_strict_hardened_20260710_seed53
- [PASS] `p2_seed53_pair_boundary` - constructed rows are unlabeled contrastive candidates, not verified non-binders
- [PASS] `p2_seed53_dataset_sizes_match` - {'contact_test': 1262, 'contact_train': 5890, 'contact_val': 1262, 'pair_test': 686, 'pair_train': 3262, 'pair_val': 712, 'rank_test': 502, 'rank_train': 2402, 'rank_val': 527, 'site_test': 184, 'site_train': 861, 'site_val': 185}
- [PASS] `p2_seed53_portable_checkpoint` - /mnt/d/work/抗体/data/experiments/phase2_5080_v1/checkpoints/phase2_v2_3_strict_seed53_best_checkpoint.pt
- [PASS] `p2_seed67_metrics_present` - /mnt/d/work/抗体/data/experiments/phase2_5080_v1/runs/phase2_v2_3_strict_hardened_20260710_seed67
- [PASS] `p2_seed67_pair_boundary` - constructed rows are unlabeled contrastive candidates, not verified non-binders
- [PASS] `p2_seed67_dataset_sizes_match` - {'contact_test': 1262, 'contact_train': 5890, 'contact_val': 1262, 'pair_test': 686, 'pair_train': 3262, 'pair_val': 712, 'rank_test': 502, 'rank_train': 2402, 'rank_val': 527, 'site_test': 184, 'site_train': 861, 'site_val': 185}
- [PASS] `p2_seed67_portable_checkpoint` - /mnt/d/work/抗体/data/experiments/phase2_5080_v1/checkpoints/phase2_v2_3_strict_seed67_best_checkpoint.pt
- [PASS] `p2_three_cuda_runs_telemetry_pass` - ['NVIDIA GeForce RTX 5080']
- [PASS] `p2_gpu_was_materially_used` - [{'seed': 43, 'max_util': 62.0, 'max_mem': 5984.0}, {'seed': 53, 'max_util': 65.0, 'max_mem': 5634.0}, {'seed': 67, 'max_util': 63.0, 'max_mem': 5632.0}]
- [PASS] `p2_runtime_staging_byte_equivalent` - 786254847
- [PASS] `p2_portable_inference_exact` - {'phase2_v2_3_pair_ranking_logit': 0.0, 'phase2_v2_3_combined_ranking_ai_prior': 0.0, 'phase2_v2_3_contact_top20_mean_ai_prior': 0.0}
- [PASS] `p4_multiseed_summary_pass` - ['phase2_v2_3_strict_hardened_20260710_seed43', 'phase2_v2_3_strict_hardened_20260710_seed53', 'phase2_v2_3_strict_hardened_20260710_seed67']
- [PASS] `p4_calibration_honestly_not_applicable` - {'reason': 'no explicit verified binary calibration labels were provided', 'status': 'NOT_APPLICABLE'}
- [PASS] `p4_pair_ranking_limitation_explicit` - Strict ranking MRR is effectively at the exact random-order expectation; hard-negative pair wins and proxy AUROC are only modestly above chance.
- [PASS] `p4_validation_only_tuning_decision` - The single pre-registered rank-focused branch did not improve validation ranking MRR; no further test-guided hyperparameter search was performed.
- [PASS] `p3_pose_inventory_complete` - NO_EXACT_TOP50_POSES_FOUND
- [PASS] `p3_zero_pose_data_gate_explicit` - {'pose_coverage': 0, 'ai_only': 50}
- [PASS] `p3_fusion_validation_pass` - []
- [PASS] `p4_ensemble_has_50_three_seed_rows` - /mnt/d/work/抗体/data/experiments/phase2_5080_v1/predictions/pvrig_candidate_ranking_ai_prior_v2_3_multiseed_ensemble.csv
- [PASS] `p3_output_has_50_ai_only_rows` - /mnt/d/work/抗体/data/experiments/phase2_5080_v1/predictions/p3_late_fusion_rankings_v1.csv
- [PASS] `candidate_leakage_labels_clean` - {'NO_KNOWN_POSITIVE_LEAKAGE': 50}
- [PASS] `known_controls_absent_from_candidate_ensemble` - hash_overlap=0
- [PASS] `final_unit_suite_57_pass` - /mnt/d/work/抗体/data/experiments/phase2_5080_v1/logs/v2_3_final_full_unit_and_compile.log
- [PASS] `readme_documents_v2_3_boundary` - /mnt/d/work/抗体/data/experiments/phase2_5080_v1/README.md
- [PASS] `project_progress_updated` - /mnt/d/work/抗体/PROJECT_PROGRESS.md

Computational ranking evidence only; no experimental binding, Kd, IC50, or blocker-efficacy claim.
