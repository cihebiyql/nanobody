# V4-F96 zero-eligible terminal V2.1

V2 completed the frozen Fast-QC on all 96 prospective V4-F candidates. All 96 were genuine Fast-QC hard failures, so the frozen Full-QC eligible set is empty. The V2 wrapper then failed only because its terminal validator required a `merge_full` state that the cascade intentionally does not emit when there are no survivors.

V2.1 does **not** alter thresholds, sequences, or hard-fail decisions. It does not create a synthetic `full_merged.tsv`, does not run Full-QC chunks, and does not replace candidates. It validates the exact V2 artifacts and publishes `COMPLETE_WITH_ZERO_ELIGIBLE`, plus a canonical eligibility receipt with `hardpass_count=0` and `downstream_docking_eligible_count=0`.

Canonical Node1 receipt:

`/data1/qlyu/projects/pvrig_v4_f_holdout96_zero_eligible_terminal_v2_1_20260717/CANONICAL_ELIGIBILITY_RECEIPT.json`

Evidence boundary: frozen V4-F96 sequence/Fast-QC eligibility attrition only; not Full-QC evidence for any candidate, not Docking, geometry, binding, affinity, competition, experimental blocking, blocker probability, or Docking Gold.

Audit note: `IMPLEMENTATION_FREEZE.json` contains a manually mistyped `frozen_at_utc` two minutes later than the actual file creation. `AUDIT_TIMESTAMP_CORRECTION_V1.json` preserves the original freeze hash and records filesystem ordering showing that the freeze preceded terminalization. No scientific field or result was changed.
