#!/usr/bin/env bash
set -euo pipefail

# Node1 convenience wrapper. MODE=seq emits a generic binding prior;
# MODE=affi emits the upstream reference-anchored affinity interval.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${NANOBIND_PYTHON:-/data/qlyu/anaconda3/envs/deepnano/bin/python}"
MODE="${MODE:-seq}"
GPU="${GPU:-1}"
NB_FASTA="${1:?nanobody FASTA is required}"
AG_FASTA="${2:?antigen FASTA is required}"
OUTPUT="${3:?output CSV is required}"

case "$MODE" in
  seq) SCRIPT="predict_seq.py" ;;
  affi) SCRIPT="predict_affi.py" ;;
  *) echo "Unsupported MODE=$MODE (expected seq or affi)" >&2; exit 2 ;;
esac

mkdir -p "$(dirname "$OUTPUT")"
cd "$ROOT"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1
CUDA_VISIBLE_DEVICES="$GPU" "$PY" "$SCRIPT" \
  --nb "$NB_FASTA" --ag "$AG_FASTA" --output "$OUTPUT"
