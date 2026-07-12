#!/usr/bin/env bash
set -Eeuo pipefail

ARM_ID=${1:?Usage: run_generation_arm.sh ARM_ID GPU_ID}
GPU_ID=${2:?Usage: run_generation_arm.sh ARM_ID GPU_ID}

RF_ROOT=${RF_ROOT:-/data/qlyu/software/RFantibody}
RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712}
ARM_TABLE=${ARM_TABLE:-$RUN_ROOT/config/generation_arms.tsv}
ARM_OUTPUT_BASE=${ARM_OUTPUT_BASE:-$RUN_ROOT/generation/arms}
TARGET_BACKBONES_OVERRIDE=${TARGET_BACKBONES_OVERRIDE:-}
SEQS_PER_BACKBONE_OVERRIDE=${SEQS_PER_BACKBONE_OVERRIDE:-}

[[ -s "$ARM_TABLE" ]] || { echo "Missing arm table: $ARM_TABLE" >&2; exit 2; }
line=$(awk -F $'\t' -v arm="$ARM_ID" 'NR > 1 && $1 == arm { print; found=1; exit } END { if (!found) exit 3 }' "$ARM_TABLE") || {
  echo "Unknown arm: $ARM_ID" >&2
  exit 2
}
IFS=$'\t' read -r arm_id configured_gpu patch_id hotspots_pdb hotspots_uniprot holdout_hotspots_pdb \
  scaffold_id framework_relpath framework_mutations scaffold_lane h3_regime design_loops \
  target_backbones seqs_per_backbone mpnn_temperature generation_seed_lane purpose <<< "$line"

[[ "$arm_id" == "$ARM_ID" ]] || exit 2
[[ "$configured_gpu" == "$GPU_ID" ]] || {
  echo "Arm $ARM_ID is assigned to GPU $configured_gpu, not GPU $GPU_ID" >&2
  exit 2
}
[[ -n "$TARGET_BACKBONES_OVERRIDE" ]] && target_backbones=$TARGET_BACKBONES_OVERRIDE
[[ -n "$SEQS_PER_BACKBONE_OVERRIDE" ]] && seqs_per_backbone=$SEQS_PER_BACKBONE_OVERRIDE

ARM_DIR="$ARM_OUTPUT_BASE/$ARM_ID"
BACKBONE_DIR="$ARM_DIR/backbones"
SEQUENCE_DIR="$ARM_DIR/sequences"
TMP_DIR="$ARM_DIR/tmp"
STATUS_DIR="$ARM_DIR/status"
LOG_DIR="$ARM_DIR/logs"
TARGET="$RUN_ROOT/inputs/pvrig_8x6b_chainT.pdb"
FRAMEWORK="$RUN_ROOT/$framework_relpath"
mkdir -p "$BACKBONE_DIR" "$SEQUENCE_DIR" "$TMP_DIR" "$STATUS_DIR" "$LOG_DIR"

exec 9>"$ARM_DIR/run.lock"
if ! flock -n 9; then
  echo "Arm $ARM_ID is already running" >&2
  exit 75
fi

write_status() {
  local state=$1
  local rc=${2:-0}
  python3 - "$ARM_DIR" "$ARM_ID" "$GPU_ID" "$state" "$rc" "$target_backbones" \
    "$seqs_per_backbone" "$patch_id" "$scaffold_id" "$h3_regime" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
payload = {
    "arm_id": sys.argv[2],
    "gpu_id": int(sys.argv[3]),
    "state": sys.argv[4],
    "return_code": int(sys.argv[5]),
    "target_backbones": int(sys.argv[6]),
    "seqs_per_backbone": int(sys.argv[7]),
    "patch_id": sys.argv[8],
    "scaffold_id": sys.argv[9],
    "h3_regime": sys.argv[10],
    "backbone_pdb_count": len(list((root / "backbones").glob("design_*.pdb"))),
    "backbone_trb_count": len(list((root / "backbones").glob("design_*.trb"))),
    "sequence_pdb_count": len(list((root / "sequences").glob("design_*_dldesign_*.pdb"))),
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
(root / "status" / "status.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
if payload["state"] == "complete":
    (root / "complete.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY
}

on_exit() {
  rc=$?
  [[ $rc -eq 0 ]] || write_status failed "$rc" || true
}
trap on_exit EXIT

test -s "$TARGET"
test -s "$FRAMEWORK"
echo $$ > "$STATUS_DIR/pid"
date -Is > "$STATUS_DIR/started_at.txt"
printf '%s\n' "$GPU_ID" > "$STATUS_DIR/gpu.txt"
write_status running 0

existing_backbones=$(find "$BACKBONE_DIR" -maxdepth 1 -type f -name 'design_*.pdb' | wc -l)
if (( existing_backbones > target_backbones )); then
  echo "Found $existing_backbones backbones, expected at most $target_backbones" >&2
  exit 3
fi
missing_backbones=$((target_backbones - existing_backbones))
if (( missing_backbones > 0 )); then
  echo "[$(date -Is)] arm=$ARM_ID stage=rfdiffusion missing=$missing_backbones gpu=$GPU_ID"
  cd "$RF_ROOT"
  CUDA_VISIBLE_DEVICES="$GPU_ID" bin/rfdiffusion \
    --target "$TARGET" \
    --framework "$FRAMEWORK" \
    --output "$BACKBONE_DIR/design" \
    --num-designs "$missing_backbones" \
    --design-loops "$design_loops" \
    --hotspots "$hotspots_pdb" \
    --diffuser-t 50 \
    --deterministic \
    --no-trajectory \
    >"$LOG_DIR/rfdiffusion.log" 2>&1
fi

backbone_count=$(find "$BACKBONE_DIR" -maxdepth 1 -type f -name 'design_*.pdb' | wc -l)
trb_count=$(find "$BACKBONE_DIR" -maxdepth 1 -type f -name 'design_*.trb' | wc -l)
if [[ "$backbone_count" -ne "$target_backbones" || "$trb_count" -ne "$target_backbones" ]]; then
  echo "Incomplete RFdiffusion output: pdb=$backbone_count trb=$trb_count expected=$target_backbones" >&2
  exit 4
fi

pending_dir="$TMP_DIR/pending_$$"
mpnn_work_dir="$TMP_DIR/mpnn_work_$$"
mkdir -p "$pending_dir" "$mpnn_work_dir"
for pdb in "$BACKBONE_DIR"/design_*.pdb; do
  base=$(basename "$pdb" .pdb)
  output_count=$(find "$SEQUENCE_DIR" -maxdepth 1 -type f -name "${base}_dldesign_*.pdb" | wc -l)
  if [[ "$output_count" -lt "$seqs_per_backbone" ]]; then
    ln -s "$pdb" "$pending_dir/$(basename "$pdb")"
  elif [[ "$output_count" -gt "$seqs_per_backbone" ]]; then
    echo "Too many sequence outputs for $base: $output_count" >&2
    exit 5
  fi
done

pending_count=$(find "$pending_dir" -maxdepth 1 -type l -name 'design_*.pdb' | wc -l)
if (( pending_count > 0 )); then
  echo "[$(date -Is)] arm=$ARM_ID stage=proteinmpnn pending=$pending_count gpu=$GPU_ID"
  cd "$mpnn_work_dir"
  PYTHONHASHSEED=0 CUDA_VISIBLE_DEVICES="$GPU_ID" "$RF_ROOT/bin/rfantibody-env" \
    "$RF_ROOT/scripts/proteinmpnn_interface_design.py" \
    -pdbdir "$pending_dir" \
    -outpdbdir "$SEQUENCE_DIR" \
    -loop_string H1,H2,H3 \
    -seqs_per_struct "$seqs_per_backbone" \
    -temperature "$mpnn_temperature" \
    -checkpoint_path "$RF_ROOT/weights/ProteinMPNN_v48_noise_0.2.pt" \
    -omit_AAs CX \
    -augment_eps 0 \
    -checkpoint_name "$TMP_DIR/mpnn_checkpoint_$$.txt" \
    -deterministic \
    >"$LOG_DIR/proteinmpnn.log" 2>&1
fi

sequence_count=$(find "$SEQUENCE_DIR" -maxdepth 1 -type f -name 'design_*_dldesign_*.pdb' | wc -l)
expected_sequences=$((target_backbones * seqs_per_backbone))
if [[ "$sequence_count" -ne "$expected_sequences" ]]; then
  echo "Incomplete ProteinMPNN output: sequences=$sequence_count expected=$expected_sequences" >&2
  exit 6
fi

date -Is > "$STATUS_DIR/completed_at.txt"
write_status complete 0
trap - EXIT
echo "[$(date -Is)] arm=$ARM_ID complete backbones=$backbone_count sequences=$sequence_count"
