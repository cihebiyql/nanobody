# PVRIG V2.5 Geometry-4 Dual-Baseline Follow-up

This package follows the four-candidate geometry shortlist from the blinded
`vhh-large-scale-screen` run. It keeps the cascade IDs blinded while retaining
the coordinator-only source IDs needed to locate docking assets.

## Fixed interpretation

- HADDOCK3 produces candidate/PVRIG poses against the 8X6B receptor setup.
- The same poses are aligned and scored independently against the 8X6B and
  9E6Y PVRIG/PVRL2 references by the established success-case workflow.
- Two-baseline A/A support is required for `CONSENSUS_BLOCKER_LIKE_A`.
- A single A baseline or A/B result remains a recheck result.
- Recheck or consensus labels are invalid as per-baseline inputs and can never
  be normalized to A.
- A complete import must reconstruct chain A from the candidate VHH input PDB
  and match the manifest sequence SHA256.
- Every label is a computational geometry priority, not measured binding or
  blocking truth.

## Current candidates

| Blinded cascade ID | Coordinator-only source ID | HADDOCK3 state |
| --- | --- | --- |
| `PV25-EF3F71502C71` | `zym_test_359954` | Guarded waiter queued; load gate pending |
| `PV25-8E96BF37FD37` | `zym_test_3633872` | Guarded waiter queued; load gate pending |
| `PV25-0B63D218E0F3` | `zym_test_8787` | Guarded waiter queued; load gate pending |
| `PV25-25F7D6778F87` | `zym_test_108006` | HADDOCK3 complete; dual-baseline postprocess complete |

The completed candidate uses HADDOCK rank-1 pose `cluster_1_model_1` and is A
against both reference interfaces. Its candidate-level class is
`CONSENSUS_BLOCKER_LIKE_A`, with conservative metrics 15 hotspot overlaps, 610
total PVRL2 occlusion pairs, 106 CDR3 occlusion pairs, and a 0.17377 CDR3
fraction. Cascade finalize currently reports one computational
`FINAL_POSITIVE_HIGH` and three `FINAL_INCOMPLETE_NEEDS_DOCKING` rows. This does
not establish experimental binding or blocking.

Generated evidence:

```text
reports/candidate_level_8x6b_9e6y_audit.csv
reports/cascade_finalize_docking_summary.csv
reports/dual_baseline_postprocess_status.json
```

## Commands

Preflight only:

```bash
bash scripts/run_pending_haddock3_node1.sh --plan
```

Execute only when the fixed host load gate accepts `load1 < 64`:

```bash
bash scripts/run_pending_haddock3_node1.sh --execute
```

The final 2026-07-11 preflight returned exit 20 at load1 101.38, so none of the
three pending jobs was started. Evidence is in
`reports/node1_preflight_final_20260711.log`.

To wait without bypassing the gate, deploy the bounded Node1 tmux waiter:

```bash
bash scripts/deploy_guarded_haddock3_waiter_node1.sh --deploy
bash scripts/deploy_guarded_haddock3_waiter_node1.sh --status
```

The deployed waiter uses an independent tmux socket plus `flock`, polls every 60
seconds, times out after 24 hours, rechecks `load1 < 64` before every candidate,
and refuses any incomplete pre-existing or newly appeared run directory. It was
deployed at 2026-07-11 17:42:09 +08:00 and entered `WAITING_FOR_LOAD` at load1
96.97. After a controlled timeout-order hardening restart, the current runner
started at 17:48:21; the 17:49:21 status remained `WAITING_FOR_LOAD` at load1
103.44. No HADDOCK3 run had started.

The launcher is sequential, refuses incomplete pre-existing run directories,
and never deletes a run. Completed outputs must be synced back into the
corresponding `remote_sync/haddock3/<candidate>/` workdir before dual-baseline
postprocessing.

After syncing completed runs, rebuild the audit and import-only summary with:

```bash
python scripts/run_dual_baseline_postprocess.py
```

Only `RUN` rows with two baselines, all four geometry metrics, and valid sequence
provenance are written to the finalize CSV. The package currently passes 13/13
unit tests plus both existing success-case regression scripts.

The post-fix code review is APPROVED with no remaining findings, and independent
artifact verification is PASS. See `reports/review_closure_20260711.json` and
`reports/final_verification_20260711.json`.
