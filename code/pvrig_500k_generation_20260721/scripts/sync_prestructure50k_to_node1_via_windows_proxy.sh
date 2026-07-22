#!/usr/bin/env bash
set -euo pipefail

ROOT=/mnt/d/work/抗体/code
WRAP="$ROOT/pvrig_500k_generation_20260721/scripts/ssh_node1_windows_proxy.sh"
RUN_ROOT="$ROOT/pvrig_500k_generation_20260721/run"
LOG="$RUN_ROOT/pvrig_prestructure50k_node1_sync_v1_20260722.log"

NBB_SRC="$RUN_ROOT/pvrig_prestructure50k_nbb2_bxcpu_v1_20260722"
TNP_SRC="$RUN_ROOT/pvrig_prestructure50k_tnp_bxcpu_v1_20260722"
MULTI_SRC="$RUN_ROOT/pvrig_prestructure50k_multimetric_v1_20260722"

NBB_DST=/data1/qlyu/projects/pvrig_prestructure50k_nbb2_v1_20260722
TNP_DST=/data1/qlyu/projects/pvrig_prestructure50k_tnp_v1_20260722
MULTI_DST=/data1/qlyu/projects/pvrig_prestructure50k_multimetric_v1_20260722

exec >>"$LOG" 2>&1
echo "$(date -Is) sync start"

make_manifest() {
  local src=$1
  python3 - "$src" <<'PY'
import hashlib
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
excluded = {
    "NODE1_TRANSFER_SHA256SUMS",
    "NODE1_TRANSFER_SHA256SUMS.partial",
    "NODE1_SYNC_COMPLETE.json",
    "node1_sync.log",
    "sync.log",
    "monitor.log",
    "watcher.stdout.log",
    "watcher.stderr.log",
    "sync_node1_retry.sh",
}
target = root / "NODE1_TRANSFER_SHA256SUMS"
partial = root / "NODE1_TRANSFER_SHA256SUMS.partial"
paths = sorted(p for p in root.rglob("*") if p.is_file() and p.name not in excluded)
with partial.open("w", encoding="utf-8", newline="\n") as out:
    for path in paths:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        rel = "./" + path.relative_to(root).as_posix()
        out.write(f"{digest.hexdigest()}  {rel}\n")
os.replace(partial, target)
PY
}

sync_one() {
  local src=$1 dst=$2 label=$3
  "$WRAP" node1 "mkdir -p '$dst'"
  rsync -a --partial --append-verify --info=progress2 \
    --exclude 'node1_sync.log' \
    --exclude 'sync.log' \
    --exclude 'monitor.log' \
    --exclude 'watcher.stdout.log' \
    --exclude 'watcher.stderr.log' \
    --exclude 'sync_node1_retry.sh' \
    -e "$WRAP" "$src/" "node1:$dst/"
  "$WRAP" node1 "cd '$dst' && sha256sum -c NODE1_TRANSFER_SHA256SUMS"
  echo "$(date -Is) $label verified"
}

make_manifest "$NBB_SRC"
make_manifest "$TNP_SRC"
make_manifest "$MULTI_SRC"

sync_one "$NBB_SRC" "$NBB_DST" NBB2
sync_one "$TNP_SRC" "$TNP_DST" TNP
sync_one "$MULTI_SRC" "$MULTI_DST" MULTIMETRIC

finished=$(date -Is)
receipt=$(printf '{"status":"COMPLETE","completed_at":"%s","transport":"windows-openssh-proxy","datasets":["NBB2","TNP","MULTIMETRIC"]}\n' "$finished")
printf '%s' "$receipt" > "$MULTI_SRC/NODE1_SYNC_COMPLETE.json"
printf '%s' "$receipt" | "$WRAP" node1 "cat > '$MULTI_DST/NODE1_SYNC_COMPLETE.json.partial' && mv '$MULTI_DST/NODE1_SYNC_COMPLETE.json.partial' '$MULTI_DST/NODE1_SYNC_COMPLETE.json'"
echo "$(date -Is) all node1 transfers complete"
