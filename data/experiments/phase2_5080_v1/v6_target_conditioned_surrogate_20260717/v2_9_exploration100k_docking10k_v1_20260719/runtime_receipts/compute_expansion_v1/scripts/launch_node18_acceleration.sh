#!/usr/bin/env bash
set -euo pipefail
ROOT=/data/qlyu/projects/pvrig_v29_docking25k_v1_20260720
SCRATCH=/tmp/pvrig_v29_docking25k_node18
mkdir -p "$SCRATCH"
tail -n +2 "$ROOT/manifests/node18_acceleration_jobs.tsv" | cut -f1 | xargs -r -I{} -P4 sh -c 'PVRIG_PROJECT_ROOT="$2" PVRIG_LOCAL_SCRATCH_ROOT="$3" HADDOCK3=/data/qlyu/anaconda3/envs/haddock3/bin/haddock3 /data/qlyu/anaconda3/envs/haddock3/bin/python "$2/scripts/run_job.py" "$1" --max-attempts 2' _ {} "$ROOT" "$SCRATCH"
