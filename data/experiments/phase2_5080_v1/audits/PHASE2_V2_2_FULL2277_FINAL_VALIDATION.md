# Phase 2 V2.2 Full2277 Final Validation

Updated: 2026-07-09

Verdict: PASS

## Summary

- Full contact records: 8414
- Positive contact pairs <=4.5 A: 855922
- Negative contact pairs >=8.0 A: 3423688
- Contact test AUROC/AUPRC: 0.8975 / 0.7242
- Contact positive rate: 0.2082
- Paratope AUPRC: 0.6477
- Epitope AUPRC: 0.2272
- Pair AUROC/AUPRC: 0.5833 / 0.3338
- PVRIG prediction rows: 50

## Checks

| Check | Status | Evidence |
| --- | --- | --- |
| cuda_5080_environment_recorded | PASS | `environment audit records RTX 5080 CUDA` |
| full2277_contact_dataset_present | PASS | `records=8414 pos=855922 neg=3423688` |
| contact_summary_csv_matches_json | PASS | `csv_records=8414` |
| train_val_test_contact_split_present | PASS | `{"test": 884, "train": 6068, "val": 1462}` |
| training_outputs_present | PASS | `checkpoint_mb=8.5` |
| contact_model_above_random | PASS | `contact_auroc=0.8975 contact_auprc=0.7242 random=0.2082` |
| improves_contact_over_v21 | PASS | `contact AUPRC 0.6157->0.7242` |
| improves_site_over_v21 | PASS | `paratope 0.6411->0.6477; epitope 0.1839->0.2272` |
| improves_pair_over_v21 | PASS | `pair AUROC/AUPRC 0.5160/0.2686->0.5833/0.3338` |
| pvrig_predictions_clean | PASS | `rows=50 leakage={'NO_KNOWN_POSITIVE_LEAKAGE': 50}` |
| report_states_boundary | PASS | `report keeps computational-prior boundary` |

## Warnings

- pair head improved but remains below strong standalone threshold: AUROC=0.5833, AUPRC=0.3338

## Boundary

This validates V2.2 as a completed computational training/evaluation package over the full2277 real-contact dataset. It supports candidate prioritization and next-round structure computation, but it does not claim experimental binding, Kd, IC50, wet-lab efficacy, clinical effect, or proven PVRIG-PVRL2 blocking.
