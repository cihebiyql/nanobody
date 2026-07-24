#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
  pwd -P
)"
cd -- "$SCRIPT_DIR"

python3 -m py_compile \
  build_top5000_unstarted_seed42_3047_two_node_handoff_v1.py \
  test_build_top5000_unstarted_seed42_3047_two_node_handoff_v1.py
python3 -m unittest -v \
  test_build_top5000_unstarted_seed42_3047_two_node_handoff_v1.py
