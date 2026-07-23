#!/usr/bin/env bash
set -euo pipefail
umask 027

ROOT=/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722
PKG="$ROOT/code/c2_top30k_publication_verifier_v1_20260723"
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
COARSE=/data1/qlyu/projects/pvrig_v2_11_canonical10644_c2_features_v1_20260721/code/coarse_pose_features_v1.py
VENDOR="$ROOT/code/src/run_v2_11_production_multimodal_inference_v1.py"
ARTIFACT=/data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721/training/canonical10644_multimodal_v1/MODEL_ARTIFACT.pkl
TARGET_NPZ=/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graph_cache_v2.npz
TARGET_PDB8=/data1/qlyu/projects/pvrig_v2_11_canonical10644_c2_features_v1_20260721/inputs/pvrig_8x6b_chain_b.pdb
TARGET_PDB9=/data1/qlyu/projects/pvrig_v2_11_canonical10644_c2_features_v1_20260721/inputs/pvrig_9e6y_chain_a.pdb
VERIFY_ROOT="$ROOT/c2_refined_top7500_publication_verification_v1"
OUT="$VERIFY_ROOT/C2_REFINED_TOP7500_PUBLICATION_VERIFIED.json"
STATUS="$ROOT/status/C2_REFINED_TOP7500_PUBLICATION_VERIFIED.json"
WATCHER="$ROOT/status/C2_REFINED_TOP7500_PUBLICATION_VERIFIER_WATCHER.json"
mkdir -p "$ROOT/status" "$ROOT/logs"

cat > "$WATCHER" <<JSON
{"status":"WAITING_FOR_C2_REFINED_TOP7500_TERMINAL","started_at":"$(date -u +%FT%TZ)","failure_policy":"FAIL_CLOSED_NO_AUTOMATIC_CLEANUP"}
JSON
for _ in $(seq 1 25920); do
  [[ -f "$ROOT/status/C2_REFINED_TOP7500_TERMINAL.json" ]] && break
  sleep 10
done
[[ -f "$ROOT/status/C2_REFINED_TOP7500_TERMINAL.json" ]]
[[ ! -e "$VERIFY_ROOT" && ! -e "$STATUS" ]]

sha256sum -c <<EOF
eb016a0fc3256ea53b013e6e42833ede86622afb3b935e09575aa20cfaf9183b  $PKG/PREREGISTRATION_V1.json
045ab3552d016705ece7258bfb71e831af6bce0f1f0e79712bf5a32eac0e9384  $PKG/src/verify_c2_refined_top7500_publication_v1.py
5bad9dc586ca1002b95b135e143a471d962aa2b69adf47d2d49c662127a628aa  $PKG/tests/test_verify_c2_refined_top7500_publication_v1.py
a87cda436379e768755f05aa0006c7a7dae8dd445a08b75339fc5a2bd0dfa591  $COARSE
e85730c752bc32602074d0171fd16c649cb26b34987917e9dd40ec14bdd69e4e  $VENDOR
02f71b30e70a3afe326d1a6f9b8fffb5c05fb1249a9c75ac8887b3ffadf5395d  $ARTIFACT
b3081b7e91a5492f7765a721d9114dcb11f8ae095f40bfbcdcc3fe2b36edc108  $TARGET_NPZ
03af8f415847b8b6b246e787ec1e8d3cae4f024aa7bff6393ca344e0d7b02bcd  $TARGET_PDB8
a65a26f0a50c36765f29930cd425a566028d216864ce5d835595e6db5b3e334a  $TARGET_PDB9
EOF

"$PY" -m unittest discover -s "$PKG/tests" -p 'test_*.py' -v \
  > "$ROOT/logs/c2_top7500_publication_verifier_tests_v1.log" 2>&1
mkdir "$VERIFY_ROOT"
cat > "$WATCHER" <<JSON
{"status":"RUNNING_RECURSIVE_PUBLICATION_VERIFICATION","started_at":"$(date -u +%FT%TZ)","failure_policy":"FAIL_CLOSED_NO_AUTOMATIC_CLEANUP"}
JSON
"$PY" "$PKG/src/verify_c2_refined_top7500_publication_v1.py" \
  --runtime-root "$ROOT" \
  --coarse-code "$COARSE" --coarse-code-sha256 a87cda436379e768755f05aa0006c7a7dae8dd445a08b75339fc5a2bd0dfa591 \
  --vendor-adapter "$VENDOR" --vendor-adapter-sha256 e85730c752bc32602074d0171fd16c649cb26b34987917e9dd40ec14bdd69e4e \
  --model-artifact "$ARTIFACT" --model-artifact-sha256 02f71b30e70a3afe326d1a6f9b8fffb5c05fb1249a9c75ac8887b3ffadf5395d \
  --target-npz "$TARGET_NPZ" --target-npz-sha256 b3081b7e91a5492f7765a721d9114dcb11f8ae095f40bfbcdcc3fe2b36edc108 \
  --target-pdb8 "$TARGET_PDB8" --target-pdb8-sha256 03af8f415847b8b6b246e787ec1e8d3cae4f024aa7bff6393ca344e0d7b02bcd \
  --target-pdb9 "$TARGET_PDB9" --target-pdb9-sha256 a65a26f0a50c36765f29930cd425a566028d216864ce5d835595e6db5b3e334a \
  --stage1-rows 30000 --shards 32 --final-rows 7500 --output-json "$OUT" \
  > "$ROOT/logs/c2_top7500_publication_verification_v1.log" 2>&1
sha256sum "$OUT" > "$VERIFY_ROOT/SHA256SUMS"
tmp="$ROOT/status/.C2_REFINED_TOP7500_PUBLICATION_VERIFIED.json.$$"
cp "$OUT" "$tmp"
mv "$tmp" "$STATUS"
cat > "$WATCHER" <<JSON
{"status":"PASS_C2_REFINED_TOP7500_PUBLICATION_VERIFIED","completed_at":"$(date -u +%FT%TZ)","publication_receipt":"$STATUS","failure_policy":"FAIL_CLOSED_NO_AUTOMATIC_CLEANUP"}
JSON
