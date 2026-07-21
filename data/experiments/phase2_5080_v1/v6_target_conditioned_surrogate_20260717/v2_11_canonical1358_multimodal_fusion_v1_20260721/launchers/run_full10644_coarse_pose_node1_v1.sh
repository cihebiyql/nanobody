#!/usr/bin/env bash
set -euo pipefail
umask 027

SHARDS="${SHARDS:-32}"
MAX_PARALLEL="${MAX_PARALLEL:-16}"
[[ "$SHARDS" =~ ^[0-9]+$ && "$MAX_PARALLEL" =~ ^[0-9]+$ ]]
(( SHARDS >= 16 && SHARDS <= 32 ))
(( MAX_PARALLEL >= 16 && MAX_PARALLEL <= 32 && MAX_PARALLEL <= SHARDS ))

ROOT=/data1/qlyu/projects/pvrig_v2_11_canonical10644_coarse_pose_features_v1_20260721
CODE_ROOT="$ROOT/code"
PLAN_ROOT="$ROOT/shard_plan"
SHARD_OUTPUT_ROOT="$ROOT/shard_outputs"
MERGED_ROOT="$ROOT/full10644_features"
STATUS_ROOT="$ROOT/status"
LOG="$ROOT/logs/materialize_full10644_coarse_pose_v1.log"
PYTHON=/data1/qlyu/pvrig_node1_cpu_offload_20260717/env/bin/python3.11
UPSTREAM_ROOT=/data1/qlyu/projects/pvrig_v2_11_canonical10644_m2_features_v1_20260721
UPSTREAM_TERMINAL="$UPSTREAM_ROOT/status/TERMINAL.json"
STRUCTURE_MANIFEST="$UPSTREAM_ROOT/full10644_features/canonical10644_structure_manifest_v1.tsv"
STRUCTURE_RECEIPT="$UPSTREAM_ROOT/full10644_features/canonical10644_structure_manifest_v1.receipt.json"
TARGET_NPZ=/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graph_cache_v2.npz
TARGET_PDB8="$ROOT/inputs/fixed_targets/pvrig_8x6b_chain_b.pdb"
TARGET_PDB9="$ROOT/inputs/fixed_targets/pvrig_9e6y_chain_a.pdb"
TARGET_NPZ_SHA=b3081b7e91a5492f7765a721d9114dcb11f8ae095f40bfbcdcc3fe2b36edc108
TARGET_PDB8_SHA=03af8f415847b8b6b246e787ec1e8d3cae4f024aa7bff6393ca344e0d7b02bcd
TARGET_PDB9_SHA=a65a26f0a50c36765f29930cd425a566028d216864ce5d835595e6db5b3e334a
COARSE="$CODE_ROOT/frozen/coarse_pose_features_v1.py"
PLANNER="$CODE_ROOT/src/prepare_full10644_coarse_pose_shards_v1.py"
MERGER="$CODE_ROOT/src/merge_full10644_coarse_pose_shards_v1.py"
TEST="$CODE_ROOT/tests/test_full10644_coarse_pose_sharding_v1.py"
COARSE_SHA=a87cda436379e768755f05aa0006c7a7dae8dd445a08b75339fc5a2bd0dfa591
PLANNER_SHA=9e469327d9ab0e74577f79eb303c542636a328d68d6da040b207e53d1d739c74
MERGER_SHA=ef602091701d759ef1d36899f33cbeb8500ba0af9c070ccc0296e6856ac4fa16
TEST_SHA=9ff1359ef6842fd6405d76a9e6d0e403f4a25e23adeeb492ddc583fed4b7ac9f

mkdir -p "$ROOT/logs" "$STATUS_ROOT"
exec > >(tee -a "$LOG") 2>&1
[[ -x "$PYTHON" ]]
for path in "$COARSE" "$PLANNER" "$MERGER" "$TEST" "$UPSTREAM_TERMINAL" \
            "$STRUCTURE_MANIFEST" "$STRUCTURE_RECEIPT" "$TARGET_NPZ" "$TARGET_PDB8" "$TARGET_PDB9"; do
  [[ -f "$path" && ! -L "$path" ]]
done
for path in "$PLAN_ROOT" "$SHARD_OUTPUT_ROOT" "$MERGED_ROOT" "$STATUS_ROOT/TERMINAL.json"; do
  [[ ! -e "$path" && ! -L "$path" ]]
done
printf '%s  %s\n' \
  "$COARSE_SHA" "$COARSE" "$PLANNER_SHA" "$PLANNER" "$MERGER_SHA" "$MERGER" "$TEST_SHA" "$TEST" \
  "$TARGET_NPZ_SHA" "$TARGET_NPZ" "$TARGET_PDB8_SHA" "$TARGET_PDB8" "$TARGET_PDB9_SHA" "$TARGET_PDB9" \
  | sha256sum --check --strict

STRUCTURE_SHA="$("$PYTHON" - "$UPSTREAM_TERMINAL" "$STRUCTURE_MANIFEST" "$STRUCTURE_RECEIPT" <<'PY'
import hashlib, json, pathlib, sys
terminal_path, manifest_path, receipt_path = map(pathlib.Path, sys.argv[1:])
terminal = json.loads(terminal_path.read_text())
if terminal.get("status") != "PASS_FULL10644_M2_TERMINAL":
    raise SystemExit("upstream_terminal_not_pass")
actual_manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
actual_receipt_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
outputs = terminal.get("outputs", {})
if outputs.get(str(manifest_path)) != actual_manifest_sha:
    raise SystemExit("upstream_terminal_manifest_sha_mismatch")
if outputs.get(str(receipt_path)) != actual_receipt_sha:
    raise SystemExit("upstream_terminal_receipt_sha_mismatch")
receipt = json.loads(receipt_path.read_text())
if receipt.get("status") != "PASS_CANONICAL10644_LABEL_FREE_MONOMER_CLOSURE":
    raise SystemExit("upstream_structure_receipt_not_pass")
if receipt.get("output", {}).get("sha256") != actual_manifest_sha:
    raise SystemExit("upstream_structure_receipt_manifest_sha_mismatch")
if receipt.get("counts", {}).get("candidates") != 10644:
    raise SystemExit("upstream_structure_candidate_count_mismatch")
print(actual_manifest_sha)
PY
)"

"$PYTHON" "$TEST" -v
"$PYTHON" "$PLANNER" --input-manifest "$STRUCTURE_MANIFEST" \
  --expected-manifest-sha256 "$STRUCTURE_SHA" --output-dir "$PLAN_ROOT" \
  --expected-rows 10644 --shards "$SHARDS"
PLAN_JSON="$PLAN_ROOT/SHARD_PLAN.json"
PLAN_SHA="$(sha256sum "$PLAN_JSON" | awk '{print $1}')"
MANIFEST_COUNT="$(find "$PLAN_ROOT/manifests" -maxdepth 1 -type f -name 'shard_*.tsv' | wc -l)"
[[ "$MANIFEST_COUNT" -eq "$SHARDS" ]]
mkdir "$SHARD_OUTPUT_ROOT"

run_coarse_pose_shard() {
  local manifest="$1" shard_id output_dir
  shard_id="$(basename "$manifest" .tsv)"
  output_dir="$SHARD_OUTPUT_ROOT/$shard_id"
  mkdir "$output_dir"
  "$PYTHON" "$COARSE" --candidate-manifest "$manifest" --target-npz "$TARGET_NPZ" \
    --target-pdb8 "$TARGET_PDB8" --target-pdb9 "$TARGET_PDB9" \
    --output-tsv "$output_dir/coarse_pose_features_36d.tsv" \
    --receipt-json "$output_dir/FEATURE_RECEIPT.json"
}
export -f run_coarse_pose_shard
export SHARD_OUTPUT_ROOT PYTHON COARSE TARGET_NPZ TARGET_PDB8 TARGET_PDB9
find "$PLAN_ROOT/manifests" -maxdepth 1 -type f -name 'shard_*.tsv' -print0 \
  | sort -z | xargs -0 -r -n 1 -P "$MAX_PARALLEL" bash -c 'run_coarse_pose_shard "$1"' _

"$PYTHON" "$MERGER" --plan-json "$PLAN_JSON" --expected-plan-sha256 "$PLAN_SHA" \
  --shard-output-root "$SHARD_OUTPUT_ROOT" \
  --target-npz "$TARGET_NPZ" --target-npz-sha256 "$TARGET_NPZ_SHA" \
  --target-pdb8 "$TARGET_PDB8" --target-pdb8-sha256 "$TARGET_PDB8_SHA" \
  --target-pdb9 "$TARGET_PDB9" --target-pdb9-sha256 "$TARGET_PDB9_SHA" \
  --output-dir "$MERGED_ROOT" --expected-rows 10644

"$PYTHON" - "$PLAN_JSON" "$MERGED_ROOT" "$STATUS_ROOT/TERMINAL.json" \
  "$STRUCTURE_SHA" "$TARGET_NPZ_SHA" "$TARGET_PDB8_SHA" "$TARGET_PDB9_SHA" <<'PY'
import hashlib, json, pathlib, sys
plan, merged, terminal = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
structure_sha, npz_sha, pdb8_sha, pdb9_sha = sys.argv[4:]
table = merged / "canonical10644_coarse_pose_features_36d_v1.tsv"
receipt_path = merged / "canonical10644_coarse_pose_features_36d_v1.receipt.json"
receipt = json.loads(receipt_path.read_text())
if receipt.get("status") != "PASS_CANONICAL10644_COARSE_POSE_36D_SHARD_CLOSURE":
    raise SystemExit("merge_receipt_not_pass")
files = [plan, table, receipt_path]
payload = {
    "schema_version": "pvrig_v2_11_full10644_coarse_pose_node1_terminal_v1",
    "status": "PASS_FULL10644_COARSE_POSE_TERMINAL",
    "inputs": {
        "structure_manifest_sha256": structure_sha, "target_npz_sha256": npz_sha,
        "target_pdb8_sha256": pdb8_sha, "target_pdb9_sha256": pdb9_sha,
    },
    "outputs": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
    "claim_boundary": "Frozen V2.5 label-free coarse-pose 36D features only; no model training or performance claim.",
}
terminal.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY
cat "$STATUS_ROOT/TERMINAL.json"
