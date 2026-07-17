# PVRIG V4-F96 Full-QC SSD recovery V2

This package processes **all 96** rows of the prospectively frozen V4-F manifest on Node1 SSD. It performs no model-based reselection and no replacement. It does not read V4-F predictions, Docking outputs, geometry labels, or experimental labels.

The deployed waiter is fail-closed. It starts CPU-only Full-QC only after the Support V4-A720 monomer run publishes an exact 720-attempt terminal marker, its runner/children/resource monitor are dead, and `load1 <= 8.0`. Full-QC is constrained to CPU affinity `0-23`, at most 24 requested workers, and no GPU.

At this deployment snapshot the waiter is active and scientific Full-QC work has not started. TNP is preregistered as deferred with explicit `DEFERRED_UNRUN` / `UPSTREAM_FAST_HARD_FAIL_NA` state and blank numeric/flag fields.

Evidence boundary: sequence/developability QC only; not Docking, docking geometry, PVRIG binding, affinity, competition, experimental blocking, blocker probability, or Docking Gold.

## Terminal update

After the Support V4-A720 structure gate passed, V2 ran the frozen Fast-QC on all 96 candidates. All 96 were real Fast-QC hard failures, leaving zero Full-QC-eligible candidates. The wrapper then failed only because it expected a `merge_full` marker that the cascade does not emit for a zero-survivor branch. No Full-QC chunks were run and no candidate was replaced or reclassified.

The versioned, fail-closed terminal record is published under `../pvrig_v4_f_holdout96_zero_eligible_terminal_v2_1_20260717/`; its canonical receipt records `COMPLETE_WITH_ZERO_ELIGIBLE`, `hardpass_count=0`, and `downstream_docking_eligible_count=0`.
