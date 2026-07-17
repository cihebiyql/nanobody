#!/usr/bin/env bash
set -euo pipefail

# This launcher is intentionally inert with the implementation-freeze candidate.
# A separate reviewed launch-authorized freeze is mandatory before any source
# result path can be opened.

ROOT=${PVRIG_V4D_DEV1_ROOT:-/data/qlyu/projects/pvrig_v4_d_dev1_open258_v1_20260717}
SOURCE=/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715
PYTHON=${PVRIG_V4D_DEV1_PYTHON:-/data/qlyu/anaconda3/envs/haddock3/bin/python}
LAUNCH_FREEZE=${PVRIG_V4D_DEV1_LAUNCH_FREEZE:-$ROOT/governance/phase2_v4_d_dev1_open258_launch_authorized_freeze.json}
PREREG=$ROOT/governance/phase2_v4_d_dev1_open258_preregistration.json
BUILDER=$ROOT/scripts/prepare_phase2_v4_d_dev1_open258.py
V1_HELPER=$ROOT/scripts/prepare_phase2_v4_d_open_teacher.py
STATUS=$ROOT/status/dev1_release_status.json
LOG_DIR=$ROOT/logs
OUTPUT_DIR=$ROOT/release
GENERIC_PRIOR_EXPECTED=$ROOT/governance/v4d_dev1_fullqc290_label_free_generic_prior_v1.csv
GENERIC_PRIOR_EXPECTED_SHA256=21b4c6a38056d6777de5b5efbfcd5887b45098c637cab61489072d1e6e7783cd

[[ "$ROOT" == /data/qlyu/projects/pvrig_v4_d_dev1_open258_v1_20260717 ]] || {
  echo "noncanonical DEV1 root: $ROOT" >&2
  exit 2
}

mkdir -p "$ROOT/status" "$LOG_DIR"

write_status() {
  local state=$1 reason=$2
  STATUS_VALUE=$state REASON_VALUE=$reason STATUS_PATH=$STATUS "$PYTHON" - <<'PY'
import json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path
path=Path(os.environ["STATUS_PATH"])
payload={
 "schema_version":"phase2_v4_d_dev1_node23_launcher_v1",
 "status":os.environ["STATUS_VALUE"],
 "reason":os.environ["REASON_VALUE"],
 "updated_at":datetime.now(timezone.utc).isoformat(),
 "development_only":True,
 "source_evaluator_status":"FAIL",
 "formal_v4_f_unlock_eligible":False,
 "raw_test32_job_files_opened":0,
 "test32_metric_values_read":0,
}
fd,name=tempfile.mkstemp(prefix=f".{path.name}.",dir=path.parent)
with os.fdopen(fd,"w",encoding="utf-8") as handle:
 json.dump(payload,handle,indent=2,sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
os.replace(name,path)
PY
}

trap 'rc=$?; write_status FAILED_DEV1_BUILD "launcher_error_line=$LINENO rc=$rc" || true; exit "$rc"' ERR

exec 9>"$ROOT/status/dev1_build.lock"
flock -n 9 || { write_status BLOCKED_ALREADY_RUNNING "dev1_build_lock_held"; exit 3; }

# Validate authorization and byte-level closure before inspecting source result paths.
runtime_tmp=$(mktemp "$ROOT/status/.runtime-inputs.XXXXXX")
if ! "$PYTHON" - "$ROOT" "$LAUNCH_FREEZE" "$PREREG" "$BUILDER" "$V1_HELPER" "$0" >"$runtime_tmp" <<'PY'
import hashlib, json, os, stat, sys
from pathlib import Path
root,freeze_path,prereg,builder,helper,launcher=map(Path,sys.argv[1:])
def digest(path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def regular(path,label):
 st=path.lstat()
 if not stat.S_ISREG(st.st_mode): raise SystemExit(f"not_regular:{label}:{path}")
for p,label in [(freeze_path,"launch_freeze"),(prereg,"prereg"),(builder,"builder"),(helper,"v1_helper"),(launcher,"launcher")]: regular(p,label)
freeze=json.loads(freeze_path.read_text())
if freeze.get("status")!="FROZEN_FOR_DEV1_REMOTE_EXECUTION" or freeze.get("remote_execution_authorized") is not True:
 raise SystemExit("launch_authorization_missing")
if freeze.get("test32_raw_job_files_opened")!=0 or freeze.get("formal_v4_f_unlock_eligible") is not False:
 raise SystemExit("launch_freeze_boundary_invalid")
files=freeze.get("files") or {}
expected={"preregistration":prereg,"builder":builder,"v1_formula_helper":helper,"node23_launcher":launcher}
for key,path in expected.items():
 if (files.get(key) or {}).get("sha256")!=digest(path): raise SystemExit(f"launch_freeze_hash_mismatch:{key}")
if digest(prereg)!="ee2c1076b0fd58b5bcb991f7646321c6fd03204746ff926f2d93940fec5ffe55":
 raise SystemExit("prereg_hash_mismatch")
runtime=freeze.get("runtime_inputs") or {}
prior=Path(str(runtime.get("generic_prior_path","")))
prior_sha=str(runtime.get("generic_prior_sha256",""))
expected_prior=root/"governance/v4d_dev1_fullqc290_label_free_generic_prior_v1.csv"
if prior!=expected_prior: raise SystemExit("generic_prior_noncanonical_path")
if prior_sha!="21b4c6a38056d6777de5b5efbfcd5887b45098c637cab61489072d1e6e7783cd":
 raise SystemExit("generic_prior_unreviewed_hash")
regular(prior,"generic_prior")
if digest(prior)!=prior_sha: raise SystemExit("generic_prior_hash_mismatch")
print(prior)
print(prior_sha)
PY
then
  rm -f "$runtime_tmp"
  write_status BLOCKED_LAUNCH_AUTHORIZATION "launch freeze or hash closure invalid"
  exit 5
fi
mapfile -t runtime <"$runtime_tmp"
rm -f "$runtime_tmp"
[[ ${#runtime[@]} -eq 2 ]] || { write_status BLOCKED_RUNTIME_INPUTS "runtime input closure invalid"; exit 6; }

GENERIC_PRIOR=${runtime[0]}
GENERIC_PRIOR_SHA=${runtime[1]}
[[ "$GENERIC_PRIOR" == "$GENERIC_PRIOR_EXPECTED" && "$GENERIC_PRIOR_SHA" == "$GENERIC_PRIOR_EXPECTED_SHA256" ]] || {
  write_status BLOCKED_RUNTIME_INPUTS "generic prior path/hash is not the reviewed label-free extract"
  exit 6
}

# Zero-work preflight: the versioned release path must not contain prior science outputs.
if [[ -e "$OUTPUT_DIR" || -L "$OUTPUT_DIR" ]]; then
  write_status BLOCKED_NONEMPTY_OUTPUT "versioned output path already exists"
  exit 4
fi

write_status BUILDING_DEV1_OPEN258 "launch-authorized DEV-only extraction; test32 remains sealed"
"$PYTHON" "$BUILDER" \
  --preregistration "$PREREG" \
  --v1-formula-helper "$V1_HELPER" \
  --split-manifest "$SOURCE/inputs/fullqc290_split_manifest.tsv" \
  --job-manifest "$SOURCE/manifests/docking_jobs.tsv" \
  --job-results "$SOURCE/reports/job_results.tsv" \
  --pose-scores "$SOURCE/reports/pose_scores.tsv" \
  --protocol-core-lock "$SOURCE/PROTOCOL_CORE_LOCK.json" \
  --protocol-lock "$SOURCE/PROTOCOL_LOCK.json" \
  --stability-spec "$SOURCE/config/evaluator_stability_gate.json" \
  --results-root "$SOURCE/results" \
  --evaluator "$SOURCE/reports/EVALUATOR_STABLE.json" \
  --generic-prior "$GENERIC_PRIOR" \
  --expected-generic-prior-sha256 "$GENERIC_PRIOR_SHA" \
  --output-dir "$OUTPUT_DIR" \
  >"$LOG_DIR/dev1_builder.stdout.log" 2>"$LOG_DIR/dev1_builder.stderr.log"

test -s "$OUTPUT_DIR/v4d_dev1_open258_delivery_v1.tar.gz"
test -s "$OUTPUT_DIR/v4d_dev1_open258_delivery_v1.tar.gz.sha256"
write_status DEV1_RELEASE_READY_TEST32_SEALED "development-only bundle ready; formal V4-F remains locked"
