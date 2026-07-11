# VHH competition QC run report

Input FASTA: `/data/qlyu/software/vhh_eval_tools/runs/pvrig_v25_assay_preqc_20260711_1413/panel_blinded.fasta`
Output directory: `/data/qlyu/software/vhh_eval_tools/runs/pvrig_v25_assay_preqc_20260711_1413/qc`
Candidates: 24
Official validator failures: 18
Hard gate rejects: 22
Selected Top 24: 2
Reserve 0: 0

## Recommendation counts

- REJECT_HARD_GATE: 22
- REVIEW_RISK: 2

## Output files

- `official_failed_reasons.csv`
- `vhh_screen/screen_summary.tsv`
- `cdr_novelty.tsv`
- `team_diversity.tsv`
- `portfolio_ranked.tsv`
- `submission_top24.fasta`
- `submission_top24.xlsx`
- `reserve_0.fasta`

## Notes

- `official_validator_pass=FAIL` is a hard gate.
- `pass_similarity_filter=FAIL` means at least one CDR has identity >= threshold.
- Structure and docking scores are neutral if those gates were not run/imported.
- Docking labels are computational hypotheses, not experimental IC50/Kd evidence.
