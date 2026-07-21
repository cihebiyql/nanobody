# V2.10 Stage0 development evaluator / selector audit V1

## Verdict

The existing variable-size V2.9 runner is directly compatible with the
V2.10 canonical teacher contract.  It already enforces open-only input,
whole-parent train/development isolation, zero frozen/sealed truth access,
R8/R9 direct prediction, and exact-min Rdual derivation.

Reusable implementation:

```text
v2_9_expanded_training_v1_20260720/src/
run_sequence_stage0_expanded_v2_9.py
```

Do **not** use the older V2.7 trainer directly: it hard-codes 1,085/184 rows,
an `outer_0_inner_0` split ID, and 1,507-row embedding receipts.

## Existing metric semantics

V2.9 already calculates, per seed and model:

- R8/R9/Rdual exact-min Spearman, MAE and RMSE;
- true top 10% and 20% crossed with prediction budgets 5%, 10% and 20%;
- recall, precision, enrichment factor and binary NDCG at each crossing;
- within-parent top-20% macro recall and macro EF.

For V2.10 development `N=795`:

```text
true/predicted top 10% = ceil(79.5)  = 80 candidates
true/predicted top 20% = ceil(159.0) = 159 candidates
```

The requested headline metrics map to:

```text
Recall@前20% = true_top_fraction=0.20, predicted_budget_fraction=0.20
EF@10%       = true_top_fraction=0.10, predicted_budget_fraction=0.10
NDCG@10%     = binary_ndcg on the same 0.10 / 0.10 row
Spearman     = Rdual_exact_min.spearman over all 795 development rows
```

Because the development parents are imbalanced (9--105 rows per parent), the
within-parent macro top-20 recall must be reported next to the global recall.
The smallest parent has only 9 rows, so its per-parent result is diagnostic,
not a standalone decision.

## Gaps fixed by the independent evaluator

The V2.9 top-level `MULTISEED_SUMMARY.json` retains only Spearman.  Early
enrichment remains nested inside each seed `RESULT.json`, and there is no
cross-seed prediction ensemble evaluation.  The old tie-break also depends on
input row order.

The versioned evaluator in `evaluation/` therefore:

1. derives the 795 development IDs only from the open teacher and score-parent
   metadata;
2. rejects any missing, extra, train or frozen candidate prediction;
3. ignores prediction-file truth as the authority and checks any compatibility
   truth columns against the canonical development teacher;
4. recomputes Rdual as `min(pred_R8, pred_R9)`;
5. evaluates every seed/model plus mean-R8/R9-across-seeds ensembles;
6. uses candidate ID as the deterministic score-tie break;
7. emits Recall@20%, EF@10%, deterministic binary NDCG@10%, Spearman and parent-macro recall;
8. selects a development model lexicographically by frozen criteria:
   global Recall@20%, parent-macro Recall@20%, binary NDCG@10%, Spearman.

This selection is open-development model selection, not formal test evidence.

## Executable command after Stage0 finishes

```bash
set -euo pipefail

V210=experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/\
v2_10_canonical10644_training_v1_20260721
RUN=/data1/qlyu/projects/pvrig_v29_canonical_merged_teacher_v1_20260721/\
training/stage0_sequence_v2_10_3seed_v1

python3 "$V210/evaluation/evaluate_v2_10_open_development.py" \
  --teacher-tsv "$V210/prepared/primary_D1_canonical10644_teacher.tsv" \
  --expected-teacher-sha256 \
    46bc32276a574e21bb92d7e6672b18aa68323c778b4f65d2415a384144ab95c3 \
  --split-manifest \
    "$V210/prepared/primary_D1_canonical10644_split_manifest.json" \
  --prediction "43=$RUN/seed_43/OPEN_SCORE_PREDICTIONS.tsv" \
  --prediction "97=$RUN/seed_97/OPEN_SCORE_PREDICTIONS.tsv" \
  --prediction "193=$RUN/seed_193/OPEN_SCORE_PREDICTIONS.tsv" \
  --output-dir "$RUN/open_development_evaluation_v1"
```

If the production seed list differs, pass exactly the actually frozen seed
directories.  Never point this evaluator at a frozen-test prediction or truth
table; prohibited path tokens fail closed, and the candidate join must equal
the 795-row development set exactly.

## Label-free 100K selector boundary

The reusable selector is:

```text
v2_7_100k_multi_model_early_enrichment_v1_20260719/src/
select_100k_label_free_multimodel.py
```

It is appropriate only after development chooses and freezes the production
model/config.  It consumes no truth columns and supports exploitation,
single-model rescue, disagreement, diversity and random-sentinel quotas.  The
V2.10 development prediction TSV cannot be passed directly because it contains
truth columns; production 100K inference must emit a separate label-free
candidate table with only declared prediction, uncertainty, QC, provenance and
diversity fields.
