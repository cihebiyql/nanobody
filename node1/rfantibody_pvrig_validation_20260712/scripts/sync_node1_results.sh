#!/usr/bin/env bash
set -euo pipefail

LOCAL_ROOT=${LOCAL_ROOT:-/mnt/d/work/抗体/node1/rfantibody_pvrig_validation_20260712}
REMOTE_ROOT=${REMOTE_ROOT:-/data/qlyu/projects/pvrig_rfantibody_validation_20260712}
REMOTE_HOST=${REMOTE_HOST:-node1}
REMOTE_PACKAGE=$REMOTE_ROOT/docking/rf2_diagnostic_top30
LOCAL_PACKAGE=$LOCAL_ROOT/docking/remote_selected

mkdir -p "$LOCAL_ROOT/rf2/remote_outputs" "$LOCAL_PACKAGE"

ssh.exe "$REMOTE_HOST" "cd '$REMOTE_ROOT' && \
  find rf2/batch_10recycle_blind rf2/results rf2/shortlist -type f \
    \( -name '*_best.pdb' -o -name '*.tsv' -o -name '*.json' -o -name '*.fasta' -o -name '*.log' -o -name '*.exit_code' \) \
    -print0 | tar --null -T - -czf -" \
  | tar -xzf - -C "$LOCAL_ROOT/rf2/remote_outputs"

ssh.exe "$REMOTE_HOST" "cd '$REMOTE_PACKAGE' && \
  { printf '%s\\0' package_summary.json controller.log monomer.complete docking.complete 2>/dev/null || true; \
    find shard_* -type f \
      \( -path '*/manifests/*.tsv' \
         -o -path '*/monomer/*/*_chainA.pdb' \
         -o -path '*/reports/*/*.json' \
         -o -path '*/haddock3/*/*.cfg' \
         -o -path '*/haddock3/*/data/*.pdb' \
         -o -path '*/haddock3/*/run_*/6_seletopclusts/cluster_*_model_*.pdb' \
         -o -path '*/haddock3/*/run_*/6_seletopclusts/cluster_*_model_*.pdb.gz' \
         -o -path '*/haddock3/*/run_*/traceback/consensus.tsv' \
         -o -name '*.complete' \) -print0; \
  } | tar --null --ignore-failed-read -T - -czf -" \
  | tar -xzf - -C "$LOCAL_PACKAGE"

echo "Synced RF2 outputs to $LOCAL_ROOT/rf2/remote_outputs"
echo "Synced selected docking evidence to $LOCAL_PACKAGE"

