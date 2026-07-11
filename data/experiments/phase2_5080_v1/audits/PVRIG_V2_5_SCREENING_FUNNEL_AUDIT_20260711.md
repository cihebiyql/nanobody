# PVRIG V2.5 Screening Funnel Audit - 2026-07-11

## Decision

`ONE_DUAL_BASELINE_COMPUTATIONAL_HIGH_THREE_DOCKING_PENDING_WET_LAB_PENDING`

The model-to-cascade interface is operational. The V2.4 multi-seed candidate
score is converted into the cascade-compatible `binder_score`, the 24-sample
blinded panel completed the new sequence cascade, and the prospective assay
package was rebuilt under the strengthened preregistration contract. One
geometry candidate now has complete dual-baseline evidence and has been
imported through the cascade finalize stage; the other three remain pending.

No computational result in this audit is a measured binding, blocking, or
functional label. `FINAL_POSITIVE_HIGH` means only a high-priority A/A
dual-baseline geometry call. The current stop condition is three remaining
docking jobs plus all prospective laboratory measurements.

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
| Docking rows imported after finalize | 1 |
| `FINAL_POSITIVE_HIGH` after finalize | 1 |
| `FINAL_INCOMPLETE_NEEDS_DOCKING` after finalize | 3 |

The current candidate-level state after dual-baseline finalize is:

| Blinded ID | Coordinator-only candidate ID | Model rank | Docking evidence | Current final label |
| --- | --- | ---: | --- | --- |
| `PV25-EF3F71502C71` | `zym_test_359954` | 1 | Missing | `FINAL_INCOMPLETE_NEEDS_DOCKING` |
| `PV25-8E96BF37FD37` | `zym_test_3633872` | 4 | Missing | `FINAL_INCOMPLETE_NEEDS_DOCKING` |
| `PV25-0B63D218E0F3` | `zym_test_8787` | 5 | Missing | `FINAL_INCOMPLETE_NEEDS_DOCKING` |
| `PV25-25F7D6778F87` | `zym_test_108006` | 6 | Imported A/A | `FINAL_POSITIVE_HIGH` |

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

For `zym_test_108006`, representative pose `cluster_1_model_1` is HADDOCK rank
1 and is `BLOCKER_LIKE_A` against both references. The candidate-level class is
therefore `CONSENSUS_BLOCKER_LIKE_A`. Conservative cross-baseline metrics are:

- hotspot overlap: 15;
- total PVRL2 occlusion: 610;
- CDR3 PVRL2 occlusion: 106;
- CDR3 occlusion fraction: 0.17377.

The import CSV contains only this complete candidate. Single-baseline A, A/B,
missing, malformed, or provenance-invalid evidence cannot be upgraded to
`FINAL_POSITIVE_HIGH`.

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
- Geometry-4 package: 13 tests, all passed; two existing success-case regression
  scripts also passed.
- Review hardening rejects per-baseline recheck/consensus labels instead of
  collapsing them to A, binds every complete import to the chain-A sequence
  reconstructed from its VHH input PDB, and requires RUN/two-baseline/four-
  metric completeness before writing the finalize CSV.
- Independent closure review reports 0 critical/high/medium/low findings and
  APPROVE; the independent artifact verifier reports PASS.
- Cascade outputs report one docking import, one computational high-priority
  call, and three candidates still missing docking evidence.
- Five synchronized finalize artifacts have matching local/remote SHA256
  values.
- No known software error remains in the completed model-to-cascade and assay
  package branch.
- The final Node1 preflight at 2026-07-11 17:14:51 +08:00 correctly returned
  exit 20 at load1 `101.38`; a follow-up check at 17:15:11 reported load
  averages `100.92 / 99.85 / 98.44`. The fixed launch threshold is 64, so no new
  HADDOCK3 task was started.
- A bounded guarded waiter was deployed on an independent Node1 tmux socket at
  17:42:09. It uses `flock`, a 60-second poll, a 24-hour timeout, and the same
  strict `load1 < 64` rule before each candidate. Initial state was
  `WAITING_FOR_LOAD` at load1 96.97; no docking run had started.

## Required Next Gates

1. Keep the frozen 24-sample prospective panel intact; sequence/cascade rejects
   are not experimental negatives.
2. Let the guarded waiter launch the three pending HADDOCK3 jobs only after the
   Node1 load gate passes; do not bypass the fixed load threshold.
3. Produce and validate dual-baseline evidence for the three remaining geometry
   candidates, then rebuild the candidate-level docking summary.
4. Re-run `vhh-large-scale-screen --stage finalize` with the expanded summary;
   retain `zym_test_108006` as a computational priority, not experimental truth.
5. Fill and freeze laboratory-specific preregistration values before the first
   physical measurement.
6. Execute expression/SEC, binding, competition, and functional assays in the
   preregistered order.
7. Treat any resulting E6 rows as review-only. Before model training, create a
   new V2.6 registry, split, seal, readiness audit, and formal protocol.
