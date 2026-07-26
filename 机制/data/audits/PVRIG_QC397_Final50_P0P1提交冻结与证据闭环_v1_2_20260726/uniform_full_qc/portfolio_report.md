# VHH competition QC run report

Input FASTA: `/data/qlyu/projects/pvrig_top7500_dualpanel_screen_v1_20260724/run/qc397_final50_submission_freeze_p0p1_v1_20260726/input_freeze/Final50_submission_freeze.fasta`
Output directory: `/data/qlyu/projects/pvrig_top7500_dualpanel_screen_v1_20260724/run/qc397_final50_submission_freeze_p0p1_v1_20260726/uniform_full_qc`
Candidates: 50
Official validator failures: 0
Official validator deferred: False
Hard gate rejects: 4
Selected Top 50: 46
Reserve 0: 0
Gate policy: competition
Team diversity deferred: False

## Recommendation counts

- REJECT_HARD_GATE: 4
- REVIEW_DEVELOPABILITY: 41
- REVIEW_NOVELTY_MARGIN: 1
- REVIEW_RISK: 4

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
