#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
MODE="${1:-}"
if [[ -z "$MODE" ]]; then
  echo "usage: $0 prepare|materialize [adapter arguments...]" >&2
  exit 2
fi
shift

case "$MODE" in
  prepare)
    exec "$PYTHON_BIN" "$HERE/src/build_canonical10644_label_free_graph_v1.py" \
      --mode prepare --contract "$HERE/INPUT_CONTRACT.json" "$@"
    ;;
  materialize)
    if [[ "${PVRIG_ALLOW_CANONICAL10644_GRAPH_MATERIALIZATION:-}" != "1" ]]; then
      echo "materialization blocked: export PVRIG_ALLOW_CANONICAL10644_GRAPH_MATERIALIZATION=1" >&2
      exit 3
    fi
    # Avoid competing with the current C2 32-CPU workload.  The reused graph
    # builder is single-process; BLAS/OpenMP are explicitly capped to one thread.
    export OMP_NUM_THREADS=1
    export MKL_NUM_THREADS=1
    export OPENBLAS_NUM_THREADS=1
    exec "$PYTHON_BIN" "$HERE/src/build_canonical10644_label_free_graph_v1.py" \
      --mode materialize --allow-high-load-materialization \
      --contract "$HERE/INPUT_CONTRACT.json" "$@"
    ;;
  *)
    echo "unknown mode: $MODE" >&2
    exit 2
    ;;
esac
