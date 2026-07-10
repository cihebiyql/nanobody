# Phase 2 V2.1 Final Validation

Updated: 2026-07-09

Verdict: PASS

## Summary

- Expanded contact records: 2725
- Positive contact pairs <=4.5 A: 293937
- Negative contact pairs >=8.0 A: 1175748
- Contact test AUROC/AUPRC: 0.8617 / 0.6157
- Contact positive rate: 0.2000
- Paratope AUPRC: 0.6411
- Epitope AUPRC: 0.1839
- Pair AUROC/AUPRC: 0.5160 / 0.2686
- PVRIG prediction rows: 50

## Checks

| Check | Status | Evidence |
| --- | --- | --- |
| cuda_5080_environment_recorded | PASS | `environment_audit.md records RTX 5080 CUDA availability` |
| expanded800_contact_dataset_present | PASS | `structures=800 records=2725 pos=293937 neg=1175748` |
| contact_summary_csv_matches_json | PASS | `csv_records=2725 csv_pos=293937 csv_neg=1175748` |
| train_val_test_contact_split_present | PASS | `{"test": 318, "train": 1932, "val": 475}` |
| training_outputs_present | PASS | `checkpoint_mb=8.5` |
| contact_model_above_random | PASS | `contact_auroc=0.8617 contact_auprc=0.6157 random=0.2000` |
| site_heads_improved_over_v1 | PASS | `paratope 0.6244->0.6411; epitope 0.1541->0.1839` |
| pair_metrics_present_with_boundary | PASS | `pair_auroc=0.5160 pair_auprc=0.2686` |
| pvrig_predictions_clean | PASS | `rows=50 leakage={'NO_KNOWN_POSITIVE_LEAKAGE': 50}` |
| reports_state_delivery_boundary | PASS | `audit/report preserve computational-only boundary` |
| comparison_records_expansion | PASS | `record_multiplier=7.35` |

## Warnings

- pair head remains weak: AUROC=0.5160, AUPRC=0.2686
- contact AUPRC is lower than small V2 but uses a much larger test set: 0.6157 vs 0.6559

## Boundary

This validates V2.1 as a completed computational training/evaluation package. It does not claim experimental binding, Kd, IC50, wet-lab efficacy, or clinical effect. Pair-level classification remains the main model bottleneck.
