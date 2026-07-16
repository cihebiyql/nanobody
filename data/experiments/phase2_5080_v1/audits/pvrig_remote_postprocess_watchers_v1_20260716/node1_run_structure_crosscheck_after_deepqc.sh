#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE=/data/qlyu/projects/pvrig_pre_shortlist100_deepqc_v1_20260716
MONOMER_ROOT=/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715
ROOT=/data/qlyu/projects/pvrig_pre_shortlist100_structure_crosscheck_v1_20260716
PYTHON=/data/qlyu/software/envs/vhh-eval/bin/python
MAX_WAIT_SECONDS=${MAX_WAIT_SECONDS:-86400}
EXPECTED_SCRIPT_SHA=ed08ed936b4c6a80d86175f72293a35973760065d76240c0a01132297b02589c
EXPECTED_SHORTLIST_SHA=2701d5ab43677b3e302924ddc3454639fce1a8a9f8d6102713d6df24156173b5
EXPECTED_MONOMER_MANIFEST_SHA=ebc07ccb7ba36dee84714fbf27911e82b560d1cc184a8d45e054d8577f1d70f0
cd "$ROOT"

mkdir -p status outputs logs
exec 9>status/crosscheck_watcher.lock
flock -n 9 || exit 75

write_status() {
  local state=$1 reason=$2
  STATE_VALUE=$state REASON_VALUE=$reason $PYTHON - <<'PY'
import json, os
from datetime import datetime, timezone
from pathlib import Path
Path("status/crosscheck_status.json").write_text(json.dumps({
    "status":os.environ["STATE_VALUE"], "reason":os.environ["REASON_VALUE"],
    "updated_at":datetime.now(timezone.utc).isoformat(),
},indent=2,sort_keys=True)+"\n")
PY
}

fail() {
  local rc=$? line=$1
  write_status FAILED "crosscheck_error_line=$line rc=$rc"
  exit "$rc"
}
trap 'fail $LINENO' ERR

[[ $(sha256sum audit_pre_shortlist100_igfold_nbb2.py | awk '{print $1}') == "$EXPECTED_SCRIPT_SHA" ]]
[[ $(sha256sum inputs/pre_shortlist100.tsv | awk '{print $1}') == "$EXPECTED_SHORTLIST_SHA" ]]
[[ $(sha256sum inputs/v4d_candidate_monomers_manifest.tsv | awk '{print $1}') == "$EXPECTED_MONOMER_MANIFEST_SHA" ]]

if [[ -s outputs/structure_crosscheck_receipt.json &&
      -s outputs/igfold_nbb2_crosscheck_delivery_v1.tar.gz &&
      -s outputs/igfold_nbb2_crosscheck_delivery_v1.tar.gz.sha256 ]] &&
   sha256sum -c outputs/igfold_nbb2_crosscheck_delivery_v1.tar.gz.sha256 >/dev/null 2>&1 &&
   $PYTHON - <<'PY'
import json
from pathlib import Path
p=Path("outputs/structure_crosscheck_receipt.json")
raise SystemExit(0 if json.loads(p.read_text()).get("status")=="PASS_100_OF_100_STRUCTURE_CROSSCHECK_COMPUTED" else 1)
PY
then
  write_status COMPLETE "existing hash-bound structure crosscheck delivery verified"
  exit 0
fi

started=$(date +%s)
write_status WAITING_DEEPQC "waiting for terminal Top100 TNP/IgFold run"
while true; do
  state=$($PYTHON - "$SOURCE/status/deepqc_status.json" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); print(json.loads(p.read_text()).get("status","MISSING") if p.is_file() else "MISSING")
PY
)
  case "$state" in
    COMPLETE) break ;;
    FAILED) write_status BLOCKED "deepqc_failed"; exit 2 ;;
  esac
  if (( $(date +%s) - started > MAX_WAIT_SECONDS )); then
    write_status BLOCKED "deepqc_wait_timeout_seconds=$MAX_WAIT_SECONDS"
    exit 3
  fi
  sleep 300
done

write_status RUNNING "auditing IgFold against hash-frozen NBB2 monomers"
$PYTHON audit_pre_shortlist100_igfold_nbb2.py \
  --pre-shortlist inputs/pre_shortlist100.tsv \
  --monomer-manifest inputs/v4d_candidate_monomers_manifest.tsv \
  --monomer-root "$MONOMER_ROOT" \
  --igfold-root "$SOURCE/runs" \
  --outdir outputs \
  --terminal >logs/crosscheck.stdout.log 2>logs/crosscheck.stderr.log

$PYTHON - <<'PY'
import hashlib,json
from pathlib import Path
root=Path(".")
summary=json.loads((root/"outputs/igfold_nbb2_crosscheck.json").read_text())
if summary.get("status")!="PASS" or summary.get("candidate_count")!=100 or summary.get("pass_count")!=100:
    raise SystemExit(f"crosscheck closure failed: {summary}")
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
receipt={
  "schema_version":"pvrig_pre_shortlist100_igfold_nbb2_delivery_v1",
  "status":"PASS_100_OF_100_STRUCTURE_CROSSCHECK_COMPUTED",
  "crosscheck_tsv_sha256":sha(root/"outputs/igfold_nbb2_crosscheck.tsv"),
  "crosscheck_json_sha256":sha(root/"outputs/igfold_nbb2_crosscheck.json"),
  "script_sha256":sha(root/"audit_pre_shortlist100_igfold_nbb2.py"),
  "shortlist_sha256":sha(root/"inputs/pre_shortlist100.tsv"),
  "monomer_manifest_sha256":sha(root/"inputs/v4d_candidate_monomers_manifest.tsv"),
  "claim_boundary":"Monomer structure agreement only; not PVRIG binding, affinity, docking, or blocking.",
}
(root/"outputs/structure_crosscheck_receipt.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
PY

sha256sum outputs/igfold_nbb2_crosscheck.tsv outputs/igfold_nbb2_crosscheck.json \
  outputs/structure_crosscheck_receipt.json >outputs/SHA256SUMS
tar -czf outputs/igfold_nbb2_crosscheck_delivery_v1.tar.gz \
  outputs/igfold_nbb2_crosscheck.tsv outputs/igfold_nbb2_crosscheck.json \
  outputs/structure_crosscheck_receipt.json outputs/SHA256SUMS
sha256sum outputs/igfold_nbb2_crosscheck_delivery_v1.tar.gz \
  >outputs/igfold_nbb2_crosscheck_delivery_v1.tar.gz.sha256
write_status COMPLETE "100-candidate hash-frozen IgFold/NBB2 crosscheck delivery ready"
