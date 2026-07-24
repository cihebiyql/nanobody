# Runtime validation report

Validation date: 2026-07-24

Scope:

`pvrig_500k_generation_20260721/deployment/bxcpu_top5000_multimodal_4seed_v1_20260724/runtime/`

Executed:

```text
bash run_static_tests.sh
```

Result:

```text
Ran 7 tests
OK
```

The runner also completed:

- `python3 -m py_compile` for all five Python source/test files;
- `bash -n` for every shell script in this directory;
- synthetic exact 40,000-job manifest validation;
- synthetic 8×5,000 exact shard closure validation;
- builder-compatible `READY.json` validation;
- compact evidence creation and member hash validation;
- Node1 transport tar construction with embedded file-hash manifest;
- verified-prune resume stub preservation;
- static submit dependency, 16×4-core worker, four-sync-shard, bounded-spool,
  `/data` target, archive/file hash-before-prune ordering checks.

No live Slurm submission, real HADDOCK smoke, bxcpu prune, or Node1 write was
performed by local validation. Those actions remain gated by the production
preflight and required SHA/path parameters.
