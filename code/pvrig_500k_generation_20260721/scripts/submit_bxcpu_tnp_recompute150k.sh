#!/usr/bin/env bash
set -Eeuo pipefail

BASE=${BASE:-/mnt/d/work/抗体/code/pvrig_500k_generation_20260721}
NBB2_LOCAL=${NBB2_LOCAL:-$BASE/run/pvrig_1m_fixed_pose_top150k_nbb2_batched_v1_20260722}
SELECTION_ROOT=${SELECTION_ROOT:-$BASE/run/pvrig_1m_fixed_pose_top150k_structure_input_v1_20260722}
LOCAL=${LOCAL:-$BASE/run/pvrig_1m_fixed_pose_top150k_tnp_recompute_bxcpu_v2_20260722}
RUNTIME=${RUNTIME:-/publicfs04/fs04-al/home/als001821/pvrig_bxcpu_model_runtime_v1_20260721}
NBB2_REMOTE=${NBB2_REMOTE:-$RUNTIME/pvrig1m_fixed_pose_top150k_nbb2_batched_v1_20260722}
REMOTE=${REMOTE:-$RUNTIME/pvrig1m_fixed_pose_top150k_tnp_recompute_v2_20260722}

mkdir -p "$LOCAL"
exec 9>"$LOCAL/submit.lock"
flock -n 9 || exit 75
exec >>"$LOCAL/controller.log" 2>&1
printf '%s\n' "$$" >"$LOCAL/controller.pid"
trap 'rc=$?; printf "%s\n" "$rc" >"$LOCAL/FAILED.return_code"; exit "$rc"' ERR
echo "$(date -Is) recompute controller start"

test -s "$NBB2_LOCAL/NBB2_ALL_WAVES_COMPLETE.json"
test -s "$SELECTION_ROOT/fixed_pose_top150k_for_structure.tsv.gz"

rsync -a \
  "$BASE/scripts/run_bxcpu_nbb2_ephemeral_for_tnp.slurm" \
  "$BASE/scripts/run_bxcpu_tnp_generic.slurm" \
  "$BASE/scripts/nbb2_predict_worker.py" \
  "$BASE/scripts/run_bxcpu_tnp_prestructure50k.py" \
  "$BASE/scripts/aggregate_bxcpu_tnp_generic.py" \
  "$BASE/scripts/aggregate_tnp_fixed_pose150k.py" \
  "$BASE/scripts/cleanup_bxcpu_tnp_recompute.py" \
  "bxcpu:$RUNTIME/scripts/"
ssh bxcpu "mkdir -p '$REMOTE'"
rsync -a "$SELECTION_ROOT/fixed_pose_top150k_for_structure.tsv.gz" \
  "bxcpu:$REMOTE/fixed_pose_top150k_for_structure.tsv.gz"

make_wave_selection() {
  local wave=$1 output=$2
  python3 - "$SELECTION_ROOT/fixed_pose_top150k_for_structure.tsv.gz" \
    "$NBB2_LOCAL/$wave/input" "$output" <<'PY'
import csv, gzip, sys
from pathlib import Path

selection, fasta_dir, output = map(Path, sys.argv[1:])
wanted = set()
for fasta in sorted(fasta_dir.glob('task_*.fasta')):
    with fasta.open() as handle:
        wanted.update(line[1:].strip().split()[0] for line in handle if line.startswith('>'))
with gzip.open(selection, 'rt', newline='') as src, gzip.open(output, 'wt', newline='') as dst:
    reader = csv.DictReader(src, delimiter='\t')
    writer = csv.DictWriter(dst, fieldnames=reader.fieldnames, delimiter='\t', lineterminator='\n')
    writer.writeheader()
    observed = set()
    for row in reader:
        if row['candidate_id'] in wanted:
            writer.writerow(row)
            observed.add(row['candidate_id'])
if observed != wanted:
    raise SystemExit(f'wave selection mismatch wanted={len(wanted)} observed={len(observed)}')
PY
}

wait_job() {
  local job=$1 label=$2 states
  while ssh bxcpu "squeue -h -j '$job' | grep -q ."; do
    echo "$(date -Is) waiting $label job=$job"
    sleep 30
  done
  states=$(ssh bxcpu "sacct -X -j '$job' -n -P -o State" \
    | sed '/^$/d' | sed 's/+.*$//' | sort -u)
  [[ "$states" == "COMPLETED" ]]
}

submit_retry() {
  local label=$1 output rc
  shift
  while true; do
    set +e
    output=$(ssh bxcpu "$*" 2>>"$LOCAL/controller.log")
    rc=$?
    set -e
    if [[ "$rc" -eq 0 && "$output" =~ ^[0-9]+([_;].*)?$ ]]; then
      printf '%s\n' "${output%%[_;]*}"
      return 0
    fi
    echo "$(date -Is) scheduler retry label=$label rc=$rc output=$output"
    sleep 30
  done
}

for wi in 0 1 2 3; do
  wave=$(printf 'wave_%02d' "$wi")
  records=40000
  [[ "$wi" -eq 3 ]] && records=30000
  campaign="$NBB2_REMOTE/$wave"
  wave_remote="$REMOTE/$wave"
  selection="$wave_remote/selection.tsv.gz"
  mkdir -p "$LOCAL/$wave"
  local_selection="$LOCAL/$wave/selection.tsv.gz"
  [[ -s "$local_selection" ]] || make_wave_selection "$wave" "$local_selection"
  ssh bxcpu "mkdir -p '$wave_remote/logs' '$wave_remote/tnp_aggregate'"
  rsync -a "$local_selection" "bxcpu:$selection"

  if [[ -s "$LOCAL/$wave/NBB2_JOB_ID" ]]; then
    NBB2_JOB=$(cat "$LOCAL/$wave/NBB2_JOB_ID")
  else
    NBB2_JOB=$(submit_retry "${wave}_NBB2" "sbatch --parsable --array=0-7%8 \
      --output='$wave_remote/logs/nbb2-%A_%a.out' \
      --error='$wave_remote/logs/nbb2-%A_%a.err' \
      --export=ALL,RUNTIME_ROOT='$RUNTIME',CAMPAIGN_ROOT='$campaign',ENV_ROOT='$RUNTIME/env' \
      '$RUNTIME/scripts/run_bxcpu_nbb2_ephemeral_for_tnp.slurm'")
    printf '%s\n' "$NBB2_JOB" >"$LOCAL/$wave/NBB2_JOB_ID"
  fi
  wait_job "$NBB2_JOB" "${wave}_NBB2"

  if [[ -s "$LOCAL/$wave/TNP_JOB_ID" ]]; then
    TNP_JOB=$(cat "$LOCAL/$wave/TNP_JOB_ID")
  else
    TNP_JOB=$(submit_retry "${wave}_TNP" "sbatch --parsable --array=0-7%8 \
      --output='$wave_remote/logs/tnp-%A_%a.scheduler.out' \
      --error='$wave_remote/logs/tnp-%A_%a.scheduler.err' \
      --export=ALL,RUNTIME_ROOT='$RUNTIME',CAMPAIGN_ROOT='$campaign',NBB2_JOB_ID='$NBB2_JOB',SELECTION='$selection' \
      '$RUNTIME/scripts/run_bxcpu_tnp_generic.slurm'")
    printf '%s\n' "$TNP_JOB" >"$LOCAL/$wave/TNP_JOB_ID"
  fi
  wait_job "$TNP_JOB" "${wave}_TNP"

  if ! ssh bxcpu "test -s '$wave_remote/tnp_aggregate/READY.json'"; then
    ssh bxcpu "'$RUNTIME/env/bin/python' '$RUNTIME/scripts/aggregate_bxcpu_tnp_generic.py' \
      --input-dir '$campaign/tnp_results_$TNP_JOB' --selection '$selection' \
      --output-dir '$wave_remote/tnp_aggregate' --expected '$records' --shards 8"
  fi
  ssh bxcpu "'$RUNTIME/env/bin/python' '$RUNTIME/scripts/cleanup_bxcpu_tnp_recompute.py' \
    --campaign '$campaign' --nbb2-job-id '$NBB2_JOB' --tnp-job-id '$TNP_JOB' \
    --aggregate '$wave_remote/tnp_aggregate' --expected '$records'"
  date -Is >"$LOCAL/$wave/COMPLETE"
  echo "$(date -Is) $wave complete NBB2=$NBB2_JOB TNP=$TNP_JOB"
done

if ! ssh bxcpu "test -s '$REMOTE/aggregate/READY.json'"; then
  ssh bxcpu "'$RUNTIME/env/bin/python' '$RUNTIME/scripts/aggregate_tnp_fixed_pose150k.py' \
    --input-root '$REMOTE' --selection '$REMOTE/fixed_pose_top150k_for_structure.tsv.gz' \
    --output-dir '$REMOTE/aggregate' --expected 150000"
fi
date -Is >"$LOCAL/REMOTE_COMPUTE_COMPLETE"
python3 - <<'PY'
from pathlib import Path
p = Path('/mnt/d/work/抗体/code/pvrig_500k_generation_20260721/run/pvrig_1m_fixed_pose_top150k_tnp_recompute_bxcpu_v2_20260722/FAILED.return_code')
if p.exists():
    p.unlink()
PY
echo "$(date -Is) recompute controller complete"
