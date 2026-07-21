#!/usr/bin/env bash
set -Eeuo pipefail

: "${CPU_RUN_ROOT:?CPU_RUN_ROOT is required}"
: "${RF_RUN_ROOT:?RF_RUN_ROOT is required}"
ANARCI_ENV=${ANARCI_ENV:-/data/qlyu/anaconda3/envs/boltz}
NCPU=${NCPU:-20}
POLL_SECONDS=${POLL_SECONDS:-60}
status_dir="$CPU_RUN_ROOT/status"
qc_dir="$CPU_RUN_ROOT/anarci"
input_gz="$CPU_RUN_ROOT/exact_unique/exact_unique_fast_qc_pass.fasta.gz"
input_fasta="$qc_dir/exact_unique_fast_qc_pass.fasta"
output_prefix="$qc_dir/exact_unique_anarci_imgt_v1"
mkdir -p "$status_dir" "$qc_dir" "$CPU_RUN_ROOT/logs"

write_state() {
  python3 - "$status_dir/anarci_controller.json" "$1" "${2:-}" <<'PY'
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    'state':sys.argv[2], 'message':sys.argv[3], 'pid':os.getppid(),
    'updated_at':datetime.now(timezone.utc).isoformat()
},indent=2,sort_keys=True)+'\n')
PY
}
fail_state() { rc=$?; write_state FAILED "return_code=$rc" || true; exit "$rc"; }
trap fail_state ERR

test -s "$input_gz"
test -x "$ANARCI_ENV/bin/python"
test -f "$ANARCI_ENV/bin/ANARCI"
while true; do
  state=$(python3 - "$RF_RUN_ROOT/status/controller.json" <<'PY'
import json,sys
try: print(json.load(open(sys.argv[1])).get('state','UNKNOWN'))
except Exception: print('UNKNOWN')
PY
)
  case "$state" in
    COMPLETE) break ;;
    FAILED) write_state BLOCKED "RFantibody controller failed"; exit 5 ;;
    *) write_state WAITING_RFANTIBODY "state=$state"; sleep "$POLL_SECONDS" ;;
  esac
done

write_state PREPARING "decompressing 286872 exact-unique fast-QC sequences"
gzip -cd "$input_gz" > "$input_fasta.partial"
mv "$input_fasta.partial" "$input_fasta"
write_state RUNNING "ANARCI IMGT ncpu=$NCPU"
export PATH="$ANARCI_ENV/bin:$PATH"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
taskset -c "0-$((NCPU-1))" "$ANARCI_ENV/bin/python" "$ANARCI_ENV/bin/ANARCI" \
  -i "$input_fasta" -o "$output_prefix" --scheme imgt --csv --ncpu "$NCPU" \
  >"$CPU_RUN_ROOT/logs/anarci_imgt_v1.log" 2>&1
test -s "${output_prefix}_H.csv"
(cd "$qc_dir" && sha256sum "$(basename "$input_fasta")" "$(basename "${output_prefix}_H.csv")" > SHA256SUMS)
write_state COMPLETE "ANARCI IMGT output and SHA256SUMS ready"
date -Is > "$status_dir/anarci_controller.complete"
trap - ERR
