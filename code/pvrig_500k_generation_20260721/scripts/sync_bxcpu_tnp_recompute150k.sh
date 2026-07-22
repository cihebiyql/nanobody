#!/usr/bin/env bash
set -Eeuo pipefail

BASE=${BASE:-/mnt/d/work/抗体/code/pvrig_500k_generation_20260721}
LOCAL=${LOCAL:-$BASE/run/pvrig_1m_fixed_pose_top150k_tnp_recompute_bxcpu_v2_20260722}
RUNTIME=${RUNTIME:-/publicfs04/fs04-al/home/als001821/pvrig_bxcpu_model_runtime_v1_20260721}
REMOTE=${REMOTE:-$RUNTIME/pvrig1m_fixed_pose_top150k_tnp_recompute_v2_20260722}
NODE1_OUT=${NODE1_OUT:-/data/qlyu/projects/pvrig_1m_fixed_pose_top150k_tnp_recompute_bxcpu_v2_20260722}
SSH1=${SSH1:-/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe}
POLL_SECONDS=${POLL_SECONDS:-60}

mkdir -p "$LOCAL/status"
exec 9>"$LOCAL/status/sync.lock"
flock -n 9 || exit 75
exec >>"$LOCAL/sync.log" 2>&1
printf '%s\n' "$$" > "$LOCAL/status/sync.pid"
trap 'rc=$?; printf "%s\n" "$rc" >"$LOCAL/status/SYNC_FAILED.return_code"; exit "$rc"' ERR
echo "$(date -Is) sync watcher start"

while ! ssh bxcpu "test -s '$REMOTE/aggregate/READY.json'"; do
  sleep "$POLL_SECONDS"
done

for wave in wave_00 wave_01 wave_02 wave_03; do
  mkdir -p "$LOCAL/$wave/tnp_aggregate"
  rsync -a --whole-file --partial \
    "bxcpu:$REMOTE/$wave/tnp_aggregate/" "$LOCAL/$wave/tnp_aggregate/"
  (cd "$LOCAL/$wave/tnp_aggregate" && sha256sum -c SHA256SUMS)
done
mkdir -p "$LOCAL/aggregate"
rsync -a --whole-file --partial "bxcpu:$REMOTE/aggregate/" "$LOCAL/aggregate/"
(cd "$LOCAL/aggregate" && sha256sum -c SHA256SUMS)
python3 - "$LOCAL/aggregate/READY.json" <<'PY'
import json, sys
x = json.load(open(sys.argv[1]))
assert x['records'] == 150000, x
assert x['id_set_exact_match'] is True, x
assert x['technical_na_is_not_negative'] is True, x
PY
date -Is > "$LOCAL/status/LOCAL_HASH_OK"

# Use a sequential tar stream instead of rsync's delta protocol over the
# Windows OpenSSH transport.  The destination is accepted only after Node1
# independently verifies every aggregate checksum.
"$SSH1" node1 "mkdir -p '$NODE1_OUT'"
(cd "$LOCAL" && tar -cf - \
  wave_00/tnp_aggregate wave_01/tnp_aggregate \
  wave_02/tnp_aggregate wave_03/tnp_aggregate aggregate) \
  | "$SSH1" node1 "tar -xf - -C '$NODE1_OUT'"
"$SSH1" node1 "set -e; for wave in wave_00 wave_01 wave_02 wave_03; do (cd '$NODE1_OUT'/\$wave/tnp_aggregate && sha256sum -c SHA256SUMS); done; cd '$NODE1_OUT/aggregate' && sha256sum -c SHA256SUMS"
date -Is > "$LOCAL/status/NODE1_HASH_OK"
"$SSH1" node1 "date -Is > '$NODE1_OUT/COMPLETE'"
date -Is > "$LOCAL/COMPLETE"
python3 - <<'PY'
from pathlib import Path
p = Path('/mnt/d/work/抗体/code/pvrig_500k_generation_20260721/run/pvrig_1m_fixed_pose_top150k_tnp_recompute_bxcpu_v2_20260722/status/SYNC_FAILED.return_code')
if p.exists():
    p.unlink()
PY
echo "$(date -Is) sync watcher complete"

