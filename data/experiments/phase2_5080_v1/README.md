# Phase 2 RTX 5080 Training Workspace

This folder is reserved for the upgraded structure+sequence VHH-antigen model.

See documentation in:

```text
docs/phase2_5080_training/
```

## Subdirectories

| Directory | Purpose |
| --- | --- |
| `configs/` | Training configs |
| `data_splits/` | Split manifests |
| `prepared/` | Preprocessed training caches |
| `negative_sets/` | Negative sample sets and audits |
| `checkpoints/` | Model weights |
| `runs/` | Run-specific logs and checkpoints |
| `reports/` | Evaluation reports |
| `logs/` | Generic logs |
| `predictions/` | Model predictions |
| `audits/` | Validation/audit reports |
| `assays/` | Blinded prospective assay packages and result-intake state |
| `src/` | Phase 2 training code |

Do not overwrite MVP outputs under `model_data/`, `models/phase1_sequence_baseline/`, or `reports/`.

## Current Completed Runs

| Run | Status | Key output |
| --- | --- | --- |
| V1 | Completed | `reports/phase2_v1_eval.md` |
| V2 | Completed | `reports/phase2_v2_eval.md` |
| V2.1 Expanded800 | Completed / PASS | `audits/PHASE2_V2_1_FINAL_VALIDATION.md` |
| V2.2 Full2277 | Completed / PASS | `audits/PHASE2_V2_2_FULL2277_FINAL_VALIDATION.md` |
| V2.3 Strict multi-seed | Completed / PASS with pair-ranking limitation | `reports/PHASE2_V2_3_STRICT_EVALUATION_V1.md` |
| V2.4 Listwise multi-seed + candidate poses | Completed / PASS with pair-ranking limitation | `audits/PHASE2_V2_4_FINAL_AUDIT_V1.md` |
| V2.5 Evidence-first generic transfer + target gate | Completed / target data not ready; generic ranking limited | `audits/PHASE2_V2_5_FINAL_AUDIT_V1.md` |

V2.2 remains the reference deliverable for the earlier full real-contact split:

- Contact dataset: `prepared/structure_contact_maps_v2_full2277.jsonl`
- Checkpoint: `checkpoints/phase2_v2_2_full2277_best_checkpoint.pt`
- Metrics: `runs/phase2_v2_2_full2277_20260709_seed41/test_metrics.json`
- PVRIG re-score: `predictions/pvrig_top_candidates_phase2_v2_2_full2277.csv`
- Re-runnable validation: `src/validate_phase2_v2_2_training.py`

V2.2 remains computational evidence only; it does not prove experimental binding or blocking.

## V2.5 Evidence-First Deliverable

V2.5 starts from the supervision and evidence contract rather than model size.
Its canonical target remains `VHH sequence + receptor/antigen context ->
paratope/epitope/contact evidence + ranking score`, but target-specific PVRIG
training is gated on assay-backed labels. The completed target decision is
`DATA_NOT_READY_FOR_TARGET_MODEL`: all 11 measured PVRIG E5 rows are retained
as calibration/leakage controls, leaving zero target-model-eligible assay rows,
zero verified negatives, zero eligible ranking groups, and zero sealed PVRIG
formal groups.

### Evidence, Splits, And Formal Chronology

- Canonical registry: `data_splits/evidence_registry_v2_5.csv` with 10,324
  rows (`E0=36`, `E1=6,385`, `E2=3,614`, `E3=97`, `E4=181`, `E5=11`).
- External-use contract: `data_splits/external_dataset_usage_manifest_v2_5.csv`;
  NanoBind is `REVIEWED_LOCAL_USE` and redistribution remains prohibited.
- Authoritative generic split: 123 train / 29 dev / 29 blinded formal rows;
  supported leakage-key overlaps are zero. See
  `audits/phase2_v2_5_split_seal_audit_v1.json`.
- Target readiness: `audits/phase2_v2_5_readiness_audit_v1.json`; target
  training remained unscheduled.
- Authoritative run:
  `runs/phase2_v2_5_generic/phase2_v2_5_generic_20260711T042831_045756Z`.
- Formal labels were opened exactly once. The run records
  `UNSEALED_EXPLICIT_ONE_SHOT_COMPLETE`, `formal_run_count=1`, and requires a
  new version for any method change or rerun.

An independent post-unseal review found that the generic evaluator joined
sealed labels by `sample_id` without requiring explicit sequence hashes inside
the label file. The actual V2.5 run remains usable because
`audits/phase2_v2_5_formal_label_binding_audit_v1.json` independently rebuilt
all 29 labels from the raw NanoBind affinity table and verified deterministic
pair-derived IDs, P1 pair/split assignments, and exact Kd/`-log10(Kd)` values.
V2.6 must include sequence/target hashes or a row-identity digest in every
sealed label row before unseal.

### Generic Formal Result

The frozen ESM2 pooled features plus 64-hidden-unit shallow ordinal head used
seeds 43, 53, and 67. The dev-selected strongest eligible baseline was frozen
cosine distance. Canonical formal primary values are:

| Seed | Shallow head | Frozen cosine | Delta | Paired 95% bootstrap CI |
| --- | ---: | ---: | ---: | --- |
| 43 | 0.509524 | 0.419048 | +0.090476 | [-0.109524, 0.285714] |
| 53 | 0.552381 | 0.419048 | +0.133333 | [-0.057143, 0.304762] |
| 67 | 0.604762 | 0.419048 | +0.185714 | [0.023810, 0.328571] |

The mean seed/group delta is `+0.136508`, but its 5,000-resample paired 95% CI
is `[-0.017460, 0.290476]`; the 5,000-draw group-local two-sided permutation
test gives `p=0.301940`. All three seed deltas are positive, yet the CI and
permutation gates fail. The frozen result is therefore
`PASS_LIMITED_RANKING_ONLY`, not `PASS_GENERIC_TRANSFER_ONLY`. See
`reports/PHASE2_V2_5_STRICT_EVALUATION_V1.md`,
`reports/phase2_v2_5_metrics_v1.json`, and
`reports/phase2_v2_5_gap_matrix_v1.csv`.

Primary pairwise metrics exactly match the one-shot evaluator. Secondary NDCG
uses different gain transforms in the one-shot and canonical modules and is
retained only as an explicit warning, not formal-decision evidence.
As a locked post-hoc diagnostic, leakage-safe sequence-identity nearest
neighbor reaches `0.564286` and exceeds shallow seeds 43 and 53; it cannot
replace the development-selected comparator after unseal, but it further
supports the limited-result interpretation.

### GPU, Node1, And Prospective Data

- GPU use is confirmed for ESM2 preparation, all three training seeds, and all
  three formal inference passes on the local RTX 5080. External sampling saw
  5,477 MiB peak memory during ESM2 preparation and 3,147 MiB during shallow
  training. The head itself allocated only about 67.6 MiB because embeddings
  were frozen; low one-second sampled utilization is expected. See
  `audits/PHASE2_V2_5_GPU_TELEMETRY_SUMMARY_V1.md`.
- Node1 GPU 4 produced 8/8 sequence-exact, geometry-QC-passed NanoBodyBuilder2
  monomers under `/mnt/d/work/抗体/docking/candidates/v2_5_pose_batch/`.
  Candidate-specific exact complex coverage remains 2/50 (4%). HADDOCK3 was
  correctly refused at `load1=106.98` against the fixed threshold 64, so no
  high-load docking was forced and global pose fusion remains disabled. See
  `audits/phase2_v2_5_pose_coverage_audit.json`.
- The next evidence-producing artifact is the 24-pair prospective panel in
  `data_splits/pvrig_v2_5_prospective_assay_panel.csv` and
  `reports/PHASE2_V2_5_PROSPECTIVE_ASSAY_PANEL.md`. Its candidate negatives are
  still `UNMEASURED_NOT_VERIFIED` until assays are run.

The final machine audit passes all 27 required checks with no failures or
warnings. Engineering completion does not change the scientific stop: V2.6
should first obtain prospective PVRIG affinity/competition measurements, then
freeze a new hash-bound formal schema before considering a larger model.

## Model-To-Cascade Screening Funnel

The production responsibility split is now fixed:

1. The Phase 2 model cheaply ranks a large input library.
2. `vhh-large-scale-screen` performs strict sequence QC, CDR novelty,
   developability review, bounded exact diversity, and shortlist ranking.
3. 8X6B plus 9E6Y structure/HADDOCK3 evidence supports computational geometry
   classification.
4. Prospective expression, binding, competition, and functional assays supply
   the only new biological truth.

`src/prepare_pvrig_model_screening_summary.py` converts the V2.4 multi-seed
score into the cascade field `binder_score`. This is a within-input rank
percentile, not a binding or blocker probability. The first blinded integration
run completed in 132 seconds: 24 inputs -> 4 fast/full survivors -> 4 geometry
candidates. Guarded local HADDOCK3 failover completed the three missing runs,
and the final dual-baseline import now contains all four candidates: two
`FINAL_POSITIVE_HIGH`, one `FINAL_RECHECK_SINGLE_BASELINE`, and one
`FINAL_POSITIVE_PLAUSIBLE`.

The high label is a docking/overlay geometry priority only. It is not measured
binding, blocking, or functional evidence and is not an ordinary training
label.

The geometry import is fail-closed: stale single-baseline/recheck classes cannot
collapse to A, every complete row is bound to the manifest by reconstructing
chain A from the actual VHH input PDB, and the finalize export requires a RUN
record with two baselines and all four geometry metrics.

Node1 remained above the unchanged `load1 < 64` gate, so no high-load remote
HADDOCK3 process was forced. An isolated local 2025.11.0 runtime instead passed
CNS and full-module smoke tests; a dual-lock, freeze/recheck, nonce-bound handoff
stopped the waiter only after proving all three remote runs absent. The three
production runs then completed sequentially in 96, 94, and 93 seconds.

The frozen 24-sample assay panel is not pruned by cascade outcomes. Sequence
rejects, capacity deferrals, missing docking, and computational binder/blocker
classes are not experimental negatives or positives.

See `docs/phase2_5080_training/PVRIG_MODEL_TO_CASCADE_SCREENING_FUNNEL.md` and
`audits/PVRIG_V2_5_SCREENING_FUNNEL_AUDIT_20260711.md`.

## V2.5 Prospective Assay Execution Package

The frozen 24-pair panel now has a deterministic execution and result-intake
package under `assays/pvrig_v2_5_prospective_v1/`. It contains 24 blinded
sample IDs, three independently randomized day blocks, 72 sample-run slots,
construct and FASTA manifests, and separate templates for expression/SEC QC,
binding, competition, and functional measurements. It contains no experimental
results; all 24 rows currently remain `PENDING_EXPRESSION_QC` and the E6 review
candidate table is empty.

Build and validate the initial package with:

```bash
experiments/phase2_5080_v1/.venv-phase2-5080/bin/python \
  experiments/phase2_5080_v1/src/build_pvrig_v2_5_assay_execution_package.py

experiments/phase2_5080_v1/.venv-phase2-5080/bin/python \
  experiments/phase2_5080_v1/src/analyze_pvrig_v2_5_assay_results.py
```

Before the first physical measurement, the lab coordinator must fill every
null value under `lab_parameters_to_freeze_before_first_measurement` in
`assays/pvrig_v2_5_prospective_v1/assay_preregistration.json`, then freeze it:

```bash
experiments/phase2_5080_v1/.venv-phase2-5080/bin/python \
  experiments/phase2_5080_v1/src/freeze_pvrig_v2_5_assay_preregistration.py
```

The freeze command refuses incomplete parameters and refuses a late freeze
after any result call is entered. The analyzer requires raw-data paths and
SHA256 values for completed calls, enforces sequence/target identity and the
three-run/two-day contract, excludes expression or assay failures rather than
calling them nonbinders, and never promotes binding alone to blocking. Entered
functional `INCONCLUSIVE` calls are also treated as completed measurements for
analyte, viability, and independent raw-evidence validation. Any
derived E6 row remains `PROSPECTIVE_E6_REVIEW_ONLY`; a new V2.6 split, seal,
readiness audit, and formal protocol are still required before model use.

See `docs/phase2_5080_training/PVRIG_V2_5_ASSAY_EXECUTION_HANDOFF.md` for the
operator handoff and field-level workflow.

## V2.4 Listwise And Candidate-Pose Deliverable

V2.4 keeps the validated V2.3 contact/site backbone and replaces independent
triplet updates with complete-group listwise ranking plus type-aware margins.
Its constructed N1/N2/N3 candidates remain ranking proxies, never verified
non-binders. The 11 PVRIG positives and 36 mutant/reference controls remain
isolated from ordinary train/test/candidate lanes.

### Frozen Inputs And Formal Runs

- Ranking groups: 1,230 groups / 4,844 rows, with one observed cognate anchor
  and up to three typed constructed contrasts per group.
- Controls: 47 isolated PVRIG rows; zero exact sequence-hash overlap with the
  ranking manifest.
- Preregistration: `audits/PHASE2_V2_4_PREREGISTRATION_V1.md`
- Config: `configs/phase2_v2_4_listwise_5080_16gb.json`
- Runs: `runs/phase2_v2_4_strict_listwise_20260711_seed{43,53,67}`
- Portable checkpoints: `checkpoints/phase2_v2_4_strict_seed{43,53,67}_best_checkpoint.pt`
- Canonical checkpoint: `checkpoints/phase2_v2_4_best_checkpoint.pt` (seed 53,
  selected by the preregistered validation composite)
- Runtime staging equivalence: `audits/V2_4_RUNTIME_STAGING_EQUIVALENCE_V1.md`
- GPU evidence: `audits/PHASE2_V2_4_GPU_TELEMETRY_SUMMARY_V1.md`

Strict three-seed test means:

| Metric | V2.3 | V2.4 | Interpretation |
| --- | ---: | ---: | --- |
| Contact AUPRC | 0.5197 | 0.5323 | Guardrail passed; modest increase |
| Paratope AUPRC | 0.6306 | 0.6418 | Guardrail passed; modest increase |
| Epitope AUPRC | 0.1598 | 0.1611 | Essentially unchanged and still weak |
| Ranking MRR | 0.5249 | 0.5192 | Below random expectation 0.5330 |
| Hit@1 | 0.2038 | 0.2019 | No improvement |
| Hard-negative win | 0.5454 | 0.5443 | No improvement |
| Pair contrastive-proxy AUROC | 0.5289 | 0.5301 | Proxy-only and essentially unchanged |

The formal interpretation is
`PASS_WITH_PAIR_RANKING_LIMITATION`: V2.4 is an engineering-complete,
reproducible pipeline, but it did not solve target-conditioned pair ranking and
is not a validated PVRIG binder/blocker classifier. See
`reports/PHASE2_V2_4_STRICT_EVALUATION_V1.md` and
`audits/PHASE2_V2_4_FORMAL_DECISION_V1.md`.

### Candidate And Pose Outputs

- Seed rankings: `predictions/pvrig_candidate_ranking_ai_prior_v2_4_seed{43,53,67}.csv`
- Multi-seed ensemble: `predictions/pvrig_candidate_ranking_ai_prior_v2_4_multiseed_ensemble.csv`
- Candidate pose index: `data_splits/phase2_v2_4_candidate_pose_index.csv`
- Coverage-gated P3 output: `predictions/pvrig_candidate_ranking_v2_4_p3_pose_fusion.csv`
- Pose assets: `/mnt/d/work/抗体/docking/candidates/v2_4_top2/`

Two candidates have exact candidate-specific NBB2/HADDOCK3 assets: 10 top
poses for `zym_test_9743` and 6 for `zym_test_108006`. All VHH chain A and
PVRIG chain B sequence checks pass. Because this is only 2/50 (4%) coverage,
global geometry boosting is disabled below the fixed 80% gate; the global order
remains the sequence ensemble order. Geometry ranks only the pose-supported
subset (`zym_test_9743` before `zym_test_108006`) and remains computational
pose evidence, not experimental binding/blocking evidence.

### V2.4 Inference

```bash
experiments/phase2_5080_v1/.venv-phase2-5080/bin/python \
  experiments/phase2_5080_v1/src/score_pvrig_candidates_v2_4.py \
  --checkpoint experiments/phase2_5080_v1/checkpoints/phase2_v2_4_best_checkpoint.pt \
  --candidates experiments/phase2_5080_v1/predictions/pvrig_candidate_ranking_ai_prior_v2_3_multiseed_ensemble.csv \
  --output experiments/phase2_5080_v1/predictions/pvrig_candidate_ranking_ai_prior_v2_4.csv
```

Portable-vs-run checkpoint inference is exactly equivalent for all three seeds
and all 50 candidates; see `audits/phase2_v2_4_portable_inference_equivalence_v1.json`. Brier/ECE
remain `NOT_APPLICABLE` because no verified positive-and-negative probability
calibration set exists.

## V2.3 Strict Deliverable

V2.3 combines the useful parts of the locally reproduced projects without
pretending their outputs are interchangeable labels:

- Frozen local ESM2-8M residue embeddings provide sequence priors.
- Exact/heuristic CDR type masks provide VHH region context; unresolved CDR3
  rows are excluded from pair/ranking tasks and counted explicitly.
- Contact, paratope, and epitope heads retain structure/site supervision.
- Pairwise ranking uses constructed contrasts only; these rows are not called
  verified non-binders.
- NanoBind and DeepNano outputs are external ranking priors, not blocker
  probabilities.
- P3 accepts real pose geometry when available and otherwise remains explicitly
  `AI_PRIOR_ONLY`.

### Strict Data And Cache

- Global split validation: `audits/CLUSTERED_SPLIT_VALIDATION_V2.md`
- Frozen ESM2 cache: 4,935 tensors in 21 shards, exhaustively validated by
  `audits/ESM2_CACHE_VALIDATION_V2_3.md`
- CDR masks: `data_splits/vhh_cdr_type_masks_v2_3.csv`
- Contact records: 5,890 / 1,262 / 1,262 train/val/test
- Pair rows after unresolved-CDR exclusion: 3,262 / 712 / 686
- Ranking triplets after unresolved-CDR exclusion: 2,402 / 527 / 502

### Formal Runs

The fixed baseline configuration was trained with seeds 43, 53, and 67 on an
RTX 5080. Runtime staging used byte-identical copies on the Linux filesystem to
avoid WSL `/mnt/d` I/O stalls; durable paths are restored in the portable
checkpoints.

- Config: `configs/phase2_v2_3_5080_16gb.json`
- Runs: `runs/phase2_v2_3_strict_hardened_20260710_seed{43,53,67}`
- Portable checkpoints: `checkpoints/phase2_v2_3_strict_seed{43,53,67}_best_checkpoint.pt`
- Canonical checkpoint: `checkpoints/phase2_v2_3_best_checkpoint.pt`
- GPU evidence: `audits/PHASE2_V2_3_GPU_TELEMETRY_SUMMARY_V1.md`
- Multi-seed report: `audits/PHASE2_V2_3_MULTISEED_SUMMARY_V1.md`
- Final P0-P4 audit: `audits/PHASE2_V2_3_P0_P4_FINAL_AUDIT_V1.md`

Strict test means across the three seeds:

| Metric | Mean | Interpretation |
| --- | ---: | --- |
| Contact AUROC / AUPRC | 0.8287 / 0.5197 | Clearly above contact prevalence 0.1995 |
| Paratope AUPRC | 0.6306 | Clearly above prevalence 0.1686 |
| Epitope AUPRC | 0.1598 | Above prevalence 0.0831, but still weak |
| Ranking MRR | 0.5249 | Below exact random-order expectation 0.5330 |
| Hard-negative win rate | 0.5454 | Modest pairwise signal only |
| Pair contrastive-proxy AUROC | 0.5289 | Constructed-proxy metric, not binding AUROC |

The durable conclusion is therefore narrower than “V2.3 solved binding”: the
strict contact/site learner works, while target-conditioned pair ranking remains
the main modeling bottleneck. A single validation-only rank-focused branch was
rejected because it did not improve validation MRR; see
`audits/PHASE2_V2_3_TUNING_DECISION_V1.md`.

### Candidate And P3 Outputs

- Seed predictions: `predictions/pvrig_candidate_ranking_ai_prior_v2_3_seed{43,53,67}.csv`
- Multi-seed ensemble: `predictions/pvrig_candidate_ranking_ai_prior_v2_3_multiseed_ensemble.csv`
- P3 fused ranking: `predictions/p3_late_fusion_rankings_v1.csv`
- Pose inventory: `audits/P3_TOP50_POSE_INVENTORY_V1.md`
- P3 validation: `audits/p3_late_fusion_validation_v1.json`

The exact local pose inventory found 0/50 current candidate-specific poses after
checking candidate IDs, exact sequences, and 1,680 PDB files. Consequently all
50 P3 rows are `AI_PRIOR_ONLY`; no geometry feature is fabricated.

### Inference

```bash
experiments/phase2_5080_v1/.venv-phase2-5080/bin/python \
  experiments/phase2_5080_v1/src/score_pvrig_candidates_v2_3.py \
  --checkpoint experiments/phase2_5080_v1/checkpoints/phase2_v2_3_best_checkpoint.pt \
  --output experiments/phase2_5080_v1/predictions/pvrig_candidate_ranking_ai_prior_v2_3.csv
```

The sigmoid and combined columns are within-pool ranking AI priors. They are not
calibrated binding/blocker probabilities, Kd estimates, IC50 estimates, or
experimental efficacy claims. Brier/ECE is currently `NOT_APPLICABLE` because
there is no legitimate verified positive-and-negative probability calibration
set; known blockers and mutants remain calibration/leakage controls only.
