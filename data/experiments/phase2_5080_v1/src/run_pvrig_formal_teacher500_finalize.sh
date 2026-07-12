#!/usr/bin/env bash
# Finalize RFantibody candidates into a frozen Teacher500 Node1 docking package.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PY="$ROOT/.venv-phase2-5080/bin/python"
SSH_COMMAND=${SSH_COMMAND:-ssh.exe}
NODE_HOST=${NODE_HOST:-node1}
REMOTE_BASE=${REMOTE_BASE:-/data/qlyu/projects/pvrig_teacher_formal_v1_20260712}
REMOTE_PY=${REMOTE_PY:-/data/qlyu/anaconda3/envs/rfdiffusion2/bin/python}
REMOTE_GENERATION="$REMOTE_BASE/rfantibody_generation/production"
REMOTE_COLLECTION="$REMOTE_BASE/candidate_collection_formal"
LOCAL_COLLECTION="$ROOT/prepared/pvrig_teacher_formal_v1_candidates"
FAST_DIR="$LOCAL_COLLECTION/fast_gate"
MODEL_INPUT_DIR="$LOCAL_COLLECTION/model_inputs"
MEANPOOL_DIR="$MODEL_INPUT_DIR/meanpool_embeddings"
TEACHER_DIR="$ROOT/data_splits/pvrig_teacher_formal_v1/teacher500"
PACKAGE_DIR="$ROOT/runs/pvrig_teacher_formal_v1/teacher500_docking_package"
REMOTE_PACKAGE="$REMOTE_BASE/teacher500_docking"

if [[ ! -x "$PY" ]]; then
  echo "Missing Phase2 environment: $PY" >&2
  exit 2
fi

read -r complete failed < <(
  "$SSH_COMMAND" "$NODE_HOST" \
    "ROOT='$REMOTE_GENERATION'; printf '%s ' \"\$(find \"\$ROOT/tasks\" -name complete.json | wc -l)\"; find \"\$ROOT/tasks\" -name failed.json | wc -l"
)
if [[ "$complete" != 240 || "$failed" != 0 ]]; then
  echo "RFantibody generation is not final: complete=$complete failed=$failed" >&2
  exit 3
fi

echo "[1/8] Collecting 8,640 raw RFantibody records on Node1"
"$SSH_COMMAND" "$NODE_HOST" "set -euo pipefail
  '$REMOTE_PY' '$REMOTE_BASE/collect_pvrig_formal_rfantibody_candidates.py' \
    --production-root '$REMOTE_GENERATION' \
    --tasks '$REMOTE_BASE/rfantibody_generation/manifests/tasks.tsv' \
    --parents '$REMOTE_BASE/rfantibody_generation/manifests/parent40_manifest.tsv' \
    --output-dir '$REMOTE_COLLECTION'"

echo "[2/8] Syncing the exact-deduplicated candidate table"
mkdir -p "$LOCAL_COLLECTION"
"$SSH_COMMAND" "$NODE_HOST" "cd '$REMOTE_COLLECTION' && tar -cf - \
  rfantibody_candidates_raw_v1.csv rfantibody_candidates_raw_v1.fasta \
  rfantibody_candidates_exact_dedup_v1.csv rfantibody_candidates_exact_dedup_v1.fasta \
  collection_audit_v1.json" | tar -xf - -C "$LOCAL_COLLECTION"

echo "[3/8] Applying local fast sequence and positive-leakage gates"
python "$ROOT/src/fast_gate_pvrig_formal_candidates.py" \
  --input "$LOCAL_COLLECTION/rfantibody_candidates_exact_dedup_v1.csv" \
  --output-dir "$FAST_DIR"

echo "[4/8] Preparing and embedding formal candidates for the frozen mean-pooled baseline"
python "$ROOT/src/prepare_pvrig_formal_candidate_meanpool_inputs.py" \
  --input "$FAST_DIR/fast_gate_all_v1.csv" \
  --output "$MODEL_INPUT_DIR/sequence_manifest_v3.csv"
"$PY" "$ROOT/src/prepare_phase2_v3_embeddings.py" \
  --sequence-manifest "$MODEL_INPUT_DIR/sequence_manifest_v3.csv" \
  --output-dir "$MEANPOOL_DIR" \
  --backend real --device cuda --vhhbert-batch-size 96 --esm-batch-size 192 --shard-size 1024

echo "[5/8] Scoring generic binding prior and three-seed uncertainty"
"$PY" "$ROOT/src/score_pvrig_formal_candidates_meanpool.py" \
  --input "$FAST_DIR/fast_gate_all_v1.csv" \
  --embedding-manifest "$MEANPOOL_DIR/embedding_manifest_v3.csv" \
  --output "$LOCAL_COLLECTION/scored_candidates_v1.csv" \
  --device cuda

echo "[6/8] Freezing the parent-balanced prospective Teacher500"
python "$ROOT/src/select_pvrig_formal_teacher500.py" \
  --input "$LOCAL_COLLECTION/scored_candidates_v1.csv" \
  --output-dir "$TEACHER_DIR"

echo "[7/8] Building the seven-shard Node1 monomer/HADDOCK package"
python "$ROOT/src/build_pvrig_formal_teacher500_package.py" \
  --selection "$TEACHER_DIR/pvrig_teacher500_manifest_v1.csv" \
  --outdir "$PACKAGE_DIR"

echo "[8/8] Transferring and verifying the frozen package on Node1"
"$SSH_COMMAND" "$NODE_HOST" "mkdir -p '$REMOTE_PACKAGE'"
tar -cf - -C "$PACKAGE_DIR" . | "$SSH_COMMAND" "$NODE_HOST" "tar -xf - -C '$REMOTE_PACKAGE'"
"$SSH_COMMAND" "$NODE_HOST" "set -euo pipefail; cd '$REMOTE_PACKAGE'; \
  tail -n +2 package_sha256.tsv | awk -F '\t' '{print \$1 \"  \" \$2}' | sha256sum -c -; \
  bash -n run_teacher500_controller.sh; \
  echo PASS_TEACHER500_REMOTE_PACKAGE_VERIFIED"

echo "PASS_PVRIG_FORMAL_TEACHER500_FINALIZED"
echo "Local package: $PACKAGE_DIR"
echo "Remote package: $NODE_HOST:$REMOTE_PACKAGE"
