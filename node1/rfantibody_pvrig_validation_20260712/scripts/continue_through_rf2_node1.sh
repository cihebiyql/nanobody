#!/usr/bin/env bash
set -euo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_validation_20260712}
MAX_LOAD1=${MAX_LOAD1:-64}
POLL_SECONDS=${POLL_SECONDS:-60}
MAX_RF2_RETRIES=${MAX_RF2_RETRIES:-2}
LOG=$RUN_ROOT/logs/rf2_controller.log
PID_FILE=$RUN_ROOT/manifests/rf2_controller.pid

mkdir -p "$RUN_ROOT"/{logs,manifests,pose_audit,rf2}
if [[ -s "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "RF2 controller already running pid=$(cat "$PID_FILE")"
  exit 0
fi

(
  echo "RF2_CONTROLLER_START time=$(date -Is)"
  targeted_pid_file=$RUN_ROOT/manifests/rf2_primary_78_qc.pid
  targeted_exit_file=$RUN_ROOT/manifests/rf2_primary_78_qc.exit_code
  targeted_out=$RUN_ROOT/qc/rf2_primary_78_full
  while true; do
    if [[ -s "$targeted_pid_file" ]]; then
      targeted_pid=$(cat "$targeted_pid_file")
      if ! kill -0 "$targeted_pid" 2>/dev/null && [[ -s "$targeted_exit_file" ]]; then
        rc=$(cat "$targeted_exit_file")
        if [[ "$rc" != 0 ]]; then
          echo "RF2_CONTROLLER_FAIL targeted_qc_rc=$rc"
          exit 11
        fi
        if [[ -s "$targeted_out/full_merged.tsv" && -s "$targeted_out/fast_merged.tsv" ]]; then
          break
        fi
      fi
    fi
    echo "RF2_CONTROLLER_WAIT_TARGETED_QC time=$(date -Is)"
    sleep "$POLL_SECONDS"
  done

  python3 "$RUN_ROOT/scripts/merge_qc_pose_for_rf2.py" \
    "$RUN_ROOT/pose_audit/rf2_pre_shortlist_primary.tsv" \
    "$RUN_ROOT/manifests/fr4_terminal_repair_mapping.tsv" \
    "$targeted_out/fast_merged.tsv" \
    "$targeted_out/full_merged.tsv" \
    "$RUN_ROOT/rf2/shortlist"

  python3 "$RUN_ROOT/scripts/prepare_rf2_batch.py" \
    "$RUN_ROOT/rf2/shortlist/rf2_shortlist_final.tsv" \
    "$RUN_ROOT/rf2/batch_10recycle_blind" \
    --gpu-ids 1,2,3,4,6,7

  batch=$RUN_ROOT/rf2/batch_10recycle_blind
  attempt=0
  while true; do
    expected=$(awk 'NR>1{n++} END{print n+0}' "$batch/rf2_input_manifest.tsv")
    complete=$(find "$batch/shards" -type f -name '*_best.pdb' 2>/dev/null | wc -l)
    if [[ "$complete" -eq "$expected" ]]; then
      echo "RF2_CONTROLLER_OUTPUTS_COMPLETE count=$complete"
      break
    fi
    running=0
    for pid_path in "$batch"/shards/gpu_*/rf2.pid; do
      [[ -s "$pid_path" ]] || continue
      pid=$(cat "$pid_path")
      kill -0 "$pid" 2>/dev/null && running=$((running + 1))
    done
    if [[ "$running" -gt 0 ]]; then
      echo "RF2_CONTROLLER_WAIT running_shards=$running outputs=$complete/$expected time=$(date -Is)"
      sleep "$POLL_SECONDS"
      continue
    fi
    if [[ "$attempt" -ge "$MAX_RF2_RETRIES" ]]; then
      echo "RF2_CONTROLLER_FAIL exhausted_retries outputs=$complete/$expected"
      exit 12
    fi
    load1=$(cut -d' ' -f1 /proc/loadavg)
    if ! awk -v load="$load1" -v limit="$MAX_LOAD1" 'BEGIN { exit !(load < limit) }'; then
      echo "RF2_CONTROLLER_WAIT_LOAD load1=$load1 threshold=$MAX_LOAD1 time=$(date -Is)"
      sleep "$POLL_SECONDS"
      continue
    fi
    attempt=$((attempt + 1))
    echo "RF2_CONTROLLER_LAUNCH attempt=$attempt outputs=$complete/$expected time=$(date -Is)"
    MAX_LOAD1="$MAX_LOAD1" bash "$RUN_ROOT/scripts/run_rf2_batch_node1.sh" || true
    sleep "$POLL_SECONDS"
  done

  python3 "$RUN_ROOT/scripts/parse_rf2_outputs.py" \
    "$batch/rf2_input_manifest.tsv" \
    "$RUN_ROOT/manifests/fr4_terminal_repair_mapping.tsv" \
    "$RUN_ROOT/rf2/results" \
    --top-limit 50
  echo "RF2_CONTROLLER_COMPLETE time=$(date -Is)"
) >> "$LOG" 2>&1 < /dev/null &

echo "$!" > "$PID_FILE"
echo "Started RF2 controller pid=$! log=$LOG"

