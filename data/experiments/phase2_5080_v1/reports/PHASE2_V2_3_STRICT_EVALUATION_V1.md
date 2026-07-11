# Phase 2 V2.3 Strict Evaluation V1

- Status: **COMPLETED_WITH_PAIR_RANKING_LIMITATION**
- Seeds: 43, 53, 67
- Split: strict global clustered split with zero cross-split exact/cluster/PDB overlap

## Strict Multi-Seed Metrics

| metric | mean | std | baseline | delta |
| --- | ---: | ---: | ---: | ---: |
| contact_auroc | 0.828669 | 0.003501 | n/a | n/a |
| contact_auprc | 0.519729 | 0.011592 | 0.199490 | +0.320240 |
| paratope_auprc | 0.630628 | 0.014477 | 0.168584 | +0.462044 |
| epitope_auprc | 0.159777 | 0.011909 | 0.083091 | +0.076687 |
| ranking_mrr | 0.524921 | 0.006500 | 0.532976 | -0.008056 |
| ranking_hit_at_1 | 0.203810 | 0.003299 | 0.261429 | -0.057619 |
| ranking_hard_negative_win_rate | 0.545362 | 0.032122 | 0.500000 | +0.045362 |
| pair_contrastive_proxy_auroc | 0.528935 | 0.009891 | 0.500000 | +0.028935 |
| pair_contrastive_proxy_auprc | 0.269941 | 0.004956 | 0.255102 | +0.014839 |

## Interpretation

- Contact AUPRC is 0.5197 versus prevalence 0.1995; paratope and epitope AUPRC are also above their prevalence baselines.
- Ranking MRR is 0.5249 versus the exact retained-group random expectation 0.5330; Hit@1 is 0.2038 versus random 0.2614.
- Hard-negative win rate is 0.5454; pair contrastive-proxy AUROC is 0.5289. These are modest signals, not a validated binder classifier.
- Constructed contrasts are unlabeled ranking proxies and are never reported as verified non-binders.

## Candidate Stability

- Mean/median per-candidate rank standard deviation: 8.28 / 7.91.
- Candidates shared by all three seed top-10 lists: 2 (zym_test_108006, zym_test_9743).
- Seeds 43/53: rank correlation 0.696, top-10 overlap 4/10.
- Seeds 43/67: rank correlation 0.442, top-10 overlap 3/10.
- Seeds 53/67: rank correlation 0.585, top-10 overlap 5/10.

## P3 And Calibration

- Exact real-pose coverage is 0/50 after exact ID, exact sequence, and 1,680-PDB inventory checks.
- All 50 P3 rows are `AI_PRIOR_ONLY`; no pose geometry score was fabricated.
- Calibration is `NOT_APPLICABLE`: 11 known positives and 36 mutant/leakage controls remain held out, but no legitimate verified negative probability set exists for Brier/ECE.

## V2.2 Boundary

V2.2 reference metrics were contact AUPRC 0.7242, paratope AUPRC 0.6477, epitope AUPRC 0.2272, and pair AUROC 0.5833. They are not directly comparable because V2.3 uses stricter global clustered splits and different pair-label semantics.

All scores are computational candidate-ranking evidence, not experimental binding, Kd, IC50, or blocker efficacy.
