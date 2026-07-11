# Phase 2 V2.5 Strict Evaluation V1

- Final target status: **DATA_NOT_READY_FOR_TARGET_MODEL**
- Generic formal status: **PASS_LIMITED_RANKING_ONLY**
- Formal run count: `1`; reruns or method changes require V2.6.
- Label-binding audit: **PASS**; the evaluator schema gap remains a V2.6 requirement.

## Generic Formal Result

The frozen shallow head improved the dev-selected `frozen_cosine_distance` baseline by `0.136508` on average across the three frozen seeds and seven ranking groups. The paired 95% bootstrap CI was `[-0.017460, 0.290476]`, and the group-local two-sided permutation p-value was `0.301940`. The CI crosses zero and p is not below 0.05, so the strict generic-transfer gate does not pass.

| Seed | Model primary | Baseline primary | Delta | 95% bootstrap CI | GPU |
| --- | ---: | ---: | ---: | --- | --- |
| 43 | 0.509524 | 0.419048 | +0.090476 | [-0.109524, 0.285714] | NVIDIA GeForce RTX 5080 |
| 53 | 0.552381 | 0.419048 | +0.133333 | [-0.057143, 0.304762] | NVIDIA GeForce RTX 5080 |
| 67 | 0.604762 | 0.419048 | +0.185714 | [0.023810, 0.328571] | NVIDIA GeForce RTX 5080 |

All three seed deltas are positive, but seed consistency alone cannot override the failed CI and permutation gates. The canonical primary exactly matches the one-shot evaluator. Secondary NDCG differs because the two implementations use different gain transforms; it is retained as a warning and is not used for the decision.

As a locked post-hoc diagnostic, leakage-safe sequence-identity nearest neighbor scores `0.564286` on the formal primary and exceeds shallow seeds 43 and 53. It cannot replace the development-selected comparator after unseal, but it reinforces the limited-result interpretation.

## Formal Integrity

The post-unseal audit independently rebuilt NanoBind affinities from the raw source, verified `29` deterministic pair-derived sample IDs, matched the P1 formal pair/split assignments, and reproduced every sealed label. This proves the actual V2.5 label mapping despite the evaluator's generic schema weakness. Future sealed labels must carry explicit sequence/target hashes or a row-identity digest before unseal.

## PVRIG Boundary

PVRIG remains data-not-ready: there are no verified target negatives, no new sealed target formal groups, and no powered target-specific formal block. Generic affinity transfer cannot be promoted to blocker truth or target success. The 24-pair prospective assay panel is the next evidence-producing step.

## Structure Lane

Node1 produced `8` new sequence/geometry-QC-passed NanoBodyBuilder2 monomers. Exact QC-passed complex coverage remains `4.0%`; HADDOCK3 was load-gated and global pose fusion remains disabled.

## Decision

V2.5 is engineering-complete with a negative strict generic-formal result and a target data-readiness stop. The observed positive point estimate is exploratory only. Any model, metric, join-schema, or threshold revision belongs to V2.6; the next scientifically useful action is prospective assay measurement, not a larger model.
