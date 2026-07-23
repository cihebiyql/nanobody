#!/usr/bin/env bash
set -euo pipefail
umask 027

ROOT=/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722
PKG="$ROOT/code/c2_top30k_refinement_v1_20260722"
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
COARSE=/data1/qlyu/projects/pvrig_v2_11_canonical10644_c2_features_v1_20260721/code/coarse_pose_features_v1.py
TARGET_NPZ=/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graph_cache_v2.npz
TARGET_PDB8=/data1/qlyu/projects/pvrig_v2_11_canonical10644_c2_features_v1_20260721/inputs/pvrig_8x6b_chain_b.pdb
TARGET_PDB9=/data1/qlyu/projects/pvrig_v2_11_canonical10644_c2_features_v1_20260721/inputs/pvrig_9e6y_chain_a.pdb
ARTIFACT=/data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721/training/canonical10644_multimodal_v1/MODEL_ARTIFACT.pkl
VENDOR="$ROOT/code/src/run_v2_11_production_multimodal_inference_v1.py"
PRELIM="$ROOT/four_model_preliminary_top7500_v1"
STAGING="$ROOT/nbb2_staging_full150k_v1"
BASE="$ROOT/s0_m2_predictions_full150k_v1/PRODUCTION_PREDICTIONS_RANK_READY.tsv"
PLAN="$ROOT/c2_top30k_shard_plan_v1"
SHARDS="$ROOT/c2_top30k_shard_outputs_v1"
C2="$ROOT/c2_top30k_32d_v1"
PRED="$ROOT/c2_top30k_multimodal_predictions_v1"
FINAL="$ROOT/c2_refined_top7500_docking_handoff_v1"
MAX_PARALLEL="${MAX_PARALLEL:-32}"
[[ "$MAX_PARALLEL" =~ ^[0-9]+$ ]] && (( MAX_PARALLEL >= 1 && MAX_PARALLEL <= 32 ))
mkdir -p "$ROOT/status" "$ROOT/logs"

cat > "$ROOT/status/C2_TOP30K_REFINEMENT_WATCHER.json" <<JSON
{"status":"WAITING_FOR_FOUR_MODEL_PRELIMINARY","started_at":"$(date -u +%FT%TZ)","max_parallel":$MAX_PARALLEL}
JSON
for _ in $(seq 1 25920); do
  [[ -f "$ROOT/status/FOUR_MODEL_SELECTOR_TERMINAL.json" && -f "$ROOT/status/NBB2_STAGING_TERMINAL.json" && -f "$ROOT/status/M2_S0M2_TERMINAL.json" ]] && break
  sleep 10
done
[[ -f "$ROOT/status/FOUR_MODEL_SELECTOR_TERMINAL.json" && -f "$ROOT/status/NBB2_STAGING_TERMINAL.json" && -f "$ROOT/status/M2_S0M2_TERMINAL.json" ]]

sha256sum -c <<EOF
bcdf59054002eeaef2a9b6cfaac895a40d19b2bd2027c4ac02c93c260552fc8d  $PKG/PREREGISTRATION_V1.json
6017001d63b8c6464f4f0bbfb919ee9897586637f470b6041f0c6483f512cdb7  $PKG/src/build_top30k_c2_shards_v1.py
49e746031412f2da969a54b24017d9cc6b903e1dbf64374625600ca6ec652f2e  $PKG/src/merge_top30k_c2_features_v1.py
a263568b2372ca0a34f017bce493cc2ae68e3ff8d6e47361fab8acb1d7b735aa  $PKG/src/run_top30k_v2_11_c2_adapter_v1.py
764c2e3e393598f535f8dc9d2bbb63baa6928b296aabed9406385d9c91988389  $PKG/src/select_top7500_c2_refined_v1.py
d798b8079b9ecf56f80ee28ec52c371dd4f1a77ad43097fada1b515869a170ac  $PKG/tests/test_c2_top30k_refinement_v1.py
a87cda436379e768755f05aa0006c7a7dae8dd445a08b75339fc5a2bd0dfa591  $COARSE
e85730c752bc32602074d0171fd16c649cb26b34987917e9dd40ec14bdd69e4e  $VENDOR
b3081b7e91a5492f7765a721d9114dcb11f8ae095f40bfbcdcc3fe2b36edc108  $TARGET_NPZ
03af8f415847b8b6b246e787ec1e8d3cae4f024aa7bff6393ca344e0d7b02bcd  $TARGET_PDB8
a65a26f0a50c36765f29930cd425a566028d216864ce5d835595e6db5b3e334a  $TARGET_PDB9
02f71b30e70a3afe326d1a6f9b8fffb5c05fb1249a9c75ac8887b3ffadf5395d  $ARTIFACT
EOF

"$PY" -m unittest discover -s "$PKG/tests" -p 'test_*.py' -v > "$ROOT/logs/c2_top30k_tests_v1.log" 2>&1
"$PY" "$PKG/src/build_top30k_c2_shards_v1.py" \
  --stage1 "$PRELIM/STAGE1_TOP30000_FOR_C2.tsv" --preliminary-receipt "$PRELIM/RUN_RECEIPT.json" \
  --structure-manifest "$STAGING/top150k_m2_structure_manifest_v1.tsv" \
  --staging-receipt "$STAGING/top150k_nbb2_staging_receipt_v1.json" \
  --output-dir "$PLAN" --expected-rows 30000 --shards 32 > "$ROOT/logs/c2_top30k_plan_v1.log" 2>&1

mkdir "$SHARDS"
run_shard() {
  local manifest="$1" id out
  id="$(basename "$manifest" .tsv)"; out="$SHARDS/$id"; mkdir "$out"
  env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 "$PY" "$COARSE" \
    --candidate-manifest "$manifest" --target-npz "$TARGET_NPZ" --target-pdb8 "$TARGET_PDB8" --target-pdb9 "$TARGET_PDB9" \
    --output-tsv "$out/coarse_pose_features_36d.tsv" --receipt-json "$out/FEATURE_RECEIPT.json" \
    > "$ROOT/logs/c2_top30k_${id}.log" 2>&1
}
export -f run_shard; export SHARDS PY COARSE TARGET_NPZ TARGET_PDB8 TARGET_PDB9 ROOT
find "$PLAN/manifests" -maxdepth 1 -type f -name 'shard_*.tsv' -print0 | sort -z | xargs -0 -n1 -P "$MAX_PARALLEL" bash -c 'run_shard "$1"' _

PLAN_SHA="$(sha256sum "$PLAN/SHARD_PLAN.json" | awk '{print $1}')"
"$PY" "$PKG/src/merge_top30k_c2_features_v1.py" --plan "$PLAN/SHARD_PLAN.json" --expected-plan-sha256 "$PLAN_SHA" \
 --shard-output-root "$SHARDS" --target-npz "$TARGET_NPZ" --target-npz-sha256 b3081b7e91a5492f7765a721d9114dcb11f8ae095f40bfbcdcc3fe2b36edc108 \
 --target-pdb8 "$TARGET_PDB8" --target-pdb8-sha256 03af8f415847b8b6b246e787ec1e8d3cae4f024aa7bff6393ca344e0d7b02bcd \
 --target-pdb9 "$TARGET_PDB9" --target-pdb9-sha256 a65a26f0a50c36765f29930cd425a566028d216864ce5d835595e6db5b3e334a \
 --output-dir "$C2" --expected-rows 30000 > "$ROOT/logs/c2_top30k_merge_v1.log" 2>&1
C2_SHA="$(sha256sum "$C2/TOP30000_C2_32D.tsv" | awk '{print $1}')"
"$PY" "$PKG/src/run_top30k_v2_11_c2_adapter_v1.py" --stage1 "$PRELIM/STAGE1_TOP30000_FOR_C2.tsv" --base-predictions "$BASE" \
 --c2-features "$C2/TOP30000_C2_32D.tsv" --c2-features-sha256 "$C2_SHA" \
 --vendor-adapter "$VENDOR" --vendor-adapter-sha256 e85730c752bc32602074d0171fd16c649cb26b34987917e9dd40ec14bdd69e4e \
 --model-artifact "$ARTIFACT" --model-artifact-sha256 02f71b30e70a3afe326d1a6f9b8fffb5c05fb1249a9c75ac8887b3ffadf5395d \
 --output-dir "$PRED" --expected-rows 30000 > "$ROOT/logs/c2_top30k_multimodal_v1.log" 2>&1
"$PY" "$PKG/src/select_top7500_c2_refined_v1.py" --stage1 "$PRELIM/STAGE1_TOP30000_FOR_C2.tsv" \
 --c2 "$PRED/TOP30000_C2_MULTIMODAL_PREDICTIONS.tsv" --output-dir "$FINAL" --stage1-rows 30000 --final-rows 7500 \
 --exploitation 6750 --rescue 500 --diversity 250 > "$ROOT/logs/c2_refined_top7500_v1.log" 2>&1
cp "$FINAL/RUN_RECEIPT.json" "$ROOT/status/C2_REFINED_TOP7500_TERMINAL.json"
