#!/usr/bin/env bash
set -Eeuo pipefail

: "${CPU_RUN_ROOT:?CPU_RUN_ROOT is required}"
: "${RF_RUN_ROOT:?RF_RUN_ROOT is required}"
: "${FIXED_POSE_RUN_ROOT:?FIXED_POSE_RUN_ROOT is required}"
ANARCI_ENV=${ANARCI_ENV:-/data/qlyu/anaconda3/envs/boltz}
NCPU=${NCPU:-20}
POLL_SECONDS=${POLL_SECONDS:-60}
status_dir="$CPU_RUN_ROOT/status"
qc_dir="$CPU_RUN_ROOT/anarci"
cpu_input_gz="$CPU_RUN_ROOT/combined_cpu_control_exact_unique/combined_exact_unique_fast_qc_pass.fasta.gz"
rf_input_fasta="$RF_RUN_ROOT/data/candidates.fasta"
fixed_input_gz="$FIXED_POSE_RUN_ROOT/data/fixed_pose_candidates_frozen75k.fasta.gz"
input_fasta="$qc_dir/all_routes_pre_anarci.fasta"
output_prefix="$qc_dir/all_routes_anarci_imgt_v1"
mkdir -p "$status_dir" "$qc_dir" "$CPU_RUN_ROOT/logs"
if [[ ! "$NCPU" =~ ^[1-9][0-9]*$ ]] || (( NCPU > $(nproc) )); then
  echo "NCPU must be between 1 and $(nproc)" >&2
  exit 2
fi
exec 9>"$status_dir/anarci_controller.lock"
flock -n 9 || { echo "ANARCI controller already active" >&2; exit 75; }

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

test -s "$cpu_input_gz"
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

while true; do
  fixed_state=$(python3 - "$FIXED_POSE_RUN_ROOT/status/controller.json" <<'PY'
import json,sys
try: print(json.load(open(sys.argv[1])).get('state','UNKNOWN'))
except Exception: print('UNKNOWN')
PY
)
  case "$fixed_state" in
    COMPLETE|HOLD|FAILED|BLOCKED) break ;;
    *) write_state WAITING_FIXED_POSE_MPNN "state=$fixed_state"; sleep "$POLL_SECONDS" ;;
  esac
done

test -s "$rf_input_fasta"
write_state PREPARING "combining CPU/control, RFantibody and available fixed-pose candidates"
gzip -cd "$cpu_input_gz" > "$input_fasta.partial"
cat "$rf_input_fasta" >> "$input_fasta.partial"
if [[ "$fixed_state" == COMPLETE ]]; then
  test -s "$fixed_input_gz"
  gzip -cd "$fixed_input_gz" >> "$input_fasta.partial"
fi
mv "$input_fasta.partial" "$input_fasta"
candidate_count=$(grep -c '^>' "$input_fasta")
python3 - "$input_fasta" "$cpu_input_gz" "$rf_input_fasta" "$fixed_input_gz" "$fixed_state" "$qc_dir/ANARCI_INPUT.json" "$candidate_count" <<'PY'
import hashlib,json,sys
from pathlib import Path
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()
combined,cpu,rf,fixed=map(Path,sys.argv[1:5]); fixed_state=sys.argv[5]; out=Path(sys.argv[6]); count=int(sys.argv[7])
sources={str(cpu):sha(cpu),str(rf):sha(rf)}
if fixed_state=='COMPLETE': sources[str(fixed)]=sha(fixed)
out.write_text(json.dumps({'status':'READY','candidate_records':count,'fixed_pose_state':fixed_state,
 'sources_sha256':sources,'combined_fasta':str(combined),'combined_fasta_sha256':sha(combined)},indent=2,sort_keys=True)+'\n')
PY
write_state RUNNING "ANARCI IMGT ncpu=$NCPU candidates=$candidate_count fixed_pose_state=$fixed_state"
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
