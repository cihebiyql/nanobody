# Top5000 fully-unstarted seed42/3047 two-node handoff

This package is a deterministic subset of the frozen Top5000 dual-receptor
four-seed source handoff.

- Selection: the 250 lowest `release_rank` fully-unstarted candidates from each
  of the eight original source shards.
- Active jobs: source jobs for seeds 42 and 3047 across receptors 8x6b and
  9e6y; source `job_id`, `job_hash`, and every source job field are unchanged.
- Scale: 2,000 candidates, 8,000 jobs, two node manifests with exactly 1,000
  candidates and 4,000 jobs each.
- Node 0 receives original shards 0-3; Node 1 receives original shards 4-7.
- `selection/frozen_inputs/` preserves the exact authority files supplied to
  the builder.  Canonical normalized ID lists and selection/exclusion ledgers
  are adjacent.
- `selection/STARTED_JOB_OVERLAP.tsv` is header-only by contract.

This package only prepares a portable handoff.  It does not launch Docking,
contact Node1/bxcpu, or claim biological/experimental validation.
