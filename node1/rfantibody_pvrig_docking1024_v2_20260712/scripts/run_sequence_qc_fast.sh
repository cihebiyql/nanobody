#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712}
INPUT=${INPUT:-$RUN_ROOT/data/candidates.fasta}
OUT=${OUT:-$RUN_ROOT/qc/candidate_fast}
TOOL=${TOOL:-/data/qlyu/software/vhh_eval_tools/bin/vhh-large-scale-screen}
POSITIVE_CDRS=${POSITIVE_CDRS:-/data/qlyu/software/vhh_eval_tools/references/local_pvrig_positive_vhh_cdrs.csv}
MAX_LOAD1=${MAX_LOAD1:-64}
POLL_SECONDS=${POLL_SECONDS:-60}

for path in "$INPUT" "$TOOL" "$POSITIVE_CDRS"; do
  [[ -e "$path" ]] || { echo "Missing QC input: $path" >&2; exit 2; }
done
mkdir -p "$RUN_ROOT"/{qc,logs,status,data}

if [[ -s "$OUT/fast_merged.tsv" ]] && python3 - "$OUT/fast_merged.tsv" <<'PY'
import csv
import sys
rows = list(csv.DictReader(open(sys.argv[1], newline=""), delimiter="\t"))
raise SystemExit(0 if len(rows) == 1024 and len({row["candidate_id"] for row in rows}) == 1024 else 1)
PY
then
  cp "$OUT/fast_merged.tsv" "$RUN_ROOT/data/sequence_qc.tsv"
  echo "Sequence QC already complete"
  exit 0
fi

if [[ -e "$OUT" ]]; then
  echo "Refusing to overwrite incomplete QC directory: $OUT" >&2
  exit 3
fi
while true; do
  load1=$(cut -d' ' -f1 /proc/loadavg)
  if awk -v load="$load1" -v limit="$MAX_LOAD1" 'BEGIN { exit !(load < limit) }'; then
    break
  fi
  echo "QC_LOAD_WAIT load1=$load1 threshold=$MAX_LOAD1 time=$(date -Is)"
  sleep "$POLL_SECONDS"
done

"$TOOL" "$INPUT" -o "$OUT" \
  --stage fast \
  --fast-chunk-size 256 \
  --chunk-jobs 2 \
  --workers 8 \
  --identity-cache-size 500000 \
  --local-positive-cdr-csv "$POSITIVE_CDRS" \
  >"$RUN_ROOT/logs/sequence_qc_fast.log" 2>&1

python3 - "$OUT/fast_merged.tsv" <<'PY'
import csv
import sys
rows = list(csv.DictReader(open(sys.argv[1], newline=""), delimiter="\t"))
if len(rows) != 1024 or len({row["candidate_id"] for row in rows}) != 1024:
    raise SystemExit(f"QC output identity mismatch: rows={len(rows)} unique={len({row['candidate_id'] for row in rows})}")
PY
cp "$OUT/fast_merged.tsv" "$RUN_ROOT/data/sequence_qc.tsv"
date -Is > "$RUN_ROOT/status/sequence_qc_fast.complete"
