#!/usr/bin/env bash
set -Eeuo pipefail

: "${RUN_ROOT:?RUN_ROOT is required}"
: "${RF_RUN_ROOT:?RF_RUN_ROOT is required}"
status_dir="$RUN_ROOT/status"
mkdir -p "$status_dir" "$RUN_ROOT/logs"
exec 9>"$status_dir/controller.lock"
flock -n 9 || { echo "fixed-pose controller already active" >&2; exit 75; }

write_state() {
  python3 - "$status_dir/controller.json" "$1" "${2:-}" <<'PY'
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({'state':sys.argv[2],'message':sys.argv[3],
 'pid':os.getppid(),'updated_at':datetime.now(timezone.utc).isoformat()},indent=2,sort_keys=True)+'\n')
PY
}
on_error() { rc=$?; write_state FAILED "return_code=$rc" || true; exit "$rc"; }
trap on_error ERR

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
    *) write_state WAITING_RFANTIBODY "state=$state"; sleep 60 ;;
  esac
done

run_21_workers() {
  local namespace=$1 task_table=$2 seqs=$3
  local pids=() rc=0
  for gpu in 1 2 3 4 5 6 7; do
    for slot in 0 1 2; do
      RUN_ROOT="$RUN_ROOT" TASK_TABLE="$task_table" NAMESPACE="$namespace" SEQS_PER_POSE="$seqs" \
        bash "$RUN_ROOT/scripts/run_fixed_pose_mpnn_worker.sh" "$gpu" "$slot" \
        >"$RUN_ROOT/logs/${namespace}_gpu_${gpu}_slot_${slot}.log" 2>&1 &
      pids+=("$!")
    done
  done
  for pid in "${pids[@]}"; do wait "$pid" || rc=1; done
  [[ "$rc" -eq 0 ]]
}

write_state SMOKE_3X "21 poses; 7 GPUs x 3 workers; 16 sequences per pose"
run_21_workers smoke_3x "$RUN_ROOT/inputs/fixed_pose_mpnn_smoke21.tsv" 16
python3 - "$RUN_ROOT/smoke_3x" "$RUN_ROOT/inputs/fixed_pose_mpnn_smoke21.tsv" <<'PY'
import csv,glob,re,sys
paths=glob.glob(sys.argv[1]+'/workers/*/outputs/*_dldesign_*.pdb')
if len(paths)!=336: raise SystemExit('smoke output mismatch: {}'.format(len(paths)))
tasks=list(csv.DictReader(open(sys.argv[2]),delimiter='\t'))
expected={row['pose_id'] for row in tasks}; counts={pose_id:0 for pose_id in expected}
pattern=re.compile(r'(.+)_dldesign_(\d+)\.pdb$')
seqs=set()
for p in paths:
    match=pattern.fullmatch(p.rsplit('/',1)[-1])
    if match is None or match.group(1) not in counts: raise SystemExit('unknown smoke output: '+p)
    counts[match.group(1)]+=1
    residues={}; labels={'H1':set(),'H2':set(),'H3':set()}
    target=set()
    for line in open(p,errors='replace'):
        if line.startswith('ATOM') and line[12:16].strip()=='CA':
            if line[21]=='H': residues.setdefault(int(line[22:26]),line[17:20])
            elif line[21]=='T': target.add(line[22:27])
        elif line.startswith('REMARK PDBinfo-LABEL:'):
            parts=line.split()
            if len(parts)>=4 and parts[-1] in labels: labels[parts[-1]].add(int(parts[-2]))
    if not 95<=len(residues)<=160 or len(target)<50: raise SystemExit('bad chains: '+p)
    lengths={name:sum(position in residues for position in positions) for name,positions in labels.items()}
    if not (5<=lengths['H1']<=15 and 3<=lengths['H2']<=15 and 5<=lengths['H3']<=30):
        raise SystemExit('missing or invalid CDR labels {}: {}'.format(lengths,p))
    sequence=tuple(residues[position] for position in sorted(residues))
    sequence_text=''.join(sequence)
    for name,positions in labels.items():
        cdr=''.join(residues[position] for position in sorted(positions) if position in residues)
        if sequence_text.count(cdr)!=1: raise SystemExit('CDR is not unique in H chain {}: {}'.format(name,p))
    seqs.add(sequence)
if set(counts.values())!={16}: raise SystemExit('per-pose smoke count mismatch: {}'.format(counts))
if len(seqs)<250: raise SystemExit('smoke uniqueness too low: {}'.format(len(seqs)))
print('smoke validated outputs={} exact_unique={}'.format(len(paths),len(seqs)))
PY

write_state GENERATING "99 poses; 118800 raw sequence PDBs; 7 GPUs x 3 workers"
run_21_workers generation "$RUN_ROOT/inputs/fixed_pose_mpnn_tasks.tsv" 1200
python3 - "$RUN_ROOT/generation" "$RUN_ROOT/inputs/fixed_pose_mpnn_tasks.tsv" <<'PY'
import csv,glob,re,sys
tasks=list(csv.DictReader(open(sys.argv[2]),delimiter='\t'))
expected={row['pose_id']:int(row['seqs_per_pose']) for row in tasks}; counts={pose_id:0 for pose_id in expected}
pattern=re.compile(r'(.+)_dldesign_(\d+)\.pdb$')
paths=glob.glob(sys.argv[1]+'/workers/*/outputs/*_dldesign_*.pdb')
for path in paths:
    match=pattern.fullmatch(path.rsplit('/',1)[-1])
    if match is None or match.group(1) not in counts: raise SystemExit('unknown main output: '+path)
    counts[match.group(1)]+=1
bad={pose_id:(counts[pose_id],count) for pose_id,count in expected.items() if counts[pose_id]!=count}
if bad: raise SystemExit('per-pose main count mismatch: {}'.format(bad))
if len(paths)!=sum(expected.values()): raise SystemExit('main total mismatch')
print('main per-pose counts validated: poses={} outputs={}'.format(len(expected),len(paths)))
PY
write_state OUTPUTS_COMPLETE "118800 raw sequence PDBs; postprocessing/QC required"
date -Is > "$status_dir/outputs.complete"
write_state POSTPROCESSING "sequence extraction, 11-positive CDR identity gate, exact dedup and balanced freeze"
"/data/qlyu/anaconda3/envs/rfdiffusion2/bin/python" \
  "$RUN_ROOT/scripts/collect_fixed_pose_mpnn_candidates.py" --run-root "$RUN_ROOT" --target 75000 \
  >"$RUN_ROOT/logs/fixed_pose_postprocess.log" 2>&1
terminal=$(python3 - "$RUN_ROOT/data/fixed_pose_freeze_summary.json" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['status'])
PY
)
if [[ "$terminal" == PASS ]]; then
  python3 - "$RUN_ROOT/data/fixed_pose_freeze_summary.json" <<'PY'
import gzip,json,sys
summary=json.load(open(sys.argv[1]))
if summary['raw_output_count']!=118800 or summary['frozen_count']!=75000: raise SystemExit('terminal summary count mismatch')
path=sys.argv[1].rsplit('/',1)[0]+'/fixed_pose_candidates_frozen75k.tsv.gz'
with gzip.open(path,'rt') as handle: rows=sum(1 for _ in handle)-1
if rows!=75000: raise SystemExit('frozen TSV row mismatch: {}'.format(rows))
PY
  write_state COMPLETE "75000 exact-unique fast-QC fixed-pose candidates frozen; ANARCI still required"
  date -Is > "$status_dir/controller.complete"
else
  write_state HOLD "$terminal"
  date -Is > "$status_dir/controller.hold"
fi
trap - ERR
