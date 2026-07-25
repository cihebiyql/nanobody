#!/usr/bin/env bash
set -Eeuo pipefail

gpu=${1:?gpu id required}
slot=${2:?worker slot required}
: "${RUN_ROOT:?RUN_ROOT is required}"
: "${TASK_TABLE:?TASK_TABLE is required}"
: "${NAMESPACE:?NAMESPACE is required}"
: "${SEQS_PER_POSE:?SEQS_PER_POSE is required}"
RF_ROOT=${RF_ROOT:-/data/qlyu/software/RFantibody}
TEMPERATURE=${TEMPERATURE:-0.2}
worker_root="$RUN_ROOT/$NAMESPACE/workers/gpu_${gpu}_slot_${slot}"
input_dir="$worker_root/inputs"
output_dir="$worker_root/outputs"
status_dir="$worker_root/status"
mkdir -p "$input_dir" "$output_dir" "$status_dir" "$worker_root/work"
exec 9>"$worker_root/run.lock"
flock -n 9 || { echo "worker already active gpu=$gpu slot=$slot" >&2; exit 75; }

python3 - "$RUN_ROOT" "$TASK_TABLE" "$input_dir" "$gpu" "$slot" <<'PY'
import csv,os,sys
from pathlib import Path
root=Path(sys.argv[1]); task_path=Path(sys.argv[2]); dest=Path(sys.argv[3])
gpu,slot=int(sys.argv[4]),int(sys.argv[5])
rows=[r for r in csv.DictReader(task_path.open(),delimiter='\t') if int(r['physical_gpu'])==gpu and int(r['worker_slot'])==slot]
if not rows: raise SystemExit('worker has no tasks')
for row in rows:
    source=root/'inputs'/row['normalized_pose_relpath']
    target=dest/source.name
    if not target.exists(): target.symlink_to(source)
print(len(rows))
PY
python3 - "$TASK_TABLE" "$status_dir/input_manifest.json" "$gpu" "$slot" "$SEQS_PER_POSE" "$TEMPERATURE" "$NAMESPACE" <<'PY'
import csv,hashlib,json,sys
from pathlib import Path
task_path=Path(sys.argv[1]); manifest_path=Path(sys.argv[2]); gpu,slot=int(sys.argv[3]),int(sys.argv[4])
rows=[row for row in csv.DictReader(task_path.open(),delimiter='\t') if int(row['physical_gpu'])==gpu and int(row['worker_slot'])==slot]
payload={
 'task_table_sha256':hashlib.sha256(task_path.read_bytes()).hexdigest(), 'gpu':gpu, 'slot':slot,
 'seqs_per_pose':int(sys.argv[5]), 'temperature':float(sys.argv[6]), 'namespace':sys.argv[7],
 'poses':[{'pose_id':row['pose_id'],'normalized_pose_sha256':row['normalized_pose_sha256']} for row in rows],
}
text=json.dumps(payload,indent=2,sort_keys=True)+'\n'
if manifest_path.exists() and manifest_path.read_text()!=text:
    raise SystemExit('worker input manifest changed; refusing to reuse outputs')
if not manifest_path.exists():
    tmp=manifest_path.with_suffix('.json.partial'); tmp.write_text(text); tmp.replace(manifest_path)
PY
input_count=$(find "$input_dir" -maxdepth 1 -type l -name '*.pdb' | wc -l)
expected=$((input_count * SEQS_PER_POSE))
existing=$(find "$output_dir" -maxdepth 1 -type f -name '*_dldesign_*.pdb' | wc -l)
if [[ "$existing" -eq "$expected" ]]; then
  echo "worker already complete gpu=$gpu slot=$slot outputs=$existing"
  date -Is > "$status_dir/complete"
  exit 0
fi
if [[ "$existing" -ne 0 ]]; then
  echo "partial output requires quarantine gpu=$gpu slot=$slot existing=$existing expected=$expected" >&2
  exit 8
fi
cd "$worker_root/work"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONHASHSEED=0
CUDA_VISIBLE_DEVICES="$gpu" nice -n 10 "$RF_ROOT/bin/rfantibody-env" \
  "$RF_ROOT/scripts/proteinmpnn_interface_design.py" \
  -pdbdir "$input_dir" -outpdbdir "$output_dir" \
  -loop_string H1,H2,H3 -seqs_per_struct "$SEQS_PER_POSE" \
  -temperature "$TEMPERATURE" \
  -checkpoint_path "$RF_ROOT/weights/ProteinMPNN_v48_noise_0.2.pt" \
  -omit_AAs CX -augment_eps 0 \
  -checkpoint_name "$status_dir/mpnn.checkpoint" -deterministic \
  >"$worker_root/mpnn.log" 2>&1
found=$(find "$output_dir" -maxdepth 1 -type f -name '*_dldesign_*.pdb' | wc -l)
[[ "$found" -eq "$expected" ]] || { echo "output mismatch found=$found expected=$expected" >&2; exit 6; }
date -Is > "$status_dir/complete"
