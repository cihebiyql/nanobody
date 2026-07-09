# PLAbDab-nano Scaffold Gate Summary

## Scope

- Source file: `https://opig.stats.ox.ac.uk/webapps/plabdab-nano/static/downloads/vhh_sequences.csv.gz`
- Source release marker: `Wed, 22 Oct 2025 11:33:00 GMT`
- Source rows scanned until import limit: 4457
- Unique imported VHH/sdAb records: 1965
- Top-N target: 200
- Cluster identity threshold: 0.90

## Gate Results

- ANARCI/IMGT success: 1965
- VHH/sdAb classified: 1965
- Dropped records: 374
- Clean scaffold records retained: 1591
- Clusters among retained scaffolds: 1268
- Top scaffold records written: 200

## Drop Reasons

- fail_developability: 345
- cdr3_length_outside_designable_range: 32
- fail_framework_health: 29
- incomplete_imgt_regions: 8
- positive_cdr_identity_ge_80pct: 1

## Output Files

- `scaffolds/raw_vhh_scaffold_pool.fasta`
- `scaffolds/raw_vhh_scaffold_metadata.csv`
- `scaffolds/vhh_scaffold_quality_table.csv`
- `scaffolds/clean_vhh_scaffold_library.fasta`
- `scaffolds/vhh_scaffold_cluster_table.csv`
- `scaffolds/top_200_vhh_scaffolds_for_design.fasta`
- `scaffolds/top_200_vhh_scaffolds_for_design.csv`

## Constraints

- These scaffolds are not PVRIG binders or blockers.
- No docking, RFantibody, AntiFold, or final Top 50 candidate generation was performed.
- PLAbDab-nano raw CSV/GZ is not vendored; imported rows retain the local-screening use-term caveat.
