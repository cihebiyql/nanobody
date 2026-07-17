#!/usr/bin/env bash
set -Eeuo pipefail
umask 022
readonly ROOT=/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_recovery_v2_1_20260716
readonly CONTRACT="$ROOT/RECOVERY_CONTRACT.json"
readonly WORKER="$ROOT/recover_v4g_full_qc_v2.py"
readonly PYTHON=/data1/qlyu/software/envs/vhh-eval/bin/python
readonly EXPECTED_CONTRACT_SHA=24de8e70cb38bc71f78d12d3bca47442662d9ac013b8c5316e671e30f0486790
readonly EXPECTED_WORKER_SHA=e9e63b4c228441089a0174439bb23acc6c5cf58f688772582eb5b48698d0c076
mkdir -p "$ROOT/status" "$ROOT/logs"
exec 9>"$ROOT/status/recovery.lock"
flock -n 9 || { echo 'V4-G recovery v2 already active' >&2; exit 75; }
[[ $(sha256sum "$CONTRACT" | awk '{print $1}') == "$EXPECTED_CONTRACT_SHA" ]]
[[ $(sha256sum "$WORKER" | awk '{print $1}') == "$EXPECTED_WORKER_SHA" ]]
[[ -f "$ROOT/runtime_closure/RUNTIME_MANIFEST.json" ]]
echo $$ >"$ROOT/status/launcher.pid"
trap 'rm -f "$ROOT/status/launcher.pid"' EXIT
exec "$PYTHON" "$WORKER" >>"$ROOT/logs/recovery_v2.log" 2>&1
