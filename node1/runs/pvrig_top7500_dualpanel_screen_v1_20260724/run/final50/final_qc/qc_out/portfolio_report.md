# VHH competition QC run report

Input FASTA: `/data/qlyu/projects/pvrig_top7500_dualpanel_screen_v1_20260724/run/final50/final50_ranked.fasta`
Output directory: `/data/qlyu/projects/pvrig_top7500_dualpanel_screen_v1_20260724/run/final50/final_qc/qc_out`
Candidates: 50
Official validator failures: 0
Official validator deferred: False
Hard gate rejects: 0
Selected Top 50: 35
Reserve 0: 0
Gate policy: blocker_calibrated
Team diversity deferred: False

## Recommendation counts

- REVIEW_DEVELOPABILITY: 49
- REVIEW_NOVELTY_MARGIN: 1

## Output files

- `official_failed_reasons.csv`
- `vhh_screen/screen_summary.tsv`
- `cdr_novelty.tsv`
- `team_diversity.tsv`
- `portfolio_ranked.tsv`
- `submission_top50.fasta`
- `submission_top50.xlsx`
- `reserve_0.fasta`

## Notes

- `official_validator_pass=FAIL` is a hard gate.
- `official_validator_pass=DEFERRED_TO_FULL_SHORTLIST` is not a pass; the full shortlist must rerun the official CLI.
- `pass_similarity_filter=FAIL` means at least one CDR has identity >= threshold.
- Structure and docking scores are neutral if those gates were not run/imported.
- Docking labels are computational hypotheses, not experimental IC50/Kd evidence.
- `blocker_calibrated` keeps VHH-like and hydrophobic-run findings as review signals, not blocker hard fails.
- Deferred team diversity must be recomputed on the final shortlist before portfolio selection.
