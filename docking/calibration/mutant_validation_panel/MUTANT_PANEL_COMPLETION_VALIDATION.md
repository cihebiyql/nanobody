# Mutant Panel Completion Validation

Verdict: PASS

## Metrics

- panel_records: 36
- status_records: 36
- leakage_records: 36
- total_consensus_rows: 357
- consensus_blocker_like_a: 8
- single_baseline_blocker_recheck: 109
- blocker_plausible_b: 210
- evidence_inference_only_e: 30
- exact_known_positive: 7
- near_known_positive: 29
- failures: 0

## Failures

- none

## Boundary

- This validates computational completion and current aggregate labels for the mutant/control panel.
- These rows are leakage/robustness controls derived from known positives, not new design submissions.
- Experimental blocking still requires assays; single-baseline A remains a recheck label.
- Run `summarize_mutant_panel_results.py` to stratify retained A signals and identify CDR3 disruptive/alanine manual-review rows.
