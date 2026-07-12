#!/usr/bin/env bash
set -euo pipefail

LOCAL_ROOT=${LOCAL_ROOT:-/mnt/d/work/抗体/node1/rfantibody_pvrig_validation_20260712}
REMOTE_ROOT=${REMOTE_ROOT:-/data/qlyu/projects/pvrig_rfantibody_validation_20260712}
REMOTE_HOST=${REMOTE_HOST:-node1}

command -v ssh.exe >/dev/null || { echo "Missing local command: ssh.exe" >&2; exit 2; }

for path in \
  "$LOCAL_ROOT/inputs/pvrig_rfantibody_1000.fr4_restored.fasta" \
  "$LOCAL_ROOT/manifests/fr4_terminal_repair_audit.json" \
  "$LOCAL_ROOT/manifests/fr4_terminal_repair_mapping.tsv" \
  "$LOCAL_ROOT/config/pipeline_config.json" \
  "$LOCAL_ROOT/scripts/run_sequence_qc_node1.sh"; do
  [[ -f "$path" ]] || { echo "Missing local artifact: $path" >&2; exit 2; }
done

ssh.exe "$REMOTE_HOST" "mkdir -p '$REMOTE_ROOT'/{inputs,config,manifests,scripts,qc,logs}"

# Windows scp.exe cannot stat this workspace's non-ASCII WSL path reliably.
# Streaming over the already working ssh.exe transport preserves exact bytes.
copy_file() {
  local source=$1
  local destination=$2
  ssh.exe "$REMOTE_HOST" "cat > '$destination'" < "$source"
}

copy_file \
  "$LOCAL_ROOT/inputs/pvrig_rfantibody_1000.fr4_restored.fasta" \
  "$REMOTE_ROOT/inputs/pvrig_rfantibody_1000.fr4_restored.fasta"
copy_file \
  "$LOCAL_ROOT/manifests/fr4_terminal_repair_audit.json" \
  "$REMOTE_ROOT/manifests/fr4_terminal_repair_audit.json"
copy_file \
  "$LOCAL_ROOT/manifests/fr4_terminal_repair_mapping.tsv" \
  "$REMOTE_ROOT/manifests/fr4_terminal_repair_mapping.tsv"
copy_file \
  "$LOCAL_ROOT/config/pipeline_config.json" \
  "$REMOTE_ROOT/config/pipeline_config.json"
copy_file \
  "$LOCAL_ROOT/scripts/run_sequence_qc_node1.sh" \
  "$REMOTE_ROOT/scripts/run_sequence_qc_node1.sh"
ssh.exe "$REMOTE_HOST" "chmod +x '$REMOTE_ROOT/scripts/run_sequence_qc_node1.sh' && RUN_LABEL=sequence_qc_fr4_restored INPUT='$REMOTE_ROOT/inputs/pvrig_rfantibody_1000.fr4_restored.fasta' OUT='$REMOTE_ROOT/qc/cascade_fr4_restored' '$REMOTE_ROOT/scripts/run_sequence_qc_node1.sh'"
