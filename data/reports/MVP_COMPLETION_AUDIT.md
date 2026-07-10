# PVRIG-VHH MVP Completion Audit

Updated: 2026-07-09

Verdict: PASS

## Summary

- Candidate pool rows: 547
- Scored rows: 547
- Top new candidates: 50
- Control rows: 47
- Structure contact rows: 1286 across 12 structures

## Checks

| Check | Status | Evidence |
| --- | --- | --- |
| pool_nonempty | PASS | `pool_rows=547` |
| scores_match_pool | PASS | `scores=547 pool=547` |
| top_nonempty | PASS | `top_rows=50` |
| controls_nonempty | PASS | `control_rows=47` |
| contact_nonempty | PASS | `contact_rows=1286` |
| top_all_no_leakage | PASS | `{'NO_KNOWN_POSITIVE_LEAKAGE': 50}` |
| top_all_new_candidates | PASS | `{'new_candidate_from_zym_vhh_affinity_seq_test': 50}` |
| controls_all_excluded_or_held | PASS | `{'HOLD_NEAR_KNOWN_POSITIVE_MANUAL_LEAKAGE_REVIEW': 29, 'EXCLUDE_EXACT_KNOWN_POSITIVE_CONTROL': 18}` |
| known_positive_exact_controls_present | PASS | `{'NO_KNOWN_POSITIVE_LEAKAGE': 500, 'NEAR_KNOWN_POSITIVE_OR_CDR_SIMILAR': 29, 'EXACT_KNOWN_POSITIVE': 18}` |
| near_positive_controls_present | PASS | `{'NO_KNOWN_POSITIVE_LEAKAGE': 500, 'NEAR_KNOWN_POSITIVE_OR_CDR_SIMILAR': 29, 'EXACT_KNOWN_POSITIVE': 18}` |
| summary_counts_agree | PASS | `{"candidate_pool_rows": 547, "scored_rows": 547, "top_rows": 50, "control_rows": 47}` |
| contact_summary_agrees | PASS | `{"contact_rows": 1286, "cutoff_angstrom": 4.5, "eligible_sampled_structures": 12, "manifest_rows": 2422, "output": "/mnt/d/work/抗体/data/model_data/sabdab2_single_domain_contacts_mvp.csv", "processed_structures": 12, "stderr": "", "structures_with_contacts": 12}` |

## Boundary

This audit proves the MVP computational workflow is runnable and internally gated. It does not prove experimental Kd, IC50, or cellular blocking for new candidates.
