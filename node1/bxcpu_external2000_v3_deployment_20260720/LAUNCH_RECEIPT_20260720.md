# V3 two-node launch receipt

Launch date: 2026-07-20.

- V3 archive SHA256:
  `62f3c702f582c1d488263170b3a8835746fe7fb533fa49b01786392978483e94`
- bxcpu cache preflight: PASS for the V3 archive, HADDOCK 2025.11.0 source,
  three runtime parts, and the EL7-compatible NumPy 2.0.1 overlay.
- V3 package validation: `PACKAGE_VALIDATION.json` reports `PASS`.
- Dedicated aggregation smoke on bxcpu: manifest gate `PASS`, 4,000 jobs,
  2,000 candidates, `NOT_READY`, and `unlockable=false` as intended.

Docking array: `11936029`.

| Array task | Node | Allocation | Work shape |
| --- | --- | --- | --- |
| `11936029_1` | `p2314` | 1 exclusive node, 64 CPUs, 230 GiB | 1,907 safe jobs; 16 concurrent 4-core HADDOCK jobs per batch |
| `11936029_2` | `k1314` | 1 exclusive node, 64 CPUs, 230 GiB | 1,907 safe jobs; 16 concurrent 4-core HADDOCK jobs per batch |

The first two 16-job batches published 32 `SUCCESS` records. Sampled V3 results
contain 10 selected models and 10 pose records per job; each sampled pose record
contains both `8x6b` and `9e6y` reference scores.

Only `external_ready_now_jobs.tsv` is scheduled. The 186 jobs in
`external_transfer_from_node21_jobs.tsv` remain excluded.

Aggregator job `11936048` is held with
`afterany:11936029_1:11936029_2`; after both node shards finish, it writes the
external-only reports beneath
`$HOME/pvrig_v29_external2000_sequences_v3_20260720_bxcpu_results/reports/`.
It preserves remaining node21 work as `NOT_READY`/technical `NA`, rather than
claiming main-project calibration or a false FAIL.
