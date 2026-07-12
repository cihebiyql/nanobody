#!/usr/bin/env bash
set -Eeuo pipefail

SET_ID=${1:?Usage: run_set.sh SET_ID GPU HOTSPOTS}
GPU=${2:?Usage: run_set.sh SET_ID GPU HOTSPOTS}
HOTSPOTS=${3:?Usage: run_set.sh SET_ID GPU HOTSPOTS}

RF_ROOT=${RF_ROOT:-/data/qlyu/software/RFantibody}
RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_1000_20260712}
TARGET_BACKBONES=${TARGET_BACKBONES:-50}
SEQS_PER_BACKBONE=${SEQS_PER_BACKBONE:-8}
MPNN_TEMPERATURE=${MPNN_TEMPERATURE:-0.2}

SET_DIR="$RUN_ROOT/sets/set_$SET_ID"
BACKBONE_DIR="$SET_DIR/backbones"
SEQUENCE_DIR="$SET_DIR/sequences"
TMP_DIR="$SET_DIR/tmp"
STATUS_DIR="$SET_DIR/status"
TARGET="$RUN_ROOT/inputs/pvrig_8x6b_chainT.pdb"
FRAMEWORK="$RF_ROOT/scripts/examples/example_inputs/h-NbBCII10.pdb"

mkdir -p "$BACKBONE_DIR" "$SEQUENCE_DIR" "$TMP_DIR" "$STATUS_DIR"
exec 9>"$SET_DIR/run.lock"
if ! flock -n 9; then
  echo "set $SET_ID is already running" >&2
  exit 75
fi

echo $$ > "$STATUS_DIR/pid"
date -Is > "$STATUS_DIR/started_at.txt"
printf '%s\n' "$GPU" > "$STATUS_DIR/gpu.txt"
printf '%s\n' "$HOTSPOTS" > "$STATUS_DIR/hotspots.txt"

write_status() {
  local state=$1
  local rc=${2:-0}
  python3 - "$SET_DIR" "$SET_ID" "$GPU" "$HOTSPOTS" "$state" "$rc" \
    "$TARGET_BACKBONES" "$SEQS_PER_BACKBONE" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

set_dir = Path(sys.argv[1])
backbones = sorted((set_dir / "backbones").glob("design_*.pdb"))
sequences = sorted((set_dir / "sequences").glob("design_*_dldesign_*.pdb"))
payload = {
    "set_id": sys.argv[2],
    "gpu": int(sys.argv[3]),
    "hotspots": sys.argv[4],
    "state": sys.argv[5],
    "return_code": int(sys.argv[6]),
    "target_backbones": int(sys.argv[7]),
    "sequences_per_backbone": int(sys.argv[8]),
    "backbone_pdb_count": len(backbones),
    "sequence_pdb_count": len(sequences),
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
(set_dir / "status" / "status.json").write_text(json.dumps(payload, indent=2) + "\n")
if payload["state"] == "complete":
    (set_dir / "complete.json").write_text(json.dumps(payload, indent=2) + "\n")
PY
}

on_exit() {
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    write_status failed "$rc" || true
  fi
}
trap on_exit EXIT

test -s "$TARGET"
test -s "$FRAMEWORK"
write_status running 0

existing_backbones=$(find "$BACKBONE_DIR" -maxdepth 1 -type f -name 'design_*.pdb' | wc -l)
if (( existing_backbones > TARGET_BACKBONES )); then
  echo "Found $existing_backbones backbones, expected at most $TARGET_BACKBONES" >&2
  exit 2
fi

missing_backbones=$((TARGET_BACKBONES - existing_backbones))
if (( missing_backbones > 0 )); then
  echo "[$(date -Is)] set=$SET_ID stage=rfdiffusion existing=$existing_backbones missing=$missing_backbones gpu=$GPU"
  cd "$RF_ROOT"
  CUDA_VISIBLE_DEVICES="$GPU" bin/rfdiffusion \
    --target "$TARGET" \
    --framework "$FRAMEWORK" \
    --output "$BACKBONE_DIR/design" \
    --num-designs "$missing_backbones" \
    --design-loops "H1:7,H2:6,H3:5-13" \
    --hotspots "$HOTSPOTS" \
    --diffuser-t 50 \
    --deterministic \
    --no-trajectory
fi

backbone_count=$(find "$BACKBONE_DIR" -maxdepth 1 -type f -name 'design_*.pdb' | wc -l)
trb_count=$(find "$BACKBONE_DIR" -maxdepth 1 -type f -name 'design_*.trb' | wc -l)
if [[ "$backbone_count" -ne "$TARGET_BACKBONES" || "$trb_count" -ne "$TARGET_BACKBONES" ]]; then
  echo "Incomplete RFdiffusion output: pdb=$backbone_count trb=$trb_count expected=$TARGET_BACKBONES" >&2
  exit 3
fi

pending_dir="$TMP_DIR/pending_$$"
mpnn_work_dir="$TMP_DIR/mpnn_work_$$"
mkdir -p "$pending_dir" "$mpnn_work_dir"

for pdb in "$BACKBONE_DIR"/design_*.pdb; do
  base=$(basename "$pdb" .pdb)
  output_count=$(find "$SEQUENCE_DIR" -maxdepth 1 -type f -name "${base}_dldesign_*.pdb" | wc -l)
  if [[ "$output_count" -lt "$SEQS_PER_BACKBONE" ]]; then
    ln -s "$pdb" "$pending_dir/$(basename "$pdb")"
  elif [[ "$output_count" -gt "$SEQS_PER_BACKBONE" ]]; then
    echo "Too many sequence outputs for $base: $output_count" >&2
    exit 4
  fi
done

pending_count=$(find "$pending_dir" -maxdepth 1 -type l -name 'design_*.pdb' | wc -l)
if (( pending_count > 0 )); then
  echo "[$(date -Is)] set=$SET_ID stage=proteinmpnn pending_backbones=$pending_count seqs_per_backbone=$SEQS_PER_BACKBONE gpu=$GPU"
  cd "$mpnn_work_dir"
  PYTHONHASHSEED=0 CUDA_VISIBLE_DEVICES="$GPU" "$RF_ROOT/bin/rfantibody-env" \
    "$RF_ROOT/scripts/proteinmpnn_interface_design.py" \
    -pdbdir "$pending_dir" \
    -outpdbdir "$SEQUENCE_DIR" \
    -loop_string H1,H2,H3 \
    -seqs_per_struct "$SEQS_PER_BACKBONE" \
    -temperature "$MPNN_TEMPERATURE" \
    -checkpoint_path "$RF_ROOT/weights/ProteinMPNN_v48_noise_0.2.pt" \
    -omit_AAs CX \
    -augment_eps 0 \
    -checkpoint_name "$TMP_DIR/mpnn_checkpoint_$$.txt" \
    -deterministic
fi

sequence_count=$(find "$SEQUENCE_DIR" -maxdepth 1 -type f -name 'design_*_dldesign_*.pdb' | wc -l)
expected_sequences=$((TARGET_BACKBONES * SEQS_PER_BACKBONE))
if [[ "$sequence_count" -ne "$expected_sequences" ]]; then
  echo "Incomplete ProteinMPNN output: sequences=$sequence_count expected=$expected_sequences" >&2
  exit 5
fi

date -Is > "$STATUS_DIR/completed_at.txt"
write_status complete 0
trap - EXIT
echo "[$(date -Is)] set=$SET_ID complete backbones=$backbone_count sequences=$sequence_count"
