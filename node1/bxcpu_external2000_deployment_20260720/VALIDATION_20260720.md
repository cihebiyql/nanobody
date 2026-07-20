# bxcpu external2000 deployment validation

Validated on 2026-07-20 for the frozen external2000 v2 package.

- Input archive SHA256: `411d15ca971adc6b114387a8d2f92b689bb0b6bf4c39d5c01cb77c46ed6c6d96`
- Engine source: HADDOCK 2025.11.0 (`cli.py - 2025.11.0`)
- Target platform: bxcpu EL7 / glibc 2.17
- Compatibility repair: immutable original runtime parts plus the SHA-pinned
  `numpy_el7_overlay_2.0.1.tar.gz` overlay (`manylinux_2_17`).
- v2 package material repair: SHA-pinned
  `reference_normalization_summary.json` from the matching V29 reference
  lineage. Its two normalized PVRIG/PVRL2 reference PDB hashes match the v2
  package.

Preflight on bxcpu passed for the source archive, all three runtime parts, the
NumPy overlay, and the reference summary.

One and only one safe-manifest smoke job was submitted:

- Slurm job: `11935765_1`
- Node: `p1811`
- State: `COMPLETED`, exit code `0:0`, elapsed `00:06:32`
- Docking job:
  `CANDIDATE_V29_GEN__C0001__0604783E89058161_8x6b_s917_e35a6ed603de`
- Published state: `SUCCESS`, 10 selected models, 10 pose-score records.

Evidence on bxcpu:

- `$HOME/pvrig_v29_external2000_sequences_v2_20260720_bxcpu_results/status/jobs/CANDIDATE_V29_GEN__C0001__0604783E89058161_8x6b_s917_e35a6ed603de.json`
- `$HOME/pvrig_v29_external2000_sequences_v2_20260720_bxcpu_results/results/CANDIDATE_V29_GEN__C0001__0604783E89058161_8x6b_s917_e35a6ed603de/job_result.json`

The deployment worker reads only `external_ready_now_jobs.tsv`; the 186 jobs in
`external_transfer_from_node21_jobs.tsv` remain excluded.
