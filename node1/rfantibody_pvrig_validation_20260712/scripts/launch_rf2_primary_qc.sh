#!/usr/bin/env bash
set -euo pipefail

LOCAL_ROOT=${LOCAL_ROOT:-/mnt/d/work/抗体/node1/rfantibody_pvrig_validation_20260712}
REMOTE_ROOT=${REMOTE_ROOT:-/data/qlyu/projects/pvrig_rfantibody_validation_20260712}
REMOTE_HOST=${REMOTE_HOST:-node1}

input_local=$LOCAL_ROOT/inputs/rf2_primary_78.fr4_restored.fasta
audit_local=$LOCAL_ROOT/manifests/rf2_primary_78_sequence_audit.json
runner_local=$LOCAL_ROOT/scripts/run_sequence_qc_node1.sh
scheduler_local=$LOCAL_ROOT/scripts/schedule_rf2_primary_qc_node1.sh
for path in "$input_local" "$audit_local" "$runner_local" "$scheduler_local"; do
  [[ -f "$path" ]] || { echo "Missing local artifact: $path" >&2; exit 2; }
done

ssh.exe "$REMOTE_HOST" "mkdir -p '$REMOTE_ROOT'/{inputs,manifests,scripts,qc,logs}"
ssh.exe "$REMOTE_HOST" "cat > '$REMOTE_ROOT/inputs/rf2_primary_78.fr4_restored.fasta'" < "$input_local"
ssh.exe "$REMOTE_HOST" "cat > '$REMOTE_ROOT/manifests/rf2_primary_78_sequence_audit.json'" < "$audit_local"
ssh.exe "$REMOTE_HOST" "cat > '$REMOTE_ROOT/scripts/run_sequence_qc_node1.sh'" < "$runner_local"
ssh.exe "$REMOTE_HOST" "cat > '$REMOTE_ROOT/scripts/schedule_rf2_primary_qc_node1.sh'" < "$scheduler_local"
ssh.exe "$REMOTE_HOST" "chmod +x '$REMOTE_ROOT/scripts/run_sequence_qc_node1.sh' '$REMOTE_ROOT/scripts/schedule_rf2_primary_qc_node1.sh' && '$REMOTE_ROOT/scripts/schedule_rf2_primary_qc_node1.sh'"
