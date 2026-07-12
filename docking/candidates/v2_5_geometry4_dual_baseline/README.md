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
| `PV25-EF3F71502C71` | `zym_test_359954` | Complete; dual-baseline B; final rank 4 |
| `PV25-8E96BF37FD37` | `zym_test_3633872` | Complete; single-baseline A recheck; final rank 3 |
| `PV25-0B63D218E0F3` | `zym_test_8787` | Complete; dual-baseline A/A; final rank 1 |
| `PV25-25F7D6778F87` | `zym_test_108006` | HADDOCK3 complete; dual-baseline postprocess complete |

The completed candidate uses HADDOCK rank-1 pose `cluster_1_model_1` and is A
against both reference interfaces. Its candidate-level class is
`CONSENSUS_BLOCKER_LIKE_A`, with conservative metrics 15 hotspot overlaps, 610
total PVRL2 occlusion pairs, 106 CDR3 occlusion pairs, and a 0.17377 CDR3
fraction. Final cascade labels are two computational `FINAL_POSITIVE_HIGH`, one
`FINAL_RECHECK_SINGLE_BASELINE`, and one `FINAL_POSITIVE_PLAUSIBLE`; no docking
row remains incomplete. This does not establish experimental binding or blocking.

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

Because Node1 remained near load1 120-130, the gate was not weakened. The
isolated local runtime and guarded takeover path are:

```bash
python scripts/run_pending_haddock3_local.py --plan
python scripts/run_pending_haddock3_local.py --claim-and-execute
```

The takeover requires exact HADDOCK3 2025.11.0, an explicit CNS `stop` smoke,
unchanged production input hashes, a recent nonce-bound handoff, a frozen and
rechecked remote waiter, an absent remote run for every candidate, and both
ownership and runner locks. The completed production runs took 96, 94, and 93
seconds and produced 10, 9, and 8 non-empty top poses.

To wait without bypassing the gate, deploy the bounded Node1 tmux waiter:

```bash
bash scripts/deploy_guarded_haddock3_waiter_node1.sh --deploy
bash scripts/deploy_guarded_haddock3_waiter_node1.sh --status
```

The deployed waiter uses an independent tmux socket plus global and per-candidate
`flock` locks, polls every 60 seconds, times out after 24 hours, rechecks
`load1 < 64` before every candidate, and refuses any incomplete run directory.
It also records HUP/INT/TERM as `INTERRUPTED`, never as `COMPLETE`, and validates
all numeric overrides before launching tmux. A review-discovered status bug was
fixed while all three run directories were absent. A live tmux HUP check at
18:02:57 produced `INTERRUPTED` with exit 129 rather than false `COMPLETE`.
The final corrected runner was deployed at 18:03:11, entered
`WAITING_FOR_LOAD` at load1 93.21, and had no duplicate session or HADDOCK3
process.

The launcher is sequential, refuses incomplete pre-existing run directories,
and never deletes a run. Completed outputs must be synced back into the
corresponding `remote_sync/haddock3/<candidate>/` workdir before dual-baseline
postprocessing.

After syncing completed runs, rebuild the audit and import-only summary with:

```bash
python scripts/run_dual_baseline_postprocess.py
```

The local post-waiter finalizer can keep the remaining chain resumable without
bypassing the Node1 load gate. It waits for the remote waiter to report
`COMPLETE`, atomically stages each run, requires all four dual-baseline rows,
uploads the hash-checked summary, reruns cascade finalize under a remote lock,
and writes an immutable local cascade snapshot:

```bash
python scripts/watch_and_finalize_geometry4.py --once
python scripts/watch_and_finalize_geometry4.py --watch
python scripts/watch_and_finalize_geometry4.py --status
```

`--once` exits 10 while the remote load gate is still active. The long-running
`--watch` path retries bounded SSH failures, refuses stale active waiter state or
partial local runs, and records its machine-readable state in
`reports/post_waiter_finalize_status.json`.

The earlier production watcher exited after bounded SSH failures while the
remote waiter remained safe. The local failover later completed, remote cascade
finalize published under lock with rollback protection, and an SCP-transferred
archive produced immutable snapshot `geometry4_complete_finalize_20260711_230812`.
The canonical local and remote cascade files are SHA256-identical.

Only `RUN` rows with two baselines, all four geometry metrics, and valid sequence
provenance are written to the finalize CSV. The package currently passes 41/41
unit tests plus both existing success-case regression scripts.

The workspace keeps a catch-all `.gitignore`, but the existing lightweight sync
allowlist builder selects this package's README, manifest, source scripts, and
all five tests, including the behavioral waiter and local takeover suites. The selection proof is
`reports/lightweight_sync_allowlist_check_20260711.txt`; `.gitignore` was not
broadened.

The post-fix code review is APPROVED with no remaining findings, and independent
artifact verification is PASS. See `reports/review_closure_20260711.json` and
`reports/final_verification_20260711.json`.

The guarded-waiter follow-up review is also APPROVED with zero remaining
findings after the signal, numeric, quoting, shared-lock, executable-test,
direct-launcher NaN, and lightweight-allowlist closures.
