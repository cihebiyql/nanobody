# PVRIG V2.5 Screening Funnel Audit - 2026-07-11

## Decision

`FOUR_DUAL_BASELINE_IMPORTS_TWO_COMPUTATIONAL_HIGH_WET_LAB_PENDING`

The model-to-cascade interface is operational. The V2.4 multi-seed candidate
score is converted into the cascade-compatible `binder_score`, the 24-sample
blinded panel completed the new sequence cascade, and the prospective assay
package was rebuilt under the strengthened preregistration contract. All four
geometry candidates now have complete importable evidence and have been
published through the cascade finalize stage.

No computational result in this audit is a measured binding, blocking, or
functional label. `FINAL_POSITIVE_HIGH` means only a high-priority A/A
dual-baseline geometry call. The computational screening stop condition is now
met; all prospective laboratory measurements remain pending.

Machine-readable evidence:
`audits/pvrig_v2_5_screening_funnel_audit_20260711.json`.

## Fixed Stage Responsibilities

| Stage | Responsibility | Output semantics | Must not be interpreted as |
| --- | --- | --- | --- |
| Model front-screen | Rank a large candidate library cheaply | Relative priority within the scored input set | Binding probability or blocker probability |
| Large-scale cascade | Sequence QC, positive-CDR novelty, developability review, bounded diversity, and shortlist ranking | Computational validation and queue priority | Experimental nonbinding or blocking truth |
| 8X6B/9E6Y geometry | Structure, docking, and dual-baseline blocker-like geometry consensus | Computational pose evidence | Wet-lab blocker validation |
| Prospective assays | Expression/SEC, BLI/SPR, competition, then functional assay | New reviewed biological evidence | Automatic training data before review and a new split/seal protocol |

## Model Front-Screen Interface

- Source rows: 50 candidates in
  `predictions/pvrig_model_frontscreen_summary_v1.csv`.
- Panel rows mapped to blinded IDs: 6 in
  `assays/pvrig_v2_5_prospective_v1/model_frontscreen_summary_blinded.csv`.
- Cascade field: `binder_score`.
- Exact semantics: `within_input_rank_percentile_higher_is_better`.
- Claim boundary:
  `relative_model_frontscreen_priority_not_binding_or_blocker_probability`.

The score is intentionally monotonic with the model rank and bounded to
`[0, 1]`; it is not calibrated against measured binders/nonbinders.

## Cascade Execution Evidence

Remote run:
`/data/qlyu/software/vhh_eval_tools/runs/pvrig_v25_panel_cascade_20260711_1450`

| Metric | Value |
| --- | ---: |
| Started | 2026-07-11 15:39:59 +08:00 |
| Finished | 2026-07-11 15:42:11 +08:00 |
| Wall time | 132 seconds |
| Input records | 24 |
| Exact unique records | 24 |
| Fast hard-pass | 4 |
| Full-QC shortlist | 4 |
| Full hard-pass | 4 |
| Geometry shortlist | 4 |
| Docking rows imported after finalize | 4 |
| `FINAL_POSITIVE_HIGH` after finalize | 2 |
| `FINAL_RECHECK_SINGLE_BASELINE` after finalize | 1 |
| `FINAL_POSITIVE_PLAUSIBLE` after finalize | 1 |
| Incomplete docking rows after finalize | 0 |

The current candidate-level state after dual-baseline finalize is:

| Blinded ID | Coordinator-only candidate ID | Model rank | Docking evidence | Current final label |
| --- | --- | ---: | --- | --- |
| `PV25-0B63D218E0F3` | `zym_test_8787` | 5 | Imported A/A | `FINAL_POSITIVE_HIGH` (rank 1) |
| `PV25-25F7D6778F87` | `zym_test_108006` | 6 | Imported A/A | `FINAL_POSITIVE_HIGH` (rank 2) |
| `PV25-8E96BF37FD37` | `zym_test_3633872` | 4 | Imported single-baseline A | `FINAL_RECHECK_SINGLE_BASELINE` (rank 3) |
| `PV25-EF3F71502C71` | `zym_test_359954` | 1 | Imported B | `FINAL_POSITIVE_PLAUSIBLE` (rank 4) |

The coordinator-only mapping must not be copied into operator schedules.

The older full-QC comparator took 1,629 seconds for 24 rows and returned 22
hard rejects plus 2 review rows. It is retained as a behavior comparator, not
as panel-pruning truth: known positives, designed mutants, and blocker-like
sequences can legitimately trigger sequence/developability review rules.

## Dual-Baseline Docking Evidence

The established success-case protocol docks against the 8X6B PVRIG receptor
setup once, then aligns and scores the same top poses independently against the
8X6B and 9E6Y PVRIG/PVRL2 references. It does not claim two independent docking
runs.

Node1 remained above the fixed load gate, so the threshold was not bypassed.
An isolated local HADDOCK3 2025.11.0 runtime passed CNS and a full-module
candidate smoke. A reviewed ownership protocol then froze/rechecked the remote
waiter, proved all remote runs absent, stopped it, and wrote a nonce-bound owner
sentinel before local execution. The three missing runs completed sequentially
in 96, 94, and 93 seconds with 10, 9, and 8 non-empty top poses.

Candidate-level classes are two `CONSENSUS_BLOCKER_LIKE_A`, one
`SINGLE_BASELINE_BLOCKER_RECHECK`, and one `BLOCKER_PLAUSIBLE_B`. The import CSV
contains all four complete rows. Single-baseline A, malformed, or provenance-
invalid evidence still cannot be upgraded to `FINAL_POSITIVE_HIGH`.

## Prospective Assay Package

The production package was safely rebuilt after the preregistration contract
was strengthened:

- manifest artifacts: 10;
- panel candidates: 24;
- randomized runs/day blocks: 3/3;
- scheduled sample-run positions: 72;
- current truth status: 24 `PENDING_EXPRESSION_QC`;
- current E6 review rows: 0;
- status: `READY_FOR_LAB_PREREGISTRATION`;
- experimental measurements recorded: 0.

Both `functional_max_analyte_concentration_nM` and
`minimum_functional_viability_fraction` are now mandatory preregistration
parameters. The package still requires the laboratory coordinator to enter
real SOP-dependent values and run the freeze command before any measurement.

## Verification

- Phase 2 unittest discovery: 160 tests, all passed.
- Geometry-4 package: 41 tests, all passed; two existing success-case regression
  scripts also passed.
- Review hardening rejects per-baseline recheck/consensus labels instead of
  collapsing them to A, binds every complete import to the chain-A sequence
  reconstructed from its VHH input PDB, and requires RUN/two-baseline/four-
  metric completeness before writing the finalize CSV.
- Independent closure review reports 0 critical/high/medium/low findings and
  APPROVE; the independent artifact verifier reports PASS.
- Guarded-waiter/local-takeover follow-up review reports 0 remaining findings
  and APPROVE after zero-byte-pose, ownership-lock, freeze/recheck, nonce, and
  interrupted-state regression coverage.
- Cascade outputs report four docking imports, two computational high-priority
  calls, one single-baseline recheck, one plausible call, and zero incomplete rows.
- The four canonical cascade artifacts have matching local/remote SHA256 values;
  the finalize CSV hash is
  `38523a3d3dbcbc99c1713af45d1ede6c7fcce105dcb3b0d385a6bd4e8d6809d8`.
- No known software error remains in the completed model-to-cascade and assay
  package branch.
- The remote waiter was interrupted at 22:59:48 only after a SIGSTOP/recheck
  proved state `WAITING_FOR_LOAD`, no candidate run directory, and no candidate
  HADDOCK process. Its final remote state is `INTERRUPTED`; owner remains `local`
  with `state=COMPLETE_LOCAL`, preventing duplicate remote work.
- Remote finalize ran in a staged copy with rollback protection. Binary rsync
  over Windows OpenSSH was rejected after protocol incompatibility; a SHA256-
  verified SCP tar archive was used instead. The immutable local snapshot is
  `geometry4_complete_finalize_20260711_230812`.
- The existing lightweight-sync allowlist selects the waiter/deployer/direct
  launcher and all geometry tests, including the behavioral suite; the global
  catch-all `.gitignore` was not changed.

## Required Next Gates

1. Keep the frozen 24-sample prospective panel intact; sequence/cascade rejects
   are not experimental negatives.
2. Fill and freeze all 13 laboratory-specific preregistration values before the first
   physical measurement.
3. Execute expression/SEC, binding, competition, and functional assays in the
   preregistered order.
4. Treat any resulting E6 rows as review-only. Before model training, create a
   new V2.6 registry, split, seal, readiness audit, and formal protocol.
