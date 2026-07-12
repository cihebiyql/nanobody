#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_1000_20260712}

printf 'time\t%s\n' "$(date -Is)"
printf 'set\tpid\talive\tbackbones\tsequences\tcomplete\n'
for set_id in A B C D; do
  set_dir="$RUN_ROOT/sets/set_$set_id"
  pid='-'
  alive=no
  if [[ -s "$set_dir/status/launcher_pid" ]]; then
    pid=$(cat "$set_dir/status/launcher_pid")
    if kill -0 "$pid" 2>/dev/null; then alive=yes; fi
  fi
  backbones=0
  sequences=0
  if [[ -d "$set_dir/backbones" ]]; then
    backbones=$(find "$set_dir/backbones" -maxdepth 1 -type f -name 'design_*.pdb' | wc -l)
  fi
  if [[ -d "$set_dir/sequences" ]]; then
    sequences=$(find "$set_dir/sequences" -maxdepth 1 -type f -name 'design_*_dldesign_*.pdb' | wc -l)
  fi
  complete=no
  [[ -s "$set_dir/complete.json" ]] && complete=yes
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$set_id" "$pid" "$alive" "$backbones" "$sequences" "$complete"
done

nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu \
  --format=csv,noheader,nounits
