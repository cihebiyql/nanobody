# Mutant Panel Threshold Sensitivity Report

Updated: 2026-07-08

## Bottom line

- Default threshold row summarizes 357 consensus pose rows: A/A=8, single-A=109, B=210, E=30.
- Grid rows tested: 81.
- Case-level calls unchanged vs default in 4/81 parameter settings.
- Default retained-A disruptive/alanine controls: consensus-A=3, any-A=12.
- This is a postprocessing robustness check on completed mutant/control docking outputs; it does not make near-positive mutants into new designs.

## Default gate

- hotspot_overlap_count >= 14
- total_vhh_pvrl2_residue_pair_occlusion >= 500
- cdr3_pvrl2_residue_pair_occlusion >= 100
- cdr3_occlusion_fraction >= 0.15
- hotspot-only total occlusion < 50 remains binder-like/nonblocking.

## Most permissive settings by A signal

| threshold | A/A | single-A | B | E | changed cases | disruptive any-A |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| h12_t400_c75_f0.1 | 70 | 142 | 125 | 20 | 25 | 14 |
| h12_t500_c75_f0.1 | 66 | 138 | 123 | 30 | 25 | 14 |
| h12_t400_c75_f0.15 | 66 | 124 | 147 | 20 | 24 | 14 |
| h12_t400_c100_f0.1 | 64 | 130 | 143 | 20 | 23 | 14 |
| h12_t400_c100_f0.15 | 64 | 120 | 153 | 20 | 23 | 14 |

## Most conservative settings by A signal

| threshold | A/A | single-A | B | E | changed cases | disruptive any-A |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| h16_t600_c125_f0.2 | 0 | 25 | 291 | 41 | 23 | 6 |
| h16_t600_c75_f0.2 | 0 | 26 | 290 | 41 | 22 | 6 |
| h16_t600_c100_f0.2 | 0 | 26 | 290 | 41 | 22 | 6 |
| h16_t500_c125_f0.2 | 0 | 29 | 298 | 30 | 20 | 6 |
| h16_t400_c125_f0.2 | 0 | 30 | 307 | 20 | 20 | 6 |

## Disruptive/alanine retained-A sensitivity

High retained-A settings:

| threshold | disruptive consensus-A | disruptive any-A | A/A | single-A |
| --- | ---: | ---: | ---: | ---: |
| h12_t400_c75_f0.1 | 10 | 14 | 70 | 142 |
| h12_t400_c75_f0.15 | 10 | 14 | 66 | 124 |
| h12_t500_c75_f0.1 | 10 | 14 | 66 | 138 |
| h12_t500_c75_f0.15 | 10 | 14 | 62 | 120 |
| h12_t400_c100_f0.1 | 9 | 14 | 64 | 130 |

Low retained-A settings:

| threshold | disruptive consensus-A | disruptive any-A | A/A | single-A |
| --- | ---: | ---: | ---: | ---: |
| h14_t400_c125_f0.2 | 0 | 6 | 0 | 58 |
| h14_t500_c125_f0.2 | 0 | 6 | 0 | 54 |
| h14_t600_c75_f0.2 | 0 | 6 | 0 | 42 |
| h14_t600_c100_f0.2 | 0 | 6 | 0 | 42 |
| h14_t600_c125_f0.2 | 0 | 6 | 0 | 41 |

## Use in production batching

- Use this report to decide which mutant/control A calls are threshold-sensitive and need redocking or pose inspection.
- Do not promote exact/near known-positive mutant rows; they are leakage and robustness controls.
- If a new candidate resembles the retained-A disruptive controls, require stricter manual pose review before prioritization.
- Re-run after any scoring, CDR-range, consensus, or HADDOCK restraint change.
