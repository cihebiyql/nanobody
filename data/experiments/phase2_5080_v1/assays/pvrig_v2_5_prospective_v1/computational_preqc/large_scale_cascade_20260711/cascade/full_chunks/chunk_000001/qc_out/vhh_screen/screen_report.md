# VHH Screening Report

- Input candidates: 4
- Verdict counts: DEPRIORITIZE_DEVELOPABILITY=2, REVIEW=2
- Summary TSV: `screen_summary.tsv`
- Details JSON: `screen_details.json`

## Layer Rules

- L1 is a hard gate: AbNumber/ANARCI IMGT+Kabat heavy-chain numbering, FR/CDR boundaries, conserved IMGT Cys H23/H104, FR4 motif, CDR length sanity.
- L2 is VHH-like gate: Kabat FR2 hallmarks, hydrophilic H44/H45 substitutions, reduced VH/VL-interface hydrophobicity, AbNatiV VHH score when available.
- L3 is developability: TNP flags, pI/charge, N-glyc motif, Cys pairing, deamidation/isomerization/clipping motifs, hydrophobic runs, polyreactivity proxy.
- L4 is optional structure stability: model coverage and cross-tool FR C-alpha RMSD; CDR graft and target epitope fit need scaffold/antigen context.

## Top Rows

- `PV25-EF3F71502C71`: DEPRIORITIZE_DEVELOPABILITY | L1=WARN L2=WARN L3=FAIL L4=SKIPPED
- `PV25-8E96BF37FD37`: REVIEW | L1=WARN L2=WARN L3=WARN L4=NOT_RUN
- `PV25-0B63D218E0F3`: REVIEW | L1=WARN L2=WARN L3=WARN L4=NOT_RUN
- `PV25-25F7D6778F87`: DEPRIORITIZE_DEVELOPABILITY | L1=WARN L2=PASS L3=FAIL L4=SKIPPED
