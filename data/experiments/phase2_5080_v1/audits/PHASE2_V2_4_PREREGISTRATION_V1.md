# Phase 2 V2.4 formal-run preregistration

- Status: **FROZEN_BEFORE_FORMAL_RUNS**
- Registered (UTC): `2026-07-10T16:44:10.483540+00:00`
- Config: `experiments/phase2_5080_v1/configs/phase2_v2_4_listwise_5080_16gb.json` (`51bb9269f1ce6cc94ab96a6bd59638b96ee20cbbb8f237cf2b0e6664063c4d65`)
- Seeds: `43, 53, 67`; each warm-starts the matching strict V2.3 seed checkpoint.
- Epochs: `4`; LR: `0.0001`; rank batch: `12`.
- Checkpoint selection uses validation metrics only. Formal test metrics cannot change this registered configuration.

## Primary decision metrics

- Mean ranking MRR must exceed both V2.3 `0.524921` and random `0.532976`; preferred target `>= 0.56`.
- Mean Hit@1 preferred target `>= 0.25`.
- Mean hard-negative win preferred target `>= 0.60`.
- Contact AUPRC guardrail `>= 0.489729`; paratope AUPRC guardrail `>= 0.600628`.

## Frozen scientific boundary

- N1/N2/N3 constructed rows are ranking proxies, not verified non-binders.
- The 11 PVRIG positives and 36 mutant/reference controls remain outside ordinary train/test/candidate lanes.
- Candidate-specific NBB2/HADDOCK3 structures are computational pose evidence only.
- Brier/ECE remain `NOT_APPLICABLE` without verified positive-and-negative probability labels.
- If preferred ranking thresholds fail, V2.4 may be engineering-complete only with an explicit pair/ranking limitation; it is not a validated binder or blocker classifier.

## Runtime smoke evidence

The single-epoch seed-43 smoke was used only to validate execution. It reached RTX 5080 CUDA training with peak `6076` MiB and peak utilization `60%`. Its validation MRR `0.518981` was below random expectation and was not used to alter this configuration.
