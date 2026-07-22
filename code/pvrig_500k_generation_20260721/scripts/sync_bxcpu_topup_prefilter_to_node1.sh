#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=${ROOT:-/mnt/d/work/抗体/code}
WRAP="$ROOT/pvrig_500k_generation_20260721/scripts/ssh_node1_windows_proxy.sh"
LOCAL="$ROOT/pvrig_500k_generation_20260721/run/pvrig_1m_cpu_topup305705_prefilter_v1_20260722"
REMOTE='$HOME/pvrig_bxcpu_model_runtime_v1_20260721/pvrig1m_cpu_topup305705_v1/aggregated'
NODE1=/data1/qlyu/projects/pvrig_1m_cpu_topup305705_prefilter_v1_20260722
mkdir -p "$LOCAL"
home=$(ssh bxcpu 'printf %s "$HOME"'); REMOTE="$home/${REMOTE#\$HOME/}"
rsync -a --partial --append-verify "bxcpu:$REMOTE/" "$LOCAL/"
(cd "$LOCAL" && sha256sum -c SHA256SUMS)
"$WRAP" node1 "mkdir -p '$NODE1'"
rsync -a --partial --append-verify -e "$WRAP" "$LOCAL/" "node1:$NODE1/"
"$WRAP" node1 "cd '$NODE1' && sha256sum -c SHA256SUMS"
date -Is >"$LOCAL/SYNC_COMPLETE"
