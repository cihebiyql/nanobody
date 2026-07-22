#!/usr/bin/env bash
set -Eeuo pipefail

BASE=${BASE:-/mnt/d/work/抗体/code/pvrig_500k_generation_20260721}
NBB2_LOCAL=${NBB2_LOCAL:-$BASE/run/pvrig_1m_fixed_pose_top150k_nbb2_batched_v1_20260722}
SELECTION_ROOT=${SELECTION_ROOT:-$BASE/run/pvrig_1m_fixed_pose_top150k_structure_input_v1_20260722}
SELECTION=${SELECTION:-$SELECTION_ROOT/fixed_pose_top150k_for_structure.tsv.gz}
LOCAL=${LOCAL:-$BASE/run/pvrig_1m_fixed_pose_top150k_tnp_bxcpu_v1_20260722}
RUNTIME=${RUNTIME:-/publicfs04/fs04-al/home/als001821/pvrig_bxcpu_model_runtime_v1_20260721}
REMOTE=${REMOTE:-$RUNTIME/pvrig1m_fixed_pose_top150k_tnp_v1_20260722}
NODE1_NBB2=${NODE1_NBB2:-/data/qlyu/projects/pvrig_1m_fixed_pose_top150k_nbb2_batched_v1_20260722}
NODE1_OUT=${NODE1_OUT:-/data/qlyu/projects/pvrig_1m_fixed_pose_top150k_tnp_bxcpu_v1_20260722}
SSH1=${SSH1:-/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe}
POLL_SECONDS=${POLL_SECONDS:-30}
LOCK_DIR=${LOCK_DIR:-$BASE/run/.locks}

mkdir -p "$LOCAL" "$LOCAL/staging" "$LOCAL/status" "$LOCK_DIR"
exec 9>"$LOCK_DIR/pvrig_fixed_pose150k_tnp_bxcpu.lock"
flock -n 9 || exit 75
exec >>"$LOCAL/controller.log" 2>&1
printf '%s\n' "$$" >"$LOCAL/controller.pid"
trap 'rc=$?; printf "%s\n" "$rc" >"$LOCAL/FAILED.return_code"; exit "$rc"' ERR
echo "$(date -Is) controller start"

test -s "$NBB2_LOCAL/NBB2_ALL_WAVES_COMPLETE.json"
test -s "$SELECTION"

rsync -a --partial --append-verify \
  "$BASE/scripts/run_bxcpu_tnp_archived_nbb2.slurm" \
  "$BASE/scripts/aggregate_bxcpu_tnp_generic.py" \
  "$BASE/scripts/run_bxcpu_tnp_prestructure50k.py" \
  "$BASE/scripts/tnp_score_precomputed_pdb.py" \
  "bxcpu:$RUNTIME/scripts/"
ssh bxcpu "mkdir -p '$REMOTE'"

make_wave_selection() {
  local wave=$1 output=$2
  python3 - "$SELECTION" "$NBB2_LOCAL/$wave/input" "$output" <<'PY'
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
    writer.writeheader(); observed = set()
    for row in reader:
        if row['candidate_id'] in wanted:
            writer.writerow(row); observed.add(row['candidate_id'])
if observed != wanted:
    raise SystemExit(f'wave selection mismatch wanted={len(wanted)} observed={len(observed)}')
PY
}

wait_job() {
  local job=$1
  while ssh bxcpu "squeue -h -j '$job' | grep -q ."; do sleep "$POLL_SECONDS"; done
  states=$(ssh bxcpu "sacct -X -j '$job' -n -P -o State" | sed '/^$/d' | sed 's/+.*$//' | sort -u)
  [[ "$states" == "COMPLETED" ]]
}

for wi in 0 1 2 3; do
  wave=$(printf 'wave_%02d' "$wi")
  wave_local="$LOCAL/$wave"
  wave_remote="$REMOTE/$wave"
  nbb2_job=$(cat "$NBB2_LOCAL/$wave/JOB_ID")
  node1_archives="$NODE1_NBB2/$wave/archives_$nbb2_job"
  mkdir -p "$wave_local" "$wave_local/tnp_aggregate"
  wave_selection="$wave_local/selection.tsv.gz"
  [[ -s "$wave_selection" ]] || make_wave_selection "$wave" "$wave_selection"
  records=$(gzip -cd "$wave_selection" | tail -n +2 | wc -l)
  [[ "$records" -eq 40000 || "$records" -eq 30000 ]]

  ssh bxcpu "mkdir -p '$wave_remote/input' '$wave_remote/archive_stage' '$wave_remote/logs'"
  rsync -a --partial --append-verify "$NBB2_LOCAL/$wave/input/" "bxcpu:$wave_remote/input/"
  rsync -a --partial --append-verify "$wave_selection" "bxcpu:$wave_remote/selection.tsv.gz"

  for idx in {0..7}; do
    node=$(printf 'node_%03d' "$idx")
    expected=$(python3 - "$NBB2_LOCAL/receipts/${wave}_${node}.json" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['sha256'])
PY
)
    remote_archive="$wave_remote/archive_stage/$node.tar.gz"
    remote_ok=$(ssh bxcpu "test -s '$remote_archive' && sha256sum '$remote_archive' | cut -d' ' -f1" || true)
    if [[ "$remote_ok" != "$expected" ]]; then
      tmp="$LOCAL/staging/${wave}_${node}.tar.gz"
      # Keep verified blocks across controller restarts.  --append-verify is
      # unsafe after an interrupted compressed stream because a corrupt tail
      # can make the remote rsync decoder abort.  --inplace uses rsync block
      # checksums to repair the partial file instead of trusting its prefix.
      rsync -a --partial --inplace -e "$SSH1" "node1:$node1_archives/$node.tar.gz" "$tmp"
      observed=$(sha256sum "$tmp" | awk '{print $1}')
      [[ "$observed" == "$expected" ]]
      rsync -a --partial --inplace "$tmp" "bxcpu:$remote_archive.partial"
      ssh bxcpu "mv '$remote_archive.partial' '$remote_archive'"
      remote_ok=$(ssh bxcpu "sha256sum '$remote_archive' | cut -d' ' -f1")
      [[ "$remote_ok" == "$expected" ]]
      rm -f "$tmp"
    fi
    printf '%s  %s\n' "$expected" "$node.tar.gz" >"$wave_local/$node.sha256"
    rsync -a "$wave_local/$node.sha256" "bxcpu:$wave_remote/archive_stage/$node.sha256"

    # Submit each shard as soon as its archive is hash-verified.  This overlaps
    # Node1->bxcpu staging with TNP compute instead of leaving all eight nodes
    # idle until the complete wave has transferred.
    ready_remote="$wave_remote/tnp_results/$node.READY"
    node_job_file="$wave_local/TNP_JOB_ID_${node}"
    if ssh bxcpu "test -s '$ready_remote'"; then
      echo "$(date -Is) $wave $node already complete"
    elif [[ -s "$node_job_file" ]]; then
      node_job=$(cat "$node_job_file")
      echo "$(date -Is) $wave $node reusing job=$node_job"
    else
      node_job=$(ssh bxcpu "sbatch --parsable --array=$idx-$idx \
        --output='$wave_remote/logs/tnp-%A_%a.scheduler.out' \
        --error='$wave_remote/logs/tnp-%A_%a.scheduler.err' \
        --export=ALL,RUNTIME_ROOT='$RUNTIME',CAMPAIGN_ROOT='$wave_remote',SELECTION='$wave_remote/selection.tsv.gz',OUTPUT_ROOT='$wave_remote/tnp_results' \
        '$RUNTIME/scripts/run_bxcpu_tnp_archived_nbb2.slurm'")
      node_job=${node_job%%[_;]*}
      printf '%s\n' "$node_job" >"$node_job_file"
      echo "$(date -Is) $wave $node submitted job=$node_job"
    fi
  done

  for idx in {0..7}; do
    node=$(printf 'node_%03d' "$idx")
    if ! ssh bxcpu "test -s '$wave_remote/tnp_results/$node.READY'"; then
      wait_job "$(cat "$wave_local/TNP_JOB_ID_${node}")"
    fi
    ssh bxcpu "test -s '$wave_remote/tnp_results/$node.READY'"
  done
  echo "$(date -Is) $wave all shards complete records=$records"

  ssh bxcpu "'$RUNTIME/env/bin/python' '$RUNTIME/scripts/aggregate_bxcpu_tnp_generic.py' \
    --input-dir '$wave_remote/tnp_results' \
    --selection '$wave_remote/selection.tsv.gz' \
    --output-dir '$wave_remote/tnp_aggregate' \
    --expected '$records' --shards 8"
  rsync -a --partial --append-verify "bxcpu:$wave_remote/tnp_aggregate/" "$wave_local/tnp_aggregate/"
  (cd "$wave_local/tnp_aggregate" && sha256sum -c SHA256SUMS)

  "$SSH1" node1 "mkdir -p '$NODE1_OUT/$wave/tnp_aggregate'"
  rsync -a --partial --append-verify -e "$SSH1" "$wave_local/tnp_aggregate/" "node1:$NODE1_OUT/$wave/tnp_aggregate/"
  "$SSH1" node1 "cd '$NODE1_OUT/$wave/tnp_aggregate' && sha256sum -c SHA256SUMS"
  date -Is >"$wave_local/NODE1_HASH_OK"

  ssh bxcpu "rm -rf '$wave_remote/archive_stage' '$wave_remote/tnp_results'"
  date -Is >"$wave_local/REMOTE_RAW_PURGED_AFTER_NODE1_ACK"
done

python3 "$BASE/scripts/aggregate_tnp_fixed_pose150k.py" \
  --input-root "$LOCAL" --selection "$SELECTION" \
  --output-dir "$LOCAL/aggregate" --expected 150000
(cd "$LOCAL/aggregate" && sha256sum -c SHA256SUMS)
"$SSH1" node1 "mkdir -p '$NODE1_OUT/aggregate'"
rsync -a --partial --append-verify -e "$SSH1" "$LOCAL/aggregate/" "node1:$NODE1_OUT/aggregate/"
"$SSH1" node1 "cd '$NODE1_OUT/aggregate' && sha256sum -c SHA256SUMS"
date -Is >"$LOCAL/COMPLETE"
rm -f "$LOCAL/FAILED.return_code"
echo "$(date -Is) controller complete"
