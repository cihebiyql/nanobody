# Implementation notes

This V6 extractor is a Stage-1-specific adaptation of the frozen V5 OPEN_TRAIN
contact extractor. Deliberate changes from the V5 multi-seed lane are:

- the cohort is the 1,320-candidate V4-H Stage-1 release, not V4-D OPEN_TRAIN226;
- only seed 917 exists, so pose-frequency is retained and no seed-median is invented;
- 39 technical-incomplete candidates are explicit NA states and no result/pose from
  those candidates is opened;
- the original Stage-1 scalar labels, especially `R_dual_min`, are copied from the
  hash-pinned terminal ranking rather than recomputed;
- source paths are read-only and outputs must be outside the canonical campaign root.

No scorer threshold, RMSD gate, Docking result, ranking, or candidate status is
changed by this package.
