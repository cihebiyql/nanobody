# PVRIG Blocking VHH Project Progress

This is the continuously maintained progress document for the PVRIG mechanism, scaffold, and model work. Update it whenever Phase I evidence, model gates, or candidate-ranking artifacts change.

## Current Competition Objective - 2026-07-12

**Status: `PIPELINE_READY_CANDIDATE_PORTFOLIO_NOT_READY`.**

The current critical path is the 2026-07-26 18:00 first-round competition
submission, not another generic-model iteration. The project must produce 50
ranked, traceable VHH designs, with the strongest evidence concentrated in a
diverse Top10. Known positives, patent sequences, and their mutant controls
remain calibration/leakage controls and are never submission candidates.

The existing V2.4 model Top50 has now been run through the production cascade:
50/50 pass positive-CDR novelty, 29/50 pass full sequence QC, 21/50 hard-fail,
4/29 have imported docking evidence, and 2/29 receive the computational
`FINAL_POSITIVE_HIGH` label. These 50 are unmodified public ZYMScott sequences,
so this result validates the screening workflow but does not create a compliant
submission portfolio.

Authoritative competition audit and machine-readable state:

- `node1/PVRIG_COMPETITION_ASSET_AND_GOAL_AUDIT_20260712.md`
- `node1/competition_qc/pvrig_competition_asset_inventory_20260712.csv`
- `node1/competition_qc/pvrig_competition_readiness_20260712.json`
- `node1/competition_qc/pvrig_top50_audit_20260712/`

Immediate priorities are: generate a target-conditioned multi-family VHH
library with RFantibody and the clean scaffold set; obtain at least 100-300
designed hard-pass sequences; structure/dock the bounded shortlist; freeze a
50-sequence portfolio and multi-family Top10; then produce the official template,
one-page proposal, and reproducible source release. Current computational labels
remain ranking evidence, not experimental binding or blocking truth.

## Latest Phase 2 Model Update - 2026-07-11 (V2.5)

Phase 2 V2.5 is engineering-complete with final target status
`DATA_NOT_READY_FOR_TARGET_MODEL` and generic status
`PASS_LIMITED_RANKING_ONLY`. It establishes a canonical evidence registry,
license/use controls, leakage-safe generic affinity split, a one-shot formal
evaluation, a post-unseal label-binding audit, Node1 monomer-QC coverage, and a
prospective 24-pair assay panel. It deliberately does not train or claim a
PVRIG blocker model without target-eligible positive/negative or ranking data.

Final audit: `data/experiments/phase2_5080_v1/audits/PHASE2_V2_5_FINAL_AUDIT_V1.md`
(`27/27` checks passed; no failed checks or warnings).

| Stage | Status | Durable evidence | Result |
| --- | --- | --- | --- |
| P0 evidence registry | PASS | `data/experiments/phase2_5080_v1/audits/phase2_v2_5_evidence_registry_summary.json` | 10,324 canonical rows; NanoBind 185 raw rows -> 181 exact pairs; redistribution prohibited. |
| P1 split/seal/readiness | PASS / NO-GO | `data/experiments/phase2_5080_v1/audits/phase2_v2_5_split_seal_audit_v1.json`, `data/experiments/phase2_5080_v1/audits/phase2_v2_5_readiness_audit_v1.json` | Generic 123/29/29 split with zero supported leakage overlap; 11 PVRIG E5 rows are all control-only, so target-eligible assay rows/rank groups/verified negatives/formal groups are all 0. |
| Generic three-seed CUDA training | PASS | `data/experiments/phase2_5080_v1/runs/phase2_v2_5_generic/phase2_v2_5_generic_20260711T042831_045756Z`, `data/experiments/phase2_5080_v1/audits/PHASE2_V2_5_GPU_TELEMETRY_SUMMARY_V1.md` | Seeds 43/53/67 ran on RTX 5080; frozen ESM2 preparation peaked at 5,477 MiB sampled memory and shallow training at 3,147 MiB. |
| One-shot generic formal | LIMITED | `data/experiments/phase2_5080_v1/reports/PHASE2_V2_5_STRICT_EVALUATION_V1.md` | Mean delta +0.136508, paired CI [-0.017460, 0.290476], permutation p=0.301940; 3/3 positive seeds but strict CI/permutation gates fail. |
| Formal label identity | PASS with future schema requirement | `data/experiments/phase2_5080_v1/audits/phase2_v2_5_formal_label_binding_audit_v1.json` | 29/29 labels independently rebuilt from raw NanoBind and pair-bound; V2.6 must put sequence/target hashes or a row digest in sealed labels before unseal. |
| Node1 structure lane | PASS / coverage-limited | `data/experiments/phase2_5080_v1/audits/phase2_v2_5_pose_coverage_audit.json`, `docking/candidates/v2_5_pose_batch/` | 8/8 new NBB2 monomers pass sequence and geometry QC; exact complex coverage remains 2/50 (4%); HADDOCK3 load gate refused load1 106.98 > 64. |
| Model-to-cascade funnel | COMPLETE / 4 DUAL-BASELINE IMPORTS / 2 COMPUTATIONAL HIGH | `data/docs/phase2_5080_training/PVRIG_MODEL_TO_CASCADE_SCREENING_FUNNEL.md`, `data/experiments/phase2_5080_v1/audits/PVRIG_V2_5_SCREENING_FUNNEL_AUDIT_20260711.md` | Model score remains a relative front-screen priority only. The blinded run completed 24 -> 4 -> 4 in 132 seconds; a guarded local HADDOCK3 failover completed the three missing runs, and finalize now reports 2 `FINAL_POSITIVE_HIGH`, 1 `FINAL_RECHECK_SINGLE_BASELINE`, and 1 `FINAL_POSITIVE_PLAUSIBLE`. |
| Prospective assay design | PANEL FROZEN / MEASUREMENTS PENDING | `data/experiments/phase2_5080_v1/data_splits/pvrig_v2_5_prospective_assay_panel.csv` | 24 pairs across 8 groups; all proposed negatives remain unmeasured, not verified. |
| Assay execution and intake | READY FOR LAB PREREGISTRATION | `data/experiments/phase2_5080_v1/assays/pvrig_v2_5_prospective_v1/` | 24 blinded IDs, 3 randomized day blocks, 72 sample-run slots, 10 manifest artifacts, mandatory functional concentration/viability gates, raw-data SHA gates, and 0 current E6 review rows. |

Frozen generic formal primary results:

- Seed 43: shallow `0.509524`, baseline `0.419048`, delta `+0.090476`.
- Seed 53: shallow `0.552381`, baseline `0.419048`, delta `+0.133333`.
- Seed 67: shallow `0.604762`, baseline `0.419048`, delta `+0.185714`.
- Aggregate paired 95% bootstrap CI crosses zero and group-local permutation is
  not significant; the positive point estimate remains exploratory.
- Leakage-safe sequence-identity nearest neighbor scores `0.564286` as a
  formal-only diagnostic and exceeds shallow seeds 43 and 53; it was not used
  to alter the pre-unseal comparator.
- Primary pairwise metrics exactly match the one-shot evaluator. Secondary
  NDCG gain semantics differ and are not used for the formal decision.

The formal run is locked at `formal_run_count=1`; any method, metric, threshold,
or join-schema change belongs to V2.6. The highest-value next step is to measure
the 24-pair PVRIG panel and create real binder/nonblocker and nonbinder evidence.
A larger model, pseudo-negative relabeling, or global pose boost cannot replace
that missing supervision.

The prospective assay handoff is now executable rather than narrative-only.
`build_pvrig_v2_5_assay_execution_package.py` deterministically regenerates the
blinded package; `freeze_pvrig_v2_5_assay_preregistration.py` locks lab-specific
thresholds before any result is entered; and
`analyze_pvrig_v2_5_assay_results.py` validates expression/SEC, BLI/SPR,
competition, and functional result tables. The analyzer requires raw-data
SHA256 evidence, keeps binding/blocking/functional axes separate, and emits
only review-only E6 candidates with sequence and target hashes. Current state
remains physical measurements pending: 24/24 are `PENDING_EXPRESSION_QC`, with
no inferred binder, nonbinder, blocker, or functional labels.

The front-screen and post-screen responsibilities are now explicit. The Phase
2 model is used for cheap whole-library prioritization; its exported
`binder_score` is a within-input rank percentile, not a biological
probability. Node1 `vhh-large-scale-screen` then performs strict sequence QC,
positive-CDR novelty checks, full shortlist validation, bounded exact
diversity, and geometry-queue ranking. The first blinded integration run took
132 seconds for 24 inputs and selected four geometry candidates. Dual-baseline
finalize now imports all four rows with complete sequence provenance and all
four conservative geometry metrics.

For `zym_test_108006`, HADDOCK rank-1 pose `cluster_1_model_1` is
`BLOCKER_LIKE_A` against both the 8X6B and 9E6Y reference interfaces. The
candidate-level call is `CONSENSUS_BLOCKER_LIKE_A`, with conservative metrics
15 hotspot overlaps, 610 total PVRL2 occlusion pairs, 106 CDR3 occlusion pairs,
and a 0.17377 CDR3 fraction. Its blinded ID `PV25-25F7D6778F87` remains a
computational `FINAL_POSITIVE_HIGH`, but is now ranked second after completion
of all four candidates. This is not experimental binder or blocker truth.

Node1 remained near load1 120-130, so the fixed remote gate was not weakened.
Instead, an isolated local HADDOCK3 2025.11.0 runtime passed package, CNS `stop`,
and full-module candidate smoke tests. A reviewed takeover protocol acquired an
ownership lock, froze and rechecked the remote waiter, stopped it with all three
remote run directories absent, wrote a nonce-bound local-owner sentinel, and
then ran the three production configs sequentially. They completed in 96, 94,
and 93 seconds and produced 10, 9, and 8 non-empty top poses respectively.

Final dual-baseline ranking is: `PV25-0B63D218E0F3` high rank 1,
`PV25-25F7D6778F87` high rank 2, `PV25-8E96BF37FD37` single-baseline recheck
rank 3, and `PV25-EF3F71502C71` plausible rank 4. The remote and local canonical
cascade artifacts are SHA256-identical, and the immutable local snapshot is
`geometry4_complete_finalize_20260711_230812`.

The 24-sample panel remains frozen even when a candidate fails the cascade.
That disagreement is prospective evidence, not a reason to manufacture a
negative label. The next gates are lab-specific preregistration freeze and
physical expression/binding/competition/functional
measurements. Any resulting E6 rows remain review-only until a new V2.6
registry, split, seal, readiness audit, and formal protocol exist.

The Phase 2 codebase currently passes 160/160 unit tests; the geometry-4 package
passes 41/41 tests, and both existing success-case regression scripts pass.
Coverage includes functional `INCONCLUSIVE` evidence gates, strict rejection of
stale recheck labels in per-baseline inputs, VHH input-PDB sequence provenance,
complete two-baseline finalize filtering, and executable guarded-waiter failure
scenarios. The existing lightweight sync allowlist selects the new source and
test files without modifying the catch-all `.gitignore`; final follow-up review
reports 0 remaining findings and APPROVE.

## Previous Phase 2 Model Update - 2026-07-11 (V2.4)

Phase 2 V2.4 is engineering-complete with the explicit status
`PASS_WITH_PAIR_RANKING_LIMITATION`. It adds complete-group listwise ranking,
three preregistered RTX 5080 runs, portable checkpoints, multi-seed candidate
inference, two exact candidate-specific PVRIG docking packages, and
coverage-gated geometry integration. It is not a validated PVRIG binder or
blocker classifier.

Final audit: `data/experiments/phase2_5080_v1/audits/PHASE2_V2_4_FINAL_AUDIT_V1.md`
(`59` required/advisory checks, no failures; three ranking-target warnings retained).

| Stage | Status | Durable evidence | Result |
| --- | --- | --- | --- |
| V2.4 manifest/label contract | PASS | `data/experiments/phase2_5080_v1/audits/phase2_v2_4_manifest_build_v1.json` | 1,230 groups / 4,844 rows; 47 PVRIG controls isolated; zero exact sequence-hash overlap. |
| V2.4 listwise model | PASS with ranking limitation | `data/experiments/phase2_5080_v1/reports/PHASE2_V2_4_STRICT_EVALUATION_V1.md` | Contact/site guardrails pass, but strict pair ranking remains below random expectation. |
| Three-seed CUDA execution | PASS | `data/experiments/phase2_5080_v1/audits/PHASE2_V2_4_GPU_TELEMETRY_SUMMARY_V1.md` | Seeds 43/53/67; RTX 5080 peak utilization 64-69%, peak memory about 6.08 GiB. |
| Portable checkpoints | PASS | `data/experiments/phase2_5080_v1/audits/phase2_v2_4_portable_checkpoints_v1.json` | Durable paths restored; canonical seed 53; portable-vs-run inference max absolute difference 0.0. |
| Candidate-specific poses | PASS as computational evidence | `docking/candidates/v2_4_top2/RUN_REPORT.md`, `data/experiments/phase2_5080_v1/data_splits/phase2_v2_4_candidate_pose_index.csv` | 10 poses for `zym_test_9743`, 6 for `zym_test_108006`; 34/34 chain-sequence checks pass. |
| Coverage-gated P3 fusion | PASS / coverage-limited | `data/experiments/phase2_5080_v1/audits/phase2_v2_4_p3_pose_fusion.json` | Pose coverage 2/50 (4%); global geometry boosting disabled below 80% to avoid pose-availability bias. |

Strict three-seed test means and V2.3 deltas:

- Contact AUPRC: `0.5323` (`+0.0126`); paratope AUPRC: `0.6418` (`+0.0112`).
- Epitope AUPRC: `0.1611` (`+0.0013`), still weak.
- Ranking MRR: `0.5192` (`-0.0057`) versus random `0.5330`.
- Hit@1: `0.2019` (`-0.0019`); hard-negative win: `0.5443` (`-0.0010`).
- Pair contrastive-proxy AUROC: `0.5301` (`+0.0012`), still only a constructed-proxy metric.
- Candidate rank standard-deviation mean/median improved from `8.28 / 7.91`
  to `7.71 / 6.83`; all-three-seed top-10 intersection increased from 2 to 3.

Current V2.4 candidate artifacts:

- Multi-seed ensemble: `data/experiments/phase2_5080_v1/predictions/pvrig_candidate_ranking_ai_prior_v2_4_multiseed_ensemble.csv`.
- Coverage-gated P3 table: `data/experiments/phase2_5080_v1/predictions/pvrig_candidate_ranking_v2_4_p3_pose_fusion.csv`.
- Global sequence ranks remain 9 for `zym_test_9743` and 6 for
  `zym_test_108006`; within the two-candidate pose-supported subset, geometry
  ranks `zym_test_9743` first and `zym_test_108006` second.
- The pose-supported order is not comparable to unmodeled candidates and is
  not experimental binding/blocking evidence.

The V2.4 formal branch is locked against post-hoc test-guided tuning. Any method
change belongs to V2.5 with a new preregistration. The highest-value next input
is verified target-family ranking/competition evidence or legitimate negative
labels, not a larger model or another pseudo-negative weight sweep.

## Previous Phase 2 Model Update - 2026-07-10

Phase 2 V2.3 P0-P4 is implemented and verified. The deliverable is a strict,
target-conditioned VHH/antigen contact-site model plus computational candidate
ranking pipeline. It is not a validated PVRIG blocker classifier.

Final audit: `data/experiments/phase2_5080_v1/audits/PHASE2_V2_3_P0_P4_FINAL_AUDIT_V1.md` (`37/37` checks passed, with the pair-ranking limitation retained).

| Stage | Status | Durable evidence | Result |
| --- | --- | --- | --- |
| P0 strict global splits | PASS | `data/experiments/phase2_5080_v1/audits/CLUSTERED_SPLIT_VALIDATION_V2.md` | 72 checks; zero exact/cluster/PDB cross-split leakage; PVRIG controls excluded from ordinary training. |
| P1 target/external priors | PASS | `data/experiments/phase2_5080_v1/audits/PVRIG_TARGET_DOMAIN_AUDIT_V1.md`, `data/experiments/phase2_5080_v1/audits/EXTERNAL_PRIORS_FULL50_AUDIT_V1.md` | PVRIG 39-171 structural ectodomain proxy documented; NanoBind/DeepNano 250/250 model-candidate rows completed. |
| P2 V2.3 model | PASS with ranking limitation | `data/experiments/phase2_5080_v1/reports/PHASE2_V2_3_STRICT_EVALUATION_V1.md` | Frozen ESM2 + CDR-aware contact/site learner works; strict pair ranking remains near random. |
| P3 optional pose fusion | Pipeline PASS / data-gated | `data/experiments/phase2_5080_v1/audits/P3_TOP50_POSE_INVENTORY_V1.md`, `data/experiments/phase2_5080_v1/audits/p3_late_fusion_validation_v1.json` | 0/50 exact candidate poses; all 50 rows correctly remain `AI_PRIOR_ONLY`. |
| P4 multi-seed/calibration | PASS with calibration N/A | `data/experiments/phase2_5080_v1/audits/PHASE2_V2_3_MULTISEED_SUMMARY_V1.md` | Seeds 43/53/67 complete; Brier/ECE not applicable without a verified positive-and-negative probability set. |

Strict three-seed test means:

- Contact AUROC/AUPRC: `0.8287 / 0.5197` versus contact prevalence `0.1995`.
- Paratope AUPRC: `0.6306` versus prevalence `0.1686`.
- Epitope AUPRC: `0.1598` versus prevalence `0.0831`.
- Ranking MRR: `0.5249` versus exact random-order expectation `0.5330`.
- Hard-negative win rate: `0.5454`; pair contrastive-proxy AUROC: `0.5289`.

The metrics support contact/site learning, not a strong pair-level binding claim.
Constructed contrasts remain unlabeled ranking proxies and are never redefined as
verified non-binders. V2.2 numbers are retained as earlier-split references and
are not directly compared as improvements or regressions.

Current candidate artifacts:

- Multi-seed ensemble: `data/experiments/phase2_5080_v1/predictions/pvrig_candidate_ranking_ai_prior_v2_3_multiseed_ensemble.csv`.
- P3 ranking: `data/experiments/phase2_5080_v1/predictions/p3_late_fusion_rankings_v1.csv`.
- Only `zym_test_108006` and `zym_test_9743` occur in all three model seed top-10 lists; this is stability evidence, not biological validation.
- P3 ranks `zym_test_9743` first after deterministic V2.3/V2.2 plus NanoBind/DeepNano fusion; it still requires real structural and experimental follow-up.

Training used the RTX 5080 in three formal runs. Mean GPU utilization was
approximately 27-29%, P95 utilization 57-59%, peak utilization 62-65%, and peak
memory 5.6-6.0 GiB. Runtime inputs were staged to the Linux filesystem to avoid
WSL `/mnt/d` I/O stalls; all 27 staged files were SHA256-identical to the durable
project artifacts. Portable checkpoints restore durable paths under
`data/experiments/phase2_5080_v1/checkpoints/`.

Phase 2 next priorities are deliberately narrow:

1. Obtain verified target-conditioned negative or competition labels; without them pair calibration cannot be made legitimate.
2. Generate real poses only for a small, stable consensus subset, then rerun P3 geometry extraction instead of fabricating pose features.
3. Improve pair ranking with better hard-negative biology and target-conditioned interaction supervision before increasing model size.
4. Keep all current candidate values as computational ranking evidence until binding and blocking assays exist.

## Historical Phase I Objective

**Phase I: Mechanism-guided construction of a PVRIG-blocking-oriented VHH scaffold library**

Build a reproducible first-stage foundation for PVRIG/PVRL2 blocking VHH design. Phase I produces design-ready scaffold inputs and evidence maps, not final antibody candidates.

## Success Criteria

- [x] Phase I planning is written and versioned in `docs/PHASE_I_PLAN.md`.
- [x] PVRIG/PVRL2 structure files are collected for `8X6B` and `9E6Y`.
- [x] PVRIG interface residues are extracted per structure using a reproducible script.
- [x] Interface consensus is computed by sequence-alignment columns, not raw residue numbers.
- [x] S67/R95/I97 are documented as soft epitope hints, not hard constraints.
- [x] Positive/reference antibody strategy is documented, separating sequence positives from mechanism references.
- [x] Official-page Tab5/HR-151 sequences are recorded as sequence positives with ANARCI/IMGT CDRs.
- [x] Scaffold data source strategy is documented, separating scaffold pools from benchmarks/references.
- [x] Validator-first gates are documented for ANARCI/IMGT, ab-data-validator, CDR identity, and diversity.
- [x] Leader verification records commands, files, findings, risks, and next steps.
- [x] ANARCI/IMGT has populated known-positive CDRs.
- [x] Official `ab-data-validator` has been installed/run and versioned.
- [x] PLAbDab-nano download route has been checked without creating workspace scaffold FASTA.
- [x] Controlled PLAbDab-nano scaffold import has started after source/use-term caveat and validator gates were ready.
- [x] Phase I-b regression tests cover structure interface extraction.
- [x] PVRIG numbering reconciliation maps PDB/alignment/UniProt/patent-hint coordinates.
- [x] S67/R95/I97 have explicit structure-coordinate mapping under the UniProt Q6DKI7 numbering assumption.
- [x] First controlled PLAbDab-nano scaffold import has passed gate-first validation.

## Historical Phase I Gate

- Phase I-a status: accepted complete.
- Phase I-b status: first controlled PLAbDab-nano import complete.
- Current phase goal: controlled scaffold import and validation, not final candidate design.
- Candidate design remains out of scope for this phase; a clean validated scaffold library now exists for later Phase II redesign.

## Current Status

| Area | Status | Evidence | Notes |
| --- | --- | --- | --- |
| Workspace setup | Done | `data/`, `docs/`, `positives/`, `scaffolds/`, `reports/` | Repo-local project scaffold initialized. |
| Structure collection | Done | `data/structures/8X6B.pdb`, `data/structures/9E6Y.pdb` | Downloaded from RCSB. |
| Interface extraction | Done | `scripts/extract_pvrig_interface.py`, `data/structures/PVRIG_*csv` | Heavy-atom contact baseline at `<=4.5 A`; alignment-column consensus. |
| Epitope map | Done | `data/structures/PVRIG_epitope_priority_map.pml` | Executable PyMOL selections for each structure; soft hints remain excluded from hard selections. |
| Numbering reconciliation | Done | `scripts/reconcile_pvrig_numbering.py`, `data/structures/PVRIG_numbering_reconciliation.csv`, `data/structures/PVRIG_soft_hint_structure_mapping.csv` | PDB residue IDs, alignment columns, UniProt Q6DKI7 positions, and S67/R95/I97 hints reconciled. |
| Positive references | Done for official positives | `positives/known_positive_antibodies.fasta`, `positives/positive_antibody_metadata.csv`, `positives/known_positive_CDR_table.csv` | Tab5 VH/VL and HR-151 VHH recorded from official page; CDRs populated by ANARCI/IMGT. |
| Mechanism references | Started | `positives/mechanism_reference_table.csv` | COM701 mechanism reference only; no confirmed sequence in positive FASTA. |
| Hotspot constraints | Done | `data/structures/PVRIG_hotspot_set_v1.csv` | 21 core, 2 secondary, 3 soft hints; no hard contact constraint on soft hints. |
| Scaffold source mapping | Done for PLAbDab-nano | `scaffolds/source_registry.csv`, `reports/plabdab_nano_access_review.md`, `reports/plabdab_nano_license_decision.md` | PLAbDab-nano used for local screening with raw-data redistribution caveat. |
| Scaffold import/gate | Done for first PLAbDab-nano batch | `scaffolds/raw_vhh_scaffold_pool.fasta`, `scaffolds/raw_vhh_scaffold_metadata.csv`, `scaffolds/vhh_scaffold_quality_table.csv`, `reports/plabdab_nano_scaffold_gate_summary.md` | 1965 unique records imported; 1591 clean scaffolds retained. |
| Scaffold clustering/top set | Done for first PLAbDab-nano batch | `scaffolds/vhh_scaffold_cluster_table.csv`, `scaffolds/top_200_vhh_scaffolds_for_design.fasta`, `scaffolds/top_200_vhh_scaffolds_for_design.csv` | 1268 retained clusters; 200 top design-ready scaffolds selected. |
| Validator integration | Done for known positives | `tools/ab-data-validator`, `reports/validator/KNOWN_POSITIVE_VALIDATION.md` | Official validator cloned at commit `97df17aa09bc576a861cf0d8242de97af379fd80`; known positives trigger expected high-identity failures. |
| Team exploration | Done | `reports/team/*.md`, `reports/leader_verification.md` | Team completed and shut down cleanly. |

## Current Quantitative Evidence

- `8X6B` PVRIG chain: `B`; ligand chain: `A`.
- `9E6Y` PVRIG chain: `A`; ligand chain: `D`.
- Interface cutoff: any PVRIG heavy atom within `<=4.5 A` of ligand heavy atom.
- `8X6B`: 22 PVRIG interface residues; 57 residue-residue contact pairs.
- `9E6Y`: 22 PVRIG interface residues; 56 residue-residue contact pairs.
- Consensus map: 23 aligned interface columns; 21 supported by both structures; 2 single-structure.
- PVRIG numbering reconciliation: 211 mapped structure residues (`8X6B=103`, `9E6Y=108`) to UniProt Q6DKI7 positions via PDB DBREF offsets.
- S67/R95/I97 structure mappings: 6 rows total. S67 maps outside the current `<=4.5 A` interface in both structures; R95 maps to consensus interface column 50 in both structures; I97 maps to alignment column 52 and is an `8X6B` single-structure contact only.
- PLAbDab-nano access review: direct `vhh_sequences.csv.gz` route responds `200`; source file has 4457 rows (`4427` VHH, `30` VHH/sdAb). First controlled import has now produced scaffold FASTA/CSV artifacts with the raw-data redistribution caveat preserved.
- PVRIG hotspot set v1: 26 rows total = 21 core hotspots, 2 secondary hotspots, 3 soft hints.
- Controlled PLAbDab-nano import: 4457 source rows scanned, 1965 unique VHH/sdAb records imported.
- ANARCI/IMGT gate: 1965/1965 imported records passed numbering.
- Developability/framework/positive-leakage gates: 374 records dropped; Clean scaffold records retained: 1591.
- Drop reasons: fail_developability 345, CDR3 length outside designable range 32, fail_framework_health 29, incomplete IMGT regions 8, positive CDR identity >=80% 1.
- Diversity gate: 1591 retained scaffolds formed 1268 greedy clusters at 0.90 sequence-identity threshold.
- Top scaffold records written: 200 to `scaffolds/top_200_vhh_scaffolds_for_design.fasta` and `.csv`.
- Positive FASTA entries: 3 (`tab5_vh`, `tab5_vl`, `hr151_vhh`).
- Known-positive CDR rows: 3 with `anarci_success`.
- Official-validator high-identity rows: 9, all 100.0% identity against 80.0% threshold.
- Confirmed scaffold imports: first PLAbDab-nano controlled batch complete.

## Decisions

- Phase I output is a **design-ready VHH scaffold library foundation**, not final PVRIG binders.
- COM701 is a mechanism/clinical reference unless a complete, versioned sequence is confirmed.
- S67/R95/I97 are soft evidence, not hard constraints.
- First-stage CDR scoring uses **CDR designability**, not precise docking geometry.
- SAbDab/SAbDab-nano/ANDD are benchmark/reference sources, not scaffold main libraries.
- Validator gates must be applied before expensive design/docking stages.
- Bulk scaffold FASTA files are allowed only through controlled import scripts after source terms, numbering, and validator gates are ready; this condition is now met for the first PLAbDab-nano batch.
- Raw PLAbDab-nano CSV/GZ is not vendored; imported rows retain `do_not_redistribute_raw_csv`.
- The first top 200 are design-ready scaffolds only, not PVRIG binders/blockers.

## Latest Findings

- Official challenge page was directly fetched on 2026-07-05 and confirms PVRIG/CD112R, PVRL2, `8X6B`, `9E6Y`, IMGT/ANARCI/MUSCLE/Hamming/Identity similarity logic, ab-data-validator URL, and Tab5/HR-151 reference sequences.
- Official `clickmab-bio/ab-data-validator` was cloned at commit `97df17aa09bc576a861cf0d8242de97af379fd80`; ANARCI/MUSCLE environment was created locally with micromamba.
- RCSB and local PDB headers confirm structure titles and chain mapping.
- Raw PDB residue numbers differ between `8X6B` and `9E6Y`; alignment-column consensus prevents false disagreement.
- Numbering reconciliation now maps structure residues to UniProt Q6DKI7 positions and confirms S67/R95/I97 are still soft hints: R95 has strongest interface support, I97 partial support, and S67 is not a current distance-interface residue.
- PLAbDab-nano, OAS, INDI2, ANARCI, and ANDD web pages were fetched and summarized in `reports/external_source_evidence.md`.
- PLAbDab-nano download route is confirmed, but the page does not state a sufficiently explicit dataset-use license; `reports/plabdab_nano_license_decision.md` limits use to local screening and source disclosure without raw CSV/GZ redistribution.
- First controlled PLAbDab-nano gate produced `clean_vhh_scaffold_library.fasta` with 1591 records and `top_200_vhh_scaffolds_for_design.fasta` with 200 records.

## Verification Log

Latest leader verification command:

```bash
scripts/verify_phase_i_outputs.py
```

Result: PASS. The script verified structure row counts, byte-identical regeneration, numbering reconciliation, hotspot set v1, S67/R95/I97 soft-hint mapping, positive/reference separation, ANARCI/IMGT CDR extraction, official-validator similarity evidence, PLAbDab-nano license/access-review state, controlled scaffold import counts, clean library, cluster table, top 200 outputs, and docs/report anchors.

## Historical Phase I Next Actions

1. Review `scaffolds/top_200_vhh_scaffolds_for_design.csv` for any project-specific exclusions before Phase II.
2. Confirm source access and terms for OAS/INDI before importing those larger scaffold sources, if more scaffold diversity is needed.
3. Keep `scripts/run_known_positive_validator.py` as the reusable template for future candidate validator runs.
4. Add later structure enrichment (`delta SASA`, hydrogen bonds, salt bridges, hydrophobic contacts) before Phase II docking/redesign.
5. Only after explicit Phase II start: CDR redesign against `PVRIG_hotspot_set_v1.csv`; still no claim that current scaffolds bind PVRIG.
