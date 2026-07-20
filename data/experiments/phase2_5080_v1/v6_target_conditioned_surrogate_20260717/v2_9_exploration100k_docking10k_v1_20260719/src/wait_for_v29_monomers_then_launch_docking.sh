#!/usr/bin/env bash
set -euo pipefail
STRUCTURE_ROOT=/data1/qlyu/projects/pvrig_v2_9_monomers10k_v1_20260720
COMPLETE="$STRUCTURE_ROOT/full10k/status/COMPLETE.json"
LOG="$STRUCTURE_ROOT/logs/full_docking_waiter.log"
PY=/data/qlyu/anaconda3/envs/haddock3/bin/python
STAGER="$STRUCTURE_ROOT/src/stage_and_launch_v29_full_docking_v1.py"
while [[ ! -s "$COMPLETE" ]]; do
  printf '%s waiting_for_monomer_complete\n' "$(date -Is)" >> "$LOG"
  sleep 60
done
printf '%s monomer_complete_detected\n' "$(date -Is)" >> "$LOG"
"$PY" "$STAGER" >> "$LOG" 2>&1
printf '%s full_docking_launched\n' "$(date -Is)" >> "$LOG"
