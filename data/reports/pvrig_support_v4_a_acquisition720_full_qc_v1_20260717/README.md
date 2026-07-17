# Support V4-A acquisition720 Node1 Full-QC v1

This package records the frozen, label-free Node1 sequence/developability Full-QC run for the 720-candidate Support V4-A acquisition design.

## Terminal result

- Input / Fast-QC / Full-QC rows: `720 / 720 / 720`.
- Frozen hard gates: `720 hard_fail=False`, `0 hard_fail=True`.
- Official validator PASS: `720`; AbNatiV populated: `720`; Sapiens rows: `720`.
- All 20 parents retained exactly 36 rows; acquisition/audit roles remained `480/240`; patches remained `240/240/240`.
- All Fast-QC survivors entered Full-QC; no cap, no replacement, no model/docking reselection.
- TNP was deliberately deferred and not imputed.

`hard_fail=False` is not equivalent to uniformly strong developability. Post-terminal recommendation counts were 675 `REVIEW_DEVELOPABILITY`, 37 `REVIEW_NOVELTY_MARGIN`, and 8 `REVIEW_RISK`. See `SUPPLEMENTAL_INTERPRETATION.json`.

## Frozen execution

- Remote SSD root: `/data1/qlyu/projects/pvrig_support_v4_a_acquisition720_full_qc_v1_20260717`
- Node1 stages: `prepare -> fast -> full`
- Resource ceiling: 16 concurrent chunks x 2 workers = at most 32/64 CPU; GPU 0.
- Nine local tests passed, followed by a remote zero-work preflight and an independent terminal audit.
- The launcher preflight log was written at `17:24:10.779086Z`, before the runner started at `17:24:11.052867Z`.
- A later manual post-run preflight overwrote the canonical status filename at `17:25:31.506351Z`; it is explicitly reclassified as post-run verification. The remote correction receipt preserves the true prelaunch log provenance.
- The stale terminal `runner.pid` file was removed after proving PID 242215 was no longer alive; no scientific outputs changed.

## Resource evidence boundary

The frozen maximum request was 32 CPUs, expressed as 16 concurrent chunks x 2 workers. Sixteen fresh Full-QC chunks completed, and load1 rose from 0.28 before launch to 11.07 immediately after completion. Because the process finished before the 20-second process snapshot, this package does **not** claim measured instantaneous 32-core saturation. GPU requested and used: 0.

## Claim boundary

This is sequence/developability Full-QC evidence only. It is not Docking, PVRIG binding, affinity, competition, experimental blocking, blocker probability, Docking Gold, or a biological teacher label.

Raw sequences, `full_merged.tsv`, runtime closure, structures, and any future docking output are intentionally excluded from Git.
