# VHH Screening Report

- Input candidates: 50
- Verdict counts: DEPRIORITIZE_DEVELOPABILITY=1, REJECT_NOT_VHH_LIKE=4, REVIEW=45
- Summary TSV: `screen_summary.tsv`
- Details JSON: `screen_details.json`

## Layer Rules

- L1 is a hard gate: AbNumber/ANARCI IMGT+Kabat heavy-chain numbering, FR/CDR boundaries, conserved IMGT Cys H23/H104, FR4 motif, CDR length sanity.
- L2 is VHH-like gate: Kabat FR2 hallmarks, hydrophilic H44/H45 substitutions, reduced VH/VL-interface hydrophobicity, AbNatiV VHH score when available.
- L3 is developability: TNP flags, pI/charge, N-glyc motif, Cys pairing, deamidation/isomerization/clipping motifs, hydrophobic runs, polyreactivity proxy.
- L4 is optional structure stability: model coverage and cross-tool FR C-alpha RMSD; CDR graft and target epitope fit need scaffold/antigen context.

## Top Rows

- `PVRIG_CAND_001`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
- `PVRIG_CAND_002`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
- `PVRIG_CAND_003`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
- `PVRIG_CAND_004`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
- `PVRIG_CAND_005`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
- `PVRIG_CAND_006`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
- `PVRIG_CAND_007`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
- `PVRIG_CAND_008`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
- `PVRIG_CAND_009`: REVIEW | L1=PASS L2=WARN L3=WARN L4=NOT_RUN
- `PVRIG_CAND_010`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
- `PVRIG_CAND_011`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
- `PVRIG_CAND_012`: REVIEW | L1=PASS L2=WARN L3=WARN L4=NOT_RUN
- `PVRIG_CAND_013`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
- `PVRIG_CAND_014`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
- `PVRIG_CAND_015`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
- `PVRIG_CAND_016`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
- `PVRIG_CAND_017`: REVIEW | L1=PASS L2=WARN L3=WARN L4=NOT_RUN
- `PVRIG_CAND_018`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
- `PVRIG_CAND_019`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
- `PVRIG_CAND_020`: REVIEW | L1=PASS L2=PASS L3=WARN L4=NOT_RUN
