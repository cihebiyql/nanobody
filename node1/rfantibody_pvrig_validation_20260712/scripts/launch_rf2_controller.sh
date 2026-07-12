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
  scripts/build_nbb2_haddock_package.py
  scripts/run_nbb2_haddock_shard_node1.sh
  scripts/run_nbb2_haddock_controller_node1.sh
  scripts/continue_through_rf2_node1.sh
  scripts/docking_helpers/normalize_pdb_chain.py
  scripts/docking_helpers/validate_pdb_sequence.py
  scripts/docking_helpers/pdb_geometry_qc.py
  pose_audit/rf2_pre_shortlist_primary.tsv
  manifests/fr4_terminal_repair_mapping.tsv
  inputs/docking/8X6B.pdb
  inputs/docking/9E6Y.pdb
  inputs/docking/PVRIG_hotspot_set_v1.csv
  inputs/docking/pvrig_8x6b_chainB.pdb
  inputs/docking/hotspot_residues_8x6b.txt
)
for relative in "${files[@]}"; do
  [[ -f "$LOCAL_ROOT/$relative" ]] || { echo "Missing local artifact: $LOCAL_ROOT/$relative" >&2; exit 2; }
  ssh.exe "$REMOTE_HOST" "mkdir -p '$REMOTE_ROOT/$(dirname "$relative")' && cat > '$REMOTE_ROOT/$relative'" < "$LOCAL_ROOT/$relative"
done
ssh.exe "$REMOTE_HOST" "chmod +x '$REMOTE_ROOT'/scripts/*.py '$REMOTE_ROOT'/scripts/*.sh && '$REMOTE_ROOT/scripts/continue_through_rf2_node1.sh'"
