#!/usr/bin/env bash
set -Eeuo pipefail

: "${PVRIG_PACKAGE:?PVRIG_PACKAGE is required}"
: "${PVRIG_PUBLISH_ROOT:?PVRIG_PUBLISH_ROOT is required}"
node_index=${SLURM_ARRAY_TASK_ID:?SLURM_ARRAY_TASK_ID is required}
workers=${WORKERS_PER_NODE:-64}
python_bin=${PORTABLE_PYTHON:-$HOME/.local/opt/haddock3-2025.11.0/bin/python3.11}
scratch=${TMPDIR:-/tmp}/pvrig500k_cpu_${SLURM_ARRAY_JOB_ID}_${node_index}
mkdir -p "$scratch/package" "$scratch/results" "$PVRIG_PUBLISH_ROOT"
tar -xzf "$PVRIG_PACKAGE" -C "$scratch/package"
package_root=$(find "$scratch/package" -mindepth 1 -maxdepth 1 -type d | head -1)
test -n "$package_root"
node_dir="$package_root/tasks/node_$(printf '%02d' "$node_index")"
test -d "$node_dir"

run_one() {
  task=$1
  base=$(basename "$task" .tsv)
  "$python_bin" "$package_root/scripts/run_cpu_generation_shard.py" \
    --tasks "$task" --inputs "$package_root/inputs" \
    --output-prefix "$scratch/results/$base"
}
export -f run_one
export python_bin package_root scratch
find "$node_dir" -type f -name 'worker_*.tsv' -print0 \
  | xargs -0 -n1 -P "$workers" bash -c 'run_one "$1"' _

raw_count=$(awk 'FNR>1{n++} END{print n+0}' "$scratch"/results/*.raw.tsv)
pass_count=$(awk 'FNR>1{n++} END{print n+0}' "$scratch"/results/*.pass.tsv)
archive="cpu_node_$(printf '%02d' "$node_index").tar.gz"
tar -C "$scratch" -cf - results | gzip -1 > "$scratch/$archive"
(cd "$scratch" && sha256sum "$archive" > "$archive.sha256")
python3 - "$scratch" "$node_index" "$raw_count" "$pass_count" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]); idx=int(sys.argv[2])
(root/'READY.json').write_text(json.dumps({
  'status':'READY', 'node_index':idx, 'raw_count':int(sys.argv[3]),
  'fast_qc_pass_count':int(sys.argv[4]), 'archive':'cpu_node_{:02d}.tar.gz'.format(idx)
},indent=2,sort_keys=True)+'\n')
PY

publish_tmp="$PVRIG_PUBLISH_ROOT/.node_$(printf '%02d' "$node_index").${SLURM_JOB_ID}.tmp"
publish_final="$PVRIG_PUBLISH_ROOT/node_$(printf '%02d' "$node_index")"
if [[ -e "$publish_final" ]]; then
  echo "refusing to overwrite existing publication: $publish_final" >&2
  exit 20
fi
mkdir -p "$publish_tmp"
cp "$scratch/$archive" "$scratch/$archive.sha256" "$scratch/READY.json" "$publish_tmp/"
mv -T "$publish_tmp" "$publish_final"
