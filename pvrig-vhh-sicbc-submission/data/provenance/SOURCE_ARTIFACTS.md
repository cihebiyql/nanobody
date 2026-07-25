# Source artifact registry

The package is a final-only extraction of the active workspace.  The following
immutable source artifacts were used to construct the compact evidence:

- `node1/runs/pvrig_top7500_dualpanel_screen_v1_20260724/run/final50/`
  for the final ranked portfolio, official QC/export, Top10 priority list and
  frozen completion manifest.
- `node1/runs/pvrig_top7500_dualpanel_screen_v1_20260724/run/static_review/STATIC_POSE_METRICS.tsv`
  for final candidate/receptor/seed/pose provenance.
- `data/experiments/phase2_5080_v1/prepared/pvrig_old_priority_top7500_seed917_scalar_teacher_v1_20260723/inputs/old_priority_top7500_candidates.tsv`
  for legacy `S0_R8`, `S0_R9`, and `S0_Rdual_exact_min` fields.
- `data/experiments/phase2_5080_v1/prepared/pvrig_top150k_c2_refined_top7500_v1_20260723/c2_refined_top7500_docking_handoff_v1/TOP7500_C2_REFINED.tsv`
  for C2 label-free multi-model utilities.
- `code/pvrig_500k_generation_20260721/run/pvrig_1m_cpu_fixed_pose500k_raw_v4_20260722/inputs/positive11_cdr_imgt.tsv`
  for parent CDR authority.

The large Top7500 source tables are not copied.  `candidate_traceability.tsv`
contains the final 50-row result and can be regenerated from the named inputs.
