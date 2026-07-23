#!/usr/bin/env bash
set -euo pipefail

DEPLOY=$(cd "$(dirname "$0")" && pwd)
PROJECT=pvrig_c2_only_missing6220_seed917_dual_handoff_v1_20260723
ARCHIVE="$HOME/$PROJECT.tar.zst"
MANIFEST="$HOME/$PROJECT.manifest.tsv"
ANCHORS="$DEPLOY/FROZEN_INPUT_ANCHORS.json"
ZSTD="$DEPLOY/zstd_bxcpu"

[[ -f "$ANCHORS" && ! -L "$ANCHORS" ]] || { echo sealed_input_anchors_missing >&2; exit 65; }
mapfile -t FROZEN < <(python3 - "$ANCHORS" "$DEPLOY/deployment_contract_v1.py" <<'PY'
import importlib.util,pathlib,sys
spec=importlib.util.spec_from_file_location("deployment_contract_v1",sys.argv[2])
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d=m.load_frozen_anchors(pathlib.Path(sys.argv[1]))
for key in ("archive_sha256","archive_bytes","job_manifest_sha256","deployment_bundle_receipt_sha256"):
 print(d[key])
PY
)
[[ ${#FROZEN[@]} -eq 4 ]] || { echo sealed_input_anchor_parse_failed >&2; exit 65; }
ARCHIVE_SHA=${FROZEN[0]}
ARCHIVE_BYTES=${FROZEN[1]}
MANIFEST_SHA=${FROZEN[2]}
BUNDLE_RECEIPT_SHA=${FROZEN[3]}

[[ -f "$ARCHIVE" && ! -L "$ARCHIVE" ]] || { echo missing_archive >&2; exit 65; }
[[ -f "$MANIFEST" && ! -L "$MANIFEST" ]] || { echo missing_manifest >&2; exit 65; }
[[ -x "$ZSTD" && ! -L "$ZSTD" ]] || { echo missing_zstd_bxcpu >&2; exit 65; }
[[ $(stat -c %s "$ARCHIVE") == "$ARCHIVE_BYTES" ]] || { echo archive_byte_count_mismatch >&2; exit 65; }
[[ $(sha256sum "$ARCHIVE" | awk '{print $1}') == "$ARCHIVE_SHA" ]] || { echo archive_hash_mismatch >&2; exit 65; }
[[ $(sha256sum "$MANIFEST" | awk '{print $1}') == "$MANIFEST_SHA" ]] || { echo manifest_hash_mismatch >&2; exit 65; }

TMP=$(mktemp -d "${TMPDIR:-/tmp}/pvrig-c2-preflight.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
"$ZSTD" -dc "$ARCHIVE" | tar -xOf - "$PROJECT/DEPLOYMENT_BUNDLE_RECEIPT.json" > "$TMP/DEPLOYMENT_BUNDLE_RECEIPT.json"
[[ $(sha256sum "$TMP/DEPLOYMENT_BUNDLE_RECEIPT.json" | awk '{print $1}') == "$BUNDLE_RECEIPT_SHA" ]] || {
  echo internal_bundle_receipt_hash_mismatch >&2; exit 65;
}
"$ZSTD" -dc "$ARCHIVE" | tar -xOf - "$PROJECT/manifests/docking_jobs.tsv" > "$TMP/docking_jobs.tsv"
[[ $(sha256sum "$TMP/docking_jobs.tsv" | awk '{print $1}') == "$MANIFEST_SHA" ]] || {
  echo internal_manifest_hash_mismatch >&2; exit 65;
}
python3 - "$DEPLOY/deployment_contract_v1.py" "$TMP/DEPLOYMENT_BUNDLE_RECEIPT.json" "$TMP/docking_jobs.tsv" <<'PY'
import importlib.util,json,pathlib,sys
spec=importlib.util.spec_from_file_location("deployment_contract_v1",sys.argv[1])
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
r=json.load(open(sys.argv[2])); fields,rows=m.read_tsv(pathlib.Path(sys.argv[3]))
assert r["status"]=="SEALED_FOR_BXCPU_UPLOAD_NOT_SUBMITTED"
assert r["project"]==m.PROJECT and r["candidates"]==6220 and r["jobs"]==12440
assert r["shard_sizes"]==[1555]*8
assert r["docking_started"] is False and r["overlap1280_reuse_authorized"] is False
m.validate_manifest_rows(rows)
PY

for file in haddock3_runtime_core.tar.gz haddock3_runtime_python.tar.gz haddock3_runtime_lib.tar.gz \
            haddock3_source_2025.11.0.tar.gz numpy_el7_overlay_2.0.1.tar.gz; do
  [[ -s "$HOME/.local/opt/$file" ]] || { echo "missing runtime $file" >&2; exit 65; }
done
[[ $(squeue -h -u "$USER" -n pvrig-c2-gap-12440 | wc -l) -eq 0 ]] || { echo active_campaign_exists >&2; exit 66; }
sbatch --test-only --partition=amd_256q --nodes=1 --ntasks=1 --cpus-per-task=64 --mem=230G \
  --exclusive --time=24:00:00 --array=1-8%8 "$DEPLOY/bxcpu_c2_missing6220_eight_node_worker.sh" >/dev/null
printf 'PREFLIGHT=PASS archive_sha256=%s manifest_sha256=%s nodes=8 jobs=12440 shard_jobs=1555 docking_started=false\n' \
  "$ARCHIVE_SHA" "$MANIFEST_SHA"
