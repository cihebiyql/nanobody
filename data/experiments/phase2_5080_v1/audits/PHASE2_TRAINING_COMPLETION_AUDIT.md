# Phase 2 V1 Training Completion Audit

Updated: 2026-07-09

Verdict: PASS

## Summary

- CUDA/5080 training environment: PASS
- ZYM site split rows: 1230
- Pair binding rows: 4851
- Pair negative rows: 3621
- Structure contact proxy rows: 10870
- PVRIG prediction rows: 50
- Phase2 paratope test AUPRC: 0.6244 vs Phase1 0.4174
- Phase2 epitope test AUPRC: 0.1541 vs Phase1 0.1325
- Phase2 pair test AUROC/AUPRC: 0.5153 / 0.2684

## Checks

| Check | Status | Evidence |
| --- | --- | --- |
| cuda_5080_available | PASS | `environment_audit.md` |
| site_split_nonempty | PASS | `rows=1230 splits={'train': 851, 'test': 240, 'val': 139}` |
| pair_split_has_pos_neg | PASS | `labels={0: 3621, 1: 1230}` |
| pair_negative_types_present | PASS | `{'N1_easy_cross_antigen': 1230, 'N3_framework_similar_hard_vhh': 1228, 'N2_same_family_hard_antigen': 1163}` |
| contact_pos_neg_present | PASS | `{0: 8696, 1: 2174}` |
| pvrig_predictions_50 | PASS | `rows=50` |
| pvrig_predictions_leakage_free | PASS | `{'NO_KNOWN_POSITIVE_LEAKAGE': 50}` |
| paratope_improved_vs_phase1 | PASS | `{"phase1_paratope_test_auprc": 0.41744344000115485, "phase2_paratope_test_auprc": 0.6244340297865512, "paratope_auprc_delta": 0.2069905897853963}` |
| epitope_improved_vs_phase1 | PASS | `{"phase1_epitope_test_auprc": 0.13251513532736475, "phase2_epitope_test_auprc": 0.15410052732313168, "epitope_auprc_delta": 0.021585391995766923}` |
| hard_negative_metrics_present | PASS | `dict_keys(['N1_easy_cross_antigen', 'N2_same_family_hard_antigen', 'N3_framework_similar_hard_vhh'])` |

## Warnings

- pair binding head is weak: test AUROC=0.5153, AUPRC=0.2684

## Boundary

This audit proves Phase 2 V1 was trained and evaluated on the RTX 5080 environment. It does not prove experimental binding or blocking. The pair-binding head is reported honestly as weak in this first V1 run.
