# Batch Screening Output Integrity Report

Verdict: PASS

## Metrics

- manifest_rows: 11
- status_rows: 11
- summary_rows: 11
- pose_total: 109
- consensus_blocker_like_a: 3
- single_baseline_blocker_recheck: 36
- blocker_plausible_b: 57
- evidence_inference_only_e: 13
- families: 151:3;20:2;30:2;38:1;39:3
- warnings: 22
- failures: 0

## Warnings

- manifest status columns still pending for PVRIG-151_HR151: structure_status,docking_status,consensus_status
- manifest status columns still pending for PVRIG-20: structure_status,docking_status,consensus_status
- manifest status columns still pending for PVRIG-30: structure_status,docking_status,consensus_status
- manifest status columns still pending for PVRIG-38: structure_status,docking_status,consensus_status
- manifest status columns still pending for PVRIG-39: structure_status,docking_status,consensus_status
- manifest status columns still pending for 20H5: structure_status,docking_status,consensus_status
- manifest status columns still pending for 30H2: structure_status,docking_status,consensus_status
- manifest status columns still pending for 39H2: structure_status,docking_status,consensus_status
- manifest status columns still pending for 39H4: structure_status,docking_status,consensus_status
- manifest status columns still pending for 151H7: structure_status,docking_status,consensus_status
- manifest status columns still pending for 151H8: structure_status,docking_status,consensus_status
- per-case cdr range CSV absent for PVRIG-151_HR151; using batch-level patent_success_validation_cdr_ranges.csv
- per-case cdr range CSV absent for PVRIG-20; using batch-level patent_success_validation_cdr_ranges.csv
- per-case cdr range CSV absent for PVRIG-30; using batch-level patent_success_validation_cdr_ranges.csv
- per-case cdr range CSV absent for PVRIG-38; using batch-level patent_success_validation_cdr_ranges.csv
- per-case cdr range CSV absent for PVRIG-39; using batch-level patent_success_validation_cdr_ranges.csv
- per-case cdr range CSV absent for 20H5; using batch-level patent_success_validation_cdr_ranges.csv
- per-case cdr range CSV absent for 30H2; using batch-level patent_success_validation_cdr_ranges.csv
- per-case cdr range CSV absent for 39H2; using batch-level patent_success_validation_cdr_ranges.csv
- per-case cdr range CSV absent for 39H4; using batch-level patent_success_validation_cdr_ranges.csv
- per-case cdr range CSV absent for 151H7; using batch-level patent_success_validation_cdr_ranges.csv
- per-case cdr range CSV absent for 151H8; using batch-level patent_success_validation_cdr_ranges.csv

## Failures

- none

## Interpretation

- This validates batch artifact completeness and locked aggregate counts for the completed 11-positive calibration set.
- Warnings about pending manifest status columns are documentation drift; batch_status.csv and the actual output files are the execution truth.
- This does not claim experimental blocking for new sequences; new or mutated VHHs still require structure prediction, docking, and postprocessing.
