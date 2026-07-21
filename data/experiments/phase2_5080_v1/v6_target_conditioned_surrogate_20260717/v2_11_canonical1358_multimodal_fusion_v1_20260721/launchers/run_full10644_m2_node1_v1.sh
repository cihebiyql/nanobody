#!/usr/bin/env bash
set -euo pipefail
umask 027

# This launcher writes only under the versioned /data1 project root. The V4I
# and V4D monomer inputs remain read-only on /data; only their derived M2 table
# is materialized on /data1.
ROOT=/data1/qlyu/projects/pvrig_v2_11_canonical10644_m2_features_v1_20260721
CODE_ROOT="$ROOT/code"
OUT="$ROOT/full10644_features"
LOG="$ROOT/logs/materialize_full10644_m2_v1.log"
STATUS="$ROOT/status"
PYTHON=/data1/qlyu/pvrig_node1_cpu_offload_20260717/env/bin/python3.11

TEACHER=/data1/qlyu/projects/pvrig_v29_canonical_merged_teacher_v1_20260721/prepared/primary_D1_canonical10644_teacher.tsv
SPLIT=/data1/qlyu/projects/pvrig_v29_canonical_merged_teacher_v1_20260721/prepared/primary_D1_canonical10644_split_manifest.json
V29=/data1/qlyu/projects/pvrig_v2_9_monomers10k_v1_20260720/full10k/outputs/monomer_manifest.tsv
V4I_ROOT=/data/qlyu/projects/pvrig_v4_i_round2_combined_docking_input_v1_1_20260718
V4I="$V4I_ROOT/monomer_manifest.tsv"
V4H_ROOT=/data1/qlyu/projects/pvrig_v4_h_research_pool_v1_20260717/docking_input_full_v1
V4H="$V4H_ROOT/monomer_manifest.tsv"
V4D_ROOT=/data/qlyu/projects/pvrig_v4_d_open258_structure_inputs_v1_20260717/release
V4D="$V4D_ROOT/outputs/open258_structure_manifest_v1.tsv"

TEACHER_SHA=46bc32276a574e21bb92d7e6672b18aa68323c778b4f65d2415a384144ab95c3
SPLIT_SHA=9dc416dcf8694f321a5432ba8574f0229c03527af14926fcf2f43ee4211f07ed
V29_SHA=ca7a7e8aa784ddf7c0f9079d3700c5098159e1fd599253ea64ade04a2cb3fe9f
V4I_SHA=869b345f4aa4ede80869ccc178f638d9fa727709b01addc8da6b0533e5c3c2b8
V4H_SHA=e74b32d53d7a1fb2719d8b7e01b60bb2855553794607f011e14e0f5399fa8137
V4D_SHA=893556640293d15a240158d487c8607a4326b55dd7af5ece46aeb4f3890bf03c

BUILDER="$CODE_ROOT/build_full10644_structure_manifest_v1.py"
MATERIALIZER="$CODE_ROOT/materialize_full10644_m2_features_v1.py"
TEST="$CODE_ROOT/test_full10644_structure_m2_v1.py"
BUILDER_SHA=1b8746a48d07771979c4bdd05df5f491089de0770296b91da31250644f80f563
MATERIALIZER_SHA=12575c6061a2885d9cc8625988291a6d1460d7ab85bf0e5b5b417a520c5c38dc
TEST_SHA=124b9771018f6592c53543254dc65ec58db71a40da675e924642ee8ddf446faf

mkdir -p "$ROOT/logs" "$STATUS"
exec > >(tee -a "$LOG") 2>&1

[[ -x "$PYTHON" ]]
[[ ! -e "$OUT" ]]
for path in "$BUILDER" "$MATERIALIZER" "$TEST" "$TEACHER" "$SPLIT" "$V29" "$V4I" "$V4H" "$V4D"; do
  [[ -f "$path" && ! -L "$path" ]]
done

printf '%s  %s\n' \
  "$BUILDER_SHA" "$BUILDER" \
  "$MATERIALIZER_SHA" "$MATERIALIZER" \
  "$TEST_SHA" "$TEST" \
  "$TEACHER_SHA" "$TEACHER" \
  "$SPLIT_SHA" "$SPLIT" \
  "$V29_SHA" "$V29" \
  "$V4I_SHA" "$V4I" \
  "$V4H_SHA" "$V4H" \
  "$V4D_SHA" "$V4D" | sha256sum --check --strict

"$PYTHON" "$TEST" -v

"$PYTHON" "$BUILDER" \
  --teacher-tsv "$TEACHER" --teacher-sha256 "$TEACHER_SHA" \
  --split-manifest "$SPLIT" --split-sha256 "$SPLIT_SHA" \
  --v29-manifest "$V29" --v29-root / --v29-manifest-sha256 "$V29_SHA" \
  --v4i-manifest "$V4I" --v4i-root "$V4I_ROOT" --v4i-manifest-sha256 "$V4I_SHA" \
  --v4h-manifest "$V4H" --v4h-root "$V4H_ROOT" --v4h-manifest-sha256 "$V4H_SHA" \
  --v4d-manifest "$V4D" --v4d-root "$V4D_ROOT" --v4d-manifest-sha256 "$V4D_SHA" \
  --output-dir "$OUT" --expected-rows 10644

STRUCTURE_MANIFEST="$OUT/canonical10644_structure_manifest_v1.tsv"
STRUCTURE_SHA="$(sha256sum "$STRUCTURE_MANIFEST" | awk '{print $1}')"

"$PYTHON" "$MATERIALIZER" \
  --input-manifest "$STRUCTURE_MANIFEST" \
  --expected-manifest-sha256 "$STRUCTURE_SHA" \
  --output-dir "$OUT" --expected-rows 10644 --workers 32

"$PYTHON" - "$OUT" "$STATUS/TERMINAL.json" <<'PY'
import hashlib, json, pathlib, sys
out = pathlib.Path(sys.argv[1])
terminal = pathlib.Path(sys.argv[2])
files = [
    out / "canonical10644_structure_manifest_v1.tsv",
    out / "canonical10644_structure_manifest_v1.receipt.json",
    out / "canonical10644_m2_126d_features_v1.tsv",
    out / "canonical10644_m2_126d_features_v1.receipt.json",
]
payload = {
    "schema_version": "pvrig_v2_11_full10644_m2_node1_terminal_v1",
    "status": "PASS_FULL10644_M2_TERMINAL",
    "outputs": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
    "claim_boundary": "Label-free monomer M2 features only; no C2, training, Docking pose, or target values consumed.",
}
terminal.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY

cat "$STATUS/TERMINAL.json"
