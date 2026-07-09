# Scaffold Workspace

This directory holds Phase I-b VHH scaffold-source planning, controlled imports, gate outputs, and top design-ready scaffold selections.

Current state:

- `source_registry.csv` records explored source roles, import status, and use-term caveats.
- `raw_vhh_scaffold_pool.fasta` and `raw_vhh_scaffold_metadata.csv` contain the first controlled PLAbDab-nano local-screening import.
- `vhh_scaffold_quality_table.csv` contains ANARCI/IMGT, framework-health, developability, positive-leakage, scoring, and keep/drop fields.
- `clean_vhh_scaffold_library.fasta` contains scaffolds that passed the Phase I-b gates.
- `vhh_scaffold_cluster_table.csv` records greedy diversity clusters among retained scaffolds.
- `top_200_vhh_scaffolds_for_design.fasta` and `.csv` contain design-ready scaffold starting points for later CDR redesign.

Key rules:

- These entries are design-ready scaffold starting points only; they are not PVRIG binders or blockers.
- Do not vendor or redistribute the original PLAbDab-nano raw CSV/GZ with submissions unless a clearer dataset license is obtained.
- Keep `license_or_use_terms` provenance fields intact on derived scaffold rows.
- Do not run docking/RFantibody/final Top 50 generation inside Phase I-b outputs.
