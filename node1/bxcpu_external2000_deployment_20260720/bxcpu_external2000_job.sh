#!/usr/bin/env bash
# One safe-now external2000 HADDOCK3 job per Slurm array task.
# The project bundle deliberately excludes the node21-transfer manifest.
set -euo pipefail
umask 027

PROJECT_ROOT="${PVRIG_PROJECT_ROOT:-$HOME/pvrig_v29_external2000_sequences_v2_20260720}"
ENV_ROOT="${PVRIG_HADDOCK_ENV:-$HOME/.local/opt/haddock3-2025.11.0}"
HADDOCK_SOURCE="${PVRIG_HADDOCK_SOURCE:-$HOME/.local/opt/haddock3-source-2025.11.0/src}"
SAFE_MANIFEST="$PROJECT_ROOT/manifests/external_ready_now_jobs.tsv"
ARRAY_INDEX="${SLURM_ARRAY_TASK_ID:-1}"

[[ "$ARRAY_INDEX" =~ ^[1-9][0-9]*$ ]] || { echo "invalid Slurm array index: $ARRAY_INDEX" >&2; exit 64; }
[[ -x "$ENV_ROOT/bin/python" && -x "$ENV_ROOT/bin/haddock3" ]] || {
    echo "missing relocatable HADDOCK3 environment: $ENV_ROOT" >&2
    exit 69
}
[[ -d "$HADDOCK_SOURCE/haddock" ]] || { echo "HADDOCK3 source missing: $HADDOCK_SOURCE" >&2; exit 69; }
[[ -f "$SAFE_MANIFEST" ]] || { echo "safe manifest missing: $SAFE_MANIFEST" >&2; exit 66; }

expected_version='haddock3 - 2025.11.0'
actual_version=$("$ENV_ROOT/bin/haddock3" --version 2>&1 | head -n 1)
[[ "$actual_version" == "$expected_version" ]] || {
    echo "unexpected HADDOCK3 version: $actual_version" >&2
    exit 65
}

job_id=$(sed -n "$((ARRAY_INDEX + 1))p" "$SAFE_MANIFEST" | cut -f1)
[[ -n "$job_id" ]] || {
    echo "array index $ARRAY_INDEX has no job in the 3814-job safe manifest" >&2
    exit 64
}

scratch_base="${SLURM_TMPDIR:-/tmp}/${USER}/pvrig_external2000/${SLURM_JOB_ID:-manual}_${ARRAY_INDEX}"
mkdir -p "$PROJECT_ROOT/logs/slurm" "$scratch_base"

export PVRIG_PROJECT_ROOT="$PROJECT_ROOT"
export PVRIG_LOCAL_SCRATCH_ROOT="$scratch_base"
export HADDOCK3="$ENV_ROOT/bin/haddock3"
export PATH="$ENV_ROOT/bin:$PATH"
export PYTHONPATH="$HADDOCK_SOURCE${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONOPTIMIZE=0

printf 'job_id=%s\nproject_root=%s\nenv_root=%s\nscratch=%s\n' \
    "$job_id" "$PROJECT_ROOT" "$ENV_ROOT" "$PVRIG_LOCAL_SCRATCH_ROOT"
exec "$ENV_ROOT/bin/python" "$PROJECT_ROOT/scripts/run_job.py" "$job_id" --max-attempts 2
