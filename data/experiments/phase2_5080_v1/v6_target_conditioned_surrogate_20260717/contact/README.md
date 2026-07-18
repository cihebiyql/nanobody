# V4-H Stage-1 residue-contact teacher

This directory contains a fail-closed, read-only extractor for the terminal V4-H
Stage-1 docking campaign.

Frozen behavior:

- consume the immutable local terminal package plus the canonical Node23 raw root;
- acknowledge all 2,640 jobs (`2,636 SUCCESS`, `4 FAILED_MAX_ATTEMPTS`);
- open results and poses only for the 1,281 `DUAL_1_SEED` candidates;
- retain the 39 `TECHNICAL_INCOMPLETE` candidates as explicit NA rows;
- never recover the valid receptor of an incomplete candidate;
- never relax `native_overlay_rmsd_above_1A` or any scorer threshold;
- write all outputs outside the canonical raw root.

Outputs are three deterministic gzip TSVs (candidate, receptor, residue pair), an
audit JSON, and a hash-bound receipt. These are computational docking contact
intermediates only, not experimental labels.

Use `launchers/launch_node23_stage1_contact_teacher.sh dry-run` before `run`.
