# Threshold Sensitivity Report

## Bottom line

- Default threshold row summarizes 109 consensus pose rows: A/A=3, single-A=36, B=57, E=13.
- Grid rows tested: 81.
- Case-level calls unchanged vs default in 4/81 parameter settings.
- This is a postprocessing robustness check on completed docking outputs; it does not replace fresh docking for new mutants.

## Default gate

- hotspot_overlap_count >= 14
- total_vhh_pvrl2_residue_pair_occlusion >= 500
- cdr3_pvrl2_residue_pair_occlusion >= 100
- cdr3_occlusion_fraction >= 0.15
- hotspot-only total occlusion < 50 remains binder-like/nonblocking.

## Most permissive settings by A signal

| threshold | A/A | single-A | plausible-B | evidence-E | changed cases |
| --- | ---: | ---: | ---: | ---: | ---: |
| h12_t400_c75_f0.1 | 17 | 46 | 37 | 9 | 8 |
| h12_t400_c75_f0.15 | 17 | 45 | 38 | 9 | 7 |
| h12_t400_c100_f0.1 | 17 | 45 | 38 | 9 | 8 |
| h12_t400_c100_f0.15 | 17 | 44 | 39 | 9 | 7 |
| h12_t500_c75_f0.1 | 17 | 41 | 38 | 13 | 8 |

## Most conservative settings by A signal

| threshold | A/A | single-A | plausible-B | evidence-E | changed cases |
| --- | ---: | ---: | ---: | ---: | ---: |
| h16_t600_c75_f0.2 | 0 | 13 | 76 | 20 | 6 |
| h16_t600_c100_f0.2 | 0 | 13 | 76 | 20 | 6 |
| h16_t600_c125_f0.2 | 0 | 13 | 76 | 20 | 6 |
| h16_t600_c125_f0.1 | 0 | 15 | 74 | 20 | 4 |
| h16_t600_c125_f0.15 | 0 | 15 | 74 | 20 | 4 |

## Use in production batching

- Keep the default HR-151 calibrated gate for primary ranking; use the grid only as a stability audit.
- Promote candidates only when dual-baseline support or repeated single-baseline A signal survives leakage and manual pose review.
- Treat threshold-sensitive A calls as re-dock/re-score items, not as final blockers.
- Re-run this script after any scoring, CDR-range, or consensus-rule change.
