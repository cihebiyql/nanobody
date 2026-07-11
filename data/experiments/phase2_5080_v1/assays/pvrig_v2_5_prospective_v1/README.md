# PVRIG V2.5 Prospective Assay Execution Package

This directory is a deterministic, blinded handoff package for the frozen
24-pair panel. It contains no experimental measurements.

## Required order

1. Freeze every null value in `assay_preregistration.json` before the first run.
2. Complete construct identity, expression, purification, and SEC QC.
3. Measure binding for all 24 samples in all three randomized run blocks.
4. Run competition only for QC-passed verified binders.
5. Run the functional assay only for verified blockers.
6. Run `analyze_pvrig_v2_5_assay_results.py` after each data update.

`blinding_key.csv` is coordinator-only. Instrument operators should receive
`assay_run_schedule_blinded.csv` and the applicable result template, not the
candidate identities or roles.

Expression or assay failure is exclusion evidence, never a nonbinder label.
Binding is not blocking. The analyzer only aggregates explicit scientist calls;
it does not invent assay thresholds or replace review of raw curves.
