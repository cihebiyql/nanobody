#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722
SOURCE=/data/qlyu/projects/pvrig_1m_fixed_pose_top150k_multimetric_v2_20260722/fixed_pose_top150k_multimetric.tsv.gz
SCRIPT="$ROOT/code/src/stage_top150k_nbb2_archives_v1.py"
PDB_ROOT="$ROOT/nbb2_pdbs_full150k_v1"
OUTPUT="$ROOT/nbb2_staging_full150k_v1"
EXPECTED_SOURCE=105bed3b7542a6f1b4d3bbf609101c7ed254be776ca2a3fdacc3c2cc695e88e0

mkdir -p "$ROOT/status" "$ROOT/logs"
[[ "$(sha256sum "$SOURCE" | awk '{print $1}')" == "$EXPECTED_SOURCE" ]]
[[ -f "$SCRIPT" ]]
[[ ! -e "$OUTPUT/top150k_nbb2_staging_receipt_v1.json" ]]

cat > "$ROOT/status/NBB2_STAGING_LAUNCH_RECEIPT.json" <<JSON
{"status":"RUNNING_NBB2_STAGING_FULL150K","workers":32,"pdb_root":"$PDB_ROOT","started_at":"$(date -u +%FT%TZ)"}
JSON

python3 "$SCRIPT" \
  --source-tsv-gz "$SOURCE" \
  --pdb-root "$PDB_ROOT" \
  --output-dir "$OUTPUT" \
  --expected-rows 150000 \
  --workers 32 \
  --require-expected-archive-sha256 > "$ROOT/logs/nbb2_staging_full150k_v1.log" 2>&1

python3 - "$OUTPUT/top150k_nbb2_staging_receipt_v1.json" "$ROOT/status/NBB2_STAGING_TERMINAL.json" <<'PY'
import json,sys
source,target=sys.argv[1:]
payload=json.load(open(source))
assert payload["status"]=="PASS_TOP150K_LABEL_FREE_NBB2_ARCHIVE_STAGING"
assert payload["counts"]["candidates"]==150000
payload["terminal_status"]="PASS_NBB2_STAGING_FULL150K_COMPLETE"
open(target,"w").write(json.dumps(payload,indent=2,sort_keys=True)+"\n")
PY
