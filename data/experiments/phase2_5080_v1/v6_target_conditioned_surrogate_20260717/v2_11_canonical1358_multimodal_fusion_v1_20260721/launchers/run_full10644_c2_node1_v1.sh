#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_v2_11_canonical10644_c2_features_v1_20260721
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
SOURCE=/data1/qlyu/projects/pvrig_v2_11_canonical10644_m2_features_v1_20260721/full10644_features/canonical10644_structure_manifest_v1.tsv
SOURCE_SHA=9d9324260b2d91baf990ea6ffd443d8c5fb3629181252eab7a4c295543113327
TARGET_NPZ=/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graph_cache_v2.npz
TARGET_NPZ_SHA=b3081b7e91a5492f7765a721d9114dcb11f8ae095f40bfbcdcc3fe2b36edc108
TARGET_PDB8=$ROOT/inputs/pvrig_8x6b_chain_b.pdb
TARGET_PDB8_SHA=03af8f415847b8b6b246e787ec1e8d3cae4f024aa7bff6393ca344e0d7b02bcd
TARGET_PDB9=$ROOT/inputs/pvrig_9e6y_chain_a.pdb
TARGET_PDB9_SHA=a65a26f0a50c36765f29930cd425a566028d216864ce5d835595e6db5b3e334a
PLAN_ROOT=$ROOT/shard_plan_v1
SHARD_ROOT=$ROOT/shard_outputs_v1
FINAL_ROOT=$ROOT/full10644_features
STATUS_ROOT=$ROOT/status
LOG_ROOT=$ROOT/logs
SHARDS=32

mkdir -p "$STATUS_ROOT" "$LOG_ROOT" "$SHARD_ROOT"

sha256sum -c <<EOF
$SOURCE_SHA  $SOURCE
$TARGET_NPZ_SHA  $TARGET_NPZ
$TARGET_PDB8_SHA  $TARGET_PDB8
$TARGET_PDB9_SHA  $TARGET_PDB9
EOF

"$PY" -m unittest discover -s "$ROOT/tests" -p 'test_full10644_coarse_pose_sharding_v1.py' -v

if [[ ! -f "$PLAN_ROOT/SHARD_PLAN.json" ]]; then
  "$PY" "$ROOT/src/prepare_full10644_coarse_pose_shards_v1.py" \
    --input-manifest "$SOURCE" \
    --expected-manifest-sha256 "$SOURCE_SHA" \
    --output-dir "$PLAN_ROOT" \
    --expected-rows 10644 \
    --shards "$SHARDS"
fi
PLAN=$PLAN_ROOT/SHARD_PLAN.json
PLAN_SHA=$(sha256sum "$PLAN" | awk '{print $1}')

pids=()
for shard_index in $(seq 0 $((SHARDS - 1))); do
  shard_id=$(printf 'shard_%03d' "$shard_index")
  manifest=$PLAN_ROOT/manifests/${shard_id}.tsv
  out=$SHARD_ROOT/$shard_id
  mkdir -p "$out"
  (
    exec env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
      "$PY" "$ROOT/code/coarse_pose_features_v1.py" \
        --candidate-manifest "$manifest" \
        --target-npz "$TARGET_NPZ" \
        --target-pdb8 "$TARGET_PDB8" \
        --target-pdb9 "$TARGET_PDB9" \
        --output-tsv "$out/coarse_pose_features_36d.tsv" \
        --receipt-json "$out/FEATURE_RECEIPT.json"
  ) >"$LOG_ROOT/${shard_id}.log" 2>&1 &
  pids+=("$!")
done

failed=0
for index in "${!pids[@]}"; do
  if ! wait "${pids[$index]}"; then
    printf 'shard_%03d failed\n' "$index" >&2
    failed=1
  fi
done
if [[ "$failed" -ne 0 ]]; then
  printf '{"status":"FAIL_FULL10644_C2_SHARD_EXECUTION"}\n' > "$STATUS_ROOT/TERMINAL.json"
  exit 1
fi

"$PY" "$ROOT/src/merge_full10644_coarse_pose_shards_v1.py" \
  --plan-json "$PLAN" \
  --expected-plan-sha256 "$PLAN_SHA" \
  --shard-output-root "$SHARD_ROOT" \
  --target-npz "$TARGET_NPZ" \
  --target-npz-sha256 "$TARGET_NPZ_SHA" \
  --target-pdb8 "$TARGET_PDB8" \
  --target-pdb8-sha256 "$TARGET_PDB8_SHA" \
  --target-pdb9 "$TARGET_PDB9" \
  --target-pdb9-sha256 "$TARGET_PDB9_SHA" \
  --output-dir "$FINAL_ROOT" \
  --expected-rows 10644

"$PY" - "$FINAL_ROOT" "$PLAN_SHA" > "$STATUS_ROOT/TERMINAL.json" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
plan_sha = sys.argv[2]
files = sorted(path for path in root.iterdir() if path.is_file())
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
print(json.dumps({
    "schema_version": "pvrig_v2_11_full10644_c2_node1_terminal_v1",
    "status": "PASS_FULL10644_C2_TERMINAL",
    "claim_boundary": "Label-free monomer/fixed-target coarse rigid-body features only; no candidate Docking pose or teacher label consumed.",
    "shard_plan_sha256": plan_sha,
    "outputs": {str(path): sha(path) for path in files},
}, indent=2, sort_keys=True))
PY
