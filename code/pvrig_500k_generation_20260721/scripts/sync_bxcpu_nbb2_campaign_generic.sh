#!/usr/bin/env bash
set -Eeuo pipefail

: "${REMOTE_CAMPAIGN_ROOT:?REMOTE_CAMPAIGN_ROOT is required}"
: "${FULL_JOB_ID:?FULL_JOB_ID is required}"
: "${LOCAL_ROOT:?LOCAL_ROOT is required}"
: "${NODE1_TARGET:?NODE1_TARGET is required}"

SHARDS=${SHARDS:-8}
POLL_SECONDS=${POLL_SECONDS:-30}
NODE1_SSH=${NODE1_SSH:-/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe}
TRANSFER_SHARD_COUNT=${TRANSFER_SHARD_COUNT:-1}
TRANSFER_SHARD_INDEX=${TRANSFER_SHARD_INDEX:-0}
if (( TRANSFER_SHARD_COUNT < 1 || TRANSFER_SHARD_INDEX < 0 || TRANSFER_SHARD_INDEX >= TRANSFER_SHARD_COUNT )); then
  echo "invalid transfer shard configuration" >&2
  exit 64
fi
mkdir -p "$LOCAL_ROOT/state" "$LOCAL_ROOT/archives" "$LOCAL_ROOT/metadata"

event() {
  printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOCAL_ROOT/state/sync.log"
}

node1_prepare() {
  "$NODE1_SSH" node1 "mkdir -p '$NODE1_TARGET/archives' '$NODE1_TARGET/metadata'"
}

sync_node() {
  local index=$1
  local node ready_remote sha_remote archive_remote
  local ready sha_file archive
  node=$(printf '%03d' "$index")
  ready_remote="$REMOTE_CAMPAIGN_ROOT/archives_${FULL_JOB_ID}/node_${node}.READY.json"
  sha_remote="$REMOTE_CAMPAIGN_ROOT/archives_${FULL_JOB_ID}/node_${node}.sha256"
  archive_remote="$REMOTE_CAMPAIGN_ROOT/archives_${FULL_JOB_ID}/node_${node}.tar.gz"
  ready="$LOCAL_ROOT/archives/node_${node}.READY.json"
  sha_file="$LOCAL_ROOT/archives/node_${node}.sha256"
  archive="$LOCAL_ROOT/archives/node_${node}.tar.gz"

  if [[ -s "$LOCAL_ROOT/state/node_${node}.NODE1_ACK" ]]; then
    return 0
  fi
  if ! ssh bxcpu "test -s '$ready_remote' -a -s '$sha_remote' -a -s '$archive_remote'"; then
    return 1
  fi
  if [[ ! -s "$LOCAL_ROOT/state/node_${node}.LOCAL_ACK" ]]; then
    event "downloading node_${node}"
    rsync -a --partial --partial-dir=.rsync-partial \
      "bxcpu:$ready_remote" "bxcpu:$sha_remote" "bxcpu:$archive_remote" \
      "$LOCAL_ROOT/archives/"
    (cd "$LOCAL_ROOT/archives" && sha256sum -c "node_${node}.sha256")
    date -u +%FT%TZ > "$LOCAL_ROOT/state/node_${node}.LOCAL_ACK"
  fi

  node1_prepare
  event "relaying node_${node} to Node1"
  rsync -az --partial -e "$NODE1_SSH" \
    "$ready" "$sha_file" "$archive" "node1:$NODE1_TARGET/archives/"
  "$NODE1_SSH" node1 \
    "cd '$NODE1_TARGET/archives' && sha256sum -c 'node_${node}.sha256'"
  date -u +%FT%TZ > "$LOCAL_ROOT/state/node_${node}.NODE1_ACK"
  return 0
}

assigned=0
for index in $(seq 0 $((SHARDS - 1))); do
  if (( index % TRANSFER_SHARD_COUNT == TRANSFER_SHARD_INDEX )); then
    assigned=$((assigned + 1))
  fi
done
event "sync start job=$FULL_JOB_ID shards=$SHARDS transfer_shard=$TRANSFER_SHARD_INDEX/$TRANSFER_SHARD_COUNT assigned=$assigned"
while true; do
  complete=0
  for index in $(seq 0 $((SHARDS - 1))); do
    if (( index % TRANSFER_SHARD_COUNT != TRANSFER_SHARD_INDEX )); then
      continue
    fi
    if sync_node "$index"; then
      complete=$((complete + 1))
    fi
  done
  event "archive progress transfer_shard=$TRANSFER_SHARD_INDEX ${complete}/${assigned}"
  if [[ "$complete" -eq "$assigned" ]]; then
    break
  fi
  sleep "$POLL_SECONDS"
done

date -u +%FT%TZ > "$LOCAL_ROOT/state/TRANSFER_SHARD_${TRANSFER_SHARD_INDEX}.COMPLETE"
if (( TRANSFER_SHARD_INDEX != 0 )); then
  event "transfer shard complete; metadata finalization delegated to shard 0"
  exit 0
fi
while [[ $(find "$LOCAL_ROOT/state" -maxdepth 1 -name 'node_*.NODE1_ACK' -type f | wc -l) -ne "$SHARDS" ]]; do
  event "waiting for all Node1 archive acknowledgements"
  sleep "$POLL_SECONDS"
done

while ! ssh bxcpu \
  "test -s '$REMOTE_CAMPAIGN_ROOT/aggregated_${FULL_JOB_ID}/COMPLETE.json'"; do
  event "waiting for aggregate manifest"
  sleep "$POLL_SECONDS"
done
rsync -a --partial \
  "bxcpu:$REMOTE_CAMPAIGN_ROOT/aggregated_${FULL_JOB_ID}/" \
  "$LOCAL_ROOT/metadata/aggregated_${FULL_JOB_ID}/"
node1_prepare
rsync -az --partial -e "$NODE1_SSH" \
  "$LOCAL_ROOT/metadata/aggregated_${FULL_JOB_ID}/" \
  "node1:$NODE1_TARGET/metadata/aggregated_${FULL_JOB_ID}/"

while true; do
  tnp_job=$(
    ssh bxcpu \
      "sed -n 's/^TNP=//p' '$REMOTE_CAMPAIGN_ROOT/status/JOB_IDS' 2>/dev/null | tail -1" \
      || true
  )
  if [[ "$tnp_job" =~ ^[0-9]+$ ]] && ssh bxcpu \
    "test -s '$REMOTE_CAMPAIGN_ROOT/tnp_aggregated_${tnp_job}/READY.json'"; then
    event "downloading TNP aggregate job=$tnp_job"
    rsync -a --partial \
      "bxcpu:$REMOTE_CAMPAIGN_ROOT/tnp_aggregated_${tnp_job}/" \
      "$LOCAL_ROOT/metadata/tnp_aggregated_${tnp_job}/"
    rsync -az --partial -e "$NODE1_SSH" \
      "$LOCAL_ROOT/metadata/tnp_aggregated_${tnp_job}/" \
      "node1:$NODE1_TARGET/metadata/tnp_aggregated_${tnp_job}/"
    break
  fi
  event "waiting for TNP aggregate"
  sleep "$POLL_SECONDS"
done

rsync -a --partial \
  "bxcpu:$REMOTE_CAMPAIGN_ROOT/status/" "$LOCAL_ROOT/metadata/status/"
rsync -az --partial -e "$NODE1_SSH" \
  "$LOCAL_ROOT/metadata/status/" "node1:$NODE1_TARGET/metadata/status/"
date -u +%FT%TZ > "$LOCAL_ROOT/state/TRANSFER_COMPLETE"
event "sync complete"
