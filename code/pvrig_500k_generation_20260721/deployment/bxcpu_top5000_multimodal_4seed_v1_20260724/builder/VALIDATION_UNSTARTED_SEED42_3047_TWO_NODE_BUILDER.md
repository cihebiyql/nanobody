# Validation report: fully-unstarted seed42/3047 two-node builder

Date: 2026-07-24  
Scope: `deployment/bxcpu_top5000_multimodal_4seed_v1_20260724/builder/` only

## Delivered

- `build_top5000_unstarted_seed42_3047_two_node_handoff_v1.py`
  - local-only CLI with explicit source/frozen-authority/output paths;
  - validates an exact, symlink-free, SHA256-closed 5000 candidate / 40000 job /
    8 original shard source package;
  - freezes raw and normalized `UNSTARTED_CANDIDATES` and `STARTED_JOB_IDS`;
  - selects the 250 lowest `(release_rank, candidate_id)` fully-unstarted
    candidates from each original shard;
  - emits exactly 2000 candidates and the existing seed 42/3047 × receptor
    8x6b/9e6y source rows (8000 jobs);
  - preserves complete source job rows, including `job_id` and `job_hash`;
  - maps original shards 0–3 to node 0 and 4–7 to node 1, exactly
    1000 candidates / 4000 jobs per node;
  - copies selected monomers and hash-bound protocol/runtime resources;
  - emits selection/exclusion/frozen-authority ledgers, `READY.json`,
    `HANDOFF_RECEIPT.json`, `DOCKING_PLAN.json`, `README.md`, node receipt,
    two-seed cfg lock, and exact-closure `SHA256SUMS`;
  - fail-closes on any selected/started overlap and publishes atomically without
    overwriting an existing output.
- `test_build_top5000_unstarted_seed42_3047_two_node_handoff_v1.py`
  - builds an exact-scale synthetic source with 5000 monomers, 40000 jobs, and
    eight 5000-job shards;
  - runs the CLI twice and compares every output file hash;
  - verifies exact selection, exclusion, node closure, source-row preservation,
    monomer hashes, zero overlap, source immutability, receipts, and
    `SHA256SUMS`;
  - verifies fail-closed behavior when one source shard has only 249 eligible
    candidates.
- `run_unstarted_seed42_3047_builder_tests.sh`
  - repeatable static/synthetic test entry point.
- `README_UNSTARTED_SEED42_3047_TWO_NODE_BUILDER_ZH.md`
  - CLI, package contract, outputs, and test instructions.

## Verification evidence

Executed from the builder directory:

```text
$ bash -n run_unstarted_seed42_3047_builder_tests.sh
PASS

$ ./run_unstarted_seed42_3047_builder_tests.sh
test_cli_builds_exact_reproducible_hash_closed_handoff ... ok
test_rejects_source_shard_with_fewer_than_250_fully_unstarted ... ok
Ran 2 tests in 4.437s
OK

$ python3 build_top5000_unstarted_seed42_3047_two_node_handoff_v1.py --help
PASS
```

The test runner itself executes `python3 -m py_compile` for the builder and test
module before running the synthetic tests.

## Scope and production boundary

- No command in this implementation contacts or mutates Node1/bxcpu.
- No file under `runtime/` is part of this change.
- A real production handoff was intentionally not built because the task calls
  for implementation/unit tests first and supplies no local frozen production
  authority paths. Production execution remains an explicit CLI operation using
  the real source package and its expected SHA256 values.
