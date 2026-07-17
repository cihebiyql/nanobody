#!/usr/bin/env bash
set -Eeuo pipefail
umask 022
readonly ROOT=/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_recovery_v2_20260716
readonly CONTRACT="$ROOT/RECOVERY_CONTRACT.json"
readonly WORKER="$ROOT/recover_v4g_full_qc_v2.py"
readonly PYTHON=/data1/qlyu/software/envs/vhh-eval/bin/python
readonly EXPECTED_CONTRACT_SHA=8ad2affedc88ef4a1b3e0c1e57242dc08b9d119cd62a83dd6c6d1c5b220ce0ce
readonly EXPECTED_WORKER_SHA=2f1afa009f232f40f846d7a7938a93d794106375f673054e6e202ad54db9ef75
mkdir -p "$ROOT/status" "$ROOT/logs"
exec 9>"$ROOT/status/recovery.lock"
flock -n 9 || { echo 'V4-G recovery v2 already active' >&2; exit 75; }
[[ $(sha256sum "$CONTRACT" | awk '{print $1}') == "$EXPECTED_CONTRACT_SHA" ]]
[[ $(sha256sum "$WORKER" | awk '{print $1}') == "$EXPECTED_WORKER_SHA" ]]
[[ -f "$ROOT/runtime_closure/RUNTIME_MANIFEST.json" ]]
echo $$ >"$ROOT/status/launcher.pid"
trap 'rm -f "$ROOT/status/launcher.pid"' EXIT
exec "$PYTHON" "$WORKER" >>"$ROOT/logs/recovery_v2.log" 2>&1
