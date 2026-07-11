# VHH competition QC run report

Input FASTA: `/data/qlyu/software/vhh_eval_tools/runs/pvrig_v25_panel_cascade_20260711_1450/cascade/fast_chunks/chunk_000001/input.fasta`
Output directory: `/data/qlyu/software/vhh_eval_tools/runs/pvrig_v25_panel_cascade_20260711_1450/cascade/fast_chunks/chunk_000001/qc_out`
Candidates: 24
Official validator failures: 0
Official validator deferred: True
Hard gate rejects: 20
Selected Top 100000000: 4
Reserve 0: 0
Gate policy: blocker_calibrated
Team diversity deferred: True

## Recommendation counts

- REJECT_HARD_GATE: 20
- REVIEW_DEVELOPABILITY: 2
- REVIEW_RISK: 2

## Output files

- `official_failed_reasons.csv`
- `vhh_screen/screen_summary.tsv`
- `cdr_novelty.tsv`
- `team_diversity.tsv`
- `portfolio_ranked.tsv`
- `submission_top100000000.fasta`
- `submission_top100000000.xlsx`
- `reserve_0.fasta`

## Notes

- `official_validator_pass=FAIL` is a hard gate.
- `official_validator_pass=DEFERRED_TO_FULL_SHORTLIST` is not a pass; the full shortlist must rerun the official CLI.
- `pass_similarity_filter=FAIL` means at least one CDR has identity >= threshold.
- Structure and docking scores are neutral if those gates were not run/imported.
- Docking labels are computational hypotheses, not experimental IC50/Kd evidence.
- `blocker_calibrated` keeps VHH-like and hydrophobic-run findings as review signals, not blocker hard fails.
- Deferred team diversity must be recomputed on the final shortlist before portfolio selection.
