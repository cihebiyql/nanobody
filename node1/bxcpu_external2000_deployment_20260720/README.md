# bxcpu external2000 deployment

This overlay runs the frozen `external_ready_now_jobs.tsv` only. It never selects
the 186 jobs that remain owned by node21. It also supplies the verified V29
`reference_normalization_summary.json` required by `score_pose.py`: the supplied
v2 archive omits that file, while the summary and normalized reference PDB hashes
match `pvrig_v29_external2000_sequences_v3_20260720`.

One Slurm task runs one docking job with the frozen four-core configuration and a
16 GiB memory request. Intermediate files use node-local scratch and are
published by `run_job.py` into the shared project root.

`bxcpu` home is GPFS and unpacking a full Conda environment there is metadata-bound.
The supported deployment is therefore the verified portable cache in
`$HOME/.local/opt`, expanded once per Slurm worker in node-local scratch. Each
worker processes eight safe jobs serially by default; this avoids any direct
workload on the login nodes. The worker sets `PYTHONNOUSERSITE=1`, so it cannot
accidentally import packages from the login account instead of the validated runtime.

The cached HADDOCK runtime is the original 2025.11.0 environment plus a separately
hashed NumPy 2.0.1 overlay. The original NumPy 2.4.0 wheel requires glibc 2.27,
whereas the overlay is `manylinux_2_17`; it is placed first on `PYTHONPATH` for
each worker without modifying the immutable cached runtime.

Validate the portable cache:

```bash
./preflight_portable_bxcpu.sh
```

Submit one safe smoke job:

```bash
PVRIG_JOB_BATCH_SIZE=1 ./submit_portable_workers.sh 1-1
```

The full-safe subset is `477` workers x `8` jobs, with the default expression
`1-477%32`; it is deliberately not submitted by the deployment procedure.
