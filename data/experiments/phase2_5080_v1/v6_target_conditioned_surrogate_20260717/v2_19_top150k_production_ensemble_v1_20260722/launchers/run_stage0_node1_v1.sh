#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722
CODE="$ROOT/code"
SOURCE=/data/qlyu/projects/pvrig_1m_fixed_pose_top150k_multimetric_v2_20260722/fixed_pose_top150k_multimetric.tsv.gz
OUTPUT="$ROOT/stage0_label_free_priors_v1"
STATUS="$ROOT/status"
LOG="$ROOT/logs/stage0_label_free_priors_v1.log"
EXPECTED_SOURCE=105bed3b7542a6f1b4d3bbf609101c7ed254be776ca2a3fdacc3c2cc695e88e0
EXPECTED_SCRIPT=88f05b81ed2f62b861b659792a6a8c79b7a72dd8846d4bb91cce39470e88367f

mkdir -p "$STATUS" "$ROOT/logs"
[[ "$(sha256sum "$SOURCE" | awk '{print $1}')" == "$EXPECTED_SOURCE" ]]
[[ "$(sha256sum "$CODE/src/materialize_top150k_stage0_priors_v1.py" | awk '{print $1}')" == "$EXPECTED_SCRIPT" ]]
[[ ! -e "$OUTPUT" ]]

cat > "$STATUS/STAGE0_LAUNCH_RECEIPT.json" <<JSON
{
  "status": "RUNNING_STAGE0_LABEL_FREE_PRIORS",
  "source_sha256": "$EXPECTED_SOURCE",
  "script_sha256": "$EXPECTED_SCRIPT",
  "output": "$OUTPUT",
  "started_at": "$(date -u +%FT%TZ)"
}
JSON

python3 "$CODE/src/materialize_top150k_stage0_priors_v1.py" \
  --input "$SOURCE" \
  --expected-sha256 "$EXPECTED_SOURCE" \
  --expected-rows 150000 \
  --broad-pool-rows 45000 \
  --output-dir "$OUTPUT" > "$LOG" 2>&1

python3 - "$OUTPUT/RUN_RECEIPT.json" "$STATUS/STAGE0_TERMINAL.json" <<'PY'
import json,sys
source,target=sys.argv[1:]
payload=json.load(open(source))
payload["terminal_status"]="PASS_STAGE0_COMPLETE"
open(target,"w").write(json.dumps(payload,indent=2,sort_keys=True)+"\n")
PY
