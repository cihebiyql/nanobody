#!/usr/bin/env bash
set -euo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_validation_20260712}
INPUT=${INPUT:-$RUN_ROOT/inputs/pvrig_rfantibody_1000.canonical.fasta}
OUT=${OUT:-$RUN_ROOT/qc/cascade}
TOOL=${TOOL:-/data/qlyu/software/vhh_eval_tools/bin/vhh-large-scale-screen}
POSITIVE_CDRS=${POSITIVE_CDRS:-/data/qlyu/software/vhh_eval_tools/references/local_pvrig_positive_vhh_cdrs.csv}
MAX_LOAD1=${MAX_LOAD1:-64}
LOG_DIR=$RUN_ROOT/logs
PID_FILE=$RUN_ROOT/manifests/sequence_qc.pid
LOG_FILE=$LOG_DIR/sequence_qc.log

mkdir -p "$RUN_ROOT"/{inputs,config,manifests,scripts,qc,logs}

for path in "$INPUT" "$TOOL" "$POSITIVE_CDRS"; do
  if [[ ! -e "$path" ]]; then
    echo "Required path is missing: $path" >&2
    exit 2
  fi
done

if [[ -s "$PID_FILE" ]]; then
  previous_pid=$(cat "$PID_FILE")
  if kill -0 "$previous_pid" 2>/dev/null; then
    echo "Sequence QC is already running with PID $previous_pid"
    exit 0
  fi
fi

if [[ -f "$OUT/cascade_state.json" ]] && python3 - "$OUT/cascade_state.json" <<'PY'
import json
import sys

state = json.load(open(sys.argv[1]))
raise SystemExit(0 if state.get("stages", {}).get("finalize", {}).get("status") == "complete" else 1)
PY
then
  echo "Sequence QC already completed: $OUT"
  exit 0
fi

load1=$(cut -d' ' -f1 /proc/loadavg)
if ! awk -v load="$load1" -v limit="$MAX_LOAD1" 'BEGIN { exit !(load < limit) }'; then
  echo "Refusing launch: node1 load1=$load1 is not below gate $MAX_LOAD1" >&2
  exit 3
fi

{
  echo "captured_at=$(date -Is)"
  echo "hostname=$(hostname)"
  echo "loadavg=$(cat /proc/loadavg)"
  echo "input=$INPUT"
  sha256sum "$INPUT" "$TOOL" "$POSITIVE_CDRS"
  df -h "$RUN_ROOT" | tail -n 1
  nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader
} > "$RUN_ROOT/manifests/sequence_qc_launch_snapshot.txt"

command=(
  "$TOOL" "$INPUT" -o "$OUT"
  --stage all
  --fast-chunk-size 250
  --chunk-jobs 2
  --full-qc-limit 300
  --full-chunk-size 100
  --full-chunk-jobs 1
  --geometry-pool-size 150
  --geometry-limit 50
  --geometry-cluster-limit 3
  --workers 16
  --tnp-ncores 4
  --identity-cache-size 500000
  --local-positive-cdr-csv "$POSITIVE_CDRS"
)

{
  printf '%q ' "${command[@]}"
  printf '\n'
} > "$RUN_ROOT/manifests/sequence_qc_command.sh"

nohup "${command[@]}" > "$LOG_FILE" 2>&1 < /dev/null &
pid=$!
echo "$pid" > "$PID_FILE"
echo "Started sequence QC: PID=$pid LOG=$LOG_FILE OUT=$OUT"

