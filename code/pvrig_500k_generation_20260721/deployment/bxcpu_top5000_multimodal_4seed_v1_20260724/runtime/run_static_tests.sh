#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")" && pwd)
PYCACHE=$(mktemp -d "${TMPDIR:-/tmp}/pvrig-top5000-pycache.XXXXXX")
trap 'rm -rf "$PYCACHE"' EXIT

export PYTHONPYCACHEPREFIX="$PYCACHE"
python3 -m py_compile \
    "$ROOT/runtime_contract.py" \
    "$ROOT/compact_run_evidence.py" \
    "$ROOT/prune_bxcpu_payload.py" \
    "$ROOT/sync_top5000_results_incremental.py" \
    "$ROOT/test_runtime_slice.py"
for script in "$ROOT"/*.sh; do
    bash -n "$script"
done
python3 "$ROOT/test_runtime_slice.py"
