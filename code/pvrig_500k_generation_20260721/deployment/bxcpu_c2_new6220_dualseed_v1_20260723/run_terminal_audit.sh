#!/usr/bin/env bash
set -euo pipefail
umask 027

DEPLOY_ROOT="${PVRIG_C2_NEW_DEPLOY_ROOT:-$HOME/.local/share/bxcpu_c2_new6220_dualseed_v1_20260723}"
PUBLISH_ROOT="${PVRIG_C2_NEW_PUBLISH_ROOT:-$HOME/pvrig_c2_new6220_dualreceptor_2seed_v1_20260723_bxcpu_results}"
PYTHON="$HOME/.local/opt/haddock3-2025.11.0/bin/python"
OUTPUT="$PUBLISH_ROOT/reports/TECHNICAL_COMPLETION.json"
EXPECTED_ANCHORS_SHA256="${PVRIG_C2_NEW_ANCHORS_SHA256:?frozen anchors SHA256 is required}"

[[ $(sha256sum "$DEPLOY_ROOT/FROZEN_INPUT_ANCHORS.json" | awk '{print $1}') == "$EXPECTED_ANCHORS_SHA256" ]]
"$PYTHON" - "$DEPLOY_ROOT/FROZEN_INPUT_ANCHORS.json" "$DEPLOY_ROOT" <<'PY_DEPLOY_GATE'
import hashlib,json,pathlib,sys
anchors=json.load(open(sys.argv[1])); deploy=pathlib.Path(sys.argv[2])
def sha(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
assert anchors["status"]=="FROZEN_READY_FOR_DEPENDENT_SUBMISSION"
for relative, expected in anchors["deployment_file_sha256"].items():
    assert sha(deploy/relative)==expected, relative
PY_DEPLOY_GATE

"$PYTHON" "$DEPLOY_ROOT/technical_audit_c2_new6220.py" \
    --manifest-4220 "$DEPLOY_ROOT/inputs/c2_new4220_docking_jobs.tsv" \
    --manifest-2000 "$DEPLOY_ROOT/inputs/c2_new2000_docking_jobs.tsv" \
    --publish-root "$PUBLISH_ROOT" \
    --sha-4220 "${PVRIG_C2_NEW_4220_MANIFEST_SHA256:?4220 manifest SHA256 is required}" \
    --sha-2000 "${PVRIG_C2_NEW_2000_MANIFEST_SHA256:?2000 manifest SHA256 is required}" \
    --output "$OUTPUT"

"$PYTHON" - "$OUTPUT" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
assert d["status"]=="COMPLETE_WITH_TECHNICAL_NA"
assert d["expected_jobs"] == 24880
assert d["technical_failure_semantics"] == "NA_not_negative"
print(d["status"])
PY
