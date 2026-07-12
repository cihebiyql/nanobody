#!/usr/bin/env bash
set -euo pipefail

LOCAL_ROOT=${LOCAL_ROOT:-/mnt/d/work/抗体/node1/rfantibody_pvrig_validation_20260712}
REMOTE_ROOT=${REMOTE_ROOT:-/data/qlyu/projects/pvrig_rfantibody_validation_20260712}
REMOTE_HOST=${REMOTE_HOST:-node1}
PACKAGE_ROOT=$REMOTE_ROOT/docking/rf2_diagnostic_top30

files=(
  rf2/results/rf2_diagnostic_docking_top.tsv
  scripts/build_nbb2_haddock_package.py
  scripts/run_nbb2_haddock_shard_node1.sh
  scripts/run_nbb2_haddock_controller_node1.sh
  scripts/docking_helpers/normalize_pdb_chain.py
  scripts/docking_helpers/validate_pdb_sequence.py
  scripts/docking_helpers/pdb_geometry_qc.py
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

ssh.exe "$REMOTE_HOST" "set -e; \
  python3 '$REMOTE_ROOT/scripts/build_nbb2_haddock_package.py' \
    '$REMOTE_ROOT/rf2/results/rf2_diagnostic_docking_top.tsv' \
    '$REMOTE_ROOT/inputs/docking' \
    '$REMOTE_ROOT/scripts/docking_helpers' \
    '$PACKAGE_ROOT' --shards 4; \
  cp '$REMOTE_ROOT/scripts/run_nbb2_haddock_shard_node1.sh' '$PACKAGE_ROOT/'; \
  cp '$REMOTE_ROOT/scripts/run_nbb2_haddock_controller_node1.sh' '$PACKAGE_ROOT/'; \
  chmod +x '$PACKAGE_ROOT/'*.sh; \
  if [ -s '$PACKAGE_ROOT/controller.pid' ] && kill -0 \$(cat '$PACKAGE_ROOT/controller.pid') 2>/dev/null; then \
    echo controller_already_running pid=\$(cat '$PACKAGE_ROOT/controller.pid'); \
  else \
    nohup env PACKAGE_ROOT='$PACKAGE_ROOT' MONOMER_MAX_LOAD1=64 DOCKING_MAX_LOAD1=48 POLL_SECONDS=60 \
      bash '$PACKAGE_ROOT/run_nbb2_haddock_controller_node1.sh' \
      > '$PACKAGE_ROOT/controller_launcher.log' 2>&1 < /dev/null & \
    echo \$! > '$PACKAGE_ROOT/controller.pid'; \
    echo started_diagnostic_docking_controller pid=\$!; \
  fi"

