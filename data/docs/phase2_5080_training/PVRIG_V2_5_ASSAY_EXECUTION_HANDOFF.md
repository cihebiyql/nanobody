# PVRIG V2.5 Prospective Assay Execution Handoff

## Scope

This handoff operationalizes the frozen 24-pair PVRIG panel. It does not claim
that expression, binding, competition, or functional experiments have already
run. The package is designed to make those measurements blinded, randomized,
hash-bound, and safe to ingest without converting failures into biological
negative labels.

Package directory:

```text
experiments/phase2_5080_v1/assays/pvrig_v2_5_prospective_v1/
```

The upstream computational funnel is documented in
`PVRIG_MODEL_TO_CASCADE_SCREENING_FUNNEL.md`. The model supplies large-library
relative priority, `vhh-large-scale-screen` performs strict shortlist QC and
computational ranking, and 8X6B/9E6Y docking supplies geometry evidence. None
of those stages replaces the prospective assays in this package.

## Current State

- 24 blinded samples in 8 groups.
- 3 independent randomized run blocks on 3 day blocks.
- 72 sample-run rows for binding, competition, and functional templates.
- 24 expression/SEC QC rows.
- 0 measured rows and 0 E6 review-candidate labels.
- Package status: `READY_FOR_LAB_PREREGISTRATION`.

## Files And Ownership

| File | Owner | Purpose |
| --- | --- | --- |
| `blinding_key.csv` | Study coordinator only | Maps blind IDs to candidate identities and roles. |
| `assay_run_schedule_blinded.csv` | Instrument operators | Frozen run order and sample wells without candidate roles. |
| `construct_manifest.csv` | Expression team | Sequence identity, construct, host/vector/tag, and lot tracking. |
| `expression_qc_results.csv` | Expression/QC team | Yield, purity, SEC monomer fraction, aggregation, identity, and raw evidence. |
| `binding_results.csv` | BLI/SPR team | One row per sample and independent run. |
| `competition_results.csv` | Competition team | Filled only after verified binding eligibility. |
| `functional_results.csv` | Reporter/cell team | Filled only after verified biochemical blocking. |
| `assay_preregistration.json` | Study lead | Lab-specific thresholds and curve-review rules frozen before measurements. |
| `candidate_assay_status.csv` | Generated | Current per-candidate gate status. |
| `e6_label_candidates_review.csv` | Generated | Hash-bound review queue; never direct training input. |

## Execution Order

### 1. Freeze lab-specific parameters

Fill every null value under
`lab_parameters_to_freeze_before_first_measurement` in
`assay_preregistration.json`. These values are intentionally not guessed by
the software because they depend on expression format, target lot, instrument,
assay window, and the approved laboratory SOP.

Then run:

```bash
experiments/phase2_5080_v1/.venv-phase2-5080/bin/python \
  experiments/phase2_5080_v1/src/freeze_pvrig_v2_5_assay_preregistration.py
```

The command checks that all four result tables still contain only `PENDING`
calls. After freezing, changing a threshold requires a new package version.

### 2. Expression, purification, and SEC QC

Use `construct_manifest.csv` for lot tracking and enter the selected lot in
`expression_qc_results.csv`. A `PASS` call requires:

- observed sequence SHA256 equals the expected sequence SHA256;
- identity review passes;
- yield, purity, SEC monomer fraction, and aggregation values are present;
- values agree with the frozen thresholds;
- raw evidence path and SHA256 are present.

`FAIL` and `INCONCLUSIVE` are valid outcomes. They lead to exclusion or
remeasurement, never to `NONBINDER`.

### 3. Binding measurement

Run every QC-passed sample according to `assay_run_schedule_blinded.csv`.
Populate all three run rows in `binding_results.csv`. A completed call must
include the method, maximum analyte concentration, fit QC, concentration-
dependence call, raw-data path, and raw-data SHA256. A binder needs a positive
Kd or explicit censoring qualifier. A nonbinder requires absent concentration-
dependent binding in all valid runs after QC.

The analyzer requires agreement across three independent runs and at least two
day blocks. Mixed, incomplete, or failed fits remain inconclusive.

### 4. PVRIG-PVRL2 competition

Only verified binders are eligible. Set `verified_binder_eligibility=YES` and
populate all three rows in `competition_results.csv`. A valid consensus can
produce either biochemical blocker evidence or verified binder/nonblocker
evidence. Binding alone never produces a blocking label.

### 5. Functional reporter or cell assay

Only biochemical blockers are eligible. Set
`verified_blocker_eligibility=YES` and populate all three rows in
`functional_results.csv`. Functional calls remain a separate axis from binding
and biochemical competition. Every entered functional call, including
`INCONCLUSIVE`, requires an assay method, fit-QC pass, a positive analyte
concentration, viability evidence that meets the frozen threshold, and a
distinct raw-data file for each independent run.

### 6. Analyze after every update

```bash
experiments/phase2_5080_v1/.venv-phase2-5080/bin/python \
  experiments/phase2_5080_v1/src/analyze_pvrig_v2_5_assay_results.py
```

Review:

```text
assays/pvrig_v2_5_prospective_v1/ASSAY_EXECUTION_STATUS.md
assays/pvrig_v2_5_prospective_v1/candidate_assay_status.csv
assays/pvrig_v2_5_prospective_v1/e6_label_candidates_review.csv
assays/pvrig_v2_5_prospective_v1/assay_analysis_summary.json
```

## Raw Data Rule

For each completed result call, keep the raw instrument/QC file and record its
SHA256. For example:

```bash
sha256sum path/to/raw_file
```

Relative paths are resolved against the package directory. Absolute paths are
also accepted. A missing file or hash mismatch is a hard contract failure.

## Truth Boundaries

- Expression failure is not a nonbinder.
- Assay failure is not a nonbinder.
- A designed alanine scan is not a negative before measurement.
- Binding is not blocking.
- Biochemical competition is not automatically a functional effect.
- Mixed calls remain inconclusive.
- Generated E6 rows are review-only and ordinary training is disabled.
- Cascade rejects and incomplete docking rows are computational outcomes, not
  prospective nonbinder labels; the frozen 24-sample panel remains intact.
- Model use requires a new V2.6 split, sealed formal contract, readiness audit,
  and one-shot evaluation plan.
