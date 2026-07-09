# Mutant Validation Panel

This panel is for robustness validation of the PVRIG VHH sequence-to-blocker workflow.
It is not a new-design submission set.

## Scope

- Base VHHs: PVRIG-20, PVRIG-30, PVRIG-38, PVRIG-39, 20H5, 30H2, 39H4
- Panel records: 36
- Uses known positive/control sequences and local amino-acid perturbations to test pipeline stability, leakage detection, and threshold sensitivity.
- Current panel execution is complete: 36/36 structures, 36/36 HADDOCK3 run dirs, and 36/36 8X6B+9E6Y consensus CSVs.
- These rows remain calibration/leakage controls, not new-design submissions.

## Mutation classes

- known_20_family_cdr3_stability_delta: 1
- multi_cdr3_alanine_scan: 7
- single_aromatic_to_alanine_cdr3: 7
- single_conservative_cdr3: 7
- single_conservative_framework: 7
- unmutated_positive_control: 7

## Execution order

```bash
python docking/success_case_validation/prepare_mutant_validation_batch.py
python docking/success_case_validation/check_vhh_sequence_leakage.py \
  --candidate-csv docking/calibration/mutant_validation_panel/mutant_panel.csv \
  --out-csv docking/calibration/mutant_validation_panel/mutant_panel_sequence_leakage.csv
python docking/success_case_validation/run_mutant_panel_batch.py --stage structure --keep-going
python docking/success_case_validation/run_mutant_panel_batch.py --stage docking --jobs 4 --keep-going
python docking/success_case_validation/run_mutant_panel_batch.py --stage postprocess --jobs 4 --keep-going
python docking/success_case_validation/summarize_mutant_panel_status.py
python docking/success_case_validation/validate_mutant_panel_completion.py
python docking/success_case_validation/summarize_mutant_panel_results.py
python docking/success_case_validation/analyze_mutant_panel_threshold_sensitivity.py
```

## Interpretation

- Base-reference rows are leakage/positive controls and must not be ranked as novel candidates.
- Conservative CDR3 substitutions are sensitivity controls; retained A-level labels mean the workflow is not overly brittle, but still need pose review.
- CDR3 alanine/aromatic-to-alanine rows are negative/fragility controls; a retained high score should trigger manual pose inspection rather than automatic biological interpretation.
- Framework controls test pipeline plumbing and CDR-range stability, not biological improvement.

## Current full-panel status

All 36 rows have been run through node1 structure prediction, HADDOCK3 docking, and local 8X6B/9E6Y postprocessing.

- Structure-ready records: 36/36
- Structure QC sane: 36/36
- HADDOCK3 run dirs: 36/36
- Consensus CSVs: 36/36
- Aggregate consensus rows: 357
- Aggregate labels: A/A=8, single-baseline A=109, plausible B=210, evidence E=30
- Leakage labels: exact known-positive=7, near known-positive=29
- Manual-review queue: 12 CDR3 disruptive/alanine rows retain A/A or single-baseline A and require pose inspection before interpretation.
- Threshold grid: 81 settings; default row reproduces the locked aggregate counts; 4/81 preserve default case-level calls.

Status summary:

```bash
python docking/success_case_validation/summarize_mutant_panel_status.py
python docking/success_case_validation/validate_mutant_panel_completion.py
python docking/success_case_validation/summarize_mutant_panel_results.py
python docking/success_case_validation/analyze_mutant_panel_threshold_sensitivity.py
```

Outputs:

- `mutant_panel_status.csv`
- `MUTANT_PANEL_STATUS_SUMMARY.md`
- `MUTANT_PANEL_COMPLETION_VALIDATION.md`
- `MUTANT_PANEL_RESULT_STRATIFICATION.md`
- `mutant_panel_result_stratification_summary.csv`
- `MUTANT_PANEL_THRESHOLD_SENSITIVITY_REPORT.md`
- `mutant_panel_threshold_sensitivity_summary.csv`
