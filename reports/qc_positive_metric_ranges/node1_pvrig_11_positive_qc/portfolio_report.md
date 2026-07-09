# VHH competition QC run report

Input FASTA: `/data/qlyu/software/vhh_eval_tools/runs/pvrig_11_positive_qc_20260708/pvrig_11_success_positives.fasta`
Output directory: `/data/qlyu/software/vhh_eval_tools/runs/pvrig_11_positive_qc_20260708/out`
Candidates: 11
Official validator failures: 11
Hard gate rejects: 11
Selected Top 20: 0
Reserve 10: 0

## Recommendation counts

- REJECT_HARD_GATE: 11

## Output files

- `official_failed_reasons.csv`
- `vhh_screen/screen_summary.tsv`
- `cdr_novelty.tsv`
- `team_diversity.tsv`
- `portfolio_ranked.tsv`
- `submission_top20.fasta`
- `submission_top20.xlsx`
- `reserve_10.fasta`

## Notes

- `official_validator_pass=FAIL` is a hard gate.
- `pass_similarity_filter=FAIL` means at least one CDR has identity >= threshold.
- Structure and docking scores are neutral if those gates were not run/imported.
- Docking labels are computational hypotheses, not experimental IC50/Kd evidence.
