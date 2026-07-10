# Phase 2 V2.1 Expanded800 Completion Audit

Updated: 2026-07-09

Verdict: PASS

## Summary

- Contact records: 371 -> 2725 (7.35x)
- Positive contact pairs: 32807 -> 293937 (8.96x)
- Negative contact pairs: 131228 -> 1175748 (8.96x)
- V2.1 contact test AUROC/AUPRC: 0.8617 / 0.6157
- V2.1 contact positive rate: 0.2000
- V2.1 paratope AUPRC: 0.6411
- V2.1 epitope AUPRC: 0.1839
- V2.1 pair AUROC/AUPRC: 0.5160 / 0.2686
- PVRIG predictions: 50 rows, all leakage-free

## Checks

| Check | Status | Evidence |
| --- | --- | --- |
| expanded_dataset_present | PASS | `records 371->2725; positives 32807->293937` |
| real_contact_labels_present | PASS | `pos=293937 neg=1175748` |
| v21_training_artifacts_present | PASS | `checkpoint and report exist` |
| contact_above_random | PASS | `auprc=0.6157 random=0.2000` |
| contact_auroc_above_random | PASS | `auroc=0.8617` |
| site_paratope_improved_over_v1 | PASS | `0.6244->0.6411` |
| site_epitope_improved_over_v1 | PASS | `0.1541->0.1839` |
| pvrig_predictions_50_clean | PASS | `rows=50 leakage={'NO_KNOWN_POSITIVE_LEAKAGE': 50}` |

## Warnings

- pair head remains weak: AUROC=0.5160, AUPRC=0.2686
- contact AUPRC lower than small V2 (0.6157 < 0.6559) but evaluated on 318 vs 32 test records

## Boundary

V2.1 expands and retrains the real heavy-atom contact-map workflow. It still does not prove experimental binding or PVRIG-PVRL2 blocking; pair-level binder classification remains the main bottleneck.
