#!/usr/bin/env bash
set -euo pipefail
ROOT=${1:-/data1/qlyu/model_smoke/pvrig_positive11_structure_affinity_benchmark_20260719}
POSE_DIR="$ROOT/input_poses"
PRODIGY=/data/qlyu/software/bin/prodigy
FOLDX=/data/qlyu/software/foldx/foldx_20261231
mkdir -p "$ROOT/prodigy" "$ROOT/foldx" "$ROOT/logs"

# One interpreter startup, parallel processing inside PRODIGY.
/usr/bin/time -f 'elapsed_seconds=%e max_rss_kb=%M' -o "$ROOT/logs/prodigy.time" \
  "$PRODIGY" "$POSE_DIR" -np 16 --selection A B \
  > "$ROOT/prodigy/prodigy_all.stdout" 2> "$ROOT/prodigy/prodigy_all.stderr"

run_foldx_one() {
  set -euo pipefail
  local pdb=$1 root=$2 foldx=$3
  local base stem wd repaired interaction
  base=$(basename "$pdb"); stem=${base%.pdb}; wd="$root/foldx/$stem"
  mkdir -p "$wd"; cp -f "$pdb" "$wd/$base"; cd "$wd"
  interaction="$wd/Interaction_${stem}_Repair_AC.fxout"
  if [[ -s "$interaction" ]]; then printf '%s\tSKIP_COMPLETE\n' "$stem"; return 0; fi
  /usr/bin/time -f 'repair_elapsed_seconds=%e repair_max_rss_kb=%M' -o repair.time \
    "$foldx" --command=RepairPDB --pdb="$base" --output-dir="$wd" > repair.stdout 2> repair.stderr
  repaired="${stem}_Repair.pdb"
  test -s "$repaired"
  /usr/bin/time -f 'analyse_elapsed_seconds=%e analyse_max_rss_kb=%M' -o analyse.time \
    "$foldx" --command=AnalyseComplex --pdb="$repaired" --analyseComplexChains=A,B --output-dir="$wd" > analyse.stdout 2> analyse.stderr
  test -s "$interaction"
  printf '%s\tSUCCESS\n' "$stem"
}
export -f run_foldx_one
find "$POSE_DIR" -maxdepth 1 -type f -name '*.pdb' -print0 | sort -z | \
  xargs -0 -n1 -P12 bash -euo pipefail -c 'run_foldx_one "$3" "$1" "$2"' _ "$ROOT" "$FOLDX" \
  > "$ROOT/logs/foldx_status.tsv" 2> "$ROOT/logs/foldx_parallel.stderr"

/home/qlyu/anaconda3/bin/python - "$ROOT" <<'PY'
import json,sys,time
from pathlib import Path
r=Path(sys.argv[1])
poses=list((r/'input_poses').glob('*.pdb'))
ints=list((r/'foldx').glob('*/Interaction_*_AC.fxout'))
status=(r/'logs'/'foldx_status.tsv').read_text().splitlines() if (r/'logs'/'foldx_status.tsv').exists() else []
receipt={
 'created_epoch':time.time(),'pose_count':len(poses),'foldx_interaction_count':len(ints),
 'foldx_success_lines':sum(x.endswith(('SUCCESS','SKIP_COMPLETE')) for x in status),
 'prodigy_stdout_bytes':(r/'prodigy'/'prodigy_all.stdout').stat().st_size,
 'status':'PASS' if len(poses)==len(ints)==99 else 'FAIL',
 'boundary':'structure scoring benchmark; not measured Kd'}
(r/'RUN_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
PY
