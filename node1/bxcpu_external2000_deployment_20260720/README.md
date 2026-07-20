# bxcpu external2000 deployment

This overlay runs the frozen `external_ready_now_jobs.tsv` only. It never selects
the 186 jobs that remain owned by node21.

The environment path is `$HOME/.local/opt/haddock3-2025.11.0`; the corresponding
HADDOCK source path is `$HOME/.local/opt/haddock3-source-2025.11.0/src`. Together
they must report `haddock3 - 2025.11.0`. One Slurm task runs one docking job with the frozen
four-core configuration and a 16 GiB memory request. Intermediate files use
node-local scratch and are published by `run_job.py` into the shared project root.

`bxcpu` home is GPFS and unpacking a full Conda environment there is metadata-bound.
The supported deployment is therefore the verified portable cache in
`$HOME/.local/opt`, expanded once per Slurm worker in node-local scratch. Each worker
processes eight safe jobs serially by default; this avoids any direct workload on the
login nodes.

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
