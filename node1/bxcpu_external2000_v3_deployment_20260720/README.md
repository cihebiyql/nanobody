# bxcpu V3 external2000 deployment

This deployment runs the V3 archive, not V2. V3 retains all 2,000 sequence,
monomer, job-ID, job-hash, protocol-hash, receptor, and seed-917 identities while
adding the missing score reference and a shard-specific aggregator.

`amd_256q` uses `select/linear`: one submitted job occupies one complete 64-core
node even when fewer CPUs are requested. The account is limited to two nodes, so
the launcher submits exactly two exclusive 64-core jobs. Each node runs sixteen
independent frozen 4-core HADDOCK jobs in parallel, for 64 active docking cores
per node. The requested memory is 230 GiB, below the partition's usable per-node
memory ceiling.

Only `external_ready_now_jobs.tsv` is selected: 3,814 jobs, split evenly as 1,907
jobs per node. The 186 node21-transfer jobs are never scheduled. After both shards
finish, shard 1 runs `aggregate_external2000_results.py`; the published V3 report
is explicitly partial, uses technical `NA` rather than negative labels, and remains
`unlockable=false` until results return to the complete project.

Before submitting, run:

```bash
./preflight_v3_bxcpu.sh
./submit_v3_two_nodes.sh
```
