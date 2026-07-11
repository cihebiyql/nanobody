# Phase 2 V2.4 Strict Evaluation V1

- Status: **PASS_WITH_PAIR_RANKING_LIMITATION**
- Formal seeds: `43, 53, 67`; fixed preregistered configuration; test metrics were not used for model selection.
- Scientific boundary: ranking AI prior and computational pose evidence only; not a calibrated binder/blocker classifier.
- Calibration: `NOT_APPLICABLE` (no verified positive-and-negative probability labels).

## V2.3 comparison

| metric | V2.3 mean | V2.4 mean | delta | interpretation |
| --- | ---: | ---: | ---: | --- |
| contact_auprc | 0.519729 | 0.532292 | +0.012563 | guardrail passed |
| paratope_auprc | 0.630628 | 0.641821 | +0.011193 | guardrail passed |
| epitope_auprc | 0.159777 | 0.161124 | +0.001347 | small increase, still weak |
| ranking_mrr | 0.524921 | 0.519206 | -0.005715 | below V2.3 and random 0.532976 |
| ranking_hit_at_1 | 0.203810 | 0.201905 | -0.001905 | no improvement |
| ranking_hard_negative_win_rate | 0.545362 | 0.544343 | -0.001019 | no improvement |
| pair_contrastive_proxy_auroc | 0.528935 | 0.530120 | +0.001185 | proxy-only, essentially unchanged |

## Per-seed formal test metrics

| seed | best val epoch | contact AUPRC | paratope AUPRC | epitope AUPRC | MRR | random MRR | Hit@1 | hard-neg win |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 43 | 3 | 0.520764 | 0.627610 | 0.153521 | 0.526190 | 0.532976 | 0.217143 | 0.559633 |
| 53 | 2 | 0.535845 | 0.645717 | 0.169661 | 0.521429 | 0.532976 | 0.211429 | 0.541284 |
| 67 | 4 | 0.540267 | 0.652134 | 0.160190 | 0.510000 | 0.532976 | 0.177143 | 0.532110 |

## Candidate stability

- 50-candidate rank standard deviation improved from V2.3 mean/median `8.28 / 7.91` to V2.4 `7.71 / 6.83`.
- All-three-seed top-10 intersection: `3` candidates (zym_test_21966, zym_test_359954, zym_test_5495); V2.3 had `2`.
- Stability improved modestly, but the strict held-out ranking metrics did not improve.

## Candidate-specific pose integration

- Exact candidate-specific pose coverage is `2/50` (4%): 16 HADDOCK3 top poses across two candidates; all VHH chain A and PVRIG chain B identity checks passed.
- Global geometry boosting is disabled below 80% coverage to prevent pose-availability bias; the 50-candidate global order remains the sequence ensemble order.
- Within the pose-supported two-candidate subset:
  - pose rank 1: `zym_test_9743` (global sequence rank 9, geometry proxy 0.925).
  - pose rank 2: `zym_test_108006` (global sequence rank 6, geometry proxy 0.075).

## Decision

- V2.4 is engineering-complete: strict manifests, three CUDA runs, multi-seed inference, portable checkpoints, exact inference equivalence, candidate pose identity QC, coverage-gated P3 fusion, and final audit are available.
- V2.4 does **not** meet the preregistered ranking targets (MRR 0.56, Hit@1 0.25, hard-negative win 0.60).
- Do not describe V2.4 outputs as binding probabilities, non-binder labels, or PVRIG-blocking validation.
- A future V2.5 should add verified target-family ranking evidence or experimentally labelled negatives; another post-hoc pseudo-negative weight sweep is not justified by this test set.
