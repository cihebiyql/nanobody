#!/usr/bin/env bash
set -euo pipefail
export PATH="/data1/qlyu/anaconda3/envs/boltz/bin:${PATH}"
exec /data1/qlyu/anaconda3/envs/boltz/bin/python3.11 \
  /data1/qlyu/projects/pvrig_v4_h_research_pool_v1_20260717/scripts/NanoBodyBuilder2_openmm_threads_compat.py \
  "$@"
