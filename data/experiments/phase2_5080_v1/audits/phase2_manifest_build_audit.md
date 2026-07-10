# Phase 2 Manifest Build Audit

Updated: 2026-07-09

## Verdict

PASS: split manifests, pair negatives, contact negatives, and PVRIG external calibration manifest were generated.

## Summary

```json
{
  "contact_label_counts": {
    "0": 8696,
    "1": 2174
  },
  "contact_negative_rows": 8696,
  "contact_pair_rows": 10870,
  "pair_binding_rows": 4851,
  "pair_binding_split_counts": {
    "test": 954,
    "train": 3345,
    "val": 552
  },
  "pair_negative_rows": 3621,
  "pair_negative_type_counts": {
    "N1_easy_cross_antigen": 1230,
    "N2_same_family_hard_antigen": 1163,
    "N3_framework_similar_hard_vhh": 1228
  },
  "pvrig_external_rows": 97,
  "seed": 7,
  "structure_groups": 24,
  "structure_split_counts": {
    "test": 3,
    "train": 17,
    "val": 4
  },
  "zym_site_rows": 1230,
  "zym_split_counts": {
    "test": 240,
    "train": 851,
    "val": 139
  }
}
```

## Pair negative type counts

| negative_type | rows |
| --- | --- |
| N1_easy_cross_antigen | 1230 |
| N3_framework_similar_hard_vhh | 1228 |
| N2_same_family_hard_antigen | 1163 |

## Contact label counts

| label | rows |
| --- | --- |
| 0 | 8696 |
| 1 | 2174 |

## Boundary

Pair negatives are constructed negatives, not experimentally confirmed non-binders. N2/N3 are hard-negative heuristics and must be reported separately during evaluation.
PVRIG known positives and mutant controls are held out for calibration/inference only and are not training positives.
