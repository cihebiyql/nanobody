#!/usr/bin/env bash
set -euo pipefail

DEPLOY=$(cd "$(dirname "$0")" && pwd)
PROJECT=pvrig_c2_only_missing6220_seed917_dual_handoff_v1_20260723
MANIFEST="$HOME/$PROJECT.manifest.tsv"
PUBLISH_ROOT="${PVRIG_C2_PUBLISH_ROOT:-$HOME/${PROJECT}_bxcpu_results}"
ANCHORS="$DEPLOY/FROZEN_INPUT_ANCHORS.json"
OUTPUT="$PUBLISH_ROOT/reports_v2/TECHNICAL_COMPLETION_V2.json"
PYTHON="$HOME/.local/opt/haddock3-2025.11.0/bin/python"

test -x "$PYTHON"
EXPECTED_SHA=$(
  "$PYTHON" - "$ANCHORS" "$DEPLOY/deployment_contract_v1.py" <<'PY'
import importlib.util,pathlib,sys
spec=importlib.util.spec_from_file_location("deployment_contract_v1",sys.argv[2])
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.load_frozen_anchors(pathlib.Path(sys.argv[1]))["job_manifest_sha256"])
PY
)
"$PYTHON" "$DEPLOY/technical_status_c2_missing6220_v2.py" \
  --manifest "$MANIFEST" --publish-root "$PUBLISH_ROOT" --expected-count 12440 \
  --expected-manifest-sha256 "$EXPECTED_SHA" --output "$OUTPUT"

"$PYTHON" - "$OUTPUT" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert d["status"] in {"COMPLETE_WITH_TECHNICAL_NA","INCOMPLETE"}
assert d["overlap1280_reuse_authorized"] is False
print(d["status"])
PY
