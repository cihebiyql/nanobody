#!/usr/bin/env bash
set -euo pipefail

LOCAL_ROOT=${LOCAL_ROOT:-/mnt/d/work/抗体/node1/rfantibody_pvrig_validation_20260712}
REMOTE_ROOT=${REMOTE_ROOT:-/data/qlyu/projects/pvrig_rfantibody_validation_20260712}
REMOTE_HOST=${REMOTE_HOST:-node1}

files=(
  scripts/merge_qc_pose_for_rf2.py
  scripts/prepare_rf2_batch.py
  scripts/run_rf2_batch_node1.sh
  scripts/parse_rf2_outputs.py
  scripts/continue_through_rf2_node1.sh
  pose_audit/rf2_pre_shortlist_primary.tsv
  manifests/fr4_terminal_repair_mapping.tsv
)
for relative in "${files[@]}"; do
  [[ -f "$LOCAL_ROOT/$relative" ]] || { echo "Missing local artifact: $LOCAL_ROOT/$relative" >&2; exit 2; }
  ssh.exe "$REMOTE_HOST" "mkdir -p '$REMOTE_ROOT/$(dirname "$relative")' && cat > '$REMOTE_ROOT/$relative'" < "$LOCAL_ROOT/$relative"
done
ssh.exe "$REMOTE_HOST" "chmod +x '$REMOTE_ROOT'/scripts/*.py '$REMOTE_ROOT'/scripts/*.sh && '$REMOTE_ROOT/scripts/continue_through_rf2_node1.sh'"

