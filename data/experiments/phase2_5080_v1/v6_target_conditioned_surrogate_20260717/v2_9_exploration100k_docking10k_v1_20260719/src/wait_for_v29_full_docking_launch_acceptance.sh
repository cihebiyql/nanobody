#!/usr/bin/env bash
set -euo pipefail
ROOT=/data/qlyu/projects/pvrig_v29_docking25k_v1_20260720
MONOMER_ROOT=/data1/qlyu/projects/pvrig_v2_9_monomers10k_v1_20260720
VERIFY="$MONOMER_ROOT/src/verify_v29_full_docking_launch_v1.py"
PY=/data/qlyu/anaconda3/envs/haddock3/bin/python
LOG="$MONOMER_ROOT/logs/full_docking_launch_acceptance_waiter.log"

while [[ ! -s "$ROOT/status/LAUNCHED.json" ]]; do
  printf '%s waiting_for_full_docking_launch\n' "$(date -Is)" >> "$LOG"
  sleep 60
done

while true; do
  set +e
  "$PY" "$VERIFY" --root "$ROOT" --require-first-status >> "$LOG" 2>&1
  rc=$?
  set -e
  if [[ $rc -eq 0 ]]; then
    printf '%s launch_acceptance_passed\n' "$(date -Is)" >> "$LOG"
    exit 0
  fi
  if [[ $rc -ne 3 ]]; then
    printf '%s launch_acceptance_failed_rc_%s\n' "$(date -Is)" "$rc" >> "$LOG"
    exit "$rc"
  fi
  sleep 30
done
