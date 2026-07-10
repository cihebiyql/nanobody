# Phase 2 V2 Completion Audit

Updated: 2026-07-09

Verdict: PASS

## Summary

- Real contact-map records: 371
- Real positive contact pairs: 32807
- Real non-contact negative pairs: 131228
- Contact test AUROC/AUPRC: 0.8728 / 0.6559
- Contact positive rate: 0.2056
- Pair test AUROC/AUPRC: 0.5180 / 0.2708
- Paratope test AUROC/AUPRC: 0.8804 / 0.5795
- Epitope test AUROC/AUPRC: 0.5888 / 0.1066
- PVRIG prediction rows: 50

## Checks

| Check | Status | Evidence |
| --- | --- | --- |
| cuda_5080_available | PASS | `environment_audit.md confirms torch CUDA on RTX 5080` |
| real_contact_records_present | PASS | `records=371 pos=32807 neg=131228` |
| contact_split_present | PASS | `{'train': 290, 'val': 49, 'test': 32}` |
| contact_test_metric_present | PASS | `{"contact_auprc": 0.6559011663561297, "contact_auroc": 0.8728014120832861, "contact_f1": 0.6392623895505186, "contact_fn": 201.0, "contact_fp": 738.0, "contact_n": 5024.0, "contact_positive_rate": 0.20561305732484075, "contact_precision": 0.5299363057324841, "contact_precision_at_poscount_or_50": 0.04268935454217218, "contact_recall": 0.8054211035818006, "contact_tn": 3253.0, "contact_tp": 832.0}` |
| contact_better_than_random | PASS | `auprc=0.6559011663561297 positive_rate=0.20561305732484075` |
| contact_auroc_above_random | PASS | `contact_auroc=0.8728014120832861` |
| pair_metrics_present | PASS | `{"pair_auprc": 0.2707656036425119, "pair_auroc": 0.5180380485527545, "pair_f1": 0.31250000000000006, "pair_fn": 150.0, "pair_fp": 246.0, "pair_n": 954.0, "pair_positive_rate": 0.25157232704402516, "pair_precision": 0.26785714285714285, "pair_recall": 0.375, "pair_tn": 468.0, "pair_tp": 90.0}` |
| hard_negative_breakdown_present | PASS | `dict_keys(['N1_easy_cross_antigen', 'N2_same_family_hard_antigen', 'N3_framework_similar_hard_vhh'])` |
| pvrig_predictions_50 | PASS | `rows=50` |
| pvrig_predictions_leakage_free | PASS | `{'NO_KNOWN_POSITIVE_LEAKAGE': 50}` |
| report_states_real_contact_boundary | PASS | `phase2_v2_eval.md` |

## Warnings

- pair binding remains weak: AUROC=0.5180, AUPRC=0.2708
- site paratope lower than V1 because V2 prioritizes real contact loss: 0.5795 < 0.6244
- site epitope lower than V1: 0.1066 < 0.1541

## Boundary

This audit proves V2 real heavy-atom contact-map training ran on the RTX 5080 environment and produced test metrics plus PVRIG re-scoring. It does not prove experimental binding, Kd, IC50, or PVRIG-PVRL2 blocking for new candidates.
