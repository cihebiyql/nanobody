#!/usr/bin/env bash
set -euo pipefail

PACKAGE_ROOT=/data1/qlyu/projects/pvrig_v2_6_next_inner_experiments_v1_20260719
RUNTIME_ROOT=/data1/qlyu/projects/pvrig_v2_6_b_matched_seeds_runtime_v1_20260719
PYTHON=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
EXPECTED_LAUNCHER_SHA256=0799dda5691280965ea70b7b6da36c542e09f55fbe5b6c51c3a182919ca9b380

actual="$(sha256sum "${PACKAGE_ROOT}/launch_b_matched_seeds_v1.py" | awk '{print $1}')"
[[ "${actual}" == "${EXPECTED_LAUNCHER_SHA256}" ]]
[[ ! -e "${RUNTIME_ROOT}" ]]
exec "${PYTHON}" "${PACKAGE_ROOT}/launch_b_matched_seeds_v1.py" \
  --runtime-root "${RUNTIME_ROOT}" \
  --poll-seconds 10
